"""Apply parameter-driven paired connectors to the current manual A/B source.

The four Formlabs-inspired ``presets`` are separate teaching specimens.  This
bridge uses the same frozen A/B source, revision history, Boolean geometry and
exports as ``manual.generate``; it does not transplant those teaching models
onto arbitrary imported parts.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

from backend import cutting, manual
from backend.engine import np


SCHEMA = "parametric-bridge.context/v1"

_COMMON = dict(shape="circle", style="prism", size_mm=5.5, depth_mm=5.5, size_tolerance_mm=0.2, depth_tolerance_mm=0.1)
_FAMILIES = (
    dict(
        id="plug",
        name="插头与配对插槽",
        mechanism="paired_plug_socket",
        description="在当前 A/B 切面上生成一体插头和配合孔。",
        defaults=_COMMON,
        parameter_keys=("shape", "style", "size_mm", "depth_mm", "size_tolerance_mm", "depth_tolerance_mm"),
    ),
    dict(
        id="dowel",
        name="独立定位销",
        mechanism="separate_dowel",
        description="在两件上生成同轴孔，并另导出一根独立定位销。",
        defaults=_COMMON,
        parameter_keys=("shape", "style", "size_mm", "depth_mm", "size_tolerance_mm", "depth_tolerance_mm"),
    ),
    dict(
        id="snap",
        name="开槽卡扣柱",
        mechanism="split_axial_snap",
        description="在切面上生成开槽卡扣柱和配合孔；弹性与寿命仍待实测。",
        defaults={**_COMMON, "bulge_pct": 15, "space_pct": 30},
        parameter_keys=(
            "shape",
            "style",
            "size_mm",
            "depth_mm",
            "size_tolerance_mm",
            "depth_tolerance_mm",
            "bulge_pct",
            "space_pct",
        ),
    ),
    dict(
        id="dovetail",
        name="滑入式燕尾",
        mechanism="sliding_dovetail",
        description="沿切面滑入的燕尾舌和槽，包含整件刚体滑入干涉检查。",
        defaults={**_COMMON, "slide_length_mm": 8.8, "neck_ratio": 0.62},
        parameter_keys=(
            "size_mm",
            "depth_mm",
            "size_tolerance_mm",
            "depth_tolerance_mm",
            "slide_length_mm",
            "neck_ratio",
        ),
    ),
)


def catalog():
    """Describe native A/B connector families without conflating specimens."""
    return dict(
        schema="parametric-bridge.catalog/v1",
        families=copy.deepcopy(_FAMILIES),
        placement=dict(
            required=["center_mm", "normal"],
            optional=["rotation_deg", "flip"],
            coordinate_system="mm/Z-up",
            explanation="选当前 A/B 相对切面上的同一点；法线从 A 指向 B。",
        ),
        reference_presets=dict(
            catalog_url="/api/presets",
            project_url="/api/presets/project",
            applies_to_current_parts=False,
            scope="独立几何教学样件；未移植到任意 A/B 零件",
        ),
    )


def _alignment(source):
    """Prevent an older cut pair from silently standing in for a new GLB."""
    active = cutting.current()["source"]
    cut = source.get("cut")
    origin_sha = cut.get("full_source_sha256") if cut else None
    current_sha = active.get("sha256") if active else None
    if cut is None:
        status = "independent_pair"
        warning = "当前 A/B 是单独导入或示例配对，不来自整件 GLB 分件；请核对零件名称后设计连接件。"
    elif active is None:
        status = "source_unavailable"
        warning = "找不到生成这组 A/B 的整件来源；请重新载入并分件后再设计参数化连接件。"
    elif origin_sha != current_sha:
        status = "stale_pair"
        warning = "当前整件 GLB 与已保存的 A/B 分件来源不同；请先对当前 GLB 分件。"
    else:
        status = "aligned"
        warning = None
    return dict(
        status=status,
        aligned=status in ("aligned", "independent_pair"),
        warning=warning,
        paired_source_id=source["id"],
        active_cut_source_id=active.get("id") if active else None,
        paired_origin_sha256=origin_sha,
        active_cut_source_sha256=current_sha,
    )


def current():
    """Expose the active frozen A/B pair and its shared manual revision."""
    project = manual.current_project()
    source = project["source"]
    return dict(
        schema=SCHEMA,
        source_id=source["id"],
        revision=project["revision"],
        source=source,
        parts=project["parts"],
        connectors=project["connectors"],
        report=project["report"],
        alignment=_alignment(source),
        **{key: value for key, value in catalog().items() if key != "schema"},
    )


def check_placement(payload):
    """Read-only check that a picked face has an opposite face on the pair."""
    allowed = {"source_id", "revision", "center_mm", "normal", "part_id"}
    if (
        not isinstance(payload, dict)
        or set(payload) - allowed
        or not {"source_id", "revision", "center_mm", "normal"} <= set(payload)
    ):
        raise ValueError("落点检查需要 source_id、revision、center_mm 和 normal")
    part_id = payload.get("part_id", "part_a")
    if part_id not in ("part_a", "part_b"):
        raise ValueError("part_id 只能是 part_a 或 part_b")
    try:
        center = np.asarray(payload["center_mm"], dtype=float)
        clicked_normal = np.asarray(payload["normal"], dtype=float)
    except (TypeError, ValueError) as exc:
        raise ValueError("center_mm 和 normal 必须是三个有限数值") from exc
    if (
        center.shape != (3,)
        or clicked_normal.shape != (3,)
        or not np.isfinite(center).all()
        or not np.isfinite(clicked_normal).all()
        or not 0.9 <= np.linalg.norm(clicked_normal) <= 1.1
    ):
        raise ValueError("center_mm 和 normal 必须是三个有限数值，法线长度约为 1")
    normal = clicked_normal / np.linalg.norm(clicked_normal)
    if part_id == "part_b":
        normal = -normal
    result = dict(
        schema="paired-placement.check/v1",
        valid=False,
        reason=None,
        source_id=payload["source_id"],
        revision=payload["revision"],
        center_mm=center.tolist(),
        normal_a_to_b=normal.tolist(),
    )
    if not manual.SOURCE.is_file() or not manual.STATE.is_file():
        result["reason"] = "请先完成 A/B 分件，再放置连接件"
        return result
    source = json.loads(manual.SOURCE.read_text(encoding="utf-8"))
    project = json.loads(manual.STATE.read_text(encoding="utf-8"))
    if source["id"] != payload["source_id"] or project.get("source_id") != source["id"]:
        result["reason"] = "A/B 来源已变化，请刷新当前项目"
        return result
    if type(payload["revision"]) is not int or project.get("revision") != payload["revision"]:
        result["reason"] = "项目版本已更新，请刷新后再放置连接件"
        return result
    alignment = _alignment(source)
    if not alignment["aligned"]:
        result["reason"] = alignment["warning"]
        return result
    parts = source.get("parts")
    if not isinstance(parts, list) or len(parts) != 2 or any(not Path(part["stl"]).is_file() for part in parts):
        result["reason"] = "A/B 原始零件文件缺失，请重新分件"
        return result
    mesh_a, mesh_b = [manual._mesh(part["stl"]) for part in parts]
    on_a = manual._face_at(mesh_a, center, normal)
    on_b = manual._face_at(mesh_b, center, normal, opposite=True)
    if on_a and on_b:
        result["valid"] = True
        return result
    result["reason"] = (
        "这里是外表面，不是 A/B 共同切面；请点击分件后的相对断面"
        if on_a or on_b
        else "点击位置不在 A/B 相对的共同切面上；请重新选取切面"
    )
    return result


def design(payload):
    """Add or replace one parameterized connector on the active A/B pair.

    Existing manually placed connectors are retained.  The returned project is
    the ordinary ``manual-connectors.project/v1`` project so both interfaces
    see the same revision, report and printable exports.
    """
    allowed = {"source_id", "revision", "family_id", "placement", "parameters", "replace_id"}
    if (
        not isinstance(payload, dict)
        or set(payload) - allowed
        or not {"source_id", "revision", "family_id", "placement", "parameters"} <= set(payload)
    ):
        raise ValueError("parametric design requires source_id, revision, family_id, placement and parameters")
    family = next((item for item in _FAMILIES if item["id"] == payload["family_id"]), None)
    if family is None:
        raise ValueError("unknown A/B connector family; standalone teaching presets cannot be applied to this pair")
    placement = payload["placement"]
    parameters = payload["parameters"]
    if (
        not isinstance(placement, dict)
        or not {"center_mm", "normal"} <= set(placement)
        or set(placement) - {"center_mm", "normal", "rotation_deg", "flip"}
    ):
        raise ValueError("placement requires center_mm and normal; optional rotation_deg and flip")
    if not isinstance(parameters, dict) or set(parameters) - set(family["parameter_keys"]):
        raise ValueError("unsupported parameters for this A/B connector family")
    raw_revision = payload["revision"]
    if isinstance(raw_revision, bool) or not isinstance(raw_revision, int):
        raise ValueError("revision must be an integer")

    project = manual.current_project()
    if payload["source_id"] != project["source_id"]:
        raise RuntimeError("source changed; refresh the parametric mode")
    if raw_revision != project["revision"]:
        raise RuntimeError("revision conflict; refresh before editing")
    if not _alignment(project["source"])["aligned"]:
        raise RuntimeError("当前整件来源与 A/B 分件不一致；请先对当前 GLB 分件")

    connector = {**copy.deepcopy(family["defaults"]), **parameters, **placement, "type": family["id"]}
    existing = copy.deepcopy(project["connectors"])
    replace_id = payload.get("replace_id")
    if replace_id is not None:
        if not isinstance(replace_id, str) or not replace_id or not any(item["id"] == replace_id for item in existing):
            raise ValueError("replace_id must identify an existing connector")
        connector["id"] = replace_id
        connectors = [connector if item["id"] == replace_id else item for item in existing]
    else:
        connectors = existing + [connector]
    return manual.generate(dict(source_id=project["source_id"], revision=project["revision"], connectors=connectors))
