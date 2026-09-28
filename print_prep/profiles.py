"""print_prep.profiles —— Bambu Studio 系统预设的索引、inherits/include 展开与床参数解析。

做法改编自作者早期私有研究代码 `manufacturing_kit/engine/print_waveab_v0/kitlib/slice_p1s.py::_index/resolve_profiles`
（自有代码）：预设文件之间用 `inherits`（单个父）与 `include`（多个混入）互相引用，
展开顺序是"父链先展开、include 依次覆盖、自身字段优先级最高"。
"""

from __future__ import annotations

import json
import math
import os
import shutil
import sys
from pathlib import Path
from typing import Any, Optional

from .messages import render

# macOS default: the .app bundle (not directly executable; `bambu.open_project`
# / `bambu_binary()` reach inside it). Windows/Linux defaults resolve straight
# to an executable — see `_default_app_root()`.
DEFAULT_APP = "/Applications/BambuStudio.app"


class ProfileError(RuntimeError):
    """预设目录缺失/损坏/找不到指定预设，属于环境错误（退出码 3）。"""


# Overhang-angle threshold used by `print_prep.orient` (`orient.DEFAULT_ANGLE_DEG`
# carries the same value as the ultimate fallback). This is our own conservative
# default, not a number Bambu Studio's machine presets publish per printer — the
# vendor JSON has no such field, so every printer currently gets the same 30
# degrees until we have real per-printer overhang data to differentiate on.
DEFAULT_OVERHANG_ANGLE_DEG = 30.0


def _windows_app_candidates() -> list[Path]:
    program_files = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
    candidates = [program_files / "Bambu Studio" / "bambu-studio.exe"]
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        candidates.append(Path(local_appdata) / "Programs" / "Bambu Studio" / "bambu-studio.exe")
    return candidates


def _default_app_root() -> Path:
    """Platform default install location, used when `BAMBU_STUDIO_APP` is unset.

    macOS returns the `.app` bundle (`DEFAULT_APP`). Windows returns the first
    existing `bambu-studio.exe` under Program Files / the per-user Programs
    directory, or the Program Files path as a best guess if neither exists yet.
    Linux returns whatever `bambu-studio` resolves to on `PATH`, else
    `~/.local/bin/bambu-studio`. None of these cover a Flatpak install, which
    has no single executable path on disk — point `BAMBU_STUDIO_APP` (or
    `BAMBU_STUDIO_PATH`) at a one-line wrapper script that runs
    `flatpak run com.bambulab.BambuStudio "$@"` instead.
    """
    if sys.platform == "darwin":
        return Path(DEFAULT_APP)
    if sys.platform == "win32":
        candidates = _windows_app_candidates()
        return next((c for c in candidates if c.is_file()), candidates[0])
    found = shutil.which("bambu-studio")
    return Path(found) if found else Path.home() / ".local" / "bin" / "bambu-studio"


def app_root() -> Path:
    """`BAMBU_STUDIO_APP` 环境变量，缺省按平台走 `_default_app_root()`。"""
    configured = os.environ.get("BAMBU_STUDIO_APP")
    return Path(configured) if configured else _default_app_root()


def bambu_binary() -> Path:
    """`BAMBU_STUDIO_PATH` 环境变量，缺省从 `app_root()` 推出可执行文件路径：
    macOS 是 app 包内的可执行文件；Windows/Linux 上 `app_root()` 本身已经指向
    可执行文件，原样返回。"""
    configured = os.environ.get("BAMBU_STUDIO_PATH")
    if configured:
        return Path(configured)
    root = app_root()
    if sys.platform == "darwin":
        return root / "Contents/MacOS/BambuStudio"
    return root


def profile_root() -> Path:
    """`MFG_BAMBU_PROFILE_ROOT` 环境变量，缺省按平台走：macOS 是
    `<app>/Contents/Resources/profiles/BBL`（app 包自带资源）；Windows 是
    `%APPDATA%\\BambuStudio\\system\\BBL`；Linux 是
    `~/.config/BambuStudio/system/BBL`。后两者未经过全部发行版验证，装错了直接
    用这个环境变量指到实际目录。找不到目录时 `_index()` 会抛出报出具体路径的
    `ProfileError`，不是裸的 `FileNotFoundError`。"""
    configured = os.environ.get("MFG_BAMBU_PROFILE_ROOT")
    if configured:
        return Path(configured)
    if sys.platform == "darwin":
        return app_root() / "Contents/Resources/profiles/BBL"
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        base = Path(appdata) if appdata else app_root().parent
        return base / "BambuStudio" / "system" / "BBL"
    return Path.home() / ".config" / "BambuStudio" / "system" / "BBL"


def _index(root: Path) -> dict[str, Path]:
    """遍历 machine/process/filament 三个子目录，按文件名（不含扩展名）与预设自身的
    `name` 字段两条路建立索引，供 `resolve()` 按名字查文件。"""
    idx: dict[str, Path] = {}
    for kind in ("machine", "process", "filament"):
        kind_dir = root / kind
        if not kind_dir.is_dir():
            raise ProfileError(render("profiles.dir_missing", dir=kind_dir))
        for p in sorted(kind_dir.rglob("*.json")):
            try:
                data = json.loads(p.read_text())
            except (OSError, json.JSONDecodeError) as exc:
                raise ProfileError(render("profiles.parse_failed", path=p, error=exc)) from exc
            idx.setdefault(p.stem, p)
            name = data.get("name")
            if name:
                idx.setdefault(name, p)
    return idx


def resolve(name: str, idx: dict[str, Path], chain: tuple[str, ...] = ()) -> dict[str, Any]:
    """展开 `inherits`（单继承）与 `include`（多混入）链，返回合并后的字段字典；
    自身字段优先级最高，`include` 按列表顺序后者覆盖前者。额外带一个内部字段
    `_source_path` 指回这份预设自己的文件（供 provenance 记 sha256 用）。"""
    if name not in idx:
        raise ProfileError(render("profiles.not_found", name=name))
    if name in chain:
        raise ProfileError(render("profiles.inherits_cycle", chain=chain + (name,)))
    path = idx[name]
    data = json.loads(path.read_text())
    merged: dict[str, Any] = {}
    if data.get("inherits"):
        merged.update(resolve(data["inherits"], idx, chain + (name,)))
    for inc in data.get("include", []):
        merged.update(resolve(inc, idx, chain + (name,)))
    merged.update({k: v for k, v in data.items() if k not in ("inherits", "include")})
    merged["_source_path"] = str(path)
    return merged


def _parse_points(tokens) -> list[tuple[float, float]]:
    """把 `"18x28"` 这类角点串解析成 (x, y) 浮点数对列表。"""
    pts = []
    for tok in tokens or []:
        x_str, y_str = tok.split("x")
        pts.append((float(x_str), float(y_str)))
    return pts


def _bbox_groups(points: list[tuple[float, float]], group_size: int = 4) -> list[list[float]]:
    """把点列表按 group_size 个一组切开，每组取轴对齐包围盒 [x0,y0,x1,y1]。

    Bambu 的 `bed_exclude_area` 把多个互不相邻的矩形排除区拼成一条长点串，每个
    矩形固定 4 个角点；按 4 一组分块取 bbox 就能还原出各自独立的矩形（P1S 0.4
    nozzle 只有一个矩形，分块数=1）。
    """
    groups = []
    for i in range(0, len(points), group_size):
        chunk = points[i : i + group_size]
        if not chunk:
            continue
        xs = [p[0] for p in chunk]
        ys = [p[1] for p in chunk]
        groups.append([min(xs), min(ys), max(xs), max(ys)])
    return groups


def bed_params(machine: dict[str, Any]) -> dict[str, Any]:
    """从展开后的 machine 预设取床尺寸（[x,y,z] 毫米）与避让区矩形列表。"""
    area_pts = _parse_points(machine.get("printable_area"))
    xs = [p[0] for p in area_pts]
    ys = [p[1] for p in area_pts]
    bed_x = (max(xs) - min(xs)) if area_pts else 0.0
    bed_y = (max(ys) - min(ys)) if area_pts else 0.0
    bed_z = float(machine.get("printable_height", 0))
    exclude_pts = _parse_points(machine.get("bed_exclude_area"))
    exclude_areas = _bbox_groups(exclude_pts)
    return {"bed_mm": [bed_x, bed_y, bed_z], "exclude_areas": exclude_areas}


def list_printers(root: Optional[Path] = None, filter_str: Optional[str] = None) -> list[dict[str, Any]]:
    """列出 `machine/` 下所有 `instantiation == "true"` 的机器预设（展开 inherits 后）。"""
    root = root or profile_root()
    idx = _index(root)
    machine_dir = root / "machine"
    seen_paths: set[Path] = set()
    printers: dict[str, dict[str, Any]] = {}
    for p in sorted(machine_dir.rglob("*.json")):
        if p in seen_paths:
            continue
        seen_paths.add(p)
        try:
            raw = json.loads(p.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        name = raw.get("name")
        if not name:
            continue
        resolved = resolve(name, idx)
        if str(resolved.get("instantiation")) != "true":
            continue
        if filter_str and filter_str.lower() not in name.lower():
            continue
        bed = bed_params(resolved)
        nozzle_list = resolved.get("nozzle_diameter") or []
        nozzle_mm = float(nozzle_list[0]) if nozzle_list else None
        default_filament_list = resolved.get("default_filament_profile") or []
        printers[name] = {
            "name": name,
            "printer_model": resolved.get("printer_model"),
            "nozzle_mm": nozzle_mm,
            "bed_mm": bed["bed_mm"],
            "exclude_areas": bed["exclude_areas"],
            "default_process": resolved.get("default_print_profile"),
            "default_filament": default_filament_list[0] if default_filament_list else None,
            # Own conservative default, not read from the vendor preset; see
            # `DEFAULT_OVERHANG_ANGLE_DEG` above.
            "overhang_angle_deg": DEFAULT_OVERHANG_ANGLE_DEG,
        }
    return sorted(printers.values(), key=lambda e: e["name"])


def find_process_by_layer_height(
    root: Path, machine_name: str, layer_height_mm: float, tol: float = 1e-6
) -> Optional[str]:
    """在 `process/` 里找 `compatible_printers` 含 `machine_name`、`layer_height`
    等于 `layer_height_mm` 的系统预设；找不到返回 None（调用方回退到机器的
    `default_print_profile` 并写 warning）。

    同一层高经常有两个系统预设并存（比如 X1C 家族 0.16mm 档同时有 "Optimal" 与
    "High Quality"），实测两者的 `setting_id`（形如 "GP004"）分出明显的两代——
    数字小的那批（GP0xx）是各层高最早收录、被机器 `default_print_profile` 直接
    引用的那个（比如 0.16mm 档的 `default_print_profile` 恰好指向 GP003
    "Optimal" 而不是 GP103 "High Quality"），数字大的是后加的变体档。没有更权威
    的字段可用时，取 `setting_id` 数字最小的那个作为该层高的"标准档"。
    """
    idx = _index(root)
    process_dir = root / "process"
    candidates: list[tuple[int, str]] = []
    for p in sorted(process_dir.rglob("*.json")):
        try:
            raw = json.loads(p.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        name = raw.get("name")
        if not name:
            continue
        resolved = resolve(name, idx)
        if str(resolved.get("instantiation")) != "true":
            continue
        compatible = resolved.get("compatible_printers") or []
        if machine_name not in compatible:
            continue
        lh = resolved.get("layer_height")
        if lh is None or abs(float(lh) - layer_height_mm) >= tol:
            continue
        setting_id = str(resolved.get("setting_id") or "")
        digits = "".join(ch for ch in setting_id if ch.isdigit())
        rank = int(digits) if digits else 10**9
        candidates.append((rank, name))
    if not candidates:
        return None
    candidates.sort(key=lambda t: (t[0], t[1]))
    return candidates[0][1]


def suggest_scale(ratio: float) -> float:
    """把一个"可以再放大多少倍仍放得下"的比例向下取整到 3 位小数（保证结果依然
    放得下，不会因为四舍五入卡在边界上）。"""
    return math.floor(ratio * 1000) / 1000.0
