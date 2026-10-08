from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).parent / "_vendor"))
import numpy as np
import trimesh
import manifold3d as mf

OUTPUTS = ROOT / "outputs"
STATE_PATH = OUTPUTS / "project.json"
_historical_source = os.environ.get("CONNECTION_DEMO_HISTORICAL_SOURCE_DIR")
SOURCE_DIR = Path(_historical_source).expanduser() if _historical_source else None
DEFAULT = dict(
    type="tongue_slot",
    clearance_mm=0.3,
    position_mm=0.0,
    engagement_mm=6.0,
    wall_mm=2.4,
    cavity_depth_mm=32.74,
    beam_thickness_mm=1.2,
    hook_mm=0.8,
)
LIMITS = dict(
    clearance_mm=(0.1, 0.65),
    position_mm=(-5, 5),
    engagement_mm=(5, 10),
    wall_mm=(2, 3.2),
    cavity_depth_mm=(28, 45),
    beam_thickness_mm=(0.9, 1.6),
    hook_mm=(0.45, 1.1),
)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save_json(path, data):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def box(lo, hi):
    return mf.Manifold.cube(tuple(float(b - a) for a, b in zip(lo, hi))).translate(lo)


def to_trimesh(solid):
    result = solid.to_mesh64()
    return trimesh.Trimesh(np.asarray(result.vert_properties)[:, :3], np.asarray(result.tri_verts), process=True)


def mesh_solid(mesh):
    return mf.Manifold(mf.Mesh(np.asarray(mesh.vertices, dtype=np.float32), np.asarray(mesh.faces, dtype=np.uint32)))


def export_solid(solid, folder, stem, color):
    mesh = to_trimesh(solid)
    mesh.export(folder / f"{stem}.stl")
    export_glb(mesh, folder / f"{stem}.glb", color)
    return mesh


def export_glb(mesh, path, color):
    view = mesh.copy()
    # Engineering mm/Z-up -> glTF meters/Y-up. +X stays +X, +Y becomes -Z.
    transform = np.array([[0.001, 0, 0, 0], [0, 0, 0.001, 0], [0, -0.001, 0, 0], [0, 0, 0, 1]])
    view.apply_transform(transform)
    view.visual = trimesh.visual.ColorVisuals(view, vertex_colors=color)
    view.export(path)


def init_source():
    target = OUTPUTS / "source"
    manifest_path = target / "manifest.json"
    if manifest_path.exists():
        frozen = json.loads(manifest_path.read_text(encoding="utf-8"))
        if "reference_required" not in frozen:
            frozen["reference_required"] = bool(frozen.get("records")) or SOURCE_DIR is not None
            save_json(manifest_path, frozen)
        return frozen
    target.mkdir(parents=True, exist_ok=True)
    records, meshes = [], []
    for name in ["A_00.stl", "A_01_NORMAL.stl"]:
        source = SOURCE_DIR / "PARTS" / name if SOURCE_DIR is not None else None
        if source is None:
            continue
        if not source.exists():
            continue
        copy = target / name
        shutil.copy2(source, copy)
        mesh = trimesh.load(copy, force="mesh")
        records.append(
            dict(
                file=name,
                original_path=str(source),
                sha256=sha(source),
                frozen_sha256=sha(copy),
                bounds_mm=mesh.bounds.tolist(),
                faces=len(mesh.faces),
            )
        )
        meshes.append(mesh)
    if meshes:
        merged = trimesh.util.concatenate(meshes)
        merged.apply_translation(-merged.bounds.mean(axis=0))
        # Place bottom at zero for reference mode, preserving all relative geometry.
        merged.apply_translation([0, 0, -merged.bounds[0, 2]])
        export_glb(merged, target / "source_reference.glb", [75, 144, 160, 255])
    source = dict(
        name="兔子摄像头壳体 · REV_DEPTH43_FOUR" if meshes else "规则相机壳体工程样件",
        url="/outputs/source/source_reference.glb" if meshes else None,
        description=(
            "已冻结历史 A_00 与 A_01_NORMAL 原件作为只读参考。当前生成的是采用其已确认内腔尺寸的规则壳体工程样件，不是兔形原件自动改造。"
            if meshes
            else "未配置历史兔形源文件；当前按已确认的内腔尺寸生成规则壳体工程样件。"
        ),
        records=records,
        reference_required=SOURCE_DIR is not None,
        cavity_mm=[25, 25, 32.74],
        original_geometry_modified=False,
    )
    save_json(manifest_path, source)
    return source


def validate_parameters(data, previous=None):
    result = {**DEFAULT, **(previous or {})}
    for key in DEFAULT:
        if key in data:
            result[key] = data[key]
    if result["type"] not in ("tongue_slot", "snap_fit"):
        raise ValueError("type must be tongue_slot or snap_fit")
    for key, (low, high) in LIMITS.items():
        try:
            v = float(result[key])
        except (TypeError, ValueError):
            raise ValueError(f"{key} must be a number")
        if not math.isfinite(v) or not low <= v <= high:
            raise ValueError(f"{key} must be within [{low}, {high}] mm")
        result[key] = v
    if result["type"] == "snap_fit" and result["hook_mm"] <= result["clearance_mm"]:
        raise ValueError("snap_fit requires hook_mm > clearance_mm; otherwise there is no geometric retention undercut")
    return result


def build_geometry(p):
    w, c, depth = p["wall_mm"], p["clearance_mm"], p["cavity_depth_mm"]
    half, H, L, ypos = 12.5 + w, depth + w, p["engagement_mm"], p["position_mm"]
    seam = 0.30
    base = box([-half, -half, 0], [half, half, H]) - box([-12.5, -12.5, w], [12.5, 12.5, H + 1])
    lid = box([-half, -half, H + seam], [half, half, H + seam + w])
    # Locked external rear boss is a visible preservation witness, separate from connector ROI.
    protected = box([-8, -half - 2, 4], [8, -half + 0.25, 12])
    base = base + protected
    baseline_base, baseline_lid = base, lid
    if p["type"] == "tongue_slot":
        x0, thickness, width = half + 1.2, 2.4, 6.0
        tongue = box([x0, ypos - width / 2, H - L], [x0 + thickness, ypos + width / 2, H + seam + 0.4])
        bridge = box([half - 0.4, ypos - 4.2, H + seam], [x0 + thickness + 0.5, ypos + 4.2, H + seam + w])
        receiver = box([half - 0.3, ypos - 5, H - L - 1.8], [x0 + thickness + c + 1.6, ypos + 5, H - 0.4])
        pocket = box([x0 - c, ypos - width / 2 - c, H - L - c], [x0 + thickness + c, ypos + width / 2 + c, H + 1])
        base = (base + receiver) - pocket
        lid = lid + bridge + tongue
        feature = dict(
            width_mm=width,
            thickness_mm=thickness,
            receiver_width_mm=width + 2 * c,
            receiver_thickness_mm=thickness + 2 * c,
            engagement_mm=L,
            hook_mm=0,
            geometric_release_deflection_mm=0,
        )
    else:
        x0, thickness, width = half + 1.2, p["beam_thickness_mm"], 6.0
        x1, hook = x0 + thickness, p["hook_mm"]
        beam = box([x0, ypos - width / 2, H - L + 0.15], [x1, ypos + width / 2, H + seam + 0.4])
        bridge = box([half - 0.4, ypos - 4.2, H + seam], [x1 + 0.5, ypos + 4.2, H + seam + w])
        # Real sloped insertion nose and square retention shoulder, extruded along Y.
        polygon = [
            (x0 + 0.10, H - L),
            (x1 + 0.15, H - L),
            (x1 + hook, H - L + 1.3),
            (x1 + hook, H - L + 2.0),
            (x0 + 0.10, H - L + 2.0),
        ]
        barb = (
            mf.CrossSection([polygon])
            .extrude(width - 0.4)
            .rotate([90, 0, 0])
            .translate([0, ypos + (width - 0.4) / 2, 0])
        )
        receiver = box([half - 0.3, ypos - 5, H - L - 1.8], [x1 + hook + 1.8, ypos + 5, H - 1.0])
        channel = box([x0 - c, ypos - width / 2 - c, H - L - c], [x1 + c, ypos + width / 2 + c, H + 1])
        window = box(
            [x1 - 0.1, ypos - width / 2 - c, H - L - 0.25], [x1 + hook + 2.2, ypos + width / 2 + c, H - L + 2.0 + c]
        )
        # Receiver back wall is opened locally so the beam may flex inward when pressed.
        flex_space = box(
            [x0 - hook - 0.25, ypos - width / 2 - c, H - L - 0.25], [x0 + 0.05, ypos + width / 2 + c, H - 0.8]
        )
        base = (base + receiver) - channel - window - flex_space
        lid = lid + bridge + beam + barb
        feature = dict(
            width_mm=width,
            thickness_mm=thickness,
            receiver_width_mm=width + 2 * c,
            receiver_thickness_mm=thickness + 2 * c,
            engagement_mm=L,
            hook_mm=hook,
            geometric_release_deflection_mm=max(0, hook - c),
            free_beam_length_mm=L + seam - 2.0,
            estimated_beam_surface_strain=1.5 * thickness * max(0, hook - c) / ((L + seam - 2.0) ** 2),
            strain_model="small-deflection uniform cantilever estimate only; no allowable material strain specified",
        )
    roi = box([half - 0.5, ypos - 5.2, H - L - 2], [half + 8, ypos + 5.2, H + seam + w + 0.2])
    # Include the original cavity-side wall face (x=12.5), preserving its full thickness.
    coupon_roi = box([12.0, ypos - 6, H - L - 2], [half + 9, ypos + 6, H + seam + w + 0.3])
    return dict(
        base=base,
        lid=lid,
        baseline_base=baseline_base,
        baseline_lid=baseline_lid,
        roi=roi,
        coupon_roi=coupon_roi,
        feature=feature,
        H=H,
        half=half,
        protected=protected,
    )


def section_crossings(solid, z, axis, at):
    """Intersect actual triangulated solid section boundary with a measurement line."""
    values = []
    for polygon in solid.slice(z).to_polygons():
        for a, b in zip(polygon, np.roll(polygon, -1, axis=0)):
            if (a[axis] <= at < b[axis]) or (b[axis] <= at < a[axis]):
                t = (at - a[axis]) / (b[axis] - a[axis])
                values.append(float(a[1 - axis] + t * (b[1 - axis] - a[1 - axis])))
    return sorted(set(round(x, 8) for x in values))


def measure_fit(g, p):
    z = g["H"] - 1.5
    xmid = g["half"] + 1.2 + g["feature"]["thickness_mm"] / 2
    y = p["position_mm"]
    female_y = section_crossings(g["base"], z, 0, xmid)
    male_y = section_crossings(g["lid"], z, 0, xmid)
    female_x = section_crossings(g["base"], z, 1, y)
    male_x = section_crossings(g["lid"], z, 1, y)
    inner_high = min(v for v in female_y if v > y)
    inner_low = max(v for v in female_y if v < y)
    male_high = min(v for v in male_y if v > y)
    male_low = max(v for v in male_y if v < y)
    x_clearance = min(v for v in female_x if v > xmid) - min(v for v in male_x if v > xmid)
    measured = dict(
        method="actual solid cross-section boundary intersections",
        section_z_mm=z,
        receiver_width_mm=inner_high - inner_low,
        male_width_mm=male_high - male_low,
        side_clearance_positive_y_mm=inner_high - male_high,
        side_clearance_negative_y_mm=male_low - inner_low,
        outer_x_clearance_mm=x_clearance,
    )
    measured["matches_requested_clearance"] = all(
        abs(measured[k] - p["clearance_mm"]) < 1e-6
        for k in ["side_clearance_positive_y_mm", "side_clearance_negative_y_mm", "outer_x_clearance_mm"]
    )
    return measured


def geometry_report(p, g, source):
    base, lid = g["base"], g["lid"]
    meshes = [to_trimesh(base), to_trimesh(lid)]
    reports = []
    for part_id, mesh, solid in zip(["part_a", "part_b"], meshes, [base, lid]):
        reports.append(
            dict(
                id=part_id,
                watertight=bool(mesh.is_watertight),
                winding_consistent=bool(mesh.is_winding_consistent),
                components=len(solid.decompose()),
                volume_mm3=float(mesh.volume),
                faces=len(mesh.faces),
                bounds_mm=mesh.bounds.tolist(),
            )
        )
    final_overlap = float((base ^ lid).volume())
    outside = float(
        ((base - g["baseline_base"]) - g["roi"]).volume()
        + ((g["baseline_base"] - base) - g["roi"]).volume()
        + ((lid - g["baseline_lid"]) - g["roi"]).volume()
        + ((g["baseline_lid"] - lid) - g["roi"]).volume()
    )
    cavity = box([-12.5, -12.5, p["wall_mm"]], [12.5, 12.5, g["H"]])
    cavity_overlap = float((base ^ cavity).volume())
    # Deterministic finite pose sampling; explicitly not continuous swept-volume proof.
    travel = p["engagement_mm"] + 3
    samples = []
    for dz in np.linspace(travel, 0, 41):
        overlap = float((base ^ lid.translate([0, 0, float(dz)])).volume())
        samples.append(dict(offset_mm=round(float(dz), 4), overlap_mm3=round(overlap, 6)))
    collisions = [s for s in samples if s["overlap_mm3"] > 1e-5]
    records = source.get("records", [])
    hashes_ok = (
        len(records) == 2
        and {r["file"] for r in records} == {"A_00.stl", "A_01_NORMAL.stl"}
        and all(
            (OUTPUTS / "source" / r["file"]).is_file()
            and Path(r["original_path"]).is_file()
            and sha(OUTPUTS / "source" / r["file"]) == r["frozen_sha256"] == r["sha256"]
            and sha(Path(r["original_path"])) == r["sha256"]
            for r in records
        )
    )
    reference_required = source.get("reference_required", True)
    source_status = ("pass" if hashes_ok else "fail") if reference_required else "not_applicable"
    source_detail = (
        (
            "历史兔壳的冻结副本 SHA-256 一致；本 demo 不改写历史源文件。"
            if hashes_ok
            else "已配置历史源件，但两件原件或冻结副本缺失/哈希不一致。"
        )
        if reference_required
        else "未配置历史兔壳参照；规则壳体直接由已确认的内腔尺寸生成。"
    )
    closed_ok = final_overlap < 1e-5
    fit = measure_fit(g, p)
    checks = [
        dict(
            id="mesh",
            label="两件实体网格",
            status="pass"
            if all(x["watertight"] and x["winding_consistent"] and x["components"] == 1 for x in reports)
            else "fail",
            detail="逐件检查闭合、法线一致、单连通实体；STL 源单位 mm。",
        ),
        dict(
            id="fit",
            label="截面实测配合尺寸",
            status="pass" if fit["matches_requested_clearance"] else "fail",
            detail=f"从实体截面测得槽宽 {fit['receiver_width_mm']:.3f} / 舌宽 {fit['male_width_mm']:.3f} mm；两侧与外侧间隙符合 {p['clearance_mm']:.3f} mm 参数。尚未实打校准。",
        ),
        dict(
            id="closed",
            label="闭合状态干涉",
            status="pass" if closed_ok else "fail",
            detail=f"实体交集 {final_overlap:.6f} mm³。",
        ),
        dict(
            id="path",
            label="装配路径 · 41 帧采样",
            status="review" if collisions else "pass",
            detail=(
                f"{len(collisions)} 帧存在刚性穿插；卡扣需弹性让位，本次没有材料力学验证。"
                if collisions
                else "41 个刚性平移姿态未发现体积穿插；不是连续扫掠证明。"
            ),
        ),
        dict(
            id="protected",
            label="局部改动边界",
            status="pass" if outside < 1e-5 else "fail",
            detail=f"连接 ROI 外，相对本版规则壳体基线的变化体积 {outside:.6f} mm³；后侧保护凸台保留。",
        ),
        dict(
            id="cavity",
            label="相机占用空间",
            status="pass" if cavity_overlap < 1e-5 else "fail",
            detail=f"25 × 25 × {p['cavity_depth_mm']:.2f} mm 内腔与新增结构交集 {cavity_overlap:.6f} mm³。",
        ),
        dict(id="source", label="历史源件冻结", status=source_status, detail=source_detail),
        dict(
            id="physical",
            label="实物装配与寿命",
            status="pending",
            detail="待打印小样验证松紧、强度和重复拆装；未执行切片、FEA 或真实打印。",
        ),
    ]
    limitations = [
        "确定性参数模板；未调用大模型推理或自动理解任意自然语言。",
        (
            "主体为采用历史内腔尺寸生成的规则壳体工程样件；兔形原件仅作只读参考。"
            if reference_required
            else "规则壳体使用已确认的内腔尺寸；没有载入历史兔形原件。"
        ),
        "不支持任意网格自动选择连接区域；当前连接位于 +X 外壁，位置参数沿工程 Y 方向移动。",
        "几何间隙不是打印公差保证，当前材料/打印机配置尚未实测校准。",
        "局部试片保留原侧壁厚度，验证尺寸配合与局部几何；裁断边界改变整体刚度，不能预测整壳拆装力。",
        "装配检查为 41 个离散刚性姿态的体积交集，未证明连续路径无碰撞。",
        "卡扣形变与表面应变只有简化梁估计；材料允许应变、根部应力集中、疲劳与打印各向异性未验证。",
        "与同事工作台只提供本地可验证交接包；尚未安装插件或调用其真实服务。",
    ]
    status = "geometry_failed" if any(c["status"] == "fail" for c in checks) else "needs_physical_validation"
    return dict(
        status=status,
        checks=checks,
        parts=reports,
        final_overlap_mm3=final_overlap,
        outside_roi_change_mm3=outside,
        cavity_intrusion_mm3=cavity_overlap,
        feature_dimensions=g["feature"],
        measured_fit=fit,
        coupon=dict(
            retains_full_source_wall_thickness=True,
            wall_mm=p["wall_mm"],
            purpose="local dimensional fit and connector geometry",
            does_not_predict_full_shell_stiffness_or_release_force=True,
        ),
        assembly=dict(
            direction=[0, 1, 0],
            coordinate_system="viewer meters/Y-up",
            engineering_direction=[0, 0, 1],
            moving_part_id="part_b",
            travel_mm=travel,
            samples=samples,
            rigid_collision=bool(collisions),
            elastic_contact_expected=p["type"] == "snap_fit",
            max_overlap_mm3=max(s["overlap_mm3"] for s in samples),
            continuous_check=False,
        ),
        limitations=limitations,
        real_llm_invocation=False,
        fea_performed=False,
        physical_print_performed=False,
    )


def current_project():
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    return generate(DEFAULT)


def generate(data, reset=False):
    start = time.perf_counter()
    previous = json.loads(STATE_PATH.read_text(encoding="utf-8")) if STATE_PATH.exists() else None
    if previous and "revision" in data and int(data["revision"]) != previous["revision"]:
        raise RuntimeError("revision conflict: refresh project before applying changes")
    p = validate_parameters(data, None if reset else (previous or {}).get("parameters"))
    existing = (
        [int(x.name[1:]) for x in (OUTPUTS / "revisions").glob("r[0-9][0-9][0-9][0-9]")]
        if (OUTPUTS / "revisions").exists()
        else []
    )
    revision = max([(previous or {}).get("revision", 0)] + existing) + 1
    folder = OUTPUTS / "revisions" / f"r{revision:04d}"
    if folder.exists():
        raise RuntimeError("revision folder already exists; refusing overwrite")
    folder.mkdir(parents=True)
    source = init_source()
    g = build_geometry(p)
    report = geometry_report(p, g, source)
    if report["status"] == "geometry_failed":
        save_json(folder / "failed_report.json", report)
        raise ValueError(
            "geometry validation failed; current project was not modified; inspect "
            + str(folder / "failed_report.json")
        )
    colors = ([79, 157, 171, 255], [232, 177, 85, 255])
    for stem, solid, color in [
        ("part_a", g["base"], colors[0]),
        ("part_b", g["lid"], colors[1]),
        ("coupon_a", g["base"] ^ g["coupon_roi"], colors[0]),
        ("coupon_b", g["lid"] ^ g["coupon_roi"], colors[1]),
    ]:
        export_solid(solid, folder, stem, color)
    assembly = trimesh.Scene()
    for name in ["part_a", "part_b"]:
        part = trimesh.load(folder / f"{name}.glb", force="mesh")
        assembly.add_geometry(part, node_name=name, geom_name=name)
    assembly.export(folder / "assembly.glb")
    # Export a plate with separated coupons, mm coordinates; no slicer claims.
    ca, cb = to_trimesh(g["base"] ^ g["coupon_roi"]), to_trimesh(g["lid"] ^ g["coupon_roi"])
    for i, m in enumerate([ca, cb]):
        m.apply_translation(-m.bounds[0] + [i * 22, 0, 0])
    trimesh.util.concatenate([ca, cb]).export(folder / "coupon_pair_print_layout.stl")
    relative = "/outputs/revisions/" + folder.name + "/"
    params_record = dict(
        schema="connection-design.parameters/v1",
        units="mm",
        revision=revision,
        parameters=p,
        source_sha256=[x["sha256"] for x in source["records"]],
        joint=dict(
            id="connection_01",
            host_a="part_a",
            host_b="part_b",
            anchor_rule="right-wall/upper-rim",
            anchor_mm=[g["half"], p["position_mm"], g["H"]],
            axis=[0, 0, 1],
        ),
        generator="Manifold exact mesh booleans + deterministic parametric templates",
        source_code_sha256=sha(Path(__file__)),
    )
    save_json(folder / "parameters.json", params_record)
    save_json(folder / "report.json", report)
    # Explicit adapter boundary: contract proposal, not an invented studio_edit command.
    handoff = dict(
        schema="connection-design.workbench-handoff/v1",
        status="offline_adapter_not_live_integrated",
        unit="mm",
        preview_unit="m",
        source_revision=revision,
        source_parameters="parameters.json",
        source_report="report.json",
        expected_part_ids=["part_a", "part_b"],
        artifacts=[
            dict(
                part_id=part_id,
                preview=f"{part_id}.glb",
                manufacturing=f"{part_id}.stl",
                sha256=sha(folder / f"{part_id}.stl"),
            )
            for part_id in ["part_a", "part_b"]
        ],
        proposed_workbench_steps=[
            "Read current project revision and selection using the installed workbench contract.",
            "Run this task in a local workbench task template.",
            "Import the two GLB artifacts through the actual supported import API, preserving part IDs.",
            "Attach parameters.json and report.json; route mm STL copies to Print Prep.",
        ],
        note="This manifest deliberately contains no unverified studio_edit or studio_task mutation payload.",
    )
    save_json(folder / "workbench_handoff.json", handoff)
    artifacts = []
    labels = {
        "assembly.glb": "完整配对装配 GLB",
        "part_a.stl": "壳体 STL",
        "part_b.stl": "盖子 STL",
        "coupon_pair_print_layout.stl": "配对试装件 STL",
        "part_a.glb": "壳体 GLB",
        "part_b.glb": "盖子 GLB",
        "coupon_a.glb": "局部母件 GLB",
        "coupon_b.glb": "局部公件 GLB",
        "parameters.json": "参数与关联记录",
        "report.json": "几何检查报告",
        "workbench_handoff.json": "工作台交接清单",
    }
    for name, label in labels.items():
        artifacts.append(
            dict(
                id=name,
                label=label,
                url=relative + name,
                absolute_path=str(folder / name),
                kind=Path(name).suffix[1:],
                bytes=(folder / name).stat().st_size,
            )
        )
    history = (previous or {}).get("history", []) + [
        dict(
            revision=revision,
            type=p["type"],
            parameters=p,
            report_url=relative + "report.json",
            created_at=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        )
    ]
    project = dict(
        id="camera-connection-demo",
        name="相机外壳 · 连接设计工程样件",
        revision=revision,
        units="mm",
        viewer_units="m",
        parameters=p,
        source=source,
        parts=[
            dict(id="part_a", name="壳体 · 接收结构", url=relative + "part_a.glb", color="#4f9dab", role="female"),
            dict(id="part_b", name="盖子 · 连接结构", url=relative + "part_b.glb", color="#e8b155", role="male"),
        ],
        coupons=[
            dict(id="coupon_a", name="局部母件", url=relative + "coupon_a.glb", color="#4f9dab", role="female"),
            dict(id="coupon_b", name="局部公件", url=relative + "coupon_b.glb", color="#e8b155", role="male"),
        ],
        connections=[params_record["joint"]],
        report=report,
        artifacts=artifacts,
        history=history,
        elapsed_ms=round((time.perf_counter() - start) * 1000),
        capabilities=dict(
            real_geometry=True,
            parametric=True,
            full_shell_pair=True,
            local_coupon=True,
            real_llm=False,
            fea=False,
            live_workbench_integration=False,
        ),
    )
    # Atomic publication: a failed build never changes the current revision.
    temp = STATE_PATH.with_suffix(".tmp")
    save_json(temp, project)
    temp.replace(STATE_PATH)
    return project


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    data = json.loads(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT
    result = generate(data)
    print(
        json.dumps(
            dict(revision=result["revision"], elapsed_ms=result["elapsed_ms"], checks=result["report"]["checks"]),
            ensure_ascii=False,
            indent=2,
        )
    )
