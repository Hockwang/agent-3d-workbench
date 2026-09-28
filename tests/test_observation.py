import json

import numpy as np
import pytest
import trimesh

from studio.core.editor import EditorError
from studio.core.observation import Observations, dependencies, options
from studio.core.observation_run import metrics
from studio.core.tasks import Tasks
from tests.helpers import wait


def completed_observation(tmp_path):
    tasks = Tasks(tmp_path / "tasks")
    report = {
        "variants": [{"label": "A", "metrics": {"parts": [{"name": "body"}]}}],
        "phases": [0, 1],
        "images": [],
        "inputs": [],
        "verdict": "unreviewed",
    }
    script = (
        f"from pathlib import Path\nPath(workbench['output'],'observation.json').write_text({json.dumps(report)!r})"
    )
    task = tasks.start({"engine": "python", "script": script}, "ai")["task"]
    assert wait(tasks, task["id"])["status"] == "completed"
    return Observations(tasks), task["id"]


def test_reviews_bind_exact_report_and_shared_focus(tmp_path):
    observations, task_id = completed_observation(tmp_path)
    result = observations.execute({"action": "read", "id": task_id}, "ai")
    assert result["report"]["verdict"] == "unreviewed" and not result["reviews"]
    with pytest.raises(EditorError, match="版本不匹配"):
        observations.execute(
            {"action": "review", "id": task_id, "expected_sha256": "old", "verdict": "good", "note": "looks fine"}, "ai"
        )
    observations.execute({"action": "focus", "id": task_id, "variant": 0, "phase_index": 1}, "human")
    focused = observations.execute({"action": "read"}, "ai")
    assert focused["focus"]["actor"] == "human" and focused["focus"]["phase_index"] == 1
    observations.execute(
        {
            "action": "review",
            "id": task_id,
            "expected_sha256": result["report_sha256"],
            "verdict": "needs_review",
            "note": "Need to inspect the closing pose",
        },
        "ai",
    )
    reread = observations.execute({"action": "read"}, "human")
    assert reread["reviews"][0]["actor"] == "ai"
    assert reread["report_sha256"] == result["report_sha256"]
    assert observations.tasks.list()[0]["review_revision"]
    with pytest.raises(EditorError):
        observations.execute({"action": "focus", "id": task_id, "variant": 5}, "ai")


def test_start_freezes_dependencies_and_validates_inputs(tmp_path, monkeypatch):
    observations = Observations(Tasks(tmp_path / "tasks"))
    path = tmp_path / "box.glb"
    path.write_bytes(trimesh.Scene(trimesh.creation.box()).export(file_type="glb"))
    captured = {}
    monkeypatch.setattr(
        observations.tasks, "start", lambda body, actor: captured.update(body=body, actor=actor) or {"ok": True}
    )
    observations.execute({"action": "start", "inputs": [str(path)], "labels": ["baseline"]}, "human")
    assert captured["body"]["inputs"] == [str(path)] and captured["actor"] == "human"
    assert captured["body"]["params"]["labels"] == ["baseline"]
    for invalid in [[], ["relative.glb"], [str(tmp_path / "missing.glb")]]:
        with pytest.raises(EditorError):
            observations.execute({"action": "start", "inputs": invalid}, "ai")
    with pytest.raises(EditorError):
        observations.execute({"action": "start", "inputs": [str(path)], "labels": ["A", "B"]}, "ai")


def test_source_task_provenance_reads_cost_and_model_from_service_state(tmp_path, monkeypatch):
    tasks = Tasks(tmp_path / "tasks")
    script = (
        "from pathlib import Path\nimport trimesh\n"
        "Path(workbench['output'], 'scene.glb').write_bytes("
        "trimesh.Scene(trimesh.creation.box()).export(file_type='glb'))"
    )
    task = tasks.start({"engine": "python", "script": script}, "ai")["task"]
    assert wait(tasks, task["id"])["status"] == "completed"
    (tasks.folder(task["id"]) / "service-receipt.json").write_text(
        json.dumps(
            {
                "provider": "test-provider",
                "operation": "text-to-3d",
                "adapter": "meshy",
                "model": "mesh-v1",
                "remote_id": "abc",
                "status": "succeeded",
                "cost": 12.5,
                "cost_unit": "provider credits",
                "submitted_at": 1.0,
                "polled_at": 2.0,
                "received_at": 3.0,
            }
        )
    )

    observations = Observations(tasks)
    captured = {}
    monkeypatch.setattr(
        observations.tasks, "start", lambda body, actor: captured.update(body=body, actor=actor) or {"ok": True}
    )
    observations.execute({"action": "start", "source_tasks": [task["id"]]}, "human")
    provenance = captured["body"]["params"]["provenance"][0]
    assert provenance["cost"] == 12.5 and provenance["cost_unit"] == "provider credits"
    assert provenance["provider"] == "test-provider" and provenance["operation"] == "text-to-3d"
    assert provenance["model"] == "mesh-v1" and provenance["tokens"] is None


def test_urdf_dependencies_keep_subdirectories_and_reject_partial_graph(tmp_path):
    (tmp_path / "meshes").mkdir()
    mesh = tmp_path / "meshes/part.glb"
    mesh.write_bytes(trimesh.Scene(trimesh.creation.box()).export(file_type="glb"))
    urdf = tmp_path / "robot.urdf"
    urdf.write_text(
        '<robot name="r"><link name="root"/><link name="part"><visual><geometry><mesh filename="package://robot/meshes/part.glb"/></geometry></visual></link><joint name="j" type="fixed"><parent link="root"/><child link="part"/></joint></robot>'
    )
    assert dependencies(urdf) == [urdf, mesh]
    urdf.write_text('<robot><link name="a"/><link name="b"/></robot>')
    with pytest.raises(ValueError, match="完整"):
        dependencies(urdf)
    urdf.write_text('<!DOCTYPE x [<!ENTITY x SYSTEM "file:///tmp/file">]><robot/>')
    with pytest.raises(ValueError, match="实体"):
        dependencies(urdf)


def test_world_metrics_preserve_instances_and_do_not_normalize_sizes():
    scene = trimesh.Scene()
    box = trimesh.creation.box(extents=[1, 2, 3])
    scene.add_geometry(box, geom_name="body", node_name="one")
    scene.graph.update(
        frame_from=scene.graph.base_frame,
        frame_to="two",
        geometry="body",
        matrix=trimesh.transformations.translation_matrix([4, 0, 0]),
    )
    before = box.vertices.copy()
    result = metrics(scene)
    assert result["part_count"] == 2 and result["faces"] == 24
    assert result["extents_m"] == [5, 2, 3]
    assert result["boundary_edges"] == 0 and result["all_watertight"]
    assert np.array_equal(box.vertices, before)


@pytest.mark.parametrize(
    "params",
    [{"phases": [float("nan")]}, {"phases": [True]}, {"views": ["wrong"]}, {"resolution": 2048}, {"urdf_up": "auto"}],
)
def test_invalid_observation_parameters(params):
    with pytest.raises(ValueError):
        options(params)
