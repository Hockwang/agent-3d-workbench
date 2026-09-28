"""studio.shell.mcp_server —— stdio MCP 服务（官方 `mcp` SDK），工具 -> HTTP（SPEC.md §6/§8）。

用低层 `mcp.server.Server`（构造函数注入 `on_list_tools`/`on_call_tool`，v2 SDK
的写法）+ `mcp.server.stdio.stdio_server`：`tools/list` 直接把
`studio.shell.tools_schema` 里现成的 JSON Schema 报出去，不需要每个工具另写一份
Python 签名再让 SDK 反推 schema。`tools/call` 每次都先确保本机 HTTP 服务在跑
（没跑就用 `studio.start_server()` 拉起），再用 `urllib` 转发到对应接口，把
返回的 JSON 原文包成一条 `TextContent` 带回去；`ok:false` 时把 `isError`
置真。

⚠️ stdout 只能有 MCP 协议字节：本文件里任何给人看的诊断信息都必须写 stderr。
`stdio_server()` 本身在服务期间也会把 fd 1 转向别处兜底（对拿着旧引用的
`sys.stdout` 之外的写入生效），但不能把这一点当成允许自己写 stdout 的理由——
我们自己的代码一律只用 `_log()`（内部固定写 stderr）。
"""

from __future__ import annotations

import asyncio
import copy
import json
import secrets
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Optional

_PLUGIN_ROOT = Path(__file__).resolve().parents[2]
if str(_PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(_PLUGIN_ROOT))

import mcp.types as types  # noqa: E402
from mcp.server import Server  # noqa: E402
from mcp.server.stdio import stdio_server  # noqa: E402

import studio  # noqa: E402
from studio.core import workspaces  # noqa: E402
from studio.i18n import get_language, render, set_language  # noqa: E402
from studio.shell import app_resources, part_chat, tools_schema  # noqa: E402

# 试切/导出可能耗时数分钟；SPEC.md §6 要求给足 30 分钟超时。
HTTP_TIMEOUT_S = 1800.0

_TOOLS_BY_NAME: dict[str, dict[str, Any]] = {t["name"]: t for t in tools_schema.get_tools()}

_OPEN_TOOL_DESCRIPTION = (
    "Open the 3D Workbench: static editing, Blender/CAD modelling, service tasks, motion preview "
    "and print preparation. Default mode='edit'; use mode='tasks' for modelling/animation/generation, "
    "mode='observe' for observing/comparing, mode='print' for printing. "
    "In hosts that render MCP Apps (Codex: the right-side workspace) the panel opens inline; keep the "
    "chat reply to a short pointer, no need to open a browser or a localhost address. "
    "Codex native entrypoints bind automatically via request _meta.threadId. "
    "workspace_id is the host's conversation/task ID (Codex: CODEX_THREAD_ID); a new Codex task "
    "auto-attaches to the current project folder, sharing the model in that folder while keeping "
    "selection and undo independent. Hosts without such an ID (Claude Code, plain MCP clients) set "
    "PRINT_PREP_WORKSPACE_ID in the server environment and omit workspace_id. Old session-owned "
    "projects are preserved and can be explicitly copied into a folder with studio_workspaces "
    "open_project. Pass presentation='browser' to get a web URL when the host does not render MCP "
    "Apps or the user asks for the web page. "
    "This tool never sends anything to a printer."
)


def _app_meta(uri: str | None = None) -> dict:
    uri = uri or app_resources.load_ui().uri
    return {
        "ui": {"resourceUri": uri},
        "openai/outputTemplate": uri,
        "openai/widgetAccessible": True,
        # Codex desktop extension, verified against the installed host's schema.
        "openai/ui": {
            "entrypoints": [{"type": "global"}, {"type": "thread"}],
            "preferredModelDisplayMode": "fullscreen",
        },
    }


def _workspace_arguments(arguments: dict | None, meta: types.RequestParamsMeta | None) -> dict:
    """Normalize per-request host identity without a shared-session default.

    Codex native entrypoints send empty arguments and put the current thread
    in MCP _meta.threadId. Preserve explicit workspace arguments; otherwise
    use that identity before the configured fallback for other MCP hosts.
    """
    scoped = dict(arguments or {})
    thread_id = (meta or {}).get("threadId")
    if not scoped.get("workspace_id") and thread_id is not None:
        scoped["workspace_id"] = workspaces.validate_id(thread_id)
    return scoped


def _log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


# Per-workspace nonce that authenticates workbench-UI-originated tool calls
# (studio_ui_action / studio_part_chat) as actor="human". Minted lazily the first
# time studio_open runs for a workspace, stable for this process's lifetime, and
# handed to the UI only through studio_open's CallToolResult._meta (never content
# or structuredContent, both of which reach the host model). A model that reads
# the tool result therefore never sees the nonce and cannot forge a human call;
# it can still omit ui_nonce, which is honestly recorded as actor="ai" below,
# never denied.
_UI_NONCES: dict[str, str] = {}


def _ui_nonce(workspace_id: str) -> str:
    nonce = _UI_NONCES.get(workspace_id)
    if nonce is None:
        nonce = secrets.token_urlsafe(24)
        _UI_NONCES[workspace_id] = nonce
    return nonce


def _actor_for_nonce(workspace_id: str, nonce: Any) -> str:
    expected = _UI_NONCES.get(workspace_id)
    if isinstance(nonce, str) and expected is not None and secrets.compare_digest(nonce, expected):
        return "human"
    return "ai"


def _ensure_running(workspace_id: str) -> tuple[dict[str, Any], bool]:
    from studio.core.projects import auto_attach
    from studio.shell.codex_projects import resolve_cwd

    auto_attach(workspace_id, resolve_cwd=resolve_cwd)
    return workspaces.ensure_running(workspace_id)


def _snapshot(workspace_id: str) -> dict:
    if workspace_id == "legacy":
        path = studio.default_job_dir() / "workbench" / "project.json"
        if not path.exists():
            raise ValueError(render("mcp_server.no_branchable_legacy_project"))
        # The legacy writer atomically replaces this document; geometry assets
        # are immutable by content hash. No old server restart is necessary.
        return json.loads(path.read_text())
    info, _ = _ensure_running(workspace_id)
    result = _call_http("GET", "/api/workspace-snapshot", info["token"], info["url"])
    if not result.get("ok"):
        raise ValueError(result.get("error", {}).get("message", "Cannot read workspace"))
    return result["document"]


def _workspace_action(arguments: dict) -> dict:
    action = arguments.get("action", "list")
    if action == "list":
        return {"ok": True, "workspaces": workspaces.list_workspaces()}
    workspace_id = workspaces.resolve_id(arguments)
    if action in ("open_project", "project"):
        from studio.core import projects
        from studio.shell.codex_projects import resolve_cwd

        if action == "project":
            return {"ok": True, **projects.info(workspace_id)}
        source_id = arguments.get("source_id")
        snapshot = _snapshot(source_id) if source_id else None
        if snapshot is not None and snapshot["revision"] != arguments.get("expected_revision"):
            raise ValueError(render("mcp_server.source_project_changed"))
        directory = arguments.get("worktree") or str(projects.thread_folder(workspace_id, resolve_cwd))
        return projects.open_project(workspace_id, directory, source_id=source_id, snapshot=snapshot)
    if action in ("invite", "join", "renew", "release"):
        source_id = arguments.get("source_id", workspace_id) if action == "join" else workspace_id
        info, _ = _ensure_running(source_id)

        def request():
            return _call_http(
                "POST", "/api/collaboration", info["token"], info["url"], json_body=arguments, workspace_id=workspace_id
            )

        if action == "join":
            return workspaces.bind(workspace_id, source_id, request)
        return {**request(), "project_id": workspaces.project_id(workspace_id)}
    if action == "fork":
        source_id = arguments["source_id"]
        snapshot = _snapshot(source_id)
        if snapshot["revision"] != arguments.get("expected_revision"):
            raise ValueError(render("mcp_server.source_revision_changed"))
        return workspaces.fork(workspace_id, source_id, snapshot)
    if action == "merge":
        branch_file = workspaces.job_dir(workspace_id) / "workbench" / "branch.json"
        if not branch_file.exists():
            raise ValueError(render("mcp_server.not_a_model_branch"))
        branch = json.loads(branch_file.read_text())
        if branch["source_id"] == "legacy":
            raise ValueError(render("mcp_server.legacy_shared_project_source_only"))
        snapshot = _snapshot(workspace_id)
        info, _ = _ensure_running(branch["source_id"])
        source_session = branch["source_id"]
        # A folder has its own persistent runtime ID, distinct from chat IDs.
        # Explicit merge is recorded in its owner's history just as an old
        # session-owned branch merge; part-chat source scopes remain intact.
        if (workspaces.home(source_session) / "project-location.json").exists():
            source_session = _snapshot(branch["source_id"])["collaboration"]["owner"]
        result = _call_http(
            "POST",
            "/api/branch-merge",
            info["token"],
            info["url"],
            json_body={
                "expected_revision": arguments.get("expected_revision"),
                "branch_id": workspace_id,
                "base_objects": branch["base_objects"],
                "objects": snapshot["objects"],
                "asset_root": str(workspaces.job_dir(workspace_id) / "workbench" / "assets"),
            },
            workspace_id=source_session,
        )
        return {
            **result,
            "workspace_id": workspace_id,
            "target_id": branch["source_id"],
            "branch_revision": snapshot["revision"],
        }
    raise ValueError("Unknown workspace action")


def _call_http(
    method: str,
    path: str,
    token: str,
    base_url: str,
    query: Optional[dict[str, Any]] = None,
    json_body: Optional[dict[str, Any]] = None,
    actor: str = "ai",
    workspace_id: Optional[str] = None,
) -> dict[str, Any]:
    url = base_url.rstrip("/") + path
    if method.upper() == "GET" and query:
        flat = {k: (json.dumps(v) if isinstance(v, (dict, list)) else v) for k, v in query.items() if v is not None}
        qs = urllib.parse.urlencode(flat)
        if qs:
            url = f"{url}?{qs}"
    data = None
    # Forward this process's language (STUDIO_LANG) on every proxied call: the
    # per-workspace HTTP server is a long-lived subprocess that keeps whatever
    # STUDIO_LANG it was spawned with, so without this header a server started
    # by another host (or an older run) would answer in the wrong language.
    headers: dict[str, str] = {"X-Studio-Token": token, "X-Studio-Actor": actor, "Accept-Language": get_language()}
    if workspace_id:
        headers["X-Studio-Workspace"] = workspace_id
    if method.upper() != "GET":
        headers["Content-Type"] = "application/json"
        data = json.dumps(json_body or {}).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method=method.upper())
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {"ok": True}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {"ok": False, "error": {"code": f"http_{exc.code}", "message": raw or exc.reason, "params": {}}}
    except urllib.error.URLError as exc:
        return {"ok": False, "error": {"code": "network_error", "message": str(exc.reason), "params": {}}}


def _tool_list() -> list[types.Tool]:
    out = [
        types.Tool(
            name=t["name"],
            description=t["description"],
            inputSchema=t["inputSchema"],
            annotations=types.ToolAnnotations(readOnlyHint=t.get("readOnly", False)),
            _meta={"openai/widgetAccessible": True},
        )
        for t in tools_schema.get_tools()
    ]
    out.append(
        types.Tool(
            name="studio_part_chat",
            title=render("mcp_server.tool_title_part_chat"),
            description=(
                "Recorded as actor 'human' only when called by the workbench UI itself (ui_nonce from "
                "studio_open's result metadata); otherwise recorded as 'ai' and rejected by the "
                "human-only gate. Creates and views part chat branches; it does not send chat messages "
                "or start a model turn."
            ),
            inputSchema=copy.deepcopy(part_chat.SCHEMA),
            annotations=types.ToolAnnotations(readOnlyHint=False),
            _meta={"ui": {"visibility": ["app"]}, "openai/widgetAccessible": True},
        )
    )
    out.append(
        types.Tool(
            name="studio_open",
            title=render("mcp_server.tool_title_open"),
            description=_OPEN_TOOL_DESCRIPTION,
            inputSchema={
                "type": "object",
                "properties": {
                    "presentation": {"type": "string", "enum": ["app", "browser"], "default": "app"},
                    "mode": {
                        "type": "string",
                        "enum": ["edit", "motion", "print", "tasks", "observe"],
                        "default": "edit",
                    },
                    "task_id": {"type": "string", "description": "Open the model artifact of the given task"},
                },
                "additionalProperties": False,
            },
            annotations=types.ToolAnnotations(readOnlyHint=True),
            _meta=_app_meta(),
        )
    )
    out.append(
        types.Tool(
            name="studio_ui_action",
            title=render("mcp_server.tool_title_ui_action"),
            description=(
                "For workspace UI buttons to call; recorded as actor 'human' only when called by the "
                "workbench UI itself (ui_nonce from studio_open's result metadata), otherwise recorded "
                "as 'ai'. The AI should call the corresponding studio tool directly instead."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "enum": [t["name"] for t in tools_schema.get_tools() if t["method"] == "POST"],
                    },
                    "arguments": {"type": "object"},
                    "ui_nonce": {"type": "string"},
                },
                "required": ["name", "arguments"],
                "additionalProperties": False,
            },
            annotations=types.ToolAnnotations(readOnlyHint=False),
            _meta={"ui": {"visibility": ["app"]}, "openai/widgetAccessible": True},
        )
    )
    out.append(
        types.Tool(
            name="studio_workspaces",
            title=render("mcp_server.tool_title_workspaces"),
            description=(
                "project reports project ownership. open_project opens a shared project by an absolute "
                "worktree directory, or reads the current Codex task directory if omitted; passing "
                "source_id + expected_revision copies an existing model into an empty directory (the "
                "original project is preserved), and different Git worktrees stay independent. list "
                "lists projects; fork creates an independent model branch; merge checks for conflicts "
                "and merges. invite/join create a part-scoped chat collaboration; renew/release "
                "renew or release the write lease. Selection and undo are independent per task."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": [
                            "list",
                            "project",
                            "open_project",
                            "fork",
                            "merge",
                            "invite",
                            "join",
                            "renew",
                            "release",
                        ],
                    },
                    "source_id": {"type": "string"},
                    "expected_revision": {"type": "integer"},
                    "object_id": {"type": "string"},
                    "worktree": {"type": "string"},
                    "invitation": {"type": "string"},
                    "ids": {"type": "array", "items": {"type": "string"}},
                },
                "additionalProperties": False,
            },
            annotations=types.ToolAnnotations(readOnlyHint=False),
            _meta={"openai/widgetAccessible": True},
        )
    )
    for tool in out:
        tool.input_schema["properties"]["workspace_id"] = {
            "type": "string",
            "pattern": workspaces.ID_PATTERN,
            "description": (
                "The host's conversation/task ID (Codex: CODEX_THREAD_ID); pass the same value for "
                "every operation and never another task's ID. Codex native UI calls can omit it: "
                "request _meta.threadId provides the current task identity. Hosts without such an ID omit it and "
                "set PRINT_PREP_WORKSPACE_ID in the server environment instead. Operations are "
                "rejected when neither is present."
            ),
        }
    return out


async def on_list_tools(ctx: Any, params: Any) -> types.ListToolsResult:
    return types.ListToolsResult(tools=_tool_list())


async def on_list_resources(ctx: Any, params: Any) -> types.ListResourcesResult:
    return types.ListResourcesResult(
        resources=[
            types.Resource(
                uri=app_resources.load_ui().uri,
                name="3D Workbench",
                mimeType=app_resources.UI_MIME,
                description="Embedded mesh editing and print preparation workspace",
            ),
            types.Resource(uri="print-prep://catalog/shapes", name="Print Prep shapes", mimeType="application/json"),
        ]
    )


async def on_read_resource(ctx: Any, params: types.ReadResourceRequestParams) -> types.ReadResourceResult:
    uri = str(params.uri)
    html = app_resources.ui_html(uri)
    if html is not None:
        return types.ReadResourceResult(
            contents=[
                types.TextResourceContents(
                    uri=uri,
                    mimeType=app_resources.UI_MIME,
                    text=html,
                    _meta={
                        "ui": {
                            "prefersBorder": False,
                            "csp": {
                                "connectDomains": [],
                                "resourceDomains": ["blob:", "data:"],
                                "frameDomains": ["about:"],
                            },
                        },
                        "openai/widgetDescription": "3D Workbench: edit, split, repair, export and prepare printing.",
                        "openai/widgetPrefersBorder": False,
                        "openai/widgetHeightHint": 148,
                    },
                )
            ]
        )
    workspace_id = workspaces.resolve_id(_workspace_arguments(
        {"workspace_id": urllib.parse.parse_qs(urllib.parse.urlsplit(uri).query).get("workspace", [None])[0]},
        params.meta,
    ))
    if uri.split("?")[0] == "print-prep://catalog/shapes":
        info, _ = await asyncio.to_thread(_ensure_running, workspace_id)
        result = await asyncio.to_thread(_call_http, "GET", "/api/shapes", info["token"], info["url"])
        if not result.get("ok"):
            raise ValueError(result.get("error", {}).get("message", "Cannot read shapes"))
        return types.ReadResourceResult(
            contents=[
                types.TextResourceContents(
                    uri=uri,
                    mimeType="application/json",
                    text=json.dumps(result, ensure_ascii=False),
                )
            ]
        )
    if uri.startswith("print-prep://preview/"):
        info, _ = await asyncio.to_thread(_ensure_running, workspace_id)
        text = await asyncio.to_thread(app_resources.preview_json, uri, info["job"])
        return types.ReadResourceResult(
            contents=[
                types.TextResourceContents(
                    uri=uri,
                    mimeType="application/json",
                    text=text,
                )
            ]
        )
    if uri.startswith("print-prep://city/"):
        import base64
        from studio.core.editor import Workspace
        from studio.core.city import resource

        info, _ = await asyncio.to_thread(_ensure_running, workspace_id)
        workspace = Workspace(Path(info["job"]) / "workbench")
        digest, name = urllib.parse.urlsplit(uri).path.lstrip("/").split("/", 1)
        raw = await asyncio.to_thread(resource, workspace, digest, urllib.parse.unquote(name))
        return types.ReadResourceResult(
            contents=[
                types.BlobResourceContents(
                    uri=uri, mimeType="application/octet-stream", blob=base64.b64encode(raw).decode("ascii")
                )
            ]
        )
    if uri.startswith("print-prep://editor/"):
        import base64
        from studio.core.editor import Workspace

        info, _ = await asyncio.to_thread(_ensure_running, workspace_id)
        workspace = Workspace(Path(info["job"]) / "workbench")
        raw = await asyncio.to_thread(workspace.asset_bytes, urllib.parse.urlsplit(uri).path.lstrip("/"))
        return types.ReadResourceResult(
            contents=[
                types.BlobResourceContents(
                    uri=uri,
                    mimeType="model/gltf-binary",
                    blob=base64.b64encode(raw).decode("ascii"),
                )
            ]
        )
    if uri.startswith("print-prep://task/"):
        import base64
        from studio.core.tasks import Tasks

        info, _ = await asyncio.to_thread(_ensure_running, workspace_id)
        parsed = urllib.parse.urlsplit(uri)
        task_id, artifact_id = parsed.path.lstrip("/").split("/")
        path, item = await asyncio.to_thread(Tasks(Path(info["job"]) / "tasks").artifact, task_id, artifact_id)
        if path.stat().st_size > 200 * 1024 * 1024:
            raise ValueError(render("mcp_server.preview_artifact_too_large"))
        raw = await asyncio.to_thread(path.read_bytes)
        if urllib.parse.parse_qs(parsed.query).get("presentation") == ["studio"] and item["mime"] == "text/html":
            from studio.core.viewer_presentation import studio_presentation

            raw = await asyncio.to_thread(studio_presentation, raw)
        return types.ReadResourceResult(
            contents=[
                types.BlobResourceContents(uri=uri, mimeType=item["mime"], blob=base64.b64encode(raw).decode("ascii"))
            ]
        )
    raise ValueError("Unknown Print Prep resource")


async def on_call_tool(ctx: Any, params: types.CallToolRequestParams) -> types.CallToolResult:
    name = params.name
    # Language is fixed process-wide at startup (main(), below) for now; a per-call
    # override (e.g. reading a `language` tool argument here and calling
    # `studio.i18n.set_language(...)`) would go right here once a client actually needs it.
    try:
        arguments = _workspace_arguments(params.arguments, params.meta)
        if name == "studio_workspaces":
            result = await asyncio.to_thread(_workspace_action, arguments)
            return types.CallToolResult(
                content=[types.TextContent(text=json.dumps(result, ensure_ascii=False))],
                structuredContent=result,
                isError=not result.get("ok", False),
            )
        workspace_id = workspaces.resolve_id(arguments)
        if name == "studio_part_chat":
            info, _ = await asyncio.to_thread(_ensure_running, workspace_id)
            actor = _actor_for_nonce(workspace_id, arguments.pop("ui_nonce", None))
            result = await asyncio.to_thread(
                _call_http,
                "POST",
                "/api/part-chat",
                info["token"],
                info["url"],
                json_body=arguments,
                actor=actor,
                workspace_id=workspace_id,
            )
            return types.CallToolResult(
                content=[types.TextContent(text=json.dumps(result, ensure_ascii=False))],
                structuredContent=result,
                isError=not result.get("ok", False),
            )
        if name == "studio_open":
            info, already_running = await asyncio.to_thread(_ensure_running, workspace_id)
            if arguments.get("presentation") == "browser":
                query = {"workspace": workspace_id}
                if arguments.get("mode"):
                    query["mode"] = arguments["mode"]
                if arguments.get("task_id"):
                    query.update(mode="tasks", task=arguments["task_id"])
                payload = {
                    "url": info["url"] + "?" + urllib.parse.urlencode(query),
                    "job": info["job"],
                    "already_running": already_running,
                    "workspace_id": workspace_id,
                }
                return types.CallToolResult(content=[types.TextContent(text=json.dumps(payload, ensure_ascii=False))])
            state = await asyncio.to_thread(
                _call_http, "GET", "/api/state", info["token"], info["url"], workspace_id=workspace_id
            )
            state["workspace_mode"] = arguments.get("mode", "edit")
            state["workspace_id"] = workspace_id
            if arguments.get("task_id"):
                state["focus_task_id"] = arguments["task_id"]
                state["workspace_mode"] = "tasks"
            payload = {
                "ok": state.get("ok", False),
                "presentation": "app",
                "parts": len(state.get("parts", [])),
                "already_running": already_running,
                "workspace_id": workspace_id,
            }
            # Preserve camera/selection on repeat opens, but never reuse an old
            # iframe after the UI bundle changes. The backend job stays the same.
            bundle = app_resources.load_ui()
            uri = app_resources.workspace_ui_uri(workspace_id, bundle)
            session_id = app_resources.widget_session_id(info["job"] + "/" + workspace_id, bundle)
            return types.CallToolResult(
                content=[types.TextContent(text=json.dumps(payload, ensure_ascii=False))],
                structuredContent=state,
                _meta={
                    **_app_meta(uri),
                    "openai/widgetSessionId": session_id,
                    "studio/uiNonce": _ui_nonce(workspace_id),
                },
                isError=not bool(state.get("ok")),
            )

        actor = "ai"
        if name == "studio_ui_action":
            target = arguments.get("name")
            tool = _TOOLS_BY_NAME.get(target) if isinstance(target, str) else None
            if not tool or tool["method"] != "POST" or not isinstance(arguments.get("arguments"), dict):
                raise ValueError("Invalid workspace action")
            actor = _actor_for_nonce(workspace_id, arguments.get("ui_nonce"))
            name, arguments = target, arguments["arguments"]
        tool = _TOOLS_BY_NAME.get(name)
        if tool is None:
            payload = {
                "ok": False,
                "error": {
                    "code": "unknown_tool",
                    "message": render("mcp_server.unknown_tool", name=name),
                    "params": {},
                },
            }
            return types.CallToolResult(
                content=[types.TextContent(text=json.dumps(payload, ensure_ascii=False))], isError=True
            )

        info, _already = await asyncio.to_thread(_ensure_running, workspace_id)
        method = tool["method"]
        path = tool["path"]
        if method == "GET":
            result = await asyncio.to_thread(
                _call_http, "GET", path, info["token"], info["url"], arguments, None, workspace_id=workspace_id
            )
        else:
            result = await asyncio.to_thread(
                _call_http, "POST", path, info["token"], info["url"], None, arguments, actor, workspace_id=workspace_id
            )
        result["workspace_id"] = workspace_id
        is_error = not bool(result.get("ok", True))
        if name == "studio_observe" and not is_error and result.get("ready"):
            import base64
            from studio.core.tasks import Tasks

            report = result["report"]
            images = []
            if arguments.get("action") == "read" and arguments.get("image", True):
                filename = arguments.get("image_file", "contact-sheet.png")
                allowed = {item["file"] for item in report["images"]} | {"contact-sheet.png"}
                if filename not in allowed:
                    raise ValueError(render("mcp_server.image_not_in_observation_list"))
                item = next(a for a in result["task"]["artifacts"] if a["name"] == filename)
                path, _ = await asyncio.to_thread(
                    Tasks(Path(info["job"]) / "tasks").artifact, result["task"]["id"], item["id"]
                )
                if path.stat().st_size > 12 * 1024 * 1024:
                    raise ValueError(render("mcp_server.observation_image_too_large"))
                images.append(
                    types.ImageContent(data=base64.b64encode(path.read_bytes()).decode("ascii"), mimeType="image/png")
                )
            if not arguments.get("detail"):
                result = {
                    **result,
                    "task": {k: result["task"][k] for k in ("id", "title", "status", "elapsed_seconds")},
                    "report": {
                        **report,
                        "inputs": [{"sha256": x["sha256"], "bytes": x["bytes"]} for x in report["inputs"]],
                        "variants": [
                            {**v, "metrics": {k: value for k, value in v["metrics"].items() if k != "parts"}}
                            for v in report["variants"]
                        ],
                    },
                }
            return types.CallToolResult(
                content=[types.TextContent(text=json.dumps(result, ensure_ascii=False)), *images],
                structuredContent=result,
            )
        return types.CallToolResult(
            content=[types.TextContent(text=json.dumps(result, ensure_ascii=False))],
            structuredContent=result,
            isError=is_error,
        )
    except Exception as exc:  # noqa: BLE001 —— 任何异常都要变成 isError 结果，不能让协议层崩
        _log(f"studio_mcp tool {name!r} failed: {exc!r}")
        payload = {
            "ok": False,
            "error": {"code": "tool_exception", "message": str(exc), "params": getattr(exc, "params", {})},
        }
        return types.CallToolResult(
            content=[types.TextContent(text=json.dumps(payload, ensure_ascii=False))], isError=True
        )


server: Server = Server(
    "print-prep-studio",
    title="3D Workbench",
    version="0.8.6",
    on_list_tools=on_list_tools,
    on_call_tool=on_call_tool,
    on_list_resources=on_list_resources,
    on_read_resource=on_read_resource,
)


async def _run() -> None:
    async with stdio_server() as (read_stream, write_stream):
        # Declare the MCP Apps extension (SEP-1865, io.modelcontextprotocol/ui).
        # Codex keys on the openai/* tool metadata and ignores this. Hosts that follow
        # the extension spec (Claude desktop, claude.ai, MCPJam) look for it in
        # `capabilities.extensions`, but the Python SDK (2.2.0) serialises the
        # initialize result against the 2025-11-25 schema, which has no `extensions`
        # field, so the declaration is currently dropped on the wire. It is kept so it
        # takes effect once the SDK negotiates a protocol version that carries it;
        # until then non-Codex hosts use `studio_open(presentation="browser")`.
        options = server.create_initialization_options(extensions={"io.modelcontextprotocol/ui": {}})
        await server.run(read_stream, write_stream, options)


def main() -> int:
    set_language(None)  # normalizes os.environ["STUDIO_LANG"] once for the life of this process
    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
