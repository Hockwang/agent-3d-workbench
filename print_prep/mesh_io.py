"""print_prep.mesh_io —— 载入网格文件、连通性/水密性测量、床位判断、落盘。

坐标/连通性的两个坑（均已知问题，见同仓 memory）：
1. trimesh 4.12.2 的 `Scene.geometry.values()` 会丢节点变换——必须自己按
   `scene.graph` 逐节点取世界变换再应用，否则带节点平移/旋转的 GLB/GLTF/3MF
   场景会把子物体读到原点。
2. UV 缝会把同一个空间位置的顶点拆成好几份不同索引的顶点，直接在原始网格上
   测连通分量/水密性会把这类"假缝"误判成真的开口/断裂。要先丢掉 UV、按顶点
   位置重新焊接一份副本，再在副本上测（原始网格保持不变）。
"""

from __future__ import annotations

import hashlib
import math
from pathlib import Path
from typing import Any, Optional

import numpy as np
import trimesh

from .messages import render

SUPPORTED_EXTENSIONS = {".stl", ".obj", ".ply", ".glb", ".gltf", ".3mf"}

AXES6 = [
    np.array([1.0, 0.0, 0.0]),
    np.array([-1.0, 0.0, 0.0]),
    np.array([0.0, 1.0, 0.0]),
    np.array([0.0, -1.0, 0.0]),
    np.array([0.0, 0.0, 1.0]),
    np.array([0.0, 0.0, -1.0]),
]


class MeshLoadError(ValueError):
    """网格不可用：格式不支持/文件损坏/空几何，归为用户侧错误（退出码 2）。"""


def sha256_file(path: Path) -> str:
    """流式计算文件 sha256。"""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _nodes_from_scene(scene: trimesh.Scene) -> list[tuple[str, trimesh.Trimesh]]:
    """按 `scene.graph` 逐节点取世界变换并应用到该节点的几何副本上。"""
    nodes: list[tuple[str, trimesh.Trimesh]] = []
    for node_name in scene.graph.nodes_geometry:
        transform, geom_name = scene.graph.get(node_name)
        geom = scene.geometry.get(geom_name)
        if geom is None or not hasattr(geom, "vertices") or len(geom.vertices) == 0:
            continue
        mesh = geom.copy()
        mesh.apply_transform(transform)
        nodes.append((node_name, mesh))
    return nodes


def load_raw_parts(path: Path, merge: bool = False) -> list[tuple[str, trimesh.Trimesh]]:
    """载入单个文件，返回 `[(节点名, mesh)]`；`merge=True` 把整个文件拼成一件。

    场景类文件（GLB/GLTF/3MF，以及带多组/多材质的 OBJ）默认每个几何节点各是
    一件；普通单几何文件（STL/PLY，多数 OBJ）就是一件，节点名取文件主名。
    """
    ext = path.suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise MeshLoadError(render("mesh_io.unsupported_file_type", suffix=path.suffix, path=path))
    if not path.exists():
        raise MeshLoadError(render("mesh_io.file_not_found", path=path))
    try:
        loaded = trimesh.load(path, process=False, force=None)
    except Exception as exc:  # trimesh 对不同格式抛的异常类型五花八门
        raise MeshLoadError(render("mesh_io.load_failed", path=path, error=exc)) from exc

    if isinstance(loaded, trimesh.Trimesh):
        if len(loaded.vertices) == 0:
            raise MeshLoadError(render("mesh_io.empty_geometry", path=path))
        return [(path.stem, loaded)]

    if isinstance(loaded, trimesh.Scene):
        nodes = _nodes_from_scene(loaded)
        if not nodes:
            dumped = loaded.dump(concatenate=True)
            if dumped is None or len(dumped.vertices) == 0:
                raise MeshLoadError(render("mesh_io.no_usable_geometry", path=path))
            nodes = [(path.stem, dumped)]
        if merge:
            meshes = [m for _, m in nodes]
            combined = trimesh.util.concatenate(meshes) if len(meshes) > 1 else meshes[0]
            return [(path.stem, combined)]
        return nodes

    raise MeshLoadError(render("mesh_io.unrecognized_load_result", path=path, loaded_type=type(loaded)))


def dedupe_name(name: str, seen: dict[str, int]) -> str:
    """重名加 `_2`（第一次出现保留原名，第二次开始编号）。"""
    if name not in seen:
        seen[name] = 1
        return name
    seen[name] += 1
    return f"{name}_{seen[name]}"


def position_merged_copy(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    """丢掉 UV/顶点色等视觉属性，按顶点位置重新焊接的副本（不改原始网格）。"""
    clean = trimesh.Trimesh(
        vertices=np.asarray(mesh.vertices, dtype=np.float64), faces=np.asarray(mesh.faces, dtype=np.int64), process=True
    )
    return clean


def measure_part(mesh: trimesh.Trimesh) -> dict[str, Any]:
    """算 extents/水密性/连通分量/体积；水密性与连通分量在"位置焊接副本"上测，
    体积不水密时给 `None`。原始网格的 faces/vertices 计数原样报告（不因焊接副本
    合并顶点而改变）。"""
    clean = position_merged_copy(mesh)
    watertight = bool(clean.is_watertight)
    components = len(clean.split(only_watertight=False))
    volume_cm3 = None
    if watertight:
        volume_cm3 = abs(float(clean.volume)) / 1000.0  # mm^3 -> cm^3
    return {
        "faces": int(len(mesh.faces)),
        "vertices": int(len(mesh.vertices)),
        "extents_mm": [float(x) for x in mesh.extents],
        "volume_cm3": volume_cm3,
        "watertight": watertight,
        "components": components,
    }


def _rotation_to_up_z(direction: np.ndarray) -> np.ndarray:
    """返回 3x3 旋转矩阵 R，使 `R @ unit(direction) == [0,0,1]`。"""
    d = direction / np.linalg.norm(direction)
    R4 = trimesh.geometry.align_vectors(d, [0.0, 0.0, 1.0])
    return np.asarray(R4)[:3, :3]


def fits_any_axis(
    mesh: trimesh.Trimesh, avail_w: float, avail_h: float, avail_z: float
) -> tuple[bool, Optional[float]]:
    """六个轴向朝上里是否存在一个放得进可用区；都放不下时给一个"再等比例缩小
    多少倍就能放下"的建议系数（用六个候选里最不吃亏的那个，向下取 3 位小数，
    保证按它缩放后确实放得下而不是刚好卡在边界上）。"""
    best_ratio = 0.0
    any_fit = False
    for axis in AXES6:
        R = _rotation_to_up_z(axis)
        pts = mesh.vertices @ R.T
        dims = pts.max(axis=0) - pts.min(axis=0)
        if dims[0] <= avail_w and dims[1] <= avail_h and dims[2] <= avail_z:
            any_fit = True
        ratios = [
            avail_w / dims[0] if dims[0] > 0 else math.inf,
            avail_h / dims[1] if dims[1] > 0 else math.inf,
            avail_z / dims[2] if dims[2] > 0 else math.inf,
        ]
        best_ratio = max(best_ratio, min(ratios))
    if any_fit:
        return True, None
    suggested = math.floor(best_ratio * 1000) / 1000.0
    return False, suggested


def warnings_for_part(name: str, measured: dict[str, Any]) -> list[str]:
    """不水密 / 多连通块 / 面数超 200 万 / 最长边异常（多半是单位错）四类警告。"""
    warns: list[str] = []
    if not measured["watertight"]:
        warns.append(render("mesh_io.warning_not_watertight", name=name))
    if measured["components"] > 1:
        warns.append(render("mesh_io.warning_disconnected_components", name=name, components=measured["components"]))
    if measured["faces"] > 2_000_000:
        warns.append(render("mesh_io.warning_face_count_exceeds", name=name, faces=measured["faces"]))
    max_extent = max(measured["extents_mm"]) if measured["extents_mm"] else 0.0
    if max_extent < 5.0:
        warns.append(render("mesh_io.warning_unit_suspect_low", name=name, max_extent=max_extent))
    elif max_extent > 2000.0:
        warns.append(render("mesh_io.warning_unit_suspect_high", name=name, max_extent=max_extent))
    return warns


def save_part_stl(mesh: trimesh.Trimesh, path: Path) -> None:
    """把（缩放后的）零件几何存成二进制 STL，后续步骤只读这份。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    mesh.export(path, file_type="stl")


def load_part_stl(path: Path | str) -> trimesh.Trimesh:
    """载入 `inspect` 落盘的零件 STL（orient/arrange/export 三处载入点公用）。

    STL 读回来的顶点数恒等于面数乘 3（每个三角形拥有独立的三个顶点，STL 格式
    本身不共享顶点索引）；不合并直接写进 3MF，切片器会在这些"假缝"上看到一堆
    开边。`Trimesh.merge_vertices()` 按位置去重、原地重映射 `faces` 索引，
    面数与面序不变（只合并顶点，不删面）。"""
    mesh = trimesh.load(path, process=False, force="mesh")
    mesh.merge_vertices()
    return mesh
