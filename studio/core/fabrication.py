"""Shared local fabrication contracts: explicit plans, immutable inputs, checked solids."""

from pathlib import Path
import hashlib
import math

import numpy as np
import trimesh

from studio.core.editor import EditorError, _check_static
from studio.core.kernels import mechanical_geometry as g
from studio.i18n import register


register(
    {
        "fabrication.invalid": {"en": "Invalid fabrication parameter: {field}", "zh-CN": "制造参数无效：{field}"},
        "fabrication.input": {
            "en": "Expected {count} static, closed, connected mesh objects with unique names",
            "zh-CN": "需要 {count} 个名称唯一、静态、闭合且连通的网格对象",
        },
        "fabrication.geometry": {"en": "Fabrication check failed: {check}", "zh-CN": "制造几何检查未通过：{check}"},
        "fabrication.connect_title": {"en": "Locating pins and blind sockets", "zh-CN": "定位销与盲孔"},
        "fabrication.connect_description": {
            "en": "Machine two closed mating parts at explicit centers/axes. Round or keyed separate pins, conservative socket-wall containment, insertion samples and STL/GLB reports.",
            "zh-CN": "按明确的接缝中心和轴向加工两个闭合部件。圆形或 D 形独立销、保守孔壁包络检查、插拔采样及 STL/GLB 报告。",
        },
        "fabrication.color_title": {"en": "Palette-guided color inlays", "zh-CN": "按调色板制作分色嵌件"},
        "fabrication.color_description": {
            "en": "Sample face colors/UV textures against an explicit palette. Extrude outward-facing patches inward along one pull direction; deliver closed inserts, a pocketed body and sampled removal checks.",
            "zh-CN": "按明确调色板采样面颜色或 UV 贴图，沿一个拔出方向将朝外色块向内加厚，交付闭合嵌件、挖槽主体和拔出采样检查。",
        },
        "fabrication.joint_title": {"en": "Install a local joint module", "zh-CN": "安装本地关节模块"},
        "fabrication.joint_description": {
            "en": "Machine explicit host parts and attach a pin hinge, slew, slider or split ball socket. Requires a frame, anchors and bounded machining zone; hardware and physical calibration remain explicit.",
            "zh-CN": "在明确主体上加工并安装销铰、回转、滑轨或分体球窝。需要坐标架、锚点和有限加工区；五金与实物标定单独列出。",
        },
        "fabrication.motion_title": {"en": "Combined joint configuration check", "zh-CN": "组合关节姿态检查"},
        "fabrication.motion_description": {
            "en": "Check a bounded Cartesian grid or explicit URDF configurations, including mixed joint poses. Reports exact intersections at samples and sampled clear configurations, never continuous safety.",
            "zh-CN": "检查有限笛卡尔网格或明确的 URDF 姿态，包括混合关节组合。报告采样点实体相交与无碰撞姿态，不承诺连续安全。",
        },
    }
)

CATALOG = [
    {
        "id": name,
        "title": f"fabrication.{prefix}_title",
        "description": f"fabrication.{prefix}_description",
        "engine": "python",
        "params": {},
    }
    for name, prefix in [
        ("connect-parts", "connect"),
        ("color-inlays", "color"),
        ("install-joint", "joint"),
        ("motion-check", "motion"),
    ]
]

_EXAMPLES = {
    "connect-parts": {
        "parts": ["negative_side", "positive_side"],
        "connectors": [
            {
                "center_mm": [0, 0, 0],
                "axis": [0, 0, 1],
                "profile": "keyed",
                "radius_mm": 2,
                "depth_mm": 6,
                "clearance_mm": 0.2,
                "min_wall_mm": 1.6,
            }
        ],
    },
    "color-inlays": {
        "palette_rgb": [[0, 0, 255], [255, 0, 0]],
        "pull_direction": [0, 0, 1],
        "depth_mm": 1.2,
        "clearance_mm": 0.15,
        "min_patch_area_mm2": 4,
    },
    "install-joint": {
        "parts": ["fixed_host", "moving_host"],
        "family": "pin_hinge",
        "center_mm": [0, 0, 0],
        "axis": [0, 0, 1],
        "x_hint": [1, 0, 0],
        "anchors_mm": [[-25, 0, 0], [30, 0, 0]],
        "machining_box_mm": [[-40, -40, -20], [40, 40, 20]],
        "mount_radius_mm": 0.75,
    },
    "motion-check": {"sampling": "grid", "steps": 5},
}
for _entry in CATALOG:
    _entry["params"] = _EXAMPLES[_entry["id"]]


def invalid(field):
    raise EditorError.coded("fabrication.invalid", field=field)


def require(condition, check):
    if not condition:
        raise EditorError.coded("fabrication.geometry", check=check)


def scalar(p, key, default, lo=0, hi=10000):
    value = p.get(key, default)
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or not lo < value <= hi
    ):
        invalid(key)
    return float(value)


def vector(value, field, direction=False):
    try:
        v = np.asarray(value, dtype=float)
    except (ValueError, TypeError):
        invalid(field)
    if v.shape != (3,) or not np.isfinite(v).all() or (direction and np.linalg.norm(v) < 1e-8):
        invalid(field)
    return v / np.linalg.norm(v) if direction else v


def inputs(w, count):
    from studio.core.task_operations import scene_input

    items, hashes = {}, {}
    for filename in w["inputs"]:
        path = Path(filename)
        _check_static(path)
        hashes[str(path.resolve())] = hashlib.sha256(path.read_bytes()).hexdigest()
        scene = scene_input(path)
        for node in scene.graph.nodes_geometry:
            transform, key = scene.graph[node]
            m = scene.geometry[key].copy()
            m.apply_transform(transform)
            if node in items:
                invalid("unique object names")
            # Merge coincident geometry vertices only when testing solidity; keep
            # the original UV/material data for palette sampling.
            s = g.solid(m)
            if len(s.decompose()) != 1:
                invalid("one connected solid per object")
            items[node] = (m, s)
    if len(items) != count:
        raise EditorError.coded("fabrication.input", count=count)
    return items, hashes


def checked_mesh(s):
    m = g.mesh(s)
    require(m.is_volume and len(s.decompose()) == 1, "closed_connected_output")
    return m


def emit(w, solids, report, colors=None):
    from studio.core.task_operations import deliver

    meshes = {name: checked_mesh(s) for name, s in solids.items()}
    for name, color in (colors or {}).items():
        meshes[name].visual.face_colors = [*color, 255]
    report.update(units="mm", physical_calibration="pending", continuous_motion_checked=False)
    report["parts"] = [
        {
            "name": n,
            "volume_mm3": float(m.volume),
            "extents_mm": m.extents.tolist(),
            "watertight": bool(m.is_watertight),
        }
        for n, m in meshes.items()
    ]
    deliver(meshes, Path(w["output"]), report)
    # Read the deliverable back, rather than assuming serialization retained it.
    for name, m in meshes.items():
        again = trimesh.load_mesh(Path(w["output"]) / f"{name}.stl")
        require(again.is_volume and np.allclose(again.bounds, m.bounds, atol=1e-5), "stl_readback")


def run(template, w):
    if template == "connect-parts":
        from studio.core.connect_parts import run as operation
    elif template == "color-inlays":
        from studio.core.color_inlays import run as operation
    elif template == "install-joint":
        from studio.core.install_joint import run as operation
    elif template == "motion-check":
        from studio.core.motion_check import run as operation
    else:
        invalid("template")
    operation(w)
