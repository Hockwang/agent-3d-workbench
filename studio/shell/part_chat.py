"""User-authorized direct part chat coordinator; state lives outside model history."""

from __future__ import annotations

import contextlib
import json
import time
import uuid

from studio.core import collaboration as c, filelock, workspaces
from studio.shell.codex_bridge import CodexBridge, identity
from studio.core.editor import _atomic
from studio.i18n import render

SCHEMA = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": ["status", "allow", "deny", "create"]},
        "object_id": {"type": "string"},
        "operation_id": {"type": "string", "format": "uuid"},
        "expected_revision": {"type": "integer"},
        # Authenticates a workbench-UI-originated call as actor="human"; the MCP
        # server strips it before this module ever sees the request body (see
        # mcp_server.py's studio_part_chat handling), so it never reaches `handle`.
        "ui_nonce": {"type": "string"},
    },
    "required": ["action"],
    "additionalProperties": False,
}


def _read(path, default):
    return json.loads(path.read_text()) if path.exists() else default


def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic(path, json.dumps(data, ensure_ascii=False, allow_nan=False).encode())


@contextlib.contextmanager
def _lock(root):
    root.mkdir(parents=True, exist_ok=True)
    with (root / ".lock").open("a") as file:
        filelock.lock(file)
        yield


def _public(operation):
    child = operation.get("child_id")
    return {
        k: v
        for k, v in operation.items()
        if k in ("operation_id", "object_id", "name", "status", "child_id", "message")
    } | {"url": f"codex://threads/{child}" if child else None}


def _verify_thread(thread, expected_id, cwd=None, parent=None):
    if thread.get("id") != expected_id:
        c.fail("part_chat.bridge_identity_mismatch", "bridge_identity")
    actual = c.canonical_worktree(thread.get("cwd"))
    if cwd and actual != cwd:
        c.fail("part_chat.worktree_mismatch_reauth", "worktree_mismatch")
    if parent and thread.get("forkedFromId") != parent:
        c.fail("part_chat.fork_source_mismatch", "bridge_identity")
    return actual


def handle(workspace, body, actor):
    """Only the current workspace's authenticated UI may grant/create.

    The child ID comes exclusively from official RPC, never from the page.
    join_verified_child is an internal coordinator operation, not a public
    collaboration action impersonating the child's own session header.
    """
    if actor != "human":
        c.fail("part_chat.human_required", "human_required")
    parent_id = workspaces.validate_id(c.SESSION.get())
    if workspace.root.resolve() != (workspaces.job_dir(parent_id) / "workbench").resolve():
        c.fail("part_chat.session_unbound", "session_unbound")
    action = body.get("action")
    if set(body) - set(SCHEMA["properties"]) or action not in SCHEMA["properties"]["action"]["enum"]:
        c.fail("part_chat.bad_action", "bad_arguments")
    with workspace.lock:
        if workspace.doc.get("collaboration"):
            c.member(workspace.doc)
    root = workspaces.home(parent_id) / "part-chat"
    with _lock(root):
        permission_path = root / "permission.json"
        permission = _read(permission_path, {"decision": "ask"})
        operations = root / "operations"
        if action == "deny":
            _write(permission_path, {"decision": "denied"})
            return {"ok": True, "decision": "denied", "enabled": False}
        try:
            adapter = identity()
        except Exception as error:
            if action != "status":
                raise
            return {
                "ok": True,
                "decision": permission["decision"],
                "enabled": False,
                "available": False,
                "message": str(error),
                "operations": [],
            }
        same_adapter = permission.get("adapter") == adapter
        enabled = permission["decision"] == "allowed" and same_adapter
        if action == "status":
            recent = sorted(operations.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:20]
            return {
                "ok": True,
                "decision": permission["decision"] if same_adapter or permission["decision"] != "allowed" else "ask",
                "enabled": enabled,
                "available": True,
                "operations": [_public(_read(p, {})) for p in recent],
            }
        if action == "create" and not enabled:
            c.fail("part_chat.permission_required", "permission_required")
        with CodexBridge(adapter) as bridge:
            cwd = _verify_thread(bridge.read(parent_id), parent_id)
            # The official fork keeps its exact cwd, while folder projects use
            # the Git root as their collaboration boundary (cwd may be a child).
            from studio.core import projects

            project = projects.info(parent_id)
            shared_directory = str(projects.folder(cwd)) if project["storage"] == "folder" else cwd
            if action == "allow":
                with workspace.lock:
                    collab = workspace.doc.get("collaboration")
                    if collab and collab["worktree"] != shared_directory:
                        c.fail("part_chat.worktree_mismatch", "worktree_mismatch")
                _write(
                    permission_path,
                    {
                        "decision": "allowed",
                        "adapter": adapter,
                        "cwd": cwd,
                        "project_id": workspaces.project_id(parent_id),
                        "at": time.time(),
                    },
                )
                return {"ok": True, "decision": "allowed", "enabled": True, "available": True}
            if (
                not enabled
                or permission.get("cwd") != cwd
                or permission.get("project_id") != workspaces.project_id(parent_id)
            ):
                c.fail("part_chat.permission_required", "permission_required")
            try:
                operation_id = str(uuid.UUID(body.get("operation_id", "")))
            except (ValueError, TypeError, AttributeError):
                c.fail("part_chat.bad_operation_id", "bad_arguments")
            path = operations / (operation_id + ".json")
            operation = _read(path, None)
            if operation and operation["object_id"] != body.get("object_id"):
                c.fail("part_chat.operation_conflict", "operation_conflict")
            if operation and operation["status"] == "bound":
                return {"ok": True, **_public(operation)}
            if operation and not operation.get("child_id") and operation["status"] != "prepared":
                return {
                    "ok": True,
                    **_public(operation),
                    "status": "uncertain",
                    "message": render("part_chat.duplicate_create_uncertain"),
                }
            if operation is None:
                # Prevent repeated clicks/reloaded tabs from creating two chats
                # for one part, including the uncertain-response case.
                for other in operations.glob("*.json"):
                    prior = _read(other, {})
                    if prior.get("object_id") == body.get("object_id"):
                        return {"ok": True, **_public(prior)}
                invitation = c.control(
                    workspace,
                    {
                        "action": "invite",
                        "object_id": body.get("object_id"),
                        "worktree": shared_directory,
                        "expected_revision": body.get("expected_revision"),
                    },
                )
                operation = {
                    "operation_id": operation_id,
                    "object_id": invitation["object_id"],
                    "name": invitation["name"],
                    "status": "prepared",
                    "invitation": invitation["invitation"],
                    "cwd": cwd,
                    "parent_id": parent_id,
                    "created_at": time.time(),
                }
                _write(path, operation)

            def remember(thread):
                child_id = str(uuid.UUID(thread["id"]))
                _verify_thread(thread, child_id, operation["cwd"], parent_id)
                if operation.get("child_id") not in (None, child_id):
                    c.fail("part_chat.multiple_forks_bound_stopped", "bridge_identity")
                operation.update(child_id=child_id, status="created")
                _write(path, operation)

            try:
                if not operation.get("child_id"):
                    operation["status"] = "forking"
                    _write(path, operation)
                    remember(bridge.fork(parent_id, cwd, remember))
                child_id = operation["child_id"]
                _verify_thread(bridge.read(child_id), child_id, cwd, parent_id)
                bridge.rename(child_id, render("part_chat.branch_thread_title", name=operation["name"][:80]))
                with workspace.lock:
                    collab = workspace.doc.get("collaboration", {})
                    invite = collab.get("invitations", {}).get(operation["invitation"])
                    if not invite or (
                        invite["joined_by"] is None
                        and (
                            invite["expires_at"] <= time.time()
                            or any(collab["versions"].get(k) != v for k, v in invite["versions"].items())
                        )
                    ):
                        replacement = c.control(
                            workspace,
                            {
                                "action": "invite",
                                "object_id": operation["object_id"],
                                "worktree": shared_directory,
                                "expected_revision": body.get("expected_revision"),
                            },
                        )
                        operation["invitation"] = replacement["invitation"]
                        _write(path, operation)
                result = workspaces.bind(
                    child_id,
                    parent_id,
                    lambda: c.join_verified_child(workspace, child_id, operation["invitation"], shared_directory),
                )
                if not result.get("ok"):
                    raise RuntimeError(
                        result.get("error", {}).get("message", render("part_chat.binding_failed_fallback"))
                    )
                operation.update(status="bound", message=render("part_chat.bound_ready_message"))
            except Exception as error:
                operation.update(
                    status="binding_failed" if operation.get("child_id") else "uncertain", message=str(error)
                )
            _write(path, operation)
            return {"ok": True, **_public(operation)}
