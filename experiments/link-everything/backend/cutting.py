"""Import a closed whole-model STL/GLB, cut it, and freeze a paired source.

All internal geometry uses millimetres and Z-up. GLB scene transforms and mesh
instances are baked into the source, then a true solid union is cut. Boolean
intersections produce sealed caps. Surface materials are not retained.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import math
import uuid
from pathlib import Path

from backend import manual
from backend.engine import box, export_glb, mesh_solid, mf, np, save_json, sha, to_trimesh, trimesh

MAX_BYTES = 50 * 1024 * 1024
MAX_FACES = 250000
MAX_PREVIEW_FACES = 500000
MIN_PREVIEW_VOLUME_MM3 = 0.1
MAX_MESHES = 128
MAX_VISUAL_MESHES = 1024
MAX_VISUAL_FACES = 1500000
MAX_VISUAL_VERTICES = 2000000
MAX_REPAIR_LOOPS = 32
MAX_REPAIR_LOOP_VERTICES = 512
MAX_REPAIR_TOTAL_BOUNDARY_VERTICES = 1024
MAX_REPAIR_EAR_POINT_TESTS = 300000
MAX_REPAIR_CAP_AREA_RATIO = 0.6


def _folder():
    return manual.OUT / "cutting"


def _active():
    return _folder() / "active.json"


def _current():
    if not _active().exists():
        return None
    record = json.loads(_active().read_text(encoding="utf-8"))
    if record.get("cut_ready") is False:
        original = record.get("original_path")
        return record if original and Path(original).is_file() else None
    return record if record.get("stl") and Path(record["stl"]).is_file() else None


def _verified_source():
    record = _current()
    if not record:
        raise ValueError("请先载入整件 STL、GLB 或示例")
    if record.get("cut_ready") is False:
        raise ValueError("当前 GLB 已作为展示模型导入，但不是可切割的水密实体；请先修复或简化网格后再分件")
    if sha(record["stl"]) != record["sha256"]:
        raise RuntimeError("整件几何文件与导入记录不一致，请重新上传")
    if record.get("original_format"):
        original = Path(record["stl"]).with_name("original." + record["original_format"])
        if not original.is_file() or sha(original) != record["original_sha256"]:
            raise RuntimeError("上传原件与导入记录不一致，请重新上传")
    return record


def _set_source(
    mesh,
    label,
    kind,
    *,
    original=None,
    original_format=None,
    input_units="mm",
    input_up_axis="Z",
    nodes=None,
    repair_notes=None,
    metadata=None,
):
    if not mesh.is_watertight or not mesh.is_winding_consistent or mesh.volume <= 1:
        raise ValueError("整件必须是正体积、闭合且法线一致的实体")
    if len(mesh.faces) > MAX_FACES:
        raise ValueError("整件三角面数不能超过 250000")
    if not np.isfinite(mesh.vertices).all() or max(mesh.extents) > 10000 or min(mesh.extents) < 0.01:
        raise ValueError("整件尺寸异常；请核对 GLB 输入单位（米或毫米）")
    if nodes is None:
        nodes = [dict(name="whole", faces=len(mesh.faces), bounds_mm=mesh.bounds.tolist(), watertight=True)]
    source_id = "whole-" + uuid.uuid4().hex[:12]
    folder = _folder() / "sources" / source_id
    folder.mkdir(parents=True, exist_ok=False)
    stl, glb = folder / "whole.stl", folder / "whole.glb"
    mesh.export(stl)
    export_glb(mesh, glb, [100, 151, 177, 255])
    original_path = None
    if original is not None:
        original_path = folder / ("original." + original_format)
        original_path.write_bytes(original)
    record = dict(
        id=source_id,
        label=label,
        kind=kind,
        stl=str(stl),
        url=f"/outputs/manual/cutting/sources/{source_id}/whole.glb",
        sha256=sha(stl),
        bounds_mm=mesh.bounds.tolist(),
        volume_mm3=float(mesh.volume),
        closed=True,
        cut_ready=True,
        face_count=len(mesh.faces),
        units="mm",
        coordinate_system="mm/Z-up",
        original_format=original_format,
        input_units=input_units,
        input_up_axis=input_up_axis,
        mesh_count=len(nodes),
        source_nodes=nodes,
        repair_notes=repair_notes or [],
        original_sha256=hashlib.sha256(original).hexdigest() if original is not None else None,
        original_url=(
            f"/outputs/manual/cutting/sources/{source_id}/original.{original_format}" if original_path else None
        ),
        materials_preserved=False,
    )
    if metadata:
        record.update(metadata)
    save_json(folder / "source.json", record)
    save_json(_active(), record)
    return record


def sample(_payload=None):
    # One cut crosses both towers; only the selected cap will become part B.
    solid = box([-23, -14, 0], [23, 14, 8])
    solid += box([-19, -10, 8], [-3, 10, 23])
    solid += box([3, -10, 8], [19, 10, 23])
    return dict(source=_set_source(to_trimesh(solid), "双立柱整件示例 · 一刀切到两处", "sample"))


def _boundary_loops(mesh):
    """Return consistently oriented open edge rings, or refuse ambiguous topology."""
    edges = mesh.edges
    _, inverse, counts = np.unique(np.sort(edges, axis=1), axis=0, return_inverse=True, return_counts=True)
    if np.any(counts > 2):
        return None
    boundary = edges[counts[inverse] == 1]
    if not len(boundary):
        return None
    successors = {}
    incoming = set()
    for start, end in boundary:
        start, end = int(start), int(end)
        if start in successors or end in incoming:
            return None
        successors[start] = end
        incoming.add(end)
    if set(successors) != incoming:
        return None
    loops = []
    boundary_vertices = 0
    while successors:
        start = next(iter(successors))
        current = start
        loop = []
        while current in successors:
            if len(loop) > MAX_REPAIR_LOOP_VERTICES:
                return None
            loop.append(current)
            current = successors.pop(current)
        if current != start or len(loop) < 3:
            return None
        loops.append(loop)
        boundary_vertices += len(loop)
        if len(loops) > MAX_REPAIR_LOOPS or boundary_vertices > MAX_REPAIR_TOTAL_BOUNDARY_VERTICES:
            return None
    return loops


def _cross2(a, b):
    return float(a[0] * b[1] - a[1] * b[0])


def _simple_polygon(points, epsilon):
    """Refuse crossing or doubled boundaries before generating a cap."""
    count = len(points)
    for i in range(count):
        a, b = points[i], points[(i + 1) % count]
        if np.linalg.norm(b - a) <= epsilon:
            return False
        for j in range(i + 2, count):
            if i == 0 and j == count - 1:
                continue
            c, d = points[j], points[(j + 1) % count]
            ab, cd = b - a, d - c
            s1, s2 = _cross2(ab, c - a), _cross2(ab, d - a)
            t1, t2 = _cross2(cd, a - c), _cross2(cd, b - c)
            if (s1 > epsilon and s2 < -epsilon or s1 < -epsilon and s2 > epsilon) and (
                t1 > epsilon and t2 < -epsilon or t1 < -epsilon and t2 > epsilon
            ):
                return False
            if (
                abs(s1) <= epsilon
                and abs(s2) <= epsilon
                and max(min(a[0], b[0]), min(c[0], d[0])) <= min(max(a[0], b[0]), max(c[0], d[0])) + epsilon
                and max(min(a[1], b[1]), min(c[1], d[1])) <= min(max(a[1], b[1]), max(c[1], d[1])) + epsilon
            ):
                return False
    return True


def _point_in_polygon(point, points, epsilon):
    inside = False
    for i in range(len(points)):
        a, b = points[i], points[(i + 1) % len(points)]
        if abs(_cross2(b - a, point - a)) <= epsilon and np.dot(point - a, point - b) <= epsilon:
            return True
        if (a[1] > point[1]) != (b[1] > point[1]):
            crossing = a[0] + (point[1] - a[1]) * (b[0] - a[0]) / (b[1] - a[1])
            if crossing > point[0]:
                inside = not inside
    return inside


def _nested_coplanar_loops(loops, vertices):
    """Two nested rings are an annulus; filling each as a disk is invalid."""
    planes = []
    for loop in loops:
        coords = vertices[loop]
        origin = coords.mean(axis=0)
        _, _, axes = np.linalg.svd(coords - origin, full_matrices=False)
        diameter = float(np.linalg.norm(coords.max(axis=0) - coords.min(axis=0)))
        planes.append((origin, axes, diameter))
    for i, (origin, axes, diameter) in enumerate(planes):
        polygon = (vertices[loops[i]] - origin) @ axes[:2].T
        for j, (other_origin, other_axes, _) in enumerate(planes):
            if i == j or abs(np.dot(axes[2], other_axes[2])) < 0.999:
                continue
            if abs(np.dot(other_origin - origin, axes[2])) > max(0.02, min(0.2, 0.003 * diameter)):
                continue
            point = (vertices[loops[j][0]] - origin) @ axes[:2].T
            if _point_in_polygon(point, polygon, 1e-9 * max(diameter, 1.0) ** 2):
                return True
    return False


def _triangulate_loop(loop, vertices, budget):
    """Ear-clip a nearly planar, simple ring using its existing edge vertices."""
    coords = vertices[loop]
    centered = coords - coords.mean(axis=0)
    _, _, axes = np.linalg.svd(centered, full_matrices=False)
    diameter = float(np.linalg.norm(coords.max(axis=0) - coords.min(axis=0)))
    if diameter <= 0.01 or np.max(abs(centered @ axes[2])) > max(0.02, min(0.2, 0.003 * diameter)):
        return None
    points = centered @ axes[:2].T
    scale = max(diameter, 1.0)
    epsilon = 1e-10 * scale * scale
    if not _simple_polygon(points, 1e-9 * scale):
        return None
    area = 0.5 * sum(_cross2(points[i], points[(i + 1) % len(loop)]) for i in range(len(loop)))
    if abs(area) <= epsilon:
        return None
    # Work counterclockwise in 2D. A cap must run opposite the existing
    # directed boundary edges, regardless of which PCA normal was chosen.
    order = list(range(len(loop)))
    if area < 0:
        order.reverse()
    faces = []
    while len(order) > 3:
        found = False
        for k in range(len(order)):
            ia, ib, ic = order[k - 1], order[k], order[(k + 1) % len(order)]
            a, b, c = points[[ia, ib, ic]]
            if _cross2(b - a, c - a) <= epsilon:
                continue
            blocked = False
            for index in order:
                if index in (ia, ib, ic):
                    continue
                budget[0] -= 1
                if budget[0] < 0:
                    return None
                point = points[index]
                if (
                    _cross2(b - a, point - a) >= -epsilon
                    and _cross2(c - b, point - b) >= -epsilon
                    and _cross2(a - c, point - c) >= -epsilon
                ):
                    blocked = True
                    break
            if blocked:
                continue
            faces.append([loop[ia], loop[ib], loop[ic]])
            order.pop(k)
            found = True
            break
        if not found:
            return None
    faces.append([loop[index] for index in order])
    cap = np.asarray(faces, dtype=np.int64)
    if area > 0:
        cap = np.fliplr(cap)
    return cap, abs(area)


def _cap_planar_openings(shell):
    """Close modest planar holes without replacing or voxelizing source geometry."""
    candidate = shell.copy()
    if not candidate.is_winding_consistent:
        trimesh.repair.fix_winding(candidate)
    loops = _boundary_loops(candidate)
    if not loops:
        return None, 0, 0
    if _nested_coplanar_loops(loops, candidate.vertices):
        return None, 0, 0
    caps, area = [], 0.0
    budget = [MAX_REPAIR_EAR_POINT_TESTS]
    for loop in loops:
        result = _triangulate_loop(loop, candidate.vertices, budget)
        if result is None:
            return None, 0, 0
        faces, cap_area = result
        caps.append(faces)
        area += cap_area
    if area > MAX_REPAIR_CAP_AREA_RATIO * candidate.area or len(candidate.faces) + sum(map(len, caps)) > MAX_FACES:
        return None, 0, 0
    candidate.extend_faces(np.vstack(caps))
    if not candidate.is_watertight:
        return None, 0, 0
    trimesh.repair.fix_normals(candidate, multibody=True)
    if not candidate.is_winding_consistent or candidate.volume <= 0.01:
        return None, 0, 0
    return candidate, len(loops), max(map(len, loops))


def _glb_mesh(raw, input_units, up_axis):
    if (
        raw[:4] != b"glTF"
        or len(raw) < 20
        or int.from_bytes(raw[4:8], "little") != 2
        or int.from_bytes(raw[8:12], "little") != len(raw)
    ):
        raise ValueError("GLB 文件头无效，需上传 glTF 2.0 二进制 GLB")
    if input_units not in ("mm", "m"):
        raise ValueError("上传 GLB 时须明确选择单位：mm 或 m")
    if up_axis not in ("Y", "Z"):
        raise ValueError("GLB 坐标轴只能是 Y 或 Z")
    try:
        scene = trimesh.load(io.BytesIO(raw), file_type="glb", force="scene", process=False)
    except Exception as exc:
        raise ValueError("无法读取 GLB 网格；请导出未压缩的 glTF 2.0 GLB") from exc
    if not isinstance(scene, trimesh.Scene) or not scene.graph.nodes_geometry:
        raise ValueError("GLB 没有可切割的三角网格")
    if len(scene.graph.nodes_geometry) > MAX_MESHES:
        raise ValueError(f"GLB 最多支持 {MAX_MESHES} 个网格实例")
    # glTF convention: metres, Y-up. Our engineering convention: mm, Z-up.
    scale = 1000.0 if input_units == "m" else 1.0
    basis = np.eye(4)
    basis[:3, :3] = (
        [[scale, 0, 0], [0, 0, -scale], [0, scale, 0]]
        if up_axis == "Y"
        else [[scale, 0, 0], [0, scale, 0], [0, 0, scale]]
    )
    meshes, nodes, repair_notes = [], [], []
    total_faces = 0
    for node in scene.graph.nodes_geometry:
        transform, geometry_name = scene.graph.get(node)
        geometry = scene.geometry[geometry_name]
        if not isinstance(geometry, trimesh.Trimesh) or len(geometry.faces) == 0:
            continue
        total_faces += len(geometry.faces)
        if total_faces > MAX_FACES:
            raise ValueError(f"GLB 总三角面数不能超过 {MAX_FACES}")
        transform = np.asarray(transform, dtype=float)
        if (
            transform.shape != (4, 4)
            or not np.isfinite(transform).all()
            or abs(np.linalg.det(transform[:3, :3])) < 1e-12
        ):
            raise ValueError(f"GLB 节点 {node} 存在无效或退化的变换")
        mesh = geometry.copy()
        mesh.apply_transform(basis @ transform)
        mesh.remove_unreferenced_vertices()
        if not np.isfinite(mesh.vertices).all() or not np.isfinite(mesh.bounds).all():
            raise ValueError(f"GLB 节点 {node} 有非有限坐标")
        meshes.append(mesh)
        nodes.append(
            dict(
                name=str(node),
                geometry=str(geometry_name),
                faces=len(mesh.faces),
                bounds_mm=mesh.bounds.tolist(),
                watertight=bool(mesh.is_watertight),
            )
        )
    if not meshes:
        raise ValueError("GLB 没有可切割的闭合实体网格")
    # GLBs commonly split one closed shell across several material primitives.
    # Weld matching boundaries before deciding whether any individual node is
    # an invalid open surface. If every node is already closed, Boolean-union
    # them individually to handle overlaps without duplicated internal faces.
    if all(mesh.is_watertight for mesh in meshes):
        shells = meshes
    else:
        combined = trimesh.util.concatenate(meshes)
        # 1 µm welding tolerance absorbs float32 glTF roundoff while staying
        # well below any intentional clearance used by this print workflow.
        combined.merge_vertices(digits_vertex=3)
        shells = [combined]
    for index, shell in enumerate(shells):
        if not shell.is_watertight:
            # Keep all opening sizes subject to the same planarity, area and
            # topology limits. This never voxelizes or invents a new outline.
            repaired, loop_count, largest_loop = _cap_planar_openings(shell)
            if repaired is not None:
                shell = repaired
                repair_notes.append(
                    f"shell {index}: filled small boundary holes"
                    if largest_loop <= 4
                    else f"shell {index}: capped {loop_count} planar boundary opening(s)"
                )
        if not shell.is_watertight:
            # Some CAD exports weld two otherwise closed bodies along one
            # edge. Those edges have four incident triangles, but there is no
            # boundary or missing surface to invent. Manifold can separate
            # the touching shells; accept that narrow repair only when its
            # volume and bounds match the source to sub-print tolerances.
            _, edge_counts = np.unique(np.sort(shell.edges, axis=1), axis=0, return_counts=True)
            if (
                len(edge_counts)
                and np.all(edge_counts >= 2)
                and np.all(edge_counts % 2 == 0)
                and np.any(edge_counts > 2)
            ):
                try:
                    repaired = to_trimesh(mesh_solid(shell))
                    if (
                        repaired.is_watertight
                        and repaired.is_winding_consistent
                        and repaired.volume > 0.01
                        and np.allclose(repaired.bounds, shell.bounds, rtol=0, atol=0.01)
                        and abs(repaired.volume - shell.volume) <= max(0.01, abs(shell.volume) * 1e-4)
                    ):
                        shell = repaired
                        repair_notes.append(f"shell {index}: separated touching closed seams")
                except Exception:
                    pass
        if not shell.is_watertight:
            raise ValueError(
                "GLB 仍有未闭合的表面网格，无法可靠自动修复；自动补洞仅支持边界完整、近似平面的开口。大面积、复杂或非流形开口需先在建模软件中修复"
            )
        if not shell.is_winding_consistent or shell.volume < 0:
            trimesh.repair.fix_normals(shell, multibody=True)
            repair_notes.append(f"shell {index}: corrected face orientation")
        if not shell.is_winding_consistent or shell.volume <= 0.01:
            raise ValueError("GLB 网格不是闭合正体积实体；请修复自交或法线")
        shells[index] = shell
    try:
        whole = mesh_solid(shells[0])
        for shell in shells[1:]:
            whole += mesh_solid(shell)
        merged = to_trimesh(whole)
    except Exception as exc:
        raise ValueError("GLB 网格无法组成有效实体；请修复自交或重叠几何") from exc
    if merged.is_empty or not merged.is_watertight or not merged.is_winding_consistent or merged.volume <= 1:
        raise ValueError("GLB 合并后不是有效闭合实体；请检查重叠或退化网格")
    return merged, nodes, repair_notes


def _set_visual_source(raw, label, input_units, up_axis, solid_error):
    """Keep a valid GLB intact when no trustworthy printable solid exists.

    This is deliberately an intake path, not a mesh repair. We validate every
    displayed triangle and node transform, but do not invent a solid or alter
    the original materials/scene graph. The mm/Z-up bounds are metadata only;
    the GLB URL still points to the original bytes and coordinate system.
    """
    if (
        raw[:4] != b"glTF"
        or len(raw) < 20
        or int.from_bytes(raw[4:8], "little") != 2
        or int.from_bytes(raw[8:12], "little") != len(raw)
    ):
        raise ValueError("GLB 文件头无效，需上传 glTF 2.0 二进制 GLB")
    if input_units not in ("mm", "m"):
        raise ValueError("上传 GLB 时须明确选择单位：mm 或 m")
    if up_axis not in ("Y", "Z"):
        raise ValueError("GLB 坐标轴只能是 Y 或 Z")
    try:
        scene = trimesh.load(io.BytesIO(raw), file_type="glb", force="scene", process=False)
    except Exception as exc:
        raise ValueError("无法读取 GLB 网格；请导出未压缩的 glTF 2.0 GLB") from exc
    if not isinstance(scene, trimesh.Scene) or not scene.graph.nodes_geometry:
        raise ValueError("GLB 没有三角网格，无法展示")
    if len(scene.graph.nodes_geometry) > MAX_VISUAL_MESHES:
        raise ValueError(f"GLB 展示最多支持 {MAX_VISUAL_MESHES} 个网格实例")

    scale = 1000.0 if input_units == "m" else 1.0
    basis = np.eye(4)
    basis[:3, :3] = (
        [[scale, 0, 0], [0, 0, -scale], [0, scale, 0]]
        if up_axis == "Y"
        else [[scale, 0, 0], [0, scale, 0], [0, 0, scale]]
    )
    lower, upper = np.full(3, np.inf), np.full(3, -np.inf)
    nodes, face_count, vertex_count = [], 0, 0
    for node in scene.graph.nodes_geometry:
        transform, geometry_name = scene.graph.get(node)
        geometry = scene.geometry[geometry_name]
        if not isinstance(geometry, trimesh.Trimesh) or len(geometry.faces) == 0:
            continue
        face_count += len(geometry.faces)
        vertex_count += len(geometry.vertices)
        if face_count > MAX_VISUAL_FACES or vertex_count > MAX_VISUAL_VERTICES:
            raise ValueError("GLB 网格过于复杂，超过展示安全上限")
        transform = np.asarray(transform, dtype=float)
        if (
            transform.shape != (4, 4)
            or not np.isfinite(transform).all()
            or abs(np.linalg.det(transform[:3, :3])) < 1e-12
        ):
            raise ValueError(f"GLB 节点 {node} 存在无效或退化的变换")
        vertices = np.asarray(geometry.vertices, dtype=float)
        faces = np.asarray(geometry.faces, dtype=np.int64)
        if not len(vertices) or not np.isfinite(vertices).all() or np.any(faces < 0) or np.any(faces >= len(vertices)):
            raise ValueError(f"GLB 节点 {node} 含无效三角网格")
        world = basis @ transform
        positioned = vertices @ world[:3, :3].T + world[:3, 3]
        if not np.isfinite(positioned).all():
            raise ValueError(f"GLB 节点 {node} 有非有限坐标")
        node_lower, node_upper = positioned.min(axis=0), positioned.max(axis=0)
        lower = np.minimum(lower, node_lower)
        upper = np.maximum(upper, node_upper)
        nodes.append(
            dict(
                name=str(node),
                geometry=str(geometry_name),
                faces=len(faces),
                bounds_mm=[node_lower.tolist(), node_upper.tolist()],
            )
        )
    if not nodes:
        raise ValueError("GLB 没有三角网格，无法展示")
    if max(upper - lower) > 10000 or max(upper - lower) < 0.01:
        raise ValueError("整件尺寸异常；请核对 GLB 输入单位（米或毫米）")

    source_id = "visual-" + uuid.uuid4().hex[:12]
    folder = _folder() / "sources" / source_id
    folder.mkdir(parents=True, exist_ok=False)
    original = folder / "original.glb"
    original.write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    warning = "原模型不是已验证的水密实体，已按原样导入供查看；目前不能分件或添加连接件。原因：" + str(solid_error)
    record = dict(
        id=source_id,
        label=label,
        kind="upload",
        stl=None,
        url=f"/outputs/manual/cutting/sources/{source_id}/original.glb",
        sha256=digest,
        bounds_mm=[lower.tolist(), upper.tolist()],
        volume_mm3=None,
        closed=False,
        cut_ready=False,
        face_count=face_count,
        mesh_count=len(nodes),
        units="mm",
        coordinate_system="mm/Z-up",
        original_format="glb",
        original_path=str(original),
        original_sha256=digest,
        original_url=f"/outputs/manual/cutting/sources/{source_id}/original.glb",
        input_units=input_units,
        input_up_axis=up_axis,
        source_nodes=nodes,
        repair_notes=["原始 GLB 未改动；仅供查看。"],
        import_warning=warning,
        materials_preserved=True,
    )
    save_json(folder / "source.json", record)
    save_json(_active(), record)
    return record


def upload(payload):
    if (
        not isinstance(payload, dict)
        or not {"data", "name"} <= set(payload)
        or set(payload) - {"data", "name", "units", "up_axis"}
    ):
        raise ValueError("整件上传需要 data、name，可附加 units 和 up_axis")
    data = payload["data"]
    if not isinstance(data, str) or len(data) > MAX_BYTES * 4 // 3 + 4:
        raise ValueError("整件文件超过 50 MB")
    try:
        raw = base64.b64decode(data, validate=True)
    except Exception as exc:
        raise ValueError("无效的 base64 文件") from exc
    if not 80 <= len(raw) <= MAX_BYTES:
        raise ValueError("整件文件必须在 80 B 到 50 MB 之间")
    name = str(payload["name"])[:90]
    extension = Path(name).suffix.lower()
    if extension not in (".stl", ".glb"):
        raise ValueError("整件只接受 .stl 或 .glb")
    units = payload.get("units", "mm" if extension == ".stl" else None)
    up_axis = payload.get("up_axis", "Y" if extension == ".glb" else "Z")
    if extension == ".glb":
        try:
            mesh, nodes, repair_notes = _glb_mesh(raw, units, up_axis)
        except MemoryError:
            raise
        except Exception as exc:
            # Solid conversion and its geometry libraries encounter many
            # different failures on otherwise displayable GLBs: open or
            # non-manifold surfaces, overlapping shells, repair failures,
            # and even unexpected errors in an optional Boolean backend.
            # Revalidate the original scene independently for viewing. This
            # validator still rejects malformed GLBs, unsafe transforms,
            # empty scenes, oversized geometry and invalid units.
            return dict(source=_set_visual_source(raw, name, units, up_axis, exc))
        try:
            return dict(
                source=_set_source(
                    mesh,
                    name,
                    "upload",
                    original=raw,
                    original_format="glb",
                    input_units=units,
                    input_up_axis=up_axis,
                    nodes=nodes,
                    repair_notes=repair_notes,
                )
            )
        except ValueError as exc:
            # The final printable-source gate can reject an otherwise valid
            # scene (for example a tiny or degenerate resulting solid). The
            # original visual GLB remains useful and is validated separately.
            return dict(source=_set_visual_source(raw, name, units, up_axis, exc))
    if units != "mm" or up_axis != "Z":
        raise ValueError("STL 上传使用毫米、Z 向上；请先转换坐标和单位")
    folder = _folder() / "_incoming"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / ("upload-" + uuid.uuid4().hex + ".stl")
    try:
        path.write_bytes(raw)
        mesh = manual._mesh(path)
        return dict(
            source=_set_source(
                mesh,
                name,
                "upload",
                original=raw,
                original_format="stl",
                input_units="mm",
                input_up_axis="Z",
                nodes=[dict(name="STL whole", faces=len(mesh.faces))],
            )
        )
    finally:
        path.unlink(missing_ok=True)


def solidify(payload):
    """Derive a separate, explicitly approximate cutting solid from a visual GLB.

    The original remains byte-identical and available for side-by-side review.
    A failed proxy never replaces the active visual import or saved paired work.
    """
    if not isinstance(payload, dict) or set(payload) != {"source_id"}:
        raise ValueError("生成切割代理体需要 source_id")
    source = _current()
    if not source or source["id"] != payload["source_id"]:
        raise RuntimeError("整件来源已变化，请重新载入当前 GLB")
    if source.get("cut_ready") is not False or source.get("original_format") != "glb":
        raise ValueError("只有非水密 GLB 展示源需要生成切割代理体")
    original = Path(source["original_path"])
    if not original.is_file() or sha(original) != source["original_sha256"]:
        raise RuntimeError("原始 GLB 与导入记录不一致，请重新上传")
    from backend.voxel_proxy import make_proxy

    mesh, metrics = make_proxy(original, source["input_units"], source["input_up_axis"])
    raw = original.read_bytes()
    node = dict(name="approximate-voxel-proxy", faces=len(mesh.faces), bounds_mm=mesh.bounds.tolist(), watertight=True)
    record = _set_source(
        mesh,
        source["label"] + " · 近似切割代理体",
        "proxy",
        original=raw,
        original_format="glb",
        input_units=source["input_units"],
        input_up_axis=source["input_up_axis"],
        nodes=[node],
        repair_notes=["以体素重建生成近似切割代理体；原始 GLB 未改动。"],
        metadata=dict(
            proxy=metrics, approximate=True, visual_source_id=source["id"], import_warning=metrics["warning"]
        ),
    )
    return dict(source=record)


def current():
    return dict(source=_current())


def _vector(value, key):
    result = np.asarray(value, dtype=float)
    if result.shape != (3,) or not np.isfinite(result).all():
        raise ValueError(f"{key} 需要三个有限数值")
    return result


def _params(payload, source):
    if payload.get("source_id") != source["id"]:
        raise RuntimeError("整件来源已改变，请重新载入")
    mode = payload.get("mode")
    if mode not in ("plane", "wave", "bowl"):
        raise ValueError("切割模式只能是 plane、wave 或 bowl")
    origin = _vector(payload.get("origin_mm"), "origin_mm")
    normal = _vector(payload.get("normal"), "normal")
    length = float(np.linalg.norm(normal))
    if length < 0.1:
        raise ValueError("切面法线不能为零")
    normal /= length
    amplitude = manual._finite(payload.get("amplitude_mm", 1.2), "amplitude_mm", 0.1, 6)
    wavelength = manual._finite(payload.get("wavelength_mm", 22), "wavelength_mm", 8, 100)
    return dict(
        mode=mode, origin_mm=origin.tolist(), normal=normal.tolist(), amplitude_mm=amplitude, wavelength_mm=wavelength
    )


def _basis(normal):
    helper = np.array([1.0, 0.0, 0.0]) if abs(normal[0]) < 0.85 else np.array([0.0, 1.0, 0.0])
    u = np.cross(helper, normal)
    u /= np.linalg.norm(u)
    v = np.cross(normal, u)
    return u, v


def _height(mode, u, v, amplitude, wavelength):
    if mode == "wave":
        return amplitude * math.sin(2 * math.pi * u / wavelength)
    if mode == "bowl":
        return amplitude * ((u / wavelength) ** 2 + (v / wavelength) ** 2)
    return 0.0


def _cutter(mesh, params):
    origin, normal = np.array(params["origin_mm"]), np.array(params["normal"])
    u, v = _basis(normal)
    corners = np.array([[x, y, z] for x in mesh.bounds[:, 0] for y in mesh.bounds[:, 1] for z in mesh.bounds[:, 2]])
    local = corners - origin
    # Grid is fitted to the model, so even a small curved cut has useful detail.
    count = 2 if params["mode"] == "plane" else 61
    xs = np.linspace(float((local @ u).min()) - 4, float((local @ u).max()) + 4, count)
    ys = np.linspace(float((local @ v).min()) - 4, float((local @ v).max()) + 4, count)
    lower_z = float((local @ normal).min()) - 10 - params["amplitude_mm"]
    top = []
    bottom = []
    for x in xs:
        for y in ys:
            point = origin + u * x + v * y
            top.append(point + normal * _height(params["mode"], x, y, params["amplitude_mm"], params["wavelength_mm"]))
            bottom.append(point + normal * lower_z)
    vertices = np.vstack((top, bottom))
    faces = []
    n = count
    offset = n * n
    for i in range(n - 1):
        for j in range(n - 1):
            a = i * n + j
            b = (i + 1) * n + j
            c = (i + 1) * n + j + 1
            d = i * n + j + 1
            faces.extend(
                ((a, b, c), (a, c, d), (a + offset, c + offset, b + offset), (a + offset, d + offset, c + offset))
            )
    boundary = (
        [i * n for i in range(n)]
        + [(n - 1) * n + j for j in range(1, n)]
        + [i * n + n - 1 for i in range(n - 2, -1, -1)]
        + [j for j in range(n - 2, 0, -1)]
    )
    for a, b in zip(boundary, boundary[1:] + boundary[:1]):
        faces.extend(((a, a + offset, b + offset), (a, b + offset, b)))
    cutter = trimesh.Trimesh(vertices=vertices, faces=faces, process=True)
    if not cutter.is_watertight or not cutter.is_winding_consistent:
        raise ValueError("曲面切割体未闭合")
    return mesh_solid(cutter)


def _preview_mesh(path):
    """Reload a saved cut island at the same threshold used by preview().

    Final A/B parts retain manual._mesh's stricter 1 mm³ / 250k-face gate.
    Boolean intersections may create a smaller closed island; reading every
    preview island through that final-part gate used to reject the whole
    commit even when the island was to be merged or discarded.
    """
    mesh = trimesh.load(path, force="mesh", process=True)
    if (
        not isinstance(mesh, trimesh.Trimesh)
        or not mesh.is_watertight
        or not mesh.is_winding_consistent
        or not np.isfinite(mesh.vertices).all()
        or len(mesh.faces) > MAX_PREVIEW_FACES
        or mesh.volume < MIN_PREVIEW_VOLUME_MM3
    ):
        raise ValueError("切块预览无效；请重新预览切面")
    return mesh


def _group_shells(group):
    return [shell for solid in group for shell in solid.decompose()]


def _group_mesh(group):
    return trimesh.util.concatenate([to_trimesh(shell) for shell in _group_shells(group)])


def _group_valid(group):
    shells = _group_shells(group)
    if not shells:
        return False
    shell_meshes = [to_trimesh(shell) for shell in shells]
    if any(
        not mesh.is_watertight or not mesh.is_winding_consistent or mesh.volume < MIN_PREVIEW_VOLUME_MM3
        for mesh in shell_meshes
    ):
        return False
    joined = trimesh.util.concatenate(shell_meshes)
    return bool(joined.is_watertight and joined.is_winding_consistent and joined.volume > 1)


def _join_without_loss(parts):
    """Join touching cut islands only if the union preserves their volume."""
    if len(parts) < 2:
        return parts
    joined = parts[0]
    for part in parts[1:]:
        joined += part
    before = sum(float(part.volume()) for part in parts)
    if _group_valid([joined]) and abs(float(joined.volume()) - before) <= manual._overlap_tolerance(before):
        return [joined]
    return parts


def _fit_commit_face_budget(groups):
    """Boundedly simplify a dense cut pair before the final printable gate.

    Both sides use the same tolerance, and candidates are accepted only when
    they keep every closed shell, do not overlap, and stay within volume and
    bounds checks. The original upload and preview meshes remain untouched.
    """
    legacy = all(isinstance(group, mf.Manifold) for group in groups)
    if legacy:
        groups = [[group] for group in groups]
    meshes = [_group_mesh(group) for group in groups]
    if all(len(mesh.faces) <= MAX_FACES for mesh in meshes):
        return ([group[0] for group in groups] if legacy else groups), meshes, None
    original_volume = sum(float(mesh.volume) for mesh in meshes)
    original_shell_counts = [len(_group_shells(group)) for group in groups]
    for tolerance in (0.005, 0.01, 0.02, 0.05, 0.1):
        try:
            reduced = [[solid.simplify(tolerance) for solid in group] for group in groups]
            candidates = [_group_mesh(group) for group in reduced]
            if any(
                len(mesh.faces) > MAX_FACES
                or not _group_valid(group)
                or len(_group_shells(group)) != original_shell_counts[index]
                or not np.allclose(mesh.bounds, original.bounds, rtol=0, atol=tolerance + 0.01)
                for index, (mesh, original, group) in enumerate(zip(candidates, meshes, reduced))
            ):
                continue
            if abs(sum(float(mesh.volume) for mesh in candidates) - original_volume) > max(
                1.0, original_volume * 0.001
            ):
                continue
            if manual._group_overlap(reduced[0], reduced[1]) > manual._overlap_tolerance(original_volume):
                continue
            return ([group[0] for group in reduced] if legacy else reduced), candidates, tolerance
        except Exception:
            continue
    raise ValueError("分件后网格超过每件 250000 面，无法在 0.1 mm 几何偏差内安全简化；请先降低原模型面数")


def _stl_roundtrip(mesh):
    """Check the actual STL serialization, not just indexed in-memory shells.

    STL stores triangles rather than shell/vertex identities. Trimesh must weld
    vertices on import, which can turn two individually closed shells that meet
    at one edge into a non-manifold four-face edge. This is the same gate used
    by ``manual._source_from_files`` after commit.
    """
    try:
        loaded = trimesh.load(io.BytesIO(mesh.export(file_type="stl")), file_type="stl", force="mesh", process=True)
        shells = loaded.split(only_watertight=False)
        valid = (
            isinstance(loaded, trimesh.Trimesh)
            and loaded.is_watertight
            and loaded.is_winding_consistent
            and 0 < len(loaded.faces) <= MAX_FACES
            and loaded.volume > 1
            and shells
            and all(shell.is_watertight and shell.is_winding_consistent and shell.volume > 0 for shell in shells)
        )
        return loaded, bool(valid)
    except Exception:
        return None, False


def _stl_problem(loaded, expected_shells):
    if loaded is None:
        return "STL 重新读取失败"
    details = []
    if not loaded.is_watertight:
        _, counts = np.unique(np.sort(loaded.edges, axis=1), axis=0, return_counts=True)
        if np.any(counts == 1):
            details.append(f"{int(np.count_nonzero(counts == 1))} 条开放边")
        if np.any(counts > 2):
            details.append(f"{int(np.count_nonzero(counts > 2))} 条多重共享边")
    if not loaded.is_winding_consistent:
        details.append("法线不一致")
    if loaded.volume <= 1:
        details.append("体积不足 1 mm³")
    count = len(loaded.split(only_watertight=False))
    if count != expected_shells:
        details.append(f"壳体数由 {expected_shells} 变为 {count}")
    return "、".join(details) or "实体拓扑无效"


def _fit_stl_roundtrip(groups, meshes, normal, max_shift_mm=0.02):
    """Preserve touching closed shells through STL's coordinate-only format.

    First try the exact geometry. If its STL round-trip welds distinct shells
    together, move only secondary shells *tangentially* by at most 0.02 mm,
    keeping the largest shell and the original source/preview unchanged. Each
    candidate must round-trip as the same number of closed positive shells,
    retain their volumes/bounds and avoid A/B overlap. The numerical shift is
    recorded for review; it is never presented as a physical Boolean fusion.
    """
    baseline = []
    for mesh, group in zip(meshes, groups):
        loaded, valid = _stl_roundtrip(mesh)
        baseline.append((loaded, valid, len(_group_shells(group))))
    original_volumes = [float(mesh.volume) for mesh in meshes]
    tolerance = manual._overlap_tolerance(sum(original_volumes))
    baseline_closed = all(
        valid and len(loaded.split(only_watertight=False)) == count for loaded, valid, count in baseline
    )
    if baseline_closed:
        reloaded = [[mesh_solid(shell) for shell in loaded.split(only_watertight=False)] for loaded, _, _ in baseline]
        overlap = manual._group_overlap(reloaded[0], reloaded[1])
        if overlap <= tolerance:
            return groups, meshes, None
        raise ValueError(f"STL 序列化后 A/B 交叠 {overlap:.4f} mm³，超过 {tolerance:.4f} mm³ 容差；请调整切面")
    if not any(
        count > 1 and (not valid or len(loaded.split(only_watertight=False)) != count)
        for loaded, valid, count in baseline
    ):
        bad = [
            "AB"[i] + "（" + _stl_problem(loaded, count) + "）"
            for i, (loaded, valid, count) in enumerate(baseline)
            if not valid or (baseline[i][0] is not None and len(baseline[i][0].split(only_watertight=False)) != count)
        ]
        raise ValueError(f"分件 {'、'.join(bad)} 的 STL 往返无效；请调整切面")
    _, tangent = _basis(np.asarray(normal, dtype=float))
    original_counts = [count for _, _, count in baseline]
    # The first step is 0.2 µm; the largest possible shift is 20 µm. For a
    # large number of shells, cap the step rather than growing without bound.
    for step in (0.0002, 0.0005, 0.001, 0.002):
        for direction in (1.0, -1.0):
            candidates = []
            shifts = []
            for group in groups:
                shells = sorted(_group_shells(group), key=lambda shell: float(shell.volume()), reverse=True)
                if len(shells) == 1:
                    candidates.append(shells)
                    shifts.append([])
                    continue
                increment = min(step, max_shift_mm / (len(shells) - 1))
                adjusted = [shells[0]]
                displacements = []
                for index, shell in enumerate(shells[1:], 1):
                    vector = tangent * (direction * increment * index)
                    adjusted.append(shell.translate(vector))
                    displacements.append([float(x) for x in vector])
                candidates.append(adjusted)
                shifts.append(displacements)
            if manual._group_overlap(candidates[0], candidates[1]) > tolerance:
                continue
            new_meshes = [_group_mesh(group) for group in candidates]
            checked = [_stl_roundtrip(mesh) for mesh in new_meshes]
            if any(
                not valid or len(loaded.split(only_watertight=False)) != count
                for (loaded, valid), count in zip(checked, original_counts)
            ):
                continue
            reloaded = [
                [mesh_solid(shell) for shell in loaded.split(only_watertight=False)] for loaded, valid in checked
            ]
            if manual._group_overlap(reloaded[0], reloaded[1]) > tolerance:
                continue
            if any(
                not np.allclose(new.bounds, old.bounds, rtol=0, atol=max_shift_mm + 0.001)
                or abs(float(new.volume) - volume) > max(0.05, abs(volume) * 1e-7)
                or abs(float(loaded.volume) - volume) > max(0.05, abs(volume) * 1e-7)
                for (loaded, _), new, old, volume in zip(checked, new_meshes, meshes, original_volumes)
            ):
                continue
            adjustment = dict(
                method="bounded_tangential_shell_separation",
                max_displacement_mm=max((np.linalg.norm(vector) for part in shifts for vector in part), default=0.0),
                vectors_mm=dict(part_a=shifts[0], part_b=shifts[1]),
                reason="STL 不记录壳体身份；贴边壳体直接导出会被焊接为非流形边",
                physical_fusion=False,
            )
            return candidates, new_meshes, adjustment
    bad = [
        "AB"[i] + "（" + _stl_problem(loaded, count) + "）"
        for i, (loaded, valid, count) in enumerate(baseline)
        if not valid or (baseline[i][0] is not None and len(baseline[i][0].split(only_watertight=False)) != count)
    ]
    raise ValueError(f"分件 {'、'.join(bad)} 的 STL 在 ≤0.02 mm 的安全分离内仍非闭合；请调整切面或单独导出这些壳体")


def preview(payload):
    source = _verified_source()
    params = _params(payload, source)
    mesh = manual._mesh(source["stl"])
    solid = mesh_solid(mesh)
    cutter = _cutter(mesh, params)
    sides = [("lower", solid ^ cutter), ("upper", solid - cutter)]
    preview_id = "cut-" + uuid.uuid4().hex[:12]
    folder = _folder() / "previews" / preview_id
    folder.mkdir(parents=True, exist_ok=False)
    components = []
    for side, side_solid in sides:
        for component in side_solid.decompose():
            part = to_trimesh(component)
            if part.volume < MIN_PREVIEW_VOLUME_MM3:
                continue
            index = len(components)
            key = f"piece_{index}"
            stl = folder / f"{key}.stl"
            part.export(stl)
            export_glb(part, folder / f"{key}.glb", [73, 158, 173, 255] if side == "lower" else [241, 174, 79, 255])
            components.append(
                dict(
                    id=key,
                    side=side,
                    stl=str(stl),
                    url=f"/outputs/manual/cutting/previews/{preview_id}/{key}.glb",
                    volume_mm3=round(float(part.volume), 3),
                    center_mm=part.center_mass.tolist(),
                    bounds_mm=part.bounds.tolist(),
                    closed=bool(part.is_watertight and part.is_winding_consistent),
                )
            )
    if (
        len(components) < 2
        or not any(x["side"] == "lower" for x in components)
        or not any(x["side"] == "upper" for x in components)
    ):
        raise ValueError("切面没有将模型分开；请移动切面或调整方向")
    if not all(x["closed"] for x in components):
        raise ValueError("切割后有未封口的部件")
    record = dict(
        id=preview_id,
        source_id=source["id"],
        source_sha256=source["sha256"],
        params=params,
        components=components,
        closed=True,
        note="每块切出的实体均由布尔运算自动封口；请选择独立零件，其余切出块并回主体。",
    )
    save_json(folder / "preview.json", record)
    return record


def commit(payload):
    if (
        not isinstance(payload, dict)
        or not {"preview_id", "separate_ids"} <= set(payload)
        or set(payload) - {"preview_id", "separate_ids", "discard_ids", "output_mode", "print_orientation"}
    ):
        raise ValueError("提交需要 preview_id 和 separate_ids，可附加 discard_ids、output_mode、print_orientation")
    preview_id = payload["preview_id"]
    if not isinstance(preview_id, str) or not preview_id.startswith("cut-") or not preview_id[4:].isalnum():
        raise ValueError("无效的预览编号")
    path = _folder() / "previews" / preview_id / "preview.json"
    if not path.is_file():
        raise ValueError("切割预览不存在")
    record = json.loads(path.read_text(encoding="utf-8"))
    source = _verified_source()
    if not source or record["source_id"] != source["id"] or record["source_sha256"] != source["sha256"]:
        raise RuntimeError("整件来源已改变，请重新预览")
    ids = payload["separate_ids"]
    all_ids = {x["id"] for x in record["components"]}
    discard_ids = payload.get("discard_ids", [])
    output_mode = payload.get("output_mode", "objects")
    orientation = payload.get("print_orientation", {"part_a": "keep", "part_b": "keep"})
    if output_mode not in ("objects", "parts"):
        raise ValueError("output_mode 只能是 objects 或 parts")
    if (
        not isinstance(orientation, dict)
        or set(orientation) != {"part_a", "part_b"}
        or any(value not in ("keep", "cut_face_down", "flip") for value in orientation.values())
    ):
        raise ValueError("print_orientation 须分别指定 part_a、part_b：keep、cut_face_down 或 flip")
    if (
        not isinstance(ids, list)
        or not isinstance(discard_ids, list)
        or not ids
        or len(set(ids)) != len(ids)
        or len(set(discard_ids)) != len(discard_ids)
        or not set(ids + discard_ids) <= all_ids
        or set(ids) & set(discard_ids)
        or not (all_ids - set(ids) - set(discard_ids))
    ):
        raise ValueError("至少选一块独立零件，并留一块在主体；丢弃块不能同时被选为零件")
    selected = set(ids)
    discarded = set(discard_ids)
    retained = all_ids - selected - discarded
    selected_sides = sorted({piece["side"] for piece in record["components"] if piece["id"] in selected})
    retained_sides = sorted(
        {
            piece["side"]
            for piece in record["components"]
            if piece["id"] not in selected and piece["id"] not in discarded
        }
    )
    axis = np.asarray(record["params"]["normal"], dtype=float)
    if selected_sides == ["upper"]:
        normal_a, normal_b = axis, -axis
    elif selected_sides == ["lower"]:
        normal_a, normal_b = -axis, axis
    else:
        normal_a = normal_b = None
    pieces = [mesh_solid(_preview_mesh(x["stl"])) for x in record["components"]]
    separated = [piece for component, piece in zip(record["components"], pieces) if component["id"] in selected]
    removed = [piece for component, piece in zip(record["components"], pieces) if component["id"] in discarded]
    part_b = _join_without_loss(separated)
    # Without discards, subtracting from the original avoids microscopic
    # curved seams from re-unioning exported cut islands. With discards, use
    # only the explicitly retained preview solids; subtracting nearly
    # coincident shells from the original can leave floating slivers.
    if removed:
        part_a = _join_without_loss(
            [piece for component, piece in zip(record["components"], pieces) if component["id"] in retained]
        )
    else:
        # Reconstructing A from the original avoids duplicate cut seams when
        # it remains sound. On complex imported proxies that subtraction can
        # create inverted micro-shells; retain the exact preview islands then.
        selected_union = part_b[0]
        for piece in part_b[1:]:
            selected_union += piece
        reconstructed = [mesh_solid(manual._mesh(source["stl"])) - selected_union]
        kept = [piece for component, piece in zip(record["components"], pieces) if component["id"] in retained]
        preserved = _group_valid(reconstructed) and sum(
            float((piece - reconstructed[0]).volume()) for piece in kept
        ) <= manual._overlap_tolerance(source["volume_mm3"])
        part_a = reconstructed if preserved else _join_without_loss(kept)
    groups = [part_a, part_b]
    shell_counts = [len(_group_shells(group)) for group in groups]
    if any(count < 1 for count in shell_counts):
        raise ValueError("分件后主体或独立零件为空；请调整选块或切面")
    groups, meshes, simplification_mm = _fit_commit_face_budget(groups)
    if not all(_group_valid(group) for group in groups):
        raise ValueError("分件后的某个壳体未闭合或没有正体积；请调整选块或切面")
    groups, meshes, stl_adjustment = _fit_stl_roundtrip(groups, meshes, axis)
    overlap = manual._group_overlap(groups[0], groups[1])
    tolerance = manual._overlap_tolerance(sum(float(mesh.volume) for mesh in meshes))
    if overlap > tolerance:
        raise ValueError(f"两件在装配位置实体交叠 {overlap:.4f} mm³；请调整选块或切面")
    source_id = "split-" + uuid.uuid4().hex[:12]
    temp = _folder() / "previews" / preview_id
    paths = [temp / "committed_a.stl", temp / "committed_b.stl"]
    for path, mesh in zip(paths, meshes):
        mesh.export(path)
    old_source = manual.SOURCE.read_bytes() if manual.SOURCE.exists() else None
    old_state = manual.STATE.read_bytes() if manual.STATE.exists() else None
    try:
        pair = manual._source_from_files(paths, source_id, source["label"] + " · 已分件")
        pair["cut"] = dict(
            preview_id=preview_id,
            full_source_sha256=source["sha256"],
            selected_ids=ids,
            merged_ids=sorted(all_ids - selected - discarded),
            discarded_ids=sorted(discarded),
            output_mode=output_mode,
            commit_simplification_tolerance_mm=simplification_mm,
            print_orientation=orientation,
            part_a_original_sides=retained_sides,
            part_b_original_sides=selected_sides,
            part_a_shells=len(_group_shells(groups[0])),
            part_b_shells=len(_group_shells(groups[1])),
            grouping="logical; disconnected closed shells are not physically fused",
            stl_serialization_adjustment=stl_adjustment,
            part_a_cut_normal=normal_a.tolist() if normal_a is not None else None,
            part_b_cut_normal=normal_b.tolist() if normal_b is not None else None,
            params=record["params"],
        )
        pair["note"] = (
            f"自动封口；{len(ids)} 块独立，{len(all_ids) - len(ids) - len(discarded)} 块并回主体，"
            f"{len(discarded)} 块丢弃。A 为 {pair['cut']['part_a_shells']} 个封闭壳体，"
            f"B 为 {pair['cut']['part_b_shells']} 个封闭壳体；多壳体仅逻辑分组，未物理融合。"
            "点击两件相对切面可布置配对连接件。"
            + (
                f"为避免 STL 贴边焊接，次要壳体在切面切向做了最多 "
                f"{stl_adjustment['max_displacement_mm']:.4f} mm 的数值分离；"
                "原始整件及预览未修改，分离量已记录。"
                if stl_adjustment
                else ""
            )
        )
        save_json(manual.OUT / "sources" / source_id / "source.json", pair)
        save_json(manual.SOURCE, pair)
        manual.STATE.unlink(missing_ok=True)
        project = manual.current_project()
        return dict(source=pair, project=project, cut=record)
    except Exception:
        if old_source is None:
            manual.SOURCE.unlink(missing_ok=True)
        else:
            manual.SOURCE.write_bytes(old_source)
        if old_state is None:
            manual.STATE.unlink(missing_ok=True)
        else:
            manual.STATE.write_bytes(old_state)
        raise
