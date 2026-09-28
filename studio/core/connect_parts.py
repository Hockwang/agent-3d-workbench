"""Blind mating sockets with separate pins; all dimensions in mm."""

import numpy as np
from studio.core import fabrication as f
from studio.core.kernels import mechanical_geometry as g


def run(w):
    p = w["params"]
    objects, hashes = f.inputs(w, 2)
    names = p.get("parts")
    if not isinstance(names, list) or len(names) != 2 or len(set(names)) != 2 or set(names) != set(objects):
        f.invalid("parts: [negative_axis_part, positive_axis_part]")
    plans = p.get("connectors")
    if not isinstance(plans, list) or not 1 <= len(plans) <= 16:
        f.invalid("connectors")
    original = [objects[n][1] for n in names]
    f.require(g.overlap(*original) < 1e-6, "source_parts_overlap")
    bodies = original.copy()
    pins, reports, guards = {}, [], []
    for i, plan in enumerate(plans):
        if not isinstance(plan, dict):
            f.invalid("connector")
        center = f.vector(plan.get("center_mm"), "center_mm")
        axis = f.vector(plan.get("axis"), "axis", True)
        rotation = g.frame(axis, f.vector(plan.get("x_hint", [1, 0, 0]), "x_hint", True))
        radius = f.scalar(plan, "radius_mm", 2)
        depth = f.scalar(plan, "depth_mm", 6)
        clearance = f.scalar(plan, "clearance_mm", 0.2, hi=2)
        wall = f.scalar(plan, "min_wall_mm", 1.6)
        kind = plan.get("profile", "keyed")
        if kind not in ("round", "keyed") or depth <= 2 * clearance:
            f.invalid("profile/depth_mm")
        # An explicit planar mating interface is required. A recessed/gapped or
        # oblique fit needs a different plan, not a silent floating connector.
        for side, name in enumerate(names):
            projected = (objects[name][0].vertices - center) @ axis
            seam = projected.max() if side == 0 else projected.min()
            f.require(abs(seam) < 0.001, "mating_plane")

        def placed(s):
            return g.transform(s, rotation, center)

        def profile(lo, hi, gap=0):
            return g.keyed(radius, lo, hi, gap) if kind == "keyed" else g.cyl(radius + gap, lo, hi)

        pin = placed(profile(-depth + clearance, depth - clearance))
        cutters = [placed(profile(-depth, 0.01, clearance)), placed(profile(-0.01, depth, clearance))]
        for side in range(2):
            # Full conservative guard, including the blind bottom. The circular
            # guard also bounds a keyed bore's flat side from below.
            lo, hi = (-depth - wall, -1e-4) if side == 0 else (1e-4, depth + wall)
            guard = placed(g.cyl(radius + clearance + wall, lo, hi))
            f.require((guard - bodies[side]).volume() <= 1e-6, "socket_wall_envelope")
            guards.append((side, guard - cutters[side]))
            f.require(g.overlap(cutters[side], bodies[side]) > 1e-6, "socket_engagement")
            bodies[side] -= cutters[side]
            f.checked_mesh(bodies[side])
        f.require(all(g.overlap(pin, b) < 1e-6 for b in bodies), "pin_socket_clearance")
        f.require(all(g.overlap(pin, q) < 1e-6 for q in pins.values()), "pins_overlap")
        pins[f"pin_{i:02d}"] = pin
        reports.append(
            {
                "profile": kind,
                "center_mm": center.tolist(),
                "axis": axis.tolist(),
                "radius_mm": radius,
                "depth_mm": depth,
                "clearance_mm": clearance,
                "min_hole_wall_mm_lower_bound": wall,
                "anti_rotation": kind == "keyed",
                "guard_contained": True,
            }
        )
    # Later holes must also preserve earlier holes' requested wall thickness,
    # including when connector plans specify different minimum walls.
    f.require(all((guard - bodies[side]).volume() <= 1e-6 for side, guard in guards), "final_socket_wall_envelope")
    # Check withdrawal of each entire host from all stationary pins. This is
    # sampled evidence, not a continuous collision or arbitrary assembly proof.
    axis = f.vector(plans[0]["axis"], "axis", True)
    if any(np.dot(axis, f.vector(q["axis"], "axis", True)) < 0.999999 for q in plans):
        f.invalid("parallel connector axes")
    distance = max(q["depth_mm"] for q in reports) * 2
    samples = []
    for t in np.linspace(0, distance, 21):
        for side, sign in enumerate((-1, 1)):
            moved = bodies[side].translate((sign * t * axis).tolist())
            collisions = sum(g.overlap(moved, pin) for pin in pins.values()) + g.overlap(moved, bodies[1 - side])
            samples.append({"part": f"body_{side}", "distance_mm": float(t), "overlap_mm3": collisions})
    f.require(all(s["overlap_mm3"] < 1e-6 for s in samples), "sampled_withdrawal")
    f.emit(
        w,
        {"body_0": bodies[0], "body_1": bodies[1], **pins},
        {
            "operation": "connect-parts",
            "source_sha256": hashes,
            "source_parts": names,
            "connectors": reports,
            "withdrawal_samples": samples,
            "status": "pass",
            "fit_type": "separate_glue_or_clearance_pins",
            "holding_strength_verified": False,
        },
    )
