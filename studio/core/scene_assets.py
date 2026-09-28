"""Whole GLB instances: immutable source assets, local placement, safe replacement.

The normal editor mesh is a rest-pose proxy. Never flatten the authoritative
GLB: its hierarchy, materials, skins and clips remain in a separate asset.
"""

from __future__ import annotations

import copy
import hashlib
import io
import json
import re
import struct
from functools import lru_cache
from pathlib import Path

import numpy as np
import trimesh

from studio.i18n import render

SCHEMA = "studio-scene-instance/v1"


def error(code, **params):
    from studio.core.editor import EditorError

    raise EditorError.coded(code, **params)


def unpack(raw):
    from studio.core.editor import MAX_BYTES

    if len(raw) < 28 or len(raw) > MAX_BYTES or struct.unpack("<4sII", raw[:12]) != (b"glTF", 2, len(raw)):
        error("scene_assets.invalid_glb_header")
    length, kind = struct.unpack("<II", raw[12:20])
    end = 20 + length
    if kind != 0x4E4F534A or length % 4 or end + 8 > len(raw):
        error("scene_assets.invalid_json_chunk")
    try:
        doc = json.loads(raw[20:end])
    except (ValueError, UnicodeError):
        error("scene_assets.invalid_json")
    size, kind = struct.unpack("<II", raw[end : end + 8])
    if kind != 0x004E4942 or end + 8 + size != len(raw):
        error("scene_assets.invalid_binary_chunk")
    return doc, raw[end + 8 :]


def pack(doc, binary):
    raw = json.dumps(doc, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()
    raw += b" " * (-len(raw) % 4)
    binary += b"\0" * (-len(binary) % 4)
    return (
        struct.pack("<4sII", b"glTF", 2, 28 + len(raw) + len(binary))
        + struct.pack("<II", len(raw), 0x4E4F534A)
        + raw
        + struct.pack("<II", len(binary), 0x004E4942)
        + binary
    )


def inspect(raw):
    from studio.core import motion

    doc, binary = unpack(raw)
    if (
        len(doc.get("buffers", [])) != 1
        or doc["buffers"][0].get("uri")
        or doc["buffers"][0].get("byteLength", 0) > len(binary)
    ):
        error("scene_assets.requires_self_contained")
    if any(i.get("uri") and not i["uri"].startswith("data:") for i in doc.get("images", [])):
        error("scene_assets.external_textures")
    if set(doc.get("extensionsRequired", [])) & {
        "KHR_draco_mesh_compression",
        "EXT_meshopt_compression",
        "KHR_texture_basisu",
    }:
        error("scene_assets.requires_decompression")
    if any(p.get("targets") for m in doc.get("meshes", []) for p in m.get("primitives", [])):
        error("scene_assets.has_morph_targets")
    nodes = doc.get("nodes", [])
    if not nodes or len(nodes) > 20000:
        error("scene_assets.node_count_out_of_range")
    # Detect bad indices, cycles and multiple parents before a loader walks it.
    parents = {}
    for index, node in enumerate(nodes):
        for child in node.get("children", []):
            if type(child) is not int or not 0 <= child < len(nodes) or child in parents:
                error("scene_assets.invalid_hierarchy_or_multi_parent")
            parents[child] = index
        for key, size in [("matrix", 16), ("translation", 3), ("rotation", 4), ("scale", 3)]:
            if key in node:
                value = np.asarray(node[key], dtype=float)
                if value.shape != (size,) or not np.isfinite(value).all():
                    error("scene_assets.invalid_transform_values")
    complete = set()
    for index in range(len(nodes)):
        seen = set()
        while index in parents and index not in complete:
            if index in seen:
                error("scene_assets.hierarchy_cycle")
            seen.add(index)
            index = parents[index]
        complete.update(seen)
    for scene in doc.get("scenes", []):
        if any(type(i) is not int or not 0 <= i < len(nodes) or i in parents for i in scene.get("nodes", [])):
            error("scene_assets.invalid_scene_root")
    if (
        not doc.get("scenes")
        or type(doc.get("scene", 0)) is not int
        or not 0 <= doc.get("scene", 0) < len(doc["scenes"])
    ):
        error("scene_assets.missing_default_scene")
    for view in doc.get("bufferViews", []):
        offset, size = view.get("byteOffset", 0), view.get("byteLength", 0)
        if (
            view.get("buffer", 0) != 0
            or type(offset) is not int
            or type(size) is not int
            or offset < 0
            or size < 0
            or offset + size > len(binary)
        ):
            error("scene_assets.buffer_view_out_of_range")
    for skin in doc.get("skins", []):
        joints = skin.get("joints", [])
        if (
            not joints
            or any(type(i) is not int or not 0 <= i < len(nodes) for i in joints)
            or len(joints) != len(set(joints))
        ):
            error("scene_assets.invalid_skin_joint_index")

    def accessor(index, expected="VEC4"):
        if type(index) is not int or not 0 <= index < len(doc.get("accessors", [])):
            error("scene_assets.invalid_accessor_index")
        a = doc["accessors"][index]
        if a.get("sparse") or "bufferView" not in a:
            error("scene_assets.sparse_accessor_unsupported")
        view = doc["bufferViews"][a["bufferView"]]
        dtype = {5121: "u1", 5123: "<u2", 5126: "<f4"}.get(a["componentType"])
        if not dtype or a["type"] != expected or view.get("buffer", 0) != 0:
            error("scene_assets.invalid_accessor_type")
        width = {"SCALAR": 1, "VEC3": 3, "VEC4": 4}[expected]
        item = np.dtype(dtype).itemsize
        stride = view.get("byteStride", item * width)
        count = a["count"]
        offset = a.get("byteOffset", 0)
        needed = offset + max(0, count - 1) * stride + width * item
        if (
            count <= 0
            or count > 10000000
            or stride < item * width
            or offset < 0
            or needed > view["byteLength"]
            or view.get("byteOffset", 0) + needed > len(binary)
        ):
            error("scene_assets.skin_data_out_of_range")
        array = np.ndarray(
            (count, width),
            dtype=dtype,
            buffer=binary,
            offset=view.get("byteOffset", 0) + offset,
            strides=(stride, item),
        )
        if a.get("normalized") and a["componentType"] != 5126:
            return array.astype(float) / (255 if item == 1 else 65535)
        return array

    try:
        for animation in doc.get("animations", []):
            targets = set()
            for channel in animation["channels"]:
                node, path = channel["target"]["node"], channel["target"]["path"]
                if (
                    type(node) is not int
                    or not 0 <= node < len(nodes)
                    or path not in ("translation", "rotation", "scale")
                    or (node, path) in targets
                ):
                    error("scene_assets.invalid_or_duplicate_animation_target")
                targets.add((node, path))
                sampler_index = channel["sampler"]
                if type(sampler_index) is not int or not 0 <= sampler_index < len(animation["samplers"]):
                    error("scene_assets.invalid_animation_sampler_index")
                sampler = animation["samplers"][sampler_index]
                interpolation = sampler.get("interpolation", "LINEAR")
                if interpolation not in ("LINEAR", "STEP", "CUBICSPLINE"):
                    error("scene_assets.invalid_animation_interpolation")
                times = accessor(sampler["input"], "SCALAR").ravel()
                values = accessor(sampler["output"], "VEC4" if path == "rotation" else "VEC3")
                if (
                    not np.isfinite(times).all()
                    or np.any(times < 0)
                    or np.any(np.diff(times) <= 0)
                    or not np.isfinite(values).all()
                ):
                    error("scene_assets.animation_non_finite_or_unordered_time")
                if len(values) != len(times) * (3 if interpolation == "CUBICSPLINE" else 1):
                    error("scene_assets.animation_keyframe_count_mismatch")
                declared = doc["accessors"][sampler["input"]].get("max", [])
                if len(declared) != 1 or abs(declared[0] - float(times[-1])) > 1e-4:
                    error("scene_assets.animation_time_bound_mismatch")
        for node in nodes:
            if "skin" not in node:
                continue
            skin = doc["skins"][node["skin"]]
            for p in doc["meshes"][node["mesh"]]["primitives"]:
                attrs = p["attributes"]
                if "JOINTS_1" in attrs or "WEIGHTS_1" in attrs:
                    error("scene_assets.too_many_skin_weight_sets")
                joints, weights = accessor(attrs["JOINTS_0"]), accessor(attrs["WEIGHTS_0"])
                if joints.shape != weights.shape or joints.shape[0] != doc["accessors"][attrs["POSITION"]]["count"]:
                    error("scene_assets.skin_vertex_count_mismatch")
                if (
                    not np.isfinite(weights).all()
                    or np.any(weights < 0)
                    or np.any(np.abs(weights.sum(axis=1) - 1) > 0.025)
                ):
                    error("scene_assets.skin_weights_invalid")
                if np.any(joints < 0) or np.any(joints >= len(skin["joints"])) or np.any(joints != np.floor(joints)):
                    error("scene_assets.vertex_references_missing_joint")
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        from studio.core.editor import EditorError

        if isinstance(exc, EditorError):
            raise
        error("scene_assets.invalid_animation_or_skin_structure")
    if doc.get("skins"):
        info = motion.glb_info(raw)
    else:
        clips = []
        for clip in doc.get("animations", []):
            if any(
                c.get("target", {}).get("path") not in ("translation", "rotation", "scale")
                for c in clip.get("channels", [])
            ):
                error("scene_assets.scene_animation_trs_only")
            duration = max(
                (doc["accessors"][s["input"]].get("max", [0])[0] for s in clip.get("samplers", [])), default=0
            )
            clips.append({"name": clip.get("name", "动作"), "duration": float(duration)})
        info = {"bones": [], "clips": clips}
    if any(not np.isfinite(c["duration"]) or not 0 < c["duration"] <= 120 for c in info["clips"]):
        error("scene_assets.clip_duration_out_of_range")
    return doc, info


def create(workspace, raw, name):
    from studio.core.editor import GLTF_TO_WORKSPACE, _atomic

    doc, info = inspect(raw)
    scene = trimesh.load_scene(io.BytesIO(raw), file_type="glb", process=False)
    proxy = scene.to_mesh()
    conversion = GLTF_TO_WORKSPACE.copy()
    conversion[:3, :3] *= 1000
    proxy.apply_transform(conversion)
    obj = workspace._object(proxy, name)
    digest = hashlib.sha256(raw).hexdigest()
    _atomic(workspace.root / "assets" / f"{digest}.glb", raw)
    kind = "skin" if info["bones"] else "animated" if info["clips"] else "static"
    obj["scene"] = {
        "schema": SCHEMA,
        "asset": digest,
        "family": digest,
        "kind": kind,
        "nodes": len(doc["nodes"]),
        "bones": len(info["bones"]),
        "clips": len(info["clips"]),
    }
    if kind != "static":
        obj["motion"] = dict(
            schema="studio-motion/v1",
            kind="skin" if kind == "skin" else "gltf",
            asset=digest,
            bound_asset=obj["asset"],
            mode="clip" if info["clips"] else "pkf",
            duration=info["clips"][0]["duration"] if info["clips"] else 4,
            fps=30,
            clip=0,
            speed=1,
            start=0,
            parameters=[],
            steps=[],
            keyframes=[],
            **info,
        )
    return obj


def read(path):
    from studio.core.editor import MAX_BYTES

    path = Path(path).expanduser()
    if not path.is_absolute() or not path.is_file() or path.suffix.lower() != ".glb" or path.stat().st_size > MAX_BYTES:
        error("scene_assets.invalid_local_path")
    return path, path.read_bytes()


def apply(workspace, doc, action, p):
    from studio.core import motion

    if action == "scene_import":
        files = p.get("files", [])
        if not isinstance(files, list) or not 1 <= len(files) <= 50:
            error("scene_assets.invalid_import_file_count")
        new = [create(workspace, raw, path.stem) for path, raw in (read(f) for f in files)]
        doc["objects"].extend(new)
        doc["selection"] = [o["id"] for o in new]
        motion.worker(doc["objects"])
        return {"summary": render("scene_assets.import_summary", count=len(new)), "created": doc["selection"]}
    selected = workspace._selected(doc, p)
    if len(selected) != 1:
        error("scene_assets.requires_single_selection")
    obj = selected[0]
    if action == "scene_export":
        if not obj.get("scene") and obj.get("motion", {}).get("kind") != "skin":
            from studio.core.editor import WORKSPACE_TO_GLTF

            mesh = workspace.mesh(obj)
            conversion = WORKSPACE_TO_GLTF.copy()
            conversion[:3] *= 0.001
            mesh.apply_transform(conversion)
            raw = trimesh.Scene(mesh).export(file_type="glb")
            digest = obj["asset"]
        else:
            digest = obj.get("scene", {}).get("asset") or obj["motion"]["asset"]
            raw = (workspace.root / "assets" / f"{digest}.glb").read_bytes()
        path = workspace._output_path(p, ".glb")
        with path.open("xb") as f:
            f.write(raw)
        return {
            "summary": render("scene_assets.export_summary"),
            "path": str(path),
            "source_asset": digest,
            "object_id": obj["id"],
            "transform": obj["transform"],
        }
    if action == "scene_replace":
        path, raw = read(p.get("path", ""))
        new = create(workspace, raw, obj["name"])
        new.update(id=obj["id"], transform=copy.deepcopy(obj["transform"]), visible=obj["visible"])
        new["scene"]["family"] = obj.get("scene", {}).get("family", new["scene"]["family"])
        from studio.core.city import check_replacement

        check_replacement(obj, new, raw)
        if p.get("blend_path"):
            # Source Blender files follow the existing motion import validation.
            if new.get("motion", {}).get("kind") != "skin":
                error("scene_assets.blend_path_requires_skin")
            incoming = {"objects": [], "selection": []}
            motion.rig_import(workspace, incoming, p)
            new["motion"]["blend_asset"] = incoming["objects"][0]["motion"]["blend_asset"]
        workspace._replace(doc, selected, [new])
        motion.worker(doc["objects"])
        motion.validate_assets(workspace, doc["objects"])
        return {
            "summary": render("scene_assets.replace_summary"),
            "created": [obj["id"]],
            "validation": render("scene_assets.replace_validation_note"),
        }
    error("scene_assets.unknown_action")


def materials(workspace, obj):
    return copy.deepcopy(_materials(str(workspace.root / "assets" / f"{obj['scene']['asset']}.glb")))


@lru_cache(maxsize=64)
def _materials(path):
    doc, _ = unpack(Path(path).read_bytes())
    result = []
    for index, material in enumerate(doc.get("materials", [])):
        pbr = material.get("pbrMetallicRoughness", {})
        color = pbr.get("baseColorFactor", [1, 1, 1, 1])
        result.append(
            {
                "slot": index,
                "name": material.get("name", f"材质 {index + 1}"),
                "editable": True,
                "color": "#" + "".join(f"{round(max(0, min(1, c)) * 255):02x}" for c in color[:3]),
                "roughness": pbr.get("roughnessFactor", 1),
                "metallic": pbr.get("metallicFactor", 1),
                "base_color_texture": bool(pbr.get("baseColorTexture")),
            }
        )
    return result


def edit_material(workspace, obj, p):
    # Patch JSON only. Original skin/normal/UV/animation buffers stay byte-identical.
    doc, binary = unpack((workspace.root / "assets" / f"{obj['scene']['asset']}.glb").read_bytes())
    mats = doc.setdefault("materials", [])
    if not mats:
        mats.append({})
        for mesh in doc["meshes"]:
            for prim in mesh["primitives"]:
                prim["material"] = 0
    slots = p.get("material_slots", list(range(len(mats))))
    if not isinstance(slots, list) or not slots or any(type(i) is not int or not 0 <= i < len(mats) for i in slots):
        error("scene_assets.material_slots_changed")
    if p.get("base_color_texture") is not None:
        error("scene_assets.texture_replacement_unsupported")
    for i in slots:
        pbr = mats[i].setdefault("pbrMetallicRoughness", {})
        if "color" in p:
            if not isinstance(p["color"], str) or not re.fullmatch(r"#[a-fA-F0-9]{6}", p["color"]):
                error("scene_assets.invalid_color")
            pbr["baseColorFactor"] = [int(p["color"][j : j + 2], 16) / 255 for j in (1, 3, 5)] + [
                pbr.get("baseColorFactor", [1] * 4)[3]
            ]
        for source, target in [("roughness", "roughnessFactor"), ("metallic", "metallicFactor")]:
            if source in p:
                v = p[source]
                if not isinstance(v, (int, float)) or not np.isfinite(v) or not 0 <= v <= 1:
                    error("scene_assets.material_value_out_of_range")
                pbr[target] = v
        if "base_color_texture" in p:
            pbr.pop("baseColorTexture", None)
    candidate = create(workspace, pack(doc, binary), obj["name"])
    old_motion = copy.deepcopy(obj.get("motion"))
    obj["asset"] = candidate["asset"]
    obj["scene"]["asset"] = candidate["scene"]["asset"]
    if old_motion:
        old_motion.update(asset=candidate["scene"]["asset"], bound_asset=candidate["asset"])
        obj["motion"] = old_motion


def validate(workspace, objects):
    for obj in objects:
        scene = obj.get("scene")
        if scene is None:
            continue
        if (
            not isinstance(scene, dict)
            or scene.get("schema") != SCHEMA
            or any(not re.fullmatch(r"[a-f0-9]{64}", str(scene.get(k, ""))) for k in ("asset", "family"))
        ):
            error("scene_assets.invalid_scene_reference")
        raw = (workspace.root / "assets" / f"{scene['asset']}.glb").read_bytes()
        if hashlib.sha256(raw).hexdigest() != scene["asset"]:
            error("scene_assets.asset_hash_mismatch")
        _, info = inspect(raw)
        if obj.get("motion") and obj["motion"].get("asset") != scene["asset"]:
            error("scene_assets.motion_asset_version_mismatch")
        if scene.get("bones") != len(info["bones"]) or scene.get("clips") != len(info["clips"]):
            error("scene_assets.asset_summary_mismatch")
