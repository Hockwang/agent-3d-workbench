"""Bounded host machining for explicit mechanical interfaces; no semantic fitting."""

import numpy as np
import manifold3d as mf
from pathlib import Path
import xml.etree.ElementTree as ET
import trimesh
from studio.core import fabrication as f
from studio.core.kernels import mechanical_geometry as g


def module(family, p):
    from studio.core.kernels.mechanical_modules import compact_pivot, thin_slew

    gap = f.scalar(p, "clearance_mm", 0.2, hi=0.3)
    if family == "pin_hinge":
        m = compact_pivot(gap=gap)
        fixed = (
            m["fork"]
            + g.box([-7, -2, -5.4], [-2, 2, -m["inner"]])
            + g.box([-7, -2, m["inner"]], [-2, 2, 5.4])
            + g.box([-8, -2, -5.4], [-6, 2, 5.4])
        )
        moving = m["tongue"] + g.box([2, -1, -1.2], [18, 1, 1.2])
        return (
            {"parent": fixed, "child": moving},
            [[-8, 0, 0], [18, 0, 0]],
            [[-10, -7, -7], [20, 7, 7]],
            [{"item": "M2x8 screw", "quantity": 1}, {"item": "M2 nut", "quantity": 1}],
            {"type": "revolute", "axis": [0, 0, 1], "declared_range_rad": m["limits"]},
        )
    if family == "slew":
        if gap < 0.15:
            f.invalid("slew clearance_mm >= 0.15")
        m = thin_slew(gap=gap)
        moving = m["child"] + g.cyl(m["radius"], gap + 0.55, gap + 4)
        return (
            {"parent": m["parent"], "child": moving, "retaining_cap": m["cap"]},
            [[-7, 0, -1.5], [7, 0, gap + 2]],
            [[-9, -9, -6], [9, 9, 5]],
            [{"item": "adhesive for retaining cap", "quantity": 1}],
            {"type": "revolute", "axis": [0, 0, 1]},
        )
    if family == "slider":
        cross = mf.CrossSection([np.array([[-3, -1], [3, -1], [2, 2], [-2, 2]], float)])
        channel = cross.extrude(30).translate([0, 0, -15]) + g.box([-2, 1, -15], [2, 5, 15])
        fixed = g.box([-6, -4, -14], [6, 4, 14]) - channel
        moving = cross.offset(-gap).extrude(6).translate([0, 0, -3]) + g.box([-1, 1, -3], [1, 7, 3])
        return (
            {"parent": fixed, "child": moving},
            [[0, -4, 0], [0, 7, 0]],
            [[-7, -5, -15], [7, 8, 15]],
            [],
            {"type": "prismatic", "axis": [0, 0, 1], "end_stops": False},
        )
    if family == "ball_socket":
        radius = f.scalar(p, "ball_radius_mm", 5, lo=3, hi=20)
        wall = f.scalar(p, "socket_wall_mm", 2, lo=1, hi=10)
        outer = radius + gap + wall
        stem_radius = min(radius * 0.35, 2)
        swing = f.scalar(p, "stem_swing_rad", 0.55, hi=0.7)
        # A straight clearance bore allows twist but blocks lateral swing.
        # Open a cone around the stem while retaining the rear spherical cage.
        opening = mf.Manifold.cylinder(
            outer + 2, stem_radius + gap, stem_radius + gap + (outer + 2) * np.tan(swing), 64
        ).rotate([0, 90, 0])
        shell = g.ball(outer) - g.ball(radius + gap) - opening
        lower = shell ^ g.box([-outer - 1, -outer - 1, -outer - 1], [outer + 1, outer + 1, -gap / 2])
        cap = shell ^ g.box([-outer - 1, -outer - 1, gap / 2], [outer + 1, outer + 1, outer + 1])
        for sign in (-1, 1):
            y = sign * (outer + 2)
            lo, hi = sorted([sign * (outer - 1), sign * (outer + 4)])
            lower += g.box([-3, lo, -3], [3, hi, -gap / 2])
            cap += g.box([-3, lo, gap / 2], [3, hi, 3])
            bore = g.cyl(1.2, -4, 4).translate([0, y, 0])
            lower -= bore
            cap -= bore
        moving = g.ball(radius) + g.cx(stem_radius, 0, outer + 6)
        return (
            {"parent": lower, "child": moving, "socket_cap": cap},
            [[-outer + 1, 0, -2], [outer + 5, 0, 0]],
            [[-outer - 2, -outer - 5, -outer - 2], [outer + 7, outer + 5, outer + 2]],
            [{"item": "M2 through-bolt and nut; length selected for printed stack", "quantity": 2}],
            {"type": "spherical", "stem_axis": [1, 0, 0], "stem_swing_rad": swing, "friction_holding_verified": False},
        )
    f.invalid("family: pin_hinge/slew/slider/ball_socket")


def beam(start, end, radius):
    start, end = np.array(start, float), np.array(end, float)
    distance = np.linalg.norm(end - start)
    if distance < 0.1:
        f.invalid("anchor must differ from module port")
    return g.transform(g.cyl(radius, -radius, distance + radius), g.frame(end - start), start)


def export_urdf(w, solids, family, center, rotation, motion):
    """Bind the *machined* outputs, not the source meshes, to a local URDF."""
    kind = motion["type"]
    count = 3 if kind == "spherical" else 1
    default = (
        [[-0.35, 0.35]] * 3
        if count == 3
        else [motion.get("declared_range_rad", [-0.01, 0.01] if kind == "prismatic" else [-np.pi, np.pi])]
    )
    limits = w["params"].get("joint_limits", default)
    if not isinstance(limits, list) or len(limits) != count:
        f.invalid("joint_limits")
    for pair in limits:
        if (
            not isinstance(pair, list)
            or len(pair) != 2
            or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not np.isfinite(v) for v in pair)
            or not pair[0] <= 0 <= pair[1]
            or pair[0] >= pair[1]
        ):
            f.invalid("joint_limits must include rest pose zero")

    def text(values):
        return " ".join(format(float(v), ".17g") for v in values)

    robot = ET.Element("robot", name="local_joint")
    parent = ET.SubElement(robot, "link", name="parent")

    def visual(link, name, xyz=(0, 0, 0), rpy=(0, 0, 0)):
        v = ET.SubElement(link, "visual", name=name)
        ET.SubElement(v, "origin", xyz=text(xyz), rpy=text(rpy))
        ET.SubElement(ET.SubElement(v, "geometry"), "mesh", filename=f"{name}.stl", scale="0.001 0.001 0.001")

    moving_names = {"child", "retaining_cap"} if family == "slew" else {"child"}
    for name in solids:
        if name not in moving_names:
            visual(parent, name)
    previous = "parent"
    for i in range(count):
        name = "child" if i == count - 1 else f"pivot_{i}"
        link = ET.SubElement(robot, "link", name=name)
        j = ET.SubElement(robot, "joint", name=f"joint_{i}", type="revolute" if count == 3 else kind)
        ET.SubElement(j, "parent", link=previous)
        ET.SubElement(j, "child", link=name)
        ET.SubElement(
            j,
            "origin",
            xyz=text(center * 0.001 if i == 0 else [0, 0, 0]),
            rpy=text(trimesh.transformations.euler_from_matrix(rotation) if i == 0 else [0, 0, 0]),
        )
        ET.SubElement(j, "axis", xyz=text(np.eye(3)[i] if count == 3 else [0, 0, 1]))
        ET.SubElement(j, "limit", lower=str(limits[i][0]), upper=str(limits[i][1]), effort="1", velocity="1")
        previous = name
    for name in sorted(moving_names):
        visual(link, name, -rotation.T @ center * 0.001, trimesh.transformations.euler_from_matrix(rotation.T))
    ET.ElementTree(robot).write(Path(w["output"]) / "assembly.urdf", encoding="utf-8", xml_declaration=True)


def run(w):
    p = w["params"]
    objects, hashes = f.inputs(w, 2)
    names = p.get("parts")
    if not isinstance(names, list) or len(names) != 2 or len(set(names)) != 2 or set(names) != set(objects):
        f.invalid("parts: [fixed_host, moving_host]")
    center = f.vector(p.get("center_mm"), "center_mm")
    rotation = g.frame(f.vector(p.get("axis"), "axis", True), f.vector(p.get("x_hint", [1, 0, 0]), "x_hint", True))
    anchors = p.get("anchors_mm")
    if not isinstance(anchors, list) or len(anchors) != 2:
        f.invalid("anchors_mm")
    anchors = [rotation.T @ (f.vector(a, "anchors_mm") - center) for a in anchors]
    zone = p.get("machining_box_mm")
    if not isinstance(zone, list) or len(zone) != 2:
        f.invalid("machining_box_mm")
    lo, hi = [f.vector(a, "machining_box_mm") for a in zone]
    if np.any(hi <= lo):
        f.invalid("machining_box_mm bounds")
    zone_solid = g.box(lo, hi)
    originals = [objects[n][1] for n in names]
    f.require(g.overlap(*originals) < 1e-6, "source_parts_overlap")
    family = p.get("family", "pin_hinge")
    solids, ports, envelope, hardware, motion = module(family, p)
    radius = f.scalar(p, "mount_radius_mm", 2, hi=10)
    cutting = g.transform(g.box(*envelope), rotation, center)
    changed = []
    for i, key in enumerate(("parent", "child")):
        attached = g.transform(solids[key] + beam(ports[i], anchors[i], radius), rotation, center)
        stock = originals[i] - cutting
        f.require(g.overlap(stock, attached) > 1e-4, "mount_engagement")
        result = stock + attached
        f.checked_mesh(result)
        removed, added = originals[i] - result, result - originals[i]
        outside_removed = (removed - zone_solid).volume()
        outside_added = (added - zone_solid).volume()
        f.require(outside_removed < 1e-6 and outside_added < 1e-6, "machining_zone")
        solids[key] = result
        changed.append(
            {
                "part": key,
                "source": names[i],
                "removed_mm3": removed.volume(),
                "added_mm3": added.volume(),
                "outside_zone_changed_mm3": outside_removed + outside_added,
            }
        )
    for key in list(solids):
        if key not in ("parent", "child"):
            solids[key] = g.transform(solids[key], rotation, center)
            f.require((solids[key] - zone_solid).volume() < 1e-6, "machining_zone")
    pairs = []
    keys = list(solids)
    for i, a in enumerate(keys):
        for b in keys[i + 1 :]:
            volume = g.overlap(solids[a], solids[b])
            pairs.append({"a": a, "b": b, "overlap_mm3": volume})
            f.require(volume < 1e-6, "joint_rest_overlap")
    f.emit(
        w,
        solids,
        {
            "operation": "install-joint",
            "status": "pass",
            "family": family,
            "source_sha256": hashes,
            "center_mm": center.tolist(),
            "frame": rotation.tolist(),
            "machining_box_mm": [lo.tolist(), hi.tolist()],
            "changes": changed,
            "hardware": hardware,
            "rest_collisions": pairs,
            "motion_definition": motion,
            "travel_checked": False,
            "assembly_order_verified": False,
            "holding_strength_verified": False,
        },
    )
    export_urdf(w, solids, family, center, rotation, motion)
