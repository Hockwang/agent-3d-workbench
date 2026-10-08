"""Blender subprocess worker for an approximate watertight cutting proxy.

Invocation: blender --background --factory-startup --python this-file --
            source.glb proxy.glb pitch_in_source_units target_triangles mode
The source file is read only. The Python caller verifies the exported mesh.
"""

import bmesh
import bpy
import json
import sys
import time
from pathlib import Path


def main():
    args = sys.argv[sys.argv.index("--") + 1 :]
    if len(args) not in (4, 5):
        raise ValueError("expected source, output, voxel pitch, face budget and mode")
    source, output = Path(args[0]), Path(args[1])
    pitch, target_faces = float(args[2]), int(args[3])
    # Keep an already-running API process using the original four-argument
    # worker contract functional while it is restarted with the new module.
    mode = args[4] if len(args) == 5 else "voxel"
    if not source.is_file() or pitch <= 0 or target_faces < 1000:
        raise ValueError("invalid voxel proxy input")
    if mode not in ("voxel", "solidify"):
        raise ValueError("unknown voxel proxy mode")
    started = time.perf_counter()
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(source))
    objects = [obj for obj in bpy.context.scene.objects if obj.type == "MESH" and len(obj.data.polygons)]
    if not objects:
        raise ValueError("GLB has no triangle mesh")
    bpy.ops.object.select_all(action="DESELECT")
    for obj in objects:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = objects[0]
    if len(objects) > 1:
        bpy.ops.object.join()
    obj = bpy.context.view_layer.objects.active
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
    if mode == "solidify":
        # A missing large surface or a zero-thickness sheet has no reliable
        # inside for voxel remesh. Make a shallow, explicitly approximate shell
        # and close its rims before voxelizing it.
        solidify = obj.modifiers.new("Approximate open surface thickness", "SOLIDIFY")
        solidify.thickness = pitch * 2.5
        solidify.offset = 0.0
        solidify.use_rim = True
        solidify.use_even_offset = True
        bpy.ops.object.modifier_apply(modifier=solidify.name)
    obj.data.remesh_voxel_size = pitch
    bpy.ops.object.voxel_remesh()
    voxel_faces = len(obj.data.polygons)
    if voxel_faces * 2 > target_faces:
        modifier = obj.modifiers.new("Limit proxy triangles", "DECIMATE")
        modifier.decimate_type = "COLLAPSE"
        modifier.ratio = min(1.0, target_faces / (voxel_faces * 2))
        bpy.ops.object.modifier_apply(modifier=modifier.name)
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bmesh.ops.triangulate(bm, faces=list(bm.faces))
    nonmanifold_edges = sum(1 for edge in bm.edges if not edge.is_manifold)
    volume = bm.calc_volume(signed=False)
    bm.to_mesh(obj.data)
    bm.free()
    obj.data.materials.clear()
    face_count = len(obj.data.polygons)
    print(
        "PROXY_METRICS "
        + json.dumps(
            dict(
                mode=mode,
                solidify_thickness_source_units=(pitch * 2.5 if mode == "solidify" else 0),
                voxel_faces=voxel_faces,
                faces=face_count,
                nonmanifold_edges=nonmanifold_edges,
                volume_source_units3=volume,
                duration_s=round(time.perf_counter() - started, 3),
            )
        ),
        flush=True,
    )
    if nonmanifold_edges or face_count > 250000 or volume <= 0:
        raise ValueError("voxel proxy did not produce a closed mesh within budget")
    bpy.ops.export_scene.gltf(filepath=str(output), export_format="GLB", export_apply=True)
    if not output.is_file() or output.stat().st_size < 80:
        raise RuntimeError("Blender did not export a GLB")


if __name__ == "__main__":
    main()
