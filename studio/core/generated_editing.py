"""Rebuildable edits on existing geometry, using the shared Manifold kernel."""

from pathlib import Path
import copy
import hashlib
import json

import numpy as np
import trimesh

from studio.core.editor import _check_static, _textured
from studio.i18n import render
from studio.core.kernels.mechanical_geometry import box, solid, mesh, overlap
from studio.core.task_operations import scene_input, deliver, number

CATALOG = [
    {
        "id": "generated-container",
        "title": "generated_editing.generated_container_title",
        "engine": "python",
        "description": "generated_editing.generated_container_description",
        "params": {
            "inner_width_mm": 60,
            "inner_depth_mm": 40,
            "inner_height_mm": 40,
            "wall_mm": 3,
            "floor_z_mm": 3,
            "center_x_mm": 0,
            "center_y_mm": 0,
            "lip_height_mm": 4,
            "clearance_mm": 0.3,
            "opening_width_mm": 30,
            "opening_depth_mm": 12,
            "allow_material_loss": False,
        },
    },
    {
        "id": "local-dimensions",
        "title": "generated_editing.local_dimensions_title",
        "engine": "python",
        "description": "generated_editing.local_dimensions_description",
        "params": {"axis": "z", "start_mm": 10, "end_mm": 30, "delta_mm": 5},
        "choices": {
            "axis": {
                "x": "generated_editing.local_dimensions_choice_axis_x",
                "y": "generated_editing.local_dimensions_choice_axis_y",
                "z": "generated_editing.local_dimensions_choice_axis_z",
            }
        },
    },
]


def source(w):
    if len(w["inputs"]) != 1:
        raise ValueError(render("generated_editing.static_model_required"))
    path = Path(w["inputs"][0])
    _check_static(path)
    scene = scene_input(path)
    if len(scene.graph.nodes_geometry) != 1:
        raise ValueError(render("generated_editing.single_object_required"))
    transform, key = scene.graph[next(iter(scene.graph.nodes_geometry))]
    result = scene.geometry[key].copy()
    result.apply_transform(transform)
    return result, hashlib.sha256(path.read_bytes()).hexdigest()


def coordinate(p, key, default=0):
    value = float(p.get(key, default))
    if not np.isfinite(value) or abs(value) > 100000:
        raise ValueError(render("generated_editing.finite_mm_coordinate_required", key=key))
    return value


def generated_container(w):
    p, out = w["params"], Path(w["output"])
    original, digest = source(w)
    color = original.visual.main_color
    # Topology edits deliberately don't claim texture preservation.
    if (
        _textured(original)
        or original.visual.kind in ("vertex", "face")
        and np.any(original.visual.vertex_colors != original.visual.vertex_colors[0])
    ) and p.get("allow_material_loss") is not True:
        raise ValueError(render("generated_editing.material_loss_opt_in_required"))
    s = solid(original)
    if len(s.decompose()) != 1:
        raise ValueError(render("generated_editing.cavity_requires_connected_solid"))
    width, depth, height, wall, lip, gap, ow, od = [
        number(p, k, d)
        for k, d in [
            ("inner_width_mm", 60),
            ("inner_depth_mm", 40),
            ("inner_height_mm", 40),
            ("wall_mm", 3),
            ("lip_height_mm", 4),
            ("clearance_mm", 0.3),
            ("opening_width_mm", 30),
            ("opening_depth_mm", 12),
        ]
    ]
    cx, cy, floor = coordinate(p, "center_x_mm"), coordinate(p, "center_y_mm"), coordinate(p, "floor_z_mm", 3)
    cut = floor + height + lip
    if 2 * (wall + gap) >= min(width, depth) or ow > width - 2 * (wall + gap) or od > depth - 2 * (wall + gap):
        raise ValueError(render("generated_editing.lip_or_opening_outside_cavity"))

    def prism(wide, deep, bottom, top):
        return box([cx - wide / 2, cy - deep / 2, bottom], [cx + wide / 2, cy + deep / 2, top])

    # Prove a complete rectangular structural envelope is inside the source.
    # This is stronger than a handful of wall-thickness rays, but not a claim
    # about other thin details already present on the source exterior.
    envelope = prism(width + 2 * wall, depth + 2 * wall, floor - wall, cut + wall)
    loss = max(0.0, (envelope - s).volume())
    if loss > 1e-5:
        raise ValueError(render("generated_editing.cavity_does_not_fit_source", loss=f"{loss:.4f}"))
    # Repeated subtraction of coincident high-poly exterior faces can leave
    # zero-volume shells. Split once at the actual plane instead.
    upper, lower = s.split_by_plane([0, 0, 1], cut)
    body = lower - prism(width, depth, floor, cut + 1)
    # The lid socket is entirely within the proven envelope; no guess about
    # the source's rounded/detailed top surface is needed.
    outer_lip = prism(width - 2 * gap, depth - 2 * gap, cut - lip, cut + wall / 2)
    inner_lip = prism(width - 2 * (gap + wall), depth - 2 * (gap + wall), cut - lip - 1, cut + wall / 2 + 1)
    lid = (upper + (outer_lip - inner_lip)) - prism(ow, od, cut - lip - 1, original.bounds[1, 2] + 1)
    package = prism(width, depth, floor, floor + height)
    checks = {
        "envelope_outside_source_mm3": loss,
        "body_lid_overlap_mm3": overlap(body, lid),
        "package_body_overlap_mm3": overlap(package, body),
        "package_lid_overlap_mm3": overlap(package, lid),
    }
    if any(v > 1e-5 for v in checks.values()):
        raise ValueError(render("generated_editing.structure_intersects_envelope", checks=str(checks)))
    pieces = {}
    for name, part in [("body", body), ("lid", lid)]:
        if len(part.decompose()) != 1:
            raise ValueError(render("generated_editing.disconnected_fragments", name=name))
        item = mesh(part)
        item.visual.face_colors = color
        pieces[name] = item
    # Preserve reproducibility and expose the exact modelling recipe as an artifact.
    report = {
        "source_sha256": digest,
        "params": p,
        "units": "mm",
        "up": "z",
        "cut_z_mm": cut,
        "checks": checks,
        "wall_check": "完整矩形内腔外围包络；不覆盖源外形其他薄细节",
        "clearance_mm": gap,
        "physical_fit": "未实打验证",
        "textures_preserved": False,
        "source_exterior": "切盖与顶部开口以外不移动源表面；新内壁和定位唇为新增几何",
    }
    deliver(pieces, out, report)
    for name in pieces:
        loaded = trimesh.load_mesh(out / (name + ".stl"), process=True)
        if not loaded.is_volume or abs(loaded.volume - pieces[name].volume) > max(1e-3, pieces[name].volume * 1e-5):
            raise ValueError(render("generated_editing.stl_readback_failed", name=name))
    (out / "parameters.json").write_text(
        json.dumps(
            {"template": "generated-container", "params": p, "source_sha256": digest}, ensure_ascii=False, indent=2
        )
    )


def local_dimensions(w):
    p, out = w["params"], Path(w["output"])
    original, digest = source(w)
    axis = p.get("axis", "z")
    if axis not in ("x", "y", "z"):
        raise ValueError(render("generated_editing.axis_must_be_xyz"))
    a = ("x", "y", "z").index(axis)
    start, end, delta = coordinate(p, "start_mm", 10), coordinate(p, "end_mm", 30), coordinate(p, "delta_mm", 5)
    if end <= start or end - start + delta <= 1e-6:
        raise ValueError(render("generated_editing.region_needs_positive_length"))
    # Standard GLB stores float32 metres. Allow its quantization when matching
    # millimetre control rings; do not mistake 9.9999998 mm for a crossed face.
    tolerance = max(1e-6, float(np.abs(original.bounds).max()) * 1e-7)
    if start < original.bounds[0, a] - tolerance or end > original.bounds[1, a] + tolerance:
        raise ValueError(render("generated_editing.control_plane_outside_model"))
    coords = original.vertices[:, a].copy()
    for plane in (start, end):
        coords[np.abs(coords - plane) <= tolerance] = plane
    # A coarse triangle crossing either control plane cannot represent a kink
    # without subdivision. Reject instead of changing UV/topology silently.
    triangles = coords[original.faces]
    for plane in (start, end):
        if np.any((triangles.min(axis=1) < plane) & (triangles.max(axis=1) > plane)):
            raise ValueError(render("generated_editing.control_plane_cuts_triangle"))
    result = original.copy()
    result.visual = copy.deepcopy(original.visual)
    vertices = result.vertices.copy()
    vertices[:, a] += np.clip((coords - start) / (end - start), 0, 1) * delta
    result.vertices = vertices
    if not np.array_equal(original.faces, result.faces):
        raise ValueError(render("generated_editing.unexpected_topology_change"))
    deliver(
        {"model": result},
        out,
        {
            "source_sha256": digest,
            "params": p,
            "topology_preserved": True,
            "fixed_vertices": int(np.count_nonzero(coords <= start)),
            "translated_vertices": int(np.count_nonzero(coords >= end)),
            "before_extents_mm": original.extents.tolist(),
            "after_extents_mm": result.extents.tolist(),
            "control_plane_tolerance_mm": tolerance,
            "collision_check": "未检查与其他对象的碰撞",
        },
        stl=False,
    )


OPERATIONS = {"generated-container": generated_container, "local-dimensions": local_dimensions}
