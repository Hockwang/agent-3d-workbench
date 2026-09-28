"""Codex native entries call studio_open with {} and _meta.threadId."""

import base64
import json
import sys

import pytest
from mcp import ClientSession, StdioServerParameters, stdio_client, types

from studio.shell import mcp_server
from tests.helpers import MCP_SERVER_SCRIPT


@pytest.mark.anyio
async def test_native_entry_without_arguments_binds_and_reopens_over_stdio(mcp_home, tmp_path):
    # Unlike mcp_session, intentionally do NOT configure a fallback workspace.
    params = StdioServerParameters(
        command=sys.executable,
        args=[str(MCP_SERVER_SCRIPT)],
        env={"PRINT_PREP_HOME": str(mcp_home), "CODEX_HOME": str(tmp_path / "codex"), "STUDIO_LANG": "zh-CN"},
    )
    async with stdio_client(params) as streams:
        async with ClientSession(*streams) as client:
            await client.initialize()
            meta = types.RequestParamsMeta(threadId="native-entry-a")
            opened = await client.call_tool("studio_open", {}, meta=meta)
            assert not opened.is_error, opened.content
            state = opened.structured_content
            assert state["workspace_id"] == "native-entry-a"
            assert state["workspace_mode"] == "edit"
            resource = await client.read_resource(opened.meta["ui"]["resourceUri"])
            assert 'data-workspace-id="native-entry-a"' in resource.contents[0].text
            # A UI action can immediately use the workspace's nonce and host identity.
            changed = await client.call_tool("studio_ui_action", {
                "name": "studio_edit", "ui_nonce": opened.meta["studio/uiNonce"],
                "arguments": {"action": "primitive", "expected_revision": 0},
            }, meta=meta)
            assert not changed.is_error, changed.content
            reopened = await client.call_tool("studio_open", {}, meta=meta)
            assert reopened.structured_content["workbench"]["revision"] == 1
            assert len(reopened.structured_content["workbench"]["objects"]) == 1
            assert reopened.meta["openai/widgetSessionId"] == opened.meta["openai/widgetSessionId"]
            asset = reopened.structured_content["workbench"]["objects"][0]["asset"]
            model = await client.read_resource(f"print-prep://editor/{asset}", meta=meta)
            assert base64.b64decode(model.contents[0].blob)[:4] == b"glTF"
            other = await client.call_tool("studio_open", {}, meta=types.RequestParamsMeta(threadId="native-entry-b"))
            assert not other.is_error
            assert other.structured_content["workspace_id"] == "native-entry-b"
            assert other.structured_content["workbench"]["objects"] == []
            assert other.meta["openai/widgetSessionId"] != opened.meta["openai/widgetSessionId"]
            # An earlier bound call must never become a connection-wide default.
            missing = await client.call_tool("studio_edit", {"action": "primitive", "expected_revision": 0})
            assert missing.is_error and "workspace_id" in missing.content[0].text
    assert not (mcp_home / "job").exists()


@pytest.mark.anyio
@pytest.mark.parametrize("explicit,host,configured,expected", [
    (None, "host-thread", None, "host-thread"),
    (None, "host-thread", "configured-thread", "host-thread"),
    ("explicit-thread", "host-thread", "configured-thread", "explicit-thread"),
    (None, None, "configured-thread", "configured-thread"),
    ("explicit-thread", None, None, "explicit-thread"),
])
async def test_workspace_identity_precedence(monkeypatch, explicit, host, configured, expected):
    if configured:
        monkeypatch.setenv("PRINT_PREP_WORKSPACE_ID", configured)
    seen = []

    def ensure(workspace_id):
        seen.append(workspace_id)
        return {"job": "/test/job", "url": "http://127.0.0.1:1", "token": "test"}, True

    monkeypatch.setattr(mcp_server, "_ensure_running", ensure)
    args = {"presentation": "browser"}
    if explicit:
        args["workspace_id"] = explicit
    request = types.CallToolRequestParams(name="studio_open", arguments=args,
                                         _meta={"threadId": host} if host is not None else None)
    result = await mcp_server.on_call_tool(None, request)
    assert not result.is_error
    assert json.loads(result.content[0].text)["workspace_id"] == expected
    assert seen == [expected]
    assert request.arguments == args


@pytest.mark.anyio
@pytest.mark.parametrize("host", ["../other", "legacy", 42, {"id": "task"}, ""])
async def test_invalid_host_identity_cannot_start_workspace(monkeypatch, host):
    monkeypatch.setenv("PRINT_PREP_WORKSPACE_ID", "configured-thread")
    monkeypatch.setattr(mcp_server, "_ensure_running", lambda _: pytest.fail("invalid identity reached backend"))
    request = types.CallToolRequestParams(name="studio_open", arguments={}, _meta={"threadId": host})
    result = await mcp_server.on_call_tool(None, request)
    assert result.is_error
