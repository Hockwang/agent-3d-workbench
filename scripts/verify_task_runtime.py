"""Portable local integration checks. No network calls or printer submission.
Run with uv run --frozen python scripts/verify_task_runtime.py --out /absolute/new/directory
"""

import argparse
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
import trimesh
from PIL import Image
from studio.core.tasks import Tasks


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    root = args.out.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=False)
    inputs = root / "inputs"
    inputs.mkdir()
    tasks = Tasks(root / "tasks")
    results = []

    def run(template, params=None, files=(), preview=False):
        task = tasks.start(
            {
                "template": template,
                "params": params or {},
                "inputs": [str(x) for x in files],
                "render_preview": preview,
                "timeout_seconds": 600,
            },
            "ai",
        )["task"]
        while task["status"] in ("queued", "running", "cancelling"):
            time.sleep(0.25)
            task = tasks.state(task["id"], True)
        results.append(task)
        (root / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2))
        print(template, task["status"], round(task["elapsed_seconds"], 2), flush=True)
        if task["status"] != "completed":
            raise RuntimeError(task.get("log", task.get("error")))
        return {a["name"]: Path(a["path"]) for a in task["artifacts"]}

    sphere = inputs / "sphere.glb"
    small = inputs / "template.glb"
    for path, radius, subdivisions in [(sphere, 0.03, 3), (small, 0.025, 1)]:
        path.write_bytes(
            trimesh.Scene(trimesh.creation.icosphere(subdivisions=subdivisions, radius=radius)).export(file_type="glb")
        )
    height = inputs / "height.png"
    Image.fromarray(np.tile(np.linspace(0, 255, 32, dtype=np.uint8), (32, 1))).save(height)
    a = run("image-relief", files=[height])
    assert trimesh.load(a["relief.stl"], force="mesh").is_volume
    a = run("cad-model")
    assert json.loads(a["report.json"].read_text())["watertight"]
    a = run("joint-coupon")
    assert all(trimesh.load(path, force="mesh").is_volume for name, path in a.items() if name.endswith(".stl"))
    a = run("laser-slices", {"layer_mm": 10}, [sphere])
    assert json.loads(a["layers.json"].read_text())["layers"]
    a = run("container", {"resolution": 256, "samples": 4}, preview=True)
    assert Image.open(a["preview.png"]).size == (256, 256)
    a = run("hinge")
    hinge = a["scene.glb"]
    from studio.core.task_operations import glb_data

    assert len(glb_data(hinge)[1]["animations"]) == 1
    a = run("interactive-scene", {"hotspots": [{"label": "centre", "position": [0, 0.03, 0]}]}, [hinge])
    assert a["index.html"].stat().st_size > 100000
    for operation in ("smooth", "decimate", "solidify", "remesh", "uv"):
        a = run("mesh-process", {"operation": operation, "voxel_mm": 3}, [sphere])
        report = json.loads(a["report.json"].read_text())["objects"][0]
        if operation == "uv":
            assert report["uv_layers"] > 0
        if operation == "decimate":
            assert report["after_polygons"] < report["before_polygons"]
    a = run("surface-fit", files=[sphere, small])
    assert json.loads(a["report.json"].read_text())["topology_preserved"]
    a = run("local-sculpt", {"center_m": [0, 0, 0.025], "radius_mm": 10}, [sphere])
    assert json.loads(a["report.json"].read_text())["protected_vertices_unchanged"]
    a = run("hair-cards", {"guides": [{"points_m": [[0, 0, 0], [0, 0, 0.01], [0, 0.005, 0.02]], "width_mm": 4}]})
    assert json.loads(a["report.json"].read_text())["cards_quads"] == 2
    a = run("texture-bake", {"ratio": 0.5, "resolution": 256}, [sphere])
    assert len(list(a["scene.glb"].parent.glob("*.png"))) == 2
    print(f"{len(results)} tasks completed; numerical checks passed. Review images separately. Results: {root}")


if __name__ == "__main__":
    main()
