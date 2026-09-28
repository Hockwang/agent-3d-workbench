"""Deterministic local tasks reusing Trimesh, Manifold, CadQuery and own MDE kernels."""

from pathlib import Path
import hashlib
import json
import math
import struct

import numpy as np
import trimesh
from studio.core.geometry_store import stl_bytes
from studio.i18n import render

from studio.paths import APP_DIST_DIR

CATALOG = [
    {
        "id": "cad-model",
        "title": "task_operations.cad_model_title",
        "engine": "python",
        "description": "task_operations.cad_model_description",
        "params": {"operation": "enclosure", "width_mm": 80, "depth_mm": 60, "height_mm": 30, "wall_mm": 3},
        "choices": {
            "operation": {
                "enclosure": "task_operations.cad_model_choice_operation_enclosure",
                "extrude": "task_operations.cad_model_choice_operation_extrude",
                "revolve": "task_operations.cad_model_choice_operation_revolve",
            }
        },
    },
    {
        "id": "joint-coupon",
        "title": "task_operations.joint_coupon_title",
        "engine": "python",
        "description": "task_operations.joint_coupon_description",
        "params": {"family": "compact_pivot", "clearance_mm": 0.2},
        "choices": {
            "family": {
                "compact_pivot": "task_operations.joint_coupon_choice_family_compact_pivot",
                "thin_slew": "task_operations.joint_coupon_choice_family_thin_slew",
            }
        },
    },
    {
        "id": "face-split",
        "title": "task_operations.face_split_title",
        "engine": "python",
        "description": "task_operations.face_split_description",
        "params": {},
    },
    {
        "id": "asset-preview",
        "title": "task_operations.asset_preview_title",
        "engine": "python",
        "description": "task_operations.asset_preview_description",
        "params": {},
    },
    {
        "id": "glb-clips",
        "title": "task_operations.glb_clips_title",
        "engine": "python",
        "description": "task_operations.glb_clips_description",
        "params": {"name": "Combined"},
    },
    {
        "id": "laser-slices",
        "title": "task_operations.laser_slices_title",
        "engine": "python",
        "description": "task_operations.laser_slices_description",
        "params": {"layer_mm": 3, "margin_mm": 5},
    },
]


def number(p, key, default, lower=0, upper=10000):
    x = float(p.get(key, default))
    if not math.isfinite(x) or not lower < x <= upper:
        raise ValueError(render("task_operations.number_out_of_range", key=key, lower=lower, upper=upper))
    return x


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def deliver(meshes, out, report, stl=True):
    scene = trimesh.Scene()
    for i, (name, original) in enumerate(meshes.items()):
        mesh = original.copy()
        if stl:
            (out / (name + ".stl")).write_bytes(stl_bytes(mesh))
        # Explicit mm / Z-up -> glTF metres / Y-up, same as the editor.
        transform = np.array([[0.001, 0, 0, 0], [0, 0, 0.001, 0], [0, -0.001, 0, 0], [0, 0, 0, 1]])
        mesh.apply_transform(transform)
        scene.add_geometry(mesh, node_name=name, geom_name=name)
    (out / "scene.glb").write_bytes(scene.export(file_type="glb"))
    write_json(out / "report.json", report)


def cad_model(w):
    import cadquery as cq

    p, out = w["params"], Path(w["output"])
    width, depth, height, wall = (
        number(p, k, d) for k, d in [("width_mm", 80), ("depth_mm", 60), ("height_mm", 30), ("wall_mm", 3)]
    )
    op = p.get("operation", "enclosure")
    if op == "enclosure":
        if 2 * wall >= min(width, depth, height):
            raise ValueError(render("task_operations.cad_wall_no_cavity"))
        body = cq.Workplane("XY").box(width, depth, height, centered=(True, True, False)).faces(">Z").shell(-wall)
    else:
        profile = p.get("profile_mm")
        if profile is None:
            profile = (
                [
                    [0, 0],
                    [width / 2, 0],
                    [width / 2, height],
                    [width / 2 - wall, height],
                    [width / 2 - wall, wall],
                    [0, wall],
                ]
                if op == "revolve"
                else [[0, 0], [width, 0], [width, depth], [0, depth]]
            )
        points = np.asarray(profile, float)
        if points.ndim != 2 or points.shape[1] != 2 or len(points) < 3 or not np.isfinite(points).all():
            raise ValueError(render("task_operations.cad_profile_requires_finite_points"))
        if op == "extrude":
            body = cq.Workplane("XY").polyline(points.tolist()).close().extrude(height)
        elif op == "revolve":
            body = cq.Workplane("XZ").polyline(points.tolist()).close().revolve(360, (0, 0), (0, 1))
        else:
            raise ValueError(render("task_operations.cad_unsupported_operation"))
    if not body.val().isValid():
        raise ValueError(render("task_operations.cad_invalid_solid"))
    cq.exporters.export(body, str(out / "model.step"))
    cq.exporters.export(body, str(out / "model.stl"), tolerance=0.03, angularTolerance=0.1)
    mesh = trimesh.load(out / "model.stl", force="mesh")
    if not mesh.is_volume:
        raise ValueError(render("task_operations.cad_stl_readback_not_closed"))
    deliver(
        {"model": mesh},
        out,
        {
            "engine": "CadQuery/OCP",
            "operation": op,
            "step_volume_mm3": body.val().Volume(),
            "stl_volume_mm3": float(mesh.volume),
            "watertight": bool(mesh.is_watertight),
        },
        stl=False,
    )


def joint_coupon(w):
    from studio.core.kernels.mechanical_geometry import mesh, box, cyl, overlap
    from studio.core.kernels.mechanical_modules import compact_pivot, thin_slew

    p, out = w["params"], Path(w["output"])
    gap = number(p, "clearance_mm", 0.2)
    family = p.get("family", "compact_pivot")
    if family == "compact_pivot":
        m = compact_pivot(gap=gap)
        parent = (
            m["fork"]
            + box([-7, -2, -5.4], [-2, 2, -m["inner"]])
            + box([-7, -2, m["inner"]], [-2, 2, 5.4])
            + box([-8, -2, -5.4], [-6, 2, 5.4])
        )
        child = m["tongue"] + box([2, -1, -1.2], [18, 1, 1.2])
        solids = {"fork": parent, "tongue": child}
        hardware = ["M2x8 screw", "M2 nut"]
    elif family == "thin_slew":
        m = thin_slew(gap=gap)
        solids = {"base": m["parent"], "rotor": m["child"] + cyl(m["radius"], gap + 0.55, gap + 4.0), "cap": m["cap"]}
        hardware = []
    else:
        raise ValueError(render("task_operations.joint_unsupported_family"))
    overlaps = {
        a + " / " + b: overlap(solids[a], solids[b]) for i, a in enumerate(solids) for b in list(solids)[i + 1 :]
    }
    if any(v > 1e-7 for v in overlaps.values()):
        raise ValueError(render("task_operations.joint_rest_pose_intersecting"))
    meshes = {name: mesh(s) for name, s in solids.items()}
    for name, item in meshes.items():
        if not item.is_volume or len(item.split(only_watertight=False)) != 1:
            raise ValueError(render("task_operations.joint_invalid_or_disconnected_coupon", name=name))
    deliver(
        meshes,
        out,
        {
            "family": family,
            "clearance_mm": gap,
            "rest_overlap_mm3": overlaps,
            "hardware": hardware,
            "physical_calibration": "pending",
            "holding_strength": "not measured",
        },
    )


def scene_input(filename):
    path = Path(filename)
    scene = trimesh.load(path, force="scene", process=False, allow_remote=False)
    if not scene.geometry:
        raise ValueError(render("task_operations.scene_input_no_mesh_geometry"))
    if path.suffix.lower() in (".glb", ".gltf"):
        scene.apply_transform(np.array([[1000, 0, 0, 0], [0, 0, -1000, 0], [0, 1000, 0, 0], [0, 0, 0, 1]]))
    return scene


def face_split(w):
    from studio.core.editor import _check_static

    sources = [Path(x) for x in w["inputs"]]
    model = next(x for x in sources if x.suffix.lower() in (".glb", ".stl", ".obj", ".ply"))
    labels = json.loads(next(x for x in sources if x.suffix.lower() == ".json").read_text())
    _check_static(model)
    if labels.get("source_sha256") != hashlib.sha256(model.read_bytes()).hexdigest():
        raise ValueError(render("task_operations.face_split_labels_not_bound_to_source"))
    scene = scene_input(model)
    out = Path(w["output"])
    parts = {}
    stats = []
    for node in scene.graph.nodes_geometry:
        transform, key = scene.graph[node]
        mesh = scene.geometry[key].copy()
        mesh.apply_transform(transform)
        assignment = labels["nodes"][node]
        if len(assignment) != len(mesh.faces) or not all(isinstance(x, str) and x for x in assignment):
            raise ValueError(render("task_operations.face_split_every_face_needs_label"))
        values = np.array(assignment)
        for label in sorted(set(assignment)):
            indices = np.flatnonzero(values == label)
            part = mesh.submesh([indices], append=True, repair=False)
            if len(part.faces) != len(indices):
                raise ValueError(render("task_operations.face_split_subset_changed_topology"))
            name = f"{len(parts):03d}_" + "".join(c if c.isalnum() or c in "-_" else "_" for c in label)[:60]
            parts[name] = part
            stats.append({"part": name, "node": node, "label": label, "faces": len(indices)})
    if set(labels["nodes"]) != set(scene.graph.nodes_geometry):
        raise ValueError(render("task_operations.face_split_node_set_mismatch"))
    deliver(
        parts,
        out,
        {
            "source_sha256": labels["source_sha256"],
            "parts": stats,
            "faces": sum(x["faces"] for x in stats),
            "capped": False,
        },
        stl=False,
    )


def glb_data(path):
    raw = Path(path).read_bytes()
    if (
        len(raw) < 20
        or raw[:4] != b"glTF"
        or struct.unpack_from("<II", raw, 4) != (2, len(raw))
        or raw[16:20] != b"JSON"
    ):
        raise ValueError(render("task_operations.glb_invalid"))
    size = struct.unpack_from("<I", raw, 12)[0]
    doc = json.loads(raw[20 : 20 + size])
    if any(x.get("uri") for x in doc.get("buffers", []) + doc.get("images", [])):
        raise ValueError(render("task_operations.glb_must_embed_resources"))
    return raw, doc, size


def asset_preview(w):
    out = Path(w["output"])
    for i, path in enumerate(w["inputs"]):
        raw, doc, _ = glb_data(path)
        (out / f"asset-{i}.glb").write_bytes(raw)
    if not w["inputs"]:
        raise ValueError(render("task_operations.asset_preview_requires_glb"))


def glb_clips(w):
    out = Path(w["output"])
    raw, doc, size = glb_data(w["inputs"][0])
    animations = doc.get("animations", [])
    if not animations:
        raise ValueError(render("task_operations.glb_clips_no_animations"))
    merged = {"name": str(w["params"].get("name", "Combined")), "samplers": [], "channels": []}
    targets = set()
    for animation in animations:
        offset = len(merged["samplers"])
        merged["samplers"].extend(animation["samplers"])
        for channel in animation["channels"]:
            target = channel["target"]
            key = (target.get("node"), target.get("path"))
            if key in targets:
                raise ValueError(render("task_operations.glb_clips_conflicting_channels"))
            targets.add(key)
            merged["channels"].append({**channel, "sampler": channel["sampler"] + offset})
    doc["animations"] = [merged]
    encoded = json.dumps(doc, separators=(",", ":")).encode()
    encoded += b" " * (-len(encoded) % 4)
    tail = raw[20 + size :]
    (out / "combined.glb").write_bytes(
        struct.pack("<III", 0x46546C67, 2, 20 + len(encoded) + len(tail))
        + struct.pack("<II", len(encoded), 0x4E4F534A)
        + encoded
        + tail
    )
    write_json(
        out / "report.json",
        {"source_clips": len(animations), "output_clips": 1, "channels": len(merged["channels"]), "resampled": False},
    )


def laser_slices(w):
    from xml.etree.ElementTree import Element, SubElement, tostring

    p, out = w["params"], Path(w["output"])
    layer = number(p, "layer_mm", 3)
    margin = number(p, "margin_mm", 5)
    mesh = scene_input(w["inputs"][0]).to_mesh()
    vertices, inverse = np.unique(mesh.vertices, axis=0, return_inverse=True)
    mesh = trimesh.Trimesh(vertices, inverse[mesh.faces], process=False)
    if not mesh.is_volume:
        raise ValueError(render("task_operations.laser_requires_closed_mesh"))
    lo, hi = mesh.bounds
    count = int(math.ceil((hi[2] - lo[2]) / layer))
    if not 1 <= count <= 500:
        raise ValueError(render("task_operations.laser_layer_count_range"))
    rows = []
    for i in range(count):
        bottom = lo[2] + i * layer
        top = min(bottom + layer, hi[2])
        z = (bottom + top) / 2
        section = mesh.section(plane_origin=[0, 0, z], plane_normal=[0, 0, 1])
        if section is None:
            continue
        width, height = hi[:2] - lo[:2] + margin * 2
        svg = Element(
            "svg",
            xmlns="http://www.w3.org/2000/svg",
            width=f"{width}mm",
            height=f"{height}mm",
            viewBox=f"0 0 {width} {height}",
        )
        loops = 0
        for curve in section.discrete:
            if not np.allclose(curve[0], curve[-1], atol=1e-7):
                raise ValueError(render("task_operations.laser_open_section"))
            xy = curve[:, :2] - lo[:2] + margin
            path = "M " + " L ".join(f"{x:.6f},{height - y:.6f}" for x, y in xy) + " Z"
            SubElement(svg, "path", d=path, fill="none", stroke="#000000", **{"stroke-width": "0.01"})
            loops += 1
        (out / f"layer-{i:03d}.svg").write_bytes(tostring(svg))
        rows.append({"index": i, "z_mm": float(z), "thickness_mm": float(top - bottom), "closed_loops": loops})
    write_json(
        out / "layers.json",
        {"layer_mm": layer, "layers": rows, "kerf_compensation_mm": 0, "physical_fit": "requires material test"},
    )


OPERATIONS = {
    "cad-model": cad_model,
    "joint-coupon": joint_coupon,
    "face-split": face_split,
    "asset-preview": asset_preview,
    "glb-clips": glb_clips,
    "laser-slices": laser_slices,
}


def run(template, workbench):
    OPERATIONS[template](workbench)


def relief(w):
    from PIL import Image

    p, out = w["params"], Path(w["output"])
    width = number(p, "width_mm", 100)
    base = number(p, "base_mm", 3)
    height = number(p, "relief_mm", 4)
    samples = int(p.get("samples", 128))
    if not 8 <= samples <= 256:
        raise ValueError(render("task_operations.relief_samples_range"))
    with Image.open(w["inputs"][0]) as image:
        image = image.convert("L")
        image.thumbnail((samples, samples))
        pixels = np.asarray(image, dtype=float) / 255
        ny, nx = pixels.shape
    if min(nx, ny) < 2:
        raise ValueError(render("task_operations.relief_image_too_narrow"))
    yy, xx = np.meshgrid(np.linspace(0, width * ny / nx, ny), np.linspace(0, width, nx), indexing="ij")
    vertices = np.c_[xx.ravel(), yy.ravel(), (base + height * pixels).ravel()].tolist()
    faces = []
    for y in range(ny - 1):
        for x in range(nx - 1):
            a = y * nx + x
            faces.extend([[a, a + 1, a + nx + 1], [a, a + nx + 1, a + nx]])
    ring = (
        list(range(nx))
        + [y * nx + nx - 1 for y in range(1, ny)]
        + list(range((ny - 1) * nx + nx - 2, (ny - 1) * nx - 1, -1))
        + [y * nx for y in range(ny - 2, 0, -1)]
    )
    bottoms = []
    for index in ring:
        bottoms.append(len(vertices))
        vertices.append([vertices[index][0], vertices[index][1], 0])
    center = len(vertices)
    vertices.append([width / 2, width * ny / nx / 2, 0])
    for i, a in enumerate(ring):
        j = (i + 1) % len(ring)
        b = ring[j]
        c, d = bottoms[i], bottoms[j]
        faces.extend([[a, c, d], [a, d, b], [center, d, c]])
    mesh = trimesh.Trimesh(vertices, faces, process=False)
    if not mesh.is_volume:
        raise ValueError(render("task_operations.relief_not_closed_solid"))
    deliver(
        {"relief": mesh},
        out,
        {
            "operation": "image-relief",
            "resolution": [nx, ny],
            "width_mm": width,
            "base_mm": base,
            "relief_mm": height,
            "watertight": True,
        },
    )


def assembly_audit_urdf(path, p):
    """URDF mode of `assembly-audit`: report pairwise overlaps between links.
    The legacy default samples actuated, non-mimic joints simultaneously and
    linearly: one diagonal through configuration space. `motion-check` instead
    requests a bounded Cartesian grid or explicit configurations. The report's
    `sweep` field identifies the sampling contract actually used.

    Mimic joints are excluded from the swept parameter set itself, but
    `yourdfpy`'s own `update_cfg` resolves every mimic joint's pose from its
    already-updated master on each sampled step (see `Mimic`/
    `_forward_kinematics_joint` in `yourdfpy.urdf`), so they still move; the
    report's `mimic_joints` lists which joints that applies to and their
    master/multiplier/offset.

    Links connected only through a chain of `fixed` joints are unioned into
    one solid per rigid group, named after the group's root link (the member
    with no incoming `fixed` edge from inside the same group), before
    pairwise testing -- so e.g. a bracket bolted to a base with
    interpenetrating rest geometry is not reported as a false-positive
    collision. `rigid_groups` in the report lists the merges that were made.

    URDF geometry is authored in metres; the mechanical-geometry kernels and
    `tolerance_mm3` operate in millimetres, so every per-group solid is
    scaled x1000 before intersection-testing, and the report says
    `"units": "mm"`. `joint_ranges` overrides stay in each joint's own native
    URDF unit (radians for revolute/continuous, metres for prismatic) --
    see `joint_ranges_units` in the report.
    """
    from studio.core.observation import dependencies
    from studio.core.observation_run import load_urdf
    from studio.core.kernels.mechanical_geometry import solid, union, overlap

    dependencies(path)  # same URDF safety/structure validation as model-observe
    robot, joints = load_urdf(path)
    steps = int(p.get("steps", 21))
    tolerance = float(p.get("tolerance_mm3", 0.001))
    if not 2 <= steps <= 101 or not math.isfinite(tolerance) or tolerance < 0:
        raise ValueError(render("task_operations.audit_invalid_motion_plan"))
    overrides = p.get("joint_ranges", {})
    if not isinstance(overrides, dict):
        raise ValueError(render("task_operations.audit_urdf_invalid_joint_ranges"))
    actuated = [j for j in joints if j["type"] != "fixed" and not j["mimic"]]
    actuated_names = {j["name"] for j in actuated}
    resolved_overrides = {}
    for name, rng in overrides.items():
        if name not in actuated_names or not isinstance(rng, (list, tuple)) or len(rng) != 2:
            raise ValueError(render("task_operations.audit_urdf_invalid_joint_ranges"))
        try:
            lo, hi = float(rng[0]), float(rng[1])
        except (TypeError, ValueError):
            raise ValueError(render("task_operations.audit_urdf_invalid_joint_ranges")) from None
        if not math.isfinite(lo) or not math.isfinite(hi) or lo >= hi:
            raise ValueError(render("task_operations.audit_urdf_invalid_joint_ranges"))
        resolved_overrides[name] = [lo, hi]
    missing_range = [j["name"] for j in actuated if j["type"] == "continuous" and j["name"] not in resolved_overrides]
    if missing_range:
        raise ValueError(render("task_operations.audit_urdf_continuous_needs_range", name=missing_range[0]))
    sweep = [
        {**j, "range": resolved_overrides.get(j["name"], [float(j["range"][0]), float(j["range"][1])])}
        for j in actuated
    ]

    # Rigid groups: any chain of links connected only by `fixed` joints is
    # merged into one solid, named after the group's root -- the one member
    # reached last when walking each link up through `fixed` parents only.
    fixed_parent = {j["child"]: j["parent"] for j in joints if j["type"] == "fixed"}

    def rigid_root(link):
        seen = set()
        while link in fixed_parent and link not in seen:
            seen.add(link)
            link = fixed_parent[link]
        return link

    all_links = {j["parent"] for j in joints} | {j["child"] for j in joints}
    rigid_groups = {}
    for link in all_links:
        rigid_groups.setdefault(rigid_root(link), []).append(link)
    for members in rigid_groups.values():
        members.sort()

    def group_solids():
        scene = robot.scene
        parents = scene.graph.transforms.parents
        per_link_meshes = {}
        for node in scene.graph.nodes_geometry:
            transform, key = scene.graph[node]
            link = parents.get(node, node)
            mesh = scene.geometry[key].copy()
            mesh.apply_transform(transform)
            per_link_meshes.setdefault(link, []).append(mesh)
        per_link_solid = {
            link: solid((trimesh.util.concatenate(meshes) if len(meshes) > 1 else meshes[0]).apply_scale(1000.0))
            for link, meshes in per_link_meshes.items()
        }
        grouped = {}
        for root, members in rigid_groups.items():
            parts = [per_link_solid[m] for m in members if m in per_link_solid]
            if not parts:
                continue
            grouped[root] = parts[0] if len(parts) == 1 else union(parts)
        return grouped

    from studio.core.motion_check import configurations

    sampling, poses = configurations(sweep, p)
    samples = []
    object_names = None
    merged_groups = {}
    for pose in poses:
        if sweep:
            robot.update_cfg(pose["configuration"])
        solids = group_solids()
        if object_names is None:
            object_names = list(solids)
            if not 2 <= len(object_names) <= 40:
                raise ValueError(render("task_operations.audit_requires_2_to_40_solids"))
            merged_groups = {root: rigid_groups[root] for root in object_names if len(rigid_groups[root]) > 1}
        pairs = []
        for i, a in enumerate(object_names):
            for b in object_names[i + 1 :]:
                volume = overlap(solids[a], solids[b])
                if volume > tolerance:
                    pairs.append({"a": a, "b": b, "overlap_mm3": float(volume)})
        samples.append({**pose, "collisions": pairs})
    mimic_joints = [
        {
            "name": j.name,
            "master": j.mimic.joint,
            "multiplier": j.mimic.multiplier if j.mimic.multiplier is not None else 1.0,
            "offset": j.mimic.offset if j.mimic.offset is not None else 0.0,
        }
        for j in robot.robot.joints
        if j.mimic is not None
    ]
    return {
        "status": "pass" if all(not x["collisions"] for x in samples) else "fail",
        "mode": "urdf",
        "sweep": sampling,
        "objects": object_names,
        "rigid_groups": merged_groups,
        "mimic_joints": mimic_joints,
        "joints": [
            {
                "name": j["name"],
                "type": j["type"],
                "parent": j["parent"],
                "child": j["child"],
                "axis": j["axis"],
                "range": j["range"],
            }
            for j in sweep
        ],
        "samples": samples,
        "tolerance_mm3": tolerance,
        "units": "mm",
        "joint_ranges_units": {"revolute": "rad", "continuous": "rad", "prismatic": "m"},
        "continuous_motion_checked": False,
        "check": "exact solid intersections at explicit sampled poses; contact/strength/physical fit not certified",
    }


def assembly_audit(w):
    from studio.core.kernels.mechanical_geometry import solid, overlap

    p, out = w["params"], Path(w["output"])
    sources = [Path(x) for x in w["inputs"]]
    if any(x.suffix.lower() == ".urdf" for x in sources):
        if len(sources) != 1:
            raise ValueError(render("task_operations.audit_requires_single_urdf_input"))
        write_json(out / "assembly-audit.json", assembly_audit_urdf(sources[0], p))
        return
    objects = {}
    for filename in w["inputs"]:
        scene = scene_input(filename)
        for node in scene.graph.nodes_geometry:
            transform, key = scene.graph[node]
            mesh = scene.geometry[key].copy()
            mesh.apply_transform(transform)
            if node in objects:
                raise ValueError(render("task_operations.audit_object_names_must_be_unique"))
            objects[node] = solid(mesh)
    if not 2 <= len(objects) <= 40:
        raise ValueError(render("task_operations.audit_requires_2_to_40_solids"))
    motions = p.get("motions", {})
    steps = int(p.get("steps", 21))
    tolerance = float(p.get("tolerance_mm3", 0.001))
    if (
        not isinstance(motions, dict)
        or not set(motions) <= set(objects)
        or not 2 <= steps <= 101
        or not math.isfinite(tolerance)
        or tolerance < 0
    ):
        raise ValueError(render("task_operations.audit_invalid_motion_plan"))
    samples = []
    for t in np.linspace(0, 1, steps if motions else 1):
        pose = dict(objects)
        for node, motion in motions.items():
            if motion.get("type", "revolute") == "revolute":
                lo, hi = motion.get("range_deg", [0, 90])
                angle = math.radians(lo + (hi - lo) * t)
                transform = trimesh.transformations.rotation_matrix(
                    angle, np.asarray(motion["axis"], float), np.asarray(motion["pivot_mm"], float)
                )
            elif motion["type"] == "prismatic":
                lo, hi = motion.get("range_mm", [0, 10])
                axis = np.asarray(motion["axis"], float)
                axis /= np.linalg.norm(axis)
                transform = np.eye(4)
                transform[:3, 3] = axis * (lo + (hi - lo) * t)
            else:
                raise ValueError(render("task_operations.audit_motion_type_invalid"))
            if not np.isfinite(transform).all():
                raise ValueError(render("task_operations.audit_invalid_motion_transform"))
            pose[node] = pose[node].transform(transform[:3, :])
        pairs = []
        names = list(pose)
        for i, a in enumerate(names):
            for b in names[i + 1 :]:
                volume = overlap(pose[a], pose[b])
                if volume > tolerance:
                    pairs.append({"a": a, "b": b, "overlap_mm3": float(volume)})
        samples.append({"phase": float(t), "collisions": pairs})
    write_json(
        out / "assembly-audit.json",
        {
            "status": "pass" if all(not x["collisions"] for x in samples) else "fail",
            "mode": "glb",
            "objects": list(objects),
            "samples": samples,
            "tolerance_mm3": tolerance,
            "units": "mm",
            "continuous_motion_checked": False,
            "check": "exact solid intersections at explicit sampled poses; contact/strength/physical fit not certified",
        },
    )


OPERATIONS.update({"image-relief": relief, "assembly-audit": assembly_audit})
CATALOG.extend(
    [
        {
            "id": "image-relief",
            "title": "task_operations.image_relief_title",
            "engine": "python",
            "description": "task_operations.image_relief_description",
            "params": {"width_mm": 100, "base_mm": 3, "relief_mm": 4, "samples": 128},
        },
        {
            "id": "assembly-audit",
            "title": "task_operations.assembly_audit_title",
            "engine": "python",
            "description": "task_operations.assembly_audit_description",
            "params": {"steps": 21, "tolerance_mm3": 0.001},
        },
    ]
)


def interactive_scene(w):
    import base64

    p, out = w["params"], Path(w["output"])
    assets = []
    for filename in w["inputs"]:
        raw, _, _ = glb_data(filename)
        if len(raw) > 100 * 1024 * 1024:
            raise ValueError(render("task_operations.interactive_asset_over_100mb"))
        assets.append({"name": Path(filename).name, "data": base64.b64encode(raw).decode()})
    if not assets:
        raise ValueError(render("task_operations.interactive_requires_glb_files"))
    data = {"title": str(p.get("title", "3D 成果")), "assets": assets, "hotspots": p.get("hotspots", [])}
    if sum(len(x["data"]) for x in assets) > 180 * 1024 * 1024:
        raise ValueError(render("task_operations.interactive_scene_over_180mb"))
    if not isinstance(data["hotspots"], list) or len(data["hotspots"]) > 100:
        raise ValueError(render("task_operations.interactive_hotspots_max_100"))
    for item in data["hotspots"]:
        if not isinstance(item, dict) or not isinstance(item.get("label"), str):
            raise ValueError(render("task_operations.interactive_hotspot_needs_label"))
        position = np.asarray(item.get("position", [0, 0, 0]), float)
        if position.shape != (3,) or not np.isfinite(position).all():
            # Deliberately NOT converted: tests/test_task_operations.py asserts
            # `pytest.raises(ValueError, match="finite XYZ")` under the test
            # suite's pinned STUDIO_LANG=zh-CN, and a faithful Chinese
            # translation would not contain that English phrase. See the
            # module docstring in studio/core/messages_tasks.py.
            raise ValueError("Hotspot position requires finite XYZ metre coordinates")
    encoded = json.dumps(data, ensure_ascii=True).replace("<", "\\u003c")
    template = APP_DIST_DIR / "delivery.html"
    html = template.read_text().replace("__WORKBENCH_PROJECT_DATA__", encoded)
    (out / "index.html").write_text(html)
    write_json(
        out / "manifest.json",
        {
            "title": data["title"],
            "inputs": [
                {"name": Path(x).name, "sha256": hashlib.sha256(Path(x).read_bytes()).hexdigest()} for x in w["inputs"]
            ],
            "offline": True,
            "asset_count": len(assets),
            "interaction": "orbit, WASD navigation, animation playback, clickable hotspots",
            "physics": False,
        },
    )


OPERATIONS["interactive-scene"] = interactive_scene
CATALOG.append(
    {
        "id": "interactive-scene",
        "title": "task_operations.interactive_scene_title",
        "engine": "python",
        "description": "task_operations.interactive_scene_description",
        "params": {"title": "我的 3D 场景"},
    }
)


def removal_audit(w):
    """Discrete removal/assembly-order check for any watertight STL parts,
    reusing `head_shell_audit.audit_parts` -- the same geometric core the
    `shell-kit` task's own assembly audit runs on a head shell.
    """
    from studio.core.head_shell_audit import audit_parts

    p, out = w["params"], Path(w["output"])
    meshes = {}
    for filename in w["inputs"]:
        path = Path(filename)
        if path.suffix.lower() != ".stl":
            raise ValueError(render("task_operations.removal_audit_requires_stl"))
        if path.stem in meshes:
            raise ValueError(render("task_operations.audit_object_names_must_be_unique"))
        mesh = trimesh.load_mesh(path, process=True)
        if not mesh.is_volume or len(mesh.split(only_watertight=False, repair=False)) != 1:
            raise ValueError(render("task_operations.removal_audit_part_not_single_watertight", name=path.stem))
        meshes[path.stem] = mesh
    if not 2 <= len(meshes) <= 40:
        raise ValueError(render("task_operations.audit_requires_2_to_40_solids"))

    def finite_vec3(v):
        return (
            isinstance(v, (list, tuple))
            and len(v) == 3
            and all(isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) for x in v)
        )

    groups = p.get("groups") or {"assembly": list(meshes)}
    if not isinstance(groups, dict) or any(
        not isinstance(members, list) or any(n not in meshes for n in members) for members in groups.values()
    ):
        raise ValueError(render("task_operations.removal_audit_invalid_groups"))
    insertion_directions = p.get("insertion_directions", {})
    if not isinstance(insertion_directions, dict) or any(
        name not in meshes or not finite_vec3(v) for name, v in insertion_directions.items()
    ):
        raise ValueError(render("task_operations.removal_audit_invalid_insertion_directions"))
    split_axis = p.get("split_axis", 1)
    if isinstance(split_axis, bool) or split_axis not in (0, 1, 2):
        raise ValueError(render("task_operations.removal_audit_invalid_split_axis"))
    split_value = p.get("split_value_mm", 0.0)
    if not isinstance(split_value, (int, float)) or isinstance(split_value, bool) or not math.isfinite(split_value):
        raise ValueError(render("task_operations.removal_audit_invalid_split_value"))
    bounds = trimesh.util.concatenate(list(meshes.values())).bounds
    default_center = ((bounds[0] + bounds[1]) / 2).tolist()
    radial_center_mm = p.get("radial_center_mm", default_center)
    if not finite_vec3(radial_center_mm):
        raise ValueError(render("task_operations.removal_audit_invalid_radial_center"))
    result = audit_parts(
        meshes,
        groups=groups,
        insertion_directions=insertion_directions,
        radial_center_mm=list(radial_center_mm),
        split_axis=split_axis,
        split_value=float(split_value),
    )
    # `audit_parts` is shared with `head_shell_audit.audit()`, whose own
    # `assembly-verification.json` must stay byte-identical, so its
    # head-shell-flavoured `limitations` text and Y-only `translation_y_mm`
    # field name are left as returned; this task template instead replaces/
    # augments them here, only for its own `removal-audit.json` output.
    result["limitations"] = [
        render("task_operations.removal_audit_limitations_groups"),
        render("task_operations.removal_audit_limitations_sampling"),
    ]
    result["split_axis"] = split_axis
    for entry in result["whole_halves"]:
        entry["translation_mm"] = entry["translation_y_mm"]
    write_json(out / "removal-audit.json", result)


OPERATIONS["removal-audit"] = removal_audit
CATALOG.append(
    {
        "id": "removal-audit",
        "title": "task_operations.removal_audit_title",
        "engine": "python",
        "description": "task_operations.removal_audit_description",
        "params": {"split_axis": 1, "split_value_mm": 0},
    }
)
