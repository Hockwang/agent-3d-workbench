import pytest

from studio.core.tasks import Tasks
from studio.core.editor import EditorError
from tests.helpers import wait


def test_task_survives_manager_recreation_and_checks_artifacts(tmp_path):
    tasks = Tasks(tmp_path)
    task = tasks.start(
        {
            "engine": "python",
            "script": "from pathlib import Path\nPath(workbench['output'], 'model.json').write_text('model')",
        },
        "human",
    )["task"]
    restored = Tasks(tmp_path)
    state = wait(restored, task["id"])
    assert state["status"] == "completed" and state["actor"] == "human"
    path, item = restored.artifact(task["id"], state["artifacts"][0]["id"])
    assert path.read_text() == "model"
    path.write_text("other")
    with pytest.raises(EditorError, match="校验失败"):
        restored.artifact(task["id"], item["id"])


def test_failed_script_and_empty_delivery_do_not_report_completion(tmp_path):
    tasks = Tasks(tmp_path)
    for script in ["raise RuntimeError('deliberate failure')", "pass"]:
        task = tasks.start({"engine": "python", "script": script}, "ai")["task"]
        state = wait(tasks, task["id"])
        assert state["status"] == "failed" and not state["artifacts"]
        with pytest.raises(EditorError, match="尚未成功"):
            tasks.artifact(task["id"], "missing")


def test_cancel_terminates_only_the_tasks_child(tmp_path):
    tasks = Tasks(tmp_path)
    task = tasks.start({"engine": "python", "script": "import time\ntime.sleep(30)"}, "ai")["task"]
    tasks.cancel(task["id"])
    state = wait(tasks, task["id"])
    assert state["status"] == "cancelled"


def test_timeout_and_input_validation(tmp_path):
    tasks = Tasks(tmp_path)
    with pytest.raises(EditorError):
        tasks.start({"engine": "python", "script": "pass", "inputs": ["/not/a/real/file"]}, "ai")
    with pytest.raises(EditorError):
        tasks.state("../../private")
    task = tasks.start({"engine": "python", "script": "import time\ntime.sleep(30)", "timeout_seconds": 1}, "ai")[
        "task"
    ]
    state = wait(tasks, task["id"])
    assert state["status"] == "failed" and state["error"] == "任务超时"


def test_symlink_artifacts_are_not_published(tmp_path):
    tasks = Tasks(tmp_path / "tasks")
    secret = tmp_path / "outside.txt"
    secret.write_text("private")
    script = f"from pathlib import Path\nPath(workbench['output'], 'link.txt').symlink_to({str(secret)!r})"
    task = tasks.start({"engine": "python", "script": script}, "ai")["task"]
    state = wait(tasks, task["id"])
    assert state["status"] == "failed" and not state["artifacts"]
