"""Explicit-palette, single-pull-direction solid color inlays."""

import itertools
import numpy as np
import manifold3d as mf
import trimesh
from studio.core import fabrication as f
from studio.core.kernels import mechanical_geometry as g


def extrude_patch(topology, faces, direction, depth):
    """Extrude shared patch topology, without unioning edge-touching prisms.

    Coplanar hull booleans can leave disconnected triangles at float32 GLB
    coordinates. A single boundary-stitched shell retains the source adjacency.
    """
    patch = topology.submesh([faces], append=True, repair=False)
    count = len(patch.vertices)
    edges = patch.edges
    _, first, occurrences = np.unique(np.sort(edges, axis=1), axis=0, return_index=True, return_counts=True)
    boundary = edges[first[occurrences == 1]]
    side_faces = []
    for a, b in boundary:
        side_faces.extend([[a, a + count, b + count], [a, b + count, b]])
    shell = trimesh.Trimesh(
        vertices=np.vstack([patch.vertices, patch.vertices - direction * depth]),
        faces=np.vstack([patch.faces, patch.faces[:, ::-1] + count, side_faces]),
        process=False,
    )
    return g.solid(shell)


def run(w):
    p = w["params"]
    objects, hashes = f.inputs(w, 1)
    mesh, source = next(iter(objects.values()))
    palette = np.asarray(p.get("palette_rgb", []), dtype=float)
    if (
        palette.ndim != 2
        or palette.shape[1:] != (3,)
        or not 2 <= len(palette) <= 8
        or not np.isfinite(palette).all()
        or np.any((palette < 0) | (palette > 255))
        or not np.all(palette == np.round(palette))
    ):
        f.invalid("palette_rgb")
    if len(np.unique(palette, axis=0)) != len(palette):
        f.invalid("palette_rgb duplicates")
    if mesh.visual.kind not in ("texture", "vertex", "face"):
        f.invalid("source colors or UV texture")
    if mesh.visual.kind == "texture":
        # TextureVisuals.to_color() returns detached vertex colors with no mesh
        # reference. Average against the actual face indices explicitly.
        rgba = np.asarray(mesh.visual.to_color().vertex_colors, dtype=float)[mesh.faces].mean(axis=1)
    else:
        rgba = np.asarray(mesh.visual.face_colors, dtype=float)
    if rgba.shape != (len(mesh.faces), 4) or np.any(rgba[:, 3] < 255):
        f.invalid("opaque face colors")
    distances = np.linalg.norm((rgba[:, None, :3] - palette[None, :, :]) / 255, axis=2)
    labels = distances.argmin(axis=1)
    threshold = f.scalar(p, "max_color_distance", 0.25, hi=np.sqrt(3))
    f.require(np.all(distances.min(axis=1) <= threshold), "palette_color_distance")
    direction = f.vector(p.get("pull_direction"), "pull_direction", True)
    depth = f.scalar(p, "depth_mm", 1.2)
    clearance = f.scalar(p, "clearance_mm", 0.15, hi=2)
    min_area = f.scalar(p, "min_patch_area_mm2", 4)
    cosine = f.scalar(p, "min_pull_cosine", 0.25, hi=1)
    selected = labels != 0
    f.require(selected.any() and selected.sum() <= 5000, "selected_face_count_1_to_5000")
    f.require(np.all(mesh.face_normals[selected] @ direction >= cosine), "outward_facing_color_patches")
    offsets = np.asarray(list(itertools.product((-clearance, clearance), repeat=3)))
    parts, pockets, colors, regions, paint = {}, [], {}, [], []
    # UV and color seams duplicate vertices in glTF. Build connectivity from
    # positions while retaining the source face order used for color evidence.
    vertices, inverse = np.unique(mesh.vertices, axis=0, return_inverse=True)
    topology = trimesh.Trimesh(vertices, inverse[mesh.faces], process=False)
    adjacency = topology.face_adjacency
    for label in range(1, len(palette)):
        faces = np.flatnonzero(labels == label)
        if not len(faces):
            continue
        edges = adjacency[np.all(np.isin(adjacency, faces), axis=1)]
        for group in trimesh.graph.connected_components(edges, nodes=faces, min_len=1):
            group = np.asarray(group, dtype=int)
            area = float(mesh.area_faces[group].sum())
            if area < min_area:
                paint.append({"palette_index": label, "area_mm2": area, "face_indices": group.tolist()})
                continue
            expanded = []
            for face in group:
                triangle = mesh.triangles[face]
                points = np.vstack([triangle, triangle - direction * depth])
                expanded.append(mf.Manifold.hull_points((points[:, None, :] + offsets[None, :, :]).reshape(-1, 3)))
            insert = extrude_patch(topology, group, direction, depth) ^ source
            pocket = g.union(expanded) ^ source
            f.checked_mesh(insert)
            name = f"color_{label:02d}_{len(parts):02d}"
            parts[name] = insert
            pockets.append(pocket)
            colors[name] = palette[label].astype(int).tolist()
            regions.append({"part": name, "palette_index": label, "area_mm2": area, "face_indices": group.tolist()})
    f.require(bool(parts), "no_manufacturable_color_regions")
    body = source - g.union(pockets)
    f.checked_mesh(body)
    solids = {"body": body, **parts}
    names = list(solids)
    for i, a in enumerate(names):
        for b in names[i + 1 :]:
            f.require(g.overlap(solids[a], solids[b]) < 1e-6, "inlay_rest_overlap")
    travel = float(mesh.extents.max() + depth + clearance)
    samples = []
    for name, insert in parts.items():
        for t in np.linspace(0, travel, 33):
            moved = insert.translate((direction * t).tolist())
            collisions = {other: g.overlap(moved, solid) for other, solid in solids.items() if other != name}
            samples.append({"part": name, "distance_mm": float(t), "overlap_mm3": sum(collisions.values())})
    f.require(all(s["overlap_mm3"] < 1e-6 for s in samples), "sampled_inlay_removal")
    colors["body"] = palette[0].astype(int).tolist()
    f.emit(
        w,
        solids,
        {
            "operation": "color-inlays",
            "status": "pass",
            "source_sha256": hashes,
            "palette_rgb": palette.astype(int).tolist(),
            "sampling": "UV vertex samples averaged per triangle; explicit palette nearest RGB",
            "max_observed_color_distance": float(distances.min(axis=1).max()),
            "pull_direction": direction.tolist(),
            "depth_mm": depth,
            "clearance_linf_mm": clearance,
            "regions": regions,
            "paint_only_regions": paint,
            "removal_samples": samples,
            "source_textures_preserved": False,
            "whole_body_min_wall_verified": False,
        },
        colors,
    )
