"""studio.core.print_state —— print-preparation domain logic for a job directory.

Everything here is a plain function over explicit inputs (a `job_dir`, plus
whatever in-memory bits — `selection`, `busy`, `sent`, cached values, ...
— the caller already holds): no HTTP objects, no threading locks, and no
imports from `studio.shell` or `studio.adapters` (enforced by
`tests/test_layering.py`).

`studio.shell.server.StudioBackend` owns concurrency (the `rev`/`busy`
bookkeeping, the write lock, the `_center_cache`) and calls into this module
for the two things that are actually "print prep": turning a JSON request
body into a `print_prep.cli.cmd_*` call, and assembling the `/api/state`
response out of `print_prep.job` data. Anything that needs a lock (recording
a successful send, caching part-centre lookups) stays a thin wrapper on
`StudioBackend` that calls the pure functions here.
"""

from __future__ import annotations

import argparse
import json
import os
import urllib.parse
from pathlib import Path
from typing import Any, Callable, Optional

from print_prep import arrange as arrange_mod
from print_prep import cli
from print_prep import job
from print_prep import mesh_io
from print_prep import profiles
from print_prep import shape_table
from studio.i18n import render

# --------------------------------------------------------------------- input validation


def validate_choice(value: Any, choices: tuple[str, ...], field_name: str) -> None:
    """给可以绕开 argparse `choices=` 校验的入参（JSON body 直接构造 Namespace）
    补一道同等的枚举检查，非法值报 `UserError`（400）而不是让底层某个内部
    `ValueError` 漏成未预期的 500。"""
    if value is not None and value not in choices:
        raise cli.UserError(
            render("print_state.unknown_choice", field_name=field_name, value=repr(value)), code="bad_arguments"
        )


def orient_set_to_list(d: dict[str, Any]) -> list[str]:
    """`{零件名: [x,y,z]}` -> `cmd_orient` 的 `--set NAME=x,y,z` 字符串列表。"""
    out: list[str] = []
    for name, vec in d.items():
        if not isinstance(vec, (list, tuple)) or len(vec) != 3:
            raise cli.UserError(
                render("print_state.orient_set_vector_length", entry=f"{name}={vec!r}"), code="bad_set_option"
            )
        try:
            nums = [float(c) for c in vec]
        except (TypeError, ValueError) as exc:
            raise cli.UserError(
                render("print_state.orient_set_vector_not_numeric", entry=f"{name}={vec!r}"), code="bad_set_option"
            ) from exc
        out.append(f"{name}=" + ",".join(str(n) for n in nums))
    return out


def dict_to_kv_list(d: dict[str, Any]) -> list[str]:
    """`{k: v}` -> `cmd_export` 的 `--set key=value` 字符串列表。"""
    return [f"{k}={v}" for k, v in d.items()]


def to_float(value: Any, field_name: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise cli.UserError(
            render("print_state.not_a_number", field_name=field_name, value=repr(value)), code="bad_arguments"
        ) from exc


def to_int(value: Any, field_name: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise cli.UserError(
            render("print_state.not_an_integer", field_name=field_name, value=repr(value)), code="bad_arguments"
        ) from exc


def file_version(path: Optional[str]) -> int:
    """零件网格地址的版本号 = 文件自身的修改时间。重新载入（不管走 load 还是 prepare）
    都会重写 parts/*.stl，地址随之变化；没重写就不变，前端按地址缓存、不会重复下载。"""
    try:
        return os.stat(path).st_mtime_ns if path else 0
    except OSError:
        return 0


# --------------------------------------------------------------------- write-operation wrappers
#
# 每个函数都是某个 `cli.cmd_*` 的薄封装：把 JSON body 拼成 `argparse.Namespace`
# 再调用。副作用（记 `sent`/`_delivered`、置 `busy`/`rev`/history）一律留在
# `StudioBackend` 里——这些函数本身不持有、也不修改任何实例状态。


def api_load(job_dir: Path, body: dict[str, Any]) -> dict[str, Any]:
    files = body.get("files") or []
    ns = argparse.Namespace(
        job=str(job_dir),
        files=[str(f) for f in files],
        printer=body.get("printer"),
        scale=body.get("scale"),
        target_max_mm=body.get("target_max_mm"),
        merge=bool(body.get("merge", False)),
    )
    return cli.cmd_inspect(ns)


def api_orient(job_dir: Path, body: dict[str, Any]) -> dict[str, Any]:
    shape = body.get("shape")
    strategy = body.get("strategy")
    validate_choice(shape, shape_table.VALID_LABELS, "shape")
    validate_choice(strategy, ("auto", "flat", "support", "upright"), "strategy")
    set_list = orient_set_to_list(body.get("set") or {})
    angle_deg = body.get("angle_deg")
    angle_deg = None if angle_deg is None else to_float(angle_deg, "angle_deg")
    # Range-checking `angle_deg` (5..85 degrees) happens once, in `cli.cmd_orient`
    # (`cli._resolve_angle_deg`), so the CLI and this API path share one message.
    ns = argparse.Namespace(job=str(job_dir), strategy=strategy, shape=shape, set=set_list, angle_deg=angle_deg)
    return cli.cmd_orient(ns)


def api_arrange(job_dir: Path, body: dict[str, Any]) -> dict[str, Any]:
    mode = body.get("mode") or cli.DEFAULT_MODE
    gap = body.get("gap")
    gap = cli.DEFAULT_GAP_MM if gap is None else to_float(gap, "gap")
    validate_choice(mode, arrange_mod.VALID_MODES, "mode")
    ns = argparse.Namespace(job=str(job_dir), mode=mode, gap=gap)
    return cli.cmd_arrange(ns)


def api_export(job_dir: Path, body: dict[str, Any]) -> dict[str, Any]:
    shape = body.get("shape")
    validate_choice(shape, shape_table.VALID_LABELS, "shape")
    set_list = dict_to_kv_list(body.get("set") or {})
    ns = argparse.Namespace(
        job=str(job_dir),
        process=body.get("process"),
        filament=body.get("filament"),
        shape=shape,
        set=set_list,
        no_project=bool(body.get("no_project", False)),
    )
    return cli.cmd_export(ns)


def api_check(job_dir: Path, body: dict[str, Any]) -> dict[str, Any]:
    plate = body.get("plate")
    ns = argparse.Namespace(job=str(job_dir), plate=to_int(plate, "plate") if plate is not None else None)
    return cli.cmd_check(ns)


def api_send(job_dir: Path, body: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """`cmd_open` 的薄封装。返回 `(result, dry_run)`——记 `sent`/`_delivered`
    需要一把锁，留给调用方（`StudioBackend.api_send`）在拿到结果后自己做。"""
    plate = body.get("plate")
    dry_run = bool(body.get("dry_run", False))
    ns = argparse.Namespace(
        job=str(job_dir),
        plate=to_int(plate, "plate") if plate is not None else None,
        all=bool(body.get("all", False)),
        dry_run=dry_run,
    )
    return cli.cmd_open(ns), dry_run


def api_prepare(job_dir: Path, body: dict[str, Any]) -> dict[str, Any]:
    shape = body.get("shape")
    strategy = body.get("strategy")
    mode = body.get("mode") or cli.DEFAULT_MODE
    gap = body.get("gap")
    gap = cli.DEFAULT_GAP_MM if gap is None else to_float(gap, "gap")
    validate_choice(shape, shape_table.VALID_LABELS, "shape")
    validate_choice(strategy, ("auto", "flat", "support", "upright"), "strategy")
    validate_choice(mode, arrange_mod.VALID_MODES, "mode")
    ns = argparse.Namespace(
        job=str(job_dir),
        files=[str(f) for f in (body.get("files") or [])],
        printer=body.get("printer"),
        scale=body.get("scale"),
        target_max_mm=body.get("target_max_mm"),
        merge=bool(body.get("merge", False)),
        strategy=strategy,
        shape=shape,
        orient_set=orient_set_to_list(body.get("orient_set") or {}),
        mode=mode,
        gap=gap,
        process=body.get("process"),
        filament=body.get("filament"),
        export_set=dict_to_kv_list(body.get("export_set") or {}),
        no_project=bool(body.get("no_project", False)),
        check=bool(body.get("check", False)),
        open=bool(body.get("send", False)),
    )
    # `cmd_prepare` 的 open 步骤（SPEC.md §3.8/print_prep/cli.py `cmd_prepare`）恒以
    # `dry_run=False` 调 `cmd_open`；`StudioBackend.api_prepare` 在拿到 `steps` 之后
    # 自己找 `step == "open"` 那一条去记 `sent`（同样是"要锁就留给调用方"）。
    return cli.cmd_prepare(ns)


# --------------------------------------------------------------------- /api/state assembly


def resolve_printer_info(printer_name: Optional[str]) -> Optional[dict[str, Any]]:
    if not printer_name:
        return None
    try:
        printers = profiles.list_printers()
    except profiles.ProfileError:
        printers = []
    by_name = {p["name"]: p for p in printers}
    resolved = by_name.get(printer_name)
    if not resolved:
        return {"name": printer_name, "bed_mm": None, "exclude_areas": None, "margin_mm": cli.DEFAULT_MARGIN_MM}
    return {
        "name": resolved["name"],
        "bed_mm": resolved["bed_mm"],
        "exclude_areas": resolved["exclude_areas"],
        "margin_mm": cli.DEFAULT_MARGIN_MM,
    }


def compute_source_centers(inspect_parts: list[dict[str, Any]]) -> dict[str, Optional[list[float]]]:
    """逐个载入零件 STL、算 AABB 中心（源系，orient 之前）。纯函数、不缓存——
    调用方（`StudioBackend._source_centers`）按 STL 路径签名做缓存，命中就
    不会跑到这里，未命中才付一次全量载入的代价。"""
    centers: dict[str, Optional[list[float]]] = {}
    for p in inspect_parts:
        try:
            mesh = mesh_io.load_part_stl(p["stl_path"])
            c = (mesh.bounds[0] + mesh.bounds[1]) / 2.0
            centers[p["name"]] = [round(float(x), 6) for x in c]
        except Exception:  # noqa: BLE001 —— 缺文件等异常不该打断整个 /api/state
            centers[p["name"]] = None
    return centers


def build_export_out(job_dir: Path, export_data: dict[str, Any]) -> dict[str, Any]:
    overrides: dict[str, Any] = {}
    provenance_path = job_dir / "profiles" / "provenance.json"
    if provenance_path.is_file():
        try:
            overrides = json.loads(provenance_path.read_text()).get("process_overrides", {})
        except (OSError, json.JSONDecodeError):
            overrides = {}
    plates_out = []
    for p in export_data.get("plates", []):
        plates_out.append(
            {
                "index": p.get("index"),
                "project_3mf": p.get("project_3mf"),
                "geometry_3mf": p.get("geometry_3mf"),
                "bambu_moved_objects": p.get("bambu_moved_objects"),
                "unmatched_parts": p.get("unmatched_parts", []),
                "used_slice_fallback": p.get("used_slice_fallback"),
            }
        )
    return {
        "process_preset": export_data.get("process_preset"),
        "filament_preset": export_data.get("filament_preset"),
        "overrides": overrides,
        "plates": plates_out,
        "notes": export_data.get("notes", []),
    }


def build_check_out(check_data: dict[str, Any]) -> dict[str, Any]:
    # `cmd_check` 的每条记录里盘号字段叫 "plate"，但 SPEC.md §7 的 /api/state
    # 契约（以及 studio/web/panel.js 的读法）用的是 "index"——这里做一次改名。
    plates_out = []
    for r in check_data.get("plates", []):
        plates_out.append(
            {
                "index": r.get("plate"),
                "grams": r.get("grams"),
                "seconds": r.get("seconds"),
                "warnings": r.get("warnings", []),
                "returncode": r.get("returncode"),
            }
        )
    return {"plates": plates_out}


def compute_options(
    orient_data: Optional[dict[str, Any]],
    arrange_data: Optional[dict[str, Any]],
    export_data: Optional[dict[str, Any]],
) -> dict[str, Any]:
    """现算而不是另存一份内存状态：`job.invalidate_from()` 已经把"重新
    orient 会清掉 export"这类失效级联处理好了，直接读 `job.json` 就自动拿到
    "最近一次各写操作用到的"那个值，且重启进程也不会跟 job.json 失配。"""
    shape = (export_data or {}).get("shape") or (orient_data or {}).get("shape") or cli.DEFAULT_SHAPE
    strategy = (orient_data or {}).get("strategy") or cli.DEFAULT_STRATEGY
    mode = (arrange_data or {}).get("mode") or cli.DEFAULT_MODE
    gap = (arrange_data or {}).get("gap_mm")
    if gap is None:
        gap = cli.DEFAULT_GAP_MM
    return {"shape": shape, "strategy": strategy, "mode": mode, "gap": gap}


def build_state(
    job_dir: Path,
    *,
    data: dict[str, Any],
    readiness: dict[str, Any],
    rev: int,
    busy: Optional[dict[str, Any]],
    last_error: Optional[dict[str, Any]],
    sent: Optional[dict[str, Any]],
    inspect_rev: int,
    selection: dict[str, Any],
    history_list: list[Any],
    step_actors: dict[str, Any],
    stale: dict[str, Any],
    workbench: dict[str, Any],
    recipe: Optional[dict[str, Any]],
    evaluation_focus: Any,
    source_centers: Callable[[list[dict[str, Any]]], dict[str, Optional[list[float]]]],
) -> dict[str, Any]:
    """`GET /api/state` 的响应体。`data`（已 `job.load_job()` 过一次）和
    `readiness`（`studio.core.history.compute_readiness(data, ...)`）由调用方
    传入而不是这里现算——`StudioBackend.build_state()` 装配 `recipe` 字段时也
    要用同一份 `data`/`readiness`，避免同一次请求里读到 job.json 的两个不同
    快照。`source_centers` 是一个回调（通常是 `StudioBackend._source_centers`
    的绑定方法），只在真的有 `inspect_data` 时才会被调用——缓存与加锁全在
    回调那一侧，这个函数本身不持有任何状态。"""
    inspect_data = data.get("inspect")
    orient_data = data.get("orient")
    arrange_data = data.get("arrange")
    export_data = data.get("export")
    check_data = data.get("check")

    steps = {name: (name in data) for name in job.STEP_ORDER}

    printer_out: Optional[dict[str, Any]] = None
    parts_out: list[dict[str, Any]] = []
    warnings: list[str] = []

    if inspect_data:
        printer_out = resolve_printer_info(inspect_data.get("printer"))
        warnings = list(inspect_data.get("warnings") or [])
        centers = source_centers(inspect_data["parts"])
        orient_by_name = (orient_data or {}).get("parts") or {}
        for p in inspect_data["parts"]:
            parts_out.append(
                {
                    "name": p["name"],
                    "faces": p["faces"],
                    "vertices": p["vertices"],
                    "extents_mm": p["extents_mm"],
                    "volume_cm3": p["volume_cm3"],
                    "watertight": p["watertight"],
                    "components": p["components"],
                    "fits_bed": p["fits_bed"],
                    "suggested_scale": p["suggested_scale"],
                    "source_center_mm": centers.get(p["name"]),
                    "stl_url": f"/api/part/{urllib.parse.quote(p['name'], safe='')}.stl?v={file_version(p.get('stl_path'))}",
                    "orient": orient_by_name.get(p["name"]),
                }
            )

    plates_out = arrange_data.get("plates") if arrange_data else None
    export_out = build_export_out(job_dir, export_data) if export_data else None
    check_out = build_check_out(check_data) if check_data else None
    options = compute_options(orient_data, arrange_data, export_data)

    return {
        "ok": True,
        "rev": rev,
        "print_submitted": False,
        "busy": busy,
        "last_error": last_error,
        "job": str(job_dir.resolve()),
        "printer": printer_out,
        "options": options,
        "steps": steps,
        "warnings": warnings,
        "parts": parts_out,
        "plates": plates_out,
        "export": export_out,
        "check": check_out,
        "sent": sent,
        "selection": selection,
        "step_actors": step_actors,
        "stale": stale,
        "readiness": readiness,
        "history": history_list,
        "workbench": workbench,
        "recipe": recipe,
        "evaluation_focus": evaluation_focus,
        "print_sources": [p["stl_path"] for p in (inspect_data or {}).get("parts", [])],
        # Additive: the job revision at which the model currently loaded into
        # `inspect_data` was last (re)loaded — see `StudioBackend.mark_inspect_rev`.
        "inspect_rev": inspect_rev,
    }
