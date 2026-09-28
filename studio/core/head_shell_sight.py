"""Ray tests of exported shell geometry at explicitly declared eye positions.

Angular samples are diagnostic geometry, not a human vision/comfort test.
Called by `studio.core.head_shell` at the end of the `shell-kit` task when
both an eye mesh and `eye_points_mm` are present; not a task template.
"""

from pathlib import Path
import hashlib

import numpy as np
import trimesh
import manifold3d as mf

from studio.i18n import render
from studio.core.task_operations import scene_input, deliver, write_json
from studio.core.kernels.mechanical_geometry import solid, mesh, cyl, frame, transform


def scene_mesh(path):
    scene = scene_input(Path(path))
    parts = {}
    for node in scene.graph.nodes_geometry:
        t, key = scene.graph[node]
        m = scene.geometry[key].copy()
        m.apply_transform(t)
        parts[node] = m
    return parts, trimesh.util.concatenate(list(parts.values()))


def rays_at(geometry, eye, directions):
    result = np.full(len(directions), np.inf)
    for start in range(0, len(directions), 32):
        ds = directions[start : start + 32]
        locations, ids, _ = geometry.ray.intersects_location(np.tile(eye, (len(ds), 1)), ds, multiple_hits=False)
        result[start + ids] = np.linalg.norm(locations - eye, axis=1)
    return result


def angular_directions(azimuths, elevations):
    pairs = np.array([(a, e) for e in elevations for a in azimuths])
    a, e = np.deg2rad(pairs).T
    return pairs, np.c_[np.sin(a) * np.cos(e), -np.cos(a) * np.cos(e), np.sin(e)]


def audit(folder, output, eyes):
    folder = Path(folder)
    out = Path(output)
    out.mkdir(parents=True, exist_ok=True)
    points = np.asarray(eyes, float)
    if points.shape != (2, 3) or not np.isfinite(points).all():
        raise ValueError(render("head_shell_sight.eye_points_required"))
    paths = {
        "actual_grid": folder / "scene.glb",
        "aperture_envelope": folder / "inspection/without-eye-lattice/scene.glb",
    }
    pairs, dirs = angular_directions(np.arange(-75, 76, 3), np.arange(-36, 37, 3))
    results = {}
    assembled = None
    geometry = None
    for label, path in paths.items():
        parts, m = scene_mesh(path)
        if label == "actual_grid":
            assembled = parts
            geometry = m
        eye_results = []
        for eye in points:
            print("视线采样", label, eye.tolist(), flush=True)
            distances = rays_at(m, eye, dirs)
            clear = ~np.isfinite(distances)
            direct = int(np.flatnonzero((pairs == [0, 0]).all(axis=1))[0])
            eye_results.append(
                {
                    "eye_mm": eye.tolist(),
                    "forward_clear": bool(clear[direct]),
                    "forward_first_hit_mm": None if clear[direct] else float(distances[direct]),
                    "clear_samples": int(clear.sum()),
                    "total_samples": len(clear),
                    "clear_angles_deg": pairs[clear].tolist(),
                }
            )
        results[label] = {"source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "eyes": eye_results}
    report = {
        "schema": "shell-sight-audit/v1",
        "declared_eye_points_mm": points.tolist(),
        "assumptions": "explicit provisional eye coordinates supplied by caller; not measured or inferred from circumference",
        "status_basis": "actual_grid including eye lattice",
        "front": "-Y",
        "azimuth_range_deg": [-75, 75],
        "elevation_range_deg": [-36, 36],
        "sample_step_deg": 3,
        "results": results,
        "status": "sampled_forward_clear"
        if all(x["forward_clear"] for x in results["actual_grid"]["eyes"])
        else "forward_blocked",
        "limitations": [
            "眼位是假定值；头围不能推导瞳距、眼高或前后位置",
            "离散射线，不是连续视野或真人试戴验证",
            "aperture_envelope 仅忽略细格栅，保留边框和高光；不能当成实际网片透视率",
        ],
    }
    write_json(out / "sight-verification.json", report)
    # Literal angular sample plot, independently of rendered outward appearance.
    svg = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="1060" height="610" viewBox="0 0 1060 610">',
        '<rect width="1060" height="610" fill="#14202a"/>',
        "<style>text{font-family:Arial;fill:#e4edf4;font-size:15px}</style>",
        '<text x="30" y="28">DECLARED EYE POINTS - geometric ray samples (green = clear; grey = blocked)</text>',
    ]
    for row, (label, data) in enumerate(results.items()):
        for col, er in enumerate(data["eyes"]):
            ox, oy = 40 + col * 525, 75 + row * 255
            svg.append(f'<text x="{ox}" y="{oy - 18}">{label} / {"left" if col == 0 else "right"} eye</text>')
            clear = {tuple(p) for p in er["clear_angles_deg"]}
            for a, e in pairs:
                x = ox + (a + 75) * 3
                y = oy + (36 - e) * 2.6
                color = "#5be1a0" if (a, e) in clear else "#394958"
                svg.append(f'<rect x="{x}" y="{y}" width="7" height="6" fill="{color}"/>')
            svg.append(
                f'<circle cx="{ox + 225 + 3.5}" cy="{oy + 36 * 2.6 + 3}" r="7" fill="none" stroke="#ffba62" stroke-width="2"/>'
            )
            svg.append(f'<text x="{ox}" y="{oy + 218}">azimuth -75 to +75 deg; orange circle = straight ahead</text>')
    svg.append(f'<text x="30" y="594">Eye points {points.tolist()}; provisional, no wearer validation.</text></svg>')
    (out / "sight-samples.svg").write_text("\n".join(svg))
    # A real cutaway with the right eye and its blocked forward ray.
    preview = {}
    for n, m in assembled.items():
        s = solid(m)
        positive, _ = s.split_by_plane([1, 0, 0], 0)
        if not positive.is_empty():
            cut = mesh(positive)
            cut.visual.face_colors = m.visual.main_color
            preview[n] = cut
    eye = points[1]
    ball = mesh(mf.Manifold.sphere(3, 24).translate(eye))
    ball.visual.face_colors = [70, 180, 250, 255]
    preview["declared_human_eye"] = ball
    _, ds = angular_directions([0, 30, 60], [0])
    distances = rays_at(geometry, eye, ds)
    for i, (d, dist) in enumerate(zip(ds, distances)):
        length = min(float(dist), 150)
        rod = mesh(transform(cyl(0.7, 0, max(0.1, length)), frame(d), eye))
        rod.visual.face_colors = [240, 80, 65, 255] if np.isfinite(dist) else [60, 210, 140, 255]
        preview[f"sight_ray_{i}"] = rod
    cutaway = out / "cutaway"
    cutaway.mkdir(exist_ok=True)
    deliver(preview, cutaway, {"purpose": "declared eye positions and ray blockers, inspection only"}, stl=False)
    print(report["status"], flush=True)
    return report
