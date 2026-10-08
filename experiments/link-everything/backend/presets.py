"""Four independent geometric snap-fit teaching specimens; no material simulation."""

from __future__ import annotations
import argparse
import copy
import json
import math
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.engine import box, export_solid, to_trimesh, save_json, sha
import manifold3d as mf
import trimesh
import numpy as np

OUTPUTS = ROOT / "outputs" / "presets"
SOURCE_URL = "https://formlabs.com/blog/designing-3d-printed-snap-fit-enclosures/"
COMMON_LIMITS = {"clearance_mm": [0.10, 0.55], "hook_mm": [0.45, 1.10]}
CATALOG = [
    dict(
        id="cantilever",
        name="悬臂卡扣",
        en_name="Cantilever",
        description="单根直梁一端固定，自由端的斜面扣钩与扣窗配对。",
        use_case="小型外壳、背包扣与局部开合节点的原理样件。",
        interaction="轴向接近 → 自由端让位 → 倒扣进入扣窗；释放需要使梁回撤。",
        mechanism_note="梁的弯曲区和根部是一体实体；动画只演示刚性相对位置，未计算梁的弹性。",
        thickness_label="悬臂厚度",
        thickness_limits=[0.8, 1.6],
        thickness_default=1.2,
    ),
    dict(
        id="u_shaped",
        name="U 形折返卡扣",
        en_name="U-shaped",
        description="弹性路径向下折返再向上，贯穿开口将两条臂分开。",
        use_case="直线安装空间有限、需要在局部区域布置较长弹性路径的外壳节点。",
        interaction="观察贯通 U 形开口 → 沿轴压入 → 返回臂末端进入扣窗。",
        mechanism_note="真实折返的一体弹性路径，没有实心填充 U 形开口；曲率、根部应力及可变形量未验证。",
        thickness_label="折返梁厚度",
        thickness_limits=[0.8, 1.6],
        thickness_default=1.2,
    ),
    dict(
        id="torsion",
        name="扭转卡扣",
        en_name="Torsion",
        description="左右固定支架通过细扭杆连接中央摇臂，摇臂前端带扣钩。",
        use_case="需要外露按压位置的盒盖锁扣与可操作的释放节点。",
        interaction="识别两端固定的细扭杆 → 按压后侧摇臂 → 前端扣钩回撤后拆离。",
        mechanism_note="细杆、支架、摇臂是一体实体；不是可自由转动的销轴。扭转弹性与按压力待验证。",
        thickness_label="扭杆直径",
        thickness_limits=[1.0, 2.2],
        thickness_default=1.4,
    ),
    dict(
        id="annular",
        name="环形卡扣",
        en_name="Annular",
        description="连续圆筒插口带整圈凸缘，对应圆筒内壁的环形沟槽。",
        use_case="圆形盖、筒口与同轴连接节点的原理样件。",
        interaction="同轴对齐 → 环体弹性越过入口 → 整圈凸缘进入环槽。",
        mechanism_note="连续环体需要环向变形；没有用多根悬臂替代。环体应变、拔出力与密封性均未验证。",
        thickness_label="插入环壁厚",
        thickness_limits=[0.8, 1.8],
        thickness_default=1.2,
    ),
]


def catalog():
    result = copy.deepcopy(CATALOG)
    examples = {}
    path = OUTPUTS / "examples.json"
    if path.exists():
        examples = {x["preset_id"]: x for x in json.loads(path.read_text(encoding="utf-8")).get("examples", [])}
    for spec in result:
        spec["limits"] = {**COMMON_LIMITS, "beam_thickness_mm": spec["thickness_limits"]}
        spec["defaults"] = {"clearance_mm": 0.25, "beam_thickness_mm": spec["thickness_default"], "hook_mm": 0.8}
        labels = {"clearance_mm": "单边几何间隙", "beam_thickness_mm": spec["thickness_label"], "hook_mm": "倒扣突出量"}
        spec["parameters"] = [
            dict(
                key=key,
                label=labels[key],
                min=spec["limits"][key][0],
                max=spec["limits"][key][1],
                step=0.05,
                default=spec["defaults"][key],
                unit="mm",
            )
            for key in ["clearance_mm", "beam_thickness_mm", "hook_mm"]
        ]
        spec["clearance_semantics"] = (
            "径向单边间隙；直径差为 2 × 间隙"
            if spec["id"] == "annular"
            else "配合侧的单边几何间隙，双侧尺寸差为 2 × 间隙"
        )
        spec["parameters"][0]["label"] = "径向单边间隙" if spec["id"] == "annular" else "单边几何间隙"
        spec["parameters"][0]["description"] = spec["clearance_semantics"]
        spec["scope"] = "local_geometric_teaching_specimen"
        spec["parameter_note"] = "数值仅为教学样件模板范围，不是材料或打印工艺设计限值；倒扣突出量必须大于单边间隙。"
        if spec["id"] in examples:
            spec["example"] = examples[spec["id"]]
    return dict(
        presets=result,
        source_url=SOURCE_URL,
        source_note="四类机制参考 Formlabs；样件尺寸与几何由本项目独立构建，未经 Formlabs 验证。",
        geometry_units="mm",
        viewer_units="m",
        viewer_up="Y",
    )


def validate(payload, previous=None):
    if not isinstance(payload, dict):
        raise ValueError("JSON object required")
    allowed = {"preset_id", "clearance_mm", "beam_thickness_mm", "hook_mm", "revision"}
    if set(payload) - allowed:
        raise ValueError("unsupported preset parameters: " + ", ".join(sorted(set(payload) - allowed)))
    preset_id = payload.get("preset_id", (previous or {}).get("preset_id", "cantilever"))
    spec = next((p for p in catalog()["presets"] if p["id"] == preset_id), None)
    if spec is None:
        raise ValueError("unknown preset_id")
    p = {**spec["defaults"]}
    if previous and previous.get("preset_id") == preset_id:
        p.update(previous["parameters"])
    for key, bounds in spec["limits"].items():
        if key in payload:
            if isinstance(payload[key], bool):
                raise ValueError(key + " must be a number")
            try:
                p[key] = float(payload[key])
            except (TypeError, ValueError):
                raise ValueError(key + " must be a number")
        if not math.isfinite(p[key]) or not bounds[0] <= p[key] <= bounds[1]:
            raise ValueError(f"{key} must be within {bounds} mm")
    if p["hook_mm"] <= p["clearance_mm"]:
        raise ValueError("hook_mm must exceed clearance_mm to retain a geometric undercut")
    return preset_id, p, spec


def prism_xz(points, width, center_y=0):
    return mf.CrossSection([points]).extrude(width).rotate([90, 0, 0]).translate([0, center_y + width / 2, 0])


def cylinder(radius, height, z=0, radius_top=None):
    return mf.Manifold.cylinder(height, radius, radius if radius_top is None else radius_top, 128).translate([0, 0, z])


def viewer_point(point):
    return [point[0] * 0.001, point[2] * 0.001, -point[1] * 0.001]


def viewer_size(size):
    return [size[0] * 0.001, size[2] * 0.001, size[1] * 0.001]


def region(id, label, center, size, kind):
    return dict(id=id, label=label, center_m=viewer_point(center), size_m=viewer_size(size), kind=kind)


def build(preset_id, p):
    c, t, h = p["clearance_mm"], p["beam_thickness_mm"], p["hook_mm"]
    if preset_id in ("cantilever", "u_shaped"):
        x0, x1 = 4.0, 4.0 + t
        fixed = box([-10, -8, 0], [11, 8, 2])
        receiver = box([1.6, -5, 2], [x1 + h + 2, 5, 15])
        moving = box([-10, -8, 17], [11, 8, 19])
        if preset_id == "cantilever":
            beam = box([x0, -3, 4.15], [x1, 3, 17.3])
            hook_z = 4.0
            anchor = [x1, 0, 5.0]
            regions = [
                region("root", "固定根部", [x0 + t / 2, 0, 17], [t + 1, 7, 3], "fixed"),
                region("elastic", "直梁弯曲区", [x0 + t / 2, 0, 10], [t, 6, 10], "elastic"),
            ]
        else:
            # Three overlapping solids form a single U path with a real through-opening.
            root = box([-4, -3, 3.5], [-4 + t, 3, 17.3])
            bottom = box([-4, -3, 3.5], [x1, 3, 3.5 + t])
            return_arm = box([x0, -3, 3.5], [x1, 3, 13.8])
            beam = root + bottom + return_arm
            hook_z = 11.8
            # The folded lower bridge must pass the receiver during axial assembly;
            # open this corridor to the top, rather than trapping it in a short slot.
            receiver = receiver - box([1.3, -3 - c, 3.5 - c], [x1 + c, 3 + c, 15.5])
            anchor = [x1, 0, 12.8]
            regions = [
                region("root", "固定根部", [-4 + t / 2, 0, 17], [t + 1, 7, 3], "fixed"),
                region("elastic", "贯通 U 形弹性路径", [0.5, 0, 10], [10, 6, 14], "elastic"),
            ]
        hook = prism_xz(
            [
                (x0 + 0.1, hook_z),
                (x1 + 0.15, hook_z),
                (x1 + h, hook_z + 1.3),
                (x1 + h, hook_z + 2),
                (x0 + 0.1, hook_z + 2),
            ],
            5.6,
        )
        channel = box([x0 - c, -3 - c, 3.5 - c], [x1 + c, 3 + c, 15.5])
        window = box([x1 - 0.1, -3 - c, hook_z - 0.25], [x1 + h + 2.2, 3 + c, hook_z + 2 + c])
        flex_space = box([x0 - h - 0.5, -3 - c, 3.25], [x0 + 0.05, 3 + c, 15.2])
        fixed = fixed + receiver - channel - window - flex_space
        moving = moving + beam + hook
        regions.append(region("catch", "配对倒扣与扣窗", [x1 + h / 2, 0, hook_z + 1], [h + 2, 8, 3], "catch"))
        roi_center, roi_size = [3, 0, 10], [17, 12, 18]
        names = ["局部支座与扣窗", "盖片与悬臂扣钩" if preset_id == "cantilever" else "盖片与 U 形折返扣钩"]
        travel = 19.0
    elif preset_id == "torsion":
        fixed = box([-12, -11, 0], [12, 11, 2])
        for a, b in [(-11, -8), (8, 11)]:
            fixed = fixed + box([a, -2, 1.8], [b, 2, 10.1])
        torsion = mf.Manifold.cylinder(18, t / 2, t / 2, 64).rotate([0, 90, 0]).translate([-9, 0, 10])
        lever = box([-2.4, -8, 9.1], [2.4, 8, 10.9])
        stem = box([-2, 6.7, 10.5], [2, 7.9, 13.95])
        # Make the barb in Y/Z then rotate its extrusion axis to X.
        barb = prism_xz([(7.8, 12.3), (7.9 + h, 12.3), (7.9 + h, 13.1), (7.9, 14), (7.8, 14)], 3.6).rotate([0, 0, 90])
        # prism x becomes +Y, extrusion y becomes -X.
        fixed = fixed + torsion + lever + stem + barb
        moving = box([-12, -11, 17], [12, 11, 19])
        skirt = box([-4, 7.9 + c, 10], [4, 11, 17.3])
        window = box([-2 - c, 7.7, 12.3 - c], [2 + c, 11.2, 15.3])
        moving = moving + (skirt - window)
        anchor = [0, 7.9, 13]
        roi_center, roi_size = [0, 0, 11], [25, 23, 10]
        names = ["支架＋一体扭杆＋摇臂", "盖片与锁扣窗口"]
        regions = [
            region("root", "左右固定支架", [0, 0, 6], [24, 5, 10], "fixed"),
            region("elastic", "一体细扭杆", [0, 0, 10], [18, t, t], "elastic"),
            region("press", "后侧按压摇臂", [0, -5.5, 10], [5, 5, 2], "elastic"),
            region("catch", "前端倒扣与扣窗", [0, 8.5, 13], [6, 4, 4], "catch"),
        ]
        travel = 13.0
    elif preset_id == "annular":
        inner = 10.0
        radius = inner - c
        fixed = cylinder(12.8, 16) - cylinder(inner, 15, 2)
        # The continuous circumferential recess is a real annular undercut.
        fixed = fixed - cylinder(inner + h, 1.4 + 2 * c, 9.5 - c)
        neck = cylinder(radius, 10, 8) - cylinder(radius - t, 10.4, 7.8)
        bead = cylinder(radius + h, 0.4, 10.5) + cylinder(radius + 0.05, 1.0, 9.5, radius + h)
        bead = bead - cylinder(radius - t, 2, 9.2)
        moving = cylinder(13.3, 2, 18) + neck + bead
        anchor = [0, 0, 10.5]
        roi_center, roi_size = [0, 0, 10.5], [25, 25, 5]
        names = ["圆筒与连续环槽", "圆盖＋柔性插入环＋整圈凸缘"]
        regions = [
            region("root", "圆盖固定区", [0, 0, 19], [27, 27, 2], "fixed"),
            region("elastic", "连续薄壁插入环", [0, 0, 13], [21, 21, 10], "elastic"),
            region("catch", "整圈凸缘与环槽", [0, 0, 10.2], [23, 23, 2.4], "catch"),
        ]
        travel = 15.0
    else:
        raise ValueError("unknown preset")
    return dict(
        solids=[fixed, moving],
        names=names,
        anchor=anchor,
        roi_center=roi_center,
        roi_size=roi_size,
        regions=regions,
        travel_mm=travel,
    )


def check_geometry(g, p):
    part_reports = []
    for index, solid in enumerate(g["solids"]):
        mesh = to_trimesh(solid)
        part_reports.append(
            dict(
                id=f"part_{'ab'[index]}",
                watertight=bool(mesh.is_watertight),
                winding_consistent=bool(mesh.is_winding_consistent),
                components=len(solid.decompose()),
                volume_mm3=float(mesh.volume),
                bounds_mm=mesh.bounds.tolist(),
                faces=len(mesh.faces),
            )
        )
    overlap = float((g["solids"][0] ^ g["solids"][1]).volume())
    samples = []
    for offset in np.linspace(g["travel_mm"], 0, 41):
        volume = float((g["solids"][0] ^ g["solids"][1].translate([0, 0, float(offset)])).volume())
        samples.append(dict(offset_m=float(offset) * 0.001, offset_mm=float(offset), overlap_mm3=round(volume, 7)))
    collisions = [x for x in samples if x["overlap_mm3"] > 1e-5]
    first_collision_index = next((i for i, x in enumerate(samples) if x["overlap_mm3"] > 1e-5), None)
    previous_clear = (
        samples[first_collision_index - 1]["offset_m"]
        if first_collision_index is not None and first_collision_index > 0
        else None
    )
    mesh_ok = all(
        x["watertight"] and x["winding_consistent"] and x["components"] == 1 and x["volume_mm3"] > 0
        for x in part_reports
    )
    checks = [
        dict(
            id="mesh",
            label="闭合与连通",
            status="pass" if mesh_ok else "fail",
            detail="逐件实际检查闭合网格、法线、单实体连通及正体积。",
        ),
        dict(
            id="static",
            label="锁定姿态静态干涉",
            status="pass" if overlap < 1e-5 else "fail",
            detail=f"两实体布尔交集 {overlap:.6f} mm³。",
        ),
        dict(
            id="undercut",
            label="模板倒扣约束",
            status="pass",
            detail=f"参数约束：突出量减间隙 = {p['hook_mm'] - p['clearance_mm']:.3f} mm；这不是保持力测量。",
        ),
        dict(
            id="rigid_path",
            label="刚体路径 · 41 姿态",
            status="review" if collisions else "pending",
            detail=f"{len(collisions)} 个离散姿态有刚性穿插；仅用于提示演示停止位置，不证明连续路径或弹性装配。",
        ),
        dict(
            id="elastic",
            label="弹性装配路径",
            status="pending",
            detail="未求解变形；刚性分离/接近动画只解释空间关系，不能证明实际装入或释放。",
        ),
        dict(
            id="force",
            label="保持力与寿命",
            status="pending",
            detail="未指定材料允许应变、未做 FEA 或实物拆装；不能给出合格结论。",
        ),
        dict(
            id="print",
            label="打印适配",
            status="pending",
            detail="STL 为几何样件，仍需检查朝向、支撑、层向和实际间隙。",
        ),
    ]
    return dict(
        status="geometry_failed"
        if any(c["status"] == "fail" for c in checks)
        else "needs_elastic_and_physical_validation",
        checks=checks,
        parts=part_reports,
        static_overlap_mm3=overlap,
        real_llm_invocation=False,
        fea_performed=False,
        rigid_path_samples=samples,
        first_contact_offset_m=collisions[0]["offset_m"] if collisions else None,
        previous_clear_offset_m=previous_clear,
        discrete_collision_step_m=g["travel_mm"] * 0.001 / 40,
        physical_print_performed=False,
        continuous_collision_checked=False,
        elastic_simulation_performed=False,
        limitations=[
            "四种均为局部几何教学试件，不是经力学验证的量产连接件。",
            "数据来自确定性参数模板，没有模型自由推理。",
            "弹性区只是几何与说明标注；没有根据材料求解真实形变或应力。",
            "动画中的零件分离运动不能当作可装配性证明。",
            "原兔形壳体和旧连接设计项目未修改。",
        ],
    )


def state_path():
    return OUTPUTS / "project.json"


def current_project():
    if state_path().exists():
        return json.loads(state_path().read_text(encoding="utf-8"))
    return generate({"preset_id": "cantilever"})


def publish(project):
    tmp = state_path().with_suffix(".tmp")
    save_json(tmp, project)
    tmp.replace(state_path())


def generate(payload, publish_current=True):
    begin = time.perf_counter()
    previous = json.loads(state_path().read_text(encoding="utf-8")) if state_path().exists() else None
    if "revision" in payload:
        raw = payload["revision"]
        if isinstance(raw, bool) or not isinstance(raw, (float, int)) or not math.isfinite(raw) or int(raw) != raw:
            raise ValueError("revision must be an integer")
        if not previous or int(raw) != previous["revision"]:
            raise RuntimeError("preset revision conflict; refresh before editing")
    preset_id, p, spec = validate(payload, previous)
    existing = [int(x.name[1:]) for x in (OUTPUTS / "revisions").glob("r[0-9]*") if x.name[1:].isdigit()]
    revision = max([0] + existing) + 1
    folder = OUTPUTS / "revisions" / f"r{revision:04d}"
    folder.mkdir(parents=True, exist_ok=False)
    g = build(preset_id, p)
    report = check_geometry(g, p)
    if report["status"] == "geometry_failed":
        save_json(folder / "failed_report.json", report)
        raise ValueError("preset geometry failed; previous project retained; see " + str(folder / "failed_report.json"))
    colors = [[73, 158, 173, 255], [241, 174, 79, 255]]
    parts = []
    urlbase = "/outputs/presets/revisions/" + folder.name + "/"
    assembly = trimesh.Scene()
    for i, (solid, name) in enumerate(zip(g["solids"], g["names"])):
        id = "part_" + "ab"[i]
        export_solid(solid, folder, id, colors[i])
        part_mesh = trimesh.load(folder / f"{id}.glb", force="mesh")
        assembly.add_geometry(part_mesh, node_name=id, geom_name=id)
        parts.append(
            dict(
                id=id,
                name=name,
                url=urlbase + id + ".glb",
                color=["#499ead", "#f1ae4f"][i],
                role=["fixed", "moving"][i],
                assembly_role=["fixed", "moving"][i],
            )
        )
    assembly.export(folder / "assembly.glb")
    print_meshes = []
    cursor = 0.0
    for solid in g["solids"]:
        mesh = to_trimesh(solid)
        width = float(mesh.extents[0])
        mesh.apply_translation(-mesh.bounds[0] + [cursor, 0, 0])
        print_meshes.append(mesh)
        cursor += width + 8.0
    trimesh.util.concatenate(print_meshes).export(folder / "coupon_pair_print_layout.stl")
    save_json(
        folder / "parameters.json",
        dict(
            schema="connection-presets.parameters/v1",
            preset_id=preset_id,
            revision=revision,
            units="mm",
            parameters=p,
            source_url=SOURCE_URL,
            generator_sha256=sha(Path(__file__)),
        ),
    )
    save_json(folder / "report.json", report)
    artifacts = []
    for file in sorted(folder.iterdir()):
        artifacts.append(
            dict(
                id=file.name,
                label=file.name,
                url=urlbase + file.name,
                absolute_path=str(file),
                kind=file.suffix[1:],
                bytes=file.stat().st_size,
                sha256=sha(file),
            )
        )
    connection = dict(
        anchor_m=viewer_point(g["anchor"]),
        roi_center_m=viewer_point(g["roi_center"]),
        roi_size_m=viewer_size(g["roi_size"]),
        assembly_direction=[0, 1, 0],
        travel_m=g["travel_mm"] * 0.001,
        moving_part_ids=["part_b"],
        mechanism_note=spec["mechanism_note"],
        regions=g["regions"],
        motion_kind="rigid_illustration_only",
        coordinate_system="meters/Y-up",
        engagement_depth_mm=p["hook_mm"] - p["clearance_mm"],
        rigid_path_samples=report["rigid_path_samples"],
        first_contact_offset_m=report["first_contact_offset_m"],
        previous_clear_offset_m=report["previous_clear_offset_m"],
        discrete_collision_step_m=report["discrete_collision_step_m"],
        elastic_motion_note=(
            "连续环体径向收缩/扩张，需要环向变形求解。"
            if preset_id == "annular"
            else "按压后侧摇臂，绕一体细扭杆轴扭转；本次不驱动假弹性形变。"
            if preset_id == "torsion"
            else "自由端朝查看器 -X 方向让位；本次不驱动假弹性形变。"
        ),
    )
    if preset_id == "torsion":
        connection.update(elastic_axis=[1, 0, 0], elastic_pivot_m=[0, 0.010, 0])
    elif preset_id != "annular":
        connection["elastic_direction"] = [-1, 0, 0]
    else:
        connection["elastic_mode"] = "radial"
    history = (previous or {}).get("history", []) + [
        dict(
            revision=revision,
            preset_id=preset_id,
            parameters=p,
            report_url=urlbase + "report.json",
            created_at=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        )
    ]
    project = dict(
        schema="connection-presets.project/v1",
        id="connection-presets",
        preset_id=preset_id,
        name=spec["name"] + " · 几何教学试件",
        revision=revision,
        units="mm",
        viewer_units="m",
        viewer_up="Y",
        parameters=p,
        parts=parts,
        artifacts=artifacts,
        report=report,
        connection=connection,
        history=history,
        source_url=SOURCE_URL,
        source=dict(url=SOURCE_URL, name="Formlabs 四类卡扣机制参考"),
        scope="local_geometric_teaching_specimen",
        elapsed_ms=round((time.perf_counter() - begin) * 1000),
        capabilities=dict(
            real_geometry=True,
            parametric=True,
            real_llm=False,
            fea=False,
            elastic_simulation=False,
            physical_print=False,
            old_camera_project_modified=False,
        ),
    )
    save_json(folder / "project.json", project)
    if publish_current:
        publish(project)
    return project


def initialize(refresh=False):
    path = OUTPUTS / "examples.json"
    if path.exists() and not refresh:
        if not state_path().exists():
            first = json.loads(path.read_text(encoding="utf-8"))["examples"][0]
            publish(json.loads((ROOT / first["project_url"].lstrip("/")).read_text(encoding="utf-8")))
        return json.loads(path.read_text(encoding="utf-8"))
    projects = []
    for spec in catalog()["presets"]:
        projects.append(generate({"preset_id": spec["id"], **spec["defaults"]}, publish_current=False))
    examples = dict(
        source_url=SOURCE_URL,
        examples=[
            dict(
                preset_id=p["preset_id"],
                revision=p["revision"],
                project_url=f"/outputs/presets/revisions/r{p['revision']:04d}/project.json",
                assembly_url=next(x["url"] for x in p["artifacts"] if x["id"] == "assembly.glb"),
            )
            for p in projects
        ],
    )
    save_json(path, examples)
    publish(projects[0])
    save_json(OUTPUTS / "catalog.json", catalog())
    return examples


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--initialize", action="store_true")
    parser.add_argument("--refresh-examples", action="store_true")
    parser.add_argument("--preset", choices=[x["id"] for x in CATALOG], default="cantilever")
    args = parser.parse_args()
    result = initialize(refresh=args.refresh_examples) if args.initialize else generate({"preset_id": args.preset})
    print(
        json.dumps(
            result if args.initialize else {"revision": result["revision"], "checks": result["report"]["checks"]},
            ensure_ascii=False,
            indent=2,
        )
    )
