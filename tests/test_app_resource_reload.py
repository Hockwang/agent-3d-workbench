"""Updating the UI on disk must not require a new MCP server process."""

import pytest
import mcp.types as types

from studio.shell import app_resources, mcp_server


@pytest.mark.anyio
async def test_running_server_sees_ui_upgrade_without_switching_workspace(tmp_path, monkeypatch):
    path = tmp_path / "studio.html"
    old_html = '<main data-workspace-id="">old bundle</main>'
    new_html = '<main data-workspace-id="">new bundle</main>'
    path.write_text(old_html)
    monkeypatch.setattr(app_resources, "UI_PATH", path)
    monkeypatch.setattr(
        mcp_server,
        "_ensure_running",
        lambda _: ({"job": "/same/job", "url": "http://127.0.0.1:1", "token": "test"}, True),
    )
    monkeypatch.setattr(mcp_server, "_call_http", lambda *a, **kw: {"ok": True, "parts": []})
    request = types.CallToolRequestParams(name="studio_open", arguments={"workspace_id": "reload-test"})

    async def current():
        result = await mcp_server.on_call_tool(None, request)
        tools = await mcp_server.on_list_tools(None, None)
        descriptor = next(t for t in tools.tools if t.name == "studio_open")
        resources = await mcp_server.on_list_resources(None, None)
        uri = str(resources.resources[0].uri)
        assert descriptor.meta["ui"]["resourceUri"] == uri
        assert result.meta["ui"]["resourceUri"] == uri + "?workspace=reload-test"
        assert result.meta["openai/outputTemplate"] == result.meta["ui"]["resourceUri"]
        assert result.structured_content["workspace_id"] == "reload-test"
        return result, uri

    old, old_uri = await current()
    assert old_uri == app_resources.ui_resource_uri(old_html)
    unchanged, _ = await current()
    assert old.meta["openai/widgetSessionId"] == unchanged.meta["openai/widgetSessionId"]

    # Install atomically, while the same imported server keeps running.
    staging = tmp_path / "next.html"
    staging.write_text(new_html)
    staging.replace(path)
    new, new_uri = await current()
    assert new_uri == app_resources.ui_resource_uri(new_html)
    assert old_uri != new_uri
    assert old.meta["openai/widgetSessionId"] != new.meta["openai/widgetSessionId"]
    for uri in [old_uri, new_uri, app_resources.LEGACY_UI_URI]:
        response = await mcp_server.on_read_resource(
            None, types.ReadResourceRequestParams(uri=uri + "?workspace=reload-test")
        )
        assert response.contents[0].text == new_html.replace('data-workspace-id=""', 'data-workspace-id="reload-test"')
