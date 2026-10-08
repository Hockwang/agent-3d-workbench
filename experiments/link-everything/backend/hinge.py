"""A printable three-knuckle hinge for two already cut, closed solids.

All coordinates are millimetres. ``center_mm`` is a point on the hinge axis,
outside the two source parts. The A leaf receives the two outer knuckles; the
B leaf receives the middle knuckle. A third, removable solid is the straight
pin. This is a rigid-geometry check, not a prediction of print deformation.
"""

from __future__ import annotations

import math

from backend.engine import mf, np, to_trimesh


def _vector(value, name):
    vector = np.asarray(value, dtype=float)
    if vector.shape != (3,) or not np.all(np.isfinite(vector)):
        raise ValueError(f"{name} 必须是三个有限数值")
    return vector


def _unit(value, name):
    vector = _vector(value, name)
    length = float(np.linalg.norm(vector))
    if not 0.99 <= length <= 1.01:
        raise ValueError(f"{name} 必须是单位方向向量")
    return vector / length


def _number(value, name, low, high):
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} 必须是数值") from None
    if not math.isfinite(number) or not low <= number <= high:
        raise ValueError(f"{name} 须在 {low:g}–{high:g} mm 之间")
    return number


def _frame(axis, toward):
    axis = np.asarray(axis, dtype=float)
    toward = np.asarray(toward, dtype=float)
    radial = toward - axis * float(np.dot(toward, axis))
    length = float(np.linalg.norm(radial))
    if length < 1e-5:
        raise ValueError("铰轴正对部件中心，无法判断连接耳片的方向；请移动铰轴")
    radial /= length
    tangential = np.cross(axis, radial)
    return radial, tangential, axis


def _place(solid, center, frame):
    x, y, z = frame
    return solid.transform(
        [[x[0], y[0], z[0], center[0]], [x[1], y[1], z[1], center[1]], [x[2], y[2], z[2], center[2]]]
    )


def _cylinder(radius, z0, z1, center, frame):
    local = mf.Manifold.cylinder(z1 - z0, radius, radius, 64)
    return _place(local, center + frame[2] * z0, frame)


def _web(reach, half_width, z0, z1, center, frame, tangent_offset):
    # The root starts inside the knuckle. The bore is removed after union.
    local = mf.Manifold.cube((reach, half_width * 2, z1 - z0))
    local = local.translate((0, tangent_offset - half_width, z0))
    return _place(local, center, frame)


def _reach_for(part, center, frame, radius, half_width, z0, z1, tangent_offset):
    # A Boolean union can be a single shell even if a large mounting web
    # touches the source through an almost point-sized sliver.  At the scale
    # of a scanned/voxelized model that looks detached and is not a useful
    # attachment.  Require enough *embedded volume* for a several-mm-deep
    # root across the web's cross-section before accepting the bridge.
    section_area = (half_width * 2) * (z1 - z0)
    root_depth = min(3.0, max(0.8, radius * 0.25))
    minimum_overlap = section_area * root_depth
    for reach in (
        radius + 0.5,
        radius + 1,
        radius + 2,
        radius + 3,
        radius + 4,
        radius + 6,
        radius + 8,
        radius + 12,
        radius + 16,
        radius + 24,
        radius + 32,
    ):
        candidate = _web(reach, half_width, z0, z1, center, frame, tangent_offset)
        overlap = float((part ^ candidate).volume())
        if overlap >= minimum_overlap:
            return reach, candidate, overlap, minimum_overlap
    raise ValueError("铰轴距离部件过远，或该轴向位置没有足够实体承接铰链耳片")


def _rigid_rotate(solid, center, axis, degrees):
    radians = math.radians(degrees)
    c, s = math.cos(radians), math.sin(radians)
    kx, ky, kz = axis
    cross = np.array([[0, -kz, ky], [kz, 0, -kx], [-ky, kx, 0]])
    matrix = np.eye(3) * c + (1 - c) * np.outer(axis, axis) + s * cross
    translation = center - matrix @ center
    return solid.transform(np.column_stack((matrix, translation)).tolist())


def _rotation_report(part_a, part_b, center, axis):
    paths = []
    for sign in (-1, 1):
        samples = []
        for angle in (0, 15, 30, 45, 60, 75, 90):
            posed_b = _rigid_rotate(part_b, center, axis, sign * angle)
            samples.append({"angle_deg": sign * angle, "overlap_mm3": round(float((part_a ^ posed_b).volume()), 5)})
        paths.append(
            {
                "direction": "negative" if sign < 0 else "positive",
                "collision_free": all(row["overlap_mm3"] <= 0.001 for row in samples),
                "samples": samples,
            }
        )
    return {
        "sampled_paths": paths,
        "opens_to_90_deg": any(path["collision_free"] for path in paths),
        "continuous_proof": False,
    }


def _pin_removal_report(part_a, part_b, pin_radius, center, frame, length):
    paths = []
    for sign in (-1, 1):
        # The union of every translated pin position is exactly one longer
        # cylinder. This catches an obstruction between discrete samples.
        start = -length / 2 - 0.5 - (length + 1 if sign < 0 else 0)
        end = length / 2 + 0.5 + (length + 1 if sign > 0 else 0)
        swept = _cylinder(pin_radius, start, end, center, frame)
        overlap = float((part_a ^ swept).volume()) + float((part_b ^ swept).volume())
        paths.append(
            {
                "direction": "negative" if sign < 0 else "positive",
                "collision_free": overlap <= 0.001,
                "sweep_overlap_mm3": round(overlap, 5),
                "travel_mm": length + 1,
            }
        )
    return {"paths": paths, "removable": any(path["collision_free"] for path in paths), "continuous_axis_sweep": True}


def build_hinge(
    part_a,
    part_b,
    *,
    center_mm,
    axis,
    leaf_normal,
    pin_radius_mm,
    knuckle_radius_mm,
    clearance_mm,
    segment_length_mm,
    gap_mm,
):
    """Return ``{'a', 'b', 'pin', 'report'}`` with three closed solids.

    Preconditions: one connected, watertight shell per input, matching cut
    faces already checked by the caller, and a hinge axis outside both parts.
    An exception indicates a physical or geometric precondition failure.
    """
    if not isinstance(part_a, mf.Manifold) or not isinstance(part_b, mf.Manifold):
        raise TypeError("铰链输入必须是两个已封闭的实体")
    center = _vector(center_mm, "铰轴中心")
    w = _unit(axis, "铰轴方向")
    normal = _unit(leaf_normal, "切面法线")
    if abs(float(np.dot(w, normal))) > 0.03:
        raise ValueError("铰轴必须与所选切面法线垂直")
    pin_radius = _number(pin_radius_mm, "销轴半径", 0.6, 12)
    outer_radius = _number(knuckle_radius_mm, "轴套外半径", 1.5, 24)
    clearance = _number(clearance_mm, "销轴间隙", 0.15, 0.8)
    total_length = _number(segment_length_mm, "铰链总长度", 12, 300)
    gap = _number(gap_mm, "轴套间隔", 0.2, 4)
    bore_radius = pin_radius + clearance
    if outer_radius - bore_radius < 0.8:
        raise ValueError("轴套壁厚至少需要 0.8 mm")
    if total_length / 3 - gap < 2.5:
        raise ValueError("铰链过短，放不下三节轴套和间隔")

    source_meshes = [to_trimesh(part) for part in (part_a, part_b)]
    for mesh, part, label in zip(source_meshes, (part_a, part_b), "AB"):
        if mesh.is_empty or not mesh.is_watertight or mesh.volume <= 0 or len(part.decompose()) != 1:
            raise ValueError(f"{label} 部件必须是单个封闭连通实体")
    if float((part_a ^ part_b).volume()) > 0.001:
        raise ValueError("A/B 原始部件实体相交，不能直接安装旋转铰链")

    axis_frame = _frame(w, normal)
    bore = _cylinder(bore_radius, -total_length / 2 - 1, total_length / 2 + 1, center, axis_frame)
    for source, label in ((part_a, "A"), (part_b, "B")):
        if float((source ^ bore).volume()) > 0.001:
            raise ValueError(f"铰轴穿过 {label} 原始部件；请把铰轴移至外侧")

    half = total_length / 2
    third = total_length / 6
    spans_a = [(-half, -third - gap / 2), (third + gap / 2, half)]
    spans_b = [(-third + gap / 2, third - gap / 2)]
    result = {}
    reaches = {}
    root_engagements = {}
    for label, source, mesh, spans in (
        ("a", part_a, source_meshes[0], spans_a),
        ("b", part_b, source_meshes[1], spans_b),
    ):
        frame = _frame(w, np.asarray(mesh.center_mass) - center)
        tangent_projection = float(np.dot(frame[1], normal))
        if abs(tangent_projection) < 0.65:
            raise ValueError("铰轴位置使耳片不能留在各自切面一侧；请把轴移到共同边缘外")
        side = -1 if label == "a" else 1
        web_half_width = outer_radius * 0.65
        # Keep each mounting web strictly on its own side of the cut plane.
        tangent_offset = side * (web_half_width + 0.1) / tangent_projection
        solid = source
        reached = []
        engagements = []
        for z0, z1 in spans:
            tube = _cylinder(outer_radius, z0, z1, center, axis_frame)
            reach, web, overlap, required = _reach_for(
                source, center, frame, outer_radius, web_half_width, z0, z1, tangent_offset
            )
            solid = solid + tube + web
            reached.append(round(reach, 3))
            engagements.append(
                {"embedded_volume_mm3": round(overlap, 3), "minimum_embedded_volume_mm3": round(required, 3)}
            )
        solid = solid - bore
        mesh_result = to_trimesh(solid)
        if (
            mesh_result.is_empty
            or not mesh_result.is_watertight
            or mesh_result.volume <= 0
            or len(solid.decompose()) != 1
        ):
            raise ValueError(f"{label.upper()} 的铰链耳片没有与主体形成单个封闭实体")
        result[label] = solid
        reaches[label] = reached
        root_engagements[label] = engagements

    pin = _cylinder(pin_radius, -half - 0.5, half + 0.5, center, axis_frame)
    if len(pin.decompose()) != 1 or not to_trimesh(pin).is_watertight:
        raise ValueError("无法生成独立的封闭销轴")
    overlaps = {
        "a_b_mm3": float((result["a"] ^ result["b"]).volume()),
        "pin_a_mm3": float((pin ^ result["a"]).volume()),
        "pin_b_mm3": float((pin ^ result["b"]).volume()),
    }
    if max(overlaps.values()) > 0.001:
        raise ValueError("装配态实体干涉；请移动铰轴或增大间隙")

    removal = _pin_removal_report(result["a"], result["b"], pin_radius, center, axis_frame, total_length)
    if not removal["removable"]:
        raise ValueError("销轴向两端抽出都会碰到原始部件；请调整铰轴位置或长度")
    rotation = _rotation_report(result["a"], result["b"], center, w)
    if not rotation["opens_to_90_deg"]:
        raise ValueError("整个 A/B 部件向两个方向旋转 90° 均发生干涉；请改变铰轴位置")
    result["pin"] = pin
    result["report"] = {
        "type": "three_knuckle_hinge",
        "part_assignment": "A 两侧 / B 中间",
        "axis_center_mm": center.tolist(),
        "axis": w.tolist(),
        "pin_radius_mm": pin_radius,
        "knuckle_radius_mm": outer_radius,
        "segment_length_mm": total_length,
        "pin_removable": True,
        "bore_radius_mm": bore_radius,
        "minimum_radial_pin_clearance_mm": clearance,
        "axial_gap_mm": gap,
        "web_reach_mm": reaches,
        "web_root_engagement": root_engagements,
        "assembled_overlap_mm3": overlaps,
        "pin_removal": removal,
        "rotation": rotation,
        "limits": "刚体离散角度几何检查；未验证材料弯曲、打印公差或全程连续无干涉",
    }
    return result
