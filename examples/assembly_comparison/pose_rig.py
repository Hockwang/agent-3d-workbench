"""Blender-only common diagnostic motion. Does not edit rig geometry or weights.

blender --background --python pose_rig.py -- --model rig.glb --mapping joints.json
    --reference input.glb --out new-directory
Same source framing, world axes and semantic angles on both routes. This is a
small pose test, not a locomotion or anatomical-ground-truth evaluation.
"""

import argparse
import json
import math
from pathlib import Path
import sys

import bpy
import numpy as np
from mathutils import Quaternion, Vector

p = argparse.ArgumentParser()
for key in ("model", "mapping", "reference", "out"):
    p.add_argument("--" + key, type=Path, required=True)
p.add_argument("--animate", action="store_true", help="Also render the full 2.4-second pose diagnostic")
a = p.parse_args(sys.argv[sys.argv.index("--") + 1 :])
a.out.mkdir(parents=True, exist_ok=True)
if (a.out / "pose-test.glb").exists():
    raise RuntimeError("Refusing to overwrite a completed diagnostic output")


def clear():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)


def vertices(objects):
    deps = bpy.context.evaluated_depsgraph_get()
    rows = []
    for obj in objects:
        ev = obj.evaluated_get(deps)
        mesh = ev.to_mesh()
        rows.extend(tuple(ev.matrix_world @ v.co) for v in mesh.vertices)
        ev.to_mesh_clear()
    return np.array(rows)


clear()
bpy.ops.import_scene.gltf(filepath=str(a.reference.resolve()))
v = vertices([o for o in bpy.context.scene.objects if o.type == "MESH"])
center = Vector((v.min(0) + v.max(0)) / 2)
size = float(np.max(v.max(0) - v.min(0)))
clear()
bpy.ops.import_scene.gltf(filepath=str(a.model.resolve()))
rigs = [o for o in bpy.context.scene.objects if o.type == "ARMATURE"]
custom_shapes = {b.custom_shape for r in rigs for b in r.pose.bones if b.custom_shape is not None}
meshes = [o for o in bpy.context.scene.objects if o.type == "MESH" and o not in custom_shapes]
assert len(rigs) == 1, "Expected one rig"
rig = rigs[0]
mapping = json.loads(a.mapping.read_text())["mapping"]
probes = [
    ("front_left", "upper", (0, 1, 0), 15),
    ("hind_right", "upper", (0, 1, 0), -15),
    ("head", None, (0, 1, 0), -8),
    ("tail", None, (0, 0, 1), 12),
]
rest = vertices(meshes)
for bone in rig.pose.bones:
    bone.rotation_mode = "QUATERNION"
    bone.rotation_quaternion = Quaternion()
for semantic, member, axis, degrees in probes:
    name = mapping[semantic][member] if member else mapping[semantic]
    if isinstance(name, list):
        name = name[0]
    bone = rig.pose.bones[name]
    basis = (rig.matrix_world @ bone.bone.matrix_local).to_quaternion()
    local_axis = basis.inverted() @ Vector(axis)
    for frame, factor in [(1, 0), (21, 1), (41, -1), (61, 0)]:
        bone.rotation_quaternion = Quaternion(local_axis, math.radians(degrees) * factor)
        bone.keyframe_insert(data_path="rotation_quaternion", frame=frame, group=name)
scene = bpy.context.scene
scene.frame_start, scene.frame_end, scene.render.fps = 1, 61, 25
scene.render.engine = "CYCLES"
scene.cycles.samples = 16
scene.render.resolution_x, scene.render.resolution_y = 720, 600
scene.render.resolution_percentage = 100
scene.world.color = (0.22, 0.22, 0.22)
scene.view_settings.view_transform = "AgX"
for pos, power in [((2, -3, 4), 900), ((-3, 2, 3), 600)]:
    bpy.ops.object.light_add(type="AREA", location=center + Vector(pos) * size)
    o = bpy.context.object
    o.data.energy, o.data.size = power * size * size, size * 3
    o.rotation_euler = (center - o.location).to_track_quat("-Z", "Y").to_euler()
bpy.ops.object.camera_add()
cam = bpy.context.object
scene.camera = cam
cam.data.type, cam.data.ortho_scale = "ORTHO", size * 1.3
cam.location = center + Vector((0.4, -1.6, 0.6)).normalized() * size * 3
cam.rotation_euler = (center - cam.location).to_track_quat("-Z", "Y").to_euler()
report = {
    "purpose": "Shared small-angle pose diagnostic, not a walk or naturalness proof",
    "frames": [],
    "degrees": {x[0]: x[3] for x in probes},
    "framing": {"center": list(center), "ortho_scale": cam.data.ortho_scale},
    "display_alignment": "none; original world coordinates preserved",
}
for frame in [1, 21, 41]:
    scene.frame_set(frame)
    posed = vertices(meshes)
    assert posed.shape == rest.shape and np.isfinite(posed).all()
    disp = np.linalg.norm(posed - rest, axis=1)
    report["frames"].append(
        {
            "frame": frame,
            "max_displacement": float(disp.max()),
            "mean_displacement": float(disp.mean()),
            "bounds": [posed.min(0).tolist(), posed.max(0).tolist()],
        }
    )
    scene.render.filepath = str((a.out / f"pose-{frame:02d}.png").resolve())
    bpy.ops.render.render(write_still=True)
scene.frame_set(1)
bpy.ops.object.select_all(action="DESELECT")
rig.select_set(True)
for obj in meshes:
    obj.select_set(True)
bpy.context.view_layer.objects.active = rig
bpy.ops.export_scene.gltf(
    filepath=str((a.out / "pose-test.glb").resolve()),
    use_selection=True,
    export_animations=True,
    export_frame_range=True,
    export_force_sampling=True,
)
(a.out / "pose-report.json").write_text(json.dumps(report, indent=2))
print("COMMON_POSE_DIAGNOSTIC_COMPLETE")
if a.animate:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from render_sequence import render_sequence

    render_sequence(a.out, 2.4)
