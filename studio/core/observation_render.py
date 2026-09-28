"""Blender evidence renderer. Keep only one variant/pose resident at a time."""

import json
import os
from pathlib import Path
import sys
import bpy
from mathutils import Vector

config = json.loads(Path(sys.argv[-1]).read_text())
out = Path(config["output"])
(out / "snapshots").mkdir(exist_ok=True)


def load(item):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(out / item["model"]))
    scene = bpy.context.scene
    objects = list(scene.objects)
    widgets = {
        bone.custom_shape for arm in objects if arm.type == "ARMATURE" for bone in arm.pose.bones if bone.custom_shape
    }
    meshes = [obj for obj in objects if obj.type == "MESH" and obj not in widgets]
    actions = [obj.animation_data.action for obj in objects if obj.animation_data and obj.animation_data.action]
    first = min((a.frame_range[0] for a in actions), default=1)
    last = max((a.frame_range[1] for a in actions), default=1)
    frame = first + (last - first) * item["phase"] if item["animated"] else 1
    scene.frame_set(int(frame), subframe=frame - int(frame))
    for obj in objects:
        obj.hide_render = obj in widgets or obj.type in ("LIGHT", "CAMERA")
    return scene, meshes, frame


all_points = []
sampled_frames = []
for item in config["renders"]:
    scene, meshes, frame = load(item)
    depsgraph = bpy.context.evaluated_depsgraph_get()
    for obj in meshes:
        evaluated = obj.evaluated_get(depsgraph)
        all_points.extend(evaluated.matrix_world @ Vector(c) for c in evaluated.bound_box)
    sampled_frames.append({"variant": item["variant"], "phase": item["phase"], "frame": frame})
if not all_points:
    # Runs inside Blender without the studio package on sys.path, so the message
    # cannot come from studio.i18n; pick the language from the inherited env.
    _zh = os.environ.get("STUDIO_LANG", "").lower().replace("_", "-").startswith("zh")
    raise ValueError("没有可渲染几何" if _zh else "No renderable geometry")
lo = Vector([min(p[i] for p in all_points) for i in range(3)])
hi = Vector([max(p[i] for p in all_points) for i in range(3)])
center, size = (lo + hi) / 2, max((hi - lo).length, 0.001)
# Canonical glTF Y-up directions mapped into Blender Z-up.
directions = {
    "front": (0, -1, 0),
    "back": (0, 1, 0),
    "right": (1, 0, 0),
    "left": (-1, 0, 0),
    "top": (0, 0, 1),
    "iso": (1, -1, 0.75),
}
for item in config["renders"]:
    scene, meshes, _ = load(item)
    bpy.ops.object.camera_add()
    camera = bpy.context.object
    scene.camera = camera
    camera.data.type = "ORTHO"
    camera.data.ortho_scale = size * 1.15
    camera.data.clip_start = size / 10000
    camera.data.clip_end = size * 100
    for direction, strength in [((1, -2, 3), 2.5), ((-2, 1, 1), 1.3)]:
        bpy.ops.object.light_add(type="SUN")
        light = bpy.context.object
        light.data.energy = strength
        light.rotation_euler = Vector(direction).to_track_quat("Z", "Y").to_euler()
    scene.world = bpy.data.worlds.new("Observation world")
    scene.world.color = (0.12, 0.14, 0.17)
    scene.render.engine = "CYCLES"
    scene.cycles.samples = 8
    scene.render.resolution_x = scene.render.resolution_y = config["resolution"]
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.film_transparent = False
    scene.view_settings.view_transform = "Standard"
    for view in item["views"]:
        camera.location = center + Vector(directions[view]).normalized() * size * 3
        camera.rotation_euler = (center - camera.location).to_track_quat("-Z", "Y").to_euler()
        scene.render.filepath = str(out / f"views/v{item['variant']:02d}-p{item['phase_index']:02d}-{view}.png")
        bpy.ops.render.render(write_still=True)
    # Freeze the same evaluated pose shown in the PNG for the human's 3D preview.
    # Skinning/morphs are evaluated, not mistaken for a static bind-pose mesh.
    depsgraph = bpy.context.evaluated_depsgraph_get()
    bpy.ops.object.select_all(action="DESELECT")
    for obj in meshes:
        evaluated = obj.evaluated_get(depsgraph)
        mesh = bpy.data.meshes.new_from_object(evaluated, preserve_all_data_layers=True, depsgraph=depsgraph)
        snapshot = bpy.data.objects.new(obj.name + "_snapshot", mesh)
        scene.collection.objects.link(snapshot)
        snapshot.matrix_world = evaluated.matrix_world.copy()
        snapshot.select_set(True)
    bpy.ops.export_scene.gltf(
        filepath=str(out / item["model"].replace("models/", "snapshots/")),
        export_format="GLB",
        use_selection=True,
        export_animations=False,
        export_skins=False,
    )
(out / "camera.json").write_text(
    json.dumps(
        {
            "type": "orthographic",
            "shared": True,
            "center_m": [center.x, center.z, -center.y],
            "diameter_m": size,
            "ortho_scale_m": size * 1.15,
            "coordinate_system": "y-up",
            "variant_alignment": "source coordinates, no automatic normalization",
            "sampled_frames": sampled_frames,
        }
    )
)
