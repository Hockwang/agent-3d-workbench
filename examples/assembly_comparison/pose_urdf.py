"""Display a URDF's declared joint ranges; do not infer or repair joints.
Requires explicit URDF up axis. Same reference-grounded camera for both routes.
"""

import argparse
import json
import math
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

import bpy
from mathutils import Euler, Matrix, Vector

p = argparse.ArgumentParser()
for key in ("urdf", "reference", "out"):
    p.add_argument("--" + key, type=Path, required=True)
p.add_argument("--up", choices=["y", "z"], required=True)
p.add_argument("--reverse", action="store_true", help="Display upper-to-lower when that is the opening direction")
p.add_argument("--animate", action="store_true", help="Also render the full 4-second joint diagnostic")
a = p.parse_args(sys.argv[sys.argv.index("--") + 1 :])
a.out.mkdir(parents=True, exist_ok=True)
if (a.out / "joint-test.glb").exists():
    raise RuntimeError("Refusing to overwrite diagnostic")


def vec(s, default="0 0 0"):
    return [float(x) for x in (s or default).split()]


def origin(e):
    return (
        Matrix.Identity(4)
        if e is None
        else Matrix.Translation(Vector(vec(e.get("xyz")))) @ Euler(vec(e.get("rpy")), "XYZ").to_matrix().to_4x4()
    )


def clear():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)


clear()
bpy.ops.import_scene.gltf(filepath=str(a.reference.resolve()))
pts = [o.matrix_world @ v.co for o in bpy.context.scene.objects if o.type == "MESH" for v in o.data.vertices]
lo = Vector([min(v[k] for v in pts) for k in range(3)])
hi = Vector([max(v[k] for v in pts) for k in range(3)])
center = (lo + hi) / 2
center.z -= lo.z
size = max(hi - lo)
clear()
root = ET.parse(a.urdf).getroot()
joints = []
for j in root.findall("joint"):
    limit = j.find("limit")
    axis = j.find("axis")
    joints.append(
        {
            "name": j.get("name"),
            "type": j.get("type"),
            "parent": j.find("parent").get("link"),
            "child": j.find("child").get("link"),
            "origin": origin(j.find("origin")),
            "axis": Vector(vec(axis.get("xyz") if axis is not None else "1 0 0")),
            "lower": float(limit.get("lower", "0")) if limit is not None else 0.0,
            "upper": float(limit.get("upper", "0")) if limit is not None else 0.0,
        }
    )


def fk(fraction):
    children = {j["child"] for j in joints}
    world = {link.get("name"): Matrix.Identity(4) for link in root.findall("link") if link.get("name") not in children}
    pending = list(joints)
    while pending:
        done = []
        for j in pending:
            if j["parent"] not in world:
                continue
            q = j["lower"] + fraction * (j["upper"] - j["lower"])
            motion = Matrix.Identity(4)
            if j["type"] == "prismatic":
                motion = Matrix.Translation(j["axis"].normalized() * q)
            elif j["type"] in ["revolute", "continuous"]:
                motion = Matrix.Rotation(q, 4, j["axis"])
            world[j["child"]] = world[j["parent"]] @ j["origin"] @ motion
            done.append(j)
        assert done, "Unresolvable tree"
        for j in done:
            pending.remove(j)
    return world


meshes = []
for link in root.findall("link"):
    for visual in link.findall("visual"):
        element = visual.find("geometry/mesh")
        if element is None:
            continue
        path = (a.urdf.parent / element.get("filename")).resolve()
        before = set(bpy.data.objects)
        if path.suffix.lower() == ".obj":
            bpy.ops.wm.obj_import(filepath=str(path), forward_axis="Y", up_axis="Z")
        elif path.suffix.lower() in [".glb", ".gltf"]:
            bpy.ops.import_scene.gltf(filepath=str(path))
        else:
            raise ValueError("Unsupported mesh type")
        for o in set(bpy.data.objects) - before:
            if o.type != "MESH":
                continue
            local = o.matrix_world.copy()
            if path.suffix.lower() in [".glb", ".gltf"]:
                local = Matrix.Rotation(-math.pi / 2, 4, "X") @ local
            o.parent = None
            local = (
                origin(visual.find("origin"))
                @ Matrix.Diagonal(Vector((*vec(element.get("scale"), "1 1 1"), 1)))
                @ local
            )
            meshes.append((o, link.get("name"), local))
display = Matrix.Rotation(math.pi / 2, 4, "X") if a.up == "y" else Matrix.Identity(4)
for frame, fraction in [(1, 0), (26, 0.5), (51, 1), (101, 0)]:
    transforms = fk(1 - fraction if a.reverse else fraction)
    for o, name, local in meshes:
        o.matrix_world = display @ transforms[name] @ local
        o.rotation_mode = "QUATERNION"
        for key in ["location", "rotation_quaternion", "scale"]:
            o.keyframe_insert(data_path=key, frame=frame)
scene = bpy.context.scene
scene.frame_start = 1
scene.frame_end = 101
scene.render.fps = 25
scene.render.engine = "CYCLES"
scene.cycles.samples = 16
scene.render.resolution_x = 720
scene.render.resolution_y = 600
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
cam.data.ortho_scale = size * 1.45
cam.location = center + Vector((1.5, 2.5, 1.8)).normalized() * size * 3
cam.rotation_euler = (center - cam.location).to_track_quat("-Z", "Y").to_euler()
for frame in [1, 26, 51]:
    scene.frame_set(frame)
    scene.render.filepath = str((a.out / f"pose-{frame:02d}.png").resolve())
    bpy.ops.render.render(write_still=True)
scene.frame_set(1)
bpy.ops.object.select_all(action="DESELECT")
for o, _, _ in meshes:
    o.select_set(True)
bpy.ops.export_scene.gltf(
    filepath=str((a.out / "joint-test.glb").resolve()),
    use_selection=True,
    export_animations=True,
    export_frame_range=True,
    export_force_sampling=True,
)
report = {
    "urdf_up": a.up,
    "reverse_display_range": a.reverse,
    "framing": "reference bounds with ground shifted to Z=0; no output geometry alignment",
    "camera_center": list(center),
    "ortho_scale": cam.data.ortho_scale,
    "joints": [
        {k: v for k, v in j.items() if k in ["name", "type", "parent", "child", "lower", "upper"]} for j in joints
    ],
    "note": "Fractions follow declared limits; lower/upper do not establish real closure, collision freedom or simulation readiness.",
}
(a.out / "joint-report.json").write_text(json.dumps(report, indent=2))
print("COMMON_JOINT_DIAGNOSTIC_COMPLETE")
if a.animate:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from render_sequence import render_sequence

    render_sequence(a.out, 4.0)
