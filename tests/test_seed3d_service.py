import io
import json
import re
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
import trimesh

from studio.core.editor import EditorError
from studio.adapters.seed3d_service import prepare_payload
from studio.core.tasks import Tasks
from tests.helpers import wait


@pytest.fixture
def provider(tmp_path, monkeypatch):
    state = {"posts": [], "download_auth": False, "fail_download": False, "ambiguous": False}
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as out:
        out.writestr("pbr/model.glb", trimesh.Scene(trimesh.creation.box()).export(file_type="glb"))

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            assert self.path == "/chat/completions" and self.headers["Authorization"] == "Bearer private-seed-key"
            state["posts"].append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            self.send_response(200)
            self.end_headers()
            content = [
                {
                    "type": "3d_generation_call",
                    "content": [
                        {"type": "GLB", "url": f"http://127.0.0.1:{server.server_port}/asset?signature=secret"}
                    ],
                }
            ]
            self.wfile.write(
                json.dumps(
                    {} if state["ambiguous"] else {"choices": [{"message": {"content": json.dumps(content)}}]}
                ).encode()
            )

        def do_GET(self):
            state["download_auth"] |= "Authorization" in self.headers
            self.send_response(503 if state["fail_download"] else 200)
            self.end_headers()
            self.wfile.write(archive.getvalue())

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    conf = tmp_path / "services.json"
    conf.write_text(
        json.dumps({"seed3d": {"base_url": f"http://127.0.0.1:{server.server_port}", "key_env": "TEST_SEED_KEY"}})
    )
    monkeypatch.setenv("WORKBENCH_SERVICE_CONFIG", str(conf))
    monkeypatch.setenv("TEST_SEED_KEY", "private-seed-key")
    yield state
    server.shutdown()
    server.server_close()


def start(tasks):
    return tasks.start(
        {"provider": "seed3d", "operation": "image-to-3d", "params": {"image_url": "https://assets.test/chair.png"}},
        "human",
    )["task"]["id"]


def test_real_http_download_resume_never_regenerates(tmp_path, provider):
    tasks = Tasks(tmp_path / "tasks")
    provider["fail_download"] = True
    task = start(tasks)
    result = wait(tasks, task)
    assert result["status"] == "failed" and result["can_resume"]
    provider["fail_download"] = False
    tasks.resume(task)
    result = wait(tasks, task)
    assert result["status"] == "completed", result
    assert any(a["name"].endswith("model.glb") and a["meshes"] == 1 for a in result["artifacts"])
    assert len(provider["posts"]) == 1 and not provider["download_auth"]
    assert provider["posts"][0]["model"] == "doubao-seed3d-2.0"
    folder = tasks.folder(task)
    assert (folder / "seed3d-result.json").stat().st_mode & 0o777 == 0o600
    for path in folder.rglob("*"):
        if path.is_file():
            assert b"private-seed-key" not in path.read_bytes()
            if path.is_relative_to(folder / "output"):
                assert b"signature=secret" not in path.read_bytes()


def _credential_shaped_keys(value):
    if isinstance(value, dict):
        return [k for k in value if re.search("key|token|secret|authorization", k, re.I)] + [
            k for v in value.values() for k in _credential_shaped_keys(v)
        ]
    if isinstance(value, list):
        return [k for item in value for k in _credential_shaped_keys(item)]
    return []


def test_service_json_carries_provenance_without_credentials(tmp_path, provider):
    tasks = Tasks(tmp_path / "tasks")
    task = start(tasks)
    result = wait(tasks, task)
    assert result["status"] == "completed", result
    assert result["service"]["adapter"] == "seed3d-chat"
    assert result["service"]["model"] == "doubao-seed3d-2.0"
    report = json.loads((tasks.folder(task) / "output" / "service.json").read_text())
    assert report["adapter"] == "seed3d-chat"
    assert report["model"] == "doubao-seed3d-2.0"
    assert report["request_params"]["image_url"] == "https://assets.test/chair.png"
    assert report["input_sha256"] == []
    assert isinstance(report["submitted_at"], float)
    dumped = json.dumps(report)
    assert "base_url" not in dumped and "private-seed-key" not in dumped
    assert not _credential_shaped_keys(report)


def test_ambiguous_seed_response_cannot_retry(tmp_path, provider):
    provider["ambiguous"] = True
    tasks = Tasks(tmp_path / "tasks")
    task = start(tasks)
    result = wait(tasks, task)
    assert result["status"] == "failed" and not result["can_resume"]
    with pytest.raises(EditorError):
        tasks.resume(task)
    assert len(provider["posts"]) == 1


def test_only_specialized_model_operation_allowed():
    with pytest.raises(EditorError):
        prepare_payload("image-to-3d", {"model": "gpt-6"})
    with pytest.raises(EditorError):
        prepare_payload("segment", {})
