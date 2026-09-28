"""Three-way, per-object merge. Geometry is never implicitly merged."""

from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from pathlib import Path

from studio.core.editor import EditorError, MAX_OBJECTS, _atomic
from studio.i18n import render as _render_message


def changes(base_objects, incoming_objects, current_objects):
    base, incoming, current = (
        {o["id"]: o for o in objects} for objects in (base_objects, incoming_objects, current_objects)
    )
    changed = [key for key in base.keys() | incoming.keys() if base.get(key) != incoming.get(key)]
    conflicts = [key for key in changed if current.get(key) not in (base.get(key), incoming.get(key))]
    if conflicts:
        raise EditorError.coded("branch_conflict", conflicts=", ".join(sorted(conflicts)))
    actual = [key for key in changed if current.get(key) != incoming.get(key)]
    merged = [copy.deepcopy(o) for o in current_objects if o["id"] not in actual]
    merged += [copy.deepcopy(incoming[key]) for key in sorted(actual) if key in incoming]
    return merged, actual


def merge(workspace, body, actor):
    from studio.core.workspaces import copy_assets

    with workspace.lock:
        if type(body.get("expected_revision")) is not int or body["expected_revision"] != workspace.doc["revision"]:
            raise EditorError.coded("branches.stale_source_revision", code="revision_conflict")
        incoming = body["objects"]
        objects, changed = changes(body["base_objects"], incoming, workspace.doc["objects"])
        if len(objects) > MAX_OBJECTS:
            raise EditorError.coded("branches.merge_exceeds_object_limit")
        if not changed:
            return {"ok": True, "revision": workspace.doc["revision"], "merged_ids": []}
        copy_assets([o for o in incoming if o["id"] in changed], Path(body["asset_root"]), workspace.root / "assets")
        from studio.core.city import validate

        validate(workspace, objects)
        if "collaboration" in workspace.doc:
            from studio.core import collaboration

            result = collaboration.execute(
                workspace,
                {"action": "branch_merge", "expected_revision": body["expected_revision"], "params": {"ids": changed}},
                actor,
                merged_objects=objects,
            )
            return {**result, "merged_ids": sorted(changed)}
        doc = copy.deepcopy(workspace.doc)
        doc["undo"] = (doc["undo"] + [workspace._snapshot(doc)])[-30:]
        doc["redo"] = []
        doc["objects"] = objects
        ids = {o["id"] for o in objects}
        doc["selection"] = [key for key in doc["selection"] if key in ids]
        doc["revision"] += 1
        doc["history"] = (
            doc["history"]
            + [
                {
                    "action": "branch_merge",
                    "actor": actor,
                    "at": datetime.now(timezone.utc).isoformat(),
                    "revision": doc["revision"],
                    "summary": _render_message(
                        "branches.summary_merged", branch_id=body["branch_id"], count=len(changed)
                    ),
                }
            ]
        )[-100:]
        _atomic(workspace.path, json.dumps(doc, ensure_ascii=False, allow_nan=False).encode())
        workspace.doc = doc
        return {"ok": True, "revision": doc["revision"], "merged_ids": sorted(changed)}
