"""Versioned per-object motion; shared JS evaluator, immutable rigs, portable packages."""

from __future__ import annotations
import copy
import hashlib
import io
import json
import re
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

from studio.paths import APP_DIST_DIR
from studio.i18n import render
import numpy as np
import trimesh


def error(code, **params):
    from studio.core.editor import EditorError

    raise EditorError.coded(code, **params)


def assets(objects):
    return {
        a for o in objects for a in (o["asset"], o.get("motion", {}).get("asset"), o.get("scene", {}).get("asset")) if a
    }


def worker(objects, action="validate", **kwargs):
    node = shutil.which("node") or "/opt/homebrew/bin/node"
    bundle = APP_DIST_DIR / "motion-cli.cjs"
    with tempfile.TemporaryDirectory(prefix="studio-motion-") as tmp:
        request = Path(tmp) / "request.json"
        request.write_text(json.dumps(dict(action=action, objects=objects, **kwargs), allow_nan=False))
        try:
            result = subprocess.run([node, str(bundle), str(request)], capture_output=True, text=True, timeout=180)
        except (OSError, subprocess.TimeoutExpired) as exc:
            error("motion.worker_process_unavailable", error=exc)
        if result.returncode:
            stderr = result.stderr[-2000:]
            if stderr:
                from studio.core.editor import EditorError

                raise EditorError(stderr)
            error("motion.worker_evaluation_failed")
        return json.loads(result.stdout)


def glb_info(raw):
    from studio.core.editor import _glb_document, MAX_BYTES

    if len(raw) > MAX_BYTES:
        error("motion.rig_asset_too_large")
    doc = _glb_document(raw)
    if len(doc.get("buffers", [])) != 1 or doc["buffers"][0].get("uri"):
        error("motion.requires_single_embedded_buffer")
    if set(doc.get("extensionsRequired", [])) & {
        "KHR_draco_mesh_compression",
        "EXT_meshopt_compression",
        "KHR_texture_basisu",
    }:
        error("motion.requires_decompression")
    for item in doc.get("buffers", []) + doc.get("images", []):
        if item.get("uri") and not item["uri"].startswith("data:"):
            error("motion.requires_self_contained")
    if any(p.get("targets") for m in doc.get("meshes", []) for p in m.get("primitives", [])):
        error("motion.has_morph_targets")
    if any(
        c.get("target", {}).get("path") not in ("translation", "rotation", "scale")
        for a in doc.get("animations", [])
        for c in a.get("channels", [])
    ):
        error("motion.unsupported_animation_channel")
    bones = sorted({i for s in doc.get("skins", []) for i in s.get("joints", [])})
    if not bones:
        error("motion.missing_skin")
    nodes = doc.get("nodes", [])
    names = [nodes[i].get("name", "") for i in bones]
    if any(not n for n in names) or len(names) != len(set(names)):
        error("motion.invalid_bone_names")
    parents = {child: i for i, node in enumerate(nodes) for child in node.get("children", [])}
    durations = []
    # Animation input accessors must declare min/max as required by glTF.
    for clip in doc.get("animations", []):
        maximum = max((doc["accessors"][s["input"]].get("max", [0])[0] for s in clip.get("samplers", [])), default=0)
        durations.append({"name": clip.get("name", f"动作 {len(durations) + 1}"), "duration": float(maximum)})
    return {
        "bones": [
            {"name": nodes[i]["name"], "parent": nodes[parents[i]].get("name") if i in parents else None} for i in bones
        ],
        "clips": durations,
    }


def rig_import(workspace, doc, p):
    from studio.core.editor import _atomic, GLTF_TO_WORKSPACE, MAX_BYTES

    path = Path(p.get("path", "")).expanduser()
    if not path.is_absolute() or not path.is_file() or path.suffix.lower() != ".glb" or path.stat().st_size > MAX_BYTES:
        error("motion.invalid_rig_path")
    raw = path.read_bytes()
    info = glb_info(raw)
    digest = hashlib.sha256(raw).hexdigest()
    scene = trimesh.load_scene(io.BytesIO(raw), file_type="glb", process=False)
    proxy = scene.to_mesh()
    conversion = GLTF_TO_WORKSPACE.copy()
    conversion[:3, :3] *= 1000
    proxy.apply_transform(conversion)
    obj = workspace._object(proxy, path.stem)
    duration = info["clips"][0]["duration"] if info["clips"] else 4
    if duration <= 0 or duration > 120:
        error("motion.clip_duration_out_of_range")
    obj["motion"] = dict(
        schema="studio-motion/v1",
        kind="skin",
        asset=digest,
        mode="clip" if info["clips"] else "pkf",
        duration=duration,
        fps=30,
        clip=0,
        speed=1,
        start=0,
        parameters=[],
        steps=[],
        keyframes=[],
        **info,
    )
    _atomic(workspace.root / "assets" / f"{digest}.glb", raw)
    if p.get("blend_path"):
        blend = Path(p["blend_path"]).expanduser()
        if (
            not blend.is_absolute()
            or not blend.is_file()
            or blend.suffix != ".blend"
            or blend.stat().st_size > MAX_BYTES
        ):
            error("motion.invalid_blend_path")
        blend_raw = blend.read_bytes()
        if not blend_raw.startswith(b"BLENDER"):
            error("motion.blend_not_uncompressed")
        sha = hashlib.sha256(blend_raw).hexdigest()
        directory = workspace.root / "sources"
        directory.mkdir(exist_ok=True)
        _atomic(directory / f"{sha}.blend", blend_raw)
        obj["motion"]["blend_asset"] = sha
    obj["motion"]["bound_asset"] = obj["asset"]
    doc["objects"].append(obj)
    doc["selection"] = [obj["id"]]
    worker(doc["objects"])
    return {
        "summary": render("motion.rig_import_summary", bones=len(info["bones"]), clips=len(info["clips"])),
        "created": [obj["id"]],
    }


def validate_assets(workspace, objects):
    for obj in objects:
        m = obj.get("motion")
        if not m:
            continue
        if m.get("bound_asset") != obj["asset"]:
            error("motion.geometry_changed", name=obj["name"])
        if m["kind"] in ("skin", "gltf"):
            raw = (workspace.root / "assets" / (m["asset"] + ".glb")).read_bytes()
            if m["kind"] == "gltf":
                from studio.core.scene_assets import inspect

                _, info = inspect(raw)
            else:
                info = glb_info(raw)
            if hashlib.sha256(raw).hexdigest() != m["asset"]:
                error("motion.rig_asset_checksum_mismatch")
            bone_names = {b["name"] for b in info["bones"]}
            if any(s["bone"] not in bone_names for s in m["steps"]):
                error("motion.pkf_step_missing_bone")
            if m["mode"] == "clip":
                index = m.get("clip", 0)
                if (
                    index >= len(info["clips"])
                    or m.get("start", 0) + m["duration"] * m.get("speed", 1) > info["clips"][index]["duration"] + 1e-4
                ):
                    error("motion.clip_range_exceeds_source")


def set_motion(workspace, doc, p):
    selected = workspace._selected(doc, p)
    if len(selected) != 1:
        error("motion.requires_single_selection")
    obj = selected[0]
    incoming = p.get("motion")
    if not isinstance(incoming, dict):
        error("motion.invalid_motion_payload")
    old = obj.get("motion", {})
    m = copy.deepcopy(incoming)
    if obj.get("scene") and m.get("kind") == "joint":
        error("motion.joint_not_allowed_on_scene")
    if m.get("kind") in ("skin", "gltf"):
        if old.get("kind") not in ("skin", "gltf") or m.get("asset") != old["asset"]:
            error("motion.rig_asset_must_use_import")
        if m["kind"] != old["kind"]:
            error("motion.asset_kind_changed")
        for key in ("bones", "clips", "blend_asset"):
            m.pop(key, None)
            if key in old:
                m[key] = old[key]
    m["bound_asset"] = obj["asset"]
    obj["motion"] = m
    if m.get("kind") == "joint":
        m["bound_transform"] = copy.deepcopy(obj["transform"])
        m["bindings"] = {}
        by_id = {o["id"]: o for o in doc["objects"]}
        parent = m.get("joint", {}).get("parent")
        seen = {obj["id"]}
        while parent and parent in by_id and parent not in seen:
            seen.add(parent)
            other = by_id[parent]
            m["bindings"][parent] = {"asset": other["asset"], "transform": copy.deepcopy(other["transform"])}
            parent = other.get("motion", {}).get("joint", {}).get("parent")
    worker(doc["objects"])
    validate_assets(workspace, doc["objects"])
    return {"summary": render("motion.set_summary", name=obj["name"])}


def zero_model(workspace, objects, path):
    from studio.core.editor import WORKSPACE_TO_GLTF

    result = worker(objects)
    scene = trimesh.Scene()
    for obj in objects:
        frame = np.asarray(result["rest"][obj["id"]]).reshape(4, 4, order="F")
        mesh = workspace.mesh(obj, world=True)
        matrix = WORKSPACE_TO_GLTF.copy()
        matrix[:3] *= 0.001
        mesh.apply_transform(np.linalg.inv(frame) @ matrix)
        scene.add_geometry(mesh, node_name=obj["id"], geom_name=obj["id"], transform=frame)
    Path(path).write_bytes(scene.export(file_type="glb"))


def export_motion(workspace, doc, p):
    objects = workspace._selected(doc, p) if "ids" in p else doc["objects"]
    if not any(o.get("motion") for o in objects):
        error("motion.requires_motion")
    worker(objects)
    validate_assets(workspace, objects)
    fmt = p.get("format", "zip")
    if fmt not in ("zip", "glb"):
        error("motion.invalid_export_format")
    path = workspace._output_path(p, "." + fmt)
    skin = any(o.get("motion", {}).get("kind") in ("skin", "gltf") for o in objects)
    with tempfile.TemporaryDirectory(prefix="studio-motion-export-") as tmp:
        model = Path(tmp) / "model.glb"
        output = Path(tmp) / ("result." + fmt)
        if fmt == "glb":
            if skin:
                if len(objects) != 1:
                    error("motion.glb_export_requires_single_rig")
                model.write_bytes((workspace.root / "assets" / (objects[0]["motion"]["asset"] + ".glb")).read_bytes())
            else:
                zero_model(workspace, objects, model)
            report = worker(objects, "glb", model=str(model), output=str(output))
            reloaded = trimesh.load_scene(output, process=False)
            if not reloaded.geometry:
                error("motion.exported_glb_missing_geometry")
        else:
            if not skin:
                zero_model(workspace, objects, model)
                report = worker(objects, "package", model=str(model), output=str(output))
            else:
                report = {"kind": "studio-skin-extension/v1"}
            # The studio extension preserves per-object identities/parameters,
            # original rigs and optional Blender source; plain MF readers ignore it.
            with zipfile.ZipFile(output, "a", zipfile.ZIP_DEFLATED) as z:
                manifest = dict(
                    schema="3d-workbench/v1", name=doc["name"], objects=objects, selection=[o["id"] for o in objects]
                )
                z.writestr("studio-project.json", json.dumps(manifest, ensure_ascii=False))
                z.writestr(
                    "studio-motion.json",
                    json.dumps(
                        {
                            "schema": "studio-motion-package/v1",
                            "mechanical_core": "motionforge/v7" if not skin else None,
                            "units": "glTF metres/Y-up; workspace mm/Z-up",
                            "note": "Skin extension is not readable by legacy MotionForge",
                        }
                    ),
                )
                for asset in assets(objects):
                    z.write(workspace.root / "assets" / f"{asset}.glb", f"assets/{asset}.glb")
                for blend in {o.get("motion", {}).get("blend_asset") for o in objects} - {None}:
                    z.write(workspace.root / "sources" / f"{blend}.blend", f"sources/{blend}.blend")
        with path.open("xb") as f:
            f.write(output.read_bytes())
    return {
        "summary": render("motion.export_zip_summary") if fmt == "zip" else render("motion.export_glb_summary"),
        "path": str(path),
        "motion_report": report,
    }


def import_package(workspace, doc, p):
    from studio.core.editor import MAX_BYTES, GLTF_TO_WORKSPACE
    import uuid

    path = Path(p.get("path", "")).expanduser()
    if not path.is_absolute() or not path.is_file() or path.stat().st_size > MAX_BYTES:
        error("motion.invalid_package_path")
    with zipfile.ZipFile(path) as z, tempfile.TemporaryDirectory(prefix="studio-motion-import-") as tmp:
        infos = z.infolist()
        if (
            len(infos) > 3000
            or len({i.filename for i in infos}) != len(infos)
            or sum(i.file_size for i in infos) > MAX_BYTES
        ):
            error("motion.package_too_large_or_duplicate")
        if "studio-project.json" in z.namelist():
            # Reuse the verified project loader through a temporary container.
            project = Path(tmp) / "import.3dworkbench"
            with zipfile.ZipFile(project, "w") as output:
                output.writestr("manifest.json", z.read("studio-project.json"))
                for i in infos:
                    if re.fullmatch(r"(assets/[a-f0-9]{64}\.glb|sources/[a-f0-9]{64}\.blend)", i.filename):
                        output.writestr(i.filename, z.read(i))
            incoming = copy.deepcopy(doc)
            workspace._open_archive(incoming, {"path": str(project)})
            new = incoming["objects"]
        else:
            names = [i.filename for i in infos if re.fullmatch(r"manifest[^/]*\.json", i.filename)]
            if len(names) != 1:
                error("motion.missing_motionforge_manifest")
            manifest = json.loads(z.read(names[0]))
            files = manifest.get("files", {})
            if manifest.get("schema_version") != 7:
                error("motion.unsupported_motionforge_schema")
            if manifest.get("source", {}).get("units_in_meters") != 1 or manifest["source"].get("up_axis") != "Z":
                error("motion.motionforge_units_mismatch")
            if manifest.get("scene_markers"):
                error("motion.motionforge_scene_markers_unsupported")
            joints = json.loads(z.read(files["joints"])).get("definitions", [])
            clips = json.loads(z.read(files["motion"])).get("clips", [])
            if len(clips) != 1 or clips[0].get("reparent_events"):
                error("motion.motionforge_multi_clip_unsupported")
            if any(j.get("overflow_to") or j.get("limit_upper") is not None for j in joints):
                error("motion.motionforge_overflow_unsupported")
            if any(j.get("current_value", 0) != 0 for j in joints):
                error("motion.motionforge_joint_not_zeroed")
            pkf = json.loads(z.read(files["pkf"])) if files.get("pkf") else {"parameters": [], "steps": []}
            raw = z.read(files["model"])
            from studio.core.editor import _glb_document

            gltf = _glb_document(raw)
            if any(
                item.get("uri") and not item["uri"].startswith("data:")
                for item in gltf.get("images", []) + gltf.get("buffers", [])
            ):
                error("motion.package_glb_requires_self_contained")
            model = Path(tmp) / "model.glb"
            model.write_bytes(raw)
            from studio.core.editor import _check_static

            _check_static(model)
            scene = trimesh.load_scene(model, process=False)
            conversion = GLTF_TO_WORKSPACE.copy()
            conversion[:3, :3] *= 1000
            new = []
            by_name = {}
            for name in scene.graph.nodes_geometry:
                transform, geom = scene.graph[name]
                obj = workspace._object(scene.geometry[geom], name, conversion @ transform)
                new.append(obj)
                by_name[name] = obj
            frames = worker(new)["rest"]
            for j in joints:
                obj = by_name.get(j.get("name"))
                if obj is None:
                    error("motion.motionforge_joint_requires_mesh_node")
                if j.get("parent_name") and j["parent_name"] not in by_name:
                    error("motion.motionforge_joint_parent_unresolved")
                steps = [s for s in pkf["steps"] if s.get("joint") == j["name"]]
                keys = [
                    {"time": k["t"], "value": k["joint_values"][j["name"]]}
                    for k in clips[0].get("keyframes", [])
                    if j["name"] in k.get("joint_values", {})
                ]
                origin = [j["origin"][a] for a in "xyz"]
                if j.get("parent_name"):
                    parent = by_name[j["parent_name"]]
                    frame = np.asarray(frames[parent["id"]]).reshape(4, 4, order="F")
                    native = scene.graph[j["parent_name"]][0]
                    xyz = np.linalg.inv(frame) @ native @ np.array([origin[0], origin[2], origin[1], 1])
                    origin = [float(xyz[0]), float(xyz[2]), float(xyz[1])]
                obj["motion"] = dict(
                    schema="studio-motion/v1",
                    kind="joint",
                    duration=clips[0]["duration"],
                    fps=manifest["source"].get("fps", 30),
                    mode="pkf" if steps else "keyframes",
                    joint=dict(
                        type=j["type"],
                        axis=j["axis"],
                        origin=origin,
                        limits=[j["limits"]["min"], j["limits"]["max"]],
                        parent=by_name[j["parent_name"]]["id"] if j.get("parent_name") else None,
                    ),
                    parameters=pkf["parameters"],
                    steps=steps,
                    keyframes=keys,
                    bound_asset=obj["asset"],
                )
        # Imports append with fresh IDs; references are remapped as one transaction.
        mapping = {o["id"]: uuid.uuid4().hex for o in new}
        for obj in new:
            obj["id"] = mapping[obj["id"]]
            if obj.get("motion", {}).get("kind") == "joint":
                parent = obj["motion"]["joint"].get("parent")
                obj["motion"]["joint"]["parent"] = mapping.get(parent)
                obj["motion"]["bindings"] = {mapping[k]: v for k, v in obj["motion"].get("bindings", {}).items()}
        worker(new)
        validate_assets(workspace, new)
        doc["objects"].extend(new)
        doc["selection"] = [o["id"] for o in new]
    return {"summary": render("motion.import_package_summary", count=len(new)), "created": doc["selection"]}


def apply(workspace, doc, action, p):
    if action == "motion_set":
        return set_motion(workspace, doc, p)
    if action == "motion_import":
        return (
            import_package(workspace, doc, p)
            if Path(p.get("path", "")).suffix.lower() == ".zip"
            else rig_import(workspace, doc, p)
        )
    if action == "motion_export":
        return export_motion(workspace, doc, p)
    if action == "motion_clear":
        for obj in workspace._selected(doc, p):
            obj.pop("motion", None)
        return {"summary": render("motion.clear_summary")}
    error("motion.unknown_action")


def dependencies(objects, targets, incoming=None):
    """A joint edit reads its ancestors and changes descendants' playback."""
    result = set(targets)
    parents = {o["id"]: o.get("motion", {}).get("joint", {}).get("parent") for o in objects}
    if incoming and len(targets) == 1:
        parents[targets[0]] = incoming.get("joint", {}).get("parent")
    pending = list(targets)
    while pending:
        current = pending.pop()
        for child, parent in parents.items():
            if parent == current and child not in result:
                result.add(child)
                pending.append(child)
    for target in list(result):
        cursor = parents.get(target)
        seen = set()
        while cursor and cursor not in seen:
            seen.add(cursor)
            result.add(cursor)
            cursor = parents.get(cursor)
    return result
