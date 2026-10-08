"""Finite-travel T-slot rail on a planar A/B cut pair.

The A part receives a captured undercut channel. The B part receives one
integral T-section slider. Its +travel end is open for assembly, then closed
with a third, removable cross-pin. The other end is an integral channel wall.
Only a strict planar, thick-enough subset of source geometry is accepted.
"""

from __future__ import annotations

import math

from backend.engine import mf, np, to_trimesh


def _vector(value, name):
    vector = np.asarray(value, dtype=float)
    if vector.shape != (3,) or not np.all(np.isfinite(vector)):
        raise ValueError(f"{name} 必须是三个有限数值")
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


def _place(solid, center, frame):
    x, y, z = frame
    return solid.transform(
        [[x[0], y[0], z[0], center[0]], [x[1], y[1], z[1], center[1]], [x[2], y[2], z[2], center[2]]]
    )


def _rect(x0, x1, y0, y1, z0, z1, center, frame):
    if min(x1 - x0, y1 - y0, z1 - z0) <= 0:
        raise ValueError("导轨实体尺寸必须为正")
    solid = mf.Manifold.cube((x1 - x0, y1 - y0, z1 - z0))
    return _place(solid.translate((x0, y0, z0)), center, frame)


def _rod(radius, y0, y1, x, z, center, frame):
    u, v, n = frame
    rod_frame = (n, u, v)  # n cross u == v; rod axis is transverse to travel.
    origin = center + u * x + n * z + v * y0
    return _place(mf.Manifold.cylinder(y1 - y0, radius, radius, 64), origin, rod_frame)


def _male(x0, x1, width, depth, center, frame):
    neck_half = width * 0.27
    neck = _rect(x0, x1, -neck_half, neck_half, -depth * 0.55, 0.25, center, frame)
    head = _rect(x0, x1, -width / 2, width / 2, -depth, -depth * 0.45, center, frame)
    return neck + head


def _channel(x0, x1, width, depth, clearance, center, frame):
    neck_half = width * 0.27 + clearance
    neck = _rect(x0, x1, -neck_half, neck_half, -depth * 0.55 - clearance, 0.25, center, frame)
    head = _rect(
        x0,
        x1,
        -width / 2 - clearance,
        width / 2 + clearance,
        -depth - clearance,
        -depth * 0.45 + clearance,
        center,
        frame,
    )
    return neck + head


def _probe_inside(source, center, frame, xyz, size=0.32):
    x, y, z = xyz
    half = size / 2
    probe = _rect(x - half, x + half, y - half, y + half, z - half, z + half, center, frame)
    return float((source ^ probe).volume()) / (size**3) > 0.85


def build_linear_rail(
    part_a,
    part_b,
    *,
    center_mm,
    travel_axis,
    leaf_normal,
    rail_length_mm,
    rail_width_mm,
    rail_depth_mm,
    clearance_mm,
    travel_mm,
    stop_width_mm,
):
    """Return ``{'a', 'b', 'stop', 'report'}`` for a printable rail pair.

    ``center_mm`` lies on the planar shared face. ``travel_axis`` lies in that
    face. The nominal centred pose can move ±travel_mm/2. The returned stop is
    installed after the male T-section has entered from the +travel edge.
    """
    if not isinstance(part_a, mf.Manifold) or not isinstance(part_b, mf.Manifold):
        raise TypeError("导轨输入必须是两个已封闭实体")
    center = np.asarray(center_mm, dtype=float)
    if center.shape != (3,) or not np.all(np.isfinite(center)):
        raise ValueError("导轨中心必须是三个有限数值")
    u = _vector(travel_axis, "移动方向")
    n = _vector(leaf_normal, "切面法线")
    if abs(float(np.dot(u, n))) > 0.03:
        raise ValueError("移动方向必须位于 A/B 共面切面内")
    v = np.cross(n, u)
    v /= np.linalg.norm(v)
    frame = (u, v, n)
    length = _number(rail_length_mm, "滑块长度", 8, 180)
    width = _number(rail_width_mm, "滑块头宽", 3, 60)
    depth = _number(rail_depth_mm, "导轨深度", 2.5, 32)
    clearance = _number(clearance_mm, "滑动间隙", 0.15, 0.6)
    travel = _number(travel_mm, "总行程", 2, 80)
    stop_diameter = _number(stop_width_mm, "止挡销直径", 1.2, 12)
    stop_radius = stop_diameter / 2
    if depth * 0.72 - stop_radius < 0.25:
        raise ValueError("止挡销会穿出切面；请加深导轨或缩小止挡销")
    if width * 0.23 - clearance < 1.0:
        raise ValueError("T 形头单侧相对颈部的倒扣不足 1.0 mm")

    source_a, source_b = to_trimesh(part_a), to_trimesh(part_b)
    for mesh, solid, label in ((source_a, part_a, "A"), (source_b, part_b, "B")):
        if mesh.is_empty or not mesh.is_watertight or mesh.volume <= 0 or len(solid.decompose()) != 1:
            raise ValueError(f"{label} 必须是单个封闭连通实体")
    if float((part_a ^ part_b).volume()) > 0.001:
        raise ValueError("A/B 原始实体相交，不能建立共面导轨")
    a_z = (np.asarray(source_a.vertices) - center) @ n
    b_z = (np.asarray(source_b.vertices) - center) @ n
    if float(np.max(a_z)) > 0.03 or float(np.min(b_z)) < -0.03:
        raise ValueError("此导轨仅支持 A/B 分居同一平面两侧的分件")
    if float(np.max(a_z)) < -0.03 or float(np.min(b_z)) > 0.03:
        raise ValueError("导轨中心不在 A/B 共同切面上")

    a_x = (np.asarray(source_a.vertices) - center) @ u
    a_y = (np.asarray(source_a.vertices) - center) @ v
    b_x = (np.asarray(source_b.vertices) - center) @ u
    if (
        min(float(np.max(b_x)), float(np.max(a_x))) < length / 2 + 0.5
        or max(float(np.min(b_x)), float(np.min(a_x))) > -length / 2 - 0.5
    ):
        raise ValueError("所选位置的共同切面放不下滑块长度")

    end_clearance = max(0.2, clearance)
    x_closed = -length / 2 - travel / 2 - end_clearance
    x_stop = length / 2 + travel / 2 + stop_radius + end_clearance
    x_open = float(np.max(a_x)) + 1.5
    if x_closed - float(np.min(a_x)) < 1.5 or float(np.max(a_x)) - x_stop < stop_radius + 1.5:
        raise ValueError("导轨两端缺少至少 1.5 mm 的主体材料安装止挡")
    if x_open - x_stop < stop_radius + 1.5:
        raise ValueError("导轨开口端长度不足以安装独立止挡销")

    head_half = width / 2 + clearance
    neck_half = width * 0.27 + clearance
    hole_z = -depth * 0.72
    min_wall = 1.1
    # Probe the original source before Booleans: undercut roof, channel floor,
    # and both pin-support walls must truly exist, not merely a bounding box.
    support_points = []
    for x in (-length / 4, length / 4):
        support_points.extend(
            (
                (x, 0, -depth - clearance - min_wall),
                (x, (neck_half + head_half) / 2, -0.2),
                (x, -(neck_half + head_half) / 2, -0.2),
            )
        )
    for y in (-head_half - min_wall, head_half + min_wall):
        for x, z in (
            (x_stop, hole_z - stop_radius - clearance - min_wall),
            (x_stop, hole_z + stop_radius + clearance + min_wall),
            (x_stop + stop_radius + clearance + min_wall, hole_z),
        ):
            support_points.append((x, y, z))
    if not all(_probe_inside(part_a, center, frame, point) for point in support_points):
        raise ValueError("切面附近材料太薄或形状不连续，无法保留导轨倒扣、槽底及止挡销壁厚")
    if not _probe_inside(part_b, center, frame, (0, 0, 0.45)):
        raise ValueError("B 切面处没有足够实体连接滑块")

    male = _male(-length / 2, length / 2, width, depth, center, frame)
    channel = _channel(x_closed, x_open, width, depth, clearance, center, frame)
    if float((part_b ^ male).volume()) < 0.01:
        raise ValueError("滑块没有与 B 主体形成实体连接")
    if float((part_a ^ channel).volume()) < 1:
        raise ValueError("导槽没有切入 A 主体")

    y0, y1 = float(np.min(a_y)) - 1, float(np.max(a_y)) + 1
    pin_hole = _rod(stop_radius + clearance, y0, y1, x_stop, hole_z, center, frame)
    pin_shaft = _rod(stop_radius, y0, y1, x_stop, hole_z, center, frame)
    pin_head = _rod(stop_radius * 1.5, y1, y1 + 0.9, x_stop, hole_z, center, frame)
    pin = pin_shaft + pin_head
    result_a = part_a - channel - pin_hole
    result_b = part_b + male
    for label, solid in (("A", result_a), ("B", result_b), ("止挡销", pin)):
        mesh = to_trimesh(solid)
        if mesh.is_empty or not mesh.is_watertight or mesh.volume <= 0 or len(solid.decompose()) != 1:
            raise ValueError(f"{label} 导轨几何没有形成单个封闭实体")
    assembled = (
        float((result_a ^ result_b).volume()) + float((result_a ^ pin).volume()) + float((result_b ^ pin).volume())
    )
    if assembled > 0.001:
        raise ValueError("导轨安装后实体发生干涉")
    # The cross-pin is inserted from +V after the B slider is centred. Its
    # shaft's full insertion sweep is another cylinder coaxial with the hole.
    stop_insertion_sweep = _rod(stop_radius, y0, y1 + (y1 - y0), x_stop, hole_z, center, frame)
    stop_insertion_overlap = float((stop_insertion_sweep ^ result_a).volume()) + float(
        (stop_insertion_sweep ^ result_b).volume()
    )
    if stop_insertion_overlap > 0.001:
        raise ValueError("止挡销无法从侧面插入贯通孔")
    # A real undercut must block normal pull-out. A simple open rectangular
    # groove would pass all sliding checks but would not be a captured rail.
    pull_offset = max(clearance * 2 + 0.2, 0.7)
    pull_overlap = float((result_a ^ result_b.translate(n * pull_offset)).volume())
    if pull_overlap < 0.05:
        raise ValueError("导轨倒扣不足，B 能从切面法线方向脱出")

    # Exact translation sweep of the constant T-profile over the full stroke.
    swept_male = _male(-length / 2 - travel / 2, length / 2 + travel / 2, width, depth, center, frame)
    sweep_overlap = float((swept_male ^ result_a).volume()) + float((swept_male ^ pin).volume())
    if sweep_overlap > 0.001:
        raise ValueError("指定行程内滑块与导槽或止挡销干涉")
    poses = []
    for offset in np.linspace(-travel / 2, travel / 2, 9):
        moving = result_b.translate(u * float(offset))
        overlap = float((moving ^ result_a).volume()) + float((moving ^ pin).volume())
        poses.append({"offset_mm": round(float(offset), 4), "overlap_mm3": round(overlap, 5)})
    if any(pose["overlap_mm3"] > 0.001 for pose in poses):
        raise ValueError("整件 B 在指定行程内与 A 或止挡销干涉")
    overstep = max(0.8, stop_diameter)
    negative = result_b.translate(u * (-travel / 2 - overstep))
    positive = result_b.translate(u * (travel / 2 + overstep))
    limit_overlap = {
        "negative_mm3": float((negative ^ result_a).volume()),
        "positive_mm3": float((positive ^ pin).volume()),
    }
    if min(limit_overlap.values()) < 0.05:
        raise ValueError("两端限位没有阻止滑块越过指定行程")

    # With the removable stop absent, the open end must admit the entire T
    # slider from beyond the source A envelope to its centred pose.
    insertion_offset = x_open + length / 2 + 1
    insertion_swept_male = _male(-length / 2, length / 2 + insertion_offset, width, depth, center, frame)
    insertion_overlap = float((insertion_swept_male ^ result_a).volume())
    if insertion_overlap > 0.001:
        raise ValueError("滑块无法从导槽开放端装入")

    return {
        "a": result_a,
        "b": result_b,
        "stop": pin,
        "report": {
            "type": "captured_t_rail",
            "axis_center_mm": center.tolist(),
            "travel_axis": u.tolist(),
            "nominal_travel_mm": travel,
            "allowed_offset_mm": [-travel / 2, travel / 2],
            "end_play_mm_each_side": end_clearance,
            "approximate_mechanical_offset_mm": [-travel / 2 - end_clearance, travel / 2 + end_clearance],
            "slot_open_end": "positive",
            "stop_removable": True,
            "independent_print_parts": 3,
            "minimum_nominal_sliding_clearance_mm": clearance,
            "stroke_sweep_overlap_mm3": sweep_overlap,
            "insertion_sweep_overlap_mm3": insertion_overlap,
            "stop_insertion_sweep_overlap_mm3": stop_insertion_overlap,
            "assembled_overlap_mm3": assembled,
            "normal_pull_overlap_mm3": pull_overlap,
            "sampled_whole_part_poses": poses,
            "beyond_limit_overlap_mm3": limit_overlap,
            "continuous_profile_sweep": True,
            "whole_part_continuous_proof": False,
            "limits": "仅支持共面分件和开放边缘；止挡销保持力、打印公差与材料变形待验证",
        },
    }
