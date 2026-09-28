"""Two-piece telescopes retained by the assembled end pivots, with exact length coupling."""

from .mechanical_geometry import *


def world_frame(a, b):
    a = np.asarray(a, float)
    b = np.asarray(b, float)
    T = np.eye(4)
    T[:3, :3] = frame(b - a, x_hint=(1, 0, 0))
    T[:3, 3] = a
    return T


def capsule(a, b, r):
    a = np.asarray(a, float)
    b = np.asarray(b, float)
    L = np.linalg.norm(b - a)
    if L < 1e-7:
        return ball(r).translate(a)
    return (
        transform(cyl(r, 0, L), frame(b - a), a)
        + mf.Manifold.sphere(r, 24).translate(a)
        + mf.Manifold.sphere(r, 24).translate(b)
    )


def telescope(min_length, max_length, rest_length, tube_radius=2.2):
    if not 2.0 <= tube_radius <= 3.0:
        raise ValueError("Unsupported tube radius")
    body_end = min_length - 3.4
    rod_length = max_length - (body_end - 5.0)
    minimum_tail = min_length - rod_length
    if minimum_tail < 3.9:
        raise ValueError("Length range cannot fit a one-stage telescope with declared engagement")
    eye_radius = 2.5
    eye_half = 1.1
    eye = cx(eye_radius, -eye_half, eye_half) - cx(1.2, -eye_half - 0.1, eye_half + 0.1)
    tube = (cyl(tube_radius, 1.8, body_end) - cyl(1.25, 3.5, body_end + 0.1)) + eye
    # A permanent shallow rib provides a flat bed contact without touching the
    # sliding bore or the eye bearing faces. Place this +Y face on the bed.
    tube += box([-0.7, tube_radius - 0.5, 1.8], [0.7, 2.5, body_end])
    rod = cyl(1.0, rest_length - rod_length, rest_length - 2.1) + eye.translate([0, 0, rest_length])
    return dict(
        tube=tube,
        rod=rod,
        body_end=body_end,
        rod_length=rod_length,
        bore_radius=1.25,
        rod_radius=1.0,
        minimum_engagement_mm=5.0,
        minimum_bottom_clearance_mm=minimum_tail - 3.5,
        tube_radius_mm=tube_radius,
        nominal_tube_wall_mm=tube_radius - 1.25,
        standalone_retention=False,
        retention="Both eyes pinned to the validated closed mechanism; never a standalone captured slider",
    )


def detach_visuals(parts, specs):
    edits = []
    for spec in specs:
        a = spec.get("source_a", spec["a"])
        b = spec.get("source_b", spec["b"])
        T = world_frame(a, b)
        L = np.linalg.norm(np.array(b) - a)
        cutter = transform(cyl(spec["replace_radius"], 3.2, L - 3.2), T[:3, :3], T[:3, 3])
        removed = {}
        for name in [spec["parent"], spec["child"]]:
            before = parts[name]
            parts[name] -= cutter
            removed[name] = float((before - parts[name]).volume())
        edits.append(
            dict(id=spec["id"], removed_mm3=removed, T=T.tolist(), lo=3.2, hi=L - 3.2, radius=spec["replace_radius"])
        )
    return edits


def install_eye(host, point, toward):
    p = np.array(point, float)
    T = np.eye(4)
    T[:3, :3] = frame([1, 0, 0], x_hint=-unit(np.array(toward) - p))
    T[:3, 3] = p
    local = host.transform(np.linalg.inv(T)[:3, :4])
    original = local
    fork = cyl(3.1, -3.4, -1.4) + cyl(3.1, 1.4, 3.4) + box([2.7, -1.3, -3.4], [3.6, 1.3, 3.4])
    local -= cyl(2.8, -1.4, 1.4)
    local += fork
    anchors = np.array([[3.1, 0, 0], [2.3, 0, -2.5], [2.3, 0, 2.5]])
    targets, distances, _ = trimesh.proximity.closest_point(mesh(original), anchors)
    best = int(distances.argmin())
    anchor = anchors[best]
    target = targets[best]
    if distances[best] > 3:
        raise ValueError(f"Eye mount at {point} needs a {distances[best]:.3f} mm bridge")
    local += capsule(anchor, target, 1.2)
    local -= cyl(2.8, -1.4, 1.4)
    channel = local ^ cyl(1.08, -80, 80)
    span = np.array(channel.bounding_box()).reshape(2, 3)[:, 2]
    pin_lo = float(span[0] + 0.15)
    pin_length = float(np.floor((span[1] - span[0] - 0.3) * 2) / 2)
    pin_hi = pin_lo + pin_length
    local -= cyl(1.08, float(span[0]) - 0.2, float(span[1]) + 0.2)
    # Preserve native host cheeks; only short connections within the eye's mount.
    for z in [-2.5, 2.5]:
        anchor = np.array([0, 0, z])
        target = trimesh.proximity.closest_point(mesh(local), [anchor])[0][0]
        if np.linalg.norm(target - anchor) > 4:
            raise ValueError("Eye mount is not near material")
    pin = cyl(1.0, pin_lo, pin_hi)
    return (
        local.transform(T[:3, :4]),
        pin.transform(T[:3, :4]),
        T,
        dict(
            diameter_mm=2.0,
            length_mm=pin_length,
            lo=pin_lo,
            hi=pin_hi,
            bore_lo=float(span[0]) - 0.2,
            bore_hi=float(span[1]) + 0.2,
            fixation="bond only at the host ends, keep the eye bearing dry",
        ),
    )


def install(parts, specs):
    extras = {}
    hardware = {}
    owners = {}
    modules = []
    for spec in specs:
        m = telescope(
            spec["min_length_mm"], spec["max_length_mm"], spec["rest_length_mm"], spec.get("tube_radius_mm", 2.2)
        )
        T = world_frame(spec["a"], spec["b"])
        names = {}
        for role in ["tube", "rod"]:
            name = spec["id"] + "_" + role
            extras[name] = m[role].transform(T[:3, :4])
            owners[name] = spec["parent"]
            names[role] = name
        pin_names = []
        eye_T = []
        pin_specs = []
        loading_slots = []
        for side, point in [("parent", spec["a"]), ("child", spec["b"])]:
            opposite = spec["b"] if side == "parent" else spec["a"]
            name = spec["id"] + "_" + side + "_steel_pin"
            host, pin, ET, pin_spec = install_eye(parts[spec[side]], point, opposite)
            direction = spec.get(side + "_loading_direction")
            if direction is not None:
                direction = unit(direction)
                axis = np.array([1.0, 0, 0])
                if abs(np.dot(direction, axis)) > 1e-6:
                    raise ValueError("Eye loading direction must be perpendicular to its pin")
                LT = np.eye(4)
                LT[:3, :3] = frame(axis, direction)
                LT[:3, 3] = point
                distance = float(spec.get(side + "_loading_distance_mm", 7.0))
                cut = box([0, -2.7, -1.45], [distance, 2.7, 1.45]).transform(LT[:3, :4])
                removed = float((host ^ cut).volume())
                if removed > 40:
                    raise ValueError("Eye loading slot exceeds its 40 mm3 design budget")
                host -= cut
                loading_slots.append(
                    dict(
                        owner=spec[side],
                        T=LT.tolist(),
                        lo=[0, -2.7, -1.45],
                        hi=[distance, 2.7, 1.45],
                        removed_mm3=removed,
                    )
                )
            for relief in spec.get(side + "_loading_reliefs", []):
                if direction is None:
                    raise ValueError("A local loading relief needs a loading frame")
                cut = box(relief["lo"], relief["hi"]).transform(LT[:3, :4])
                removed = float((host ^ cut).volume())
                if removed > relief["budget_mm3"]:
                    raise ValueError("Local neck loading relief exceeds its fixed budget")
                host -= cut
                loading_slots.append(
                    dict(
                        owner=spec[side],
                        T=LT.tolist(),
                        lo=relief["lo"],
                        hi=relief["hi"],
                        removed_mm3=removed,
                        reason="Measured rod-neck insertion contact",
                    )
                )
            parts[spec[side]] = host
            hardware[name] = pin
            owners[name] = spec[side]
            pin_names.append(name)
            eye_T.append(ET.tolist())
            pin_specs.append(dict(name=name, owner=spec[side], **pin_spec))
        modules.append(
            dict(
                spec,
                parts=names,
                T=T.tolist(),
                pins=pin_names,
                eye_frames=eye_T,
                pin_specs=pin_specs,
                loading_slots=loading_slots,
                eye_axial_gap_mm=0.3,
                **{k: v for k, v in m.items() if k not in ["tube", "rod"]},
            )
        )
    return extras, hardware, owners, modules


def dynamic_transforms(report, host_transforms):
    result = {}
    for item in report.get("dependent_modules", []):
        A = trimesh.transform_points([item["a"]], host_transforms[item["parent"]])[0]
        B = trimesh.transform_points([item["b"]], host_transforms[item["child"]])[0]
        axis = host_transforms[item["parent"]][:3, :3] @ np.array([1.0, 0, 0])
        T = np.eye(4)
        T[:3, :3] = frame(B - A, axis)
        T[:3, 3] = A
        rest_inv = np.linalg.inv(np.array(item["T"]))
        L = float(np.linalg.norm(B - A))
        result[item["parts"]["tube"]] = T @ rest_inv
        slide = np.eye(4)
        slide[2, 3] = L - item["rest_length_mm"]
        result[item["parts"]["rod"]] = T @ slide @ rest_inv
    return result
