"""Task recipes follow one frozen generation and its checksum-bound evidence.

The `workspace: "tasks"` analogue of `studio.core.recipe_progress` (which
tracks `workspace: "edit"` recipes): `view()` folds a `shell-kit` task's
current status, its `report.json` workflow checks, and any linked appearance
observation into the recipe's step statuses, called from
`studio.shell.server._build_recipe_state`. `record_task`/`record_observation`
are called from `studio.shell.server` right after a task/observation action
succeeds, mirroring `recipe_progress.record()`.
"""

import copy
import json

from studio.i18n import render
from studio.core.editor import EditorError

TEMPLATES = {"shell-kit"}
CHECKS = {"prepare", "generate", "geometry", "head_fit", "sight", "appearance"}


def record_task(recipe, active, task):
    if task.get("template") == recipe.get("task_template"):
        # A rebuild is a new version: no prior quality or review carries over.
        active["task_progress"] = {"task_id": task["id"]}


def record_observation(active, tasks, result):
    progress = active.get("task_progress") or {}
    if not progress.get("task_id") or not result.get("ready"):
        return
    task = tasks.state(progress["task_id"])
    scene = next((a for a in task["artifacts"] if a["name"] == "scene.glb"), None)
    if scene and any(v["source_sha256"] == scene["sha256"] for v in result["report"]["variants"]):
        progress["observation_id"] = result["task"]["id"]


def view(recipe, active, tasks, observations):
    steps = copy.deepcopy(recipe["steps"])
    for step in steps:
        step.update(status="todo", detail=step["decide"])
    by_key = {s["key"]: s for s in steps}
    task_id = (active.get("task_progress") or {}).get("task_id")
    title = None
    report_sha = None
    try:
        if task_id:
            task = tasks.state(task_id)
            if task.get("template") != recipe["task_template"]:
                raise ValueError(render("task_recipe_progress.generation_task_recipe_mismatch"))
            title = task["title"]
            by_key["prepare"].update(status="pass", detail=render("task_recipe_progress.prepare_detail_recorded"))
            if task["status"] in ("queued", "running", "cancelling"):
                by_key["generate"].update(
                    status="running", detail=render("task_recipe_progress.generate_detail_running")
                )
            elif task["status"] != "completed":
                by_key["generate"].update(
                    status="warn", detail=task.get("error") or render("task_recipe_progress.generate_detail_incomplete")
                )
            else:
                artifact = next(a for a in task["artifacts"] if a["name"] == "report.json")
                if artifact["bytes"] > 1024 * 1024:
                    raise ValueError(render("task_recipe_progress.report_too_large"))
                path, artifact = tasks.artifact(task_id, artifact["id"])
                report = json.loads(path.read_text())
                if report.get("schema") != "shell-kit/v1":
                    raise ValueError(render("task_recipe_progress.report_schema_mismatch"))
                report_sha = artifact["sha256"]
                scene = next(a for a in task["artifacts"] if a["name"] == "scene.glb")
                tasks.artifact(task_id, scene["id"])
                by_key["generate"].update(status="pass", detail=render("task_recipe_progress.generate_detail_pass"))
                for key in ("geometry", "head_fit", "sight"):
                    check = report.get("workflow_checks", {}).get(key, {})
                    by_key[key].update(
                        status=check.get("status") if check.get("status") in ("pass", "warn", "todo") else "todo",
                        detail=check.get("detail") or render("task_recipe_progress.check_detail_missing_evidence"),
                    )
                obs_id = (active.get("task_progress") or {}).get("observation_id")
                if obs_id:
                    result = observations.execute({"action": "read", "id": obs_id}, "ai")
                    scene = next(a for a in task["artifacts"] if a["name"] == "scene.glb")
                    reference = next(
                        a for a in task["artifacts"] if a["name"] == "inspection/source-reference/scene.glb"
                    )
                    tasks.artifact(task_id, reference["id"])
                    observed = {v.get("source_sha256") for v in result.get("report", {}).get("variants", [])}
                    matches = result.get("ready") and {scene["sha256"], reference["sha256"]} <= observed
                    reviews = [
                        r
                        for r in result.get("reviews", [])
                        if r["actor"] == "human" and r["report_sha256"] == result.get("report_sha256")
                    ]
                    if matches and reviews:
                        last = reviews[-1]
                        by_key["appearance"].update(
                            status="pass" if last["verdict"] == "good" else "warn",
                            detail=render("task_recipe_progress.appearance_detail_human_review", note=last["note"]),
                        )
                    elif matches:
                        by_key["appearance"].update(
                            detail=render("task_recipe_progress.appearance_detail_awaiting_human")
                        )
    except (ValueError, KeyError, OSError, StopIteration, EditorError) as exc:
        # A missing/tampered receipt cannot leave any downstream check green.
        for key in ("generate", "geometry", "head_fit", "sight", "appearance"):
            by_key[key].update(
                status="warn" if key == "generate" else "todo",
                detail=render("task_recipe_progress.evidence_unavailable", error=str(exc)),
            )
    required = [s for s in steps if not s["optional"]]
    pending = next((s for s in required if s["status"] != "pass"), None)
    return {
        "steps": steps,
        "next": pending["key"] if pending else None,
        "done": sum(s["status"] == "pass" for s in required),
        "total": len(required),
        "task_id": task_id,
        "task_title": title,
        "report_sha256": report_sha,
        "observation_id": (active.get("task_progress") or {}).get("observation_id"),
        "scope_note": render("task_recipe_progress.scope_note"),
    }
