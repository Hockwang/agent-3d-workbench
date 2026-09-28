"""Persistent local modelling tasks, independent of the HTTP server lifetime."""

from __future__ import annotations
import glob
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import uuid

from studio.core.editor import EditorError, _atomic
from studio.i18n import get_language, render

from studio.paths import CORE_DIR, KERNELS_DIR, PLUGIN_ROOT

ACTIVE = {"queued", "running", "cancelling"}
EDITABLE = {"container", "hinge", "generated-container", "local-dimensions", "shell-kit"}


def implementation_digest():
    files = [
        CORE_DIR / "generated_editing.py",
        CORE_DIR / "task_templates.py",
        CORE_DIR / "task_operations.py",
        CORE_DIR / "task_bootstrap.py",
        CORE_DIR / "head_shell.py",
        CORE_DIR / "head_shell_audit.py",
        CORE_DIR / "head_shell_vision.py",
        CORE_DIR / "head_shell_sight.py",
        KERNELS_DIR / "mechanical_geometry.py",
        PLUGIN_ROOT / "pyproject.toml",
        PLUGIN_ROOT / "uv.lock",
    ]
    return hashlib.sha256(b"".join(path.read_bytes() for path in files)).hexdigest()


def _blender_version_key(path):
    match = re.search(r"[Bb]lender\s+([\d.]+)", path)
    return tuple(int(part) for part in match.group(1).split(".")) if match else (0,)


def _default_blender_candidates():
    """Platform default search order, tried after `WORKBENCH_BLENDER`."""
    if sys.platform == "darwin":
        return ["/Applications/Blender.app/Contents/MacOS/Blender", shutil.which("blender")]
    if sys.platform == "win32":
        program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
        pattern = str(Path(program_files) / "Blender Foundation" / "Blender *" / "blender.exe")
        return sorted(glob.glob(pattern), key=_blender_version_key, reverse=True)
    return [
        shutil.which("blender"),
        "/usr/bin/blender",
        "/snap/bin/blender",
        str(Path.home() / ".local" / "bin" / "blender"),
    ]


def blender_path():
    configured = os.environ.get("WORKBENCH_BLENDER")
    candidates = [configured, *_default_blender_candidates()]
    return next((str(Path(x).resolve()) for x in candidates if x and Path(x).is_file()), None)


class Tasks:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def folder(self, task_id):
        if not isinstance(task_id, str) or not re.fullmatch(r"[a-f0-9]{32}", task_id):
            raise EditorError.coded("tasks.invalid_task_id")
        folder = self.root / task_id
        if not (folder / "state.json").is_file():
            raise EditorError.coded("tasks.task_not_found")
        return folder

    def state(self, task_id, include_log=False):
        folder = self.folder(task_id)
        state = json.loads((folder / "state.json").read_text())
        review = folder / "reviews.json"
        if review.exists():
            state["review_revision"] = review.stat().st_mtime_ns
        receipt = folder / "service-receipt.json"
        if receipt.is_file():
            cloud = json.loads(receipt.read_text())
            state["service"] = {
                k: cloud.get(k)
                for k in (
                    "provider",
                    "operation",
                    "remote_id",
                    "status",
                    "progress",
                    "output_formats",
                    "cost",
                    "cost_unit",
                    "submitted_at",
                    "polled_at",
                    "received_at",
                    "model",
                    "adapter",
                )
            }
        # Do not kill a recycled PID. Cancellation is consumed by the owning worker.
        if state["status"] in ACTIVE and time.time() - state.get("heartbeat", 0) > 30:
            state = {**state, "status": "interrupted", "error": render("tasks.heartbeat_interrupted")}
        if receipt.is_file():
            state["can_resume"] = bool(cloud.get("remote_id") or (folder / "seed3d-result.json").is_file()) and state[
                "status"
            ] not in ACTIVE | {"completed"}
        if include_log and (folder / "run.log").exists():
            with (folder / "run.log").open("rb") as log:
                log.seek(max(0, (folder / "run.log").stat().st_size - 16000))
                state["log"] = log.read().decode("utf-8", errors="replace")
        if state.get("template") in EDITABLE:
            request = json.loads((folder / "request.json").read_text())
            state["editable"] = {
                "template": state["template"],
                "params": request["params"],
                "inputs": request["inputs"],
                "source_task": state.get("source_task"),
            }
        return state

    def list(self):
        return sorted(
            [self.state(p.parent.name) for p in self.root.glob("*/state.json")],
            key=lambda x: x["created"],
            reverse=True,
        )[:100]

    def capabilities(self):
        import importlib.util
        from studio.core.task_templates import localized_catalog
        from studio.adapters.services import catalog

        return {
            "motion": {
                "available": bool(shutil.which("node") or Path("/opt/homebrew/bin/node").is_file()),
                "runtime": "Node.js 20+",
                "tool": "studio_motion",
            },
            "ok": True,
            "blender": {"available": bool(blender_path()), "path": blender_path()},
            "python": {"available": True},
            "cad": {"available": importlib.util.find_spec("cadquery") is not None, "engine": "CadQuery/OCP"},
            "templates": localized_catalog(),
            "services": catalog(),
            "local_first": {
                "generation_api_required": False,
                "guidance": render("tasks.guidance"),
                "examples": [
                    render("tasks.example_cad_script"),
                    render("tasks.example_selection_edit"),
                    render("tasks.example_animation"),
                ],
                "acceptance": render("tasks.acceptance"),
            },
            "execution": render("tasks.execution"),
            "script_contract": render("tasks.script_contract"),
        }

    def start(self, body, actor, _source=None):
        from studio.core.task_templates import script_for, CATALOG

        if body.get("provider"):
            from studio.adapters.services import prepare

            if body.get("script") or body.get("template"):
                raise EditorError.coded("tasks.service_task_conflicts_script_or_template")
            service = prepare(body["provider"], body.get("operation"), body.get("params", {}))
            # "Who is on the other end" is declared by the adapter spec
            # (`local_inputs_allowed`/`default_timeout_seconds` in
            # `studio.adapters.services.BUILTINS`, or a custom services.json entry
            # merged over it), not enumerated here by adapter id.
            if not service["spec"].get("local_inputs_allowed", True) and body.get("inputs"):
                raise EditorError.coded("tasks.assembly_workflow_no_local_inputs")
            body = {
                **body,
                "engine": "python",
                "params": {"service": service},
                "script": "from studio.adapters.services import run\nrun(workbench)",
                "timeout_seconds": body.get("timeout_seconds", service["spec"].get("default_timeout_seconds", 600)),
                "title": body.get("title") or body["provider"] + " · " + body["operation"],
            }
        template = next((x for x in CATALOG if x["id"] == body.get("template")), {})
        engine = body.get("engine", template.get("engine", "blender"))
        if engine not in ("blender", "python"):
            raise EditorError.coded("tasks.engine_must_be_blender_or_python")
        executable = blender_path() if engine == "blender" else sys.executable
        if not executable:
            raise EditorError.coded("tasks.blender_not_found")
        script = body.get("script")
        if body.get("template"):
            if script:
                raise EditorError.coded("tasks.template_and_script_conflict")
            script = script_for(body["template"])
            if engine != template.get("engine", "blender"):
                raise EditorError.coded("tasks.template_requires_engine", engine=template.get("engine", "blender"))
        if _source is not None:
            script = (_source / "script.py").read_text()
            prior = json.loads((_source / "state.json").read_text())
            if hashlib.sha256(script.encode()).hexdigest() != prior["script_sha256"]:
                raise EditorError.coded("tasks.source_script_changed")
        if not isinstance(script, str) or not script.strip() or len(script.encode()) > 200_000:
            raise EditorError.coded("tasks.script_required")
        try:
            compile(script, "<workbench>", "exec")
        except SyntaxError as exc:
            raise EditorError.coded("tasks.script_syntax_error", lineno=exc.lineno, msg=exc.msg) from None
        params = body.get("params", {})
        if not isinstance(params, dict):
            raise EditorError.coded("tasks.params_must_be_object")
        try:
            json.dumps(params, allow_nan=False)
        except (ValueError, TypeError):
            raise EditorError.coded("tasks.params_must_be_json_finite") from None
        inputs = body.get("inputs", [])
        if not isinstance(inputs, list) or len(inputs) > 50:
            raise EditorError.coded("tasks.inputs_max_50")
        paths = []
        for item in inputs:
            if not isinstance(item, str):
                raise EditorError.coded("tasks.input_must_be_absolute_local_path")
            path = Path(item).expanduser()
            if not path.is_absolute() or not path.is_file():
                raise EditorError.coded("tasks.input_must_be_absolute_local_path")
            paths.append(str(path.resolve()))
        timeout = body.get("timeout_seconds", 600)
        if type(timeout) is not int or not 1 <= timeout <= 3600:
            raise EditorError.coded("tasks.timeout_range")
        if type(body.get("render_preview", True)) is not bool:
            raise EditorError.coded("tasks.render_preview_must_be_bool")
        if sum(x["status"] in ACTIVE for x in self.list()) >= 2:
            raise EditorError.coded("tasks.busy_start", code="busy")
        task_id = uuid.uuid4().hex
        folder = self.root / task_id
        folder.mkdir()
        (folder / "output").mkdir()
        (folder / "script.py").write_text(script)
        frozen = []
        if body.get("template") in EDITABLE:
            from studio.core.editor import _glb_document

            (folder / "inputs").mkdir()
            for i, filename in enumerate(paths):
                path = Path(filename)
                if path.suffix.lower() not in (".glb", ".stl", ".ply"):
                    raise EditorError.coded("tasks.rebuildable_task_needs_self_contained_format")
                if path.stat().st_size > 500 * 1024 * 1024:
                    raise EditorError.coded("tasks.single_input_over_500mb")
                if path.suffix.lower() == ".glb":
                    doc = _glb_document(path.read_bytes())
                    if any(
                        x.get("uri") and not x["uri"].startswith("data:")
                        for x in doc.get("buffers", []) + doc.get("images", [])
                    ):
                        raise EditorError.coded("tasks.parametric_source_glb_must_embed_resources")
                target = folder / "inputs" / f"{i:02d}{path.suffix.lower()}"
                shutil.copyfile(path, target)
                with target.open("rb") as stream:
                    digest = hashlib.file_digest(stream, "sha256").hexdigest()
                frozen.append({"path": str(target), "original_path": filename, "sha256": digest})
            paths = [x["path"] for x in frozen]
        request = {
            "engine": engine,
            "executable": executable,
            "params": params,
            "inputs": paths,
            "frozen_inputs": frozen,
            "timeout_seconds": timeout,
            "render_preview": body.get("render_preview", True),
        }
        if body.get("template") in EDITABLE:
            request["implementation_sha256"] = implementation_digest()
        if _source is not None:
            old = json.loads((_source / "request.json").read_text())
            if [x["sha256"] for x in frozen] != [x["sha256"] for x in old.get("frozen_inputs", [])]:
                raise EditorError.coded("tasks.frozen_source_changed_during_copy")
        _atomic(folder / "request.json", json.dumps(request, allow_nan=False).encode())
        template_title = render(template["title"]) if template.get("title") else None
        state = {
            "id": task_id,
            "title": str(body.get("title") or template_title or render("tasks.default_title"))[:160],
            "template": body.get("template"),
            "category": template.get("category", "modelling"),
            "engine": engine,
            "status": "queued",
            "created": time.time(),
            "heartbeat": time.time(),
            "actor": actor,
            "artifacts": [],
            "script_sha256": hashlib.sha256(script.encode()).hexdigest(),
        }
        if _source is not None:
            state["source_task"] = _source.name
        _atomic(folder / "state.json", json.dumps(state).encode())
        self._launch(folder)
        return {"ok": True, "task": state, "print_submitted": False}

    def rebuild(self, body, actor):
        folder = self.folder(body.get("id"))
        state = self.state(folder.name)
        if state.get("template") not in EDITABLE or state["status"] in ACTIVE:
            raise EditorError.coded("tasks.rebuild_needs_finished_editable_task")
        old = json.loads((folder / "request.json").read_text())
        if old.get("implementation_sha256") != implementation_digest():
            raise EditorError.coded("tasks.implementation_changed")
        if old["inputs"] and not old.get("frozen_inputs"):
            raise EditorError.coded("tasks.old_task_not_frozen")
        for item in old.get("frozen_inputs", []):
            with Path(item["path"]).open("rb") as stream:
                if hashlib.file_digest(stream, "sha256").hexdigest() != item["sha256"]:
                    raise EditorError.coded("tasks.frozen_source_changed")
        patch = body.get("params", {})
        if not isinstance(patch, dict):
            raise EditorError.coded("tasks.params_must_be_object")
        return self.start(
            {
                "template": state["template"],
                "engine": old["engine"],
                "params": {**old["params"], **patch},
                "inputs": old["inputs"],
                "title": body.get("title") or state["title"],
                "timeout_seconds": old["timeout_seconds"],
                "render_preview": old["render_preview"],
            },
            actor,
            _source=folder,
        )

    @staticmethod
    def _launch(folder):
        with (folder / "worker.log").open("ab") as log:
            # The worker renders its report texts with studio.i18n, which in a fresh
            # process only sees STUDIO_LANG: pass the language of the request that
            # started the task so report.json matches what the caller sees.
            env = {**os.environ, "STUDIO_LANG": get_language()}
            subprocess.Popen(
                [sys.executable, str(Path(__file__).with_name("task_worker.py")), str(folder)],
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=log,
                start_new_session=True,
                env=env,
            )

    def resume(self, task_id):
        state = self.state(task_id)
        if not state.get("can_resume"):
            raise EditorError.coded("tasks.resume_requires_remote_task_id")
        if sum(x["status"] in ACTIVE for x in self.list()) >= 2:
            raise EditorError.coded("tasks.busy_resume", code="busy")
        folder = self.folder(task_id)
        (folder / "cancel").unlink(missing_ok=True)
        (folder / "success.json").unlink(missing_ok=True)
        state.update(status="queued", heartbeat=time.time(), error=None, artifacts=[])
        _atomic(folder / "state.json", json.dumps(state).encode())
        self._launch(folder)
        return {"ok": True, "task": state, "resubmitted": False}

    def cancel(self, task_id):
        state = self.state(task_id)
        if state["status"] in ACTIVE:
            (self.folder(task_id) / "cancel").touch()
        return {"ok": True, "task": state, "cancel_requested": state["status"] in ACTIVE}

    def artifact(self, task_id, artifact_id):
        state = self.state(task_id)
        if state["status"] != "completed":
            raise EditorError.coded("tasks.task_not_completed")
        item = next((x for x in state["artifacts"] if x["id"] == artifact_id), None)
        if not item:
            raise EditorError.coded("tasks.artifact_not_found")
        root = (self.folder(task_id) / "output").resolve()
        path = (root / item["name"]).resolve()
        if not path.is_relative_to(root) or not path.is_file() or path.stat().st_size != item["bytes"]:
            raise EditorError.coded("tasks.artifact_changed_or_outside_task_dir")
        with path.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != item["sha256"]:
                raise EditorError.coded("tasks.artifact_checksum_failed")
        return path, item
