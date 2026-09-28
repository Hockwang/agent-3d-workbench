"""Shared model transactions; chat identity and view state stay separate.

All state is committed with the project document under Workspace.lock. Leases
are advisory ownership, versions remain mandatory after lease expiry.
"""

from __future__ import annotations

import copy
import json
import secrets
import time
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path

from studio.i18n import render as _render_message

SESSION = ContextVar("studio_session", default=None)
LEASE_SECONDS = 300
READ_ACTIONS = {
    "inspect",
    "export",
    "save",
    "print_copy",
    "motion_export",
    "scene_export",
    "city_catalog",
    "city_register",
}
PART_ACTIONS = {
    "scene_replace",
    "motion_set",
    "motion_clear",
    "replace",
    "rename",
    "transform",
    "material",
    "repair",
    "simplify",
    "plane_cut",
    "split_components",
    "extract_faces",
    "duplicate",
    "delete",
    "merge",
    "boolean",
    "visibility",
}


def fail(message_code, code=None, **params):
    """Render `message_code` from the message catalog and raise it as an
    `EditorError`. `code` is the machine-readable value exposed as
    `error.code` in the JSON response; it defaults to `message_code` itself,
    but every call site here passes it explicitly because several distinct
    catalog entries share one externally-visible protocol code (several
    different messages must all surface as e.g. `error.code ==
    "scope_violation"`).

    `studio.shell.part_chat` calls this too, with its own `part_chat.*` codes
    from `studio/shell/messages.py`. A string that is not a registered code is
    returned by `studio.i18n.render()` unchanged, so a caller can still pass a
    literal message in a pinch — but every shipped call site uses a code."""
    from studio.core.editor import EditorError

    raise EditorError.coded(message_code, code=code, **params)


def member(doc):
    session = SESSION.get()
    value = doc["collaboration"]["members"].get(session)
    if value is None:
        fail("collaboration.session_not_joined", "session_unbound")
    return session, value


def persist(workspace, doc):
    from studio.core.editor import _atomic

    _atomic(workspace.path, json.dumps(doc, ensure_ascii=False, allow_nan=False).encode())
    workspace.doc = doc


def canonical_worktree(value):
    if not isinstance(value, str) or not value or not Path(value).is_absolute() or not Path(value).is_dir():
        fail("collaboration.invalid_worktree", "bad_arguments")
    return str(Path(value).resolve())


def empty_member(selection=(), scope=None):
    return {"selection": list(selection), "scope": scope, "undo": [], "redo": [], "view_revision": 0}


def check_leases(collab, ids, session):
    now = time.time()
    for key in ids:
        lease = collab["leases"].get(key)
        if lease and lease["session"] != session and lease["expires_at"] > now:
            fail("part_locked", part=key, session=lease["session"])


def _join(doc, session, invitation, worktree):
    collab = doc["collaboration"]
    if canonical_worktree(worktree) != collab["worktree"]:
        fail("collaboration.worktree_mismatch_branch_hint", "worktree_mismatch")
    invite = collab["invitations"].get(invitation)
    if not invite or invite["joined_by"] not in (None, session):
        fail("collaboration.invitation_invalid_or_expired", "invalid_invitation")
    if session in collab["members"]:
        if invite["joined_by"] != session:
            fail("collaboration.scope_already_bound", "scope_violation")
        return
    if invite["expires_at"] <= time.time():
        fail("collaboration.invitation_invalid_or_expired", "invalid_invitation")
    check_leases(collab, invite["ids"], session)
    for key, version in invite["versions"].items():
        if collab["versions"].get(key) != version:
            fail("collaboration.invitation_stale", "revision_conflict")
    collab["members"][session] = empty_member(invite["ids"], invite["ids"])
    invite["joined_by"] = session
    for key in invite["ids"]:
        collab["leases"][key] = {"session": session, "expires_at": time.time() + LEASE_SECONDS}


def join_verified_child(workspace, child_id, invitation, worktree):
    """Internal bridge coordinator; caller has verified official fork identity.

    Unlike public join, the current SESSION remains the parent. The page has
    no endpoint accepting child_id or this action.
    """
    from studio.core.workspaces import validate_id

    with workspace.lock:
        doc = copy.deepcopy(workspace.doc)
        parent, view = member(doc)
        invite = doc["collaboration"]["invitations"].get(invitation)
        if not invite or invite.get("created_by") != parent:
            fail("collaboration.invitation_not_owned", "invalid_invitation")
        if view["scope"] is not None and not set(invite["ids"]).issubset(view["scope"]):
            fail("collaboration.scope_outside_binding", "scope_violation")
        _join(doc, validate_id(child_id), invitation, worktree)
        persist(workspace, doc)
        return {"ok": True, "worktree": worktree, "scope": doc["collaboration"]["members"][child_id]["scope"]}


def control(workspace, body):
    from studio.core.workspaces import validate_id

    with workspace.lock:
        session = validate_id(SESSION.get())
        action = body.get("action")
        doc = copy.deepcopy(workspace.doc)
        collab = doc.get("collaboration")
        if action == "project_join":
            worktree = canonical_worktree(body.get("worktree"))
            if workspace.root.resolve() != (Path(worktree) / ".3dstudio/job/workbench").resolve():
                fail("collaboration.backend_worktree_mismatch", "worktree_mismatch")
            if not collab:
                collab = doc["collaboration"] = {
                    "worktree": worktree,
                    "owner": session,
                    "members": {},
                    "versions": {o["id"]: 0 for o in doc["objects"]},
                    "leases": {},
                    "invitations": {},
                }
            if collab["worktree"] != worktree:
                fail("collaboration.worktree_mismatch_plain", "worktree_mismatch")
            # Idempotent; a part-chat scope must never be widened by reconnect.
            collab["members"].setdefault(session, empty_member())
            persist(workspace, doc)
            return {"ok": True, "scope": collab["members"][session]["scope"], "worktree": worktree}
        if action == "invite":
            worktree = canonical_worktree(body.get("worktree"))
            if body.get("expected_revision") != doc["revision"]:
                fail("collaboration.project_changed_for_invite", "revision_conflict")
            part = next((o for o in doc["objects"] if o["id"] == body.get("object_id")), None)
            if part is None:
                fail("collaboration.pick_existing_part", "bad_arguments")
            if not collab:
                collab = doc["collaboration"] = {
                    "worktree": worktree,
                    "owner": session,
                    "members": {session: empty_member(doc["selection"])},
                    "versions": {o["id"]: 0 for o in doc["objects"]},
                    "leases": {},
                    "invitations": {},
                }
            current, view = member(doc)
            if collab["worktree"] != worktree:
                fail("collaboration.worktree_mismatch_branch_hint", "worktree_mismatch")
            if view["scope"] is not None and part["id"] not in view["scope"]:
                fail("collaboration.scope_own_parts_only", "scope_violation")
            check_leases(collab, [part["id"]], current)
            # Explicitly handing this part to a new chat releases our lease.
            collab["leases"].pop(part["id"], None)
            invitation = secrets.token_urlsafe(24)
            collab["invitations"] = {k: v for k, v in collab["invitations"].items() if v["expires_at"] > time.time()}
            collab["invitations"][invitation] = {
                "ids": [part["id"]],
                "expires_at": time.time() + 3600,
                "versions": {part["id"]: collab["versions"][part["id"]]},
                "joined_by": None,
                "created_by": session,
            }
            persist(workspace, doc)
            return {
                "ok": True,
                "invitation": invitation,
                "object_id": part["id"],
                "name": part["name"],
                "worktree": worktree,
                "revision": doc["revision"],
            }
        if not collab:
            fail("collaboration.no_collaboration_session", "session_unbound")
        if action == "join":
            _join(doc, session, body.get("invitation"), body.get("worktree"))
        elif action in ("renew", "release"):
            _, view = member(doc)
            ids = body.get("ids", view["scope"] or view["selection"])
            if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
                fail("collaboration.ids_must_be_part_list", "bad_arguments")
            existing = {o["id"] for o in doc["objects"]}
            if any(i not in existing or (view["scope"] is not None and i not in view["scope"]) for i in ids):
                fail("collaboration.scope_outside_operation", "scope_violation")
            if action == "renew":
                for key in ids:
                    # A delayed heartbeat must not reacquire a released part or
                    # interfere with the next editor. Editing acquires leases;
                    # renewal only extends an existing lease owned by us.
                    if collab["leases"].get(key, {}).get("session") == session:
                        collab["leases"][key]["expires_at"] = time.time() + LEASE_SECONDS
            else:
                for key in ids:
                    if collab["leases"].get(key, {}).get("session") == session:
                        collab["leases"].pop(key)
        else:
            fail("collaboration.unknown_operation", "bad_arguments")
        persist(workspace, doc)
        return {
            "ok": True,
            "session_id": session,
            "scope": collab["members"][session]["scope"],
            "worktree": collab["worktree"],
            "revision": doc["revision"],
        }


def decorate_state(doc, state):
    session, view = member(doc)
    c = doc["collaboration"]
    existing = {o["id"] for o in doc["objects"]}
    state.update(
        selection=[i for i in view["selection"] if i in existing],
        can_undo=bool(view["undo"]),
        can_redo=bool(view["redo"]),
        view_revision=view["view_revision"],
        collaboration={
            "session_id": session,
            "worktree": c["worktree"],
            "scope": view["scope"],
            "members": len(c["members"]),
        },
    )
    for obj in state["objects"]:
        obj["version"] = c["versions"][obj["id"]]
        lease = c["leases"].get(obj["id"])
        obj["lease"] = copy.deepcopy(lease) if lease and lease["expires_at"] > time.time() else None
    return state


def execute(workspace, body, actor, merged_objects=None):
    """Called under editor + geometry locks. No partial document commits."""
    from studio.core.editor import MAX_OBJECTS

    doc = copy.deepcopy(workspace.doc)
    session, view = member(doc)
    c = doc["collaboration"]
    action, params = body.get("action"), copy.deepcopy(body.get("params", {}))
    if not isinstance(params, dict):
        fail("collaboration.params_must_be_object", "bad_arguments")
    original_selection = doc["selection"]
    doc["selection"] = [i for i in view["selection"] if any(o["id"] == i for o in doc["objects"])]
    before = {o["id"]: copy.deepcopy(o) for o in doc["objects"]}
    if action == "select":
        result = workspace._apply(doc, action, params)
        view["selection"] = doc["selection"]
        view["view_revision"] += 1
        doc["selection"] = original_selection
        persist(workspace, doc)
        return {"ok": True, **result, "revision": doc["revision"]}
    if action in READ_ACTIONS:
        return {"ok": True, **workspace._apply(doc, action, params), "revision": doc["revision"]}
    if action == "open":
        fail("collaboration.scope_no_full_replace", "scope_violation")
    if action in ("undo", "redo"):
        stack = view[action]
        if not stack:
            fail("collaboration.nothing_to_undo_redo", "bad_arguments")
        transaction = stack[-1]
        for key, version in transaction["expected"].items():
            if c["versions"].get(key, 0) != version:
                fail("collaboration.parts_modified_by_others", "revision_conflict")
        affected = set(transaction["expected"])
        check_leases(c, affected, session)
        doc["objects"] = [o for o in doc["objects"] if o["id"] not in affected] + list(
            copy.deepcopy(transaction["restore"]).values()
        )
        result = {
            "summary": _render_message(
                "collaboration.summary_chat_undo" if action == "undo" else "collaboration.summary_chat_redo"
            )
        }
    else:
        targets = params.get("ids", doc["selection"])
        if not isinstance(targets, list) or not all(isinstance(i, str) for i in targets):
            fail("collaboration.ids_must_be_part_list", "bad_arguments")
        if view["scope"] is not None:
            if action not in PART_ACTIONS or not targets or any(i not in view["scope"] for i in targets):
                fail("collaboration.scope_bound_and_derived_only", "scope_violation")
        dependencies = (
            set(before)
            if action in {"isolate", "show_all"}
            else set(targets)
            if action in PART_ACTIONS or action == "branch_merge"
            else set()
        )
        if action in {"motion_set", "motion_clear", "scene_replace"}:
            from studio.core.motion import dependencies as motion_dependencies

            dependencies |= motion_dependencies(doc["objects"], targets, params.get("motion"))
            if view["scope"] is not None and not dependencies.issubset(set(view["scope"])):
                fail("collaboration.scope_parent_child_mechanism", "scope_violation")
        check_leases(c, dependencies, session)
        if type(body.get("expected_revision")) is not int:
            fail("collaboration.expected_revision_required", "revision_conflict")
        versions = body.get("expected_versions")
        if versions is not None:
            if not isinstance(versions, dict) or any(
                type(versions.get(i)) is not int or versions[i] != c["versions"].get(i) for i in dependencies
            ):
                fail("collaboration.parts_changed_reread", "revision_conflict")
        elif body["expected_revision"] != doc["revision"]:
            fail("collaboration.project_changed_reread_or_versions", "revision_conflict")
        if action == "branch_merge" and merged_objects is not None:
            doc["objects"] = copy.deepcopy(merged_objects)
            result = {"summary": _render_message("collaboration.summary_branch_merged")}
        else:
            result = workspace._apply(doc, action, params)
    if len(doc["objects"]) > MAX_OBJECTS:
        fail("collaboration.too_many_objects", "bad_arguments", max_objects=MAX_OBJECTS)
    after = {o["id"]: o for o in doc["objects"]}
    affected = {i for i in before.keys() | after.keys() if before.get(i) != after.get(i)}
    check_leases(c, affected, session)
    prior_versions = {i: c["versions"].get(i, 0) for i in affected}
    for key in affected:
        c["versions"][key] = c["versions"].get(key, 0) + 1
        c["leases"][key] = {"session": session, "expires_at": time.time() + LEASE_SECONDS}
    if affected:
        inverse = {
            "restore": {i: before[i] for i in affected if i in before},
            "expected": {i: c["versions"][i] for i in affected},
            "prior_versions": prior_versions,
        }
        if action in ("undo", "redo"):
            view[action].pop()
            # Rebase the nearest inverse for each part, skipping unrelated
            # edits. Never bridge a version gap caused by another session.
            for key in affected:
                for prior in reversed(view[action]):
                    expected = prior["expected"]
                    if key in expected:
                        if expected[key] == transaction.get("prior_versions", {}).get(key):
                            expected[key] = c["versions"][key]
                        break
            target = "redo" if action == "undo" else "undo"
            view[target] = (view[target] + [inverse])[-30:]
        else:
            view["undo"] = (view["undo"] + [inverse])[-30:]
            view["redo"] = []
        if view["scope"] is not None:
            view["scope"] = sorted(set(view["scope"]) | (after.keys() - before.keys()))
        doc["revision"] += 1
        doc["history"] = (
            doc["history"]
            + [
                {
                    "action": action,
                    "actor": actor,
                    "session_id": session,
                    "at": datetime.now(timezone.utc).isoformat(),
                    "revision": doc["revision"],
                    "summary": result.get("summary", action),
                }
            ]
        )[-100:]
    view["selection"] = [i for i in doc["selection"] if i in after]
    view["view_revision"] += 1
    doc["selection"] = [i for i in original_selection if i in after]
    persist(workspace, doc)
    return {"ok": True, **result, "revision": doc["revision"], "print_submitted": False}
