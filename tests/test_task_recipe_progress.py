"""Version-bound head-shell workflow checks and real task integration."""

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from studio.core import recipes
from studio.shell.server import StudioBackend
from studio.core.task_recipe_progress import view, record_task
from tests.test_head_shell import source, params, wait


@pytest.fixture
def recipe(tmp_path):
    return next(
        r
        for r in recipes.load_recipes(recipes.BUILTIN_RECIPES_DIR, tmp_path)["recipes"]
        if r["id"] == "wearable-head-shell"
    )


@pytest.fixture
def evidence(recipe, tmp_path):
    report = {
        "schema": "shell-kit/v1",
        "workflow_checks": {
            "geometry": {"status": "pass", "detail": "watertight"},
            "head_fit": {"status": "pass", "detail": "declared envelope only"},
            "sight": {"status": "warn", "detail": "blocked"},
        },
    }
    files = {
        "report.json": json.dumps(report).encode(),
        "scene.glb": b"new mesh",
        "inspection/source-reference/scene.glb": b"source reference",
    }
    artifacts = []
    for name, raw in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        artifacts.append(
            {"id": name, "name": name, "bytes": len(raw), "path": str(path), "sha256": hashlib.sha256(raw).hexdigest()}
        )
    task = {"id": "generated", "template": "shell-kit", "title": "test", "status": "completed", "artifacts": artifacts}

    def artifact(task_id, artifact_id):
        a = next(a for a in artifacts if a["id"] == artifact_id)
        path = Path(a["path"])
        if hashlib.sha256(path.read_bytes()).hexdigest() != a["sha256"]:
            raise ValueError("checksum mismatch")
        return path, a

    tasks = SimpleNamespace(state=lambda _: task, artifact=artifact)
    observed = {
        "ready": True,
        "task": {"id": "observation"},
        "report_sha256": "review-report",
        "report": {"variants": [{"source_sha256": a["sha256"]} for a in artifacts if a["name"].endswith(".glb")]},
        "reviews": [],
    }
    observations = SimpleNamespace(execute=lambda *args: observed)
    active = {"task_progress": {"task_id": "generated", "observation_id": "observation"}}
    return SimpleNamespace(
        recipe=recipe,
        active=active,
        tasks=tasks,
        task=task,
        observations=observations,
        observed=observed,
        artifacts=artifacts,
    )


def states(e):
    return {s["key"]: s["status"] for s in view(e.recipe, e.active, e.tasks, e.observations)["steps"]}


def review(e, actor="human", verdict="good", report_sha="review-report"):
    e.observed["reviews"].append({"actor": actor, "verdict": verdict, "note": "checked", "report_sha256": report_sha})


def test_geometry_pass_does_not_finish_blocked_sight_or_unreviewed_appearance(evidence):
    e = evidence
    s = states(e)
    assert s["geometry"] == s["head_fit"] == "pass"
    assert s["sight"] == "warn" and s["appearance"] == "todo"
    assert view(e.recipe, e.active, e.tasks, e.observations)["next"] == "sight"


def test_only_current_human_comparison_can_confirm_appearance(evidence):
    e = evidence
    review(e, actor="ai")
    assert states(e)["appearance"] == "todo"
    review(e, report_sha="old")
    assert states(e)["appearance"] == "todo"
    review(e)
    assert states(e)["appearance"] == "pass"
    review(e, verdict="needs_review")
    assert states(e)["appearance"] == "warn"


@pytest.mark.parametrize("mutation", ["other_model", "no_source", "report_changed"])
def test_review_of_different_or_incomplete_comparison_never_passes(evidence, mutation):
    e = evidence
    review(e)
    if mutation == "other_model":
        e.observed["report"]["variants"][0]["source_sha256"] = "other"
    if mutation == "no_source":
        e.observed["report"]["variants"] = e.observed["report"]["variants"][:1]
    if mutation == "report_changed":
        e.observed["report_sha256"] = "new"
    assert states(e)["appearance"] == "todo"


@pytest.mark.parametrize("name", ["report.json", "scene.glb", "inspection/source-reference/scene.glb"])
def test_tampered_evidence_cannot_remain_green(evidence, name):
    e = evidence
    review(e)
    Path(next(a["path"] for a in e.artifacts if a["name"] == name)).write_bytes(b"tampered")
    s = states(e)
    assert s["generate"] == "warn" and all(s[k] == "todo" for k in ("geometry", "head_fit", "sight", "appearance"))


def test_rebuild_clears_old_review_binding(evidence):
    e = evidence
    review(e)
    record_task(e.recipe, e.active, {"id": "rebuild", "template": "shell-kit"})
    assert e.active["task_progress"] == {"task_id": "rebuild"}
    assert states(e)["appearance"] == "todo"


@pytest.mark.parametrize(
    "args",
    [
        {"action": "start", "template": "shell-kit", "script": "danger"},
        {"action": "start", "template": "shell-kit", "inputs": ["/file.stl"]},
        {"action": "start", "template": "shell-kit", "params": {"preserve_eye_outline": False}},
    ],
)
def test_recipe_cannot_preset_script_source_or_appearance_override(tmp_path, args):
    raw = json.loads((recipes.BUILTIN_RECIPES_DIR / "wearable-head-shell" / "recipe.json").read_text())
    raw["steps"][0]["args"] = args
    d = tmp_path / "wearable-head-shell"
    d.mkdir()
    (d / "recipe.json").write_text(json.dumps(raw))
    (d / "guide.md").write_text("guide")
    loaded = recipes.load_recipes(tmp_path, tmp_path / "none")
    assert not loaded["recipes"] and loaded["problems"]


def test_real_template_recipe_persists_and_rebuilds_without_old_confirmation(tmp_path, monkeypatch):
    monkeypatch.setenv("PRINT_PREP_HOME", str(tmp_path / "home"))
    backend = StudioBackend(tmp_path / "job", "test-token")
    backend.run_write("recipe", lambda: backend.api_recipe_use({"id": "wearable-head-shell"}, "ai"))
    assert backend.build_state()["recipe"]["next"] == "prepare"
    first = backend.run_write(
        "task",
        lambda: backend.api_task(
            {"action": "start", "template": "shell-kit", "inputs": [str(source(tmp_path))], "params": params()}, "ai"
        ),
    )[1]["task"]
    assert wait(backend.tasks, first["id"])["status"] == "completed"
    state = backend.build_state()["recipe"]
    assert state["task_id"] == first["id"] and state["done"] >= 2 and state["done"] < 6
    restarted = StudioBackend(tmp_path / "job", "test-token")
    assert restarted.build_state()["recipe"]["task_id"] == first["id"]
    newer = backend.api_task({"action": "rebuild", "id": first["id"], "params": {"magnet_diameter_mm": 8}}, "ai")[
        "task"
    ]
    assert backend.build_state()["recipe"]["task_id"] == newer["id"]
    assert wait(backend.tasks, newer["id"])["status"] == "completed"
    assert backend.tasks.state(first["id"])["status"] == "completed"


def test_receipt_failure_does_not_report_started_task_as_failure(tmp_path, monkeypatch):
    monkeypatch.setenv("PRINT_PREP_HOME", str(tmp_path / "home"))
    backend = StudioBackend(tmp_path / "job", "test-token")
    monkeypatch.setattr(backend.tasks, "start", lambda *args: {"ok": True, "task": {"id": "already-started"}})
    monkeypatch.setattr(
        backend, "_record_recipe_task", lambda *args: (_ for _ in ()).throw(ValueError("receipt failed"))
    )
    result = backend.api_task({"action": "start"}, "ai")
    assert result["ok"] and result["task"]["id"] == "already-started" and result["recipe_warning"]


def test_original_outline_default_rejects_extension(tmp_path, monkeypatch):
    import studio.core.head_shell as module

    # Two valid closed components let index validation reach the outline guard.
    import trimesh

    body = trimesh.creation.box([80, 70, 100])
    body.apply_translation([0, 0, 50])
    eye = trimesh.creation.icosphere(radius=10)
    eye.apply_translation([0, -35, 65])
    path = tmp_path / "source.glb"
    path.write_bytes(trimesh.Scene([body, eye]).export(file_type="glb"))
    components, _ = module.load_components({"inputs": [str(path)], "params": params()})
    eye_index = min(range(len(components)), key=lambda i: components[i].volume)
    p = {
        **params(),
        "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "mesh_eyes": {str(eye_index): {"extension_outline_xz_mm": [[0, 0], [1, 0], [1, 1]]}},
    }
    with pytest.raises(ValueError, match="原眼轮廓受保护"):
        module.head_shell({"inputs": [str(path)], "params": p, "output": str(tmp_path / "out")})
