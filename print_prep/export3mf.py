"""print_prep.export3mf —— 几何 3MF 写出（局部系几何 + build item 摆盘变换）与读回校验。

写法改编自作者早期私有研究代码 `manufacturing_kit/engine/print_waveab_v0/kitlib/plate.py` 的
`export_bambu_3mf`/`read_back_3mf`（自有代码）：零件几何按局部系原样写入
`<object>`（不烤变换），摆盘变换整个存进 `<item transform="...">`——这样
`read_back_geometry_3mf` 验证的是"文件里存的变换 == 我们要求的摆盘变换"，而不是
"变换已经烤进顶点、读回来自然对得上"这种自证。变换序列化格式 = 4x4 齐次矩阵
前 3 行 4 列按列优先展开（12 个数），最后一行隐含 [0,0,0,1]，符合 3MF core
schema 与 Bambu Studio 的实际读法。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional, Sequence
from xml.etree import ElementTree as ET
from zipfile import ZipFile, ZIP_DEFLATED

import numpy as np
import trimesh
from scipy.spatial import cKDTree

from .messages import render

CORE_NS = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
CONTENT_TYPES_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>'
    "</Types>"
)
RELS_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Target="/3D/3dmodel.model" Id="rel0" '
    'Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>'
    "</Relationships>"
)


def serialize_transform(T) -> str:
    """4x4 齐次矩阵（`T @ v` 列向量约定）-> 3MF 的 12 个数字（按列拼接 T 的前
    4 列的转置），与 `parse_transform` 互为逆操作。"""
    block = np.asarray(T, dtype=float)[:3, :4]
    values = block.T.flatten()
    return " ".join(f"{v:.8f}" for v in values)


def parse_transform(text: Optional[str]) -> np.ndarray:
    matrix = np.eye(4)
    if text:
        values = np.array([float(x) for x in text.split()])
        matrix[:3, :] = values.reshape(4, 3).T
    return matrix


_XML_CHUNK_ROWS = 200_000  # SPEC.md §3.5：分块字符串拼接直接写进 zip，别逐元素建 XML 树


def _escape_xml_attr(value: str) -> str:
    """给要塞进 XML 属性值（双引号包裹）的字符串转义，跟 ElementTree 序列化
    属性值时做的事等价（`&`/`<`/`>`/`"` 四个字符）。"""
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _iter_xml_chunks(rows: np.ndarray, fmt) -> Any:
    """把 `rows`（N x 3 的 numpy 数组）按 `_XML_CHUNK_ROWS` 分块，每块用 `fmt`
    格式化成一整段字符串再 yield——只在块边界做一次大字符串拼接，避免千万级
    调用 `ElementTree.SubElement`/单独 `write()` 的开销。"""
    n = len(rows)
    for start in range(0, n, _XML_CHUNK_ROWS):
        chunk = rows[start : start + _XML_CHUNK_ROWS]
        yield "".join(fmt(*r) for r in chunk)


def _fmt_vertex(x: float, y: float, z: float) -> str:
    return f'<vertex x="{x:.17g}" y="{y:.17g}" z="{z:.17g}"/>'


def _fmt_triangle(a: int, b: int, c: int) -> str:
    return f'<triangle v1="{a}" v2="{b}" v3="{c}"/>'


def write_geometry_3mf(
    path: Path, meshes_by_name: dict[str, trimesh.Trimesh], placements: Sequence[dict[str, Any]]
) -> dict[str, Any]:
    """写一份几何 3MF：每个零件是一个顶层 object（局部系几何），build item 用
    3MF 标准 `transform` 属性存摆盘变换；`Metadata/model_settings.config` 挂
    零件名（`key="name"`）。

    `3D/3dmodel.model` 里的顶点/三角形用分块字符串拼接、经 `ZipFile.open(...,
    "w")` 流式写进 zip（SPEC.md §3.5）——原先逐顶点/逐三角建 `ElementTree`
    元素在 200 万面级要 ~20 秒、XML 树占 ~0.5 GB，千万面级会撑爆内存；分块
    写出的 XML 结构、元素名、命名空间与之前完全一致，`read_back_geometry_3mf`
    与 Bambu Studio 都照常能读。`Metadata/model_settings.config` 每个零件只有
    一个 `<object>`+一个 `<metadata>`，量级小，继续用 `ElementTree`。
    """
    path = Path(path)
    config = ET.Element("config")

    written = []
    build_items: list[tuple[int, str]] = []  # (object_id, transform 字符串)
    for obj_id, pl in enumerate(placements, start=1):
        name = pl["part"]
        build_items.append((obj_id, serialize_transform(np.asarray(pl["T"], dtype=float))))

        settings = ET.SubElement(config, "object", {"id": str(obj_id)})
        ET.SubElement(settings, "metadata", {"key": "name", "value": name})

    path.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(path, "w", ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", CONTENT_TYPES_XML)
        z.writestr("_rels/.rels", RELS_XML)

        with z.open("3D/3dmodel.model", "w") as fh:
            fh.write(b'<?xml version="1.0" encoding="UTF-8"?>')
            fh.write(
                f'<model xmlns="{CORE_NS}" unit="millimeter" xml:lang="en-US">'
                f'<metadata name="Application">print-prep</metadata><resources>'.encode("utf-8")
            )
            for obj_id, pl in enumerate(placements, start=1):
                name = pl["part"]
                mesh = meshes_by_name[name]
                name_attr = _escape_xml_attr(name)
                fh.write(f'<object id="{obj_id}" type="model" name="{name_attr}"><mesh><vertices>'.encode("utf-8"))
                for chunk in _iter_xml_chunks(mesh.vertices, _fmt_vertex):
                    fh.write(chunk.encode("utf-8"))
                fh.write(b"</vertices><triangles>")
                for chunk in _iter_xml_chunks(mesh.faces, _fmt_triangle):
                    fh.write(chunk.encode("utf-8"))
                fh.write(b"</triangles></mesh></object>")
                written.append(
                    {"object_id": obj_id, "part": name, "vertices": len(mesh.vertices), "faces": len(mesh.faces)}
                )
            fh.write(b"</resources><build>")
            for obj_id, transform_str in build_items:
                fh.write(f'<item objectid="{obj_id}" transform="{transform_str}"/>'.encode("utf-8"))
            fh.write(b"</build></model>")

        z.writestr("Metadata/model_settings.config", ET.tostring(config, encoding="utf-8", xml_declaration=True))

    return {"path": str(path), "objects": written}


def read_back_geometry_3mf(
    path: Path, meshes_by_name: dict[str, trimesh.Trimesh], placements: Sequence[dict[str, Any]], tol_mm: float = 0.01
) -> dict[str, Any]:
    """读回 3MF，按 build item 的 transform 属性把局部几何摆到装配系，跟"内存里
    的零件几何用同一个 placement 变换"逐顶点 KD-tree 比对（双向最近邻取较大者）。"""
    path = Path(path)
    T_by_name = {pl["part"]: np.asarray(pl["T"], dtype=float) for pl in placements}

    results: dict[str, Any] = {}
    max_error = 0.0
    with ZipFile(path) as z:
        assert z.testzip() is None, f"{path} is a corrupt zip"
        model = ET.fromstring(z.read("3D/3dmodel.model"))
        objects = {obj.get("id"): obj for obj in model.findall(f".//{{{CORE_NS}}}resources/{{{CORE_NS}}}object")}
        build_items = model.findall(f".//{{{CORE_NS}}}build/{{{CORE_NS}}}item")

        for item in build_items:
            obj = objects[item.get("objectid")]
            name = obj.get("name")
            mesh_el = obj.find(f"{{{CORE_NS}}}mesh")
            verts = np.array([[float(v.get(a)) for a in "xyz"] for v in mesh_el.find(f"{{{CORE_NS}}}vertices")])
            faces = np.array(
                [[int(t.get(a)) for a in ("v1", "v2", "v3")] for t in mesh_el.find(f"{{{CORE_NS}}}triangles")]
            )
            T_written = parse_transform(item.get("transform"))

            actual = trimesh.Trimesh(vertices=verts, faces=faces, process=False)
            actual.apply_transform(T_written)

            expected = meshes_by_name[name].copy()
            expected.apply_transform(T_by_name[name])

            d1 = float(cKDTree(expected.vertices).query(actual.vertices)[0].max())
            d2 = float(cKDTree(actual.vertices).query(expected.vertices)[0].max())
            err = max(d1, d2)
            max_error = max(max_error, err)
            results[name] = {
                "max_vertex_distance_mm": err,
                "n_vertices": len(verts),
                "n_faces": len(faces),
                "transform_matches_input": bool(np.allclose(T_written, T_by_name[name], atol=1e-6)),
                "faces_match": bool(np.array_equal(faces, meshes_by_name[name].faces)),
                "vertices_preserved": bool(np.array_equal(verts, meshes_by_name[name].vertices)),
            }

    transforms_ok = all(info["transform_matches_input"] for info in results.values())
    overall_pass = bool(
        max_error <= tol_mm
        and transforms_ok
        and set(results) == set(meshes_by_name)
        and all(x["faces_match"] and x["vertices_preserved"] for x in results.values())
    )
    return {"pass": overall_pass, "max_error_mm": max_error, "tol_mm": tol_mm, "parts": results}


def _parse_bambu_model_settings(z: ZipFile) -> dict[str, dict[str, Any]]:
    """解析 `Metadata/model_settings.config`（Bambu Studio 自己的元数据，无
    命名空间）：真实测过（2026-09-19，五件真实手办件 e2e）发现 Bambu Studio 写的
    `3D/3dmodel.model` 里 `<object>` 根本不带我们写进去的 `name` 属性——零件名
    实际存在这份文件的 `<object id><metadata key="name" value="...">` 里；同时
    Bambu Studio 会把每个零件的几何重新居中存储（`<part><metadata
    key="source_offset_{x,y,z}">` 记录了这个居中挪动量），不把这个偏移量减掉的
    话，"零件在 3MF 里的实际落点"会被误判成偏了一大截。返回
    `{objectid: {"name":..., "source_offset": np.ndarray(3,)}}`。
    """
    try:
        raw = z.read("Metadata/model_settings.config")
    except KeyError:
        return {}
    root = ET.fromstring(raw)
    result: dict[str, dict[str, Any]] = {}
    for obj in root.findall("object"):
        obj_id = obj.get("id")
        name = None
        for md in obj.findall("metadata"):
            if md.get("key") == "name":
                name = md.get("value")
                break
        offset = np.zeros(3)
        part = obj.find("part")
        if part is not None:
            offs = {}
            for md in part.findall("metadata"):
                key = md.get("key")
                if key in ("source_offset_x", "source_offset_y", "source_offset_z"):
                    offs[key] = float(md.get("value"))
            offset = np.array(
                [offs.get("source_offset_x", 0.0), offs.get("source_offset_y", 0.0), offs.get("source_offset_z", 0.0)]
            )
        result[obj_id] = {"name": name, "source_offset": offset}
    return result


def read_project_transforms(path: Path) -> dict[str, np.ndarray]:
    """读一份 Bambu Studio 导出的工程 3MF，返回 `{零件名: 修正过居中偏移后的
    build item transform}`——名字优先取自 `Metadata/model_settings.config`
    （见 `_parse_bambu_model_settings`），取不到才退回 `3D/3dmodel.model` 里
    `<object name="...">` 这条 3MF core schema 路径，再退回用 objectid 当名字。

    `source_offset` 记在**零件局部系**（存储顶点 = 源顶点 − offset），build item
    的 `(R_b, t_b)` 把存储顶点映到盘上：`plate_v = R_b @ (source_v - offset) +
    t_b = R_b @ source_v + (t_b - R_b @ offset)`。所以要拿掉居中偏移、还原成
    "对源几何的等效变换"，平移分量必须修正成 **`t_b - R_b @ offset`**，不是
    `t_b - offset`（SPEC.md §3.5）；两者只在 `R_b = I` 时相等，且 `--shape
    figurine` 的朝向策略 `upright` 恰好总是给出 `R = I`，会把这个 bug 精确遮住
    ——必须靠带旋转的朝向（如 `--shape mechanical` 的 `flat`）才测得出来。
    """
    path = Path(path)
    by_name: dict[str, np.ndarray] = {}
    with ZipFile(path) as z:
        model = ET.fromstring(z.read("3D/3dmodel.model"))
        object_names = {}
        for obj in model.findall(f".//{{{CORE_NS}}}resources/{{{CORE_NS}}}object"):
            object_names[obj.get("id")] = obj.get("name")
        settings = _parse_bambu_model_settings(z)
        for item in model.findall(f".//{{{CORE_NS}}}build/{{{CORE_NS}}}item"):
            obj_id = item.get("objectid")
            info = settings.get(obj_id, {})
            name = info.get("name") or object_names.get(obj_id) or f"object_{obj_id}"
            offset = info.get("source_offset", np.zeros(3))
            T = parse_transform(item.get("transform"))
            T[:3, 3] = T[:3, 3] - T[:3, :3] @ offset
            by_name[name] = T
    return by_name


_KNOWN_MESH_EXTENSIONS = (".stl", ".obj", ".ply", ".3mf", ".glb", ".gltf")


def _strip_known_extension(name: str) -> str:
    """去掉常见网格扩展名（大小写不敏感），用于容忍 Bambu Studio 给零件名加
    扩展名的情形（实测：请求名 `face`，工程文件里变成 `face.stl`）。没有已知
    扩展名时原样返回。"""
    lower = name.lower()
    for ext in _KNOWN_MESH_EXTENSIONS:
        if lower.endswith(ext):
            return name[: -len(ext)]
    return name


def compare_project_transforms(project_3mf: Path, requested_placements: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """把工程 3MF 里实际落地的 build item 变换跟我们请求的摆盘变换比较，报平移
    与旋转各自的最大差；差异超过 0.01mm / 1e-6 不算导出失败，但要如实报
    `bambu_moved_objects: true`（SPEC.md §3.5）。

    匹配顺序：① 精确按零件名匹配；② 对精确匹配不上的请求零件，容忍 Bambu 给
    名字加了扩展名（如 `face.stl` 对 `face`），逐个尝试宽松匹配（在 `per_part`
    里标 `matched_by: "loose_extension"`）；③ 前两步一个都没匹配上时（Bambu
    完全没保留我们写的 `name` 属性），整体退化为按 3MF 文件里出现的顺序跟请求
    列表按位置一一对应。

    **不许静默丢件**：精确/宽松匹配之后仍然对不上号的请求零件，会被列进返回值
    的 `unmatched_parts`；只要它非空，`bambu_moved_objects` 就强制为 `True`
    ——即使被丢掉的那件"看起来"没参与比较，也不能因此被漏报成"没动"。
    """
    requested_by_name = {pl["part"]: np.asarray(pl["T"], dtype=float) for pl in requested_placements}
    actual_by_name = read_project_transforms(project_3mf)

    matched_by_name: dict[str, np.ndarray] = {}
    loosely_matched: list[str] = []
    remaining_actual = dict(actual_by_name)
    for req_name in requested_by_name:
        if req_name in remaining_actual:
            matched_by_name[req_name] = remaining_actual.pop(req_name)
            continue
        stem = _strip_known_extension(req_name)
        for actual_name in list(remaining_actual):
            if _strip_known_extension(actual_name) == stem:
                matched_by_name[req_name] = remaining_actual.pop(actual_name)
                loosely_matched.append(req_name)
                break

    used_positional_fallback = False
    if not matched_by_name and requested_by_name and actual_by_name:
        used_positional_fallback = True
        req_names = [pl["part"] for pl in requested_placements]
        actual_values = list(actual_by_name.values())
        matched_by_name = dict(zip(req_names, actual_values))

    unmatched_parts = [] if used_positional_fallback else [n for n in requested_by_name if n not in matched_by_name]

    max_translation_diff = 0.0
    max_rotation_diff = 0.0
    per_part = {}
    for name, T_actual in matched_by_name.items():
        T_req = requested_by_name[name]
        # 平移差取欧氏距离（"这件挪了多远"），不是逐轴最大值——SPEC.md §5 第 10
        # 条场景 B 的数值判据（挪动 (4,-10,0) 应约等于 10.77mm = sqrt(4^2+10^2)）
        # 只有欧氏距离能对上，逐轴最大值会算成 10.0。
        translation_diff = float(np.linalg.norm(T_actual[:3, 3] - T_req[:3, 3]))
        rotation_diff = float(np.max(np.abs(T_actual[:3, :3] - T_req[:3, :3])))
        max_translation_diff = max(max_translation_diff, translation_diff)
        max_rotation_diff = max(max_rotation_diff, rotation_diff)
        per_part[name] = {
            "translation_diff_mm": translation_diff,
            "rotation_diff": rotation_diff,
            "matched_by": "loose_extension" if name in loosely_matched else "exact",
        }

    moved = bool(max_translation_diff > 0.01 or max_rotation_diff > 1e-6 or unmatched_parts)
    diff = {
        "max_translation_diff_mm": max_translation_diff,
        "max_rotation_diff": max_rotation_diff,
        "used_positional_fallback": used_positional_fallback,
        "parts": per_part,
    }
    return {
        "bambu_moved_objects": moved,
        "diff": diff,
        "unmatched_parts": unmatched_parts,
        "used_positional_fallback": used_positional_fallback,
    }


def topology_signature(mesh: trimesh.Trimesh) -> dict[str, int]:
    """Exact-position welding: UV seams are irrelevant, nearby vertices are not."""
    vertices, inverse = np.unique(np.asarray(mesh.vertices), axis=0, return_inverse=True)
    faces = inverse[np.asarray(mesh.faces)]
    edges = np.sort(np.concatenate((faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]])), axis=1)
    _, counts = np.unique(edges, axis=0, return_counts=True)
    return {
        "vertices": len(vertices),
        "faces": len(faces),
        "boundary_edges": int(np.count_nonzero(counts == 1)),
        "nonmanifold_edges": int(np.count_nonzero(counts > 2)),
        "collapsed_faces": int(
            np.count_nonzero((faces[:, 0] == faces[:, 1]) | (faces[:, 1] == faces[:, 2]) | (faces[:, 2] == faces[:, 0]))
        ),
    }


def compare_project_geometry(path: Path, sources: dict[str, trimesh.Trimesh]) -> dict[str, Any]:
    """Check geometry after the slicer's own serialization, not just transforms."""
    scene = trimesh.load_scene(path, process=False, allow_remote=False)
    with ZipFile(path) as archive:
        settings = ET.fromstring(archive.read("Metadata/model_settings.config"))
    actual_by_name = {}
    for obj in settings.findall("object"):
        metadata = {m.get("key"): m.get("value") for m in obj.findall("metadata")}
        name = _strip_known_extension(metadata.get("name", ""))
        parts = obj.findall("part")
        keys = [part.get("id") for part in parts] or [obj.get("id")]
        if not name or name in actual_by_name or any(key not in scene.geometry for key in keys):
            return {"pass": False, "error": render("export3mf.ambiguous_part_binding"), "parts": {}}
        actual_by_name[name] = trimesh.util.concatenate([scene.geometry[key] for key in keys])
    results = {}
    for name, expected in sources.items():
        if name not in actual_by_name:
            results[name] = {"pass": False, "error": render("export3mf.missing_output_part")}
            continue
        before, after = topology_signature(expected), topology_signature(actual_by_name[name])
        results[name] = {"pass": before == after, "source": before, "output": after}
    return {
        "pass": bool(results) and set(actual_by_name) == set(sources) and all(x["pass"] for x in results.values()),
        "parts": results,
    }
