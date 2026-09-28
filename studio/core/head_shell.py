"""Source-preserving split shells. Millimetres, Z-up, front = -Y.

The cavity is an explicitly approximate voxel erosion. The source exterior is
never remeshed. Component identity/colours are supplied, not inferred from
STL. Runs as a `studio.core.tasks` task-worker script (template `shell-kit`);
see `studio/core/task_templates.py::script_for`.
"""

from pathlib import Path
import hashlib
import json
import re
import math

import numpy as np
import trimesh
import manifold3d as mf
from scipy import ndimage
from skimage.measure import marching_cubes
from shapely.geometry import Polygon

from studio.core.editor import _check_static, _textured
from studio.i18n import render
from studio.core.task_operations import scene_input, deliver, number, write_json
from studio.core.kernels.mechanical_geometry import solid, mesh, union, cyl, overlap

CATALOG = [
    {
        "id": "shell-kit",
        "title": "head_shell.shell_kit_title",
        "engine": "python",
        "description": "head_shell.shell_kit_description",
        "params": {
            "target_width_mm": 400,
            "wall_mm": 3,
            "voxel_mm": 1,
            "head_circumference_mm": 600,
            "head_height_mm": 235,
            "padding_mm": 10,
            "split_y_mm": 0,
            "seam_gap_mm": 0.4,
            "neck_width_mm": 180,
            "neck_depth_mm": 180,
            "neck_top_mm": 55,
            "magnet_diameter_mm": 6,
            "magnet_thickness_mm": 3,
            "magnet_clearance_mm": 0.2,
            "magnet_pairs": 4,
            "insert_clearance_mm": 0.25,
            "preserve_components": True,
            "preserve_eye_outline": True,
            "allow_material_loss": False,
        },
        "labels": {
            "target_width_mm": "head_shell.shell_kit_label_target_width_mm",
            "voxel_mm": "head_shell.shell_kit_label_voxel_mm",
            "head_circumference_mm": "head_shell.shell_kit_label_head_circumference_mm",
            "head_height_mm": "head_shell.shell_kit_label_head_height_mm",
            "padding_mm": "head_shell.shell_kit_label_padding_mm",
            "split_y_mm": "head_shell.shell_kit_label_split_y_mm",
            "seam_gap_mm": "head_shell.shell_kit_label_seam_gap_mm",
            "neck_width_mm": "head_shell.shell_kit_label_neck_width_mm",
            "neck_depth_mm": "head_shell.shell_kit_label_neck_depth_mm",
            "neck_top_mm": "head_shell.shell_kit_label_neck_top_mm",
            "magnet_diameter_mm": "head_shell.shell_kit_label_magnet_diameter_mm",
            "magnet_thickness_mm": "head_shell.shell_kit_label_magnet_thickness_mm",
            "magnet_clearance_mm": "head_shell.shell_kit_label_magnet_clearance_mm",
            "magnet_pairs": "head_shell.shell_kit_label_magnet_pairs",
            "insert_clearance_mm": "head_shell.shell_kit_label_insert_clearance_mm",
            "preserve_components": "head_shell.shell_kit_label_preserve_components",
            "preserve_eye_outline": "head_shell.shell_kit_label_preserve_eye_outline",
        },
    }
]


def finite_vector(value, size, name):
    result = np.asarray(value, dtype=float)
    if result.shape != (size,) or not np.isfinite(result).all():
        raise ValueError(render("head_shell.finite_vector_required", name=name))
    return result


def head_envelope(p):
    if "head_envelope_mm" in p:
        return finite_vector(p["head_envelope_mm"], 3, render("head_shell.name_head_envelope_dims"))
    circumference = number(p, "head_circumference_mm", 600, upper=1000)
    ratio = number(p, "head_depth_width_ratio", 1.2, lower=0.8, upper=1.6)
    # Ramanujan ellipse perimeter; this is a declared design assumption,
    # not an inference of someone's head shape from circumference alone.
    factor = math.pi / 2 * (3 * (1 + ratio) - math.sqrt((3 + ratio) * (1 + 3 * ratio)))
    width = circumference / factor
    padding = number(p, "padding_mm", 10, upper=50)
    return np.array([width, ratio * width, number(p, "head_height_mm", 235, upper=400)]) + 2 * padding


def load_components(w):
    if len(w["inputs"]) != 1:
        raise ValueError(render("head_shell.source_file_required"))
    path = Path(w["inputs"][0])
    _check_static(path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    p = w["params"]
    if p.get("source_sha256") and p["source_sha256"] != digest:
        raise ValueError(render("head_shell.source_sha_mismatch"))
    scene = scene_input(path)
    meshes = []
    for node in scene.graph.nodes_geometry:
        t, key = scene.graph[node]
        m = scene.geometry[key].copy()
        m.apply_transform(t)
        if _textured(m) and p.get("allow_material_loss") is not True:
            raise ValueError(render("head_shell.shell_material_loss_opt_in_required"))
        # STL repeats vertices per triangle. Exact welding does not move them.
        vertices, inverse = np.unique(m.vertices, axis=0, return_inverse=True)
        m = trimesh.Trimesh(vertices, inverse[m.faces], process=False)
        for part in m.split(only_watertight=False, repair=False):
            if not part.is_volume:
                raise ValueError(render("head_shell.source_component_must_be_closed_solid"))
            meshes.append(part)
    if not 1 <= len(meshes) <= 64:
        raise ValueError(render("head_shell.source_component_count_range"))
    all_vertices = np.vstack([m.bounds for m in meshes])
    lo, hi = all_vertices.min(0), all_vertices.max(0)
    scale = number(p, "target_width_mm", 400, upper=1500) / (hi[0] - lo[0])
    origin = np.array([(lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, lo[2]])
    for m in meshes:
        m.vertices = (m.vertices - origin) * scale
    return meshes, {
        "source_sha256": digest,
        "scale": scale,
        "source_origin_mm": origin.tolist(),
        "component_faces": [len(m.faces) for m in meshes],
        "source_extents_mm": (hi - lo).tolist(),
        "output_extents_mm": ((hi - lo) * scale).tolist(),
    }


def eroded_cavity(parts, wall, pitch):
    """Create only the largest connected void, keeping thin sealed tips solid."""
    joined = trimesh.util.concatenate(parts)
    cells = np.ceil(joined.extents / pitch).astype(int) + 7
    if np.prod(cells, dtype=np.int64) > 80_000_000:
        raise ValueError(render("head_shell.cavity_grid_too_large"))
    if pitch > wall / 2:
        raise ValueError(render("head_shell.voxel_mm_exceeds_half_wall"))
    vox = joined.voxelized(pitch).fill()
    occupancy = np.pad(vox.matrix, 2)
    distance = ndimage.distance_transform_edt(occupancy, sampling=pitch).astype(np.float32)
    # Conservative allowance for surface rasterisation and cell interpolation.
    inset = wall + np.sqrt(3) * pitch
    mask = distance > inset
    labels, n = ndimage.label(mask)
    if not n:
        raise ValueError(render("head_shell.wall_too_thick_no_cavity"))
    sizes = np.bincount(labels.ravel())
    sizes[0] = 0
    keep = int(sizes.argmax())
    distance[labels != keep] = np.minimum(distance[labels != keep], inset - 0.01)
    vertices, faces, _, _ = marching_cubes(distance, level=inset, spacing=(pitch,) * 3)
    vertices += vox.transform[:3, 3] - 2 * pitch
    cavity = trimesh.Trimesh(vertices, faces, process=True)
    cavity.fix_normals()
    # All disconnected material removed from the *void* is explicitly reported.
    return solid(cavity), {
        "pitch_mm": pitch,
        "erosion_level_mm": float(inset),
        "grid_shape": list(occupancy.shape),
        "discarded_void_voxels": int(sizes.sum() - sizes[keep]),
        "cavity_volume_mm3": float(cavity.volume),
        "method": "voxel EDT, conservative inset, largest connected void",
    }


def cylinder_y(radius, y0, y1, x, z):
    return cyl(radius, y0, y1).rotate([-90, 0, 0]).translate([x, 0, z])


def main_component(s, name, tolerance=1e-6):
    chunks = s.decompose()
    volumes = np.array([abs(c.volume()) for c in chunks])
    material = [c for c, v in zip(chunks, volumes) if v > tolerance]
    if len(material) != 1:
        raise ValueError(
            render(
                "head_shell.main_component_fragment_count",
                name=name,
                count=len(material),
                volumes=volumes.tolist(),
                bounds=[c.bounding_box() for c in material],
            )
        )
    return material[0], float(volumes[volumes <= tolerance].sum())


def magnet_sites(body, split, radius, depth, count, neck_top):
    """Search a seam cross-section; test complete padded cylinders in the source."""
    boundary = mesh(body).section(plane_origin=[0, split, 0], plane_normal=[0, 1, 0])
    if boundary is None:
        raise ValueError(render("head_shell.split_plane_does_not_cross_body"))
    polygons = [Polygon(loop[:, [0, 2]]) for loop in boundary.discrete if len(loop) > 3]
    polygons = [p for p in polygons if p.is_valid and p.area > 0]
    if not polygons:
        raise ValueError(render("head_shell.split_outline_not_closed_loop"))
    outer = max(polygons, key=lambda q: q.area)
    inside = outer.buffer(-(radius + 1.0))
    if inside.is_empty or inside.geom_type != "Polygon":
        raise ValueError(render("head_shell.seam_insufficient_magnet_space"))
    ring = inside.exterior
    candidates = []
    for fraction in np.linspace(0, 1, 180, endpoint=False):
        point = ring.interpolate(fraction, normalized=True)
        x, z = point.x, point.y
        if z < neck_top + radius + 8:
            continue
        envelope = cylinder_y(radius + 0.65, split - depth - 0.65, split + depth + 0.65, x, z)
        if (envelope - body).volume() < 1e-4:
            candidates.append(np.array([x, z]))
    if len(candidates) < count:
        raise ValueError(render("head_shell.insufficient_hidden_magnet_sites"))
    candidates = np.array(candidates)
    chosen = [int(np.argmin(candidates[:, 0]))]
    while len(chosen) < count:
        distances = np.linalg.norm(candidates[:, None] - candidates[chosen][None, :], axis=2).min(1)
        i = int(distances.argmax())
        if distances[i] < 2 * radius + 8:
            raise ValueError(render("head_shell.magnet_site_spacing_insufficient"))
        chosen.append(i)
    return candidates[chosen]


def color_mesh(part, hex_color):
    m = mesh(part)
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", hex_color):
        raise ValueError(render("head_shell.color_must_be_hex"))
    m.visual.face_colors = [int(hex_color[i : i + 2], 16) for i in (1, 3, 5)] + [255]
    return m


def clearance_cutter(s, amount, convex_socket=False):
    # Offset the original closed component, never the thin hollow fragment.
    # Vertex displacement is bounded; reject folding/non-containing offsets.
    # Actual minimum gaps are checked after all Boolean operations.
    original = s
    if convex_socket:
        s = s.hull()
        if s.volume() > original.volume() * 1.05:
            raise ValueError(render("head_shell.convex_socket_expansion_exceeds_limit"))
    m = mesh(s)
    m.vertices = m.vertices + m.vertex_normals * amount
    result = solid(m)
    if (s - result).volume() > 1e-5:
        raise ValueError(render("head_shell.normal_offset_does_not_enclose_source"))
    return result


def head_shell(w):
    p, out = w["params"], Path(w["output"])
    out.mkdir(parents=True, exist_ok=True)
    parts, info = load_components(w)
    wall = number(p, "wall_mm", 3, upper=20)
    pitch = number(p, "voxel_mm", 1, upper=3)
    gap = number(p, "seam_gap_mm", 0.4, upper=3)
    md = number(p, "magnet_diameter_mm", 6, upper=30)
    mt = number(p, "magnet_thickness_mm", 3, upper=15)
    mc = number(p, "magnet_clearance_mm", 0.2, upper=2)
    insert_gap = number(p, "insert_clearance_mm", 0.25, upper=2)
    nw = number(p, "neck_width_mm", 180, upper=500)
    nd = number(p, "neck_depth_mm", 180, upper=500)
    nt = number(p, "neck_top_mm", 55, upper=500)
    split = float(p.get("split_y_mm", 0))
    if not np.isfinite(split):
        raise ValueError(render("head_shell.split_coordinate_must_be_finite"))
    count = p.get("magnet_pairs", 4)
    if type(count) is not int or not 2 <= count <= 8:
        raise ValueError(render("head_shell.magnet_pairs_range"))
    body_index = p.get("body_component", int(np.argmax([m.volume for m in parts])))
    if type(body_index) is not int or not 0 <= body_index < len(parts):
        raise ValueError(render("head_shell.invalid_body_index"))
    body = solid(parts[body_index])
    src = [solid(m) for m in parts]
    if not body.bounding_box()[1] + gap < split < body.bounding_box()[4] - gap:
        raise ValueError(render("head_shell.split_must_cross_body"))
    print("生成保外形内腔", flush=True)
    cavity, erosion = eroded_cavity(parts, wall, pitch)
    neck = cyl(1, -5, nt).scale([nw / 2, nd / 2, 1])
    if overlap(cavity, neck) < 1:
        raise ValueError(render("head_shell.neck_not_connected_to_cavity"))
    cuts = [cavity, neck]
    vision_features = {}
    if p.get("smile_vents"):
        from studio.core.head_shell_vision import smile_vents

        vent_cut, vision_features["smile_vents"] = smile_vents(p["smile_vents"])
        if overlap(vent_cut, cavity) < 1:
            raise ValueError(render("head_shell.mouth_slit_not_connected_to_cavity"))
        cuts.append(vent_cut)
    ports = p.get("ports", [])
    for port in ports:
        center = finite_vector(port["center_mm"], 3, render("head_shell.name_port_center"))
        width, height = finite_vector(port["size_mm"], 2, render("head_shell.name_port_size"))
        if min(width, height) <= 0:
            raise ValueError(render("head_shell.port_size_must_be_positive"))
        cuts.append(
            cylinder_y(1, -2000, split, center[0], center[2])
            .scale([width / 2, 1, height / 2])
            .translate([center[0] * (1 - width / 2), 0, center[2] * (1 - height / 2)])
        )
    cutter = union(cuts)
    names = p.get("component_names", {})
    colors = p.get("component_colors", {})
    if (names or colors) and p.get("source_sha256") != info["source_sha256"]:
        raise ValueError(render("head_shell.component_names_require_source_sha"))
    preserve = p.get("preserve_components", True)
    if type(preserve) is not bool:
        raise ValueError(render("head_shell.preserve_components_must_be_bool"))
    discarded = {}
    # Source decorative objects may overlap the body (this is not a ready kit).
    # Explicit priority assigns overlapping volume to the smaller original part.
    decorative = []
    insert_cutters = []
    eye_apertures = []
    eye_frames = {}
    eye_configs = p.get("mesh_eyes", {})
    preserve_outline = p.get("preserve_eye_outline", True)
    if type(preserve_outline) is not bool:
        raise ValueError(render("head_shell.preserve_eye_outline_must_be_bool"))
    if eye_configs and (not preserve or p.get("source_sha256") != info["source_sha256"]):
        raise ValueError(render("head_shell.mesh_eyes_require_preserve_and_sha"))
    if not isinstance(eye_configs, dict) or any(
        k not in [str(i) for i in range(len(src)) if i != body_index] for k in eye_configs
    ):
        raise ValueError(render("head_shell.mesh_eyes_invalid_component_index"))
    if any(not isinstance(c, dict) for c in eye_configs.values()):
        raise ValueError(render("head_shell.mesh_eyes_params_must_be_object"))
    if preserve_outline and any("extension_outline_xz_mm" in c for c in eye_configs.values()):
        raise ValueError(render("head_shell.eye_outline_protected_no_extension"))
    if preserve:
        for i in sorted((i for i in range(len(src)) if i != body_index), key=lambda i: parts[i].volume):
            eye_source = src[i]
            extension = None
            config = eye_configs.get(str(i), {})
            if "extension_outline_xz_mm" in config:
                from studio.core.head_shell_vision import extension_outline, prism

                extension = extension_outline(config)
                # Reassign only the declared patch of source face to the black
                # removable eye insert. Source face geometry is retained.
                # Materialise this shared operand before it is reused by both
                # cavity and translated-skin booleans. A deferred native CSG
                # tree combining those branches crashes on this curved case.
                eye_source = solid(mesh(eye_source + (body ^ prism(extension))))
            part = eye_source - cutter
            if insert_cutters:
                part = part - union(insert_cutters)
            if extension is not None:
                part = solid(mesh(part))
            if str(i) in eye_configs:
                from studio.core.head_shell_vision import eye_screen

                config = eye_configs[str(i)]
                protected_ids = config.get("protected_components", [])
                if any(type(j) is not int or j == i or not 0 <= j < len(src) for j in protected_ids):
                    raise ValueError(render("head_shell.highlight_protected_component_invalid"))
                part, opening, frame, body_opening, eye_report = eye_screen(
                    part, eye_source, [src[j] for j in protected_ids], config
                )
                # Highlight support belongs to the removable black insert.
                # Keeping its projected island in the host severs tiny pieces
                # of yellow shell behind the highlight's clearance socket.
                eye_apertures.append(body_opening)
                eye_frames[i] = frame
                vision_features.setdefault("mesh_eyes", {})[str(i)] = eye_report
            if part.volume() <= 1e-5:
                raise ValueError(render("head_shell.cavity_removes_component", i=i))
            part, lost = main_component(part, render("head_shell.name_decorative_part", i=i))
            discarded[str(i)] = lost
            decorative.append((i, part))
            insert_tool = clearance_cutter(src[i], insert_gap, i in p.get("convex_socket_components", []))
            if extension is not None:
                insert_tool = insert_tool + prism(extension.buffer(insert_gap))
            direction = p.get("insertion_directions", {}).get(str(i))
            if direction is not None:
                d = finite_vector(direction, 3, render("head_shell.name_insertion_direction"))
                if np.linalg.norm(d) < 1e-8:
                    raise ValueError(render("head_shell.insertion_axis_cannot_be_zero"))
                d /= np.linalg.norm(d)
                travel = number(p, "insertion_travel_mm", 150, upper=500)
                # Deliberately remove an explicitly chosen convex swept socket;
                # this changes the mating interface, never the colour insert.
                vertices = mesh(insert_tool).vertices
                insert_tool = solid(trimesh.convex.convex_hull(np.vstack([vertices, vertices + d * travel])))
            insert_cutters.append(insert_tool)
        base = (body - cutter) - union(insert_cutters) if decorative else body - cutter
        if eye_apertures:
            base = base - union(eye_apertures)
    else:
        base = union(src) - cutter
    print("加工接缝与磁铁座", flush=True)
    pad_r = (md + mc) / 2 + 2.2
    pad_depth = mt + mc + 2
    sites = p.get("magnet_sites_xz_mm")
    if sites is None:
        sites = magnet_sites(body, split, pad_r, pad_depth, count, nt)
    else:
        sites = np.asarray(sites, float)
        if sites.shape != (count, 2) or not np.isfinite(sites).all():
            raise ValueError(render("head_shell.magnet_site_count_mismatch"))
    bosses = []
    for x, z in sites:
        envelope = cylinder_y(pad_r + 0.5, split - pad_depth - 0.5, split + pad_depth + 0.5, x, z)
        if (envelope - body).volume() > 1e-4:
            raise ValueError(render("head_shell.magnet_site_exposed"))
        bosses.append(cylinder_y(pad_r, split - pad_depth, split + pad_depth, x, z))
    combined = base + union(bosses)
    back, _ = combined.split_by_plane([0, 1, 0], split + gap / 2)
    _, front = combined.split_by_plane([0, 1, 0], split - gap / 2)
    holes = []
    for x, z in sites:
        holes.extend(
            [
                cylinder_y((md + mc) / 2, split - gap / 2 - mt - mc, split - gap / 2 + 0.1, x, z),
                cylinder_y((md + mc) / 2, split + gap / 2 - 0.1, split + gap / 2 + mt + mc, x, z),
            ]
        )
    hole_union = union(holes)
    front = front - hole_union
    back = back - hole_union
    front, discarded["front"] = main_component(front, render("head_shell.name_front_shell"))
    back, discarded["back"] = main_component(back, render("head_shell.name_back_shell"))
    pieces = {"front_shell": front, "back_shell": back}
    palette = {
        "front_shell": colors.get(str(body_index), "#f4c63c"),
        "back_shell": colors.get(str(body_index), "#f4c63c"),
    }
    for i, s in decorative:
        name = names.get(str(i), f"component_{i:02d}")
        if not isinstance(name, str) or not re.fullmatch("[A-Za-z0-9_-]{1,64}", name) or name in pieces:
            raise ValueError(render("head_shell.component_name_must_be_ascii_unique"))
        pieces[name] = s
        palette[name] = colors.get(str(i), "#888888")
    print("核验实际零件和装合路径", flush=True)
    collisions = {}
    for i, a in enumerate(pieces):
        for b in list(pieces)[i + 1 :]:
            v = overlap(pieces[a], pieces[b])
            if v > 1e-4:
                collisions[a + "/" + b] = v
    if collisions:
        raise ValueError(render("head_shell.parts_intersect", collisions=collisions))
    insert_gaps = {}
    for i, s in decorative:
        name = names.get(str(i), f"component_{i:02d}")
        distance = min(s.min_gap(other, insert_gap * 2) for n, other in pieces.items() if n != name)
        insert_gaps[name] = float(distance)
        if distance < insert_gap * 0.4:
            raise ValueError(
                render("head_shell.decorative_clearance_insufficient", name=name, distance=f"{distance:.4f}")
            )
    path_samples = []
    for distance in np.linspace(0, max(info["output_extents_mm"]), 31):
        v = overlap(front, back.translate([0, float(distance), 0]))
        path_samples.append({"translation_y_mm": float(distance), "overlap_mm3": v})
    if any(r["overlap_mm3"] > 1e-4 for r in path_samples):
        raise ValueError(render("head_shell.shell_insertion_path_interferes"))
    head_check = {"status": "not_measured", "note": render("head_shell.check_head_fit_note_not_measured")}
    if "head_envelope_mm" in p or "head_circumference_mm" in p:
        dims = head_envelope(p)
        center = finite_vector(
            p.get("head_center_mm", [0, 8, dims[2] / 2 + 15]), 3, render("head_shell.name_head_envelope_center")
        )
        if (dims <= 0).any():
            raise ValueError(render("head_shell.head_envelope_dims_must_be_positive"))
        head = mf.Manifold.sphere(1, 64).scale(dims / 2).translate(center)
        volumes = {name: overlap(head, s) for name, s in pieces.items()}
        head_check = {
            "status": "clear" if max(volumes.values()) < 1e-4 else "interference",
            "shape": "declared ellipsoid only",
            "dimensions_mm": dims.tolist(),
            "center_mm": center.tolist(),
            "circumference_mm": p.get("head_circumference_mm"),
            "depth_width_ratio": p.get("head_depth_width_ratio", 1.2),
            "padding_mm": p.get("padding_mm", 10),
            "overlap_mm3": volumes,
            "note": render("head_shell.check_head_fit_note_measured"),
        }
    meshes = {name: color_mesh(s, palette[name]) for name, s in pieces.items()}
    report = {
        "schema": "shell-kit/v1",
        **info,
        "params": p,
        "units": "mm",
        "up": "z",
        "front": "-y",
        "erosion": erosion,
        "vision_features": vision_features,
        "neck": {"width_mm": nw, "depth_mm": nd, "top_mm": nt, "connected_to_cavity": True},
        "magnet": {
            "pairs": count,
            "magnet_count": 2 * count,
            "diameter_mm": md,
            "thickness_mm": mt,
            "hole_diameter_mm": md + mc,
            "hole_depth_mm": mt + mc,
            "sites_xz_mm": sites.tolist(),
            "boss_radius_mm": pad_r,
            "boss_depth_mm": pad_depth,
            "retention": "胶固定，极性需成对确认；未测保持力",
        },
        "discarded_numerical_volume_mm3": discarded,
        "static_collisions": collisions,
        "insert_clearance": {
            "requested_mm": insert_gap,
            "measured_min_gap_mm": insert_gaps,
            "method": "源闭合部件有界法向偏移切槽，包含性检查和全件对最小间隙",
        },
        "shell_insertion_samples": path_samples,
        "head_fit": head_check,
        "parts": [
            {
                "name": n,
                "volume_mm3": float(m.volume),
                "faces": len(m.faces),
                "extents_mm": m.extents.tolist(),
                "color": palette[n],
                "watertight": bool(m.is_volume),
            }
            for n, m in meshes.items()
        ],
        "limitations": [
            "可调设计样稿，未实打或真人试戴",
            "内壁为采样近似，未证明全局最小壁厚",
            "分色安装面留有余量，胶装前须做配合试片或校准",
            "未验证头部视线、衬垫和通风量",
            "前后壳路径仅离散平移采样；分色件装入方向另验",
            "大于打印床的半壳仍需打印分块",
        ],
        "exterior": "保留源三角面；接缝、颈口、显式通孔和分色安装界面除外",
        "color_provenance": "用户/AI 明确部件计划；STL 不含可恢复的原始颜色值",
    }
    deliver(meshes, out, report)
    for name, m in meshes.items():
        read = trimesh.load_mesh(out / (name + ".stl"), process=True)
        if not read.is_volume or len(read.split()) != 1:
            raise ValueError(render("head_shell.stl_readback_not_single_watertight", name=name))
        if abs(read.volume - m.volume) > max(0.01, m.volume * 1e-5):
            raise ValueError(render("head_shell.stl_readback_volume_changed", name=name))
    # The cutter is a separate inspection asset, never included in printable BOM.
    inspect_dir = out / "inspection"
    inspect_dir.mkdir(exist_ok=True)
    source_dir = inspect_dir / "source-reference"
    source_dir.mkdir(exist_ok=True)
    deliver(
        {
            names.get(str(i), f"component_{i:02d}"): color_mesh(
                s, colors.get(str(i), "#f4c63c" if i == body_index else "#888888")
            )
            for i, s in enumerate(src)
        },
        source_dir,
        {"purpose": "同尺度来源外观参考，不加入打印 BOM"},
        stl=False,
    )
    deliver({"inner_void": color_mesh(cavity, "#74bed9")}, inspect_dir, {"purpose": "只读内腔证据，不打印"}, stl=False)
    if head_check["status"] != "not_measured":
        head_dir = inspect_dir / "head-fit"
        head_dir.mkdir(exist_ok=True)
        deliver({"head_envelope": color_mesh(head, "#74bed9")}, head_dir, head_check, stl=False)
    if eye_frames:
        # Structural visibility envelope, excluding only the fine lattice.
        # Kept separately from the printable assembly and labelled explicitly.
        open_meshes = dict(meshes)
        for i, frame in eye_frames.items():
            name = names.get(str(i), f"component_{i:02d}")
            open_meshes[name] = color_mesh(frame, palette[name])
        aperture_dir = inspect_dir / "without-eye-lattice"
        aperture_dir.mkdir(exist_ok=True)
        deliver(
            open_meshes,
            aperture_dir,
            {"purpose": "aperture-only visibility inspection, fine lattice omitted; not printable BOM"},
            stl=False,
        )
    write_json(out / "parameters.json", {"template": "shell-kit", "params": p, "source_sha256": info["source_sha256"]})
    from studio.core.head_shell_audit import audit

    assembly = audit(out, out / "audit")
    report["assembly"] = {
        "status": assembly["status"],
        "unresolved_parts": assembly["unresolved_parts"],
        "order": assembly["assembly_order"],
        "tested_collision_poses": assembly["tested_collision_poses"],
    }
    if eye_frames and p.get("eye_points_mm"):
        from studio.core.head_shell_sight import audit as sight_audit

        sight = sight_audit(out, inspect_dir / "sight", p["eye_points_mm"])
        report["sight"] = {
            "status": sight["status"],
            "declared_eye_points_mm": sight["declared_eye_points_mm"],
            "note": "provisional points; see inspection/sight/sight-verification.json",
        }
    report["workflow_checks"] = {
        "geometry": {
            "status": "pass" if assembly["status"] == "pass_sampled" else "warn",
            "detail": render(
                "head_shell.check_geometry_detail_pass"
                if assembly["status"] == "pass_sampled"
                else "head_shell.check_geometry_detail_needs_review",
                count=len(meshes),
            ),
        },
        "head_fit": {
            "status": "pass" if head_check["status"] == "clear" else "warn",
            "detail": render(
                "head_shell.check_head_fit_detail_clear"
                if head_check["status"] == "clear"
                else "head_shell.check_head_fit_detail_unclear"
            ),
        },
        "sight": {
            "status": "pass" if report.get("sight", {}).get("status") == "sampled_forward_clear" else "warn",
            "detail": render(
                "head_shell.check_sight_detail_clear"
                if report.get("sight", {}).get("status") == "sampled_forward_clear"
                else "head_shell.check_sight_detail_blocked"
            ),
        },
        "physical_fit": {"status": "todo", "detail": render("head_shell.check_physical_fit_detail_todo")},
    }
    report["wearable_ready"] = False
    write_json(out / "report.json", report)
    print(
        json.dumps({"parts": len(meshes), "head_fit": head_check, "magnet": report["magnet"]}, ensure_ascii=False),
        flush=True,
    )


OPERATIONS = {"shell-kit": head_shell}

# Compatibility alias: task scripts saved on disk before this module was
# renamed from `studio.shell_kit` (see `studio/core/task_bootstrap.py`'s
# `_LEGACY_MODULE_MAP`) call `shell_kit(workbench)` by name; `Tasks.resume`
# re-runs those scripts byte-for-byte, forever, so the old name must keep
# resolving to the same function.
shell_kit = head_shell
