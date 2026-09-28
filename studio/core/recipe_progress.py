"""Editor recipes track successful operations on the same selection and asset state.

These receipts mean an operation ran, not that an arbitrary textual acceptance
criterion passed. Unrelated geometry edits, selection changes and undo invalidate
receipts. No geometry is loaded or hashed during state polling.
"""

from __future__ import annotations

import copy
import hashlib
import json


def fingerprint(doc):
    objects = [{k: o.get(k) for k in ("id", "asset", "transform", "visible")} for o in doc.get("objects", [])]
    return hashlib.sha256(json.dumps([objects, doc.get("selection", [])], sort_keys=True).encode()).hexdigest()


def initial(doc):
    return {"fingerprint": fingerprint(doc), "completed": []}


def view(recipe, active, doc, busy=None):
    progress = active.get("editor_progress") or {}
    valid = progress.get("fingerprint") == fingerprint(doc)
    completed = set(progress.get("completed", [])) if valid else set()
    steps = copy.deepcopy(recipe["steps"])
    for step in steps:
        action = step["args"]["action"]
        done = bool(doc.get("objects")) if action == "import" else step["key"] in completed
        step["status"] = "pass" if done else "todo"
    required = [s for s in steps if not s["optional"]]
    next_step = next((s for s in required if s["status"] != "pass"), None)
    if next_step and busy and busy.get("op") == "edit":
        next_step["status"] = "running"
    return {
        "steps": steps,
        "next": next_step["key"] if next_step else None,
        "done": sum(s["status"] == "pass" for s in required),
        "total": len(required),
    }


def record(recipe, active, doc, request, result, selection_before):
    progress = active.setdefault("editor_progress", initial(doc))
    completed = progress.get("completed", [])
    action = request.get("action")
    # Find the expected step using the previously accepted receipts. The current
    # operation may already have changed geometry, so don't compare its new hash.
    target = next(
        (
            s
            for s in recipe["steps"]
            if not s["optional"] and s["args"]["action"] != "import" and s["key"] not in completed
        ),
        None,
    )
    matches = target and target["args"]["action"] == action
    if matches:
        presets = target["args"].get("params", {})
        supplied = request.get("params", {})
        matches = all(supplied.get(k) == v for k, v in presets.items())
        if "ids" in supplied:
            matches = matches and set(supplied["ids"]) == set(selection_before)
    if matches:
        progress["completed"] = [*completed, target["key"]]
    elif action not in ("inspect", "save", "export", "print_copy"):
        if progress.get("fingerprint") != fingerprint(doc) or action in ("undo", "redo", "open", "import"):
            progress["completed"] = []
    progress["fingerprint"] = fingerprint(doc)
