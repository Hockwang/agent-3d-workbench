"""SPEC.md §10 P1：stdio MCP 服务 `studio/shell/mcp_server.py` 的测试。

用官方 `mcp` SDK 的 `stdio_client` 把 `studio/shell/mcp_server.py` 当子进程拉起，走
真实的 stdio 协议；`PRINT_PREP_HOME` 指到临时目录（子进程默认只继承一份很窄
的环境变量白名单 + 我们显式塞的这一个，不会碰真实的 `~/.print-prep`）。测试
结束务必把 `studio_open`/工具调用间接拉起的本机服务停掉。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_PLUGIN_ROOT = Path(__file__).resolve().parent.parent
if str(_PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(_PLUGIN_ROOT))

import studio  # noqa: E402
from studio.shell import tools_schema  # noqa: E402
from tests.helpers import content_json  # noqa: E402


@pytest.mark.anyio
async def test_editor_mcp_human_ai_assets_and_export(mcp_session):
    import base64

    result = await mcp_session.call_tool("studio_open", {"mode": "edit"})
    assert not result.is_error
    state = result.structured_content
    assert state["workspace_mode"] == "edit"
    nonce = result.meta["studio/uiNonce"]
    body = {
        "action": "primitive",
        "expected_revision": state["workbench"]["revision"],
        "params": {"size": [20, 30, 40]},
    }
    created = await mcp_session.call_tool(
        "studio_ui_action", {"name": "studio_edit", "arguments": body, "ui_nonce": nonce}
    )
    assert not created.is_error
    state = content_json(await mcp_session.call_tool("studio_get_state", {}))["workbench"]
    asset = state["objects"][0]["asset"]
    resource = await mcp_session.read_resource(f"print-prep://editor/{asset}")
    assert base64.b64decode(resource.contents[0].blob)[:4] == b"glTF"
    result = await mcp_session.call_tool("studio_edit", {"action": "plane_cut", "expected_revision": state["revision"]})
    assert not result.is_error
    state = content_json(await mcp_session.call_tool("studio_get_state", {}))["workbench"]
    assert len(state["objects"]) == 2
    assert [h["actor"] for h in state["history"]] == ["human", "ai"]
    result = await mcp_session.call_tool(
        "studio_ui_action",
        {
            "name": "studio_edit",
            "arguments": {"action": "undo", "expected_revision": state["revision"]},
            "ui_nonce": nonce,
        },
    )
    assert not result.is_error
    state = content_json(await mcp_session.call_tool("studio_get_state", {}))["workbench"]
    assert len(state["objects"]) == 1
    result = await mcp_session.call_tool("studio_edit", {"action": "export", "expected_revision": state["revision"]})
    assert not result.is_error
    assert Path(content_json(result)["path"]).read_bytes()[:4] == b"glTF"


@pytest.mark.anyio
async def test_tools_list_contains_workflow_and_app_tools(mcp_session):
    result = await mcp_session.list_tools()
    names = {t.name for t in result.tools}
    expected = {t["name"] for t in tools_schema.get_tools()} | {
        "studio_open",
        "studio_ui_action",
        "studio_workspaces",
        "studio_part_chat",
    }
    assert names == expected
    assert len(expected) == 26
    assert "studio_services" in names
    assert "studio_evaluation" in names
    bridge = next(t for t in result.tools if t.name == "studio_ui_action")
    assert bridge.meta["ui"]["visibility"] == ["app"]
    direct = next(t for t in result.tools if t.name == "studio_part_chat")
    assert direct.meta["ui"]["visibility"] == ["app"]
    # Exercises the actual workspace-scoped subprocess environment, not just
    # an in-process HTTP fixture. Never forks a real user task in unit tests.
    opened = await mcp_session.call_tool("studio_open", {})
    nonce = opened.meta["studio/uiNonce"]
    status = await mcp_session.call_tool("studio_part_chat", {"action": "status", "ui_nonce": nonce})
    assert not status.is_error
    assert status.structured_content["decision"] == "ask"


@pytest.mark.anyio
async def test_task_workspace_and_artifact_over_mcp(mcp_session):
    import asyncio
    import base64

    result = await mcp_session.call_tool("studio_open", {"mode": "tasks"})
    assert result.structured_content["workspace_mode"] == "tasks"
    nonce = result.meta["studio/uiNonce"]
    caps = content_json(await mcp_session.call_tool("studio_capabilities", {}))
    assert {"hair-cards", "cad-model", "assembly-audit"} <= {x["id"] for x in caps["templates"]}
    started = await mcp_session.call_tool(
        "studio_ui_action",
        {
            "name": "studio_task",
            "arguments": {
                "action": "start",
                "engine": "python",
                "script": "from pathlib import Path\nPath(workbench['output'],'report.json').write_text('{\"verified\":true}')",
            },
            "ui_nonce": nonce,
        },
    )
    task = content_json(started)["task"]
    assert task["actor"] == "human"
    for _ in range(100):
        task = content_json(await mcp_session.call_tool("studio_tasks", {"id": task["id"]}))["task"]
        if task["status"] not in ("queued", "running"):
            break
        await asyncio.sleep(0.05)
    assert task["status"] == "completed"
    artifact = task["artifacts"][0]
    resource = await mcp_session.read_resource(f"print-prep://task/{task['id']}/{artifact['id']}")
    assert json.loads(base64.b64decode(resource.contents[0].blob)) == {"verified": True}


@pytest.mark.anyio
async def test_studio_presentation_is_opt_in_and_original_download_survives(mcp_session):
    import asyncio
    import base64

    original = (
        b'<html data-viewer-contract="scene-viewer-a8-skin-v1"><head></head><body>'
        b'<script type="application/json" id="assembly-data">'
        b'{"resources":{"api/index.json":{"cases":[],"curationEnabled":false}},"assets":{}}'
        b"</script><script>oldViewer()</script></body></html>"
    )
    script = f"from pathlib import Path\nPath(workbench['output'],'index.html').write_bytes({original!r})"
    task = content_json(
        await mcp_session.call_tool("studio_task", {"action": "start", "engine": "python", "script": script})
    )["task"]
    for _ in range(100):
        task = content_json(await mcp_session.call_tool("studio_tasks", {"id": task["id"]}))["task"]
        if task["status"] not in ("queued", "running"):
            break
        await asyncio.sleep(0.05)
    assert task["status"] == "completed"
    artifact = next(a for a in task["artifacts"] if a["name"] == "index.html")
    uri = f"print-prep://task/{task['id']}/{artifact['id']}"
    presented = await mcp_session.read_resource(uri + "?presentation=studio")
    assert b"oldViewer()" not in base64.b64decode(presented.contents[0].blob)
    downloaded = await mcp_session.read_resource(uri)
    assert base64.b64decode(downloaded.contents[0].blob) == original


@pytest.mark.anyio
async def test_observe_returns_image_content_and_compact_metrics(mcp_session):
    import asyncio

    png = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a5foAAAAASUVORK5CYII="
    report = {
        "variants": [{"label": "A", "metrics": {"faces": 12, "parts": [{"name": "body"}]}}],
        "phases": [0],
        "images": [],
        "inputs": [],
    }
    script = f"from pathlib import Path\nimport base64\np=Path(workbench['output'])\n(p/'contact-sheet.png').write_bytes(base64.b64decode({png!r}))\n(p/'observation.json').write_text({json.dumps(report)!r})"
    task = content_json(
        await mcp_session.call_tool("studio_task", {"action": "start", "engine": "python", "script": script})
    )["task"]
    for _ in range(100):
        r = await mcp_session.call_tool("studio_observe", {"action": "read", "id": task["id"]})
        if content_json(r).get("ready"):
            break
        await asyncio.sleep(0.05)
    assert not r.is_error
    assert any(c.type == "image" and c.mime_type == "image/png" and c.data == png for c in r.content)
    assert "parts" not in content_json(r)["report"]["variants"][0]["metrics"]
    rejected = await mcp_session.call_tool(
        "studio_observe", {"action": "read", "id": task["id"], "image_file": "../secrets.png"}
    )
    assert rejected.is_error


@pytest.mark.anyio
async def test_studio_open_starts_service_and_returns_url(mcp_session, mcp_home):
    result = await mcp_session.call_tool("studio_open", {"presentation": "browser"})
    assert result.is_error is False
    payload = content_json(result)
    assert payload["already_running"] is False
    assert payload["url"].startswith("http://127.0.0.1:")
    assert payload["job"]

    session_info = studio.current_session(mcp_home / "workspaces" / "test-workspace")
    assert session_info is not None
    assert payload["url"] == session_info["url"] + "?workspace=test-workspace"

    # 再叫一次：服务已经在跑，不应该重新拉起（already_running 变 True）。
    result2 = await mcp_session.call_tool("studio_open", {"presentation": "browser"})
    payload2 = content_json(result2)
    assert payload2["already_running"] is True
    assert payload2["url"] == payload["url"]


@pytest.mark.anyio
async def test_embedded_app_entrypoints_and_self_contained_resource(mcp_session):
    from studio.shell.app_resources import load_ui, UI_MIME

    UI_URI = load_ui().uri
    tools = (await mcp_session.list_tools()).tools
    descriptor = next(t for t in tools if t.name == "studio_open")
    assert descriptor.meta["ui"]["resourceUri"] == UI_URI
    assert descriptor.meta["openai/ui"]["entrypoints"] == [{"type": "global"}, {"type": "thread"}]
    assert descriptor.meta["openai/ui"]["preferredModelDisplayMode"] == "fullscreen"
    assert all("resourceUri" not in t.meta.get("ui", {}) for t in tools if t.name != "studio_open")
    resources = await mcp_session.list_resources()
    assert resources.resources[0].uri == UI_URI
    resource = (await mcp_session.read_resource(UI_URI)).contents[0]
    assert resource.mime_type == UI_MIME
    assert "<canvas" not in resource.text  # renderer creates the canvas, not a screenshot
    assert "3D 工作台" in resource.text and "ui/initialize" in resource.text
    from html.parser import HTMLParser

    class ExternalResourceParser(HTMLParser):
        def handle_starttag(self, tag, attrs):
            if tag in {"script", "link", "iframe"}:
                assert not dict(attrs).get("src") and not dict(attrs).get("href")

    ExternalResourceParser().feed(resource.text)
    assert resource.meta["ui"]["csp"]["connectDomains"] == []
    assert resource.meta["openai/widgetHeightHint"] <= 160
    assert 'id="launch-card"' in resource.text


@pytest.mark.anyio
async def test_open_defaults_to_app_without_exposing_localhost(mcp_session):
    from studio.shell.app_resources import load_ui

    UI_URI = load_ui().uri
    result = await mcp_session.call_tool("studio_open", {})
    assert result.is_error is False
    assert content_json(result)["presentation"] == "app"
    assert "url" not in content_json(result)
    assert result.meta["ui"]["resourceUri"] == UI_URI + "?workspace=test-workspace"
    assert result.structured_content["parts"] == []
    assert result.structured_content["print_submitted"] is False
    session_id = result.meta["openai/widgetSessionId"]
    from studio.shell.app_resources import widget_session_id

    assert session_id == widget_session_id(result.structured_content["job"] + "/test-workspace")
    assert session_id and "/" not in session_id
    reopened = await mcp_session.call_tool("studio_open", {})
    assert reopened.meta["openai/widgetSessionId"] == session_id


def test_ui_cache_key_follows_bundle_content():
    from studio.shell import app_resources

    html = app_resources.UI_PATH.read_text()
    assert app_resources.load_ui().uri == app_resources.ui_resource_uri(html)
    assert app_resources.ui_resource_uri(html) == app_resources.ui_resource_uri(html)
    assert app_resources.ui_resource_uri(html + "<!-- updated -->") != app_resources.load_ui().uri


def test_workspace_identity_changes_on_ui_upgrade_only(monkeypatch):
    from studio.shell import app_resources

    original = app_resources.widget_session_id("/work/job")
    assert original == app_resources.widget_session_id("/work/job")
    assert original != app_resources.widget_session_id("/work/other-job")
    monkeypatch.setattr(
        app_resources, "load_ui", lambda: app_resources.UiBundle("", "ui://print-prep/studio-next.html")
    )
    assert original != app_resources.widget_session_id("/work/job")


@pytest.mark.anyio
async def test_legacy_ui_descriptor_still_resolves(mcp_session):
    from studio.shell import app_resources

    resource = (await mcp_session.read_resource("ui://print-prep/studio-v6.html")).contents[0]
    # Served bundles carry the process language in <meta name="studio-language">.
    assert resource.text == app_resources.stamp_language(app_resources.UI_PATH.read_bytes()).decode()


@pytest.mark.anyio
async def test_app_reads_real_preview_via_resource_without_mutating_mesh(mcp_session, tmp_path):
    import hashlib
    from urllib.parse import quote, urlsplit
    import trimesh

    source = tmp_path / "sphere.stl"
    mesh = trimesh.creation.icosphere(subdivisions=6, radius=20)
    mesh.export(source)
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    loaded = await mcp_session.call_tool("studio_load", {"files": [str(source)]})
    assert loaded.is_error is False
    state = content_json(await mcp_session.call_tool("studio_get_state", {}))
    part = state["parts"][0]
    uri = f"print-prep://preview/{quote(part['name'], safe='')}?{urlsplit(part['stl_url']).query}"
    preview = json.loads((await mcp_session.read_resource(uri)).contents[0].text)
    assert preview["original_faces"] == len(mesh.faces)
    assert 0 < preview["preview_faces"] <= 30_000
    assert preview["preview_only"] is True
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before
    # Neither preview reads nor simplification changes the authoritative job.
    state2 = content_json(await mcp_session.call_tool("studio_get_state", {}))
    assert state2["parts"] == state["parts"]
    assert state2["rev"] == state["rev"]


@pytest.mark.anyio
async def test_app_resource_rejects_arbitrary_files_and_stale_mesh(mcp_session):
    for uri in ("file:///etc/passwd", "print-prep://preview/../../etc/passwd?v=1", "print-prep://preview/missing?v=1"):
        with pytest.raises(Exception):
            await mcp_session.read_resource(uri)


@pytest.mark.anyio
async def test_get_state_matches_http_endpoint_directly(mcp_session, mcp_home):
    result = await mcp_session.call_tool("studio_get_state", {})
    assert result.is_error is False
    via_mcp = content_json(result)
    assert via_mcp["ok"] is True

    session_info = studio.current_session(mcp_home / "workspaces" / "test-workspace")
    assert session_info is not None
    import urllib.request

    req = urllib.request.Request(session_info["url"] + "/api/state", headers={"X-Studio-Token": session_info["token"]})
    with urllib.request.urlopen(req) as resp:
        via_http = json.loads(resp.read())

    # busy/rev 之外的字段应该完全一致；两次调用间隔很短，rev 不一定相同。
    for key in ("ok", "print_submitted", "job", "printer", "options", "steps", "warnings", "parts"):
        assert via_mcp[key] == via_http[key], key


@pytest.mark.anyio
async def test_list_printers_readonly_tool(mcp_session):
    result = await mcp_session.call_tool("studio_list_printers", {"filter": "P1S"})
    assert result.is_error is False
    payload = content_json(result)
    assert payload["ok"] is True
    assert any(p["name"] == "Bambu Lab P1S 0.4 nozzle" for p in payload["printers"])


@pytest.mark.anyio
async def test_unknown_tool_arguments_surface_as_error_not_crash(mcp_session):
    # orient 在还没 load 的时候调用 -> 底层 UserError -> HTTP 400 -> ok:false ->
    # 工具层应该把它标成 isError，而不是让协议本身报错或崩溃。
    result = await mcp_session.call_tool("studio_orient", {"shape": "generic"})
    assert result.is_error is True
    payload = content_json(result)
    assert payload["ok"] is False


@pytest.mark.anyio
async def test_ui_and_ai_share_history_selection_and_undo(mcp_session, tmp_path):
    from .conftest import write_box_stl

    source = write_box_stl(tmp_path, "shared-box", (30, 20, 5))
    opened = await mcp_session.call_tool("studio_open", {})
    nonce = opened.meta["studio/uiNonce"]

    async def ui(name, arguments):
        result = await mcp_session.call_tool(
            "studio_ui_action", {"name": name, "arguments": arguments, "ui_nonce": nonce}
        )
        assert not result.is_error, content_json(result)
        return content_json(result)

    await ui("studio_load", {"files": [str(source)]})
    state = content_json(await mcp_session.call_tool("studio_get_state", {}))
    name = state["parts"][0]["name"]
    assert state["history"][0]["actor"] == "human"
    await ui("studio_select", {"parts": [name]})
    state = content_json(await mcp_session.call_tool("studio_get_state", {}))
    assert state["selection"]["parts"] == [name] and state["selection"]["by"] == "human"
    assert not (await mcp_session.call_tool("studio_orient", {})).is_error
    await ui("studio_arrange", {"gap": 5})
    state = content_json(await mcp_session.call_tool("studio_get_state", {}))
    assert state["step_actors"]["orient"] == "ai"
    assert state["step_actors"]["arrange"] == "human"
    await ui("studio_undo", {"id": state["history"][0]["id"]})
    state = content_json(await mcp_session.call_tool("studio_get_state", {}))
    assert state["steps"]["orient"] and not state["steps"]["arrange"]
    assert state["history"][0]["actor"] == "human"
    assert state["step_actors"]["orient"] == "ai"
    assert not (await mcp_session.call_tool("studio_select", {"parts": []})).is_error
    state = content_json(await mcp_session.call_tool("studio_get_state", {}))
    assert state["selection"]["parts"] == [] and state["selection"]["by"] == "ai"
    shapes = json.loads((await mcp_session.read_resource("print-prep://catalog/shapes")).contents[0].text)
    assert shapes["ok"] and shapes["shapes"]
    await ui("studio_arrange", {})
    await ui("studio_export", {"no_project": True})
    # Geometry-only exports cannot be delivered as Bambu projects, even in dry-run.
    sent = await mcp_session.call_tool(
        "studio_ui_action",
        {
            "name": "studio_send_to_bambu",
            "arguments": {"dry_run": True},
            "ui_nonce": nonce,
        },
    )
    assert sent.is_error
    assert content_json(sent)["error"]["code"] == "missing_project_3mf"
    state = content_json(await mcp_session.call_tool("studio_get_state", {}))
    assert state["history"][0]["actor"] == "human"
    assert next(i for i in state["readiness"]["items"] if i["key"] == "deliver")["status"] == "todo"


@pytest.mark.anyio
async def test_ui_bridge_only_accepts_registered_write_tools(mcp_session):
    for name in ("studio_get_state", "studio_open", "/api/load", "studio_ui_action"):
        result = await mcp_session.call_tool("studio_ui_action", {"name": name, "arguments": {}})
        assert result.is_error


@pytest.mark.anyio
async def test_studio_open_never_exposes_the_ui_nonce_to_the_model(mcp_session):
    """The nonce that authenticates UI-originated calls must only reach `_meta`
    (host-only channel); `content`/`structuredContent` are read by the model."""
    result = await mcp_session.call_tool("studio_open", {})
    nonce = result.meta["studio/uiNonce"]
    assert nonce
    assert nonce not in json.dumps(result.structured_content, ensure_ascii=False)
    assert all(nonce not in block.text for block in result.content if hasattr(block, "text"))


@pytest.mark.anyio
async def test_ui_action_without_nonce_is_recorded_as_ai(mcp_session):
    result = await mcp_session.call_tool(
        "studio_ui_action",
        {"name": "studio_edit", "arguments": {"action": "primitive", "expected_revision": 0}},
    )
    assert not result.is_error
    state = content_json(await mcp_session.call_tool("studio_get_state", {}))["workbench"]
    assert state["history"][-1]["actor"] == "ai"


@pytest.mark.anyio
async def test_ui_action_with_wrong_nonce_is_recorded_as_ai(mcp_session):
    opened = await mcp_session.call_tool("studio_open", {})
    assert opened.meta["studio/uiNonce"]
    result = await mcp_session.call_tool(
        "studio_ui_action",
        {
            "name": "studio_edit",
            "arguments": {
                "action": "primitive",
                "expected_revision": opened.structured_content["workbench"]["revision"],
            },
            "ui_nonce": "not-the-real-nonce",
        },
    )
    assert not result.is_error
    state = content_json(await mcp_session.call_tool("studio_get_state", {}))["workbench"]
    assert state["history"][-1]["actor"] == "ai"


@pytest.mark.anyio
async def test_studio_part_chat_without_nonce_is_refused_by_human_only_gate(mcp_session):
    result = await mcp_session.call_tool("studio_part_chat", {"action": "status"})
    assert result.is_error
    assert content_json(result)["error"]["code"] == "human_required"


@pytest.mark.anyio
async def test_motion_mode_and_export_over_real_mcp(mcp_session):
    result = await mcp_session.call_tool("studio_open", {"mode": "motion"})
    assert result.structured_content["workspace_mode"] == "motion"
    revision = result.structured_content["workbench"]["revision"]
    created = content_json(
        await mcp_session.call_tool("studio_edit", {"action": "primitive", "expected_revision": revision})
    )
    motion = {
        "schema": "studio-motion/v1",
        "kind": "joint",
        "duration": 1,
        "fps": 24,
        "mode": "pkf",
        "joint": {"type": "revolute", "axis": "z", "origin": [0, 0, 0], "parent": None, "limits": [-180, 180]},
        "parameters": [],
        "steps": [{"id": "s", "t_start": 0, "t_end": 1, "value_start": "0", "value_end": "45", "easing": "linear"}],
        "keyframes": [],
    }
    result = await mcp_session.call_tool(
        "studio_motion", {"action": "set", "expected_revision": created["revision"], "params": {"motion": motion}}
    )
    assert not result.is_error, result.content
    exported = await mcp_session.call_tool(
        "studio_motion",
        {"action": "export", "expected_revision": content_json(result)["revision"], "params": {"format": "glb"}},
    )
    assert not exported.is_error, exported.content
    assert content_json(exported)["motion_report"]["frames"] == 25


def test_call_http_forwards_the_mcp_process_language(monkeypatch):
    """The per-workspace HTTP server keeps the STUDIO_LANG it was spawned with,
    so every proxied call carries this process's language as Accept-Language."""
    import io
    import urllib.request

    from studio.i18n import reset_language, set_language
    from studio.shell import mcp_server

    captured = {}

    class _Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def fake_urlopen(req, timeout=None):
        captured["headers"] = {k.lower(): v for k, v in req.header_items()}
        return _Resp(b'{"ok": true}')

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    token = set_language("en")
    try:
        assert mcp_server._call_http("GET", "/api/state", "tok", "http://127.0.0.1:1") == {"ok": True}
    finally:
        reset_language(token)
    assert captured["headers"]["accept-language"] == "en"
    token = set_language("zh-CN")
    try:
        mcp_server._call_http("POST", "/api/edit", "tok", "http://127.0.0.1:1", json_body={})
    finally:
        reset_language(token)
    assert captured["headers"]["accept-language"] == "zh-CN"
