"""Reusable wrappers around Blender's supported modelling/animation operators."""

from pathlib import Path
import json
import math
import bpy
from mathutils import Matrix, Vector


def report(out, data):
    Path(out, "report.json").write_text(json.dumps(data, ensure_ascii=False, indent=2))


def select(obj):
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def weights(meshes, maximum=4, repair=False):
    unbound = 0
    largest_error = 0
    total = 0
    for obj in meshes:
        arm = next((m.object for m in obj.modifiers if m.type == "ARMATURE" and m.object), None)
        if arm is None:
            raise ValueError("Every mesh must have an armature modifier: " + obj.name)
        groups = {g.index: g for g in obj.vertex_groups if g.name in arm.data.bones}
        for vertex in obj.data.vertices:
            values = sorted(
                [(g.group, g.weight) for g in vertex.groups if g.group in groups and g.weight > 0], key=lambda x: -x[1]
            )
            if not values:
                unbound += 1
                continue
            if repair:
                values = values[:maximum]
                total_weight = sum(v for _, v in values)
                for g in groups.values():
                    g.remove([vertex.index])
                for index, value in values:
                    groups[index].add([vertex.index], value / total_weight, "REPLACE")
                values = [(i, v / total_weight) for i, v in values]
            largest_error = max(largest_error, abs(sum(v for _, v in values) - 1))
            total += 1
    if unbound:
        raise ValueError(f"{unbound} vertices have no bone weights; supply or repair their binding")
    return {
        "weighted_vertices": total,
        "unbound_vertices": unbound,
        "max_weight_sum_error": largest_error,
        "max_influences": maximum if repair else None,
    }


def run(name, context):
    w = context["workbench"]
    p = w["params"]
    out = Path(w["output"])
    load = context["load_inputs"]
    if name == "hair-cards":
        return hair_cards(w)
    if name == "motion-retarget":
        return retarget(w, load)
    meshes = load()
    if name == "scene-render":
        return
    if name == "turntable":
        frames = int(p.get("frames", 120))
        if not 2 <= frames <= 1800:
            raise ValueError("frames must be 2–1800")
        root = bpy.data.objects.new("Turntable", None)
        bpy.context.scene.collection.objects.link(root)
        for obj in list(bpy.context.scene.objects):
            if obj != root and obj.parent is None and obj.type not in ("CAMERA", "LIGHT"):
                world = obj.matrix_world.copy()
                obj.parent = root
                obj.matrix_world = world
        for frame, angle in [(1, 0), (frames, math.tau)]:
            root.rotation_euler.z = angle
            root.keyframe_insert(data_path="rotation_euler", frame=frame)
        bpy.context.scene.frame_end = frames
    elif name == "rig-bind":
        bones = p.get("bones")
        if not isinstance(bones, list) or not bones:
            raise ValueError("Supply bones: [{name, head:[x,y,z], tail:[x,y,z], parent:null/name}], in metres/Z-up")
        names = [x["name"] for x in bones]
        if len(set(names)) != len(names):
            raise ValueError("Bone names must be unique")
        arm_data = bpy.data.armatures.new("Rig")
        arm = bpy.data.objects.new("Rig", arm_data)
        bpy.context.collection.objects.link(arm)
        select(arm)
        bpy.ops.object.mode_set(mode="EDIT")
        for spec in bones:
            bone = arm_data.edit_bones.new(spec["name"])
            bone.head = spec["head"]
            bone.tail = spec["tail"]
            if (bone.tail - bone.head).length < 1e-6:
                raise ValueError("A bone has zero length")
        for spec in bones:
            if spec.get("parent"):
                arm_data.edit_bones[spec["name"]].parent = arm_data.edit_bones[spec["parent"]]
        bpy.ops.object.mode_set(mode="OBJECT")
        for obj in meshes:
            obj.select_set(True)
        bpy.context.view_layer.objects.active = arm
        bpy.ops.object.parent_set(type="ARMATURE_AUTO")
        report(out, {"operation": name, **weights(meshes)})
    elif name == "skin-weights":
        maximum = int(p.get("max_influences", 4))
        if not 1 <= maximum <= 8:
            raise ValueError("max_influences must be 1–8")
        report(out, {"operation": name, **weights(meshes, maximum, True)})
    elif name == "surface-fit":
        if len(meshes) != 2:
            raise ValueError("Supply exactly two meshes: source surface, then template")
        source, target = meshes
        before = len(target.data.vertices), len(target.data.polygons)
        select(target)
        mod = target.modifiers.new("Surface fit", "SHRINKWRAP")
        mod.target = source
        mod.wrap_method = "NEAREST_SURFACEPOINT"
        mod.offset = float(p.get("offset_mm", 0.1)) / 1000
        bpy.ops.object.modifier_apply(modifier=mod.name)
        if before != (len(target.data.vertices), len(target.data.polygons)):
            raise ValueError("Template topology changed")
        bpy.data.objects.remove(source, do_unlink=True)
        report(
            out,
            {
                "operation": name,
                "vertices": before[0],
                "polygons": before[1],
                "topology_preserved": True,
                "self_intersection_check": "not performed",
            },
        )
    elif name == "texture-bake":
        bake(meshes, p, out)
    elif name == "local-sculpt":
        local_sculpt(meshes, p, out)
    else:
        raise ValueError("Unknown Blender operation")


def local_sculpt(meshes, p, out):
    import numpy as np

    if len(meshes) != 1:
        raise ValueError("Local sculpt requires exactly one mesh")
    obj = meshes[0]
    original = np.array([v.co[:] for v in obj.data.vertices], float)
    center = np.asarray(p.get("center_m"), float)
    radius = float(p.get("radius_mm", 10)) / 1000
    iterations = int(p.get("iterations", 10))
    limit = float(p.get("max_displacement_mm", 1)) / 1000
    if (
        center.shape != (3,)
        or not np.isfinite(center).all()
        or not 0 < radius < 100
        or not 1 <= iterations <= 100
        or not 0 < limit <= radius
    ):
        raise ValueError("Supply finite center_m, positive radius/displacement and 1–100 iterations")
    matrix = np.asarray(obj.matrix_world)
    world = original @ matrix[:3, :3].T + matrix[:3, 3]
    distance = np.linalg.norm(world - center, axis=1)
    weight = np.maximum(0, 1 - distance / radius) ** 2
    if not np.any(weight):
        raise ValueError("Selected region contains no vertices")
    edges = np.array([e.vertices[:] for e in obj.data.edges], int)
    i = np.r_[edges[:, 0], edges[:, 1]]
    j = np.r_[edges[:, 1], edges[:, 0]]
    degree = np.bincount(i, minlength=len(world))
    positions = world.copy()
    for _ in range(iterations):
        for coefficient in (0.5, -0.53):
            sums = np.zeros_like(positions)
            np.add.at(sums, i, positions[j])
            delta = sums / np.maximum(degree[:, None], 1) - positions
            delta[degree == 0] = 0
            positions += coefficient * weight[:, None] * delta
            offset = positions - world
            length = np.linalg.norm(offset, axis=1)
            positions = world + offset * np.minimum(1, limit / np.maximum(length, 1e-15))[:, None]
    inverse = np.linalg.inv(matrix)
    local = positions @ inverse[:3, :3].T + inverse[:3, 3]
    # Restore exact original local positions outside the region, avoiding even
    # matrix inversion roundoff in protected vertices.
    local[weight == 0] = original[weight == 0]
    obj.data.vertices.foreach_set("co", local.ravel())
    obj.data.update()
    actual = np.asarray([v.co[:] for v in obj.data.vertices])
    delta = np.linalg.norm((actual - original) @ matrix[:3, :3].T, axis=1)
    report(
        out,
        {
            "operation": "local-sculpt",
            "vertices": len(original),
            "affected_vertices": int(np.count_nonzero(weight)),
            "protected_vertices_unchanged": bool(np.array_equal(actual[weight == 0], original[weight == 0])),
            "max_displacement_mm": float(delta.max() * 1000),
            "topology_and_uv": "unchanged",
            "identity_review": "requires visual review",
        },
    )


def hair_cards(w):
    p = w["params"]
    out = Path(w["output"])
    guides = p.get("guides")
    if not isinstance(guides, list) or not 1 <= len(guides) <= 2000:
        raise ValueError("Supply 1–2000 guides with points_m and width_mm")
    material = bpy.data.materials.new("Hair atlas")
    material.use_nodes = True
    bsdf = material.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (0.09, 0.035, 0.015, 1)
    images = [x for x in w["inputs"] if Path(x).suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")]
    if len(images) > 1:
        raise ValueError("Supply a single hair atlas image")
    if images:
        image = bpy.data.images.load(images[0])
        image.pack()
        tex = material.node_tree.nodes.new("ShaderNodeTexImage")
        tex.image = image
        material.node_tree.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
        material.node_tree.links.new(tex.outputs["Alpha"], bsdf.inputs["Alpha"])
    vertices = []
    faces = []
    uvs = []
    for guide in guides:
        points = [Vector(x) for x in guide.get("points_m", [])]
        width = float(guide.get("width_mm", 5)) / 1000
        atlas = guide.get("atlas_uv", [0, 0, 1, 1])
        if not 2 <= len(points) <= 1000 or not 0 < width < 1 or len(atlas) != 4:
            raise ValueError("Invalid guide length, width or atlas rectangle")
        if not all(len(x) == 3 and all(math.isfinite(v) for v in x) for x in points) or not all(
            math.isfinite(v) and 0 <= v <= 1 for v in atlas
        ):
            raise ValueError("Guide coordinates must be finite and UVs in [0,1]")
        if atlas[0] >= atlas[2] or atlas[1] >= atlas[3]:
            raise ValueError("Atlas rectangle is empty")
        lengths = [0.0]
        for a, b in zip(points, points[1:]):
            if (a - b).length < 1e-9:
                raise ValueError("Guide has repeated adjacent points")
            lengths.append(lengths[-1] + (a - b).length)
        start = len(vertices)
        side = None
        for k, point in enumerate(points):
            tangent = (points[min(k + 1, len(points) - 1)] - points[max(k - 1, 0)]).normalized()
            candidate = Vector((1, 0, 0)) if side is None else side
            side = candidate - tangent * candidate.dot(tangent)
            if side.length < 1e-6:
                side = tangent.cross(Vector((0, 1, 0)) if abs(tangent.y) < 0.9 else Vector((0, 0, 1)))
            side.normalize()
            t = lengths[k] / lengths[-1]
            half = width * 0.5 * (1 - 0.85 * t)
            vertices.extend([point - side * half, point + side * half])
            v = atlas[1] + t * (atlas[3] - atlas[1])
            uvs.extend([(atlas[0], v), (atlas[2], v)])
            if k:
                a = start + 2 * (k - 1)
                faces.append((a, a + 1, a + 3, a + 2))
    mesh = bpy.data.meshes.new("Hair cards")
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    obj = bpy.data.objects.new("Hair cards", mesh)
    bpy.context.collection.objects.link(obj)
    mesh.materials.append(material)
    uv = mesh.uv_layers.new(name="Atlas UV")
    for polygon in mesh.polygons:
        for loop_index in polygon.loop_indices:
            uv.data[loop_index].uv = uvs[mesh.loops[loop_index].vertex_index]
    (out / "guides.json").write_text(json.dumps(guides, ensure_ascii=False, indent=2))
    report(
        out,
        {
            "operation": "hair-cards",
            "guides": len(guides),
            "vertices": len(vertices),
            "cards_quads": len(faces),
            "atlas": bool(images),
            "placement": "explicit guides; no automatic hairstyle inference",
        },
    )


def bake(meshes, p, out):
    ratio = float(p.get("ratio", 0.5))
    resolution = int(p.get("resolution", 1024))
    if not 0 < ratio < 1 or resolution not in (256, 512, 1024, 2048, 4096):
        raise ValueError("Invalid ratio or resolution")
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.samples = 16
    counts = []
    for source in meshes:
        if any(m.type == "ARMATURE" for m in source.modifiers):
            raise ValueError("Bake static source geometry before rigging")
        target = source.copy()
        target.data = source.data.copy()
        bpy.context.collection.objects.link(target)
        target.name = source.name + "_baked"
        select(target)
        mod = target.modifiers.new("Lowpoly", "DECIMATE")
        mod.ratio = ratio
        bpy.ops.object.modifier_apply(modifier=mod.name)
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.uv.smart_project(island_margin=0.03)
        bpy.ops.object.mode_set(mode="OBJECT")
        target.data.materials.clear()
        material = bpy.data.materials.new(target.name)
        material.use_nodes = True
        target.data.materials.append(material)
        for face in target.data.polygons:
            face.material_index = 0
        bsdf = material.node_tree.nodes.get("Principled BSDF")
        for kind in ("basecolor", "normal"):
            image = bpy.data.images.new(target.name + "_" + kind, width=resolution, height=resolution, alpha=True)
            image.colorspace_settings.name = "sRGB" if kind == "basecolor" else "Non-Color"
            tex = material.node_tree.nodes.new("ShaderNodeTexImage")
            tex.image = image
            material.node_tree.nodes.active = tex
            select(target)
            source.select_set(True)
            scene.render.bake.use_selected_to_active = True
            scene.render.bake.use_clear = True
            scene.render.bake.cage_extrusion = max(source.dimensions) * 0.03
            scene.render.bake.max_ray_distance = max(source.dimensions) * 0.1
            if kind == "basecolor":
                scene.render.bake.use_pass_direct = False
                scene.render.bake.use_pass_indirect = False
                scene.render.bake.use_pass_color = True
                bpy.ops.object.bake(type="DIFFUSE")
                material.node_tree.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
            else:
                bpy.ops.object.bake(type="NORMAL")
                normal = material.node_tree.nodes.new("ShaderNodeNormalMap")
                material.node_tree.links.new(tex.outputs["Color"], normal.inputs["Color"])
                material.node_tree.links.new(normal.outputs["Normal"], bsdf.inputs["Normal"])
            image.filepath_raw = str(out / (target.name + "_" + kind + ".png"))
            image.file_format = "PNG"
            image.save()
            image.pack()
        counts.append(
            {
                "source": source.name,
                "source_polygons": len(source.data.polygons),
                "target_polygons": len(target.data.polygons),
            }
        )
        bpy.data.objects.remove(source, do_unlink=True)
    report(out, {"operation": "texture-bake", "objects": counts, "resolution": resolution, "visual_review": "required"})


def retarget(w, load):
    mapping = w["params"].get("bone_map")
    if len(w["inputs"]) != 2 or not isinstance(mapping, dict) or not mapping:
        raise ValueError("Supply source, target files and explicit bone_map {source:target}")
    original = list(w["inputs"])
    w["inputs"] = [original[0]]
    load()
    source_objects = set(bpy.data.objects)
    sources = [o for o in source_objects if o.type == "ARMATURE"]
    w["inputs"] = [original[1]]
    load()
    targets = [o for o in set(bpy.data.objects) - source_objects if o.type == "ARMATURE"]
    w["inputs"] = original
    if len(sources) != 1 or len(targets) != 1:
        raise ValueError("Each input must contain exactly one armature")
    source, target = sources[0], targets[0]
    if len(set(mapping.values())) != len(mapping):
        raise ValueError("Target bones must be uniquely mapped")
    for a, b in mapping.items():
        if a not in source.data.bones or b not in target.data.bones:
            raise ValueError("Unknown mapped bone " + a + " / " + b)
    if not source.animation_data or not source.animation_data.action:
        raise ValueError("Source has no active action")
    start, end = map(int, source.animation_data.action.frame_range)
    if end - start > 1800:
        raise ValueError("At most 1800 frames per task")
    if target.animation_data:
        target.animation_data_clear()
    inverse = {b: a for a, b in mapping.items()}
    ordered = sorted(target.pose.bones, key=lambda b: len(b.parent_recursive))
    scale = float(w["params"].get("root_scale", 1))
    if not math.isfinite(scale) or scale <= 0:
        raise ValueError("root_scale must be positive")
    root = next(b for b in source.data.bones if b.parent is None)
    for frame in range(start, end + 1):
        bpy.context.scene.frame_set(frame)
        bpy.context.view_layer.update()
        for bone in ordered:
            if bone.name not in inverse:
                continue
            source_name = inverse[bone.name]
            src = source.pose.bones[source_name]
            src_rest = source.data.bones[source_name]
            rotation = (
                src.matrix.to_quaternion()
                @ src_rest.matrix_local.to_quaternion().inverted()
                @ bone.bone.matrix_local.to_quaternion()
            )
            parent_delta = (
                bone.parent.matrix @ bone.parent.bone.matrix_local.inverted() if bone.parent else Matrix.Identity(4)
            )
            position = parent_delta @ bone.bone.head_local
            if bone.parent is None:
                position += (source.pose.bones[root.name].matrix.translation - root.head_local) * scale
            bone.matrix = Matrix.LocRotScale(position, rotation, Vector((1, 1, 1)))
            bone.rotation_mode = "QUATERNION"
            bone.keyframe_insert("rotation_quaternion", frame=frame)
            bone.keyframe_insert("location", frame=frame)
            bpy.context.view_layer.update()
    for obj in source_objects:
        bpy.data.objects.remove(obj, do_unlink=True)
    # The GLB exporter considers compatible orphan actions too. Keep only the
    # newly baked action, otherwise the source clip appears on the target again.
    for action in list(bpy.data.actions):
        if action != target.animation_data.action and action.users == 0:
            bpy.data.actions.remove(action)
    bpy.context.scene.frame_start = start
    bpy.context.scene.frame_end = end
    bpy.context.scene.frame_set(start)
    report(
        w["output"],
        {
            "operation": "motion-retarget",
            "frames": end - start + 1,
            "mapped_bones": len(mapping),
            "root_scale": scale,
            "contact_and_self_collision": "not evaluated",
        },
    )
