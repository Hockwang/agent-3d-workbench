"""Persistent task workspaces. No process-global mutable 'current workspace'."""

from __future__ import annotations

import contextlib
import copy
import hashlib
import json
import os
import re
from pathlib import Path

import studio
from studio.core import filelock
from studio.core.editor import _atomic
from studio.i18n import render

ID_PATTERN = r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,95}"


def validate_id(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(ID_PATTERN, value) or value == "legacy":
        raise ValueError(render("workspaces.invalid_id"))
    return value


def resolve_id(arguments: dict) -> str:
    # MCP connection IDs are not durable chat identities. Never silently fall
    # back to the shared legacy job when the caller did not identify its task.
    value = arguments.pop("workspace_id", None) or os.environ.get("PRINT_PREP_WORKSPACE_ID")
    if not value:
        raise ValueError(render("workspaces.unbound"))
    return validate_id(value)


def home(workspace_id: str) -> Path:
    root = (
        Path(os.environ["PRINT_PREP_WORKSPACES_HOME"])
        if os.environ.get("PRINT_PREP_WORKSPACES_HOME")
        else studio.print_prep_home()
    )
    return root / "workspaces" / validate_id(workspace_id)


def job_dir(workspace_id: str) -> Path:
    if workspace_id == "legacy":
        return studio.default_job_dir()
    root = home(project_id(workspace_id))
    location = root / "project-location.json"
    if location.exists():
        from studio.core.projects import location_job

        return location_job(json.loads(location.read_text()))
    return root / "job"


def project_id(workspace_id: str) -> str:
    binding = home(workspace_id) / "binding.json"
    if not binding.exists():
        return validate_id(workspace_id)
    return validate_id(json.loads(binding.read_text())["project_id"])


def bind(workspace_id: str, source_id: str, join):
    """Join before publishing binding; a retry may finish the same invitation."""
    with lock(workspace_id):
        target = project_id(source_id)
        if workspace_id == target or (home(workspace_id) / "job").exists():
            raise ValueError(render("workspaces.target_already_has_project"))
        binding = home(workspace_id) / "binding.json"
        if binding.exists() and project_id(workspace_id) != target:
            raise ValueError(render("workspaces.target_bound_to_other_project"))
        result = join()
        if result.get("ok"):
            _atomic(binding, json.dumps({"project_id": target, "worktree": result["worktree"]}).encode())
        return {**result, "project_id": target, "workspace_id": workspace_id}


@contextlib.contextmanager
def lock(workspace_id: str):
    root = home(workspace_id)
    root.mkdir(parents=True, exist_ok=True)
    with (root / ".startup.lock").open("a") as file:
        filelock.lock(file)
        yield


def ensure_running(workspace_id: str) -> tuple[dict, bool]:
    with lock(workspace_id):
        target = project_id(workspace_id)
        if target != workspace_id:
            return ensure_running(target)
        root = home(workspace_id)
        existing = studio.current_session(root)
        if existing:
            return existing, True
        return studio.start_server(job_dir(workspace_id), port=0, home=root), False


def list_workspaces() -> list[dict]:
    result = []
    paths = [("legacy", studio.default_job_dir())]
    root = home("listing").parent
    if root.exists():
        for p in root.iterdir():
            if not p.is_dir() or not re.fullmatch(ID_PATTERN, p.name) or (p / "binding.json").exists():
                continue
            try:
                paths.append((p.name, job_dir(p.name)))
            except (ValueError, OSError):
                result.append(
                    {
                        "id": p.name,
                        "name": render("workspaces.project_directory_unavailable_name"),
                        "available": False,
                        "error": render("workspaces.project_directory_unavailable_error"),
                    }
                )
    for key, job in paths:
        path = job / "workbench" / "project.json"
        if not job.exists():
            continue
        doc = json.loads(path.read_text()) if path.exists() else {}
        result.append(
            {
                "id": key,
                "name": doc.get("name", render("workspaces.untitled_project")),
                "revision": doc.get("revision", 0),
                "objects": len(doc.get("objects", [])),
                "folder": str(job.parent.parent) if job.parent.name == ".3dstudio" else None,
                "owner_workspace_id": doc.get("collaboration", {}).get("owner"),
                "read_only": key == "legacy",
            }
        )
    return result


def copy_assets(objects: list[dict], source: Path, target: Path):
    target.mkdir(parents=True, exist_ok=True)
    from studio.core.city import copy_packages

    copy_packages(objects, source.parent, target.parent)
    for obj in objects:
        digest = obj.get("motion", {}).get("blend_asset")
        if digest:
            if not re.fullmatch(r"[a-f0-9]{64}", digest):
                raise ValueError(render("workspaces.invalid_blender_source_asset"))
            raw = (source.parent / "sources" / f"{digest}.blend").read_bytes()
            if hashlib.sha256(raw).hexdigest() != digest:
                raise ValueError(render("workspaces.blender_source_asset_checksum_failed"))
            folder = target.parent / "sources"
            folder.mkdir(exist_ok=True)
            (folder / f"{digest}.blend").write_bytes(raw)
    from studio.core.motion import assets

    for asset in assets(objects):
        if not re.fullmatch(r"[a-f0-9]{64}", asset):
            raise ValueError(render("workspaces.invalid_model_asset_id"))
        path = target / (asset + ".glb")
        if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() == asset:
            continue
        raw = (source / (asset + ".glb")).read_bytes()
        if hashlib.sha256(raw).hexdigest() != asset:
            raise ValueError(render("workspaces.model_asset_checksum_failed"))
        _atomic(path, raw)


def fork(workspace_id: str, source_id: str, snapshot: dict) -> dict:
    if source_id != "legacy":
        validate_id(source_id)
    if source_id == workspace_id:
        raise ValueError(render("workspaces.cannot_fork_from_self"))
    with lock(workspace_id):
        target = job_dir(workspace_id)
        # Refuse an already opened/created target, even an empty live backend:
        # its in-memory state could otherwise overwrite the fork.
        if target.exists() or (home(workspace_id) / "binding.json").exists():
            raise ValueError(render("workspaces.fork_target_already_exists"))
        source = job_dir(source_id) / "workbench"
        doc = copy.deepcopy(snapshot)
        doc.pop("collaboration", None)
        doc.update(revision=0, undo=[], redo=[], history=[], selection=[])
        workbench = target / "workbench"
        try:
            copy_assets(doc["objects"], source / "assets", workbench / "assets")
            _atomic(
                workbench / "branch.json",
                json.dumps(
                    {
                        "source_id": source_id,
                        "source_revision": snapshot["revision"],
                        "base_objects": snapshot["objects"],
                    },
                    ensure_ascii=False,
                ).encode(),
            )
            _atomic(workbench / "project.json", json.dumps(doc, ensure_ascii=False, allow_nan=False).encode())
        except Exception:
            # Only our newly created, never-served target is cleaned up.
            import shutil

            shutil.rmtree(target, ignore_errors=True)
            raise
        return {
            "ok": True,
            "workspace_id": workspace_id,
            "source_id": source_id,
            "source_revision": snapshot["revision"],
            "objects": len(doc["objects"]),
        }
