"""Folder-owned 3D projects; runtime credentials remain in the user registry.

A canonical folder (including a Git worktree) is the ownership boundary. The
folder contains portable model data; a path-derived runtime ID prevents copied
worktrees from sharing a server or chat scopes. Existing session projects are
never silently migrated or combined.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import subprocess
from pathlib import Path

from studio.core import workspaces
from studio.core.editor import _atomic
from studio.i18n import render


def folder(value):
    if not isinstance(value, str) or not Path(value).is_absolute() or not Path(value).is_dir():
        raise ValueError(render("projects.folder_must_be_absolute_dir"))
    path = Path(value).resolve()
    try:
        result = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "--show-toplevel"], capture_output=True, text=True, timeout=5
        )
    except FileNotFoundError:
        return path
    return Path(result.stdout.strip()).resolve() if result.returncode == 0 else path


def key(path):
    return "project-" + hashlib.sha256(str(path).encode()).hexdigest()[:24]


def location_job(location):
    path = Path(location["folder"])
    if not path.is_absolute() or not path.is_dir() or key(path.resolve()) != location["project_id"]:
        raise ValueError(render("projects.location_moved_or_missing"))
    job = path / ".3dstudio" / "job"
    if job.resolve() != job:
        raise ValueError(render("projects.job_symlink_forbidden"))
    return job


def info(workspace_id):
    target = workspaces.project_id(workspace_id)
    path = workspaces.home(target) / "project-location.json"
    if path.exists():
        return {**json.loads(path.read_text()), "storage": "folder", "workspace_id": workspace_id}
    return {
        "project_id": target,
        "storage": "session",
        "workspace_id": workspace_id,
        "folder": None,
        "job": str(workspaces.job_dir(workspace_id)),
    }


def thread_folder(workspace_id, resolve_cwd=None):
    """`resolve_cwd(workspace_id) -> {"id": ..., "cwd": ...}` is injected by the
    caller (`studio.shell.codex_projects.resolve_cwd` in production) — this
    module does not import `studio.shell.codex_bridge` directly (layer rule)."""
    if resolve_cwd is None:
        raise ValueError(render("projects.thread_folder_requires_resolve_cwd"))
    thread = resolve_cwd(workspace_id)
    if thread.get("id") != workspace_id:
        raise ValueError(render("projects.codex_task_identity_mismatch"))
    return folder(thread.get("cwd"))


def auto_attach(workspace_id, resolve_cwd=None):
    root = workspaces.home(workspace_id)
    # Explicit bindings (especially scoped part chats) always take precedence.
    # Non-Codex clients keep using explicit open_project or isolated workspaces.
    if (
        (root / "binding.json").exists()
        or (root / "job").exists()
        or (root / "project-location.json").exists()
        or not re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", workspace_id)
    ):
        return
    # Forwarded only when given, so a test that replaces `thread_folder`
    # wholesale with a single-argument stub keeps working unmodified.
    directory = thread_folder(workspace_id, resolve_cwd) if resolve_cwd is not None else thread_folder(workspace_id)
    open_project(workspace_id, str(directory))


def open_project(workspace_id, directory, *, source_id=None, snapshot=None):
    """Attach an ordinary chat; an optional explicit source seeds an empty folder.

    Callers requesting a copy supply an atomic source snapshot and expected
    revision. The source and its old server are left untouched.
    """
    from studio.shell.mcp_server import _call_http

    path = folder(directory)
    project_id = key(path)
    if workspace_id == project_id:
        raise ValueError(render("projects.workspace_id_must_be_chat_identity"))
    location = {
        "schema": "studio-folder-project/v1",
        "project_id": project_id,
        "folder": str(path),
        "job": str(path / ".3dstudio" / "job"),
    }
    with workspaces.lock(workspace_id):
        binding = workspaces.home(workspace_id) / "binding.json"
        if binding.exists():
            if workspaces.project_id(workspace_id) != project_id:
                raise ValueError(render("projects.already_bound_to_other_project"))
            # Do not turn a scoped part chat into an unrestricted project chat.
            return {"ok": True, **info(workspace_id), "already_bound": True}
        if (workspaces.home(workspace_id) / "job").exists() and source_id != workspace_id:
            raise ValueError(render("projects.existing_project_requires_source_id"))
        with workspaces.lock(project_id):
            job = location_job(location)
            project = job / "workbench" / "project.json"
            if source_id is not None:
                if job.exists():
                    raise ValueError(render("projects.target_folder_already_has_project"))
                if snapshot is None:
                    raise ValueError(render("projects.copy_requires_source_snapshot"))
                doc = copy.deepcopy(snapshot)
                doc.pop("collaboration", None)
                doc.update(revision=0, undo=[], redo=[], history=[], selection=[])
                try:
                    workspaces.copy_assets(
                        doc["objects"],
                        workspaces.job_dir(source_id) / "workbench" / "assets",
                        project.parent / "assets",
                    )
                    _atomic(project, json.dumps(doc, ensure_ascii=False, allow_nan=False).encode())
                    if source_id != workspace_id:
                        _atomic(
                            project.parent / "branch.json",
                            json.dumps(
                                {
                                    "source_id": source_id,
                                    "source_revision": snapshot["revision"],
                                    "base_objects": snapshot["objects"],
                                },
                                ensure_ascii=False,
                            ).encode(),
                        )
                except Exception:
                    import shutil

                    shutil.rmtree(job, ignore_errors=True)
                    raise
            elif project.exists():
                # Copied folder / Git worktree: geometry remains identical;
                # inherited leases and sessions belong to the source folder.
                doc = json.loads(project.read_text())
                collab = doc.get("collaboration")
                if collab and collab["worktree"] != str(path):
                    doc.pop("collaboration")
                    doc.update(undo=[], redo=[], selection=[])
                    _atomic(project, json.dumps(doc, ensure_ascii=False, allow_nan=False).encode())
            _atomic(workspaces.home(project_id) / "project-location.json", json.dumps(location).encode())
            marker = path / ".3dstudio" / "project.json"
            if not marker.exists():
                marker.parent.mkdir(parents=True, exist_ok=True)
                _atomic(
                    marker,
                    json.dumps(
                        {"schema": "studio-project/v1", "name": path.name, "scene": "job/workbench/project.json"},
                        ensure_ascii=False,
                        indent=2,
                    ).encode(),
                )
        server, _ = workspaces.ensure_running(project_id)
        result = _call_http(
            "POST",
            "/api/collaboration",
            server["token"],
            server["url"],
            json_body={"action": "project_join", "worktree": str(path)},
            workspace_id=workspace_id,
        )
        if not result.get("ok"):
            raise ValueError(result.get("error", {}).get("message", render("projects.join_failed_fallback")))
        _atomic(binding, json.dumps({"project_id": project_id, "worktree": str(path)}).encode())
        return {"ok": True, **location, "storage": "folder", "workspace_id": workspace_id, "scope": result["scope"]}
