"""Message catalog for `studio.core.cli` (`python -m studio.core`).

One entry per `_CliError`/`_ArgError`-adjacent literal error string plus every
argparse `help`/`description`/`epilog` string in `studio/core/cli.py` that a
human reads (either in `--help` output or in the JSON error body's
`message`). Codes are `<module>.<meaning>`, lower snake_case, and become part
of the public error/response contract once released: never repurpose or
delete one, only add. The "zh-CN" text below is the original wording each
site used to hardcode, carried over verbatim; "en" is a faithful translation,
not a paraphrase. Everything in `studio/core/cli.py` was originally
English-only (no Chinese ever shipped for it) — those entries keep their
original text under "en" and gain a new "zh-CN" translation here.

Imported (for its `register()` side effect) from `studio/core/__init__.py`,
so every code here is registered as soon as anything under `studio.core` is
imported.
"""

from studio.i18n import register

register(
    {
        "cli.action_help": {
            "zh-CN": "动作名，例如 primitive/import/plane_cut/inspect",
            "en": "Action name, e.g. primitive/import/plane_cut/inspect",
        },
        "cli.actor_help": {
            "zh-CN": "记录在工作区历史里的操作者（默认: human）",
            "en": "Recorded in workspace history (default: human)",
        },
        "cli.artifact_help": {
            "zh-CN": "产物 id，来自 `tasks status`",
            "en": "Artifact id, from `tasks status`",
        },
        "cli.description": {
            "zh-CN": "直接访问 studio.core 能力层（recipes、editor、tasks、observation），不经过 Codex 或 HTTP/MCP 壳层。见 docs/CORE_CLI.md。",
            "en": (
                "Direct access to the studio.core capability layer (recipes, editor, tasks, "
                "observation), without Codex or the HTTP/MCP shell. See docs/CORE_CLI.md."
            ),
        },
        "cli.doc_help": {
            "zh-CN": "工作区目录（默认: {default_doc}）",
            "en": "Workspace directory (default: {default_doc})",
        },
        "cli.editor_apply_epilog": {
            "zh-CN": "已知动作（列表可能不全，见上方 --help 文字）: {actions}",
            "en": "Known actions (may be incomplete, see --help text above): {actions}",
        },
        "cli.editor_apply_help": {
            "zh-CN": "执行一个编辑器动作",
            "en": "Apply one editor action",
        },
        "cli.editor_group_help": {
            "zh-CN": "本机带版本管理的网格工作区（studio.core.editor.Workspace）",
            "en": "Local versioned mesh workspace (studio.core.editor.Workspace)",
        },
        "cli.editor_inspect_help": {
            "zh-CN": "读取当前工作区状态（对象、选择、历史）",
            "en": "Read the current workspace state (objects, selection, history)",
        },
        "cli.epilog": {
            "zh-CN": "print ...  转发给 `python -m print_prep.cli`（一套独立的、已完整实现的打印准备管线 CLI）；运行 `python -m studio.core print --help`。",
            "en": (
                "print ...  delegates to `python -m print_prep.cli` (a separate, already-complete "
                "CLI for the print-preparation pipeline); run `python -m studio.core print --help`."
            ),
        },
        "cli.expected_revision_help": {
            "zh-CN": "乐观锁 revision；默认: 先读取工作区当前的 revision",
            "en": "Optimistic-lock revision; default: read the workspace's current revision first",
        },
        "cli.field_must_be_json_object": {
            "zh-CN": "{field} 必须是 JSON 对象",
            "en": "{field} must be a JSON object",
        },
        "cli.filter_help": {
            "zh-CN": "按名称过滤（子串匹配）",
            "en": "Filter by name (substring match)",
        },
        "cli.input_help": {
            "zh-CN": "GLB/STL/PLY/URDF 的绝对路径；可重复，共 1-4 个",
            "en": "Absolute path to a GLB/STL/PLY/URDF; repeatable, 1-4 total",
        },
        "cli.job_help": {
            "zh-CN": "任务目录（默认: PRINT_PREP_HOME/job）",
            "en": "Job directory (default: PRINT_PREP_HOME/job)",
        },
        "cli.json_file_read_failed": {
            "zh-CN": "读取 JSON 文件失败 {path}: {error}",
            "en": "Failed to read JSON file {path}: {error}",
        },
        "cli.label_help": {
            "zh-CN": "每个 --input 对应的标签，按顺序；可重复",
            "en": "Label per --input, in order; repeatable",
        },
        "cli.log_help": {
            "zh-CN": "附带 run.log 的结尾片段",
            "en": "Include the tail of run.log",
        },
        "cli.not_valid_json": {
            "zh-CN": "不是合法 JSON: {error}",
            "en": "Not valid JSON: {error}",
        },
        "cli.observe_group_help": {
            "zh-CN": "多版本渲染 + 量测（studio.core.observation.Observations）",
            "en": "Multi-version render + measure (studio.core.observation.Observations)",
        },
        "cli.observe_run_help": {
            "zh-CN": "启动一个 observation 任务（排入一次本机 Blender 渲染）",
            "en": "Start an observation task (queues a local Blender render)",
        },
        "cli.out_help": {
            "zh-CN": "如果给出，把产物字节复制到这个路径",
            "en": "If given, copy the artifact bytes to this path",
        },
        "cli.params_action_help": {
            "zh-CN": "动作参数的 JSON 对象，或 @file（默认: {}）",
            "en": "JSON object of action params, or @file (default: {})",
        },
        "cli.params_observe_help": {
            "zh-CN": 'JSON 对象，例如 {"views": ["front","iso"], "phases": [0, 1]}',
            "en": 'JSON object, e.g. {"views": ["front","iso"], "phases": [0, 1]}',
        },
        "cli.recipe_check_help": {
            "zh-CN": "校验一份 recipe.json（+ guide.md），不安装它",
            "en": "Validate a recipe.json (+ guide.md) without installing it",
        },
        "cli.recipe_check_path_help": {
            "zh-CN": "配方的 recipe.json 文件路径",
            "en": "Path to the recipe's recipe.json file",
        },
        "cli.recipe_check_path_not_recipe_json": {
            "zh-CN": "请指向配方目录里的 recipe.json 文件",
            "en": "Point at the recipe.json file inside the recipe's directory",
        },
        "cli.recipes_group_help": {
            "zh-CN": "配方目录（studio.core.recipes）",
            "en": "Recipe catalog (studio.core.recipes)",
        },
        "cli.recipes_list_help": {
            "zh-CN": "列出已安装的配方（内置 + 用户）",
            "en": "List installed recipes (built-in + user)",
        },
        "cli.recipes_show_help": {
            "zh-CN": "按 id 显示某个配方的完整内容",
            "en": "Show one recipe's full content by id",
        },
        "cli.request_help": {
            "zh-CN": '任务请求体的 JSON 对象，或 @file；例如 {"template": "..."} 或 {"script": "..."}',
            "en": 'JSON object body, or @file; e.g. {"template": "..."} or {"script": "..."}',
        },
        "cli.result_not_serializable": {
            "zh-CN": "结果无法序列化为 JSON: {error}",
            "en": "Result cannot be serialized to JSON: {error}",
        },
        "cli.source_task_help": {
            "zh-CN": "用先前任务的 id 替代 --input 观测；可重复",
            "en": "Prior task id to observe instead of --input; repeatable",
        },
        "cli.tasks_artifact_help": {
            "zh-CN": "获取（可选复制出）一个任务产物",
            "en": "Fetch (and optionally copy out) one task artifact",
        },
        "cli.tasks_cancel_help": {
            "zh-CN": "请求取消一个正在运行的任务",
            "en": "Request cancellation of a running task",
        },
        "cli.tasks_group_help": {
            "zh-CN": "本机 Blender/CadQuery 任务队列（studio.core.tasks.Tasks）",
            "en": "Local Blender/CadQuery task queue (studio.core.tasks.Tasks)",
        },
        "cli.tasks_id_help": {
            "zh-CN": "任务 id",
            "en": "Task id",
        },
        "cli.tasks_list_help": {
            "zh-CN": "列出最近 100 个任务",
            "en": "List the 100 most recent tasks",
        },
        "cli.tasks_start_help": {
            "zh-CN": "启动一个任务（模板或原始脚本）",
            "en": "Start a task (template or raw script)",
        },
        "cli.tasks_status_help": {
            "zh-CN": "读取一个任务的状态",
            "en": "Read one task's state",
        },
        "cli.title_help": {
            "zh-CN": "任务标题",
            "en": "Task title",
        },
        "cli.tool_schemas_bad_json": {
            "zh-CN": "工具列表快照不是合法 JSON {path}: {error}",
            "en": "Tool schema snapshot is not valid JSON {path}: {error}",
        },
        "cli.tool_schemas_help": {
            "zh-CN": "工具 schema 的 JSON 文件（默认: {default_name}）",
            "en": "JSON file of tool schemas (default: {default_name})",
        },
        "cli.tool_schemas_not_array": {
            "zh-CN": "工具列表快照必须是一个数组: {path}",
            "en": "Tool schema snapshot must be an array: {path}",
        },
        "cli.tool_schemas_read_failed": {
            "zh-CN": "读取工具列表快照失败 {path}: {error}",
            "en": "Failed to read tool schema snapshot {path}: {error}",
        },
        "cli.unknown_recipe": {
            "zh-CN": "未知的配方: {recipe_id!r}",
            "en": "Unknown recipe: {recipe_id!r}",
        },
        "cli.user_dir_help": {
            "zh-CN": "用户配方目录（默认: PRINT_PREP_HOME/recipes）",
            "en": "User recipes directory (default: PRINT_PREP_HOME/recipes)",
        },
    }
)
