"""A slide-in, undercut dovetail for a *planar* shared cut face.

Coordinates are engineering millimetres, Z-up.  The local +Z axis points
from the male part toward the receiver; +Y is the insertion/entry direction.
The receiver groove is deliberately open through the +Y edge of the cut face.
Without that open edge a trapezoidal plug is a captive shape, not a usable
sliding dovetail.

The caller owns part assignment, source-face checks, and the final insertion
path check for the *whole* parts.  ``build_dovetail`` returns the same four
solids as manual._connector_solids: (cut_a, cut_b, male, separate_pin).
``entry_run_mm`` is mandatory and must reach an outer boundary of part B.
Use ``required_entry_run_mm`` to derive it from a planar receiver mesh.
"""

from __future__ import annotations

import math

from backend.engine import mesh_solid, np, trimesh


def _basis(normal, degrees):
    n = np.asarray(normal, dtype=float)
    length = float(np.linalg.norm(n))
    if not math.isfinite(length) or length < 0.9 or length > 1.1:
        raise ValueError("dovetail normal must be a unit vector")
    n /= length
    helper = np.array([1.0, 0.0, 0.0]) if abs(n[0]) < 0.85 else np.array([0.0, 1.0, 0.0])
    u = np.cross(helper, n)
    u /= np.linalg.norm(u)
    v = np.cross(n, u)
    angle = math.radians(float(degrees))
    return u * math.cos(angle) + v * math.sin(angle), -u * math.sin(angle) + v * math.cos(angle), n


def _place(solid, center, axes):
    u, v, n = axes
    return solid.transform(
        [[u[0], v[0], n[0], center[0]], [u[1], v[1], n[1], center[1]], [u[2], v[2], n[2], center[2]]]
    )


def _trapezoid_prism(profile_xz, y0, y1):
    """Closed prism from a CCW cross-section in local X/Z."""
    if y1 <= y0:
        raise ValueError("dovetail extrusion length must be positive")
    count = len(profile_xz)
    vertices = [[x, y, z] for y in (y0, y1) for x, z in profile_xz]
    faces = []
    # X/Z CCW points toward -Y (because X cross Z = -Y).
    for i in range(1, count - 1):
        faces.extend(([0, i, i + 1], [count, count + i + 1, count + i]))
    for i in range(count):
        j = (i + 1) % count
        faces.extend(([i, count + i, count + j], [i, count + j, j]))
    mesh = trimesh.Trimesh(vertices=np.asarray(vertices), faces=np.asarray(faces), process=True)
    if not mesh.is_watertight or mesh.volume <= 0:
        raise ValueError("dovetail profile did not make a closed positive solid")
    return mesh_solid(mesh)


def required_entry_run_mm(receiver_mesh, item, *, margin_mm=1.0, step_mm=0.25):
    """Find +Y exit of the connected planar cut region at the chosen point.

    This samples the cut-face triangles along the exact groove centreline.  It
    rejects a receiver with no planar face or an immediate gap.  The caller
    should still verify the complete swept assembly after cutting the groove.
    """
    if not isinstance(receiver_mesh, trimesh.Trimesh):
        raise TypeError("receiver_mesh must be a trimesh.Trimesh")
    center = np.asarray(item["center_mm"], dtype=float)
    normal = np.asarray(item["normal"], dtype=float)
    if item.get("flip", False):
        normal = -normal
    u, v, n = _basis(normal, item.get("rotation_deg", 0))
    face_normals = receiver_mesh.face_normals
    triangles = receiver_mesh.triangles
    # Receiver-facing cut face points against local +Z.
    coplanar = np.where((face_normals @ -n > 0.985) & (np.max(np.abs((triangles - center) @ n), axis=1) < 0.15))[0]
    if not len(coplanar):
        raise ValueError("dovetail requires a planar receiver cut face")
    uv = np.stack(((triangles[coplanar] - center) @ u, (triangles[coplanar] - center) @ v), axis=-1)
    width = float(item["size_mm"])
    clearance = float(item.get("size_tolerance_mm", item.get("clearance_mm", 0.2)))
    half_track = width / 2 + clearance + 0.15
    # Most triangles in a dense imported GLB are irrelevant to this groove.
    near_track = (
        (np.min(uv[:, :, 0], axis=1) <= half_track)
        & (np.max(uv[:, :, 0], axis=1) >= -half_track)
        & (np.max(uv[:, :, 1], axis=1) >= 0)
    )
    uv = uv[near_track]
    if not len(uv):
        raise ValueError("dovetail footprint must lie on the receiver cut face")
    a, b, c = uv[:, 0], uv[:, 1], uv[:, 2]
    v0, v1 = c - a, b - a
    den = v0[:, 0] * v1[:, 1] - v1[:, 0] * v0[:, 1]
    valid = np.abs(den) > 1e-12
    inv = np.zeros_like(den)
    inv[valid] = 1 / den[valid]

    def inside(transverse, distance):
        delta = np.array([transverse, distance]) - a
        bary_u = (delta[:, 0] * v1[:, 1] - v1[:, 0] * delta[:, 1]) * inv
        bary_v = (v0[:, 0] * delta[:, 1] - delta[:, 0] * v0[:, 1]) * inv
        return bool(np.any(valid & (bary_u >= -1e-5) & (bary_v >= -1e-5) & (bary_u + bary_v <= 1 + 1e-5)))

    transverse_samples = np.linspace(-half_track, half_track, max(3, int(math.ceil(2 * half_track / step_mm)) + 1))
    if not all(inside(float(x), 0) for x in transverse_samples):
        raise ValueError("dovetail footprint must lie on the receiver cut face")
    max_run = float(np.max(uv[:, :, 1])) + max(margin_mm, step_mm)
    if max_run > 500:
        raise ValueError("dovetail cut face is too large for a local open groove")
    # Step in the cut-face region until the first real gap.  A full groove is
    # then extended past that boundary, so the channel is open for insertion.
    count = int(math.ceil(max_run / step_mm))
    farthest_exit = 0.0
    for transverse in transverse_samples:
        last_inside = 0.0
        for i in range(1, count + 1):
            distance = min(i * step_mm, max_run)
            if not inside(float(transverse), distance):
                if last_inside < step_mm:
                    raise ValueError("dovetail insertion side leaves the cut face immediately")
                farthest_exit = max(farthest_exit, distance)
                break
            last_inside = distance
        else:
            raise ValueError("dovetail groove did not reach an open cut-face edge")
    return farthest_exit + margin_mm


def build_dovetail(item):
    """Return a matched male tongue and edge-open receiver groove.

    Required item fields: center_mm, normal, size_mm (head width), depth_mm,
    rotation_deg, entry_run_mm. Optional: slide_length_mm, flip,
    size_tolerance_mm, depth_tolerance_mm, neck_ratio (0.45..0.8).
    """
    center = np.asarray(item["center_mm"], dtype=float)
    if center.shape != (3,) or not np.isfinite(center).all():
        raise ValueError("dovetail center_mm must have three finite numbers")
    normal = np.asarray(item["normal"], dtype=float)
    if item.get("flip", False):
        normal = -normal
    axes = _basis(normal, item.get("rotation_deg", 0))

    width = float(item["size_mm"])
    depth = float(item["depth_mm"])
    length = float(item.get("slide_length_mm", 1.6 * width))
    entry = float(item["entry_run_mm"])
    clearance = float(item.get("size_tolerance_mm", item.get("clearance_mm", 0.2)))
    axial_gap = float(item.get("depth_tolerance_mm", 0.1))
    neck_ratio = float(item.get("neck_ratio", 0.62))
    values = (width, depth, length, entry, clearance, axial_gap, neck_ratio)
    if not all(math.isfinite(x) for x in values):
        raise ValueError("dovetail dimensions must be finite")
    if not 3 <= width <= 25 or not 1.5 <= depth <= 12 or not width <= length <= 60:
        raise ValueError("dovetail width, depth or slide length is out of range")
    if not 0.45 <= neck_ratio <= 0.8 or not 0.05 <= clearance <= 0.8 or not 0 <= axial_gap <= 0.8:
        raise ValueError("dovetail neck ratio or tolerances are out of range")
    if not length / 2 + 0.5 < entry <= 500:
        raise ValueError("entry_run_mm must extend beyond the male tongue to an open cut-face edge")

    embed = 0.3
    neck_half = width * neck_ratio / 2
    head_half = width / 2
    slope = (head_half - neck_half) / (depth + embed)

    def half_width(z):
        return neck_half + slope * (z + embed)

    male_profile = [(-neck_half, -embed), (neck_half, -embed), (head_half, depth), (-head_half, depth)]
    socket_low = -0.35
    socket_high = depth + axial_gap + 0.2
    socket_profile = [
        (-(half_width(socket_low) + clearance), socket_low),
        (half_width(socket_low) + clearance, socket_low),
        (half_width(socket_high) + clearance, socket_high),
        (-(half_width(socket_high) + clearance), socket_high),
    ]

    male = _place(_trapezoid_prism(male_profile, -length / 2, length / 2), center, axes)
    groove = _place(_trapezoid_prism(socket_profile, -length / 2 - axial_gap - 0.2, entry), center, axes)
    return None, groove, male, None


def slide_path_report(part_a, part_b, item, *, samples=41):
    """Sample full-part rigid translation from the open side to final assembly.

    ``part_a`` and ``part_b`` are final Manifold solids, after applying the
    groove/tongue. A passing finite sample is evidence, not a continuous
    swept-volume or material-strength guarantee.
    """
    if not isinstance(samples, int) or not 3 <= samples <= 201:
        raise ValueError("slide path samples must be an integer from 3 to 201")
    normal = np.asarray(item["normal"], dtype=float)
    flipped = bool(item.get("flip", False))
    if flipped:
        normal = -normal
    _, tangent, _ = _basis(normal, item.get("rotation_deg", 0))
    length = float(item.get("slide_length_mm", 1.6 * float(item["size_mm"])))
    entry = float(item["entry_run_mm"])
    if not math.isfinite(entry) or entry <= length / 2 + 0.5:
        raise ValueError("invalid dovetail entry length for slide path")
    start = (1 if flipped else -1) * (entry + length / 2 + 0.5)
    poses = []
    for offset in np.linspace(start, 0.0, samples):
        overlap = float((part_a ^ part_b.translate(tangent * float(offset))).volume())
        poses.append(dict(offset_mm=round(float(offset), 5), overlap_mm3=round(max(0.0, overlap), 8)))
    maximum = max(p["overlap_mm3"] for p in poses)
    return dict(
        direction_xyz=tangent.tolist(),
        moving_part="part_b",
        poses=poses,
        max_overlap_mm3=maximum,
        collision_free=maximum <= 1e-4,
        continuous_proof=False,
    )
