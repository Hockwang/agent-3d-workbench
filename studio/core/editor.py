"""Local, versioned mesh workspace. Geometry kernels are Trimesh and Manifold.

Assets are immutable GLBs in workspace coordinates (millimetres, Z up). GLB
import/export converts between that convention and glTF's metres / Y up.
Geometry editing uses static meshes; motion.py preserves rigs separately.
"""

from __future__ import annotations

import copy
import hashlib
import io
import json
import re
import threading
import uuid
import zipfile
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

import manifold3d
import numpy as np
import trimesh
from trimesh.visual.material import MultiMaterial
from studio.i18n import render as _render_message
from studio.core import geometry_store
from studio.core import motion as motion_edit
from studio.core import collaboration
from studio.core import materials as material_edit
from studio.core import scene_assets
from studio.core import city

SCHEMA = "3d-workbench/v1"
MAX_BYTES = 500 * 1024 * 1024
MAX_OBJECTS = 500
_KERNEL_LOCK = threading.Lock()  # fast-simplification has native shared state.
GLTF_TO_WORKSPACE = trimesh.transformations.rotation_matrix(np.pi / 2, [1, 0, 0])
WORKSPACE_TO_GLTF = np.linalg.inv(GLTF_TO_WORKSPACE)


class EditorError(ValueError):
    def __init__(self, message, code="bad_arguments", *, params=None):
        super().__init__(message)
        self.code = code
        self.params = params or {}

    @classmethod
    def coded(cls, message_code, *, code=None, **params):
        """Raise-site sugar for the message-catalog path: renders `message_code`
        (via `studio.i18n.render`, in whatever language the current request set)
        and stores both the exposed `code` and the raw `params` on the instance,
        so a JSON error body can carry `params` alongside the already-rendered
        `message` without re-deriving them.

        `code` (the machine-readable value exposed as `self.code`/`error.code`)
        defaults to `message_code` itself. Pass it explicitly when several
        distinct catalog entries must all surface under one externally-visible
        protocol code — e.g. several different messages that each need
        `error.code == "revision_conflict"` for a client to treat them all as
        a stale-write conflict, even though their rendered text differs."""
        return cls(
            _render_message(message_code, **params), code=code if code is not None else message_code, params=params
        )


def _vector(value, size=3):
    try:
        result = np.asarray(value, dtype=float)
    except (TypeError, ValueError):
        raise EditorError.coded("editor.invalid_number") from None
    if result.shape != (size,) or not np.isfinite(result).all():
        raise EditorError.coded("editor.wrong_vector_size", size=size)
    return result


def _atomic(path, data):
    tmp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        tmp.write_bytes(data)
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)


def _glb_document(raw):
    if len(raw) < 20 or raw[:4] != b"glTF":
        raise EditorError.coded("editor.invalid_glb")
    size = int.from_bytes(raw[12:16], "little")
    return json.loads(raw[20 : 20 + size])


def _check_static(path):
    if path.suffix.lower() not in (".glb", ".gltf"):
        return
    doc = _glb_document(path.read_bytes()) if path.suffix.lower() == ".glb" else json.loads(path.read_text())
    if (
        doc.get("animations")
        or doc.get("skins")
        or any(p.get("targets") for m in doc.get("meshes", []) for p in m.get("primitives", []))
    ):
        raise EditorError.coded("editor.animated_mesh_rejected")
    for item in doc.get("buffers", []) + doc.get("images", []):
        uri = item.get("uri", "")
        if uri and not uri.startswith("data:") and ("://" in uri or uri.startswith("//")):
            raise EditorError.coded("editor.external_asset_reference")


def _mesh_ok(mesh):
    if not isinstance(mesh, trimesh.Trimesh) or not len(mesh.faces) or not np.isfinite(mesh.vertices).all():
        raise EditorError.coded("editor.invalid_triangle_mesh")
    if len(mesh.faces) > 5_000_000:
        raise EditorError.coded("editor.too_many_faces")


def _textured(mesh):
    return mesh.visual.kind == "texture" and any(
        getattr(mat, field, None) is not None
        for mat in _materials(mesh)
        for field in (
            "baseColorTexture",
            "metallicRoughnessTexture",
            "normalTexture",
            "emissiveTexture",
            "occlusionTexture",
            "image",
        )
    )


def _materials(mesh):
    material = getattr(mesh.visual, "material", None)
    return list(material.materials) if isinstance(material, MultiMaterial) else ([material] if material else [])


@lru_cache(maxsize=16)
def _read_mesh(path):
    scene = trimesh.load_scene(path, process=False)
    meshes = list(scene.geometry.values())
    if len(meshes) == 1:
        return geometry_store.restore(Path(path).read_bytes(), meshes[0])
    return scene.to_mesh()


@lru_cache(maxsize=256)
def _world_bounds(path, transform):
    points = trimesh.transform_points(_read_mesh(path).vertices, np.asarray(transform).reshape(4, 4))
    return np.array([points.min(axis=0), points.max(axis=0)])


class Workspace:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "assets").mkdir(exist_ok=True)
        (self.root / "exports").mkdir(exist_ok=True)
        self.path = self.root / "project.json"
        self.lock = threading.RLock()
        self.doc = (
            json.loads(self.path.read_text())
            if self.path.exists()
            else {
                "schema": SCHEMA,
                "revision": 0,
                "name": _render_message("editor.untitled_project"),
                "objects": [],
                "selection": [],
                "undo": [],
                "redo": [],
                "history": [],
            }
        )
        if self.doc.get("schema") != SCHEMA:
            raise EditorError.coded("editor.unsupported_project_format")

    def _snapshot(self, doc):
        return copy.deepcopy({k: doc[k] for k in ("objects", "selection", "name")})

    def _asset(self, mesh):
        _mesh_ok(mesh)
        raw = geometry_store.encode(mesh)
        digest = hashlib.sha256(raw).hexdigest()
        path = self.root / "assets" / (digest + ".glb")
        if not path.exists():
            _atomic(path, raw)
        return digest

    def asset_bytes(self, digest):
        with self.lock:
            if not re.fullmatch(r"[a-f0-9]{64}", digest) or not any(
                digest in motion_edit.assets([obj]) for obj in self.doc["objects"]
            ):
                raise EditorError.coded("stale_asset")
            return (self.root / "assets" / (digest + ".glb")).read_bytes()

    def mesh(self, obj, world=False):
        source = _read_mesh(str(self.root / "assets" / (obj["asset"] + ".glb")))
        mesh = source.copy()
        # Trimesh stores imported normals in its cache, which copy() discards.
        # Preserve authored shading across UV seams without sharing mutable
        # cache arrays or recomputing normals for sources that omit them.
        if "vertex_normals" in source._cache:
            mesh.vertex_normals = source.vertex_normals.copy()
        if world:
            mesh.apply_transform(obj["transform"])
        return mesh

    def _object(self, mesh, name, transform=None):
        return {
            "id": uuid.uuid4().hex,
            "name": str(name)[:160],
            "asset": self._asset(mesh),
            "transform": np.asarray(transform if transform is not None else np.eye(4)).tolist(),
            "visible": True,
        }

    def state(self):
        with self.lock:
            result = {k: copy.deepcopy(self.doc[k]) for k in ("schema", "revision", "name", "selection", "history")}
            result.update(can_undo=bool(self.doc["undo"]), can_redo=bool(self.doc["redo"]), objects=[])
            if self.root.parent.parent.name == ".3dstudio":
                result["project_folder"] = str(self.root.parent.parent.parent)
            boxes = []
            for obj in self.doc["objects"]:
                mesh = _read_mesh(str(self.root / "assets" / (obj["asset"] + ".glb")))
                bounds = _world_bounds(
                    str(self.root / "assets" / (obj["asset"] + ".glb")), tuple(np.asarray(obj["transform"]).flat)
                )
                if obj["visible"]:
                    boxes.append(bounds)
                result["objects"].append(
                    {
                        **copy.deepcopy(obj),
                        "faces": len(mesh.faces),
                        "bounds_mm": bounds.tolist(),
                        "extents_mm": (bounds[1] - bounds[0]).tolist(),
                        "textured": _textured(mesh),
                        "materials": scene_assets.materials(self, obj)
                        if obj.get("scene")
                        else material_edit.describe(mesh),
                        "asset_url": f"/api/editor-asset/{obj['asset']}.glb",
                    }
                )
            result["bounds_mm"] = (
                np.array([np.min(boxes, axis=(0, 1)), np.max(boxes, axis=(0, 1))]).tolist() if boxes else None
            )
            return collaboration.decorate_state(self.doc, result) if "collaboration" in self.doc else result

    def execute(self, body, actor="ai"):
        with self.lock, _KERNEL_LOCK:
            if "collaboration" in self.doc:
                return collaboration.execute(self, body, actor)
            if type(body.get("expected_revision")) is not int or body["expected_revision"] != self.doc["revision"]:
                raise EditorError.coded("editor.stale_project_revision", code="revision_conflict")
            action, p = body.get("action"), body.get("params", {})
            if not isinstance(p, dict):
                raise EditorError.coded("editor.params_must_be_object")
            doc = copy.deepcopy(self.doc)
            before = self._snapshot(doc)
            result = self._apply(doc, action, p)
            if len(doc["objects"]) > MAX_OBJECTS:
                raise EditorError.coded("editor.too_many_objects", max_objects=MAX_OBJECTS)
            # `editor_actions.ACTIONS` carries `snapshot`/`read_only` for every
            # action it registers; `city_`/`scene_`/`motion_` actions are
            # dispatched to sibling subsystems before `_apply` ever consults
            # that registry (see `_apply` below) and so are never in it — for
            # those, fall back to the same two action-name sets this method
            # used before the registry existed.
            spec = editor_actions.ACTIONS.get(action)
            needs_snapshot = spec.snapshot if spec is not None else action not in ("motion_export", "scene_export")
            if needs_snapshot:
                doc["undo"] = (doc["undo"] + [before])[-30:]
                doc["redo"] = []
            is_read_only = spec.read_only if spec is not None else action in ("city_catalog", "city_register")
            if not is_read_only:
                doc["revision"] += 1
                if action != "select":
                    doc["history"] = (
                        doc["history"]
                        + [
                            {
                                "action": action,
                                "actor": actor,
                                "at": datetime.now(timezone.utc).isoformat(),
                                "revision": doc["revision"],
                                "summary": result.get("summary", action),
                            }
                        ]
                    )[-100:]
                raw = json.dumps(doc, ensure_ascii=False, allow_nan=False).encode()
                _atomic(self.path, raw)
                self.doc = doc
            return {"ok": True, **result, "revision": doc["revision"], "print_submitted": False}

    def _selected(self, doc, p, minimum=1):
        ids = p.get("ids", doc["selection"])
        if not isinstance(ids, list) or any(not isinstance(i, str) for i in ids) or len(ids) != len(set(ids)):
            raise EditorError.coded("editor.ids_must_be_unique_list")
        by_id = {o["id"]: o for o in doc["objects"]}
        if any(i not in by_id for i in ids) or len(ids) < minimum:
            raise EditorError.coded("editor.select_minimum_objects", minimum=minimum)
        return [by_id[i] for i in ids]

    def _replace(self, doc, old, new):
        ids = {o["id"] for o in old}
        doc["objects"] = [o for o in doc["objects"] if o["id"] not in ids] + new
        doc["selection"] = [o["id"] for o in new]

    def _plain_geometry(self, obj, p):
        mesh = self.mesh(obj, world=True)
        colors = (
            getattr(mesh.visual, "vertex_colors", None)
            if mesh.visual.kind == "vertex"
            else (getattr(mesh.visual, "face_colors", None) if mesh.visual.kind == "face" else None)
        )
        multicolor = colors is not None and len(colors) and np.any(colors != colors[0])
        if (_textured(mesh) or multicolor or len(_materials(mesh)) > 1) and not p.get("allow_material_loss", False):
            raise EditorError.coded("editor.material_loss_requires_consent")
        # Welding is only used by topology-changing operations, not import.
        plain = trimesh.Trimesh(mesh.vertices, mesh.faces, process=True)
        color = [190, 199, 213, 255]
        if colors is not None and len(colors) and not multicolor:
            color = colors[0]
        elif len(_materials(mesh)) == 1:
            color = getattr(_materials(mesh)[0], "baseColorFactor", None)
            if color is None:
                color = [190, 199, 213, 255]
        plain.visual.face_colors = color
        return plain

    def _solid(self, mesh):
        if not mesh.is_volume:
            raise EditorError.coded("editor.solid_requires_closed_consistent_mesh")
        solid = manifold3d.Manifold(
            manifold3d.Mesh64(np.asarray(mesh.vertices), np.asarray(mesh.faces, dtype=np.uint64))
        )
        if solid.status() != manifold3d.Error.NoError:
            raise EditorError.coded("editor.manifold_read_failed")
        return solid

    def _from_solid(self, solid):
        if solid.is_empty() or solid.status() != manifold3d.Error.NoError:
            raise EditorError.coded("editor.operation_produced_no_solid")
        data = solid.to_mesh64()
        return trimesh.Trimesh(np.asarray(data.vert_properties)[:, :3], data.tri_verts, process=False)

    def _apply(self, doc, action, p):
        # city_/scene_/motion_ actions are owned by sibling subsystems, each
        # with its own action namespace; dispatch to them before ever
        # consulting the core action registry below.
        if isinstance(action, str) and action.startswith("city_"):
            return city.apply(self, doc, action, p)
        if action not in (
            "undo",
            "redo",
            "open",
            "import",
            "primitive",
            "save",
            "isolate",
            "show_all",
            "scene_import",
            "motion_import",
        ):
            city.guard(doc["objects"], self._selected(doc, p, minimum=0), action)
        if isinstance(action, str) and action.startswith("scene_"):
            return scene_assets.apply(self, doc, action, p)
        if isinstance(action, str) and action.startswith("motion_"):
            return motion_edit.apply(self, doc, action, p)

        # validate: look up the action, then apply the one cross-cutting
        # guard that spans multiple actions (stale motion/scene bindings).
        spec = editor_actions.ACTIONS.get(action)
        if spec is None:
            raise EditorError.coded("editor.unknown_action", action=action)
        if spec.blocks_motion_scene and any(
            (o.get("motion") or o.get("scene")) and not (action == "material" and o.get("scene"))
            for o in self._selected(doc, p)
        ):
            raise EditorError.coded("editor.motion_scene_binding_blocks_action")

        # run: each action function returns its own complete result dict, so
        # there is nothing left to post-process here.
        return spec.func(self, doc, p)

    def _transform(self, selected, p):
        if "matrix" in p:
            matrix = np.asarray(p["matrix"], dtype=float)
            if (
                len(selected) != 1
                or matrix.shape != (4, 4)
                or not np.isfinite(matrix).all()
                or not np.allclose(matrix[3], [0, 0, 0, 1])
            ):
                raise EditorError.coded("editor.matrix_must_be_single_object_affine")
            determinant = np.linalg.det(matrix[:3, :3])
            if determinant <= 1e-12:
                raise EditorError.coded("editor.degenerate_or_mirrored_transform")
            selected[0]["transform"] = matrix.tolist()
            return
        translate = _vector(p.get("translate_mm", [0, 0, 0]))
        rotate = np.deg2rad(_vector(p.get("rotate_deg", [0, 0, 0])))
        scale = _vector(p.get("scale", [1, 1, 1]))
        if np.any(scale <= 0) or np.any(scale > 1000):
            raise EditorError.coded("editor.scale_out_of_range")
        points = np.vstack([self.mesh(o, world=True).bounds for o in selected])
        center = (points.min(axis=0) + points.max(axis=0)) / 2
        t = trimesh.transformations.translation_matrix
        delta = (
            t(translate) @ t(center) @ trimesh.transformations.euler_matrix(*rotate) @ np.diag([*scale, 1]) @ t(-center)
        )
        for obj in selected:
            obj["transform"] = (delta @ np.asarray(obj["transform"])).tolist()

    def _geometry(self, doc, selected, action, p):
        meshes = [self._plain_geometry(obj, p) for obj in selected]
        if action == "plane_cut":
            if len(meshes) != 1:
                raise EditorError.coded("editor.plane_cut_single_object")
            normal = _vector(p.get("normal", [0, 0, 1]))
            if np.linalg.norm(normal) < 1e-9:
                raise EditorError.coded("editor.zero_cut_normal")
            normal /= np.linalg.norm(normal)
            point = _vector(p.get("point_mm", meshes[0].bounds.mean(axis=0)))
            positive, negative = self._solid(meshes[0]).split_by_plane(normal, float(normal @ point))
            outputs = [self._from_solid(solid) for solid in (positive, negative)]
            if not np.isclose(sum(m.volume for m in outputs), meshes[0].volume, rtol=1e-5, atol=1e-6):
                raise EditorError.coded("editor.cut_volume_check_failed")
        elif action in ("merge", "boolean"):
            if len(meshes) < 2:
                raise EditorError.coded("editor.merge_boolean_needs_two")
            if action == "merge":
                outputs = [trimesh.util.concatenate(meshes)]
            else:
                operation = p.get("operation", "union")
                if operation not in ("union", "difference", "intersection"):
                    raise EditorError.coded("editor.invalid_boolean_operation")
                solid = self._solid(meshes[0])
                for mesh in meshes[1:]:
                    other = self._solid(mesh)
                    solid = (
                        solid + other
                        if operation == "union"
                        else solid - other
                        if operation == "difference"
                        else solid ^ other
                    )
                outputs = [self._from_solid(solid)]
        else:
            outputs = []
            for mesh in meshes:
                if action == "split_components":
                    outputs.extend(mesh.split(only_watertight=False, repair=False))
                elif action == "repair":
                    mesh.update_faces(mesh.unique_faces() & mesh.nondegenerate_faces())
                    mesh.remove_unreferenced_vertices()
                    trimesh.repair.fix_normals(mesh, multibody=True)
                    trimesh.repair.fill_holes(mesh)
                    if p.get("require_watertight", False) and not mesh.is_watertight:
                        raise EditorError.coded("editor.repair_could_not_close_hole")
                    outputs.append(mesh)
                elif action == "simplify":
                    ratio = float(p.get("ratio", 0.5))
                    if not np.isfinite(ratio) or not 0 < ratio < 1:
                        raise EditorError.coded("editor.simplify_ratio_out_of_range")
                    reduced = mesh.simplify_quadric_decimation(face_count=max(4, int(len(mesh.faces) * ratio)))
                    if mesh.is_watertight and not reduced.is_watertight:
                        raise EditorError.coded("editor.simplify_introduced_opening")
                    outputs.append(reduced)
        if not outputs:
            raise EditorError.coded("editor.no_valid_output_mesh")
        name = selected[0]["name"]
        new = [self._object(mesh, f"{name} · {i + 1}" if len(outputs) > 1 else name) for i, mesh in enumerate(outputs)]
        self._replace(doc, selected, new)
        open_count = sum(not mesh.is_watertight for mesh in outputs)
        return {
            "output_count": len(new),
            "faces": sum(len(mesh.faces) for mesh in outputs),
            "warning": _render_message("editor.warning_open_outputs", open_count=open_count) if open_count else None,
        }

    def _output_path(self, p, suffix):
        path = (
            Path(p["path"]).expanduser() if p.get("path") else self.root / "exports" / (uuid.uuid4().hex[:12] + suffix)
        )
        if not path.is_absolute() or path.suffix.lower() != suffix or not path.parent.is_dir():
            raise EditorError.coded("editor.output_path_invalid", suffix=suffix)
        if path.exists():
            raise EditorError.coded("editor.output_path_exists")
        return path

    def _export(self, doc, p, action):
        selected = self._selected(doc, p) if "ids" in p else [o for o in doc["objects"] if o["visible"]]
        if any(o.get("city") for o in selected):
            raise EditorError.coded("editor.export_city_requires_project_save")
        if not selected:
            raise EditorError.coded("editor.export_nothing_selected")
        if action == "print_copy":
            paths = []
            for obj in selected:
                name = re.sub(r"[/\\\x00-\x1f]", "_", obj["name"])[:80].strip(". ") or "part"
                path = self._output_path(
                    {"path": str(self.root / "exports" / (name + "_" + uuid.uuid4().hex[:8] + ".stl"))}, ".stl"
                )
                raw = geometry_store.stl_bytes(self.mesh(obj, world=True))
                with path.open("xb") as f:
                    f.write(raw)
                paths.append(str(path))
            return {"summary": _render_message("editor.summary_print_copy_created"), "files": paths}
        fmt = p.get("format", "glb")
        if fmt not in ("glb", "stl"):
            raise EditorError.coded("editor.export_format_glb_or_stl")
        if fmt == "glb" and any(o.get("scene") for o in selected):
            raise EditorError.coded("editor.export_scene_requires_project_save")
        path = self._output_path(p, "." + fmt)
        scene = trimesh.Scene()
        used_names = set()
        for obj in selected:
            matrix = np.asarray(obj["transform"])
            if fmt == "glb":
                matrix = WORKSPACE_TO_GLTF @ matrix
                matrix[:3] *= 0.001
            name = obj["name"] if obj["name"] not in used_names else obj["name"] + "_" + obj["id"][:6]
            used_names.add(name)
            scene.add_geometry(self.mesh(obj), node_name=name, geom_name=obj["id"], transform=matrix)
        raw = scene.export(file_type="glb") if fmt == "glb" else geometry_store.stl_bytes(scene.to_mesh())
        with path.open("xb") as f:
            f.write(raw)
        # Decode the actual exported artifact before reporting success.
        reloaded = trimesh.load_scene(path, process=False)
        if not reloaded.geometry:
            raise EditorError.coded("editor.export_reload_failed")
        return {
            "summary": _render_message("editor.summary_exported", count=len(selected), format=fmt.upper()),
            "path": str(path),
            "warning": _render_message("editor.warning_stl_no_hierarchy") if fmt == "stl" else None,
        }

    def _open_archive(self, doc, p):
        path = Path(p.get("path", "")).expanduser()
        if not path.is_absolute() or not path.is_file() or path.stat().st_size > city.MAX_PACKAGE:
            raise EditorError.coded("editor.open_path_too_large_or_invalid")
        with zipfile.ZipFile(path) as z:
            infos = z.infolist()
            if len({i.filename for i in infos}) != len(infos) or sum(i.file_size for i in infos) > city.MAX_PACKAGE:
                raise EditorError.coded("editor.archive_duplicate_or_too_large")
            data = json.loads(z.read("manifest.json"))
            objects = data.get("objects")
            if data.get("schema") != SCHEMA or not isinstance(objects, list) or len(objects) > MAX_OBJECTS:
                raise EditorError.coded("editor.unsupported_project_format")
            ids = set()
            for obj in objects:
                asset, oid = obj.get("asset", ""), obj.get("id", "")
                if not re.fullmatch(r"[a-f0-9]{64}", asset) or not re.fullmatch(r"[a-f0-9]{32}", oid) or oid in ids:
                    raise EditorError.coded("editor.invalid_or_duplicate_object_identity")
                ids.add(oid)
                if not isinstance(obj.get("name"), str) or not isinstance(obj.get("visible"), bool):
                    raise EditorError.coded("editor.invalid_object_properties")
                self._transform([obj], {"matrix": obj.get("transform")})
                raw = z.read(f"assets/{asset}.glb")
                if hashlib.sha256(raw).hexdigest() != asset:
                    raise EditorError.coded("editor.mesh_checksum_failed")
                gltf = _glb_document(raw)
                if any(
                    item.get("uri") and not item["uri"].startswith("data:")
                    for item in gltf.get("images", []) + gltf.get("buffers", [])
                ):
                    raise EditorError.coded("editor.mesh_must_be_self_contained")
                scene = trimesh.load_scene(io.BytesIO(raw), file_type="glb", process=False)
                for mesh in scene.geometry.values():
                    _mesh_ok(mesh)
                target = self.root / "assets" / (asset + ".glb")
                if not target.exists():
                    _atomic(target, raw)
            for obj in objects:
                scene = obj.get("scene")
                if scene:
                    digest = scene.get("asset")
                    if not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest):
                        raise EditorError.coded("editor.scene_asset_id_invalid")
                    raw = z.read(f"assets/{digest}.glb")
                    if hashlib.sha256(raw).hexdigest() != digest:
                        raise EditorError.coded("editor.scene_asset_checksum_failed")
                    _atomic(self.root / "assets" / f"{digest}.glb", raw)
            scene_assets.validate(self, objects)
            city.archive(self, objects, z, read=True)
            for obj in objects:
                motion = obj.get("motion")
                if not motion:
                    continue
                for key, folder, suffix in [("asset", "assets", "glb"), ("blend_asset", "sources", "blend")]:
                    digest = motion.get(key)
                    if not digest:
                        continue
                    if not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest):
                        raise EditorError.coded("editor.motion_asset_id_invalid")
                    raw = z.read(f"{folder}/{digest}.{suffix}")
                    if hashlib.sha256(raw).hexdigest() != digest:
                        raise EditorError.coded("editor.motion_asset_checksum_failed")
                    directory = self.root / folder
                    directory.mkdir(exist_ok=True)
                    _atomic(directory / f"{digest}.{suffix}", raw)
            if any(o.get("motion") for o in objects):
                motion_edit.worker(objects)
                motion_edit.validate_assets(self, objects)
            selection = data.get("selection", [])
            if not isinstance(selection, list) or any(s not in ids for s in selection):
                raise EditorError.coded("editor.invalid_selection")
            doc.update(
                objects=objects,
                selection=selection,
                name=str(data.get("name", _render_message("editor.untitled_project")))[:160],
            )


# Imported at the bottom, once every name `editor_actions` needs (EditorError,
# `_vector`, `_mesh_ok`, ...) and the `Workspace` class itself are fully
# defined. `editor_actions` imports this module by name at its own top level;
# that only works because this import runs last — see the module docstring
# on `editor_actions.py` for the full explanation of the (safe) import cycle.
from studio.core import editor_actions  # noqa: E402
