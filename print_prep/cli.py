"""print_prep.cli —— argparse 命令行 + 统一的 JSON 输出/退出码约定（SPEC.md §3）。

通用契约：每个命令 stdout 只输出一个 JSON 对象，给人看的进度写 stderr；退出码
0=成功，2=用户侧错误，3=环境错误，1=未预期异常；非 0 时 stdout 仍是
`{"ok": false, "error": {"code","message"}}`；成功时顶层恒有
`ok/command/job/print_submitted`。
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Optional

import numpy as np

from . import arrange as arrange_mod
from . import bambu
from . import export3mf
from . import job
from . import mesh_io
from . import orient
from . import profiles
from . import shape_table
from .messages import render

DEFAULT_PRINTER = "Bambu Lab P1S 0.4 nozzle"
DEFAULT_STRATEGY = "auto"
DEFAULT_SHAPE = "generic"
DEFAULT_MODE = "auto"
DEFAULT_GAP_MM = 4.0
DEFAULT_MARGIN_MM = 5.0


class CliError(Exception):
    """统一的命令行错误基类；`exit_code` 决定进程退出码，`payload` 会原样合并
    进最终 JSON 的顶层（不只是塞进 `error` 里），方便像"改用 auto 需要几盘"
    这种结构化信息透传给调用方。"""

    exit_code = 1

    def __init__(self, message: str, code: str = "error", payload: Optional[dict[str, Any]] = None):
        super().__init__(message)
        self.code = code
        self.payload = payload or {}


class UserError(CliError):
    """退出码 2：参数错、放不下、文件不存在、网格不可用。"""

    exit_code = 2


class EnvError(CliError):
    """退出码 3：环境错误（找不到 Bambu Studio / 预设目录、命令行调用失败）。"""

    exit_code = 3


def _strip_internal_keys(d: dict[str, Any]) -> dict[str, Any]:
    """去掉 `profiles.resolve()` 塞进展开字典里的自有内部键（下划线开头，比如
    `_source_path`）——这些不是 Bambu Studio 预设 schema 的一部分，写盘前必须
    过滤掉（SPEC.md §3.5）。"""
    return {k: v for k, v in d.items() if not k.startswith("_")}


def _parse_set_kv(entries: list[str]) -> dict[str, str]:
    """把 `["key=value", ...]` 解析成 dict（export 的 `--set`，改工艺预设字段）。"""
    out: dict[str, str] = {}
    for entry in entries:
        if "=" not in entry:
            raise UserError(render("cli.set_kv_bad_format", entry=entry), code="bad_set_option")
        key, value = entry.split("=", 1)
        out[key] = value
    return out


def _parse_set_vec3(entries: list[str]) -> dict[str, tuple[float, float, float]]:
    """把 `["NAME=x,y,z", ...]` 解析成 dict（orient 的 `--set`，手工指定 print_up）。"""
    out: dict[str, tuple[float, float, float]] = {}
    for entry in entries:
        if "=" not in entry:
            raise UserError(render("cli.set_vec3_bad_format", entry=entry), code="bad_set_option")
        name, vec_str = entry.split("=", 1)
        pieces = vec_str.split(",")
        if len(pieces) != 3:
            raise UserError(render("cli.set_vec3_wrong_arity", entry=entry), code="bad_set_option")
        try:
            vec = (float(pieces[0]), float(pieces[1]), float(pieces[2]))
        except ValueError as exc:
            raise UserError(render("cli.set_vec3_not_number", entry=entry), code="bad_set_option") from exc
        norm = math.sqrt(sum(c * c for c in vec))
        if norm <= 1e-9:
            raise UserError(render("cli.set_vec3_zero_vector", entry=entry), code="zero_vector")
        out[name] = vec
    return out


# ---------------------------------------------------------------------------
# 3.1 printers
# ---------------------------------------------------------------------------


def cmd_printers(args: argparse.Namespace) -> dict[str, Any]:
    try:
        printers = profiles.list_printers(filter_str=args.filter)
    except profiles.ProfileError as exc:
        raise EnvError(str(exc)) from exc
    return {"ok": True, "command": "printers", "job": None, "print_submitted": False, "printers": printers}


# ---------------------------------------------------------------------------
# 3.2 inspect
# ---------------------------------------------------------------------------


def cmd_inspect(args: argparse.Namespace) -> dict[str, Any]:
    job_dir = Path(args.job)
    job_dir.mkdir(parents=True, exist_ok=True)

    if args.scale is not None and args.target_max_mm is not None:
        raise UserError(render("cli.scale_and_target_conflict"), code="conflicting_options")
    if args.scale is not None and args.scale <= 0:
        raise UserError(render("cli.bad_scale", scale=args.scale), code="bad_scale")
    if args.target_max_mm is not None and args.target_max_mm <= 0:
        raise UserError(render("cli.bad_target_max_mm", target_max_mm=args.target_max_mm), code="bad_target_max_mm")

    printer_name = args.printer or DEFAULT_PRINTER
    try:
        printers = profiles.list_printers()
    except profiles.ProfileError as exc:
        raise EnvError(str(exc)) from exc
    printer_by_name = {p["name"]: p for p in printers}
    if printer_name not in printer_by_name:
        raise UserError(render("cli.unknown_printer", printer=printer_name), code="unknown_printer")
    bed_mm = printer_by_name[printer_name]["bed_mm"]

    files = [Path(f) for f in args.files]
    for f in files:
        if not f.exists():
            raise UserError(render("cli.file_not_found", file=f), code="file_not_found")

    print(f"loading {len(files)} file(s)...", file=sys.stderr)
    seen_names: dict[str, int] = {}
    raw_parts: list[dict[str, Any]] = []
    for f in files:
        try:
            loaded = mesh_io.load_raw_parts(f, merge=bool(args.merge))
        except mesh_io.MeshLoadError as exc:
            raise UserError(str(exc), code="mesh_load_error") from exc
        source_sha = mesh_io.sha256_file(f)
        for node_name, mesh in loaded:
            final_name = mesh_io.dedupe_name(node_name, seen_names)
            raw_parts.append({"name": final_name, "mesh": mesh, "source": str(f), "source_sha256": source_sha})
            print(f"  part {final_name!r} <- {f.name}", file=sys.stderr)

    if not raw_parts:
        raise UserError(render("cli.no_parts"), code="no_parts")

    if args.scale is not None:
        scale = float(args.scale)
    elif args.target_max_mm is not None:
        # 全体零件的合并包围盒（各件保持在源文件里的位置，即装配坐标系）的最长
        # 边缩到 H；不是"逐件取最长边里的最大值"（那样量的是单件尺寸，不是
        # 装配整体尺寸，SPEC.md §3.2）。
        mins = np.array([p["mesh"].bounds[0] for p in raw_parts])
        maxs = np.array([p["mesh"].bounds[1] for p in raw_parts])
        combined_extent = maxs.max(axis=0) - mins.min(axis=0)
        overall_max = float(np.max(combined_extent))
        if overall_max <= 0:
            raise UserError(render("cli.degenerate_extent"), code="degenerate_extent")
        scale = float(args.target_max_mm) / overall_max
    else:
        scale = 1.0

    avail_w = bed_mm[0] - 2 * DEFAULT_MARGIN_MM
    avail_h = bed_mm[1] - 2 * DEFAULT_MARGIN_MM
    avail_z = bed_mm[2] - DEFAULT_MARGIN_MM

    parts_dir = job_dir / "parts"
    parts_out: list[dict[str, Any]] = []
    warnings: list[str] = []
    for p in raw_parts:
        mesh = p["mesh"]
        if scale != 1.0:
            mesh = mesh.copy()
            mesh.apply_scale(scale)
        print(f"measuring {p['name']!r} ({len(mesh.faces)} faces)...", file=sys.stderr)
        measured = mesh_io.measure_part(mesh)
        fits, suggested = mesh_io.fits_any_axis(mesh, avail_w, avail_h, avail_z)
        stl_path = parts_dir / f"{p['name']}.stl"
        mesh_io.save_part_stl(mesh, stl_path)
        part_warnings = mesh_io.warnings_for_part(p["name"], measured)
        warnings.extend(part_warnings)
        parts_out.append(
            {
                "name": p["name"],
                "source": p["source"],
                "source_sha256": p["source_sha256"],
                "faces": measured["faces"],
                "vertices": measured["vertices"],
                "extents_mm": measured["extents_mm"],
                "volume_cm3": measured["volume_cm3"],
                "watertight": measured["watertight"],
                "components": measured["components"],
                "fits_bed": fits,
                "suggested_scale": suggested,
                "stl_path": str(stl_path),
            }
        )

    data = job.load_job(job_dir)
    data["inspect"] = {
        "printer": printer_name,
        "scale_applied": scale,
        "merge": bool(args.merge),
        "parts": parts_out,
        "warnings": warnings,
    }
    job.invalidate_from(data, "orient")
    job.save_job(job_dir, data)

    return {
        "ok": True,
        "command": "inspect",
        "job": str(job_dir.resolve()),
        "print_submitted": False,
        "printer": printer_name,
        "scale_applied": scale,
        "parts": parts_out,
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# 3.3 orient
# ---------------------------------------------------------------------------


ANGLE_DEG_MIN = 5.0
ANGLE_DEG_MAX = 85.0


def _resolve_angle_deg(explicit: Optional[float], printer_name: Optional[str]) -> float:
    """Resolution order for the overhang-angle threshold: explicit `--angle-deg`
    (CLI) / `angle_deg` (API body) > the printer profile's `overhang_angle_deg`
    (`profiles.list_printers()`, currently `DEFAULT_OVERHANG_ANGLE_DEG` for every
    printer) > `orient.DEFAULT_ANGLE_DEG`. Only the explicit override is range-
    checked (5..85 degrees, our own bound — not from any SPEC or vendor doc): the
    printer-profile and hardcoded fallback values are internally produced and
    already known to be in range."""
    if explicit is not None:
        value = float(explicit)
        if not (ANGLE_DEG_MIN <= value <= ANGLE_DEG_MAX):
            raise UserError(
                render("cli.bad_angle_deg", angle_deg=value, min=ANGLE_DEG_MIN, max=ANGLE_DEG_MAX),
                code="bad_angle_deg",
            )
        return value
    if printer_name:
        try:
            printers = profiles.list_printers()
        except profiles.ProfileError:
            printers = []
        profile = {p["name"]: p for p in printers}.get(printer_name)
        if profile is not None and profile.get("overhang_angle_deg") is not None:
            return float(profile["overhang_angle_deg"])
    return orient.DEFAULT_ANGLE_DEG


def cmd_orient(args: argparse.Namespace) -> dict[str, Any]:
    job_dir = Path(args.job)
    data = job.load_job(job_dir)
    if "inspect" not in data:
        raise UserError(render("cli.missing_step_orient"), code="missing_step")
    inspect_data = data["inspect"]

    shape_label = shape_table.normalize_label(args.shape)
    strategy_arg = args.strategy or "auto"
    if strategy_arg not in ("auto", "flat", "support", "upright"):
        raise UserError(render("cli.bad_strategy", strategy=strategy_arg), code="bad_strategy")
    manual = _parse_set_vec3(args.set or [])
    angle_deg = _resolve_angle_deg(getattr(args, "angle_deg", None), inspect_data.get("printer"))

    parts_meta = {p["name"]: p for p in inspect_data["parts"]}
    unknown = [n for n in manual if n not in parts_meta]
    if unknown:
        raise UserError(render("cli.unknown_part_in_set", unknown=unknown), code="unknown_part")

    results: dict[str, Any] = {}
    for name, meta in parts_meta.items():
        print(f"orienting {name!r}...", file=sys.stderr)
        mesh = mesh_io.load_part_stl(meta["stl_path"])
        if name in manual:
            # 手工指定也要带稳定性告警（SPEC.md 3.3），统一走 orient.manual_result
            results[name] = orient.manual_result(mesh, orient.unit(np.array(manual[name])), angle_deg=angle_deg)
        else:
            results[name] = orient.choose_orientation(mesh, strategy_arg, shape_label=shape_label, angle_deg=angle_deg)

    # `angle_deg` is additive: it records which overhang-angle threshold this
    # orient run actually used, alongside `shape`/`strategy`.
    data["orient"] = {"shape": shape_label, "strategy": strategy_arg, "angle_deg": angle_deg, "parts": results}
    job.invalidate_from(data, "arrange")
    job.save_job(job_dir, data)

    return {
        "ok": True,
        "command": "orient",
        "job": str(job_dir.resolve()),
        "print_submitted": False,
        "shape": shape_label,
        "strategy": strategy_arg,
        "angle_deg": angle_deg,
        "parts": results,
    }


# ---------------------------------------------------------------------------
# 3.4 arrange
# ---------------------------------------------------------------------------


def cmd_arrange(args: argparse.Namespace) -> dict[str, Any]:
    job_dir = Path(args.job)
    data = job.load_job(job_dir)
    if "orient" not in data:
        raise UserError(render("cli.missing_step_arrange"), code="missing_step")
    if args.gap < 0:
        raise UserError(render("cli.bad_gap", gap=args.gap), code="bad_gap")
    inspect_data = data["inspect"]
    orient_parts = data["orient"]["parts"]
    printer_name = inspect_data["printer"]

    try:
        root = profiles.profile_root()
        idx = profiles._index(root)
        machine = profiles.resolve(printer_name, idx)
    except profiles.ProfileError as exc:
        raise EnvError(str(exc)) from exc
    bed = profiles.bed_params(machine)

    parts = []
    for p in inspect_data["parts"]:
        name = p["name"]
        mesh = mesh_io.load_part_stl(p["stl_path"])
        parts.append({"name": name, "mesh": mesh, "print_up": orient_parts[name]["print_up"]})

    print(f"arranging {len(parts)} part(s), mode={args.mode!r}...", file=sys.stderr)
    try:
        plates = arrange_mod.arrange(
            parts,
            bed_mm=bed["bed_mm"],
            margin_mm=DEFAULT_MARGIN_MM,
            exclude_areas=bed["exclude_areas"],
            mode=args.mode,
            gap_mm=args.gap,
        )
    except arrange_mod.SinglePlateOverflowError as exc:
        raise UserError(
            str(exc), code="single_plate_overflow", payload={"needed_plates_with_auto": exc.needed_plates}
        ) from exc
    except arrange_mod.PartTooLargeError as exc:
        raise UserError(
            str(exc), code="part_too_large", payload={"part": exc.name, "suggested_scale": exc.suggested_scale}
        ) from exc

    data["arrange"] = {"mode": args.mode, "gap_mm": args.gap, "plates": plates}
    job.invalidate_from(data, "export")
    job.save_job(job_dir, data)

    return {
        "ok": True,
        "command": "arrange",
        "job": str(job_dir.resolve()),
        "print_submitted": False,
        "mode": args.mode,
        "plates": plates,
    }


# ---------------------------------------------------------------------------
# 3.5 export
# ---------------------------------------------------------------------------


def cmd_export(args: argparse.Namespace) -> dict[str, Any]:
    job_dir = Path(args.job)
    data = job.load_job(job_dir)
    if "arrange" not in data:
        raise UserError(render("cli.missing_step_export"), code="missing_step")
    inspect_data = data["inspect"]
    printer_name = inspect_data["printer"]

    shape_label = shape_table.normalize_label(args.shape or (data.get("orient") or {}).get("shape") or "generic")
    shape_entry = shape_table.lookup(shape_label)

    root = profiles.profile_root()
    try:
        idx = profiles._index(root)
        machine = profiles.resolve(printer_name, idx)
    except profiles.ProfileError as exc:
        raise EnvError(str(exc)) from exc

    used_fallback_default = False
    process_name = args.process
    if not process_name:
        process_name = profiles.find_process_by_layer_height(root, printer_name, shape_entry["layer_height_mm"])
        if not process_name:
            process_name = machine.get("default_print_profile")
            used_fallback_default = True
    try:
        process = profiles.resolve(process_name, idx)
    except profiles.ProfileError as exc:
        raise EnvError(str(exc)) from exc

    filament_name = args.filament or (machine.get("default_filament_profile") or [None])[0]
    if not filament_name:
        raise EnvError(render("cli.missing_default_filament"), code="missing_default_filament")
    try:
        filament = profiles.resolve(filament_name, idx)
    except profiles.ProfileError as exc:
        raise EnvError(str(exc)) from exc

    overrides = dict(shape_entry["process_overrides"])
    overrides.update(_parse_set_kv(args.set or []))
    process_final = dict(process)
    process_final.update(overrides)

    profiles_dir = job_dir / "profiles"
    profiles_dir.mkdir(parents=True, exist_ok=True)
    machine_path = profiles_dir / "machine.json"
    process_path = profiles_dir / "process.json"
    filament_path = profiles_dir / "filament-0.json"
    # `profiles.resolve()` 往展开后的字典里塞了 `_source_path` 这个我们自己的
    # 内部键（供下面算 provenance 的 sha256 用）；写盘给 Bambu Studio 读的
    # machine.json/process.json/filament-0.json 里不该带这种下划线自有键，来源
    # 信息只留在 provenance.json 里（SPEC.md §3.5）。
    machine_path.write_text(json.dumps(_strip_internal_keys(machine), indent=1, ensure_ascii=False))
    process_path.write_text(json.dumps(_strip_internal_keys(process_final), indent=1, ensure_ascii=False))
    filament_path.write_text(json.dumps(_strip_internal_keys(filament), indent=1, ensure_ascii=False))

    provenance = {
        "sources_sha256": {
            str(machine["_source_path"]): job.sha256_file(Path(machine["_source_path"])),
            str(process["_source_path"]): job.sha256_file(Path(process["_source_path"])),
            str(filament["_source_path"]): job.sha256_file(Path(filament["_source_path"])),
        },
        "machine_preset": printer_name,
        "process_preset": process_name,
        "filament_preset": filament_name,
        "process_overrides": overrides,
        "machine_gcode_modified": False,
    }
    if used_fallback_default:
        provenance["warning"] = render(
            "cli.fallback_process_warning", printer=printer_name, layer_height_mm=shape_entry["layer_height_mm"]
        )
    (profiles_dir / "provenance.json").write_text(json.dumps(provenance, indent=1, ensure_ascii=False))

    parts_by_name = {p["name"]: p for p in inspect_data["parts"]}
    # Output paths are reused. Once writing starts, an earlier successful export
    # cannot remain marked ready if this attempt fails its readback gate.
    job.invalidate_from(data, "export")
    job.save_job(job_dir, data)
    plates_out: list[dict[str, Any]] = []
    notes: list[str] = []
    for plate in data["arrange"]["plates"]:
        idx_plate = plate["index"]
        plate_dir = job_dir / "plates"
        plate_dir.mkdir(parents=True, exist_ok=True)
        geom_path = plate_dir / f"plate_{idx_plate:02d}.geometry.3mf"
        print(f"writing geometry 3mf for plate {idx_plate}...", file=sys.stderr)
        meshes_by_name = {}
        for pl in plate["placements"]:
            name = pl["part"]
            meshes_by_name[name] = mesh_io.load_part_stl(parts_by_name[name]["stl_path"])
        export3mf.write_geometry_3mf(geom_path, meshes_by_name, plate["placements"])
        readback = export3mf.read_back_geometry_3mf(geom_path, meshes_by_name, plate["placements"], tol_mm=0.01)
        if not readback["pass"]:
            raise CliError(
                render("cli.readback_failed", plate=idx_plate, max_error_mm=readback["max_error_mm"]),
                code="readback_failed",
            )

        plate_record: dict[str, Any] = {"index": idx_plate, "geometry_3mf": str(geom_path), "readback": readback}
        if not args.no_project:
            print(f"calling Bambu Studio CLI for plate {idx_plate}...", file=sys.stderr)
            try:
                project_info = bambu.export_project_3mf(
                    geom_path,
                    plate_dir,
                    machine_path,
                    process_path,
                    [filament_path],
                    project_name=f"plate_{idx_plate:02d}",
                )
            except bambu.BambuCliError as exc:
                raise EnvError(str(exc)) from exc
            if not project_info["ok"]:
                raise EnvError(
                    render("cli.bambu_export_failed", plate=idx_plate),
                    code="bambu_export_failed",
                    payload={"execution": project_info["execution"]},
                )
            if project_info["used_slice_fallback"]:
                notes.append(render("cli.slice_fallback_note", plate=idx_plate))
            plate_record["project_3mf"] = project_info["project_3mf"]
            plate_record["used_slice_fallback"] = project_info["used_slice_fallback"]
            moved = export3mf.compare_project_transforms(Path(project_info["project_3mf"]), plate["placements"])
            plate_record["bambu_moved_objects"] = moved["bambu_moved_objects"]
            plate_record["transform_diff"] = moved["diff"]
            # export3mf.py 由另一位实现者同步在改，返回字典会新增 unmatched_parts/
            # used_positional_fallback 两个键；用 .get 保证不管谁先落地都不炸。
            plate_record["unmatched_parts"] = moved.get("unmatched_parts", [])
            plate_record["used_positional_fallback"] = moved.get("used_positional_fallback")
            topology = export3mf.compare_project_geometry(Path(project_info["project_3mf"]), meshes_by_name)
            plate_record["geometry_readback"] = topology
            if not topology["pass"]:
                raise CliError(
                    render("cli.project_geometry_changed", plate=idx_plate),
                    code="project_geometry_changed",
                    payload={"geometry_readback": topology, "geometry_3mf": str(geom_path)},
                )
        plates_out.append(plate_record)

    export_record = {
        "printer": printer_name,
        "shape": shape_label,
        "process_preset": process_name,
        "filament_preset": filament_name,
        "no_project": bool(args.no_project),
        "plates": plates_out,
        "notes": notes,
    }
    data["export"] = export_record
    job.invalidate_from(data, "check")
    job.save_job(job_dir, data)

    return {
        "ok": True,
        "command": "export",
        "job": str(job_dir.resolve()),
        "print_submitted": False,
        "plates": plates_out,
        "notes": notes,
    }


# ---------------------------------------------------------------------------
# 3.6 check
# ---------------------------------------------------------------------------


def cmd_check(args: argparse.Namespace) -> dict[str, Any]:
    job_dir = Path(args.job)
    data = job.load_job(job_dir)
    if "export" not in data:
        raise UserError(render("cli.missing_step_check"), code="missing_step")
    export_data = data["export"]
    profiles_dir = job_dir / "profiles"
    machine_path = profiles_dir / "machine.json"
    process_path = profiles_dir / "process.json"
    filament_path = profiles_dir / "filament-0.json"
    if not (machine_path.exists() and process_path.exists() and filament_path.exists()):
        raise EnvError(render("cli.missing_profiles"), code="missing_profiles")

    target_plates = export_data["plates"]
    if args.plate is not None:
        target_plates = [p for p in target_plates if p["index"] == args.plate]
        if not target_plates:
            raise UserError(render("cli.plate_not_found", plate=args.plate), code="plate_not_found")

    results = []
    for plate in target_plates:
        idx_plate = plate["index"]
        out_dir = job_dir / "check" / f"plate_{idx_plate:02d}"
        print(f"slicing plate {idx_plate} (headless, --slice 0)...", file=sys.stderr)
        try:
            rec = bambu.check_slice(
                Path(plate["geometry_3mf"]),
                out_dir,
                machine_path,
                process_path,
                [filament_path],
                name=f"plate_{idx_plate:02d}",
            )
        except bambu.BambuCliError as exc:
            raise EnvError(str(exc)) from exc
        results.append(
            {
                "plate": idx_plate,
                "grams": rec["grams"],
                "seconds": rec["seconds"],
                "warnings": rec["warnings"],
                "returncode": rec["returncode"],
                "wall_seconds": rec["wall_seconds"],
                "error": rec["error"],
            }
        )

    data["check"] = {"plates": results}
    job.save_job(job_dir, data)

    if any(r["returncode"] != 0 or r["grams"] is None for r in results):
        raise EnvError(render("cli.slice_failed"), code="slice_failed", payload={"plates": results})

    return {"ok": True, "command": "check", "job": str(job_dir.resolve()), "print_submitted": False, "plates": results}


# ---------------------------------------------------------------------------
# 3.7 open
# ---------------------------------------------------------------------------


def cmd_open(args: argparse.Namespace) -> dict[str, Any]:
    job_dir = Path(args.job)
    data = job.load_job(job_dir)
    if "export" not in data:
        raise UserError(render("cli.missing_step_open"), code="missing_step")
    plates = data["export"]["plates"]
    app = profiles.app_root()
    if not args.dry_run and not app.exists():
        raise EnvError(render("cli.app_not_found", app=app), code="app_not_found")

    if args.all:
        targets = plates
    else:
        plate_no = args.plate if args.plate is not None else 1
        targets = [p for p in plates if p["index"] == plate_no]
        if not targets:
            raise UserError(render("cli.plate_not_found", plate=plate_no), code="plate_not_found")

    # 在真正打开之前先拍一次快照：Bambu Studio 本来就开着的话，打开之后再查
    # 进程恒为真，`launched` 就分不清"我们真的拉起了新进程"还是"它压根没关过"
    # （SPEC.md §5 第 12 条相关缺陷）。这一次进程检测在 dry-run 下也执行——它只
    # 是查询状态，不算"启动了子进程"；`is_process_running()` 按平台走
    # `pgrep`/`tasklist`，工具本身不可用时返回 `None`（未知）。
    was_running_before = bambu.is_process_running()

    results = []
    for i, plate in enumerate(targets):
        project_3mf = plate.get("project_3mf")
        if not project_3mf:
            raise UserError(render("cli.missing_project_3mf", plate=plate["index"]), code="missing_project_3mf")
        print(f"opening plate {plate['index']} (dry_run={args.dry_run})...", file=sys.stderr)
        info = bambu.open_project(app, Path(project_3mf), dry_run=args.dry_run)
        results.append({"plate": plate["index"], **info})
        if args.all and not args.dry_run and i < len(targets) - 1:
            time.sleep(3)

    launched = False
    if not args.dry_run:
        launched = bambu.wait_for_process()

    return {
        "ok": True,
        "command": "open",
        "job": str(job_dir.resolve()),
        "print_submitted": False,
        "opened": results,
        "launched": launched,
        "loaded": "unverified",
        "was_running_before": was_running_before,
    }


# ---------------------------------------------------------------------------
# 3.8 prepare
# ---------------------------------------------------------------------------


def cmd_prepare(args: argparse.Namespace) -> dict[str, Any]:
    job_dir = Path(args.job)
    steps: list[dict[str, Any]] = []

    def run_step(name: str, fn, ns: argparse.Namespace) -> dict[str, Any]:
        try:
            result = fn(ns)
        except CliError as exc:
            exc.payload = dict(exc.payload or {})
            exc.payload.setdefault("failed_step", name)
            raise
        steps.append({"step": name, "result": result})
        return result

    inspect_ns = argparse.Namespace(
        job=args.job,
        files=args.files,
        printer=args.printer,
        scale=args.scale,
        target_max_mm=args.target_max_mm,
        merge=args.merge,
    )
    run_step("inspect", cmd_inspect, inspect_ns)

    orient_ns = argparse.Namespace(job=args.job, strategy=args.strategy, shape=args.shape, set=args.orient_set)
    run_step("orient", cmd_orient, orient_ns)

    arrange_ns = argparse.Namespace(job=args.job, mode=args.mode, gap=args.gap)
    run_step("arrange", cmd_arrange, arrange_ns)

    export_ns = argparse.Namespace(
        job=args.job,
        process=args.process,
        filament=args.filament,
        shape=args.shape,
        set=args.export_set,
        no_project=args.no_project,
    )
    run_step("export", cmd_export, export_ns)

    if args.check:
        run_step("check", cmd_check, argparse.Namespace(job=args.job, plate=None))
    if args.open:
        run_step("open", cmd_open, argparse.Namespace(job=args.job, plate=1, all=False, dry_run=False))

    artifacts = {
        "parts_dir": str(job_dir / "parts"),
        "plates_dir": str(job_dir / "plates"),
        "profiles_dir": str(job_dir / "profiles"),
        "job_json": str(job.job_json_path(job_dir)),
    }
    if args.check:
        artifacts["check_dir"] = str(job_dir / "check")

    return {
        "ok": True,
        "command": "prepare",
        "job": str(job_dir.resolve()),
        "print_submitted": False,
        "steps": steps,
        "artifacts": artifacts,
    }


# ---------------------------------------------------------------------------
# argparse 装配 + main()
# ---------------------------------------------------------------------------


class JsonArgumentParser(argparse.ArgumentParser):
    """argparse 自身的解析错误（未知子命令、缺子命令的必填参数、非法枚举值、
    未识别的参数……）默认直接把用法字符串打到 stderr 再 `sys.exit(2)`，stdout
    什么都不会有——违反 SPEC.md §3 通用契约"参数解析错误也必须输出 JSON"。
    这里覆写 `error()`，统一吐一份 `bad_arguments` JSON 到 stdout 再退出。

    `-h`/`--help` 不走这条路径（argparse 的 `_HelpAction` 直接调用
    `parser.exit()`，不经过 `error()`），保持"打印帮助、退出码 0"的正常行为。
    子解析器（`add_parser()` 建出来的那些）也必须是这个类，见 `add_subparsers`
    的 `parser_class=` 参数。
    """

    def error(self, message: str) -> None:
        # `self.prog` 对子解析器形如 "print_prep arrange"，顶层是 "print_prep"；
        # 能拆出子命令名就带上，拆不出（比如未知子命令本身就是在顶层解析器上
        # 报的错）就留 None——不强求，测试只要求 stdout 是单个 JSON 且退出码 2。
        prog_parts = (self.prog or "").split()
        command_name = prog_parts[1] if len(prog_parts) > 1 else None
        payload = {
            "ok": False,
            "command": command_name,
            "job": None,
            "print_submitted": False,
            "error": {"code": "bad_arguments", "message": message},
        }
        print(json.dumps(payload, ensure_ascii=False))
        raise SystemExit(2)


def build_parser() -> argparse.ArgumentParser:
    parser = JsonArgumentParser(prog="print_prep", description=render("cli.description"))
    sub = parser.add_subparsers(dest="_subcommand", parser_class=JsonArgumentParser)

    p_printers = sub.add_parser("printers")
    p_printers.add_argument("--filter", default=None)
    p_printers.set_defaults(func=cmd_printers, _command_name="printers", job=None)

    p_inspect = sub.add_parser("inspect")
    p_inspect.add_argument("--job", required=True)
    p_inspect.add_argument("files", nargs="+")
    p_inspect.add_argument("--printer", default=DEFAULT_PRINTER)
    p_inspect.add_argument("--scale", type=float, default=None)
    p_inspect.add_argument("--target-max-mm", type=float, default=None, dest="target_max_mm")
    p_inspect.add_argument("--merge", action="store_true")
    p_inspect.set_defaults(func=cmd_inspect, _command_name="inspect")

    p_orient = sub.add_parser("orient")
    p_orient.add_argument("--job", required=True)
    p_orient.add_argument("--strategy", choices=("auto", "flat", "support", "upright"), default=DEFAULT_STRATEGY)
    p_orient.add_argument("--shape", choices=shape_table.VALID_LABELS, default=DEFAULT_SHAPE)
    p_orient.add_argument("--set", action="append", default=[])
    p_orient.add_argument("--angle-deg", type=float, default=None, dest="angle_deg")
    p_orient.set_defaults(func=cmd_orient, _command_name="orient")

    p_arrange = sub.add_parser("arrange")
    p_arrange.add_argument("--job", required=True)
    p_arrange.add_argument("--mode", choices=arrange_mod.VALID_MODES, default=DEFAULT_MODE)
    p_arrange.add_argument("--gap", type=float, default=DEFAULT_GAP_MM)
    p_arrange.set_defaults(func=cmd_arrange, _command_name="arrange")

    p_export = sub.add_parser("export")
    p_export.add_argument("--job", required=True)
    p_export.add_argument("--process", default=None)
    p_export.add_argument("--filament", default=None)
    p_export.add_argument("--shape", choices=shape_table.VALID_LABELS, default=None)
    p_export.add_argument("--set", action="append", default=[])
    p_export.add_argument("--no-project", action="store_true", dest="no_project")
    p_export.set_defaults(func=cmd_export, _command_name="export")

    p_check = sub.add_parser("check")
    p_check.add_argument("--job", required=True)
    p_check.add_argument("--plate", type=int, default=None)
    p_check.set_defaults(func=cmd_check, _command_name="check")

    p_open = sub.add_parser("open")
    p_open.add_argument("--job", required=True)
    p_open.add_argument("--plate", type=int, default=None)
    p_open.add_argument("--all", action="store_true")
    p_open.add_argument("--dry-run", action="store_true", dest="dry_run")
    p_open.set_defaults(func=cmd_open, _command_name="open")

    # prepare 是 inspect->orient->arrange->export(->check)(->open) 的超集；orient
    # 与 export 各自有一个语义不同的 `--set`（前者是"零件名=方向向量"，后者是
    # "预设字段名=值"），放在同一个子命令里没法共用一个 `--set` 标志，改叫
    # `--orient-set` / `--export-set` 消歧（对 orient/export 单跑时仍是各自的
    # `--set`，这个改名只影响 prepare 这一层）。
    p_prepare = sub.add_parser("prepare")
    p_prepare.add_argument("--job", required=True)
    p_prepare.add_argument("files", nargs="+")
    p_prepare.add_argument("--printer", default=DEFAULT_PRINTER)
    p_prepare.add_argument("--scale", type=float, default=None)
    p_prepare.add_argument("--target-max-mm", type=float, default=None, dest="target_max_mm")
    p_prepare.add_argument("--merge", action="store_true")
    p_prepare.add_argument("--strategy", choices=("auto", "flat", "support", "upright"), default=DEFAULT_STRATEGY)
    p_prepare.add_argument("--shape", choices=shape_table.VALID_LABELS, default=DEFAULT_SHAPE)
    p_prepare.add_argument("--orient-set", action="append", default=[], dest="orient_set")
    p_prepare.add_argument("--mode", choices=arrange_mod.VALID_MODES, default=DEFAULT_MODE)
    p_prepare.add_argument("--gap", type=float, default=DEFAULT_GAP_MM)
    p_prepare.add_argument("--process", default=None)
    p_prepare.add_argument("--filament", default=None)
    p_prepare.add_argument("--export-set", action="append", default=[], dest="export_set")
    p_prepare.add_argument("--no-project", action="store_true", dest="no_project")
    p_prepare.add_argument("--check", action="store_true")
    p_prepare.add_argument("--open", action="store_true")
    p_prepare.set_defaults(func=cmd_prepare, _command_name="prepare")

    return parser


def _emit_error(args: argparse.Namespace, exc: CliError) -> int:
    job_dir = getattr(args, "job", None)
    payload: dict[str, Any] = {
        "ok": False,
        "command": getattr(args, "_command_name", None),
        "job": str(Path(job_dir).resolve()) if job_dir else None,
        "print_submitted": False,
        "error": {"code": exc.code, "message": str(exc)},
    }
    payload.update(exc.payload or {})
    print(json.dumps(payload, ensure_ascii=False))
    return exc.exit_code


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        # argparse 的解析错误路径（含我们自己覆写的 `JsonArgumentParser.error()`）
        # 与 `-h`/`--help` 都是靠 `raise SystemExit` 跳出的；这里跑在同一个
        # 进程里的测试是直接调用 `main()` 拿返回值，不能真的让整个进程退出，
        # 所以要接住换成普通返回值。JSON（有的话）已经在 `error()` 里打过了，
        # `--help` 的帮助文本也已经由 argparse 自己打过了，这里不用再打印。
        code = exc.code
        return code if isinstance(code, int) else (0 if code is None else 1)
    if not hasattr(args, "func"):
        parser.print_help(sys.stderr)
        payload = {
            "ok": False,
            "command": None,
            "job": None,
            "print_submitted": False,
            "error": {"code": "bad_arguments", "message": render("cli.missing_subcommand")},
        }
        print(json.dumps(payload, ensure_ascii=False))
        return 2
    try:
        result = args.func(args)
    except CliError as exc:
        return _emit_error(args, exc)
    except Exception as exc:  # noqa: BLE001 —— 未预期异常也要落成 JSON，不能让 traceback 直接炸 stdout
        traceback.print_exc(file=sys.stderr)
        wrapped = CliError(str(exc), code="unexpected")
        wrapped.exit_code = 1
        return _emit_error(args, wrapped)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
