"""Documented Assembly contract exercised over real HTTP and task subprocesses."""

import io
import json
import re
import stat
import threading
import urllib.parse
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
import trimesh

from studio.adapters.assembly_service import OPERATIONS, artifact_urls, prepare_payload, safe_extract
from studio.core.editor import EditorError
from studio.adapters.services import catalog, credential_refs, prepare
from studio.core.tasks import Tasks
from tests.helpers import wait


@pytest.fixture
def assembly(tmp_path, monkeypatch):
    state = dict(posts=0, codes=[10001, 0], ambiguous=False, fail_download=False, queries=[], asset_headers=[])
    glb = trimesh.Scene(trimesh.creation.box()).export(file_type="glb")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as package:
        package.writestr("meshes/result.glb", glb)
        package.writestr("robot.urdf", '<robot name="test"/>')
        package.writestr("untrusted.py", 'raise Exception("must not run")')
        package.writestr("index.html", "<script>untrusted</script>")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def reply(self, body, status=200):
            self.send_response(status)
            self.end_headers()
            self.wfile.write(body if isinstance(body, bytes) else json.dumps(body).encode())

        def do_POST(self):
            state["posts"] += 1
            state["post_path"] = self.path
            state["auth"] = self.headers.get("Authorization")
            state["payload"] = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            self.reply(
                {} if state["ambiguous"] else {"c": "0", "m": "", "d": {"promptId": "assembly-test-id", "number": 1}}
            )

        def do_GET(self):
            parsed = urllib.parse.urlsplit(self.path)
            if parsed.path.startswith("/assets/"):
                state["asset_headers"].append(self.headers.get("Authorization"))
                data = glb if parsed.path.endswith(".glb") else buffer.getvalue()
                self.reply(data, 503 if state["fail_download"] else 200)
                return
            state["queries"].append(urllib.parse.parse_qs(parsed.query))
            code = state["codes"].pop(0) if len(state["codes"]) > 1 else state["codes"][0]
            node = state["queries"][-1]["nodeName"][0]
            ext = ".glb" if node in ("AssemblyAgentRiggedGLBOutput", "AssemblyAgentSegmentedGLBExport") else ".zip"
            url = f"http://127.0.0.1:{server.server_port}/assets/result{ext}?signature=test-result-signature"
            self.reply({"c": code, "m": "never log this raw message", "d": {"value": url, "output": {"glbUrl": url}}})

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    config = tmp_path / "services.json"
    config.write_text(
        json.dumps(
            {
                "assembly": {
                    "enabled": True,
                    "base_url": f"http://127.0.0.1:{server.server_port}",
                    "headers_env": {"Authorization": "ASSEMBLY_TEST_AUTH"},
                    "oneapi_appkey_env": "ASSEMBLY_TEST_LLM",
                    "initial_poll_delay": 0,
                    "poll_interval": 1,
                    "max_polls": 3,
                }
            }
        )
    )
    monkeypatch.setenv("WORKBENCH_SERVICE_CONFIG", str(config))
    monkeypatch.setenv("ASSEMBLY_TEST_AUTH", "Bearer private-test-auth")
    monkeypatch.setenv("ASSEMBLY_TEST_LLM", "private-test-llm")
    yield state
    server.shutdown()
    server.server_close()


def submit(tasks, operation="assemble"):
    params = (
        {"prompt": "open drawers"}
        if operation == "motion"
        else {"meshUrl": "https://example.com/input.glb", "prompt": "open drawers"}
    )
    return tasks.start({"provider": "assembly", "operation": operation, "params": params}, "ai")["task"]


@pytest.mark.parametrize("operation", OPERATIONS)
def test_documented_templates_nodes_and_artifact_delivery(tmp_path, assembly, operation):
    tasks = Tasks(tmp_path / "tasks")
    task = submit(tasks, operation)
    result = wait(tasks, task["id"])
    assert result["status"] == "completed", result
    assert assembly["posts"] == 1
    assert assembly["post_path"] == "/cubely/v1/workflow"
    assert assembly["payload"]["workflowTemplateId"] == OPERATIONS[operation][0]
    assert assembly["payload"]["oneapiAppKey"] == "private-test-llm"
    assert assembly["auth"] == "Bearer private-test-auth"
    assert assembly["queries"][-1] == {"promptId": ["assembly-test-id"], "nodeName": [OPERATIONS[operation][1]]}
    assert not any(assembly["asset_headers"])
    assert any(a.get("meshes") == 1 for a in result["artifacts"])
    assert not any(a["name"].endswith((".py", ".html")) for a in result["artifacts"])
    assert result["service"]["remote_id"] == "assembly-test-id"
    for path in (tmp_path / "tasks").rglob("*"):
        if path.is_file():
            content = path.read_bytes()
            for secret in (b"private-test-auth", b"private-test-llm", b"test-result-signature"):
                assert secret not in content, path


def _credential_shaped_keys(value):
    if isinstance(value, dict):
        return [k for k in value if re.search("key|token|secret|authorization", k, re.I)] + [
            k for v in value.values() for k in _credential_shaped_keys(v)
        ]
    if isinstance(value, list):
        return [k for item in value for k in _credential_shaped_keys(item)]
    return []


def test_service_json_carries_provenance_without_credentials(tmp_path, assembly):
    tasks = Tasks(tmp_path / "tasks")
    task = submit(tasks, "assemble")
    result = wait(tasks, task["id"])
    assert result["status"] == "completed", result
    assert result["service"]["adapter"] == "assembly"
    assert result["service"]["model"] == OPERATIONS["assemble"][0]
    report = json.loads((tasks.folder(task["id"]) / "output" / "service.json").read_text())
    assert report["adapter"] == "assembly"
    assert report["model"] == OPERATIONS["assemble"][0]
    assert report["request_params"]["meshUrl"] == "https://example.com/input.glb"
    assert report["request_params"]["prompt"] == "open drawers"
    assert report["input_sha256"] == []
    assert isinstance(report["submitted_at"], float)
    dumped = json.dumps(report)
    assert "base_url" not in dumped
    assert "oneapiAppKey" not in dumped and "private-test-llm" not in dumped
    assert not _credential_shaped_keys(report)


def test_resume_after_download_failure_never_resubmits(tmp_path, assembly):
    tasks = Tasks(tmp_path / "tasks")
    assembly["fail_download"] = True
    task = submit(tasks)
    failed = wait(tasks, task["id"])
    assert failed["status"] == "failed" and failed["can_resume"], failed
    assembly["fail_download"] = False
    tasks.resume(task["id"])
    assert wait(tasks, task["id"])["status"] == "completed"
    assert assembly["posts"] == 1


@pytest.mark.parametrize("code", [10002, 10001, -1, 777])
def test_remote_failure_and_timeout_preserve_id(tmp_path, assembly, code):
    tasks = Tasks(tmp_path / "tasks")
    assembly["codes"] = [code]
    task = submit(tasks)
    failed = wait(tasks, task["id"])
    assert failed["status"] == "failed" and failed["can_resume"], failed
    assert failed["service"]["remote_id"] == "assembly-test-id"
    assembly["codes"] = [0]
    tasks.resume(task["id"])
    assert wait(tasks, task["id"])["status"] == "completed"
    assert assembly["posts"] == 1


def test_ambiguous_submit_cannot_retry(tmp_path, assembly):
    tasks = Tasks(tmp_path / "tasks")
    assembly["ambiguous"] = True
    task = submit(tasks)
    result = wait(tasks, task["id"])
    assert result["status"] == "failed" and not result["can_resume"]
    with pytest.raises(EditorError):
        tasks.resume(task["id"])
    assert assembly["posts"] == 1


def test_service_metadata_and_no_implicit_upload(tmp_path, assembly):
    item = next(x for x in catalog() if x["id"] == "assembly")
    assert item["configured"] and item["input_mode"] == "remote_urls"
    assert len(item["operation_templates"]) == 5
    with pytest.raises(EditorError, match="上传"):
        Tasks(tmp_path / "tasks").start(
            {
                "provider": "assembly",
                "operation": "segment",
                "inputs": ["/tmp/private.glb"],
                "params": {"meshUrl": "https://example.com/model.glb"},
            },
            "ai",
        )
    with pytest.raises(EditorError, match="凭据"):
        prepare("assembly", "assemble", {"oneapiAppKey": "secret"})
    assert assembly["posts"] == 0


@pytest.mark.parametrize(
    "payload",
    [
        {"meshUrl": "/tmp/model.glb"},
        {"meshUrl": "http://localhost/model.glb"},
        {"meshUrl": "https://example.com/model.glb", "uid": "123"},
        {"meshUrl": "https://example.com/model.glb", "workflowTemplateId": "wrong"},
        {"meshUrl": "https://example.com/model.glb", "meshUpAxis": "x_up"},
        {"meshUrl": "https://example.com/model.glb", "cubeParts": []},
    ],
)
def test_invalid_model_inputs_rejected(payload):
    with pytest.raises(EditorError):
        prepare_payload("segment", payload)


def test_aliases_from_node_and_motion_semantics():
    payload = prepare_payload("segment", {"glburl": "https://example.com/model.glb", "cube_parts": "door,frame"})
    assert payload["meshUrl"].endswith(".glb") and payload["cubeParts"] == ["door", "frame"]
    payload = prepare_payload(
        "assemble",
        {
            "prompt": "open",
            "from": {
                "fromNodeType": "AssemblyAgentSegmentedGLBExport",
                "fromNodeInput": {"segmentedGlb": "https://example.com/seg.glb"},
            },
        },
    )
    assert payload["workflowTemplateId"] == "workflow_assembly_prod"
    assert prepare_payload("motion", {"prompt": "walk", "duration": 5})["duration"] == "5"
    for invalid in (
        {"prompt": ""},
        {"prompt": "walk", "duration": True},
        {"prompt": "walk", "inputUrl": "https://example.com/model.glb"},
        {"prompt": "walk", "numSamples": 1.5},
    ):
        with pytest.raises(EditorError):
            prepare_payload("motion", invalid)


def test_zip_named_glb_url_keeps_zip_and_deduplicates():
    url = "https://example.com/agentic_package_glb.zip?signature=private"
    assert artifact_urls({"value": url, "output": {"glbUrl": url}}, "assemble") == [("00-primary.zip", url)]


@pytest.mark.parametrize("unsafe", ["../escape.glb", "/absolute.glb", "a\\escape.glb", "A.glb"])
def test_zip_preflight_does_not_leave_partial_files(tmp_path, unsafe):
    archive = tmp_path / "result.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("a.glb", b"good")
        z.writestr(unsafe, b"bad")
    dest = tmp_path / "files"
    with pytest.raises(RuntimeError):
        safe_extract(archive, dest)
    assert not dest.exists()


def test_zip_links_rejected_and_resume_replaces_old_tree(tmp_path):
    archive = tmp_path / "result.zip"
    dest = tmp_path / "files"
    dest.mkdir()
    (dest / "old.glb").write_bytes(b"old")
    with zipfile.ZipFile(archive, "w") as z:
        link = zipfile.ZipInfo("link.glb")
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        z.writestr(link, "../outside")
    with pytest.raises(RuntimeError):
        safe_extract(archive, dest)
    assert (dest / "old.glb").exists()
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("new.glb", b"new")
    safe_extract(archive, dest)
    assert not (dest / "old.glb").exists() and (dest / "new.glb").read_bytes() == b"new"


@pytest.mark.parametrize(
    "spec",
    [
        {"enabled": "true"},
        {"key_env": "a secret"},
        {"headers_env": {"Host": "TEST"}},
        {"headers_env": {"Authorization": "Bearer secret"}},
    ],
)
def test_bad_credential_references_rejected(spec):
    with pytest.raises(EditorError):
        credential_refs(spec)
