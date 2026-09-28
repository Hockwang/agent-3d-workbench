import base64
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
import trimesh
from PIL import Image

from studio.adapters.hi3d_service import prepare_payload
from studio.adapters.services import catalog, prepare
from studio.adapters.service_connections import probe
from studio.core.editor import EditorError
from studio.core.tasks import Tasks
from tests.helpers import wait


@pytest.fixture
def provider(tmp_path, monkeypatch):
    state = {
        "posts": [],
        "auths": 0,
        "download_auth": False,
        "fail_download": False,
        "ambiguous": False,
        "bad_auth": False,
        "failed": False,
        "balance": 42,
    }
    asset = trimesh.Scene(trimesh.creation.box()).export(file_type="glb")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def reply(self, data):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps(data).encode())

        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            if self.path.endswith("/auth/token"):
                assert self.headers["Authorization"] == "Basic " + base64.b64encode(b"private-ak:private-sk").decode()
                state["auths"] += 1
                self.reply(
                    {"code": 40010000, "msg": "private-sk"}
                    if state["bad_auth"]
                    else {"code": 200, "data": {"accessToken": "private-token"}}
                )
            else:
                assert self.path == "/open-api/v1/submit-task"
                assert self.headers["Authorization"] == "Bearer private-token"
                assert "multipart/form-data; boundary=" in self.headers["Content-Type"]
                assert b'name="images"' in body and b"\x89PNG" in body
                assert b'name="format"\r\n\r\n2' in body
                state["posts"].append(body)
                self.reply({"code": 200, "data": {} if state["ambiguous"] else {"task_id": "id.with.dots-1"}})

        def do_GET(self):
            if self.path.startswith("/asset"):
                state["download_auth"] |= bool(self.headers.get("Authorization"))
                self.send_response(503 if state["fail_download"] else 200)
                self.end_headers()
                self.wfile.write(asset)
                return
            assert self.headers["Authorization"] == "Bearer private-token"
            if self.path.endswith("/balance"):
                self.reply({"code": 200, "data": {"totalBalance": state["balance"]}})
            else:
                assert self.path == "/open-api/v1/query-task?task_id=id.with.dots-1"
                self.reply(
                    {
                        "code": 200,
                        "data": {
                            "state": "failed" if state["failed"] else "success",
                            "url": f"http://127.0.0.1:{server.server_port}/asset?signature=private-signature",
                        },
                    }
                )

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    config = tmp_path / "services.json"
    config.write_text(json.dumps({"hi3d": {"base_url": f"http://127.0.0.1:{server.server_port}"}}))
    monkeypatch.setenv("WORKBENCH_SERVICE_CONFIG", str(config))
    monkeypatch.setenv("HI3D_ACCESS_KEY", "private-ak")
    monkeypatch.setenv("HI3D_SECRET_KEY", "private-sk")
    path = tmp_path / "image.png"
    Image.new("RGB", (32, 32), "blue").save(path)
    state["image"] = str(path)
    yield state
    server.shutdown()
    server.server_close()


def start(tasks, provider):
    return tasks.start({"provider": "hi3d", "operation": "image-to-3d", "inputs": [provider["image"]]}, "human")[
        "task"
    ]["id"]


def test_multipart_glb_resume_and_secret_hygiene(tmp_path, provider):
    tasks = Tasks(tmp_path / "tasks")
    provider["fail_download"] = True
    task = start(tasks, provider)
    result = wait(tasks, task)
    assert result["status"] == "failed" and result["can_resume"], result
    provider["fail_download"] = False
    tasks.resume(task)
    result = wait(tasks, task)
    assert result["status"] == "completed", result
    assert any(a["name"] == "model.glb" and a["meshes"] == 1 for a in result["artifacts"])
    assert len(provider["posts"]) == 1 and provider["auths"] == 2 and not provider["download_auth"]
    report = json.loads((tasks.folder(task) / "output/service.json").read_text())
    assert report["model"] == "hitem3dv2.1" and report["input_sha256"][0]["sha256"]
    assert report["cost"] is None
    for path in tasks.folder(task).rglob("*"):
        if path.is_file():
            for secret in (b"private-ak", b"private-sk", b"private-token", b"private-signature"):
                assert secret not in path.read_bytes(), path


def test_ambiguous_submission_never_repeats(tmp_path, provider):
    tasks = Tasks(tmp_path / "tasks")
    provider["ambiguous"] = True
    task = start(tasks, provider)
    result = wait(tasks, task)
    assert result["status"] == "failed" and not result["can_resume"]
    with pytest.raises(EditorError):
        tasks.resume(task)
    assert len(provider["posts"]) == 1


def test_probe_is_non_generating_and_both_keys_required(provider, monkeypatch):
    assert probe("hi3d")["generation_tested"] is False
    assert not provider["posts"]
    monkeypatch.delenv("HI3D_SECRET_KEY")
    assert not next(p for p in catalog() if p["id"] == "hi3d")["configured"]
    with pytest.raises(EditorError):
        prepare("hi3d", "image-to-3d", {})


def test_auth_error_is_sanitized_before_submission(tmp_path, provider):
    provider["bad_auth"] = True
    tasks = Tasks(tmp_path / "tasks")
    result = wait(tasks, start(tasks, provider))
    assert result["status"] == "failed" and not provider["posts"]
    assert "private-sk" not in json.dumps(result)


def test_remote_failure_is_not_a_success(tmp_path, provider):
    provider["failed"] = True
    tasks = Tasks(tmp_path / "tasks")
    result = wait(tasks, start(tasks, provider))
    assert result["status"] == "failed" and len(provider["posts"]) == 1


@pytest.mark.parametrize(
    "params",
    [
        {"model": "gpt-6"},
        {"request_type": 2},
        {"format": 3},
        {"face": True},
        {"model": "hi3dv3.0", "resolution": "512"},
        {"shading": 0.15},
        {"prompt": "x"},
    ],
)
def test_invalid_generation_parameters(params):
    with pytest.raises(EditorError):
        prepare_payload("image-to-3d", params)


def test_invalid_image_never_submits(tmp_path, provider):
    from pathlib import Path

    Path(provider["image"]).write_text("not an image")
    tasks = Tasks(tmp_path / "tasks")
    result = wait(tasks, start(tasks, provider))
    assert result["status"] == "failed" and not provider["posts"]


def test_demo_through_stdio_mcp_import_edit_undo_export(tmp_path, provider):
    import asyncio
    from pathlib import Path
    from examples.api_generation.run_demo import run

    config = tmp_path / "services.json"
    out = tmp_path / "demo"
    report = asyncio.run(run(out, "generate", Path(provider["image"]), config))
    assert report["status"] == "passed", report
    assert report["scaled_0_5_verified"] and report["undo_verified"] and report["export_bounds_verified"]
    assert len(provider["posts"]) == 1 and not provider["download_auth"]
    with pytest.raises(RuntimeError, match="already contains a task"):
        asyncio.run(run(out, "generate", Path(provider["image"]), config))
    assert asyncio.run(run(out, "resume", service_config=config)) == report
    assert len(provider["posts"]) == 1


def test_demo_zero_balance_does_not_submit(tmp_path, provider):
    import asyncio
    from pathlib import Path
    from examples.api_generation.run_demo import run

    provider["balance"] = 0
    result = asyncio.run(run(tmp_path / "demo", "generate", Path(provider["image"]), tmp_path / "services.json"))
    assert result["status"] == "blocked_no_api_balance" and not provider["posts"]
