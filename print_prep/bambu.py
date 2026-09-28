"""print_prep.bambu —— Bambu Studio 命令行封装：导出工程 3MF、无头试切、图形界面打开。

命令行调用方式改编自作者早期私有研究代码 `manufacturing_kit/engine/print_waveab_v0/kitlib/slice_p1s.py::
slice_geometry_3mf`（自有代码）：`--datadir` 隔离一份干净的 CLI 配置目录、
`--load-settings machine.json;process.json` + `--load-filaments ...` 加载展开好
的预设、`--orient 0 --arrange 0 --ensure-on-bed` 关掉 CLI 自己的排布逻辑（几何
3MF 里已经带了我们自己算好的摆盘变换）。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Sequence

from . import profiles
from .messages import render

# check 用的默认超时取 SPEC.md §3.6 给的 1500 秒；export 阶段的两次尝试（不带
# --slice / 带 --slice 0 兜底）都可能触发真正的切片计算，用同一个超时以防超大
# 网格的兜底路径被过早掐断。
DEFAULT_TIMEOUT_S = 1500.0


class BambuCliError(RuntimeError):
    """Bambu Studio 命令行调用失败/超时/找不到可执行文件，属于环境错误（退出码 3）。"""


def _run(cmd: list[str], log_path: Path, timeout_s: float) -> dict[str, Any]:
    """跑一次子进程，stdout/stderr 都落到 `log_path`，返回执行记录（不抛异常，
    超时也只是记 `timed_out=True`，由调用方决定怎么处理）。"""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()
    started = datetime.now(timezone.utc).isoformat()
    timed_out = False
    returncode: Optional[int] = None
    with open(log_path, "w") as log:
        try:
            proc = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT, timeout=timeout_s)
            returncode = proc.returncode
        except subprocess.TimeoutExpired:
            timed_out = True
    return {
        "command": cmd,
        "returncode": returncode,
        "timed_out": timed_out,
        "started_utc": started,
        "ended_utc": datetime.now(timezone.utc).isoformat(),
        "wall_seconds": round(time.perf_counter() - t0, 2),
        "log": str(log_path),
    }


def export_project_3mf(
    geometry_3mf: Path,
    out_dir: Path,
    machine_json: Path,
    process_json: Path,
    filament_jsons: Sequence[Path],
    project_name: str,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    binary: Optional[Path] = None,
    datadir: Optional[Path] = None,
) -> dict[str, Any]:
    """SPEC.md §3.5 第 2 步：先按规格不带 `--slice` 试导出真正的 Bambu 工程
    3MF；如果命令行返回非 0 或没生成文件，改成带 `--slice 0` 重试一次，并把这
    个事实记进返回值的 `used_slice_fallback`（调用方据此写 `export.notes`）。"""
    binary = binary or profiles.bambu_binary()
    if not binary.exists():
        raise BambuCliError(render("bambu.studio_not_found", binary=binary))
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    datadir = datadir or (out_dir / "bambu-cli-data")
    project_path = out_dir / f"{project_name}.project.3mf"
    settings_path = out_dir / f"{project_name}.effective_settings.json"

    def build_cmd(with_slice: bool) -> list[str]:
        cmd = [
            str(binary),
            "--datadir",
            str(datadir),
            "--load-settings",
            f"{machine_json};{process_json}",
            "--load-filaments",
            ";".join(str(p) for p in filament_jsons),
            "--orient",
            "0",
            "--arrange",
            "0",
            "--ensure-on-bed",
        ]
        if with_slice:
            cmd += ["--slice", "0"]
        cmd += [
            "--outputdir",
            str(out_dir),
            "--export-3mf",
            project_path.name,
            "--export-settings",
            str(settings_path),
            str(geometry_3mf),
        ]
        return cmd

    log_path = out_dir / f"{project_name}.export.log"
    record = _run(build_cmd(False), log_path, timeout_s)
    used_slice_fallback = False
    if record["returncode"] != 0 or not project_path.exists():
        used_slice_fallback = True
        log_path2 = out_dir / f"{project_name}.export.slicefallback.log"
        record = _run(build_cmd(True), log_path2, timeout_s)

    ok = record["returncode"] == 0 and project_path.exists()
    return {
        "ok": ok,
        "project_3mf": str(project_path) if project_path.exists() else None,
        "used_slice_fallback": used_slice_fallback,
        "execution": record,
    }


def check_slice(
    geometry_3mf: Path,
    out_dir: Path,
    machine_json: Path,
    process_json: Path,
    filament_jsons: Sequence[Path],
    name: str,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    binary: Optional[Path] = None,
    datadir: Optional[Path] = None,
) -> dict[str, Any]:
    """无头 `--slice 0` 试切，读 `result.json` 拿克重/时间/警告；失败不抛异常，
    如实把 `grams`/`seconds` 留 `None`、`error` 填错误串，由调用方决定退出码。"""
    binary = binary or profiles.bambu_binary()
    if not binary.exists():
        raise BambuCliError(render("bambu.studio_not_found", binary=binary))
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    datadir = datadir or (out_dir / "bambu-cli-data")
    sliced_name = f"{name}.sliced.3mf"
    result_json = out_dir / "result.json"
    # `check` 的输出目录按盘固定（`DIR/check/plate_NN/`），重跑时如果这一轮的
    # 子进程在写 result.json 之前就失败/超时，读到的会是上一轮遗留的旧
    # result.json——先删掉，保证"没写出新结果"能被如实识别成失败而不是冒充
    # 上一轮的克重/时间。
    if result_json.exists():
        result_json.unlink()
    cmd = [
        str(binary),
        "--datadir",
        str(datadir),
        "--load-settings",
        f"{machine_json};{process_json}",
        "--load-filaments",
        ";".join(str(p) for p in filament_jsons),
        "--orient",
        "0",
        "--arrange",
        "0",
        "--ensure-on-bed",
        "--slice",
        "0",
        "--outputdir",
        str(out_dir),
        "--export-3mf",
        sliced_name,
        "--export-settings",
        str(out_dir / f"{name}.effective_settings.json"),
        str(geometry_3mf),
    ]
    log_path = out_dir / f"{name}.slice.log"
    record = _run(cmd, log_path, timeout_s)

    grams = seconds = None
    slice_warnings: list[str] = []
    error_string = None
    if result_json.exists():
        try:
            res = json.loads(result_json.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            error_string = render("bambu.result_json_parse_failed", error=exc)
            res = {}
        error_string = error_string or res.get("error_string")
        plates = res.get("sliced_plates") or []
        if plates:
            grams = round(sum(f.get("total_used_g", 0) for f in plates[0].get("filaments", [])), 2)
            seconds = plates[0].get("total_predication")
            slice_warnings = plates[0].get("warnings") or []
    elif record["timed_out"]:
        error_string = render("bambu.slice_timeout", timeout_s=timeout_s)
    else:
        error_string = error_string or render("bambu.result_json_missing", returncode=record["returncode"])

    ok = record["returncode"] == 0 and grams is not None
    return {
        "ok": ok,
        "grams": grams,
        "seconds": seconds,
        "warnings": slice_warnings,
        "returncode": record["returncode"],
        "wall_seconds": record["wall_seconds"],
        "error": error_string,
        "execution": record,
    }


def _launch_command(app: Path, project_3mf: Path) -> list[str]:
    """Best-effort argv for opening `project_3mf` in Bambu Studio's GUI.

    macOS always goes through `open -a` — an `.app` bundle is not itself
    directly executable. Windows/Linux invoke the discovered binary with the
    project file as its sole argument (mirrors how the mac `open -a` call
    hands the file to the app); if no binary was found (`app` does not
    resolve to an existing file — e.g. a Flatpak install with no
    `BAMBU_STUDIO_APP`/`BAMBU_STUDIO_PATH` set), fall back to the OS's own
    "open with default app" mechanism so the `.3mf` file association still
    works. `"os.startfile"` is a preview sentinel, not a real argv[0]; see
    `open_project`.
    """
    if sys.platform == "darwin":
        return ["open", "-a", str(app), str(project_3mf)]
    if app.is_file():
        return [str(app), str(project_3mf)]
    if sys.platform == "win32":
        return ["os.startfile", str(project_3mf)]
    return ["xdg-open", str(project_3mf)]


# Real values from `_winapi`/`subprocess` on Windows; looked up via `getattr`
# with the documented literal as fallback so this module still imports (and
# `sys.platform` can still be monkeypatched to "win32" in tests) when the
# interpreter running the tests is not actually Windows, where `subprocess`
# never defines these names at all.
_WIN_DETACHED_PROCESS = getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
_WIN_CREATE_NEW_PROCESS_GROUP = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)


def open_project(app: Path, project_3mf: Path, dry_run: bool = False) -> dict[str, Any]:
    """Open `project_3mf` in Bambu Studio; `dry_run=True` only echoes the
    command that would run, without launching anything.

    macOS's `open -a` returns as soon as it has asked `launchd` to start the
    app — it was already effectively async, so that branch stays exactly
    `subprocess.run(cmd, check=False)`. On win32/linux `cmd` is the Bambu
    Studio binary itself; a blocking `subprocess.run()` there would sit and
    wait for the user to close the GUI before returning, holding the server's
    write lock the whole time. Launch it detached instead and return
    immediately, same as the darwin path effectively already does.
    """
    cmd = _launch_command(app, project_3mf)
    if dry_run:
        return {"command": cmd, "executed": False}
    if cmd[0] == "os.startfile":
        os.startfile(str(project_3mf))
    elif sys.platform == "darwin":
        subprocess.run(cmd, check=False)
    elif sys.platform == "win32":
        subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=_WIN_DETACHED_PROCESS | _WIN_CREATE_NEW_PROCESS_GROUP,
        )
    else:
        subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    return {"command": cmd, "executed": True}


def _default_process_name() -> str:
    """darwin 上进程名固定是 app 包内可执行文件的名字 `BambuStudio`，与安装
    位置无关；win32/linux 上进程名就是实际发现到的可执行文件文件名
    （`bambu-studio.exe` / `bambu-studio`），随 `BAMBU_STUDIO_APP`/
    `BAMBU_STUDIO_PATH` 变化，不能硬编码。"""
    if sys.platform == "darwin":
        return "BambuStudio"
    return Path(profiles.bambu_binary()).name


def is_process_running(name: Optional[str] = None) -> Optional[bool]:
    """检查一次进程是否已经在跑（不轮询），给 `open` 命令在真正打开之前拍一次
    "之前是不是已经开着"的快照用——如果 Bambu Studio 本来就开着，打开之后再查
    进程恒为真，`launched` 这个字段就分不清"我们真的拉起了一个新进程"还是
    "它压根没关过"。Windows 用 `tasklist`，POSIX 用 `pgrep -x`；平台自带的进程
    列举工具本身不可用时返回 `None`（未知），调用方必须把它当"不确定"处理，
    不能当成"没在跑"。这个函数在 `--dry-run` 分支也允许调用——它只是查询状态，
    不启动任何东西。省略 `name` 时按 `_default_process_name()` 推导，不再固定
    写死 "BambuStudio"（win32/linux 上真实进程名不是这个）。"""
    name = name or _default_process_name()
    if sys.platform == "win32":
        exe_name = name if name.lower().endswith(".exe") else f"{name}.exe"
        try:
            result = subprocess.run(
                ["tasklist", "/FI", f"IMAGENAME eq {exe_name}", "/NH"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
            )
        except OSError:
            return None
        return exe_name.lower() in result.stdout.lower()
    try:
        result = subprocess.run(["pgrep", "-x", name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        return None
    return result.returncode == 0


def wait_for_process(name: Optional[str] = None, timeout_s: float = 20.0, poll_s: float = 0.5) -> Optional[bool]:
    """轮询确认进程已经起来；命令行侧无法确认文件是否真的已经在界面里载入完成
    （SPEC.md §3.7：`loaded` 只能报 `"unverified"`）。某一次检查就返回 `None`
    （平台工具不可用）时立即停止轮询并原样报 `None`，不再空转到超时。省略
    `name` 的默认值解析交给 `is_process_running()`，两处只有一份真源。"""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        state = is_process_running(name)
        if state is None:
            return None
        if state:
            return True
        time.sleep(poll_s)
    return False
