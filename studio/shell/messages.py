"""Message catalog for `studio.shell.*` raises and UI-facing payload strings.

One entry per raise site / literal error body under `studio/shell/` that a
human (rather than the model) ends up reading — `server.*` for
`studio/shell/server.py`, `mcp_server.*` for `studio/shell/mcp_server.py`,
`codex_bridge.*` for `studio/shell/codex_bridge.py`. Codes are
`<module>.<meaning>`, lower snake_case, and become part of the public error
contract once released: never repurpose or delete one, only add. The
"zh-CN" text below is the original wording each site used to hardcode,
carried over verbatim; "en" is a faithful translation, not a paraphrase.

MCP tool `description`/parameter-description text is read by the model, not
by a human, so — per the project's English-primary decision for everything
the model reads — that content lives as plain English literals directly in
`studio/shell/tools_schema.py` and the `*_schema.py` files (and the four
tool definitions inlined in `mcp_server.py`), not in this catalog. Only the
`title` fields of those inlined tools (shown in the host's tool-call UI, not
read by the model) go through this catalog.

Imported (for its `register()` side effect) from `studio/shell/__init__.py`,
so every code here is registered as soon as anything under `studio.shell` is
imported.
"""

from studio.i18n import register

register(
    {
        # ------------------------------------------------------- server.py
        "server.busy": {
            "zh-CN": "上一步操作还在进行，请稍候再试",
            "en": "The previous operation is still in progress; please try again shortly",
        },
        "server.bad_json_syntax": {
            "zh-CN": "请求体不是合法 JSON: {exc}",
            "en": "Request body is not valid JSON: {exc}",
        },
        "server.bad_json_not_object": {
            "zh-CN": "请求体必须是 JSON 对象",
            "en": "Request body must be a JSON object",
        },
        "server.bad_host": {
            "zh-CN": "Host 校验失败",
            "en": "Host header validation failed",
        },
        "server.missing_token": {
            "zh-CN": "缺少或错误的令牌",
            "en": "Missing or invalid token",
        },
        "server.route_not_found": {
            "zh-CN": "未知接口: {path}",
            "en": "Unknown endpoint: {path}",
        },
        "server.bad_origin": {
            "zh-CN": "跨站请求被拒绝",
            "en": "Cross-site request rejected",
        },
        "server.select_bad_parts": {
            "zh-CN": "parts 必须是字符串数组",
            "en": "parts must be an array of strings",
        },
        "server.select_unknown_part": {
            "zh-CN": "未知零件: {unknown}",
            "en": "Unknown part(s): {unknown}",
        },
        "server.recipe_missing_id": {
            "zh-CN": "缺少 ?id= 参数",
            "en": "Missing the ?id= query parameter",
        },
        "server.unknown_recipe": {
            "zh-CN": "未知的配方: {recipe_id!r}",
            "en": "Unknown recipe: {recipe_id!r}",
        },
        "server.task_open_unsupported_type": {
            "zh-CN": "此类型请保存文件后自行打开",
            "en": "This file type must be saved and opened manually",
        },
        "server.task_from_selection_conflict": {
            "zh-CN": "from_selection 与 inputs 互斥",
            "en": "from_selection and inputs are mutually exclusive",
        },
        "server.task_select_first": {
            "zh-CN": "请先在模型编辑中选择对象",
            "en": "Please select an object in the model editor first",
        },
        "server.task_bad_action": {
            "zh-CN": "任务 action 为 start/rebuild/cancel/resume/import/upload/open",
            "en": "task action must be one of start/rebuild/cancel/resume/import/upload/open",
        },
        "server.recipe_id_type": {
            "zh-CN": "id 必须是字符串或 null",
            "en": "id must be a string or null",
        },
        "server.recipe_unavailable": {
            "zh-CN": "配方 {recipe_id!r} 还缺能力: {missing_tools}",
            "en": "Recipe {recipe_id!r} is still missing capabilities: {missing_tools}",
        },
        "server.recipe_record_not_updated_task": {
            "zh-CN": "任务已启动；配方记录未更新：{error}",
            "en": "The task has started; the recipe record was not updated: {error}",
        },
        "server.recipe_record_not_updated_observe": {
            "zh-CN": "观察操作已完成；配方记录未更新：{error}",
            "en": "The observation action completed; the recipe record was not updated: {error}",
        },
        "server.missing_studio_token": {
            "zh-CN": "缺少或错误的 X-Studio-Token",
            "en": "Missing or invalid X-Studio-Token",
        },
        "server.upload_missing_name": {
            "zh-CN": "缺少 ?name= 参数",
            "en": "Missing the ?name= query parameter",
        },
        "server.upload_bad_filename": {
            "zh-CN": "非法文件名",
            "en": "Invalid file name",
        },
        "server.upload_unsupported_extension": {
            "zh-CN": "不支持的文件类型: {ext!r}",
            "en": "Unsupported file type: {ext!r}",
        },
        "server.upload_missing_content_length": {
            "zh-CN": "缺少 Content-Length",
            "en": "Missing Content-Length",
        },
        "server.upload_bad_content_length": {
            "zh-CN": "非法 Content-Length",
            "en": "Invalid Content-Length",
        },
        "server.upload_too_large": {
            "zh-CN": "超过 {max_bytes} 字节上限",
            "en": "Exceeds the {max_bytes}-byte limit",
        },
        "server.part_not_found": {
            "zh-CN": "未知零件: {name!r}",
            "en": "Unknown part: {name!r}",
        },
        # -------------------------------------------------------- mcp_server.py
        "mcp_server.no_branchable_legacy_project": {
            "zh-CN": "没有可分支的旧工程",
            "en": "There is no legacy project to branch from",
        },
        "mcp_server.source_project_changed": {
            "zh-CN": "来源工程已改变，请读取最新 revision",
            "en": "The source project has changed; please read the latest revision",
        },
        "mcp_server.source_revision_changed": {
            "zh-CN": "来源工程 revision 已改变，请读取最新状态后创建分支",
            "en": "The source project's revision has changed; read the latest state before creating a branch",
        },
        "mcp_server.not_a_model_branch": {
            "zh-CN": "当前工程不是模型分支",
            "en": "The current project is not a model branch",
        },
        "mcp_server.legacy_shared_project_source_only": {
            "zh-CN": "旧共享工程只作为来源保留；请将模型导出或在独立工作台继续编辑",
            "en": (
                "The legacy shared project is kept only as a source; export the model or keep "
                "editing it in a standalone workspace"
            ),
        },
        "mcp_server.preview_artifact_too_large": {
            "zh-CN": "预览产物超过 200 MB，请从本机文件路径打开",
            "en": "The preview artifact exceeds 200 MB; open it from its local file path instead",
        },
        "mcp_server.unknown_tool": {
            "zh-CN": "未知工具: {name!r}",
            "en": "Unknown tool: {name!r}",
        },
        "mcp_server.image_not_in_observation_list": {
            "zh-CN": "image_file 不在观察图清单中",
            "en": "image_file is not in the observation image list",
        },
        "mcp_server.observation_image_too_large": {
            "zh-CN": "观察图超过 12 MB",
            "en": "The observation image exceeds 12 MB",
        },
        "mcp_server.tool_title_part_chat": {
            "zh-CN": "零件聊天分支",
            "en": "Part chat branch",
        },
        "mcp_server.tool_title_open": {
            "zh-CN": "3D 工作台",
            "en": "3D Workbench",
        },
        "mcp_server.tool_title_ui_action": {
            "zh-CN": "3D 工作台界面操作",
            "en": "3D Workbench UI action",
        },
        "mcp_server.tool_title_workspaces": {
            "zh-CN": "工作台与模型分支",
            "en": "Workspaces and model branches",
        },
        # -------------------------------------------------------- codex_bridge.py
        "codex_bridge.cli_not_found": {
            "zh-CN": "未找到 Codex CLI，请安装后再开启零件聊天分支",
            "en": "Codex CLI was not found; install it before starting a part chat branch",
        },
        "codex_bridge.cli_too_old": {
            "zh-CN": "需要 Codex CLI 0.154.0 或更新版本",
            "en": "Codex CLI 0.154.0 or newer is required",
        },
        "codex_bridge.unsupported_operation": {
            "zh-CN": "此接入不支持该 Codex 操作",
            "en": "This bridge does not support that Codex operation",
        },
        "codex_bridge.timeout_do_not_retry": {
            "zh-CN": "Codex 接入超时；请检查创建状态，不要重复创建",
            "en": "Codex bridge timed out; check the creation status instead of retrying",
        },
        "codex_bridge.disconnected": {
            "zh-CN": "Codex 接入已断开；请检查创建状态",
            "en": "Codex bridge disconnected; check the creation status",
        },
        "codex_bridge.request_failed_fallback": {
            "zh-CN": "Codex 请求失败",
            "en": "Codex request failed",
        },
        "codex_bridge.timeout": {
            "zh-CN": "Codex 接入超时；请检查创建状态",
            "en": "Codex bridge timed out; check the creation status",
        },
        # -------------------------------------------------------- part_chat.py
        "part_chat.bad_action": {
            "zh-CN": "无效的聊天分支操作",
            "en": "Invalid part chat branch operation",
        },
        "part_chat.bad_operation_id": {
            "zh-CN": "需要有效的操作 ID",
            "en": "A valid operation ID is required",
        },
        "part_chat.binding_failed_fallback": {
            "zh-CN": "工程绑定失败",
            "en": "Project binding failed",
        },
        "part_chat.bound_ready_message": {
            "zh-CN": "分支已创建并绑定零件，等待你的修缮要求。",
            "en": "The branch has been created and bound to the part; awaiting your repair request.",
        },
        "part_chat.branch_thread_title": {
            "zh-CN": "修缮 · {name}",
            "en": "Repair · {name}",
        },
        "part_chat.bridge_identity_mismatch": {
            "zh-CN": "Codex 返回了不同的任务身份",
            "en": "Codex returned a different task identity",
        },
        "part_chat.duplicate_create_uncertain": {
            "zh-CN": "上次创建结果尚未确认，已阻止重复创建；请先在 Codex 任务列表核对。",
            "en": (
                "The previous creation result has not been confirmed yet; a duplicate creation "
                "was blocked — please check the Codex task list first."
            ),
        },
        "part_chat.fork_source_mismatch": {
            "zh-CN": "Codex 分支来源不一致，未绑定工程",
            "en": "Codex branch source does not match; the project was not bound",
        },
        "part_chat.human_required": {
            "zh-CN": "请在工作台中开启和使用直接创建分支",
            "en": "Please open and use direct branch creation from within the workbench",
        },
        "part_chat.multiple_forks_bound_stopped": {
            "zh-CN": "创建返回了多个分支，已停止绑定",
            "en": "Creation returned more than one branch; binding was stopped",
        },
        "part_chat.operation_conflict": {
            "zh-CN": "操作 ID 已用于另一个零件",
            "en": "This operation ID has already been used for a different part",
        },
        "part_chat.permission_required": {
            "zh-CN": "请先允许工作台在当前工程直接创建零件聊天分支",
            "en": "Please allow the workbench to create part chat branches directly in the current project first",
        },
        "part_chat.session_unbound": {
            "zh-CN": "此工作台不属于当前任务",
            "en": "This workbench does not belong to the current task",
        },
        "part_chat.worktree_mismatch": {
            "zh-CN": "当前任务目录与工程目录不同",
            "en": "The current task directory differs from the project directory",
        },
        "part_chat.worktree_mismatch_reauth": {
            "zh-CN": "任务目录与已授权目录不同，请重新授权",
            "en": "The task directory differs from the authorized directory; please re-authorize",
        },
    }
)
