"""Motion-preview instructions derived only from finished connector geometry checks.

Positions and directions use the source STL's engineering millimetres/Z-up
frame.  ``engine.export_glb`` converts that frame to glTF metres/Y-up; the
viewer must apply the same conversion to pivots and direction vectors.
"""

from __future__ import annotations

import math


SCHEMA = "connector-motion-preview/v1"


def _vector(value, *, unit=False):
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        return None
    try:
        numbers = [float(component) for component in value]
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(component) for component in numbers):
        return None
    length = math.sqrt(sum(component * component for component in numbers))
    if unit and not 0.99 <= length <= 1.01:
        return None
    return numbers


def _base(revision):
    return dict(
        schema=SCHEMA,
        coordinate_space="engineering_mm_z_up",
        source_revision=revision,
        kind="unavailable",
        status="unavailable",
        fixed_part="part_a",
        moving_part="part_b",
        stationary_parts=["part_a"],
        home_value=0,
        note="当前结果没有经过足以支持动画预览的整件运动验证。",
    )


def _part_bounds(part):
    bounds = []
    for shell in part.get("shells", []):
        candidate = shell.get("bounds_mm") if isinstance(shell, dict) else None
        if (
            isinstance(candidate, list)
            and len(candidate) == 2
            and all(_vector(point) is not None for point in candidate)
        ):
            bounds.append(candidate)
    candidate = part.get("bounds_mm")
    if (
        not bounds
        and isinstance(candidate, list)
        and len(candidate) == 2
        and all(_vector(point) is not None for point in candidate)
    ):
        bounds.append(candidate)
    if not bounds:
        return None
    return (
        [min(box[0][axis] for box in bounds) for axis in range(3)],
        [max(box[1][axis] for box in bounds) for axis in range(3)],
    )


def _inspection_preview(connectors, report, revision):
    """A visually separated B, explicitly without an assembly-path claim."""
    result = _base(revision)
    normals = [_vector(item.get("normal"), unit=True) for item in connectors]
    normals = [normal for normal in normals if normal is not None]
    parts = report.get("parts")
    if not isinstance(parts, list) or len(parts) != 2:
        parts = [{}, {}]
    bounds = [_part_bounds(part) if isinstance(part, dict) else None for part in parts]
    midpoint = ([(low + high) / 2 for low, high in zip(*box)] for box in bounds if box is not None)
    centers = list(midpoint)
    if normals:
        summed = [sum(normal[axis] for normal in normals) for axis in range(3)]
        axis = _vector(summed)
        magnitude = math.sqrt(sum(x * x for x in summed))
        if magnitude < 0.1:
            axis = normals[0]
        else:
            axis = [x / magnitude for x in axis]
    elif len(centers) == 2:
        delta = [right - left for left, right in zip(centers[0], centers[1])]
        magnitude = math.sqrt(sum(x * x for x in delta))
        axis = [x / magnitude for x in delta] if magnitude > 0.001 else None
    else:
        axis = None
    if axis is None:
        return result
    size_hints = []
    for item in connectors:
        for name in ("size_mm", "depth_mm", "segment_length_mm", "rail_length_mm", "travel_mm"):
            try:
                value = float(item.get(name, 0))
            except (TypeError, ValueError):
                continue
            if math.isfinite(value) and value > 0:
                size_hints.append(value)
    hint = max([10.0] + size_hints)
    distance = max(5.0, hint * 1.5)
    if all(box is not None for box in bounds):
        union_low = [min(bounds[0][0][i], bounds[1][0][i]) for i in range(3)]
        union_high = [max(bounds[0][1][i], bounds[1][1][i]) for i in range(3)]
        diagonal = math.sqrt(sum((high - low) ** 2 for low, high in zip(union_low, union_high)))

        def projected_interval(box):
            low, high = box
            return (
                sum((low[i] if axis[i] >= 0 else high[i]) * axis[i] for i in range(3)),
                sum((high[i] if axis[i] >= 0 else low[i]) * axis[i] for i in range(3)),
            )

        _, a_max = projected_interval(bounds[0])
        b_min, _ = projected_interval(bounds[1])
        # The far end clears the entire A/B bounding projections, then adds a
        # scale-aware visual gap. This is a display position, not a swept path.
        distance = max(distance, max(0.0, a_max - b_min) + max(5.0, diagonal * 0.12), diagonal * 0.18)
    distance = round(distance, 4)
    pins = report.get("pins")
    stationary = ["part_a"] + [f"pin_{index + 1}" for index, _ in enumerate(pins if isinstance(pins, list) else [])]
    result.update(
        kind="inspection_explode",
        status="ready",
        axis=axis,
        range=[0, distance],
        unit="mm",
        visualization_only=True,
        stationary_parts=stationary,
        connector_count=len(connectors),
        validation=dict(
            method="visualization_only", sampled_values=[], continuous_proof=False, physical_assembly_path_tested=False
        ),
        note="仅将 B 沿切面外侧分开展示以检查连接结构；不是无干涉装配路径、可动机构或卡扣弹性通过的证明。",
    )
    return result


def build_motion_preview(connectors, report, *, revision=None):
    """Make a conservative animation contract from a saved generation report.

    This pure read also lets older hinge/rail revisions preview immediately,
    without changing their frozen project.json or manufacturing artifacts.
    A motion candidate by itself is never treated as validation evidence.
    """
    result = _base(revision)
    if not isinstance(connectors, list) or not connectors or not isinstance(report, dict):
        result["note"] = "尚未生成连接件。"
        return result
    if not all(isinstance(item, dict) for item in connectors):
        return result
    result = _inspection_preview(connectors, report, revision)
    # A finished design remains inspectable even when an older report lacks
    # newer physical-check fields. Such a preview never becomes a claim that
    # its rigid motion path is valid. Real motion below requires these checks.
    parts = report.get("parts")
    try:
        overlap = float(report["static_overlap_mm3"])
        tolerance = float(report.get("static_overlap_tolerance_mm3", 1e-6))
    except (TypeError, ValueError, KeyError):
        overlap, tolerance = float("inf"), 0.0
    physical_base_valid = (
        isinstance(parts, list)
        and len(parts) == 2
        and all(isinstance(part, dict) and part.get("closed") for part in parts)
        and math.isfinite(overlap)
        and math.isfinite(tolerance)
        and tolerance >= 0
        and overlap <= tolerance
    )
    if len(connectors) != 1:
        return result
    if not physical_base_valid:
        return result
    item = connectors[0]
    kind = item.get("type")
    mechanisms = report.get("mechanisms", [])
    pins = report.get("pins", [])
    if kind == "hinge":
        if len(mechanisms) != 1 or mechanisms[0].get("type") != "three_knuckle_hinge" or len(pins) != 1:
            return result
        mechanism = mechanisms[0]
        axis = _vector(mechanism.get("axis"), unit=True)
        pivot = _vector(mechanism.get("axis_center_mm"))
        rotation = mechanism.get("rotation", {})
        if axis is None or pivot is None or not mechanism.get("pin_removable") or not rotation.get("opens_to_90_deg"):
            return result
        approved = []
        for path in rotation.get("sampled_paths", []):
            rows = path.get("samples", [])
            if not path.get("collision_free") or not rows:
                continue
            try:
                values = [float(row["angle_deg"]) for row in rows]
                overlaps = [float(row["overlap_mm3"]) for row in rows]
            except (TypeError, ValueError, KeyError):
                continue
            if (
                not all(math.isfinite(x) for x in values + overlaps)
                or any(overlap > 0.001 for overlap in overlaps)
                or not any(abs(value) < 1e-6 for value in values)
                or not any(abs(value) >= 89.999 for value in values)
            ):
                continue
            approved.append((path.get("direction"), values))
        if not approved:
            return result
        values = sorted({value for _, path_values in approved for value in path_values})
        result = _base(revision)
        result.update(
            kind="rotation",
            status="ready",
            stationary_parts=["part_a", "pin_1"],
            axis=axis,
            pivot_mm=pivot,
            range=[min(values), max(values)],
            unit="deg",
            auxiliary_part="pin_1",
            validation=dict(
                method="sampled_whole_part_collision",
                sampled_values=values,
                checked_directions=[direction for direction, _ in approved],
                overlap_tolerance_mm3=0.001,
                continuous_proof=False,
            ),
            note="B 绕实际销轴转动；仅显示已通过每 15° 整件碰撞采样的方向。动画插值不等于连续路径或实物寿命验证。",
        )
        return result
    if kind == "linear_rail":
        if len(mechanisms) != 1 or mechanisms[0].get("type") != "captured_t_rail" or len(pins) != 1:
            return result
        mechanism = mechanisms[0]
        axis = _vector(mechanism.get("travel_axis"), unit=True)
        bounds = mechanism.get("allowed_offset_mm")
        poses = mechanism.get("sampled_whole_part_poses", [])
        if axis is None or not isinstance(bounds, list) or len(bounds) != 2 or not poses:
            return result
        try:
            low, high = [float(value) for value in bounds]
            values = [float(pose["offset_mm"]) for pose in poses]
            overlaps = [float(pose["overlap_mm3"]) for pose in poses]
            profile_overlap = float(mechanism["stroke_sweep_overlap_mm3"])
        except (TypeError, ValueError, KeyError):
            return result
        if (
            not all(math.isfinite(x) for x in [low, high, profile_overlap] + values + overlaps)
            or not low < 0 < high
            or min(values) > low + 0.001
            or max(values) < high - 0.001
            or max(overlaps) > 0.001
            or profile_overlap > 0.001
            or not mechanism.get("continuous_profile_sweep")
        ):
            return result
        result = _base(revision)
        result.update(
            kind="translation",
            status="ready",
            stationary_parts=["part_a", "pin_1"],
            auxiliary_part="pin_1",
            axis=axis,
            range=[low, high],
            unit="mm",
            validation=dict(
                method="continuous_connector_profile_and_sampled_whole_parts",
                sampled_values=values,
                overlap_tolerance_mm3=0.001,
                continuous_profile_sweep=True,
                continuous_proof=bool(mechanism.get("whole_part_continuous_proof")),
            ),
            note="B 沿实际导轨轴移动，独立止挡销保持不动；整件碰撞仅在记录的位移点采样。",
        )
        return result
    if kind == "dovetail":
        paths = report.get("dovetail_assembly_paths", [])
        path = next((path for path in paths if path.get("connector_id") == item.get("id")), None)
        if path is None or not path.get("collision_free") or path.get("moving_part") != "part_b":
            return result
        axis = _vector(path.get("axis"), unit=True)
        poses = path.get("poses", [])
        if axis is None or not poses:
            return result
        try:
            values = [float(pose["offset_mm"]) for pose in poses]
            overlaps = [float(pose["overlap_mm3"]) for pose in poses]
            tolerance = float(path["overlap_tolerance_mm3"])
        except (TypeError, ValueError, KeyError):
            return result
        if (
            not all(math.isfinite(x) for x in values + overlaps + [tolerance])
            or max(overlaps) > tolerance
            or not any(abs(x) < 1e-6 for x in values)
            or not any(abs(x) > 1 for x in values)
        ):
            return result
        start = values[0]
        result = _base(revision)
        result.update(
            kind="assembly_translation",
            status="ready",
            axis=axis,
            range=[min(values), max(values)],
            assembly_start_value=start,
            unit="mm",
            validation=dict(
                method="sampled_whole_part_collision",
                sampled_values=values,
                overlap_tolerance_mm3=tolerance,
                continuous_proof=False,
            ),
            note="B 从燕尾槽开放边滑入装配位；这是一次装配过程，不是可往复滑动的导轨。",
        )
        return result
    return result
