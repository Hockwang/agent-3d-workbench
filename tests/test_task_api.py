import time

from tests.helpers import act, container_input, wait


def test_services_are_authenticated_and_do_not_mutate_project(studio_env, tmp_path, monkeypatch):
    monkeypatch.setenv("WORKBENCH_SERVICE_CONFIG", str(tmp_path / "service-config" / "services.json"))
    client, backend = studio_env["client"], studio_env["backend"]
    before = backend.editor.state()["revision"]
    assert client.post("/api/services", {"action": "list"}, token=None)[0] == 403
    assert client.post("/api/services", {"action": "list"}, headers={"Origin": "https://outside.test"})[0] == 403
    status, result = client.post("/api/services", {"action": "list"})
    assert status == 200 and result["encryption"]["spki"]
    status, saved = client.post(
        "/api/services",
        {
            "action": "save",
            "template": "seed3d",
            "title": "My Seed3D",
            "base_url": "https://example.test/v1",
            "key_env": "NONEXISTENT_TEST_SEED_KEY",
            "expected_revision": result["revision"],
        },
    )
    assert status == 200 and saved["id"]
    assert backend.editor.state()["revision"] == before and not backend.tasks.list()


def test_task_upload_execute_import_and_revision_conflict(studio_env):
    client, backend = studio_env["client"], studio_env["backend"]
    assert client.get("/api/tasks", token=None)[0] == 403
    assert client.get("/api/capabilities")[1]["python"]["available"]
    script = "from pathlib import Path\nimport trimesh\nPath(workbench['output'],'box.glb').write_bytes(trimesh.Scene(trimesh.creation.box(extents=[.01,.02,.03])).export(file_type='glb'))"
    status, reply = client.post(
        "/api/task", {"action": "start", "engine": "python", "script": script}, headers={"X-Studio-Actor": "human"}
    )
    assert status == 200
    tid = reply["task"]["id"]
    for _ in range(100):
        status, reply = client.get("/api/tasks?id=" + tid)
        if reply["task"]["status"] not in ("queued", "running"):
            break
        time.sleep(0.05)
    assert reply["task"]["status"] == "completed"
    assert reply["task"]["actor"] == "human"
    artifact = reply["task"]["artifacts"][0]
    assert client.get(f"/api/task-asset/{tid}/{artifact['id']}")[1][:4] == b"glTF"
    request = {"action": "import", "id": tid, "artifact_id": artifact["id"], "expected_revision": 0}
    assert client.post("/api/task", request)[0] == 200
    assert len(backend.editor.doc["objects"]) == 1
    assert client.post("/api/task", request)[0] == 409
    # Task scripts must not be duplicated into the printing pipeline history.
    meta = (studio_env["job_dir"] / "studio_meta.json").read_text()
    assert "from pathlib" not in meta


def test_selected_object_parametric_task_and_rebuild(studio_env, tmp_path):
    client, backend = studio_env["client"], studio_env["backend"]
    source = container_input(tmp_path)
    act(backend.editor, "import", files=[str(source)])
    revision = backend.editor.state()["revision"]
    request = {
        "action": "start",
        "template": "generated-container",
        "from_selection": True,
        "expected_revision": revision - 1,
    }
    assert client.post("/api/task", request)[0] == 409
    assert backend.editor.state()["revision"] == revision and not backend.tasks.list()
    request["expected_revision"] = revision
    code, reply = client.post("/api/task", request, headers={"X-Studio-Actor": "human"})
    assert code == 200, reply
    first = wait(backend.tasks, reply["task"]["id"])
    assert first["status"] == "completed", first
    assert first["actor"] == "human" and first["editable"]["inputs"]
    code, reply = client.post("/api/task", {"action": "rebuild", "id": first["id"], "params": {"inner_width_mm": 64}})
    assert code == 200, reply
    second = wait(backend.tasks, reply["task"]["id"])
    assert second["status"] == "completed", second
    assert second["source_task"] == first["id"] and second["editable"]["params"]["inner_width_mm"] == 64
    assert backend.tasks.state(first["id"])["artifacts"] == first["artifacts"]
