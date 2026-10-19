"""A browser's chat identity must resolve to the HTTP server's actual project."""

import json
import threading

import pytest

from studio.core import workspaces
from studio.shell.server import create_httpd
from tests.helpers import Client


@pytest.fixture
def connected_server():
    httpd, port, backend = create_httpd(workspaces.job_dir("chat-a"), port=0)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield Client(f"http://127.0.0.1:{port}", backend.token), backend
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def bind(chat, project):
    root = workspaces.home(chat)
    root.mkdir(parents=True, exist_ok=True)
    (root / "binding.json").write_text(json.dumps({"project_id": project}))


@pytest.mark.parametrize("path", ["/api/session", "/api/state"])
def test_wrong_chat_rejected_even_with_correct_server_token(connected_server, path):
    client, _ = connected_server
    status, data = client.get(path, headers={"X-Studio-Workspace": "chat-b"})
    assert status == 409
    assert data["error"]["code"] == "workspace_mismatch"
    assert "token" not in data


def test_wrong_chat_cannot_edit_visible_project(connected_server):
    client, backend = connected_server
    before = backend.editor.state()
    status, data = client.post(
        "/api/edit", {"action": "primitive", "expected_revision": 0}, headers={"X-Studio-Workspace": "chat-b"}
    )
    assert status == 409 and data["error"]["code"] == "workspace_mismatch"
    assert backend.editor.state() == before


def test_matching_chat_shared_binding_and_standalone_still_work(connected_server):
    client, backend = connected_server
    bind("shared-chat", "chat-a")
    for chat in (None, "chat-a", "shared-chat"):
        headers = {"X-Studio-Workspace": chat} if chat else {}
        status, session = client.get("/api/session", headers=headers)
        assert status == 200 and session["job"] == str(backend.job_dir.resolve())
        assert client.get("/api/state", headers=headers)[0] == 200


def test_binding_change_invalidates_an_already_open_browser(connected_server):
    client, _ = connected_server
    bind("shared-chat", "chat-a")
    headers = {"X-Studio-Workspace": "shared-chat"}
    assert client.get("/api/session", headers=headers)[0] == 200
    bind("shared-chat", "chat-b")
    assert client.get("/api/state", headers=headers)[0] == 409
    assert client.post("/api/edit", {"action": "primitive", "expected_revision": 0}, headers=headers)[0] == 409


def test_invalid_workspace_is_a_clean_error(connected_server):
    client, _ = connected_server
    status, data = client.get("/api/session", headers={"X-Studio-Workspace": "../other"})
    assert status == 409 and data["error"]["code"] == "workspace_mismatch"
