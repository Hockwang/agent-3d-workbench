"""Explicit source-shaped eye screens and smile vents; millimetres, front -Y.

No facial landmark inference: source component IDs and groove polylines are
declared by the caller. The fine grid is real printable geometry, not a
texture. Imported by `studio.core.head_shell` (task template `shell-kit`),
never run standalone.
"""

import numpy as np
import manifold3d as mf
import trimesh
from shapely.geometry import Polygon, LineString, box as rect
from shapely.ops import unary_union

from studio.i18n import render
from studio.core.kernels.mechanical_geometry import mesh, solid


def polygons(shape):
    if shape.is_empty:
        return []
    if shape.geom_type == "Polygon":
        return [shape]
    return [p for p in shape.geoms if p.geom_type == "Polygon" and p.area > 1e-8]


def prism(shape):
    """Extrude XZ polygons towards -Y, from the central split plane."""
    contours = []
    for p in polygons(shape):
        from shapely.geometry.polygon import orient

        p = orient(p, sign=1)
        contours.append(np.asarray(p.exterior.coords)[:-1])
        contours.extend(np.asarray(r.coords)[:-1] for r in p.interiors)
    return mf.CrossSection(contours).extrude(2000).rotate([90, 0, 0])


def projection(s):
    # Preserve a concave inner-corner outline instead of bridging it with a
    # convex hull. CrossSection contours include both outer rings and holes.
    result = Polygon()
    for contour in s.rotate([-90, 0, 0]).project().to_polygons():
        result = result.symmetric_difference(Polygon(contour))
    return result


def extension_outline(config):
    points = np.asarray(config["extension_outline_xz_mm"], float)
    if points.ndim != 2 or points.shape[1] != 2 or len(points) < 3 or not np.isfinite(points).all():
        raise ValueError(render("head_shell_vision.eye_extension_outline_needs_points"))
    p = Polygon(points)
    if not p.is_valid or p.area < 10:
        raise ValueError(render("head_shell_vision.eye_extension_outline_invalid"))
    return p


def export_stable_solid(s):
    """Resolve sub-micron CSG slivers at the actual GLB float32 precision.

    Simplify by <=0.001 mm, quantize once in metres, weld exact positions and
    remove only collapsed triangles. No hole filling or topology guessing.
    """
    m = mesh(s.simplify(0.001))
    vertices, inverse = np.unique((m.vertices * 0.001).astype(np.float32).astype(float), axis=0, return_inverse=True)
    q = trimesh.Trimesh(vertices * 1000, inverse[m.faces], process=False)
    # Only truly collapsed edges are removed; no finite-area triangles hidden.
    keep = (q.faces[:, 0] != q.faces[:, 1]) & (q.faces[:, 1] != q.faces[:, 2]) & (q.faces[:, 0] != q.faces[:, 2])
    removed = int((~keep).sum())
    q.update_faces(keep)
    q.remove_unreferenced_vertices()
    if not q.is_volume or len(q.split(only_watertight=False, repair=False)) != 1:
        raise ValueError(render("head_shell_vision.eye_screen_export_not_watertight"))
    result = solid(q)
    if abs(result.volume() - s.volume()) > max(0.01, s.volume() * 0.001):
        raise ValueError(render("head_shell_vision.eye_screen_export_volume_changed"))
    return result, {
        "simplification_tolerance_mm": 0.001,
        "quantization": "float32 metres",
        "removed_collapsed_triangles": removed,
        "volume_change_mm3": result.volume() - s.volume(),
    }


def eye_screen(part, source, protected, config):
    # Freeze the shared CSG operand before projection and branch reuse. Native
    # lazy differences can otherwise make the inspection rim evaluate empty.
    part = solid(mesh(part))
    values = {
        k: float(config.get(k, v))
        for k, v in [("rim_mm", 2.2), ("pitch_mm", 3), ("bar_mm", 0.8), ("thickness_mm", 0.8)]
    }
    if not all(np.isfinite(v) and v > 0 for v in values.values()):
        raise ValueError(render("head_shell_vision.eye_screen_params_must_be_positive"))
    rim, pitch, bar, thick = (values[k] for k in ("rim_mm", "pitch_mm", "bar_mm", "thickness_mm"))
    if not 0.4 <= bar < pitch or not 0.4 <= thick <= 2 or pitch > 8 or rim > 10:
        raise ValueError(render("head_shell_vision.eye_screen_params_out_of_range"))
    aperture = projection(part).buffer(-rim)
    body_opening = prism(aperture)
    if protected:
        aperture = aperture.difference(unary_union([projection(s).buffer(rim) for s in protected]))
    if aperture.is_empty or aperture.area < 25:
        raise ValueError(render("head_shell_vision.eye_screen_insufficient_area"))
    cutter = prism(aperture)
    # Translation difference retains the original front skin, with an exact
    # thickness along Y. It is not a uniform normal-offset thickness claim.
    frame = part - cutter
    # Use one subtraction, rather than re-union of pieces sharing the same
    # aperture boundary. That union leaves coincident edges after STL float32
    # rounding on curved source surfaces.
    screen = part - (source.translate([0, thick, 0]) ^ cutter)
    x0, z0, x1, z1 = aperture.bounds
    cells = []
    for x in np.arange(np.floor(x0 / pitch) * pitch, x1, pitch):
        for z in np.arange(np.floor(z0 / pitch) * pitch, z1, pitch):
            cell = rect(x + bar / 2, z + bar / 2, x + pitch - bar / 2, z + pitch - bar / 2)
            # Keep complete holes: avoids fragile slivers at the rim/highlight.
            if aperture.contains(cell):
                cells.append(cell)
    if not cells:
        raise ValueError(render("head_shell_vision.eye_screen_no_valid_holes"))
    holes = unary_union(cells)
    screen = screen - prism(holes)
    screen, stability = export_stable_solid(screen)
    return (
        screen,
        cutter,
        frame,
        body_opening,
        {
            **values,
            "hole_count": len(cells),
            "aperture_projection_area_mm2": aperture.area,
            "hole_projection_area_mm2": holes.area,
            "projected_open_fraction": holes.area / aperture.area,
            "export_stabilization": stability,
            "bounds_xz_mm": list(aperture.bounds),
            "thickness_definition": "front skin thickness along Y; source outline and solid rim retained",
            "attachment": "original removable colour insert socket; no snap retention claimed",
        },
    )


def smile_vents(configs):
    shapes = []
    for c in configs:
        points = np.asarray(c["points_xz_mm"], float)
        width = float(c.get("width_mm", 1.4))
        if points.ndim != 2 or points.shape[1] != 2 or len(points) < 2 or not np.isfinite(points).all():
            raise ValueError(render("head_shell_vision.smile_vent_needs_points"))
        if not np.isfinite(width) or not 0.5 <= width <= 4:
            raise ValueError(render("head_shell_vision.smile_vent_width_range"))
        shapes.append(LineString(points).buffer(width / 2, quad_segs=8))
    shape = unary_union(shapes)
    return prism(shape), {
        "count": len(configs),
        "projected_area_mm2": shape.area,
        "paths": configs,
        "purpose": "ventilation only; airflow is not measured",
    }
