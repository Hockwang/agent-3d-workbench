import json
import re
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
import trimesh

from studio.core.editor import EditorError
from studio.adapters.hunyuan_service import prepare_payload, result_files, receive
from studio.core.tasks import Tasks
from tests.helpers import wait


@pytest.fixture
def provider(tmp_path, monkeypatch):
    state = {"posts": [], "fail_download": False, "ambiguous": False, "auth_download": False}
    mesh = trimesh.Scene(trimesh.creation.box()).export(file_type="glb")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            assert self.path == "/responses"
            assert self.headers["Authorization"] == "Bearer private-test-key"
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            state["posts"].append(body)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps({} if state["ambiguous"] else {"id": "resp-test"}).encode())

        def do_GET(self):
            if self.path.startswith("/responses/"):
                self.send_response(200)
                self.end_headers()
                segment = state["posts"][-1]["model"].endswith("-part")
                content = (
                    [
                        {"type": "GLB", "url": f"http://127.0.0.1:{server.server_port}/{i}.glb?secret=signed"}
                        for i in range(2)
                    ]
                    if segment
                    else [{"type": "FBX", "url": f"http://127.0.0.1:{server.server_port}/mesh.fbx"}]
                )
                self.wfile.write(
                    json.dumps(
                        {"status": "completed", "output": [{"type": "3d_generation_call", "content": content}]}
                    ).encode()
                )
            else:
                state["auth_download"] |= "Authorization" in self.headers
                self.send_response(503 if state["fail_download"] else 200)
                self.end_headers()
                self.wfile.write(mesh)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    conf = tmp_path / "services.json"
    conf.write_text(
        json.dumps(
            {
                "test": {
                    "base_url": f"http://127.0.0.1:{server.server_port}",
                    "adapter": "hunyuan-responses",
                    "key_env": "TEST_HUNYUAN_KEY",
                    "operations": {x: "/responses" for x in ("text-to-3d", "image-to-3d", "segment")},
                }
            }
        )
    )
    monkeypatch.setenv("WORKBENCH_SERVICE_CONFIG", str(conf))
    monkeypatch.setenv("TEST_HUNYUAN_KEY", "private-test-key")
    yield state
    server.shutdown()
    server.server_close()


def test_part_pipeline_and_private_receipt(tmp_path, provider):
    tasks = Tasks(tmp_path / "tasks")
    # A remote FBX URL is explicit, so this never uploads an unrelated local model.
    task = tasks.start(
        {"provider": "test", "operation": "segment", "params": {"file_url": "https://assets.example/model.fbx"}}, "ai"
    )["task"]
    state = wait(tasks, task["id"])
    assert state["status"] == "completed", tasks.state(task["id"], True)
    assert any(a["name"] == "combined.glb" and a["meshes"] == 2 for a in state["artifacts"])
    assert not provider["auth_download"] and len(provider["posts"]) == 1
    body = provider["posts"][0]
    assert body["model"] == "hunyuan-3d-1.5-part" and body["background"] is True
    assert body["input"][0]["content"][0]["type"] == "input_file"
    root = tasks.folder(task["id"])
    assert (root / "hunyuan-result.json").stat().st_mode & 0o777 == 0o600
    for path in root.rglob("*"):
        if path.is_file():
            assert b"private-test-key" not in path.read_bytes()
            if path.is_relative_to(root / "output"):
                assert b"secret=signed" not in path.read_bytes()


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
    task = tasks.start(
        {"provider": "test", "operation": "text-to-3d", "params": {"prompt": "chair", "model": "hunyuan-3d-3.0-pro"}},
        "ai",
    )["task"]
    state = wait(tasks, task["id"])
    assert state["status"] == "completed", state
    assert state["service"]["adapter"] == "hunyuan-responses"
    assert state["service"]["model"] == "hunyuan-3d-3.0-pro"
    report = json.loads((tasks.folder(task["id"]) / "output" / "service.json").read_text())
    assert report["adapter"] == "hunyuan-responses"
    assert report["model"] == "hunyuan-3d-3.0-pro"
    assert report["request_params"]["prompt"] == "chair"
    assert report["request_params"]["model"] == "hunyuan-3d-3.0-pro"
    assert report["input_sha256"] == []
    assert isinstance(report["submitted_at"], float)
    dumped = json.dumps(report)
    assert "base_url" not in dumped and "private-test-key" not in dumped
    assert not _credential_shaped_keys(report)


def test_download_resume_posts_once(tmp_path, provider):
    provider["fail_download"] = True
    tasks = Tasks(tmp_path / "tasks")
    task = tasks.start({"provider": "test", "operation": "text-to-3d", "params": {"prompt": "chair"}}, "ai")["task"]
    state = wait(tasks, task["id"])
    assert state["status"] == "failed" and state["can_resume"]
    provider["fail_download"] = False
    tasks.resume(task["id"])
    assert wait(tasks, task["id"])["status"] == "completed"
    assert len(provider["posts"]) == 1
    assert provider["posts"][0]["input"][0]["content"] == [{"type": "input_text", "text": "chair"}]


def test_ambiguous_never_resubmits(tmp_path, provider):
    provider["ambiguous"] = True
    tasks = Tasks(tmp_path / "tasks")
    task = tasks.start({"provider": "test", "operation": "text-to-3d", "params": {"prompt": "chair"}}, "ai")["task"]
    state = wait(tasks, task["id"])
    assert state["status"] == "failed" and not state["can_resume"]
    with pytest.raises(EditorError):
        tasks.resume(task["id"])
    assert len(provider["posts"]) == 1


@pytest.mark.parametrize(
    "operation,params",
    [
        ("text-to-3d", {"prompt": "chair", "model": "gpt-6-astra"}),
        ("image-to-3d", {"face_count": True}),
        ("image-to-3d", {"face_count": 2}),
        ("image-to-3d", {"output_format": "../GLB"}),
        ("image-to-3d", {"pbr": "yes"}),
        ("segment", {}),
        ("segment", {"source_task": "../secret"}),
        ("segment", {"file_url": "http://localhost/model.fbx"}),
        ("segment", {"file_url": "https://assets.example/a.fbx", "source_task": "a" * 32}),
    ],
)
def test_invalid_input_before_submission(operation, params):
    with pytest.raises(EditorError):
        prepare_payload(operation, params)


def test_zip_wrapped_glb_and_zip_traversal(tmp_path, monkeypatch):
    from studio.adapters import services

    mesh = trimesh.Scene(trimesh.creation.box()).export(file_type="glb")

    def fetch(url, target):
        with zipfile.ZipFile(target, "w") as z:
            z.writestr("nested/model.glb", mesh)

    monkeypatch.setattr(services, "download", fetch)
    receive([{"url": "https://assets.example/model", "type": "GLB"}], tmp_path, "segment")
    assert (tmp_path / "combined.glb").exists()

    def malicious(url, target):
        with zipfile.ZipFile(target, "w") as z:
            z.writestr("../escape.glb", mesh)

    monkeypatch.setattr(services, "download", malicious)
    with pytest.raises(RuntimeError, match="不安全"):
        receive([{"url": "https://assets.example/x", "type": "GLB"}], tmp_path, "segment")
    assert not (tmp_path.parent / "escape.glb").exists()


def test_result_contract_is_3d_only():
    with pytest.raises(RuntimeError):
        result_files(
            {"output": [{"type": "message", "content": [{"type": "GLB", "url": "https://example.com/a.glb"}]}]}
        )


def test_generated_fbx_reference_and_image_request(tmp_path):
    from studio.adapters.hunyuan_service import build_request

    source = tmp_path / ("a" * 32)
    source.mkdir()
    (source / "service-receipt.json").write_text(json.dumps({"provider": "hunyuan", "operation": "text-to-3d"}))
    (source / "hunyuan-result.json").write_text(
        json.dumps({"files": [{"type": "FBX", "url": "https://assets.example/model.fbx?signature=private"}]})
    )
    root = tmp_path / ("b" * 32)
    body = build_request("segment", {"source_task": "a" * 32}, [], root, "hunyuan")
    assert body["input"][0]["content"][0]["file_url"].startswith("https://assets.example/")
    with pytest.raises(EditorError, match="同一"):
        build_request("segment", {"source_task": "a" * 32}, [], root, "other")
    from PIL import Image

    image = tmp_path / "image.png"
    Image.new("RGB", (32, 32), "white").save(image)
    body = build_request("image-to-3d", prepare_payload("image-to-3d", {}), [str(image)], root, "hunyuan")
    assert body["input"][0]["content"][0]["image_url"].startswith("data:image/png;base64,")
    assert body["model"] == "hunyuan-3d-3.1-pro"
    with pytest.raises(EditorError):
        build_request("image-to-3d", prepare_payload("image-to-3d", {}), [str(image)] * 2, root, "hunyuan")
