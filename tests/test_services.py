import hashlib
import json
import os
from pathlib import Path
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
import trimesh

from studio.core.tasks import Tasks
from studio.adapters.services import _sanitize_request_params, config, prepare
from studio.core.editor import EditorError
from tests.helpers import wait


@pytest.fixture
def provider(tmp_path, monkeypatch):
    state = {"posts": 0, "gets": 0, "fail_download": False, "ambiguous": False, "auth_on_download": False}
    raw = trimesh.Scene(trimesh.creation.box()).export(file_type="glb")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            state["posts"] += 1
            assert self.headers["Authorization"] == "Bearer test-private-key"
            size = int(self.headers["Content-Length"])
            body = json.loads(self.rfile.read(size))
            state["payload"] = body
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps({} if state["ambiguous"] else {"result": "test-remote-id"}).encode())

        def do_GET(self):
            state["gets"] += 1
            if self.path == "/model.glb":
                state["auth_on_download"] = "Authorization" in self.headers
                self.send_response(503 if state["fail_download"] else 200)
                self.end_headers()
                self.wfile.write(raw)
            else:
                self.send_response(200)
                self.end_headers()
                self.wfile.write(
                    json.dumps(
                        {
                            "status": "SUCCEEDED",
                            "model_urls": {"glb": f"http://127.0.0.1:{server.server_port}/model.glb"},
                        }
                    ).encode()
                )

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    path = tmp_path / "services.json"
    path.write_text(
        json.dumps(
            {
                "test": {
                    "base_url": f"http://127.0.0.1:{server.server_port}",
                    "key_env": "TEST_PROVIDER_KEY",
                    "adapter": "meshy",
                    "operations": {"text-to-3d": "/tasks"},
                }
            }
        )
    )
    monkeypatch.setenv("WORKBENCH_SERVICE_CONFIG", str(path))
    monkeypatch.setenv("TEST_PROVIDER_KEY", "test-private-key")
    yield state
    server.shutdown()
    server.server_close()


def test_real_http_contract_and_credential_isolation(tmp_path, provider):
    tasks = Tasks(tmp_path / "tasks")
    t = tasks.start({"provider": "test", "operation": "text-to-3d", "params": {"prompt": "box"}}, "human")["task"]
    state = wait(tasks, t["id"])
    assert state["status"] == "completed", state
    assert state["service"]["remote_id"] == "test-remote-id"
    assert provider["posts"] == 1 and not provider["auth_on_download"]
    assert provider["payload"] == {"prompt": "box", "mode": "preview"}
    assert any(a.get("meshes") == 1 for a in state["artifacts"])
    for path in (tmp_path / "tasks").rglob("*"):
        if path.is_file():
            assert b"test-private-key" not in path.read_bytes()


def test_download_failure_resume_does_not_submit_twice(tmp_path, provider):
    provider["fail_download"] = True
    tasks = Tasks(tmp_path / "tasks")
    t = tasks.start({"provider": "test", "operation": "text-to-3d"}, "ai")["task"]
    state = wait(tasks, t["id"])
    assert state["status"] == "failed" and state["can_resume"]
    provider["fail_download"] = False
    tasks.resume(t["id"])
    assert wait(tasks, t["id"])["status"] == "completed"
    assert provider["posts"] == 1


def test_ambiguous_submission_cannot_auto_retry(tmp_path, provider):
    provider["ambiguous"] = True
    tasks = Tasks(tmp_path / "tasks")
    t = tasks.start({"provider": "test", "operation": "text-to-3d"}, "ai")["task"]
    state = wait(tasks, t["id"])
    assert state["status"] == "failed" and not state["can_resume"]
    with pytest.raises(EditorError):
        tasks.resume(t["id"])
    assert provider["posts"] == 1


def test_credentials_are_references_not_job_parameters(provider):
    with pytest.raises(EditorError, match="凭据"):
        prepare("test", "text-to-3d", {"api_key": "private"})


def test_sanitize_request_params_redacts_credential_shaped_keys_only():
    raw = {
        "prompt": "box",
        "webhookApiKey": "x",
        "nested": {"authToken": "y", "count": 2},
        "list": [{"clientSecret": "z"}, "keep"],
    }
    assert _sanitize_request_params(raw) == {
        "prompt": "box",
        "webhookApiKey": "<redacted>",
        "nested": {"authToken": "<redacted>", "count": 2},
        "list": [{"clientSecret": "<redacted>"}, "keep"],
    }


def test_sanitize_request_params_trims_urls_and_local_paths():
    raw = {
        "image_url": "https://cdn.example.com/signed/a.png?token=SECRETXYZ&exp=99",
        "file_url": "https://cdn.example.com/files/b.glb#frag",
        "mesh": {"$file": "/Users/me/models/part-07.glb"},
        "images": [{"$file": "/tmp/in/a.png"}, "https://cdn.example.com/c.png?x=1"],
        "output_path": "/Users/me/out/result.glb",
        "prompt": "a red /not/a/real/path chair",
        "webhookApiKey": "secret",
    }
    assert _sanitize_request_params(raw) == {
        "image_url": "https://cdn.example.com/signed/a.png",
        "file_url": "https://cdn.example.com/files/b.glb",
        "mesh": "part-07.glb",
        "images": ["a.png", "https://cdn.example.com/c.png"],
        "output_path": "result.glb",
        "prompt": "a red /not/a/real/path chair",
        "webhookApiKey": "<redacted>",
    }
    # No query/fragment to drop: a plain URL is unchanged, not just "shortened".
    assert _sanitize_request_params({"img": "https://cdn.example.com/plain.png"}) == {
        "img": "https://cdn.example.com/plain.png"
    }


def test_service_json_and_task_state_carry_full_provenance(tmp_path, provider):
    tasks = Tasks(tmp_path / "tasks")
    local = tmp_path / "ref.bin"
    local.write_bytes(b"reference bytes")
    t = tasks.start(
        {
            "provider": "test",
            "operation": "text-to-3d",
            "params": {"prompt": "box", "model": "mesh-v1"},
            "inputs": [str(local)],
        },
        "human",
    )["task"]
    state = wait(tasks, t["id"])
    assert state["status"] == "completed", state

    service = state["service"]
    assert service["adapter"] == "meshy" and service["model"] == "mesh-v1"
    assert service["cost_unit"] == "provider credits"
    assert service["submitted_at"] and service["polled_at"] and service["received_at"]
    assert service["submitted_at"] <= service["polled_at"] <= service["received_at"]

    record = json.loads((tasks.folder(t["id"]) / "output" / "service.json").read_text())
    assert record["adapter"] == "meshy" and record["model"] == "mesh-v1"
    assert record["request_params"] == {"prompt": "box", "model": "mesh-v1"}
    assert record["input_sha256"] == [{"name": "ref.bin", "sha256": hashlib.sha256(local.read_bytes()).hexdigest()}]
    assert record["submitted_at"] == service["submitted_at"]
    assert "base_url" not in record
    for path in (tmp_path / "tasks").rglob("*"):
        if path.is_file():
            assert b"test-private-key" not in path.read_bytes()


def test_local_inputs_and_timeout_are_spec_driven_not_hardcoded(tmp_path, provider):
    config_path = Path(os.environ["WORKBENCH_SERVICE_CONFIG"])
    config = json.loads(config_path.read_text())
    # Mirrors a real "assembly"-shaped spec (remote-only inputs, long timeout) without
    # being named "assembly" -- the policy must come from the spec, not the adapter id.
    config["no-local-inputs"] = {**config["test"], "local_inputs_allowed": False, "default_timeout_seconds": 1800}
    # A custom provider that never sets either key must keep today's defaults.
    config["custom-generic"] = {**config["test"]}
    config_path.write_text(json.dumps(config))

    tasks = Tasks(tmp_path / "tasks")
    local = tmp_path / "ref.bin"
    local.write_bytes(b"x")

    with pytest.raises(EditorError):
        tasks.start(
            {
                "provider": "no-local-inputs",
                "operation": "text-to-3d",
                "params": {"prompt": "a"},
                "inputs": [str(local)],
            },
            "ai",
        )

    t = tasks.start({"provider": "no-local-inputs", "operation": "text-to-3d", "params": {"prompt": "a"}}, "ai")["task"]
    request = json.loads((tasks.folder(t["id"]) / "request.json").read_text())
    assert request["timeout_seconds"] == 1800
    wait(tasks, t["id"])

    t2 = tasks.start({"provider": "custom-generic", "operation": "text-to-3d", "params": {"prompt": "b"}}, "ai")["task"]
    request2 = json.loads((tasks.folder(t2["id"]) / "request.json").read_text())
    assert request2["timeout_seconds"] == 600
    wait(tasks, t2["id"])


def test_services_json_custom_name_derives_policy_from_matching_adapter_id(tmp_path, monkeypatch):
    # A custom-named services.json entry that never sets its own policy keys (as
    # written before either existed in BUILTINS) must still inherit the built-in
    # `assembly` entry's `local_inputs_allowed: False`/`1800` because it shares that
    # adapter id -- not silently fall back to the generic True/600 defaults.
    path = tmp_path / "services.json"
    path.write_text(
        json.dumps(
            {
                "my-assembly": {
                    "adapter": "assembly",
                    "base_url": "https://api-beta.aholo3d.cn",
                    "enabled": True,
                    "operations": {"assemble": "assemble"},
                }
            }
        )
    )
    monkeypatch.setenv("WORKBENCH_SERVICE_CONFIG", str(path))
    spec = config()["my-assembly"]
    assert spec["local_inputs_allowed"] is False
    assert spec["default_timeout_seconds"] == 1800

    # An explicit value on the entry itself still wins over the derived default.
    path.write_text(
        json.dumps(
            {
                "my-assembly": {
                    "adapter": "assembly",
                    "base_url": "https://api-beta.aholo3d.cn",
                    "enabled": True,
                    "operations": {"assemble": "assemble"},
                    "local_inputs_allowed": True,
                    "default_timeout_seconds": 42,
                }
            }
        )
    )
    spec = config()["my-assembly"]
    assert spec["local_inputs_allowed"] is True
    assert spec["default_timeout_seconds"] == 42
