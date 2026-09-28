"""Message catalog for `studio.core.workspaces` raises and the UI-facing
strings its `list_workspaces()` returns.

One entry per `ValueError(...)` call site (workspaces.py deliberately raises
bare `ValueError`, not `EditorError` -- callers such as the MCP server catch
it directly) plus the default display strings `list_workspaces()` returns for
a project whose directory is unavailable or has no name. Codes are
`<module>.<meaning>`, lower snake_case, and become part of the public
error/response contract once released: never repurpose or delete one, only
add. The "zh-CN" text below is the original wording each site used to
hardcode, carried over verbatim; "en" is a faithful translation, not a
paraphrase.

Imported (for its `register()` side effect) from `studio/core/__init__.py`, so
every code here is registered as soon as anything under `studio.core` is
imported -- before `workspaces.py`'s functions can call
`studio.i18n.render()`.
"""

from studio.i18n import register

register(
    {
        "workspaces.blender_source_asset_checksum_failed": {
            "zh-CN": "Blender 源资产校验失败",
            "en": "Blender source asset checksum failed",
        },
        "workspaces.cannot_fork_from_self": {
            "zh-CN": "不能从自身创建分支",
            "en": "Cannot fork a workspace from itself",
        },
        "workspaces.fork_target_already_exists": {
            "zh-CN": "目标工作台已经存在；请为分支使用新的任务 ID",
            "en": "The target workspace already exists; use a new task ID for the fork",
        },
        "workspaces.invalid_blender_source_asset": {
            "zh-CN": "无效 Blender 源资产",
            "en": "Invalid Blender source asset",
        },
        "workspaces.invalid_id": {
            "zh-CN": "workspace_id 须为当前 Codex 任务 ID；legacy 仅可作为分支来源",
            "en": "workspace_id must be the current Codex task ID; legacy can only be used as a fork source",
        },
        "workspaces.invalid_model_asset_id": {
            "zh-CN": "无效模型资产 ID",
            "en": "Invalid model asset ID",
        },
        "workspaces.model_asset_checksum_failed": {
            "zh-CN": "模型资产校验失败",
            "en": "Model asset checksum failed",
        },
        "workspaces.project_directory_unavailable_error": {
            "zh-CN": "目录已移动或不可访问，请从新目录重新打开。",
            "en": "The directory has moved or is inaccessible; reopen it from its new location.",
        },
        "workspaces.project_directory_unavailable_name": {
            "zh-CN": "项目目录不可用",
            "en": "Project directory unavailable",
        },
        "workspaces.target_already_has_project": {
            "zh-CN": "目标任务已有独立工程，不能覆盖；请创建新的聊天分支",
            "en": "The target task already has its own project and cannot be overwritten; create a new chat fork instead",
        },
        "workspaces.target_bound_to_other_project": {
            "zh-CN": "目标任务已绑定另一工程",
            "en": "The target task is already bound to another project",
        },
        "workspaces.unbound": {
            "zh-CN": "未绑定工作台：请传 workspace_id=当前 Codex 任务 ID；不要使用其他任务的 ID。可从 CODEX_THREAD_ID 读取。",
            "en": (
                "No workspace bound: pass workspace_id=<the current Codex task ID>; do not use another task's "
                "ID. It can be read from CODEX_THREAD_ID."
            ),
        },
        "workspaces.untitled_project": {
            "zh-CN": "未命名工程",
            "en": "Untitled project",
        },
    }
)
