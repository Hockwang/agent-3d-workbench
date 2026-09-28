"""SPEC.md §5 第 10/11 条：工程读回的数学 + 读回闸门（不依赖真实 Bambu Studio）。

手工合成的"Bambu 风格工程 3MF"结构对照了一份真实捕获的样本（2026-09-19，
`prepare --shape figurine` 对 5 件真实手办 STL 端到端产出的
`plate_01.project.3mf`，解包后核对过 `3D/3dmodel.model` 与
`Metadata/model_settings.config` 的实际内容）：真实 Bambu 输出里顶层
`<object>` 不带我们写进去的 `name` 属性、几何另存在
`<components><component path=".../object_N.model">` 指向的独立文件里；而
`read_project_transforms`/`compare_project_transforms` 从头到尾只读顶层
`<object id>`（不追踪 `<components>` 指向的几何文件）+
`<build><item objectid transform>` + `Metadata/model_settings.config` 里
`<object id><metadata key="name"><part><metadata key="source_offset_*">`——
这份合成 fixture 只需要复现这个"解析相关"的子集，几何本身留空（反正
`read_project_transforms` 从不读几何）。
"""

from __future__ import annotations

import time
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile, ZIP_DEFLATED

import numpy as np
import pytest
import trimesh

from print_prep import export3mf

CORE_NS = export3mf.CORE_NS


def test_geometry_3mf_preserves_close_float64_vertices(tmp_path):
    mesh = trimesh.creation.icosphere(subdivisions=1)
    mesh.vertices[0] = [100.000000001, 0, 0]
    mesh.vertices[1] = [100.000000002, 0, 0]
    path = tmp_path / "precise.3mf"
    placements = [{"part": "mesh", "T": np.eye(4).tolist()}]
    export3mf.write_geometry_3mf(path, {"mesh": mesh}, placements)
    report = export3mf.read_back_geometry_3mf(path, {"mesh": mesh}, placements)
    assert report["parts"]["mesh"]["vertices_preserved"]
    assert report["parts"]["mesh"]["faces_match"]


def test_project_gate_rejects_changed_topology(tmp_path):
    mesh = trimesh.creation.icosphere(subdivisions=1)
    damaged = mesh.copy()
    damaged.vertices[1] = damaged.vertices[0]
    path = tmp_path / "damaged.3mf"

    def write_project(item):
        export3mf.write_geometry_3mf(path, {"mesh": item}, [{"part": "mesh", "T": np.eye(4).tolist()}])
        # Bambu stores names in metadata and uses numeric resource IDs.
        with ZipFile(path) as archive:
            entries = {n: archive.read(n) for n in archive.namelist()}
        root = ET.fromstring(entries["3D/3dmodel.model"])
        for obj in root.findall(f".//{{{CORE_NS}}}object"):
            obj.attrib.pop("name", None)
        entries["3D/3dmodel.model"] = ET.tostring(root)
        with ZipFile(path, "w", ZIP_DEFLATED) as archive:
            for name, raw in entries.items():
                archive.writestr(name, raw)

    write_project(damaged)
    result = export3mf.compare_project_geometry(path, {"mesh": mesh})
    assert not result["pass"]
    write_project(mesh)
    assert export3mf.compare_project_geometry(path, {"mesh": mesh})["pass"]


def _write_synthetic_bambu_project(path: Path, parts: list[dict]) -> None:
    """`parts` 每项：`{"object_id": int, "stored_name": str,
    "source_offset": (x,y,z), "T_file": 4x4}`——`T_file` 是文件里 build item
    实际写的 `(R_b, t_b)`。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    ET.register_namespace("", CORE_NS)
    root = ET.Element(f"{{{CORE_NS}}}model", {"unit": "millimeter"})
    resources = ET.SubElement(root, "resources")
    build = ET.SubElement(root, "build")
    config = ET.Element("config")

    for p in parts:
        oid = str(p["object_id"])
        # 顶层 object 故意不带 name 属性——真实 Bambu 输出就是这样，名字只在
        # model_settings.config 里能找到。
        ET.SubElement(resources, "object", {"id": oid, "type": "model"})
        ET.SubElement(
            build,
            "item",
            {
                "objectid": oid,
                "transform": export3mf.serialize_transform(p["T_file"]),
            },
        )

        cfg_obj = ET.SubElement(config, "object", {"id": oid})
        ET.SubElement(cfg_obj, "metadata", {"key": "name", "value": p["stored_name"]})
        part_el = ET.SubElement(cfg_obj, "part", {"id": oid, "subtype": "normal_part"})
        ox, oy, oz = p["source_offset"]
        ET.SubElement(part_el, "metadata", {"key": "source_offset_x", "value": f"{ox}"})
        ET.SubElement(part_el, "metadata", {"key": "source_offset_y", "value": f"{oy}"})
        ET.SubElement(part_el, "metadata", {"key": "source_offset_z", "value": f"{oz}"})

    with ZipFile(path, "w", ZIP_DEFLATED) as z:
        z.writestr("3D/3dmodel.model", ET.tostring(root, encoding="utf-8", xml_declaration=True))
        z.writestr("Metadata/model_settings.config", ET.tostring(config, encoding="utf-8", xml_declaration=True))


def _rotation_z(angle_rad: float) -> np.ndarray:
    c, s = np.cos(angle_rad), np.sin(angle_rad)
    return np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]])


def _make_transform(R: np.ndarray, t) -> np.ndarray:
    T = np.eye(4)
    T[:3, :3] = R
    T[:3, 3] = t
    return T


# ---------------------------------------------------------------------------
# SPEC.md §5 第 10 条：工程读回的数学
# ---------------------------------------------------------------------------


def test_compare_project_transforms_scenario_a_not_moved(tmp_path):
    """请求 = 绕 Z 90 度 + 平移；Bambu 把几何按 `offset` 居中存储，如果它没有
    真的挪动对象，修正掉居中偏移后应与请求完全一致——这是对公式
    `t_b - R_b @ offset` 的正面验证（`R_b != I` 时若错用 `t_b - offset`，
    这里会假报 `moved=True`）。"""
    R = _rotation_z(np.pi / 2)
    t_req = np.array([50.0, 60.0, 20.0])
    offset = np.array([7.0, -3.0, 11.0])
    T_req = _make_transform(R, t_req)

    t_file = t_req + R @ offset  # 文件里存的 t_b = t_req + R_b @ offset
    T_file = _make_transform(R, t_file)

    path = tmp_path / "scenario_a.project.3mf"
    _write_synthetic_bambu_project(
        path,
        [
            {"object_id": 2, "stored_name": "top", "source_offset": offset, "T_file": T_file},
        ],
    )

    result = export3mf.compare_project_transforms(path, [{"part": "top", "T": T_req.tolist()}])
    assert result["unmatched_parts"] == []
    assert result["bambu_moved_objects"] is False
    assert result["diff"]["max_translation_diff_mm"] < 1e-6
    assert result["diff"]["max_rotation_diff"] < 1e-9


def test_compare_project_transforms_scenario_b_really_moved(tmp_path):
    """场景 B：Bambu 在居中偏移之外真的把对象挪动了 `(4, -10, 0)`——平移差应
    约等于 `|(4,-10,0)| ≈ 10.77mm`。"""
    R = _rotation_z(np.pi / 2)
    t_req = np.array([50.0, 60.0, 20.0])
    offset = np.array([7.0, -3.0, 11.0])
    delta = np.array([4.0, -10.0, 0.0])
    T_req = _make_transform(R, t_req)

    t_file = (t_req + delta) + R @ offset
    T_file = _make_transform(R, t_file)

    path = tmp_path / "scenario_b.project.3mf"
    _write_synthetic_bambu_project(
        path,
        [
            {"object_id": 2, "stored_name": "top", "source_offset": offset, "T_file": T_file},
        ],
    )

    result = export3mf.compare_project_transforms(path, [{"part": "top", "T": T_req.tolist()}])
    assert result["unmatched_parts"] == []
    assert result["bambu_moved_objects"] is True
    expected_diff = float(np.linalg.norm(delta))
    assert expected_diff == pytest.approx(10.7703296, abs=1e-4)
    assert result["diff"]["max_translation_diff_mm"] == pytest.approx(expected_diff, abs=1e-6)


def test_compare_project_transforms_scenario_c_unmatched_name(tmp_path):
    """场景 C：两件里一件在工程文件里的名字跟请求对不上（既非精确匹配也非
    "加了扩展名"式的宽松匹配）——`unmatched_parts` 必须非空，且
    `bambu_moved_objects` 强制为 True，不能因为"另一件没动"就整体报 False。"""
    R = np.eye(3)
    offset = np.zeros(3)

    t_req_top = np.array([10.0, 20.0, 0.0])
    T_req_top = _make_transform(R, t_req_top)

    t_req_bracket = np.array([100.0, 5.0, 0.0])
    T_req_bracket = _make_transform(R, t_req_bracket)

    path = tmp_path / "scenario_c.project.3mf"
    _write_synthetic_bambu_project(
        path,
        [
            {"object_id": 2, "stored_name": "top", "source_offset": offset, "T_file": T_req_top},
            {"object_id": 4, "stored_name": "unrelated_component", "source_offset": offset, "T_file": T_req_bracket},
        ],
    )

    result = export3mf.compare_project_transforms(
        path,
        [
            {"part": "top", "T": T_req_top.tolist()},
            {"part": "bracket", "T": T_req_bracket.tolist()},
        ],
    )
    assert result["unmatched_parts"] == ["bracket"]
    assert result["bambu_moved_objects"] is True
    assert result["used_positional_fallback"] is False


def test_compare_project_transforms_tolerates_extension_suffix(tmp_path):
    """defect 2 的真实复现：请求名 `face`，Bambu 存储的名字被加了扩展名变成
    `face.stl`；这件实际挪了 90mm。宽松匹配要把它捞回来参与比较（不能因为
    精确匹配失败就整体丢件、静默报成"没动"），并在 `matched_by` 里如实标出
    用了宽松匹配。"""
    R = np.eye(3)
    offset = np.zeros(3)
    t_req = np.array([0.0, 0.0, 0.0])
    T_req = _make_transform(R, t_req)
    T_file = _make_transform(R, t_req + np.array([90.0, 0.0, 0.0]))

    path = tmp_path / "scenario_ext.project.3mf"
    _write_synthetic_bambu_project(
        path,
        [
            {"object_id": 2, "stored_name": "face.stl", "source_offset": offset, "T_file": T_file},
        ],
    )

    result = export3mf.compare_project_transforms(path, [{"part": "face", "T": T_req.tolist()}])
    assert result["unmatched_parts"] == []
    assert result["bambu_moved_objects"] is True
    assert result["diff"]["max_translation_diff_mm"] == pytest.approx(90.0, abs=1e-6)
    assert result["diff"]["parts"]["face"]["matched_by"] == "loose_extension"


# ---------------------------------------------------------------------------
# SPEC.md §5 第 11 条：读回闸门
# ---------------------------------------------------------------------------


def test_read_back_geometry_gate_catches_symmetric_rotation_mismatch(tmp_path):
    """20mm 立方体对绕 Z 90 度旋转是对称的——逐顶点距离几乎为 0，光看距离测
    不出"文件里其实写的是单位阵、跟请求的旋转对不上"；`pass` 必须同时要求
    `transform_matches_input`。"""
    mesh = trimesh.creation.box(extents=[20.0, 20.0, 20.0])
    path = tmp_path / "cube.geometry.3mf"

    # 文件里写的是单位阵（模拟"写出时用错/被后处理覆盖成了单位阵"）。
    export3mf.write_geometry_3mf(path, {"cube": mesh}, [{"part": "cube", "T": np.eye(4).tolist()}])

    # 但请求（这次读回要校验的摆盘变换）其实是绕 Z 90 度。
    R = _rotation_z(np.pi / 2)
    T_requested = _make_transform(R, np.zeros(3))
    result = export3mf.read_back_geometry_3mf(
        path, {"cube": mesh}, [{"part": "cube", "T": T_requested.tolist()}], tol_mm=0.01
    )

    assert result["parts"]["cube"]["max_vertex_distance_mm"] < 0.01, (
        "20mm 立方体绕 Z 90 度旋转后逐顶点距离应几乎为 0（对称性验证前提，否则本测试测的就不是文中要测的那个坑）"
    )
    assert result["parts"]["cube"]["transform_matches_input"] is False
    assert result["pass"] is False


# ---------------------------------------------------------------------------
# 写出性能：百万面级不得逐元素建 XML 树
# ---------------------------------------------------------------------------


def test_write_geometry_3mf_million_face_performance(tmp_path):
    mesh = trimesh.creation.icosphere(subdivisions=8)
    assert len(mesh.faces) > 1_000_000, f"测试前提不成立：细分球只有 {len(mesh.faces)} 面"

    path = tmp_path / "sphere.geometry.3mf"
    placements = [{"part": "sphere", "T": np.eye(4).tolist()}]

    t0 = time.perf_counter()
    export3mf.write_geometry_3mf(path, {"sphere": mesh}, placements)
    elapsed = time.perf_counter() - t0
    assert elapsed < 15.0, f"写出 {len(mesh.faces)} 面耗时 {elapsed:.2f}s，超过 15s 预算"

    result = export3mf.read_back_geometry_3mf(path, {"sphere": mesh}, placements, tol_mm=0.01)
    assert result["pass"] is True
