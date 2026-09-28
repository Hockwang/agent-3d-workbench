"""Browser opens must preserve the requested mode, task and workspace."""
import json
from urllib.parse import parse_qs, urlparse

import mcp.types as types
import pytest

from studio.shell import mcp_server


@pytest.mark.anyio
@pytest.mark.parametrize("mode,task", [("print", None), ("edit", "model-task")])
async def test_browser_open_keeps_destination(monkeypatch, mode, task):
    monkeypatch.setattr(mcp_server, "_ensure_running", lambda _: (
        {"job": "/test/job", "url": "http://127.0.0.1:1", "token": "test"}, True))
    args = {"workspace_id": "entry-test", "presentation": "browser", "mode": mode}
    if task:
        args["task_id"] = task
    result = await mcp_server.on_call_tool(None, types.CallToolRequestParams(name="studio_open", arguments=args))
    payload = json.loads(result.content[0].text)
    query = parse_qs(urlparse(payload["url"]).query)
    assert query["workspace"] == ["entry-test"]
    assert query["mode"] == ["tasks" if task else mode]
    assert query.get("task") == ([task] if task else None)
