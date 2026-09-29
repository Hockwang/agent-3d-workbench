"""Render a GLB's actual objects assembled/exploded with source-fixed framing.
Blender --background --python render_parts.py -- --model ... --reference ... --out ...
Display colors identify objects only; they are not semantic correspondence labels.
"""

import argparse
import json
from pathlib import Path
import sys

import bpy
import numpy as np
from mathutils import Vector

p = argparse.ArgumentParser()
for key in ("model", "reference", "out"):
    p.add_argument("--" + key, type=Path, required=True)
p.add_argument("--animate", action="store_true", help="Also render a 4-second display-only explosion cycle")
a = p.parse_args(sys.argv[sys.argv.index("--") + 1 :])
a.out.mkdir(parents=True, exist_ok=True)


def clear():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)


clear()
bpy.ops.import_scene.gltf(filepath=str(a.reference.resolve()))
v = np.array(
    [tuple(o.matrix_world @ x.co) for o in bpy.context.scene.objects if o.type == "MESH" for x in o.data.vertices]
)
center = Vector((v.min(0) + v.max(0)) / 2)
size = float(np.max(v.max(0) - v.min(0)))
clear()
bpy.ops.import_scene.gltf(filepath=str(a.model.resolve()))
objects = sorted([o for o in bpy.context.scene.objects if o.type == "MESH"], key=lambda o: o.name)
original_world = {o: o.matrix_world.copy() for o in objects}
report = {
    "display_only": True,
    "display_alignment": "none",
    "objects": [],
    "framing": {"center": list(center), "ortho_scale": size * 1.8},
}
colors = [
    (0.14, 0.43, 0.72, 1),
    (0.91, 0.49, 0.18, 1),
    (0.2, 0.65, 0.46, 1),
    (0.64, 0.36, 0.72, 1),
    (0.88, 0.73, 0.24, 1),
    (0.18, 0.69, 0.73, 1),
    (0.86, 0.35, 0.46, 1),
    (0.49, 0.54, 0.62, 1),
    (0.6, 0.66, 0.24, 1),
]
for i, o in enumerate(objects):
    m = bpy.data.materials.new("Object display color")
    m.diffuse_color = colors[i % len(colors)]
    m.use_nodes = True
    m.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = m.diffuse_color
    m.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = 0.65
    o.data.materials.clear()
    o.data.materials.append(m)
    for poly in o.data.polygons:
        poly.material_index = 0
    pts = np.array([tuple(o.matrix_world @ x.co) for x in o.data.vertices])
    centroid = Vector(pts.mean(0))
    report["objects"].append(
        {
            "name": o.name,
            "faces": len(o.data.polygons),
            "world_centroid": list(centroid),
            "explosion_world_offset": list((centroid - center) * 0.55),
        }
    )
scene = bpy.context.scene
scene.render.engine = "CYCLES"
scene.cycles.samples = 16
scene.render.resolution_x = 720
scene.render.resolution_y = 720
scene.render.resolution_percentage = 100
scene.world.color = (0.24, 0.24, 0.24)
scene.view_settings.view_transform = "AgX"
for pos, power in [((2, -3, 4), 800), ((-3, 2, 3), 600)]:
    bpy.ops.object.light_add(type="AREA", location=center + Vector(pos) * size)
    o = bpy.context.object
    o.data.energy = power * size * size
    o.data.size = size * 3
    o.rotation_euler = (center - o.location).to_track_quat("-Z", "Y").to_euler()
bpy.ops.object.camera_add()
cam = bpy.context.object
scene.camera = cam
cam.data.type = "ORTHO"
cam.data.ortho_scale = size * 1.8
cam.location = center + Vector((1.2, -2, 0.8)).normalized() * size * 3
cam.rotation_euler = (center - cam.location).to_track_quat("-Z", "Y").to_euler()
for mode in ["assembled", "exploded"]:
    for o, entry in zip(objects, report["objects"]):
        world_offset = Vector(entry["explosion_world_offset"]) if mode == "exploded" else Vector((0, 0, 0))
        # Offset in world space even when source nodes have parent transforms.
        matrix = o.matrix_world.copy()
        matrix.translation += world_offset
        o.matrix_world = matrix
    bpy.context.view_layer.update()
    scene.render.filepath = str((a.out / (mode + ".png")).resolve())
    bpy.ops.render.render(write_still=True)
(a.out / "display-report.json").write_text(json.dumps(report, indent=2))
print("COMMON_PARTS_RENDER_COMPLETE")
if a.animate:
    for frame, fraction in [(1, 0), (51, 1), (101, 0)]:
        for obj, entry in zip(objects, report["objects"], strict=True):
            matrix = original_world[obj].copy()
            matrix.translation += Vector(entry["explosion_world_offset"]) * fraction
            obj.matrix_world = matrix
            obj.keyframe_insert(data_path="location", frame=frame)
    scene.frame_start, scene.frame_end, scene.render.fps = 1, 101, 25
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from render_sequence import render_sequence

    render_sequence(a.out, 4.0, square=True)
