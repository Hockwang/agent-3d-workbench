"""A GPT-authored CAD -> Blender -> editor example, with no generation service.

uv run --frozen python scripts/verify_local_first.py --out /absolute/new/directory
"""

import argparse
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from studio.core.tasks import Tasks

CAD = """
import cadquery as cq
import json, math
from pathlib import Path
import numpy as np
import trimesh
from studio.core.task_operations import deliver
out = Path(workbench['output'])
base = cq.Workplane('XY').box(80,40,4,centered=(True,True,False))
wall = cq.Workplane('XY').box(80,4,50,centered=(True,True,False)).translate((0,-18,0))
holes = cq.Workplane('XY').pushPoints([(-25,6),(25,6)]).circle(3).extrude(4)
body = base.union(wall).cut(holes)
assert body.val().isValid() and len(body.solids().vals()) == 1
cq.exporters.export(body,str(out/'bracket.step'))
cq.exporters.export(body,str(out/'bracket.stl'),tolerance=.01,angularTolerance=.05)
reloaded = cq.importers.importStep(str(out/'bracket.step'))
expected = 80*40*4 + 80*4*50 - 80*4*4 - 2*math.pi*3**2*4
assert abs(reloaded.val().Volume()-expected) < 1e-5
mesh = trimesh.load(out/'bracket.stl',force='mesh')
assert mesh.is_volume and mesh.euler_number == -2
assert np.allclose(mesh.extents,[80,40,50],atol=.001)
deliver({'bracket':mesh},out,{'generation_api_calls':0,'extents_mm':mesh.extents.tolist(),
    'hole_diameter_mm':6,'hole_center_spacing_mm':50,'wall_mm':4,
    'step_volume_mm3':reloaded.val().Volume(),'expected_volume_mm3':expected,
    'watertight':bool(mesh.is_watertight),'euler_number':int(mesh.euler_number)},stl=False)
"""

BLENDER = """
import bpy
from mathutils import Vector
bpy.ops.import_scene.gltf(filepath=workbench['inputs'][0])
for obj in bpy.context.scene.objects:
    if obj.type != 'MESH': continue
    material = bpy.data.materials.new('Brushed blue');material.diffuse_color=(.12,.3,.5,1)
    material.use_nodes=True
    shader=material.node_tree.nodes.get('Principled BSDF')
    shader.inputs['Base Color'].default_value=(.12,.3,.5,1)
    shader.inputs['Metallic'].default_value=.45;shader.inputs['Roughness'].default_value=.32
    obj.data.materials.clear();obj.data.materials.append(material)
bpy.ops.object.camera_add(location=(.14,.2,.13))
camera=bpy.context.object
camera.rotation_euler=(Vector((0,0,.025))-camera.location).to_track_quat('-Z','Y').to_euler()
camera.data.type='ORTHO';camera.data.ortho_scale=.13
bpy.context.scene.camera=camera
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    root = parser.parse_args().out.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=False)
    tasks = Tasks(root / "tasks")
    results = []

    def run(engine, script, inputs=()):
        task = tasks.start(
            {
                "title": "GPT 本机支架 · " + engine,
                "engine": engine,
                "script": script,
                "inputs": list(inputs),
                "params": {"resolution": 640, "samples": 16},
                "render_preview": True,
            },
            "ai",
        )["task"]
        while task["status"] in ("queued", "running", "cancelling"):
            time.sleep(0.25)
            task = tasks.state(task["id"], True)
        results.append(task)
        (root / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2))
        print(engine, task["status"], round(task["elapsed_seconds"], 2), flush=True)
        if task["status"] != "completed":
            raise RuntimeError(task.get("log", task.get("error")))
        return {a["name"]: a for a in task["artifacts"]}

    cad = run("python", CAD)
    render = run("blender", BLENDER, [cad["scene.glb"]["path"]])
    from studio.core.editor import Workspace

    editor = Workspace(root / "editor")
    result = editor.execute(
        {"action": "import", "params": {"files": [render["scene.glb"]["path"]]}, "expected_revision": 0}
    )
    (root / "editor-import.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print("Editor import verified. Preview:", render["preview.png"]["path"], flush=True)


if __name__ == "__main__":
    main()
