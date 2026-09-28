"""Agent-authored local reconstruction of the shared cup image, in mm/Z-up.

Run as a Python studio_task script, with the reference PNG in workbench['inputs'].
Dimensions and concealed cavity are design assumptions, not measured image truth.
This is a visual four-part model, not an engineered drinking vessel or joint kit.
"""

import hashlib
import json
from pathlib import Path
import time

import numpy as np
from scipy.interpolate import make_interp_spline
import trimesh
from trimesh.visual.material import PBRMaterial


def bezier(points, steps=16):
    p = np.asarray(points, float)
    t = np.linspace(0, 1, steps)[:, None]
    return ((1 - t) ** 3 * p[0] + 3 * (1 - t) ** 2 * t * p[1] + 3 * (1 - t) * t**2 * p[2] + t**3 * p[3]).tolist()


def lathe(profile):
    mesh = trimesh.creation.revolve(np.asarray(profile), sections=160)
    mesh.merge_vertices()
    mesh.fix_normals()
    assert mesh.is_volume
    return mesh


def handle_mesh():
    control = np.array(
        [[40, 0, 73], [52, 0, 76], [66, 0, 68], [72, 0, 51], [67, 0, 33], [54, 0, 23], [40, 0, 23]], float
    )
    spline = make_interp_spline(np.linspace(0, 1, len(control)), control, k=3)
    t = np.linspace(0, 1, 100)
    centers, tangent = spline(t), spline(t, 1)
    tangent /= np.linalg.norm(tangent, axis=1)[:, None]
    normal = np.column_stack([-tangent[:, 2], np.zeros(len(t)), tangent[:, 0]])
    angle = np.linspace(0, 2 * np.pi, 32, endpoint=False)
    vertices = (
        (
            centers[:, None, :]
            + 6 * np.cos(angle)[None, :, None] * normal[:, None, :]
            + 6 * np.sin(angle)[None, :, None] * np.array([0, 1, 0])
        )
        .reshape(-1, 3)
        .tolist()
    )
    faces = []
    for ring in range(len(t) - 1):
        for j in range(32):
            a, b = ring * 32 + j, ring * 32 + (j + 1) % 32
            faces.extend([[a, b, a + 32], [b, b + 32, a + 32]])
    for ring, center in [(0, centers[0]), (len(t) - 1, centers[-1])]:
        index = len(vertices)
        vertices.append(center.tolist())
        for j in range(32):
            faces.append([index, ring * 32 + j, ring * 32 + (j + 1) % 32])
    mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=True)
    mesh.fix_normals()
    assert mesh.is_volume
    return mesh


def build():
    outer = [[0, 0], [31, 0]] + bezier([[31, 0], [41, 0], [44, 4], [44, 15]])[1:]
    outer += bezier([[44, 15], [44, 40], [44, 78], [43.5, 90]])[1:]
    inner = [[39.5, 90], [40, 16]] + bezier([[40, 16], [40, 7], [37, 5], [31, 5]])[1:]
    body = lathe(outer + inner + [[0, 5]])
    filled = lathe(outer + [[0, 90]])
    # Trim contact surfaces against the outside of the body. No hidden handle
    # geometry protrudes into the cavity; no latch/glue strength is assumed.
    handle = trimesh.boolean.difference([handle_mesh(), filled], engine="manifold")
    lid_profile = [[0, 87.5], [38.4, 87.5], [38.4, 90.25], [43.6, 90.25]]
    lid_profile += bezier([[43.6, 90.25], [45.4, 90.5], [45.4, 93.8], [42.6, 94.6]])[1:]
    lid_profile += bezier([[42.6, 94.6], [30, 97], [12, 98], [0, 98]])[1:]
    lid = lathe(lid_profile)
    knob = lathe(
        [[0, 97.8], [5.8, 97.8], [6, 100]]
        + bezier([[6, 100], [7, 102], [10, 104], [10, 108]])[1:]
        + bezier([[10, 108], [10, 112.5], [7, 114], [0, 114]])[1:]
    )
    return {"body": body, "handle": handle, "lid": lid, "knob": knob}


def main(workbench):
    started = time.monotonic()
    output = Path(workbench["output"])
    p = workbench["params"]
    sx = float(p.get("body_diameter_mm", 88)) / 88
    sz = float(p.get("body_height_mm", 90)) / 90
    if not 0.5 <= min(sx, sz) <= max(sx, sz) <= 2:
        raise ValueError("Demo scale outside supported range")
    parts = build()
    scenes = {"assembled": trimesh.Scene(), "exploded": trimesh.Scene()}
    offsets = {"body": [0, 0, 0], "handle": [35, 0, 0], "lid": [0, 0, 25], "knob": [0, 0, 48]}
    report = []
    conversion = np.array([[0.001, 0, 0, 0], [0, 0, 0.001, 0], [0, -0.001, 0, 0], [0, 0, 0, 1]])
    for name, mesh in parts.items():
        mesh.apply_scale([sx, sx, sz])
        assert mesh.is_watertight and mesh.is_volume and len(mesh.split()) == 1, name
        mesh.export(output / (name + ".stl"))
        color = [144, 155, 125, 255] if name in ("body", "handle") else [237, 230, 210, 255]
        mesh.visual = trimesh.visual.TextureVisuals(
            material=PBRMaterial(name=name + "_ceramic", baseColorFactor=color, roughnessFactor=0.65, metallicFactor=0)
        )
        for kind, scene in scenes.items():
            copy = mesh.copy()
            if kind == "exploded":
                copy.apply_translation(np.array(offsets[name]) * [sx, sx, sz])
            copy.apply_transform(conversion)
            scene.add_geometry(copy, geom_name=name, node_name=name)
        report.append(
            {
                "name": name,
                "faces": len(mesh.faces),
                "extents_mm": mesh.extents.tolist(),
                "watertight": bool(mesh.is_watertight),
                "volume_mm3": float(mesh.volume),
            }
        )
    scenes["assembled"].export(output / "scene.glb", include_normals=True)
    scenes["exploded"].export(output / "exploded.glb", include_normals=True)
    reference = Path(workbench["inputs"][0])
    (output / "report.json").write_text(
        json.dumps(
            {
                "status": "pass",
                "route": "Codex authored Python / local execution",
                "generation_api_calls": 0,
                "reference_sha256": hashlib.sha256(reference.read_bytes()).hexdigest(),
                "assumptions": {
                    "body_diameter_mm": 88 * sx,
                    "body_height_mm": 90 * sz,
                    "cavity": "Invented constant-thickness inner profile; not visible in reference",
                    "manufacturing": "No retention, tolerance, food-contact or real-print validation",
                },
                "parts": report,
                "execution_seconds": round(time.monotonic() - started, 3),
                "agent_reasoning_time_included": False,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main(globals()["workbench"])
