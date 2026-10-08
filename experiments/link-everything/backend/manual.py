"""Place paired connectors on a selected interface of two split STL parts.

Coordinates in the API and STL are millimetres/Z-up. Viewer GLBs use metres/Y-up.
The source files are immutable; each edit creates a separate revision.
"""

from __future__ import annotations

import base64
import json
import math
import time
import uuid
from pathlib import Path

from backend.engine import box, export_glb, mesh_solid, save_json, sha, to_trimesh
from backend.engine import np, trimesh
from backend.dovetail import build_dovetail, required_entry_run_mm, _basis as dovetail_basis
from backend.cantilever import build_cantilever
from backend.hinge import build_hinge
from backend.linear_rail import build_linear_rail
from backend.motion_preview import build_motion_preview
from backend.source_cache import CURRENT_SOURCE
from backend.face_lookup import face_at as indexed_face_at

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs" / "manual"
STATE = OUT / "project.json"
SOURCE = OUT / "source.json"
SOURCE_MAX_BYTES = 12 * 1024 * 1024
MAX_CONNECTORS = 24
MAX_MANUAL_SIZE_MM = 80
MAX_MANUAL_DEPTH_MM = 32
MAX_DOVETAIL_SLIDE_MM = 120
SOURCE_URL = "https://help.prusa3d.com/article/cut-tool_1779"
COLORS = [[73, 158, 173, 255], [241, 174, 79, 255], [126, 167, 96, 255]]


def _finite(value, name, low=None, high=None):
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a number")
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a number")
    if not math.isfinite(number) or (low is not None and number < low) or (high is not None and number > high):
        raise ValueError(f"{name} must be in [{low}, {high}]")
    return number


def _mesh(path, label=None):
    mesh = trimesh.load(path, force="mesh", process=True)
    name = label or Path(path).stem
    if not isinstance(mesh, trimesh.Trimesh):
        raise ValueError(f"{name} STL 未解析为三角网格")
    if not mesh.is_watertight or not mesh.is_winding_consistent:
        _, edge_counts = np.unique(np.sort(mesh.edges, axis=1), axis=0, return_counts=True)
        boundaries = int(np.count_nonzero(edge_counts == 1))
        nonmanifold = int(np.count_nonzero(edge_counts > 2))
        details = []
        if boundaries:
            details.append(f"{boundaries} 条开放边")
        if nonmanifold:
            details.append(f"{nonmanifold} 条多重共享边（可能是壳体贴边后被 STL 焊接）")
        if not mesh.is_winding_consistent:
            details.append("法线方向不一致")
        raise ValueError(f"{name} STL 不是闭合实体：" + ("、".join(details) or "拓扑异常"))
    if len(mesh.faces) > 250000:
        raise ValueError("STL 网格超过每件 250000 面上限；请先降低面数")
    if mesh.volume < 1:
        raise ValueError("STL 实体体积不足 1 mm³；请检查微小碎屑或尺寸单位")
    return mesh


def _solid_shells(solid):
    """Audit each disconnected shell in one logical STL part."""
    shells = []
    for index, component in enumerate(solid.decompose(), 1):
        mesh = to_trimesh(component)
        shells.append(
            dict(
                index=index,
                closed=bool(mesh.is_watertight and mesh.is_winding_consistent),
                watertight=bool(mesh.is_watertight),
                winding_consistent=bool(mesh.is_winding_consistent),
                volume_mm3=float(mesh.volume),
                faces=len(mesh.faces),
                bounds_mm=mesh.bounds.tolist(),
            )
        )
    return shells


def _group_mesh(solids):
    """Concatenate shell triangles without a Boolean union between them."""
    return trimesh.util.concatenate([to_trimesh(solid) for solid in solids])


def _group_overlap(left, right):
    # Manifold may return a tiny negative signed volume for coincident faces.
    # Physical intersection volume cannot be negative, so clamp numerical
    # round-off before comparing to tolerances or displaying it in reports.
    return sum(max(0.0, float((a ^ b).volume())) for a in left for b in right)


def _overlap_tolerance(volume_mm3):
    # Boolean intersections of metre-scale proxy meshes can leave a few
    # thousandths of a cubic millimetre at a coincident cut face.
    return max(1e-4, float(volume_mm3) * 1e-10)


def _source_from_files(paths, source_id, label):
    meshes = [_mesh(path, label="分件 " + "AB"[index]) for index, path in enumerate(paths)]
    folder = OUT / "sources" / source_id
    folder.mkdir(parents=True, exist_ok=False)
    result = []
    for index, (path, mesh) in enumerate(zip(paths, meshes)):
        shells = mesh.split(only_watertight=False)
        if not shells or any(
            not shell.is_watertight or not shell.is_winding_consistent or shell.volume <= 0 for shell in shells
        ):
            raise ValueError("源零件含未闭合或非正体积的壳体")
        stem = "part_" + "ab"[index]
        target = folder / (stem + ".stl")
        target.write_bytes(Path(path).read_bytes())
        export_glb(mesh, folder / (stem + ".glb"), COLORS[index])
        result.append(
            dict(
                id=stem,
                stl=str(target),
                url="/outputs/manual/sources/" + source_id + "/" + stem + ".glb",
                sha256=sha(target),
                bounds_mm=mesh.bounds.tolist(),
                faces=len(mesh.faces),
                shell_count=len(shells),
                volume_mm3=float(mesh.volume),
            )
        )
    record = dict(
        id=source_id,
        label=label,
        parts=result,
        units="mm",
        coordinate_system="mm/Z-up",
        note="两个零件须保留装配坐标，并有相对的共面平整切面。原始 STL 按 SHA-256 冻结。",
    )
    save_json(folder / "source.json", record)
    save_json(SOURCE, record)
    return record


def initialize():
    if SOURCE.exists():
        source = json.loads(SOURCE.read_text(encoding="utf-8"))
        if all(Path(part["stl"]).is_file() for part in source["parts"]):
            return source
    OUT.mkdir(parents=True, exist_ok=True)
    sample = OUT / "_sample"
    sample.mkdir(exist_ok=True)
    for index, bounds in enumerate(([[-18, -15, 0], [18, 15, 10]], [[-18, -15, 10], [18, 15, 19]])):
        to_trimesh(box(*bounds)).export(sample / ("part_" + "ab"[index] + ".stl"))
    return _source_from_files([sample / "part_a.stl", sample / "part_b.stl"], "sample-pair", "预切开的双层零件 · 示例")


def upload(payload):
    if set(payload) != {"part_a", "part_b", "names"}:
        raise ValueError("upload requires part_a, part_b and names")
    if not isinstance(payload["names"], list) or len(payload["names"]) != 2:
        raise ValueError("two source names required")
    raw = []
    for key in ("part_a", "part_b"):
        data = payload[key]
        if not isinstance(data, str) or len(data) > SOURCE_MAX_BYTES * 4 // 3 + 4:
            raise ValueError("STL exceeds 12 MB per part")
        try:
            content = base64.b64decode(data, validate=True)
        except Exception:
            raise ValueError("invalid base64 STL")
        if not 80 <= len(content) <= SOURCE_MAX_BYTES:
            raise ValueError("STL must be between 80 bytes and 12 MB")
        raw.append(content)
    source_id = "s" + uuid.uuid4().hex[:12]
    incoming = OUT / "_incoming" / source_id
    incoming.mkdir(parents=True, exist_ok=False)
    paths = []
    old_source = SOURCE.read_bytes() if SOURCE.exists() else None
    old_state = STATE.read_bytes() if STATE.exists() else None
    try:
        for index, content in enumerate(raw):
            path = incoming / ("part_" + "ab"[index] + ".stl")
            path.write_bytes(content)
            paths.append(path)
        meshes = [_mesh(path) for path in paths]
        if (mesh_solid(meshes[0]) ^ mesh_solid(meshes[1])).volume() > 1e-4:
            raise ValueError("the two imported STL parts overlap in their assembled coordinates")
        face_count = len(meshes[0].faces)
        candidates = np.unique(
            np.concatenate(
                (
                    np.argsort(meshes[0].area_faces)[-min(64, face_count) :],
                    np.linspace(0, face_count - 1, min(64, face_count), dtype=int),
                )
            )
        )
        if not any(
            _face_at(meshes[1], meshes[0].triangles_center[i], meshes[0].face_normals[i], opposite=True)
            for i in candidates
        ):
            raise ValueError("no shared, opposite planar cut faces were found in the imported pair")
        label = " + ".join(str(name)[:80] for name in payload["names"])
        record = _source_from_files(paths, source_id, label)
        STATE.unlink(missing_ok=True)
        project = current_project()
        return dict(source=record, project=project)
    except Exception:
        if old_source is None:
            SOURCE.unlink(missing_ok=True)
        else:
            SOURCE.write_bytes(old_source)
        if old_state is None:
            STATE.unlink(missing_ok=True)
        else:
            STATE.write_bytes(old_state)
        raise
    finally:
        for path in paths:
            path.unlink(missing_ok=True)
        incoming.rmdir()


def restore_sample():
    record_path = OUT / "sources" / "sample-pair" / "source.json"
    if not record_path.exists():
        raise ValueError("sample source is unavailable")
    source = json.loads(record_path.read_text(encoding="utf-8"))
    save_json(SOURCE, source)
    STATE.unlink(missing_ok=True)
    return dict(source=source, project=current_project())


def current_project():
    source = initialize()
    if STATE.exists():
        project = json.loads(STATE.read_text(encoding="utf-8"))
        if project.get("source_id") == source["id"]:
            # Older saved revisions already contain the mechanism's measured
            # axis and collision report. Expose a preview on read without
            # rewriting the user's frozen project or artifacts.
            report = project.get("report")
            if isinstance(report, dict):
                preview = build_motion_preview(project.get("connectors"), report, revision=project.get("revision"))
                if report.get("motion_preview") != preview:
                    project = {**project, "report": {**report, "motion_preview": preview}}
            return project
    return generate({"connectors": [], "source_id": source["id"]})


def _point_in_triangle(point, tri, normal):
    a, b, c = tri
    ab, bc, ca = b - a, c - b, a - c
    return all(
        float(np.dot(np.cross(edge, point - origin), normal)) >= -1e-4 for edge, origin in ((ab, a), (bc, b), (ca, c))
    )


def _face_at(mesh, point, normal, opposite=False):
    return indexed_face_at(mesh, point, normal, opposite, _point_in_triangle)


def _basis(normal, degrees):
    n = normal / np.linalg.norm(normal)
    helper = np.array([1.0, 0.0, 0.0]) if abs(n[0]) < 0.85 else np.array([0.0, 1.0, 0.0])
    u = np.cross(helper, n)
    u /= np.linalg.norm(u)
    v = np.cross(n, u)
    angle = math.radians(degrees)
    u2, v2 = u * math.cos(angle) + v * math.sin(angle), -u * math.sin(angle) + v * math.cos(angle)
    return u2, v2, n


def _place(solid, center, basis):
    u, v, n = basis
    return solid.transform(
        [[u[0], v[0], n[0], center[0]], [u[1], v[1], n[1], center[1]], [u[2], v[2], n[2], center[2]]]
    )


def _profile(radius, z0, z1, shape, style, bulge=0):
    sides = {"circle": 64, "triangle": 3, "square": 4, "hexagon": 6}[shape]
    if shape == "square":
        radius *= math.sqrt(2)  # size is the square side, not its diagonal
    angle = math.pi / 4 if shape == "square" else 0
    factors = [1.0, 0.86 if style == "tapered" else 1.0]
    if bulge:
        factors = [
            1.0,
            0.95 if style == "tapered" else 1.0,
            1.0 + bulge,
            1.0 + bulge,
            0.86 if style == "tapered" else 1.0,
        ]
        heights = [z0, z0 + (z1 - z0) * 0.45, z0 + (z1 - z0) * 0.55, z0 + (z1 - z0) * 0.75, z1]
    else:
        heights = [z0, z1]
    vertices = []
    for factor, z in zip(factors, heights):
        vertices.extend(
            [
                [
                    radius * factor * math.cos(2 * math.pi * i / sides + angle),
                    radius * factor * math.sin(2 * math.pi * i / sides + angle),
                    z,
                ]
                for i in range(sides)
            ]
        )
    faces = []
    for k in range(len(heights) - 1):
        for i in range(sides):
            j = (i + 1) % sides
            faces.extend(
                [
                    [k * sides + i, k * sides + j, (k + 1) * sides + j],
                    [k * sides + i, (k + 1) * sides + j, (k + 1) * sides + i],
                ]
            )
    faces.extend([[0, i + 1, i] for i in range(1, sides - 1)])
    top = (len(heights) - 1) * sides
    faces.extend([[top, top + i, top + i + 1] for i in range(1, sides - 1)])
    mesh = trimesh.Trimesh(vertices=np.array(vertices), faces=np.array(faces), process=True)
    return mesh_solid(mesh)


def _cut_surface_point(point, cut, orientation):
    params = cut["params"]
    mode = params["mode"]
    origin = np.array(params["origin_mm"])
    axis = np.array(params["normal"])
    u, v, _ = _basis(axis, 0)
    x = float((point - origin) @ u)
    y = float((point - origin) @ v)
    amplitude = params["amplitude_mm"]
    wavelength = params["wavelength_mm"]
    if mode == "wave":
        height = amplitude * math.sin(2 * math.pi * x / wavelength)
        slope_u = amplitude * 2 * math.pi / wavelength * math.cos(2 * math.pi * x / wavelength)
        slope_v = 0
    elif mode == "bowl":
        height = amplitude * ((x / wavelength) ** 2 + (y / wavelength) ** 2)
        slope_u = 2 * amplitude * x / wavelength**2
        slope_v = 2 * amplitude * y / wavelength**2
    else:
        height = slope_u = slope_v = 0
    normal = axis - slope_u * u - slope_v * v
    normal /= np.linalg.norm(normal)
    if normal @ orientation < 0:
        normal = -normal
    return origin + x * u + y * v + height * axis, normal


def _suggested_dimensions(item, meshes, source):
    """Conservative per-placement dimensions for an unfilled manual field.

    The overall part scale sets a target, while the actual shared cut surface
    and the chosen point cap its footprint. This is only an initial value:
    _validate_connector and the complete Boolean/print audits still decide
    whether the requested connector can be generated.
    """
    center = np.asarray(item.get("center_mm"), dtype=float)
    normal = np.asarray(item.get("normal"), dtype=float)
    if (
        center.shape != (3,)
        or normal.shape != (3,)
        or not np.isfinite(center).all()
        or not np.isfinite(normal).all()
        or not 0.9 <= np.linalg.norm(normal) <= 1.1
    ):
        raise ValueError("center_mm and normal require three finite numbers and a unit normal")
    normal = normal / np.linalg.norm(normal)
    if not _face_at(meshes[0], center, normal) or not _face_at(meshes[1], center, normal, opposite=True):
        raise ValueError("连接点必须落在 A/B 相对的共同切面上；请点击分件断面，不要选外表面")
    kind = item.get("type", "plug")
    shape = item.get("shape", "circle")
    rotation = _finite(item.get("rotation_deg", 0), "rotation_deg", -180, 180)
    tolerance = _finite(item.get("size_tolerance_mm", item.get("clearance_mm", 0.2)), "size_tolerance_mm", 0, 0.8)
    bulge = _finite(item.get("bulge_pct", 15), "bulge_pct", 0, 35)
    u, v, n = _basis(normal, rotation)

    def extent(mesh, direction):
        corners = np.array([[x, y, z] for x in mesh.bounds[:, 0] for y in mesh.bounds[:, 1] for z in mesh.bounds[:, 2]])
        values = corners @ direction
        return float(values.max() - values.min())

    face_span = min(extent(mesh, axis) for mesh in meshes for axis in (u, v))
    thickness_bound = min(extent(mesh, n) for mesh in meshes)
    target = min(MAX_MANUAL_SIZE_MM, max(5.5, round(face_span * 0.06, 1)))
    # New blank size fields adapt to this specific point. Explicit values are
    # preserved and checked by the ordinary validator below.
    if "size_mm" in item:
        size = _finite(item["size_mm"], "size_mm", 2, MAX_MANUAL_SIZE_MM)
    else:
        cut = source.get("cut")

        def fits(width):
            radius = width / 2 + tolerance + 0.2
            if shape == "square":
                radius *= math.sqrt(2)
            if kind == "snap":
                radius *= 1 + bulge / 100
            for angle in np.linspace(0, 2 * math.pi, 16, endpoint=False):
                edge = center + radius * (math.cos(angle) * u + math.sin(angle) * v)
                edge_normal = normal
                if cut and cut["params"]["mode"] != "plane":
                    edge, edge_normal = _cut_surface_point(edge, cut, normal)
                if not (
                    indexed_face_at(meshes[0], edge, edge_normal, False, _point_in_triangle, fallback=False)
                    and indexed_face_at(meshes[1], edge, edge_normal, True, _point_in_triangle, fallback=False)
                ):
                    return False
            if kind == "dovetail":
                slide = min(MAX_DOVETAIL_SLIDE_MM, width * 1.6)
                for x in (-width / 2 - tolerance, width / 2 + tolerance):
                    for y in (-slide / 2 - 0.2, slide / 2 + 0.2):
                        edge = center + x * u + y * v
                        if not (
                            indexed_face_at(meshes[0], edge, normal, False, _point_in_triangle, fallback=False)
                            and indexed_face_at(meshes[1], edge, normal, True, _point_in_triangle, fallback=False)
                        ):
                            return False
            return True

        size = None
        for factor in (1, 0.75, 0.56, 0.42, 0.31, 0.23, 0.17, 0.125, 0.09, 0.065, 0.045):
            width = round(max(2, target * factor), 1)
            if fits(width):
                size = width
                break
        if size is None:
            raise ValueError("所选切面位置没有足够的共同面积容纳最小连接件；请向切面内部移动")
    # Bounds along the insertion axis are a conservative coarse guard, not a
    # local wall-thickness proof. Final Boolean and STL checks remain required.
    depth = round(min(MAX_MANUAL_DEPTH_MM, max(4, size * 0.30), max(1, thickness_bound * 0.65)), 1)
    result = dict(size_mm=size, depth_mm=depth)
    if kind == "dovetail":
        result["slide_length_mm"] = round(min(MAX_DOVETAIL_SLIDE_MM, max(size, size * 1.6)), 1)
    return result


def _validate_connector(item, meshes, source=None):
    allowed = {
        "id",
        "type",
        "style",
        "shape",
        "center_mm",
        "normal",
        "depth_mm",
        "size_mm",
        "rotation_deg",
        "clearance_mm",
        "depth_tolerance_mm",
        "size_tolerance_mm",
        "bulge_pct",
        "space_pct",
        "flip",
        "slide_length_mm",
        "neck_ratio",
        "beam_thickness_mm",
        "hook_mm",
        "hinge_axis_center_mm",
        "hinge_axis",
        "pin_radius_mm",
        "knuckle_radius_mm",
        "segment_length_mm",
        "gap_mm",
        "rail_axis",
        "rail_length_mm",
        "rail_width_mm",
        "rail_depth_mm",
        "travel_mm",
        "stop_width_mm",
    }
    if not isinstance(item, dict) or set(item) - allowed:
        raise ValueError("unsupported connector fields")
    choice = {
        key: item.get(key, default)
        for key, default in [("type", "plug"), ("style", "prism"), ("shape", "circle"), ("flip", False)]
    }
    for key, values in [
        ("type", ("plug", "dowel", "snap", "dovetail", "cantilever", "hinge", "linear_rail")),
        ("style", ("prism", "tapered")),
        ("shape", ("circle", "triangle", "square", "hexagon")),
    ]:
        if choice[key] not in values:
            raise ValueError("unknown " + key)
    if not isinstance(choice["flip"], bool):
        raise ValueError("flip must be boolean")
    center = np.asarray(item.get("center_mm"), dtype=float)
    normal = np.asarray(item.get("normal"), dtype=float)
    if center.shape != (3,) or normal.shape != (3,) or not np.isfinite(center).all() or not np.isfinite(normal).all():
        raise ValueError("center_mm and normal require three finite numbers")
    length = np.linalg.norm(normal)
    if not 0.9 <= length <= 1.1:
        raise ValueError("normal must be unit length")
    normal /= length
    cut = source.get("cut") if source else None
    if choice["type"] in ("dovetail", "hinge", "linear_rail") and cut and cut["params"]["mode"] != "plane":
        raise ValueError(f"{choice['type']} requires a planar cut face")
    if not _face_at(meshes[0], center, normal) or not _face_at(meshes[1], center, normal, opposite=True):
        raise ValueError("连接点必须落在 A/B 相对的共同切面上；请点击分件断面，不要选外表面")
    # Older saved projects used one radial clearance. Preserve them while
    # exposing Prusa-style independent depth and size tolerances.
    size_tolerance = _finite(item.get("size_tolerance_mm", item.get("clearance_mm", 0.2)), "size_tolerance_mm", 0, 0.8)
    depth_tolerance = _finite(item.get("depth_tolerance_mm", 0.1), "depth_tolerance_mm", 0, 0.8)
    spec = dict(
        id=str(item.get("id") or uuid.uuid4().hex[:10])[:32],
        **choice,
        center_mm=center.tolist(),
        normal=normal.tolist(),
        depth_mm=_finite(
            item.get("depth_mm", 5.5), "depth_mm", 1.5 if choice["type"] == "dovetail" else 1, MAX_MANUAL_DEPTH_MM
        ),
        size_mm=_finite(item.get("size_mm", 5.5), "size_mm", 2, MAX_MANUAL_SIZE_MM),
        rotation_deg=_finite(item.get("rotation_deg", 0), "rotation_deg", -180, 180),
        clearance_mm=size_tolerance,
        size_tolerance_mm=size_tolerance,
        depth_tolerance_mm=depth_tolerance,
        bulge_pct=_finite(item.get("bulge_pct", 15), "bulge_pct", 0, 35),
        space_pct=_finite(item.get("space_pct", 30), "space_pct", 5, 60),
    )
    if choice["type"] == "dovetail":
        spec["slide_length_mm"] = _finite(
            item.get("slide_length_mm", min(MAX_DOVETAIL_SLIDE_MM, 1.6 * spec["size_mm"])),
            "slide_length_mm",
            spec["size_mm"],
            MAX_DOVETAIL_SLIDE_MM,
        )
        spec["neck_ratio"] = _finite(item.get("neck_ratio", 0.62), "neck_ratio", 0.45, 0.8)
    if choice["type"] == "cantilever":
        if spec["depth_mm"] < 4 or spec["size_mm"] < 4:
            raise ValueError("cantilever requires depth_mm and size_mm at least 4 mm")
        spec["beam_thickness_mm"] = _finite(item.get("beam_thickness_mm", 1.2), "beam_thickness_mm", 0.8, 1.6)
        spec["hook_mm"] = _finite(item.get("hook_mm", 0.8), "hook_mm", 0.45, 1.1)
        if spec["hook_mm"] <= size_tolerance:
            raise ValueError("cantilever hook_mm must exceed side clearance to form a retaining undercut")
    if choice["type"] == "hinge":
        axis_center = np.asarray(item.get("hinge_axis_center_mm"), dtype=float)
        axis = np.asarray(item.get("hinge_axis"), dtype=float)
        if (
            axis_center.shape != (3,)
            or axis.shape != (3,)
            or not np.isfinite(axis_center).all()
            or not np.isfinite(axis).all()
            or not 0.99 <= np.linalg.norm(axis) <= 1.01
            or abs(float(axis @ normal)) > 0.03
        ):
            raise ValueError("hinge requires a finite outside axis center and unit axis in the cut plane")
        spec.update(
            hinge_axis_center_mm=axis_center.tolist(),
            hinge_axis=(axis / np.linalg.norm(axis)).tolist(),
            pin_radius_mm=_finite(item.get("pin_radius_mm", 1.2), "pin_radius_mm", 0.6, 12),
            knuckle_radius_mm=_finite(item.get("knuckle_radius_mm", 2.6), "knuckle_radius_mm", 1.5, 24),
            segment_length_mm=_finite(item.get("segment_length_mm", 24), "segment_length_mm", 12, 300),
            gap_mm=_finite(item.get("gap_mm", 0.4), "gap_mm", 0.2, 4),
        )
        if spec["knuckle_radius_mm"] - spec["pin_radius_mm"] - size_tolerance < 0.8:
            raise ValueError("hinge knuckle wall thickness must be at least 0.8 mm")
        return spec
    if choice["type"] == "linear_rail":
        axis = np.asarray(item.get("rail_axis"), dtype=float)
        if (
            axis.shape != (3,)
            or not np.isfinite(axis).all()
            or not 0.99 <= np.linalg.norm(axis) <= 1.01
            or abs(float(axis @ normal)) > 0.03
        ):
            raise ValueError("linear rail requires a unit travel axis in the cut plane")
        spec.update(
            rail_axis=(axis / np.linalg.norm(axis)).tolist(),
            rail_length_mm=_finite(item.get("rail_length_mm", 16), "rail_length_mm", 8, 180),
            rail_width_mm=_finite(item.get("rail_width_mm", 6), "rail_width_mm", 3, 60),
            rail_depth_mm=_finite(item.get("rail_depth_mm", 4), "rail_depth_mm", 2.5, 32),
            travel_mm=_finite(item.get("travel_mm", 4), "travel_mm", 2, 80),
            stop_width_mm=_finite(item.get("stop_width_mm", 2), "stop_width_mm", 1.2, 12),
        )
        if not 0.15 <= size_tolerance <= 0.6:
            raise ValueError("linear rail clearance must be within 0.15–0.6 mm")
        return spec
    u, v, _ = _basis(normal, spec["rotation_deg"])
    footprint = spec["size_mm"] / 2 + spec["size_tolerance_mm"] + 0.2
    if spec["shape"] == "square":
        footprint *= math.sqrt(2)
    if spec["type"] == "snap":
        footprint *= 1 + spec["bulge_pct"] / 100
    if spec["type"] == "cantilever":
        footprint += spec["hook_mm"]
    for angle in np.linspace(0, 2 * math.pi, 12, endpoint=False):
        edge = center + footprint * (math.cos(angle) * u + math.sin(angle) * v)
        edge_normal = normal
        if cut and cut["params"]["mode"] != "plane":
            edge, edge_normal = _cut_surface_point(edge, cut, normal)
        if not _face_at(meshes[0], edge, edge_normal) or not _face_at(meshes[1], edge, edge_normal, opposite=True):
            raise ValueError("连接件足迹超出 A/B 共同切面；请向内移动或缩小尺寸")
    if choice["type"] == "dovetail":
        # The entire tongue needs support; the groove alone is allowed to run
        # out to the receiver edge, because that is its sliding entrance.
        for x in (-spec["size_mm"] / 2 - size_tolerance, spec["size_mm"] / 2 + size_tolerance):
            for y in (-spec["slide_length_mm"] / 2 - 0.2, spec["slide_length_mm"] / 2 + 0.2):
                edge = center + x * u + y * v
                if not _face_at(meshes[0], edge, normal) or not _face_at(meshes[1], edge, normal, opposite=True):
                    raise ValueError("燕尾榫超出共同平面切面；请向内移动或缩小尺寸")
    return spec


def _connector_solids(item):
    if item["type"] == "dovetail":
        return build_dovetail(item)
    center = np.array(item["center_mm"])
    normal = np.array(item["normal"])
    if item["flip"]:
        normal = -normal
    basis = _basis(normal, item["rotation_deg"])
    if item["type"] == "cantilever":
        return build_cantilever(item, _place, basis)
    radius, depth = item["size_mm"] / 2, item["depth_mm"]
    size_tolerance = item.get("size_tolerance_mm", item.get("clearance_mm", 0.2))
    depth_tolerance = item.get("depth_tolerance_mm", 0.1)
    shape, style = item["shape"], item["style"]
    if item["type"] == "dowel":
        pin = _place(_profile(radius, -depth + 0.25, depth - 0.25, shape, style), center, basis)
        hole_a = _place(
            _profile(radius + size_tolerance, -depth - depth_tolerance - 0.15, 0.3, shape, "prism"), center, basis
        )
        hole_b = _place(
            _profile(radius + size_tolerance, -0.3, depth + depth_tolerance + 0.15, shape, "prism"), center, basis
        )
        return hole_a, hole_b, None, pin
    bulge = item["bulge_pct"] / 100 if item["type"] == "snap" else 0
    male_local = _profile(radius, -0.18, depth, shape, style, bulge)
    if item["type"] == "snap":
        slot_width = item["size_mm"] * item["space_pct"] / 100
        if slot_width > 0.1:
            male_local = male_local - box(
                [-radius - 1, -slot_width / 2, depth * 0.08], [radius + 1, slot_width / 2, depth + 0.3]
            )
        hole_core = _profile(radius + size_tolerance, -0.25, depth + depth_tolerance + 0.2, shape, "prism")
        pocket = _profile(
            radius * (1 + bulge) + size_tolerance, depth * 0.42, depth + depth_tolerance + 0.2, shape, "prism"
        )
        socket = _place(hole_core + pocket, center, basis)
    else:
        socket = _place(
            _profile(radius + size_tolerance, -0.25, depth + depth_tolerance + 0.2, shape, style), center, basis
        )
    male = _place(male_local, center, basis)
    return None, socket, male, None


def _print_oriented(mesh, mode, cut_normal=None):
    """Make a separate bed-oriented copy; assembly coordinates stay untouched."""
    result = mesh.copy()
    if mode == "cut_face_down":
        if cut_normal is None:
            raise ValueError("cut-face-down requires a recorded cut normal")
        normal = np.asarray(cut_normal, dtype=float)
        if normal.shape != (3,) or np.linalg.norm(normal) < 0.5:
            raise ValueError("invalid recorded cut normal")
        result.apply_transform(trimesh.geometry.align_vectors(normal / np.linalg.norm(normal), [0, 0, -1]))
    elif mode == "flip":
        result.apply_transform(trimesh.transformations.rotation_matrix(math.pi, [1, 0, 0]))
    elif mode != "keep":
        raise ValueError("unknown print orientation")
    bounds = result.bounds
    result.apply_translation([-(bounds[0][0] + bounds[1][0]) / 2, -(bounds[0][1] + bounds[1][1]) / 2, -bounds[0][2]])
    return result


def generate(payload):
    source = initialize()
    if not isinstance(payload, dict) or set(payload) - {"connectors", "source_id", "revision"}:
        raise ValueError("invalid manual design request")
    if payload.get("source_id") != source["id"]:
        raise RuntimeError("source changed; refresh the page")
    previous = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else None
    if "revision" in payload and (not previous or payload["revision"] != previous["revision"]):
        raise RuntimeError("revision conflict; refresh before editing")
    items = payload.get("connectors")
    if not isinstance(items, list) or len(items) > MAX_CONNECTORS:
        raise ValueError("connectors must be a list of at most 24 items")

    def read_frozen_parts():
        parsed = [_mesh(part["stl"], label="分件 " + "AB"[index]) for index, part in enumerate(source["parts"])]
        if float((parsed[0].bounds[1] - parsed[1].bounds[0]).max()) > 100000:
            raise ValueError("invalid source bounds")
        separated = [mesh.split(only_watertight=False) for mesh in parsed]
        if any(not group for group in separated):
            raise ValueError("源零件没有封闭壳体")
        return parsed, separated

    meshes, mesh_shells = CURRENT_SOURCE.load(source, read_frozen_parts)
    specs = []
    targets = []
    for item in items:
        if (
            "size_mm" not in item
            or "depth_mm" not in item
            or (item.get("type") == "dovetail" and "slide_length_mm" not in item)
        ):
            suggested = _suggested_dimensions(item, meshes, source)
            item = {**suggested, **item}
        spec = _validate_connector(item, meshes, source)
        center = np.asarray(spec["center_mm"])
        normal = np.asarray(spec["normal"])
        matching = [
            [index for index, shell in enumerate(group) if _face_at(shell, center, normal, opposite=side == 1)]
            for side, group in enumerate(mesh_shells)
        ]
        if any(len(found) != 1 for found in matching):
            raise ValueError("连接件位置须在 A、B 各一个明确的相对壳体切面上")
        target = (matching[0][0], matching[1][0])
        # The complete connector footprint must fit the same two shells.
        spec = _validate_connector(item, [mesh_shells[0][target[0]], mesh_shells[1][target[1]]], source)
        specs.append(spec)
        targets.append(target)
    for spec, target in zip(specs, targets):
        if spec["type"] == "dovetail":
            side = 0 if spec["flip"] else 1
            receiver = mesh_shells[side][target[side]]
            spec["entry_run_mm"] = required_entry_run_mm(receiver, spec)
    if len({x["id"] for x in specs}) != len(specs):
        raise ValueError("connector ids must be unique")
    if any(x["type"] in ("hinge", "linear_rail") for x in specs) and (
        len(specs) != 1 or any(len(group) != 1 for group in mesh_shells)
    ):
        raise ValueError("当前运动机构仅支持 A/B 各单个壳体且没有其他连接件")
    for i, left in enumerate(specs):
        for right in specs[i + 1 :]:
            a, b = np.asarray(left["center_mm"]), np.asarray(right["center_mm"])
            n, m = np.asarray(left["normal"]), np.asarray(right["normal"])
            if abs(float(n @ m)) > 0.98 and abs(float((a - b) @ n)) < 0.4:
                extent = sum(
                    max(
                        x["size_mm"]
                        / 2
                        * (math.sqrt(2) if x["shape"] == "square" else 1)
                        * (1 + x["bulge_pct"] / 100 if x["type"] == "snap" else 1),
                        x.get("slide_length_mm", 0) / 2,
                    )
                    + x["size_tolerance_mm"]
                    + (x.get("hook_mm", 0) if x["type"] == "cantilever" else 0)
                    for x in (left, right)
                )
                if np.linalg.norm(a - b) < extent + 0.2:
                    raise ValueError("two connector footprints overlap; move one or reduce size")
    begin = time.perf_counter()
    solids = [[mesh_solid(shell) for shell in group] for group in mesh_shells]
    source_shell_counts = [len(group) for group in solids]
    pins = []
    mechanism_reports = []
    for item, target in zip(specs, targets):
        if item["type"] == "hinge":
            built = build_hinge(
                solids[0][target[0]],
                solids[1][target[1]],
                center_mm=item["hinge_axis_center_mm"],
                axis=item["hinge_axis"],
                leaf_normal=item["normal"],
                pin_radius_mm=item["pin_radius_mm"],
                knuckle_radius_mm=item["knuckle_radius_mm"],
                clearance_mm=item["size_tolerance_mm"],
                segment_length_mm=item["segment_length_mm"],
                gap_mm=item["gap_mm"],
            )
            solids = [[built["a"]], [built["b"]]]
            pins.append(built["pin"])
            mechanism_reports.append(built["report"])
            continue
        if item["type"] == "linear_rail":
            built = build_linear_rail(
                solids[0][target[0]],
                solids[1][target[1]],
                center_mm=item["center_mm"],
                travel_axis=item["rail_axis"],
                leaf_normal=item["normal"],
                rail_length_mm=item["rail_length_mm"],
                rail_width_mm=item["rail_width_mm"],
                rail_depth_mm=item["rail_depth_mm"],
                clearance_mm=item["size_tolerance_mm"],
                travel_mm=item["travel_mm"],
                stop_width_mm=item["stop_width_mm"],
            )
            solids = [[built["a"]], [built["b"]]]
            pins.append(built["stop"])
            mechanism_reports.append(built["report"])
            continue
        cut_a, cut_b, male, pin = _connector_solids(item)
        if item["flip"]:
            cut_a, cut_b = cut_b, cut_a
        if cut_a is not None:
            solids[0][target[0]] = solids[0][target[0]] - cut_a
        if cut_b is not None:
            solids[1][target[1]] = solids[1][target[1]] - cut_b
        if male is not None:
            side = 1 if item["flip"] else 0
            solids[side][target[side]] = solids[side][target[side]] + male
        if pin is not None:
            pins.append(pin)
    reports = []
    group_meshes = []
    for i, group in enumerate(solids):
        mesh = _group_mesh(group)
        group_meshes.append(mesh)
        shells = [shell for solid in group for shell in _solid_shells(solid)]
        for index, shell in enumerate(shells, 1):
            shell["index"] = index
        record = dict(
            id="part_" + "ab"[i],
            closed=bool(mesh.is_watertight and mesh.is_winding_consistent and all(shell["closed"] for shell in shells)),
            watertight=bool(mesh.is_watertight),
            winding_consistent=bool(mesh.is_winding_consistent),
            components=len(shells),
            shells=shells,
            volume_mm3=float(mesh.volume),
            faces=len(mesh.faces),
        )
        if (
            not record["closed"]
            or record["components"] != source_shell_counts[i]
            or record["volume_mm3"] <= 0
            or any(shell["volume_mm3"] <= 0 for shell in shells)
        ):
            raise ValueError("连接件导致零件壳体破损、消失或被切成更多块；请缩小尺寸或向切面内侧移动")
        reports.append(record)
    pin_reports = []
    for index, pin in enumerate(pins):
        mesh = to_trimesh(pin)
        record = dict(
            id=f"pin_{index + 1}",
            closed=bool(mesh.is_watertight and mesh.is_winding_consistent),
            components=len(pin.decompose()),
            volume_mm3=float(mesh.volume),
            faces=len(mesh.faces),
        )
        if not record["closed"] or record["components"] != 1 or record["volume_mm3"] <= 0:
            raise ValueError("the separate dowel is not a closed printable solid")
        pin_reports.append(record)
    overlap = _group_overlap(solids[0], solids[1])
    overlap_tolerance = _overlap_tolerance(sum(part["volume_mm3"] for part in reports))
    if overlap > overlap_tolerance:
        raise ValueError(f"装配态 A/B 实体交叠 {overlap:.4f} mm³；请增大间隙或移动连接件")
    intra_group_overlap = [
        sum(
            max(0.0, float((left ^ right).volume())) for index, left in enumerate(group) for right in group[index + 1 :]
        )
        for group in solids
    ]
    dovetail_paths = []
    for item in specs:
        if item["type"] != "dovetail":
            continue
        normal = np.asarray(item["normal"]) * (-1 if item["flip"] else 1)
        _, slide_direction, _ = dovetail_basis(normal, item["rotation_deg"])
        start = (1 if item["flip"] else -1) * (item["entry_run_mm"] + item["slide_length_mm"] / 2 + 0.5)
        # Sample the *whole* finished parts, not just the connector pair. This
        # catches surrounding geometry at 31 poses; it is not a continuous
        # collision proof between those poses.
        poses = []
        for offset in np.linspace(start, 0, 31):
            translated = [solid.translate(slide_direction * float(offset)) for solid in solids[1]]
            sampled_overlap = _group_overlap(solids[0], translated)
            poses.append(dict(offset_mm=round(float(offset), 5), overlap_mm3=round(sampled_overlap, 8)))
            if sampled_overlap > overlap_tolerance:
                raise ValueError(
                    "dovetail sliding insertion collides with the other part; move or rotate the connector"
                )
        dovetail_paths.append(
            dict(
                connector_id=item["id"],
                moving_part="part_b",
                axis=slide_direction.tolist(),
                poses=poses,
                overlap_tolerance_mm3=overlap_tolerance,
                collision_free=True,
                continuous_proof=False,
            )
        )
    existing = [int(x.name[1:]) for x in (OUT / "revisions").glob("r[0-9]*") if x.name[1:].isdigit()]
    revision = max([0] + existing) + 1
    folder = OUT / "revisions" / f"r{revision:04d}"
    folder.mkdir(parents=True, exist_ok=False)
    url = "/outputs/manual/revisions/" + folder.name + "/"
    parts = []
    assembly = trimesh.Scene()
    output_mode = source.get("cut", {}).get("output_mode", "objects")
    grouped_meshes = []
    for index, mesh in enumerate(group_meshes + [to_trimesh(pin) for pin in pins]):
        key = "part_" + "ab"[index] if index < 2 else f"pin_{index - 1}"
        stl_path = folder / (key + ".stl")
        mesh.export(stl_path)
        exported = _mesh(stl_path, label=key)
        expected = reports[index]["components"] if index < 2 else 1
        if len(exported.split(only_watertight=False)) != expected:
            raise ValueError(f"{key} STL 导出后壳体数变化；本次结果没有保存为有效项目")
        export_glb(mesh, folder / (key + ".glb"), COLORS[min(index, 2)])
        view_mesh = trimesh.load(folder / (key + ".glb"), force="mesh")
        if output_mode == "parts" and index < 2:
            grouped_meshes.append(view_mesh)
        else:
            assembly.add_geometry(view_mesh, node_name=key, geom_name=key)
        parts.append(
            dict(id=key, name=key, url=url + key + ".glb", color=["#499ead", "#f1ae4f", "#7ea760"][min(index, 2)])
        )
    if grouped_meshes:
        joined = trimesh.util.concatenate(grouped_meshes)
        assembly.add_geometry(joined, node_name="joined_parts", geom_name="joined_parts")
    assembly.export(folder / "assembly.glb")
    print_orientations = source.get("cut", {}).get("print_orientation", {})
    print_exports = []
    if print_orientations:
        for index, mesh in enumerate(group_meshes):
            key = "part_" + "ab"[index]
            mode = print_orientations.get(key, "keep")
            normal = source["cut"].get(key + "_cut_normal")
            print_mesh = _print_oriented(mesh, mode, normal)
            print_stl = folder / (key + "_print.stl")
            print_mesh.export(print_stl)
            printed = _mesh(print_stl, label=key + " 打印朝向")
            if len(printed.split(only_watertight=False)) != reports[index]["components"]:
                raise ValueError(f"{key} 打印朝向 STL 导出后壳体数变化；本次结果没有保存为有效项目")
            export_glb(print_mesh, folder / (key + "_print.glb"), COLORS[index])
            print_exports.append(
                dict(
                    id=key,
                    mode=mode,
                    stl=key + "_print.stl",
                    glb=key + "_print.glb",
                    closed=bool(print_mesh.is_watertight),
                    components=reports[index]["components"],
                    bed_min_z_mm=float(print_mesh.bounds[0][2]),
                )
            )
    report = dict(
        status="geometry_valid_physical_pending",
        parts=reports,
        pins=pin_reports,
        mechanisms=mechanism_reports,
        static_overlap_mm3=overlap,
        static_overlap_tolerance_mm3=overlap_tolerance,
        intra_part_overlap_mm3=dict(part_a=intra_group_overlap[0], part_b=intra_group_overlap[1]),
        connector_count=len(specs),
        source_sha256=[p["sha256"] for p in source["parts"]],
        logical_grouping_only=any(part["components"] > 1 for part in reports),
        grouping_note="多壳体属于同一逻辑零件；各壳体独立封闭，未物理融合。",
        checks=[
            dict(
                id="closed",
                label="逐壳闭合与分组",
                status="pass",
                detail=f"A 有 {reports[0]['components']} 个封闭壳体，B 有 {reports[1]['components']} 个封闭壳体；多壳体未物理融合。",
            ),
            dict(
                id="static",
                label="装配态实体干涉",
                status="pass" if overlap <= overlap_tolerance else "fail",
                detail=f"A/B 相交 {overlap:.6f} mm³，数值公差 {overlap_tolerance:.6f} mm³。",
            ),
            dict(
                id="intra_part",
                label="同组壳体交叠",
                status="review" if max(intra_group_overlap) > overlap_tolerance else "pass",
                detail=f"A 内部 {intra_group_overlap[0]:.6f} mm³，B 内部 {intra_group_overlap[1]:.6f} mm³；导出保留各壳体，未做布尔融合。",
            ),
            dict(id="physical", label="打印与实物配合", status="pending"),
        ],
        cut=source.get("cut"),
        print_exports=print_exports,
        dovetail_assembly_paths=dovetail_paths,
        output_mode=output_mode,
        limitations=[
            "整件分割支持平面、波浪和碗形曲面；连接件按点击处的局部法线生成，曲面大尺寸接头仍须检查局部配合。",
            "刚体几何检查不能证明 Snap 的弹性装配、强度或寿命。",
            "间隙是几何尺寸，打印公差须用真实材料和设备试件校准。",
        ],
    )
    report["motion_preview"] = build_motion_preview(specs, report, revision=revision)
    save_json(
        folder / "parameters.json",
        dict(schema="manual-connectors.parameters/v1", source_id=source["id"], revision=revision, connectors=specs),
    )
    save_json(folder / "report.json", report)
    artifacts = [
        dict(id=p.name, url=url + p.name, absolute_path=str(p), bytes=p.stat().st_size, sha256=sha(p))
        for p in folder.iterdir()
    ]
    project = dict(
        schema="manual-connectors.project/v1",
        source_id=source["id"],
        source=source,
        revision=revision,
        connectors=specs,
        parts=parts,
        artifacts=artifacts,
        report=report,
        elapsed_ms=round((time.perf_counter() - begin) * 1000),
        source_url=SOURCE_URL,
    )
    save_json(folder / "project.json", project)
    temp = STATE.with_suffix(".tmp")
    save_json(temp, project)
    temp.replace(STATE)
    return project
