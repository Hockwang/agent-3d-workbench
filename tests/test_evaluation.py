import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import threading
import pytest
from studio.adapters.evaluation import Client, Evaluations, connection, fingerprint, identifier
from studio.core.editor import EditorError
from studio.core.tasks import Tasks
from studio.adapters.platform_preview import model_scene, safe_asset
from studio.core.assembly_review import validate_graph
from tests.helpers import content_json


@pytest.fixture
def platform(tmp_path):
    case = {
        "case_run_id": "cr-1",
        "case_id": "cabinet",
        "human_review": None,
        "artifacts": [],
        "review_artifact_sha256": "a" * 64,
    }
    view = {
        "analysis_view_id": "view-1",
        "name": "真实状态",
        "matrix": [{"comparison_group_id": "cabinet", "cells": {"b1": {"case_run_id": "cr-1"}}}] * 30,
        "conditions": [],
    }
    calls = []
    comparison = {"comparison_group_id": "cabinet", "current": None, "conditions": []}

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            calls.append(("GET", self.path, None))
            if self.path == "/api/health":
                data = {"status": "ok"}
            elif self.path == "/api/case-runs/cr-1":
                data = case
            elif self.path == "/api/analysis-views/view-1":
                data = view
            elif self.path == "/api/analysis-views/view-1/comparisons/cabinet":
                data = comparison
            elif self.path.endswith("/review-data.csv"):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"case,status\ncr-1,UNKNOWN\n")
                return
            else:
                data = []
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(data).encode())

        def do_PUT(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            calls.append(("PUT", self.path, body))
            if "/comparisons/" in self.path:
                comparison["current"] = body
            else:
                case["human_review"] = body
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps({"current": body}).encode())

        def do_POST(self):
            raw = self.rfile.read(int(self.headers["Content-Length"]))
            body = (
                {"multipart": raw.decode("utf8"), "content_type": self.headers["Content-Type"]}
                if self.path == "/api/intake-inspections"
                else json.loads(raw)
            )
            calls.append(("POST", self.path, body))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps(body).encode())

    server = ThreadingHTTPServer(("127.0.0.1", 0), H)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    ev = Evaluations(Tasks(tmp_path / "tasks"))
    ev.execute({"action": "connect", "base_url": f"http://127.0.0.1:{server.server_port}/api/"})
    yield ev, case, view, calls
    server.shutdown()
    server.server_close()
    thread.join()


def test_shared_persistence_and_pagination(platform):
    ev, case, view, calls = platform
    r = ev.execute({"action": "read", "resource": "analysis", "id": "view-1", "limit": 10, "offset": 20})
    assert r["data"]["total_rows"] == 30 and len(r["data"]["matrix"]) == 10
    assert r["sha256"] == fingerprint(view)
    ev.execute({"action": "focus", "id": "view-1", "case_run_id": "cr-1"}, "human")
    other = Evaluations(ev.tasks)
    assert other.focus()["by"] == "human"
    assert other.execute({"action": "read", "resource": "case"})["data"] == case
    with pytest.raises(EditorError):
        ev.execute({"action": "focus", "id": "view-1", "case_run_id": "wrong"})


def test_ai_draft_does_not_count_as_human(platform):
    ev, case, view, calls = platform
    r = ev.execute({"action": "read", "resource": "case", "id": "cr-1"})
    b = {
        "action": "review",
        "id": "cr-1",
        "expected_sha256": r["sha256"],
        "review": {"verdict": "FAIL", "note": "关节方向需要复核", "issue_tags": ["wrong_direction"]},
    }
    draft = ev.execute(b, "ai")
    assert draft["submitted_to_platform"] is False
    assert not any(method == "PUT" for method, _, _ in calls)
    assert ev.execute({"action": "status"})["suggestions"]
    ev.execute(b, "human")
    assert case["human_review"]["reviewer"] == "codex-human"
    with pytest.raises(EditorError, match="变化"):
        ev.execute(b, "human")
    assert sum(method == "PUT" for method, _, _ in calls) == 1


def test_stale_artifact_and_empty_note_fail_closed(platform):
    ev, case, view, calls = platform
    sha = fingerprint(case)
    case["review_artifact_sha256"] = "b" * 64
    with pytest.raises(EditorError, match="变化"):
        ev.execute(
            {"action": "review", "id": "cr-1", "expected_sha256": sha, "review": {"verdict": "PASS", "note": "x"}},
            "human",
        )
    with pytest.raises(EditorError, match="依据"):
        ev.execute(
            {"action": "review", "id": "cr-1", "expected_sha256": fingerprint(case), "review": {"verdict": "PASS"}},
            "human",
        )
    assert not any(method == "PUT" for method, _, _ in calls)


def test_report_is_deterministic_and_export_is_real(platform):
    ev, case, view, calls = platform
    r = ev.execute({"action": "report", "id": "view-1"})
    assert r["data"]["use_llm"] is False
    export = ev.execute({"action": "export", "resource": "review_data", "id": "view-1"})
    assert Path(export["path"]).read_text() == "case,status\ncr-1,UNKNOWN\n"
    assert len(export["sha256"]) == 64
    with pytest.raises(EditorError):
        ev.execute({"action": "delete", "id": "view-1"})


def test_comparison_stale_guard_and_explicit_zip_intake(platform, tmp_path):
    ev, case, view, calls = platform
    r = ev.execute({"action": "read", "resource": "comparison", "id": "view-1", "group_id": "cabinet"})
    body = {
        "action": "compare_review",
        "id": "view-1",
        "group_id": "cabinet",
        "expected_sha256": r["sha256"],
        "review": {"recommendation": "UNDETERMINED", "quality_scores": {}},
    }
    assert ev.execute(body)["saved_as"] == "ai_suggestion"
    assert not any(m == "PUT" for m, _, _ in calls)
    ev.execute(body, "human")
    with pytest.raises(EditorError, match="变化"):
        ev.execute(body, "human")
    zipfile = tmp_path / "result.zip"
    zipfile.write_bytes(b"ZIP test content")
    r = ev.execute({"action": "inspect", "files": [str(zipfile)]})
    assert 'name="files"' in r["data"]["multipart"] and "ZIP test content" in r["data"]["multipart"]
    assert not any(path == "/api/intake-batches" for _, path, _ in calls)


@pytest.mark.anyio
async def test_mcp_evaluation_shared_focus_and_attribution(mcp_session, platform):
    ev, case, view, calls = platform

    async def call(name, body):
        result = await mcp_session.call_tool(name, body)
        assert not result.is_error
        return content_json(result)

    await call("studio_evaluation", {"action": "connect", **ev.settings()})
    await call("studio_evaluation", {"action": "focus", "id": "view-1", "case_run_id": "cr-1"})
    state = await call("studio_get_state", {})
    assert state["evaluation_focus"]["case_run_id"] == "cr-1"
    r = await call("studio_evaluation", {"action": "read", "resource": "case"})
    body = {
        "action": "review",
        "id": "cr-1",
        "expected_sha256": r["sha256"],
        "review": {"verdict": "NEEDS_REVIEW", "note": "协议验证"},
    }
    assert (await call("studio_evaluation", body))["submitted_to_platform"] is False
    assert case["human_review"] is None
    # A UI-originated review is only attributed to the human when the call carries the
    # workbench nonce that studio_open hands the panel in its result metadata; without it
    # studio_ui_action is honestly recorded as the AI and the review stays an AI suggestion.
    await call("studio_ui_action", {"name": "studio_evaluation", "arguments": body})
    assert case["human_review"] is None
    opened = await mcp_session.call_tool("studio_open", {})
    nonce = opened.meta["studio/uiNonce"]
    await call("studio_ui_action", {"name": "studio_evaluation", "arguments": body, "ui_nonce": nonce})
    assert case["human_review"]["reviewer"] == "codex-human"


@pytest.mark.parametrize(
    "url",
    ["file:///tmp/a", "https://name:secret@x", "http://x/?key=a", "https://x/#a", "http://x/../a", "http://x/%2e%2e"],
)
def test_no_credential_url_or_path_escape(url):
    with pytest.raises(EditorError):
        connection({"base_url": url})


@pytest.mark.parametrize("value", ["../secret", "%2e%2e", "x/y", "", None])
def test_ids_do_not_become_paths(value):
    with pytest.raises(EditorError):
        identifier(value)


def test_redirect_never_forwards_credentials(monkeypatch):
    seen = []

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            seen.append(self.path)
            self.send_response(302)
            self.send_header("Location", "http://127.0.0.1:1/secret")
            self.end_headers()

    s = ThreadingHTTPServer(("127.0.0.1", 0), H)
    t = threading.Thread(target=s.serve_forever, daemon=True)
    t.start()
    monkeypatch.setenv("TEST_DASHBOARD_TOKEN", "secret")
    try:
        with pytest.raises(EditorError, match="302") as error:
            Client({"base_url": f"http://127.0.0.1:{s.server_port}", "auth_env": "TEST_DASHBOARD_TOKEN"}).read("health")
        assert "secret" not in str(error.value) and seen == ["/api/health"]
    finally:
        s.shutdown()
        s.server_close()
        t.join()


def test_preview_preserves_joint_frames_and_rejects_unknown_motion():
    model = {
        "schema": "assembly-dashboard-viewer-model/v1",
        "coordinateSystem": "y-up",
        "root": "frame",
        "links": [{"name": "frame", "visuals": []}, {"name": "box", "visuals": [{"file": "meshes/box.glb"}]}],
        "joints": [
            {
                "name": "slide",
                "parent": "frame",
                "child": "box",
                "motionType": "prismatic",
                "origin": [1, 2, 3],
                "axis": [1, 0, 0],
                "motionRange": [0, 0.4],
            }
        ],
    }
    s = model_scene(model, "cabinet")
    validate_graph(s)
    assert s["parts"][0]["frameOnly"] is True
    assert s["joints"][0]["origin"] == [1, 2, 3] and s["joints"][0]["motionRange"] == [0, 0.4]
    model["joints"][0]["motionType"] = "floating"
    with pytest.raises(ValueError):
        model_scene(model, "unsupported")
    for path in ["/private.glb", "../private.glb", "https://a/b.glb", "meshes/%2e%2e/private.glb", "a.gltf"]:
        with pytest.raises(ValueError):
            safe_asset(path)
