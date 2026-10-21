"""New Codex drafts can exist before their rollout metadata is readable."""

import pytest
import mcp.types as types

from studio.shell import codex_projects, mcp_server
from studio.shell.codex_bridge import BridgeError


THREAD = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
PENDING_ERRORS = [
    f"thread not loaded: {THREAD}",
    "failed to read thread: thread-store internal error: failed to read session metadata "
    f"/sessions/rollout-{THREAD}.jsonl: rollout at /sessions/rollout-{THREAD}.jsonl is empty",
]


def stub_bridge(monkeypatch, error):
    class Bridge:
        def __init__(self, _identity):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def read(self, thread_id):
            assert thread_id == THREAD
            raise BridgeError(error)

    monkeypatch.setattr(codex_projects, "identity", lambda: {})
    monkeypatch.setattr(codex_projects, "CodexBridge", Bridge)


@pytest.mark.parametrize("error", PENDING_ERRORS)
@pytest.mark.anyio
async def test_draft_open_returns_renderable_pending_app_without_creating_project(monkeypatch, tmp_path, error):
    stub_bridge(monkeypatch, error)
    monkeypatch.setattr(
        mcp_server.workspaces, "ensure_running", lambda *_: pytest.fail("must not create a fallback workspace")
    )
    result = await mcp_server.on_call_tool(
        None,
        types.CallToolRequestParams(
            name="studio_open",
            arguments={"mode": "tasks", "task_id": "chosen"},
            _meta={"threadId": THREAD},
        ),
    )
    assert not result.is_error
    state = result.structured_content
    assert state["startup"]["status"] == "waiting_for_thread"
    assert state["workspace_id"] == THREAD
    assert state["workspace_mode"] == "tasks" and state["focus_task_id"] == "chosen"
    assert "parts" not in state and "workbench" not in state
    assert "studio/uiNonce" not in result.meta
    assert result.meta["ui"]["resourceUri"].endswith(f"?workspace={THREAD}")
    assert not list(tmp_path.rglob("binding.json"))
    assert not list(tmp_path.rglob("project.json"))


@pytest.mark.parametrize(
    "error",
    ["permission denied", "invalid session metadata", "Codex bridge disconnected", "thread not loaded: another-thread"],
)
@pytest.mark.anyio
async def test_real_errors_still_fail_instead_of_showing_pending(monkeypatch, error):
    stub_bridge(monkeypatch, error)
    result = await mcp_server.on_call_tool(
        None, types.CallToolRequestParams(name="studio_open", arguments={"workspace_id": THREAD})
    )
    assert result.is_error
    assert error in result.content[0].text


@pytest.mark.parametrize(
    "name, arguments",
    [
        ("studio_get_state", {}),
        ("studio_edit", {"action": "primitive", "expected_revision": 0}),
        ("studio_open", {"presentation": "browser"}),
    ],
)
@pytest.mark.anyio
async def test_pending_is_not_success_for_operations_or_browser_urls(monkeypatch, name, arguments):
    stub_bridge(monkeypatch, PENDING_ERRORS[0])
    result = await mcp_server.on_call_tool(
        None, types.CallToolRequestParams(name=name, arguments={"workspace_id": THREAD, **arguments})
    )
    assert result.is_error
    assert '"code": "codex_projects.thread_not_ready"' in result.content[0].text


def test_resolved_thread_identity_is_still_checked(monkeypatch, tmp_path):
    from studio.core import projects

    with pytest.raises(ValueError):
        projects.thread_folder(THREAD, lambda _: {"id": "other", "cwd": str(tmp_path)})
