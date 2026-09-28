"""Blender render used for the API generation demo (no API calls).

blender -b --python examples/api_generation/render_model.py -- input.glb output.png [--reference]
The optional reference palette applies only to the repository's 5-part mug.
"""

import sys
from pathlib import Path

import bpy
from mathutils import Vector

args = sys.argv[sys.argv.index("--") + 1 :]
bpy.ops.object.select_all(action="SELECT")
bpy.ops.object.delete(use_global=False)
bpy.ops.import_scene.gltf(filepath=str(Path(args[0]).resolve()))
meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
if "--reference" in args:
    palette = {
        "body": (0.10, 0.50, 0.58, 1),
        "handle": (0.90, 0.48, 0.16, 1),
        "lid": (0.10, 0.30, 0.35, 1),
        "knob": (0.90, 0.48, 0.16, 1),
        "base": (0.20, 0.23, 0.24, 1),
    }
    for obj in meshes:
        mat = bpy.data.materials.new(obj.name)
        mat.diffuse_color = palette.get(obj.name, (0.3, 0.3, 0.3, 1))
        mat.use_nodes = True
        bsdf = mat.node_tree.nodes.get("Principled BSDF")
        bsdf.inputs["Base Color"].default_value = mat.diffuse_color
        bsdf.inputs["Roughness"].default_value = 0.45
        obj.data.materials.clear()
        obj.data.materials.append(mat)
points = [o.matrix_world @ Vector(c) for o in meshes for c in o.bound_box]
lo = Vector(tuple(min(p[i] for p in points) for i in range(3)))
hi = Vector(tuple(max(p[i] for p in points) for i in range(3)))
center, size = (lo + hi) / 2, max(hi - lo)
bpy.ops.object.camera_add(location=center + Vector((1.5, -2.4, 1.6)) * size)
camera = bpy.context.object
if "--comparison" in args:
    camera.location = center + Vector((0.7, -3, 1.25)) * size
camera.rotation_euler = (center - camera.location).to_track_quat("-Z", "Y").to_euler()
camera.data.type = "ORTHO"
camera.data.ortho_scale = size * 1.65
bpy.context.scene.camera = camera
for direction, power, width in [((2, -3, 5), 450, 4), ((-3, -1, 2), 150, 3), ((0, 3, 4), 250, 3)]:
    bpy.ops.object.light_add(type="AREA", location=center + Vector(direction) * size)
    light = bpy.context.object
    light.data.energy = power * size * size
    light.data.shape = "DISK"
    light.data.size = width * size
    light.rotation_euler = (center - light.location).to_track_quat("-Z", "Y").to_euler()
scene = bpy.context.scene
scene.world.color = (0.7, 0.7, 0.7)
scene.render.engine = "CYCLES"
scene.cycles.samples = 32
scene.render.resolution_x = 768
scene.render.resolution_y = 768
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = "PNG"
scene.view_settings.view_transform = "AgX" if "--comparison" in args else "Standard"
scene.render.filepath = str(Path(args[1]).resolve())
scene.render.film_transparent = False
bpy.ops.render.render(write_still=True)
