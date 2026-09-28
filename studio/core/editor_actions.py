"""Registry of `Workspace` editor actions.

`Workspace._apply` used to be one long if/elif chain keyed on the action
name (~270 lines). This module turns each action into a small, independently
readable function plus a declarative `ActionSpec`, so `_apply` itself becomes
a four-step dispatcher: validate (cross-subsystem guards) -> look up (this
registry) -> run (the action function) -> post-process (none needed, since
every action already returns its final, JSON-safe result).

`city_*`, `scene_*` and `motion_*` actions are NOT in this registry: `_apply`
dispatches those to `city.py` / `scene_assets.py` / `motion.py` before it ever
consults `ACTIONS` (each of those modules owns its own action names).

To add a new core editor action:

1. Write `def my_action(ws, doc, p) -> dict` below, next to the others. `ws`
   is the `Workspace`, `doc` is the mutable in-flight document (already
   deep-copied by `Workspace.execute`), `p` is the request's `params`. Raise
   `editor.EditorError` on bad input, exactly like the existing actions.
   Mutate `doc` in place for anything that changes the project, and return a
   result dict that includes a "summary" string (anything else in the dict
   is passed through to the caller unchanged).
2. Decorate it with `@action("my_action", ...)`, setting only the flags that
   differ from the defaults — see the field docstrings on `ActionSpec` for
   what each one means and which existing action to copy if you are unsure.
3. Add `"my_action"` to the `action` enum in `studio/shell/editor_schema.py`.
   `tests/test_editor_actions.py` asserts that this registry and that enum
   describe exactly the same set of actions (modulo the `city_`/`scene_`/
   `motion_` ones handled elsewhere), so the two can never silently drift.

This module imports from `studio.core.editor` at module scope; `editor.py`
imports this module only after `EditorError` and its other module-level
helpers are fully defined (see the bottom of `editor.py`), which is what
makes the import cycle safe.
"""

from __future__ import annotations

import copy
import json
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Callable

import numpy as np
import trimesh

from studio.core import city
from studio.core import materials as material_edit
from studio.core import motion as motion_edit
from studio.core import scene_assets
from studio.core.editor import GLTF_TO_WORKSPACE, MAX_BYTES, SCHEMA, EditorError, _check_static, _mesh_ok, _vector
from studio.i18n import render as _render_message

if TYPE_CHECKING:
    from studio.core.editor import Workspace


@dataclass(frozen=True)
class ActionSpec:
    """One entry in the editor action registry.

    Every field mirrors a property the pre-refactor `Workspace._apply`/
    `Workspace.execute` branched on for that specific action name — nothing
    here is aspirational or unused documentation.

    - `func`: `(ws, doc, p) -> dict`, see the module docstring.
    - `snapshot`: whether `Workspace.execute` pushes an undo snapshot before
      this action runs. False for actions that navigate history themselves
      (`undo`/`redo`), don't mutate the project (`select`, `inspect`), or
      write their own artifact instead of the live project (`export`,
      `print_copy`, `save`).
    - `requires_selection`: whether the action's body calls
      `ws._selected(doc, p)` with the default `minimum=1` — i.e. it needs at
      least one existing, addressable object (the current selection or
      explicit `ids`), not just a loaded (possibly empty) document.
    - `blocks_motion_scene`: whether `_apply` rejects the action up front
      when any selected object carries a motion rig or scene binding (the
      "此对象带动作绑定" guard). True for the geometry-mutating actions,
      where applying a stale rig/scene binding to new geometry would be
      unsafe.
    - `read_only`: whether the action leaves the document unchanged — no
      revision bump, no persisted write, no history entry. True only for
      `inspect`.
    """

    name: str
    func: Callable[["Workspace", dict, dict], dict]
    snapshot: bool = True
    requires_selection: bool = False
    blocks_motion_scene: bool = False
    read_only: bool = False


ACTIONS: dict[str, ActionSpec] = {}


def action(
    name: str,
    *,
    snapshot: bool = True,
    requires_selection: bool = False,
    blocks_motion_scene: bool = False,
    read_only: bool = False,
):
    """Register the decorated function as the handler for editor action `name`.

    See the module docstring for the 3-step recipe for adding a new action.
    """

    def register(func):
        if name in ACTIONS:
            raise RuntimeError(f"duplicate editor action registration: {name}")
        ACTIONS[name] = ActionSpec(
            name=name,
            func=func,
            snapshot=snapshot,
            requires_selection=requires_selection,
            blocks_motion_scene=blocks_motion_scene,
            read_only=read_only,
        )
        return func

    return register


def blocks_motion_scene(action_name: str) -> bool:
    """Whether `_apply`'s motion/scene-binding guard applies to this action."""
    spec = ACTIONS.get(action_name)
    return bool(spec and spec.blocks_motion_scene)


# --- history navigation -----------------------------------------------------


@action("undo", snapshot=False)
def undo(ws, doc, p):
    if not doc["undo"]:
        raise EditorError.coded("editor_actions.nothing_to_undo_redo")
    doc["redo"].append(ws._snapshot(doc))
    doc.update(doc["undo"].pop())
    return {"summary": _render_message("editor_actions.summary_undo")}


@action("redo", snapshot=False)
def redo(ws, doc, p):
    if not doc["redo"]:
        raise EditorError.coded("editor_actions.nothing_to_undo_redo")
    doc["undo"].append(ws._snapshot(doc))
    doc.update(doc["redo"].pop())
    return {"summary": _render_message("editor_actions.summary_redo")}


# --- project / object lifecycle ---------------------------------------------


@action("replace", requires_selection=True, blocks_motion_scene=True)
def replace(ws, doc, p):
    selected = ws._selected(doc, p)
    if len(selected) != 1 or len(p.get("files", [])) != 1:
        raise EditorError.coded("editor_actions.replace_needs_one_part_and_one_file")
    incoming = {**doc, "objects": [], "selection": []}
    ws._apply(incoming, "import", p)
    parts = incoming["objects"]
    parts[0]["id"] = selected[0]["id"]
    if len(parts) == 1:
        parts[0]["name"] = selected[0]["name"]
    ws._replace(doc, selected, parts)
    return {
        "summary": _render_message("editor_actions.summary_replaced_part", count=len(parts)),
        "created": doc["selection"],
    }


@action("import")
def import_files(ws, doc, p):
    files = p.get("files", [])
    if not isinstance(files, list) or not files or len(files) > 50:
        raise EditorError.coded("editor_actions.import_needs_1_to_50_paths")
    new = []
    for filename in files:
        path = Path(filename).expanduser()
        if not path.is_absolute() or not path.is_file() or path.stat().st_size > MAX_BYTES:
            raise EditorError.coded("editor_actions.import_path_must_exist_and_be_small")
        if path.suffix.lower() not in (".glb", ".gltf", ".stl", ".obj", ".ply", ".3mf"):
            raise EditorError.coded("editor_actions.import_unsupported_extension")
        _check_static(path)
        scene = trimesh.load_scene(path, process=False, allow_remote=False)
        gltf = path.suffix.lower() in (".glb", ".gltf")
        units = p.get("units", "auto")
        if units not in ("auto", "mm", "cm", "m"):
            raise EditorError.coded("editor_actions.invalid_units")
        factor = {"mm": 1, "cm": 10, "m": 1000}.get(units, 1000 if gltf else 1)
        conversion = GLTF_TO_WORKSPACE.copy() if gltf else np.eye(4)
        conversion[:3, :3] *= factor
        for node in scene.graph.nodes_geometry:
            transform, geom = scene.graph[node]
            mesh = scene.geometry[geom]
            _mesh_ok(mesh)
            name = (
                node
                if len(scene.graph.nodes_geometry) > 1 or node not in ("geometry_0", "world", "default")
                else path.stem
            )
            new.append(ws._object(mesh, name, conversion @ transform))
    if not new:
        raise EditorError.coded("editor_actions.no_editable_mesh_in_files")
    doc["objects"].extend(new)
    doc["selection"] = [o["id"] for o in new]
    if not doc["objects"][: -len(new)]:
        doc["name"] = Path(files[0]).stem
    return {"summary": _render_message("editor_actions.summary_imported", count=len(new)), "created": doc["selection"]}


@action("primitive")
def primitive(ws, doc, p):
    kind = p.get("kind", "box")
    size = _vector(p.get("size", [20, 20, 20]))
    if np.any(size <= 0) or np.any(size > 10000):
        raise EditorError.coded("editor_actions.primitive_size_out_of_range")
    if kind == "box":
        mesh = trimesh.creation.box(size)
    elif kind == "sphere":
        mesh = trimesh.creation.icosphere(subdivisions=3, radius=size[0] / 2)
    else:
        raise EditorError.coded("editor_actions.primitive_unsupported_kind")
    obj = ws._object(
        mesh,
        _render_message("editor_actions.default_box_name" if kind == "box" else "editor_actions.default_sphere_name"),
    )
    doc["objects"].append(obj)
    doc["selection"] = [obj["id"]]
    return {"summary": _render_message("editor_actions.summary_created", name=obj["name"])}


@action("open")
def open_project(ws, doc, p):
    ws._open_archive(doc, p)
    return {"summary": _render_message("editor_actions.summary_opened_project")}


@action("save", snapshot=False)
def save(ws, doc, p):
    city.validate(ws, doc["objects"])
    scene_assets.validate(ws, doc["objects"])
    if any(o.get("motion") for o in doc["objects"]):
        motion_edit.worker(doc["objects"])
        motion_edit.validate_assets(ws, doc["objects"])
    path = ws._output_path(p, ".3dworkbench")
    manifest = {"schema": SCHEMA, **ws._snapshot(doc)}
    with path.open("xb") as f, zipfile.ZipFile(f, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False))
        city.archive(ws, doc["objects"], z)
        for asset in motion_edit.assets(doc["objects"]):
            z.write(ws.root / "assets" / (asset + ".glb"), f"assets/{asset}.glb")
        for blend in {o.get("motion", {}).get("blend_asset") for o in doc["objects"]} - {None}:
            z.write(ws.root / "sources" / f"{blend}.blend", f"sources/{blend}.blend")
    return {"summary": _render_message("editor_actions.summary_saved_project_copy"), "path": str(path)}


@action("select", snapshot=False)
def select(ws, doc, p):
    doc["selection"] = [o["id"] for o in ws._selected(doc, p, minimum=0)]
    return {"summary": _render_message("editor_actions.summary_selection_updated")}


@action("show_all")
def show_all(ws, doc, p):
    for obj in doc["objects"]:
        obj["visible"] = True
    return {"summary": _render_message("editor_actions.summary_show_all")}


@action("export", snapshot=False)
def export(ws, doc, p):
    return ws._export(doc, p, "export")


@action("print_copy", snapshot=False)
def print_copy(ws, doc, p):
    return ws._export(doc, p, "print_copy")


# --- selection-based edits ---------------------------------------------------


@action("rename", requires_selection=True)
def rename(ws, doc, p):
    selected = ws._selected(doc, p)
    name = p.get("name", "").strip()
    if len(selected) != 1 or not name or len(name) > 160:
        raise EditorError.coded("editor_actions.rename_needs_one_object_and_name")
    selected[0]["name"] = name
    return {"summary": _render_message("editor_actions.summary_renamed", count=len(selected))}


@action("visibility", requires_selection=True)
def visibility(ws, doc, p):
    selected = ws._selected(doc, p)
    if not isinstance(p.get("visible"), bool):
        raise EditorError.coded("editor_actions.visible_must_be_boolean")
    for obj in selected:
        obj["visible"] = p["visible"]
    return {"summary": _render_message("editor_actions.summary_visibility_changed", count=len(selected))}


@action("isolate", requires_selection=True)
def isolate(ws, doc, p):
    selected = ws._selected(doc, p)
    ids = {o["id"] for o in selected}
    for obj in doc["objects"]:
        obj["visible"] = obj["id"] in ids
    return {"summary": _render_message("editor_actions.summary_isolated", count=len(selected))}


@action("delete", requires_selection=True)
def delete(ws, doc, p):
    selected = ws._selected(doc, p)
    ws._replace(doc, selected, [])
    return {"summary": _render_message("editor_actions.summary_deleted", count=len(selected))}


@action("duplicate", requires_selection=True)
def duplicate(ws, doc, p):
    selected = ws._selected(doc, p)
    new = copy.deepcopy(selected)
    mapping = {o["id"]: uuid.uuid4().hex for o in new}
    for obj in new:
        obj.update(id=mapping[obj["id"]], name=obj["name"] + _render_message("editor_actions.duplicate_suffix"))
        if obj.get("motion", {}).get("kind") == "joint":
            joint = obj["motion"]["joint"]
            joint["parent"] = mapping.get(joint.get("parent"), joint.get("parent"))
            obj["motion"]["bindings"] = {mapping.get(k, k): v for k, v in obj["motion"].get("bindings", {}).items()}
    doc["objects"].extend(new)
    doc["selection"] = [o["id"] for o in new]
    return {"summary": _render_message("editor_actions.summary_duplicated", count=len(selected))}


@action("transform", requires_selection=True)
def transform(ws, doc, p):
    selected = ws._selected(doc, p)
    ws._transform(selected, p)
    for obj in selected:
        if obj.get("city_link"):
            basis = np.asarray(obj["transform"])[:3, :3]
            basis = basis / np.linalg.norm(basis, axis=0)
            if not np.allclose(basis.T @ basis, np.eye(3), atol=1e-6):
                raise EditorError.coded("editor_actions.city_instance_no_shear")
    return {"summary": _render_message("editor_actions.summary_transformed", count=len(selected))}


@action("extract_faces", requires_selection=True, blocks_motion_scene=True)
def extract_faces(ws, doc, p):
    selected = ws._selected(doc, p)
    if len(selected) != 1:
        raise EditorError.coded("editor_actions.extract_faces_needs_one_object")
    obj = selected[0]
    mesh = ws.mesh(obj)
    if "face_ids" in p:
        indices = p["face_ids"]
        if not isinstance(indices, list) or any(type(i) is not int or not 0 <= i < len(mesh.faces) for i in indices):
            raise EditorError.coded("editor_actions.invalid_face_ids")
        mask = np.zeros(len(mesh.faces), dtype=bool)
        mask[indices] = True
    else:
        point = _vector(p.get("point_mm"))
        radius = float(p.get("radius_mm", 0))
        if not np.isfinite(radius) or not 0 < radius <= 10000:
            raise EditorError.coded("editor_actions.extract_faces_radius_out_of_range")
        centers = trimesh.transform_points(mesh.triangles_center, np.asarray(obj["transform"]))
        mask = np.linalg.norm(centers - point, axis=1) <= radius
    if not mask.any() or mask.all():
        raise EditorError.coded("editor_actions.extract_faces_needs_partial_selection")
    new = [
        ws._object(mesh.submesh([np.flatnonzero(m)], append=True, repair=False), obj["name"] + suffix, obj["transform"])
        for m, suffix in [
            (mask, _render_message("editor_actions.suffix_region")),
            (~mask, _render_message("editor_actions.suffix_remainder")),
        ]
    ]
    ws._replace(doc, selected, new)
    return {
        "summary": _render_message("editor_actions.summary_extract_faces"),
        "faces_extracted": int(mask.sum()),
        "capped": False,
        "created": [x["id"] for x in new],
    }


@action("material", requires_selection=True, blocks_motion_scene=True)
def material(ws, doc, p):
    selected = ws._selected(doc, p)
    if p.get("material_slots") is not None and len(selected) != 1:
        raise EditorError.coded("editor_actions.material_slot_edit_needs_one_object")
    for obj in selected:
        if obj.get("scene"):
            scene_assets.edit_material(ws, obj, p)
        else:
            obj["asset"] = ws._asset(material_edit.edit(ws.mesh(obj), p))
    return {"summary": _render_message("editor_actions.summary_material_changed", count=len(selected))}


@action("inspect", requires_selection=True, snapshot=False, read_only=True)
def inspect(ws, doc, p):
    selected = ws._selected(doc, p)
    reports = []
    for obj in selected:
        source = ws.mesh(obj, world=True)
        # Inspect geometric connectivity, not UV islands. Materialized
        # submeshes copy each texture once per component and can exhaust
        # memory on ordinary atlased meshes. Keep this geometry-only.
        mesh = trimesh.Trimesh(source.vertices, source.faces, process=False)
        mesh.merge_vertices()
        counts = np.bincount(mesh.edges_unique_inverse)
        components = trimesh.graph.connected_components(mesh.face_adjacency, nodes=np.arange(len(mesh.faces)))
        reports.append(
            {
                "id": obj["id"],
                "name": obj["name"],
                "faces": len(mesh.faces),
                "watertight": bool(mesh.is_watertight),
                "winding_consistent": bool(mesh.is_winding_consistent),
                "boundary_edges": int(np.count_nonzero(counts == 1)),
                "nonmanifold_edges": int(np.count_nonzero(counts > 2)),
                "components": len(components),
                "volume_mm3": float(mesh.volume) if mesh.is_volume else None,
            }
        )
    return {"summary": _render_message("editor_actions.summary_inspected"), "reports": reports}


# --- geometry kernel actions (share Workspace._geometry) ---------------------


@action("plane_cut", requires_selection=True, blocks_motion_scene=True)
def plane_cut(ws, doc, p):
    details = ws._geometry(doc, ws._selected(doc, p), "plane_cut", p)
    return {"summary": _render_message("editor_actions.summary_plane_cut"), **details}


@action("split_components", requires_selection=True, blocks_motion_scene=True)
def split_components(ws, doc, p):
    details = ws._geometry(doc, ws._selected(doc, p), "split_components", p)
    return {"summary": _render_message("editor_actions.summary_split_components"), **details}


@action("repair", requires_selection=True, blocks_motion_scene=True)
def repair(ws, doc, p):
    details = ws._geometry(doc, ws._selected(doc, p), "repair", p)
    return {"summary": _render_message("editor_actions.summary_repair"), **details}


@action("simplify", requires_selection=True, blocks_motion_scene=True)
def simplify(ws, doc, p):
    details = ws._geometry(doc, ws._selected(doc, p), "simplify", p)
    return {"summary": _render_message("editor_actions.summary_simplify"), **details}


@action("merge", requires_selection=True, blocks_motion_scene=True)
def merge(ws, doc, p):
    details = ws._geometry(doc, ws._selected(doc, p), "merge", p)
    return {"summary": _render_message("editor_actions.summary_merge"), **details}


@action("boolean", requires_selection=True, blocks_motion_scene=True)
def boolean(ws, doc, p):
    details = ws._geometry(doc, ws._selected(doc, p), "boolean", p)
    return {"summary": _render_message("editor_actions.summary_boolean"), **details}
