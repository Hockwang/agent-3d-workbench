"""Read-only asset observations, immutable evidence and revision-bound reviews."""

from __future__ import annotations
import hashlib
import json
import math
from pathlib import Path
import time
import xml.etree.ElementTree as ET

from studio.core.editor import EditorError, _atomic
from studio.i18n import render

VIEWS = ("front", "right", "back", "left", "top", "iso")
# `title`/`description` are message codes, not text — `task_templates.localized_catalog()`
# renders them per-request (see the CATALOG convention in `studio/core/task_templates.py`).
CATALOG = [
    {
        "id": "model-observe",
        "title": "observation.model_observe.title",
        "engine": "python",
        "description": "observation.model_observe.description",
        "params": {"resolution": 512},
        "category": "observation",
    }
]


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def mesh_ref(path, filename):
    if filename.startswith("package://"):
        filename = filename[10:].partition("/")[2]
    if "://" in filename:
        raise ValueError(render("observation.remote_urdf_resource_unsupported"))
    target = (Path(path).parent / filename).resolve()
    if not target.is_file() or target.suffix.lower() not in (".glb", ".stl", ".ply"):
        raise ValueError(render("observation.urdf_visual_mesh_missing", filename=filename))
    return target


def dependencies(path):
    path = Path(path).resolve()
    if path.suffix.lower() not in (".glb", ".stl", ".ply", ".urdf"):
        raise ValueError(render("observation.unsupported_format"))
    refs = [path]
    if path.suffix.lower() == ".urdf":
        raw = path.read_bytes()
        if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
            raise ValueError(render("observation.urdf_external_entities_forbidden"))
        xml = ET.fromstring(raw)
        names = [item.get("name") for item in xml.findall("link")]
        if not names or any(not n for n in names) or len(set(names)) != len(names):
            raise ValueError(render("observation.urdf_link_name_invalid"))
        children, edges = set(), {n: [] for n in names}
        for joint in xml.findall("joint"):
            parent, child = joint.find("parent"), joint.find("child")
            if parent is None or child is None or parent.get("link") not in edges or child.get("link") not in edges:
                raise ValueError(render("observation.urdf_joint_references_missing_link"))
            if child.get("link") in children:
                raise ValueError(render("observation.urdf_link_multiple_parents"))
            children.add(child.get("link"))
            edges[parent.get("link")].append(child.get("link"))
        roots = set(names) - children
        if len(roots) != 1:
            raise ValueError(render("observation.urdf_link_tree_invalid"))
        seen, stack = set(), list(roots)
        while stack:
            current = stack.pop()
            if current in seen:
                raise ValueError(render("observation.urdf_joint_cycle"))
            seen.add(current)
            stack.extend(edges[current])
        if seen != set(names):
            raise ValueError(render("observation.urdf_unreachable_link"))
        refs += [mesh_ref(path, m.attrib["filename"]) for m in xml.findall("link/visual/geometry/mesh")]
        if xml.findall(".//texture"):
            raise ValueError(render("observation.urdf_texture_must_be_packed"))
    for ref in refs:
        if not ref.is_file():
            raise ValueError(render("observation.file_not_found", path=ref))
        if ref.suffix.lower() == ".glb":
            import struct

            with ref.open("rb") as stream:
                head = stream.read(20)
                if len(head) != 20 or head[:4] != b"glTF" or head[16:20] != b"JSON":
                    raise ValueError(render("observation.invalid_glb"))
                count = struct.unpack_from("<I", head, 12)[0]
                if count > 64 * 1024 * 1024:
                    raise ValueError(render("observation.glb_json_too_large"))
                doc = json.loads(stream.read(count))
            for item in doc.get("buffers", []) + doc.get("images", []):
                if item.get("uri") and not item["uri"].startswith("data:"):
                    raise ValueError(render("observation.glb_must_be_self_contained"))
    return list(dict.fromkeys(refs))


def options(params):
    p = dict(params or {})
    views = p.get("views", ["front", "right", "top", "iso"])
    phases = p.get("phases", [0])
    if not isinstance(views, list) or not views or len(views) > 6 or any(v not in VIEWS for v in views):
        raise ValueError(render("observation.views_invalid"))
    if (
        not isinstance(phases, list)
        or not 1 <= len(phases) <= 5
        or any(type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 1 for v in phases)
    ):
        raise ValueError(render("observation.phases_invalid"))
    resolution = p.get("resolution", 512)
    if type(resolution) is not int or not 256 <= resolution <= 1024:
        raise ValueError(render("observation.resolution_invalid"))
    if p.get("urdf_up", "z") not in ("y", "z"):
        raise ValueError(render("observation.urdf_up_invalid"))
    return {**p, "views": views, "phases": phases, "resolution": resolution, "urdf_up": p.get("urdf_up", "z")}


class Observations:
    def __init__(self, tasks):
        self.tasks = tasks

    def focus(self):
        path = self.tasks.root.parent / "observation-focus.json"
        return json.loads(path.read_text()) if path.exists() else None

    def execute(self, body, actor):
        try:
            return self._execute(body, actor)
        except (ValueError, TypeError, KeyError, OSError) as exc:
            raise EditorError(str(exc)) from None

    def _execute(self, body, actor):
        action = body.get("action")
        if action == "start":
            inputs = body.get("inputs", [])
            source_tasks = body.get("source_tasks", [])
            if not isinstance(source_tasks, list) or len(source_tasks) > 4:
                raise EditorError.coded("observation.source_tasks_max")
            if inputs and source_tasks:
                raise EditorError.coded("observation.inputs_or_source_tasks_only")
            provenance = []
            if source_tasks:
                inputs = []
                for task_id in source_tasks:
                    task = self.tasks.state(task_id)
                    artifact = next((a for a in task["artifacts"] if a["name"] == "scene.glb"), None)
                    artifact = artifact or next((a for a in task["artifacts"] if a["name"].endswith(".glb")), None)
                    if not artifact:
                        raise EditorError.coded("observation.source_task_missing_glb")
                    path, _ = self.tasks.artifact(task_id, artifact["id"])
                    inputs.append(str(path))
                    service = task.get("service") or {}
                    provenance.append(
                        {
                            "task_id": task_id,
                            "title": task["title"],
                            "elapsed_seconds": task.get("elapsed_seconds"),
                            "source": "workbench_task",
                            "tokens": None,
                            "cost": service.get("cost"),
                            "cost_unit": service.get("cost_unit"),
                            "provider": service.get("provider"),
                            "operation": service.get("operation"),
                            "model": service.get("model"),
                        }
                    )
            if not isinstance(inputs, list) or not 1 <= len(inputs) <= 4:
                raise EditorError.coded("observation.variant_count_invalid")
            if any(not isinstance(p, str) or not Path(p).expanduser().is_absolute() for p in inputs):
                raise EditorError.coded("observation.inputs_must_be_absolute")
            inputs = [str(Path(p).expanduser().resolve()) for p in inputs]
            params = options(body.get("params"))
            labels = body.get("labels", [Path(p).stem for p in inputs])
            if (
                not isinstance(labels, list)
                or len(labels) != len(inputs)
                or any(not isinstance(s, str) or not s.strip() or len(s) > 100 for s in labels)
            ):
                raise EditorError.coded("observation.labels_invalid")
            refs = list(dict.fromkeys(str(r) for p in inputs for r in dependencies(p)))
            params.update(sources=inputs, labels=labels, provenance=provenance)
            return self.tasks.start(
                {
                    "template": "model-observe",
                    "inputs": refs,
                    "params": params,
                    "title": body.get("title") or render("observation.default_title", labels=" / ".join(labels)),
                    "timeout_seconds": 1800,
                    "render_preview": False,
                },
                actor,
            )
        if action not in ("read", "review", "focus"):
            raise EditorError.coded("observation.action_invalid")
        focus = self.focus()
        task = self.tasks.state(body.get("id") or (focus or {}).get("task_id"))
        if task["status"] != "completed":
            return {"ok": True, "task": task, "ready": False}
        artifact = next((a for a in task["artifacts"] if a["name"] == "observation.json"), None)
        if not artifact:
            raise EditorError.coded("observation.not_an_observation_task")
        path, artifact = self.tasks.artifact(task["id"], artifact["id"])
        report = json.loads(path.read_text())
        if action == "focus":
            variant, phase = body.get("variant", 0), body.get("phase_index", 0)
            if (
                type(variant) is not int
                or type(phase) is not int
                or not 0 <= variant < len(report["variants"])
                or not 0 <= phase < len(report["phases"])
            ):
                raise EditorError.coded("observation.variant_phase_out_of_range")
            focus = {
                "task_id": task["id"],
                "variant": variant,
                "phase_index": phase,
                "report_sha256": artifact["sha256"],
                "actor": actor,
                "at": time.time(),
            }
            _atomic(self.tasks.root.parent / "observation-focus.json", json.dumps(focus).encode())
        review_path = self.tasks.folder(task["id"]) / "reviews.json"
        reviews = json.loads(review_path.read_text()) if review_path.exists() else []
        if action == "review":
            if body.get("expected_sha256") != artifact["sha256"]:
                raise EditorError.coded("observation.review_stale_report", code="revision_conflict")
            verdict, note = body.get("verdict"), body.get("note", "")
            if (
                verdict not in ("good", "bad", "needs_review")
                or not isinstance(note, str)
                or not note.strip()
                or len(note) > 4000
            ):
                raise EditorError.coded("observation.review_requires_verdict_and_note")
            reviews.append(
                {
                    "at": time.time(),
                    "actor": actor,
                    "verdict": verdict,
                    "note": note,
                    "report_sha256": artifact["sha256"],
                }
            )
            _atomic(review_path, json.dumps(reviews, ensure_ascii=False).encode())
        return {
            "ok": True,
            "ready": True,
            "task": task,
            "report": report,
            "report_sha256": artifact["sha256"],
            "reviews": reviews,
            "focus": focus,
        }
