"""Message catalog for `studio.core.projects` and `studio.core.recipes`.

One entry per `EditorError`/`ValueError`/`RuntimeError`/`_InvalidRecipe` raise
site in `studio/core/projects.py` and `studio/core/recipes.py`. Codes are
`<module>.<meaning>`, lower snake_case. The "zh-CN" text below is the original
wording each raise site used to hardcode, carried over verbatim; "en" is a
faithful translation, not a paraphrase.

Several `recipes.py` validators build a dotted/indexed "field path" (e.g.
`f"steps[{idx}].args"`, `f"{field}.{k}"`) before formatting it into a message;
that path-building stays in Python (so the rendered text is byte-identical to
before) and the finished path is passed to `render()` as a single `field`/`key`
parameter.

Imported (for its `register()` side effect) from `studio/core/__init__.py`.
"""

from studio.i18n import register

register(
    {
        # --- projects.py ---
        "projects.already_bound_to_other_project": {
            "zh-CN": (
                "此任务已绑定其他工程；请在目标项目创建新任务。如果多个 Claude Code 会话需要各自"
                "绑定不同工程，给这个会话单独的 workspace id：运行 install.sh 前设 "
                "CLAUDE_WORKSPACE_ID=...（会写成 MCP 服务的 PRINT_PREP_WORKSPACE_ID 环境变量），"
                "或者直接给 MCP 服务本身设 PRINT_PREP_WORKSPACE_ID"
            ),
            "en": (
                "This task is already bound to another project; please create a new task in the target "
                "project. If multiple Claude Code sessions need to bind to different projects, give this "
                "session its own workspace id: set CLAUDE_WORKSPACE_ID=... before running install.sh (it "
                "becomes the MCP server's PRINT_PREP_WORKSPACE_ID environment variable), or set "
                "PRINT_PREP_WORKSPACE_ID on the MCP server directly"
            ),
        },
        "projects.codex_task_identity_mismatch": {
            "zh-CN": "Codex 任务身份不一致，未绑定工程",
            "en": "Codex task identity does not match; the project is not bound",
        },
        "projects.copy_requires_source_snapshot": {
            "zh-CN": "复制工程需要来源快照",
            "en": "Copying a project requires a source snapshot",
        },
        "projects.existing_project_requires_source_id": {
            "zh-CN": "此任务已有旧工程；请显式传 source_id=当前任务和 expected_revision，将其复制进空项目目录",
            "en": (
                "This task already has an old project; please explicitly pass source_id=the current task and "
                "expected_revision to copy it into an empty project folder"
            ),
        },
        "projects.folder_must_be_absolute_dir": {
            "zh-CN": "项目目录必须是存在的绝对路径",
            "en": "The project folder must be an existing absolute path",
        },
        "projects.job_symlink_forbidden": {
            "zh-CN": "项目 .3dstudio/job 不能通过软链接共享到另一目录；请创建独立模型分支",
            "en": (
                "A project's .3dstudio/job cannot be shared to another folder via a symlink; please create an "
                "independent model branch"
            ),
        },
        "projects.join_failed_fallback": {
            "zh-CN": "加入项目失败",
            "en": "Failed to join the project",
        },
        "projects.location_moved_or_missing": {
            "zh-CN": "项目目录已移动或不存在，请从新的目录重新打开工程",
            "en": "The project folder has moved or no longer exists; please reopen the project from its new folder",
        },
        "projects.target_folder_already_has_project": {
            "zh-CN": "目标文件夹已有工程，不能覆盖；请直接打开或选择新的空文件夹",
            "en": "The target folder already has a project and cannot be overwritten; open it directly or pick a new empty folder",
        },
        "projects.thread_folder_requires_resolve_cwd": {
            "zh-CN": "thread_folder 需要显式传入 resolve_cwd（例如 studio.shell.codex_projects.resolve_cwd）",
            "en": "thread_folder requires resolve_cwd to be passed explicitly (e.g. studio.shell.codex_projects.resolve_cwd)",
        },
        "projects.workspace_id_must_be_chat_identity": {
            "zh-CN": "workspace_id 必须使用聊天身份",
            "en": "workspace_id must be a chat identity",
        },
        # --- recipes.py ---
        "recipes.args_all_must_be_false": {
            "zh-CN": "{field} 的 all 只能是 false（多盘默认只开第 1 盘）",
            "en": "{field}'s all may only be false (multi-plate defaults to opening plate 1 only)",
        },
        "recipes.args_array_item_invalid": {
            "zh-CN": "{field} 数组元素必须是 JSON 标量（浮点数不能是 NaN/Infinity）",
            "en": "{field}'s array elements must be JSON scalars (floats cannot be NaN/Infinity)",
        },
        "recipes.args_banned_key": {
            "zh-CN": "{field} 不允许出现路径类的键: {key}",
            "en": "{field} may not contain a path-like key: {key}",
        },
        "recipes.args_bool_only": {
            "zh-CN": "{field} 只接受 JSON 布尔 true/false，收到: {value}",
            "en": "{field} only accepts the JSON booleans true/false, got: {value}",
        },
        "recipes.args_dict_value_invalid": {
            "zh-CN": "{field} 必须是标量（字典只能一层，浮点数不能是 NaN/Infinity）",
            "en": "{field} must be a scalar (a dict may only be one level deep; floats cannot be NaN/Infinity)",
        },
        "recipes.args_edit_params_must_be_object": {
            "zh-CN": "编辑 params 必须是对象",
            "en": "Editing params must be an object",
        },
        "recipes.args_key_must_be_string": {
            "zh-CN": "{field} 的键必须是字符串",
            "en": "{field}'s keys must be strings",
        },
        "recipes.args_material_loss_must_be_confirmed": {
            "zh-CN": "贴图丢失必须在执行时明确确认",
            "en": "Texture loss must be explicitly confirmed at execution time",
        },
        "recipes.args_must_be_object": {
            "zh-CN": "{field} 必须是对象",
            "en": "{field} must be an object",
        },
        "recipes.args_no_expected_revision": {
            "zh-CN": "配方不能预设工程版本",
            "en": "A recipe may not preset a project revision",
        },
        "recipes.args_no_preset_ids": {
            "zh-CN": "配方不能预设对象 ID",
            "en": "A recipe may not preset object IDs",
        },
        "recipes.args_too_large": {
            "zh-CN": "{field} 序列化后 {size} 字节，超过 {max_bytes} 字节上限",
            "en": "{field} serializes to {size} bytes, exceeding the {max_bytes}-byte limit",
        },
        "recipes.args_unknown_params": {
            "zh-CN": "{field} 出现工具 {tool_name} 不认识的入参: {unknown}",
            "en": "{field} has parameters tool {tool_name} does not recognize: {unknown}",
        },
        "recipes.args_unsupported_edit_action": {
            "zh-CN": "配方中的编辑 action 不受支持",
            "en": "This edit action is not supported in a recipe",
        },
        "recipes.args_value_type_unsupported": {
            "zh-CN": "{field} 的值类型不受支持: {type}",
            "en": "{field}'s value type is not supported: {type}",
        },
        "recipes.author_too_long": {
            "zh-CN": "author 不能超过 {max_len} 个字符",
            "en": "author cannot exceed {max_len} characters",
        },
        "recipes.dir_scan_failed": {
            "zh-CN": "目录扫描失败: {error}",
            "en": "Directory scan failed: {error}",
        },
        "recipes.edit_recipe_no_one_shot": {
            "zh-CN": "编辑配方不支持打印 one_shot",
            "en": "An editing recipe does not support a print one_shot",
        },
        "recipes.edit_recipe_only_studio_edit": {
            "zh-CN": "编辑配方只能使用 studio_edit",
            "en": "An editing recipe may only use studio_edit",
        },
        "recipes.enum_item_invalid": {
            "zh-CN": "{field} 不认识的取值: {value}",
            "en": "{field} has an unrecognized value: {value}",
        },
        "recipes.field_max_items": {
            "zh-CN": "{field} 最多 {max_len} 条",
            "en": "{field} allows at most {max_len} item(s)",
        },
        "recipes.field_min_items": {
            "zh-CN": "{field} 至少要有 {min_len} 条",
            "en": "{field} requires at least {min_len} item(s)",
        },
        "recipes.field_must_be_array": {
            "zh-CN": "{field} 必须是数组",
            "en": "{field} must be an array",
        },
        "recipes.field_must_be_string": {
            "zh-CN": "{field} 必须是字符串",
            "en": "{field} must be a string",
        },
        "recipes.field_must_not_be_empty": {
            "zh-CN": "{field} 不能为空",
            "en": "{field} cannot be empty",
        },
        "recipes.field_too_long": {
            "zh-CN": "{field} 超过 {max_len} 个字符（实际 {actual}）",
            "en": "{field} exceeds {max_len} characters (actual {actual})",
        },
        "recipes.guide_md_bad_utf8": {
            "zh-CN": "guide.md 不是合法 UTF-8: {error}",
            "en": "guide.md is not valid UTF-8: {error}",
        },
        "recipes.guide_md_missing": {
            "zh-CN": "缺少 guide.md（或它不是普通文件）",
            "en": "guide.md is missing (or it is not a regular file)",
        },
        "recipes.guide_md_read_failed": {
            "zh-CN": "guide.md 读取失败: {error}",
            "en": "Failed to read guide.md: {error}",
        },
        "recipes.guide_md_stat_failed": {
            "zh-CN": "guide.md 无法读取文件大小: {error}",
            "en": "Could not read guide.md's file size: {error}",
        },
        "recipes.guide_md_too_large": {
            "zh-CN": "guide.md 有 {size} 字节，超过 {max_bytes} 字节上限（超限不读内容）",
            "en": "guide.md is {size} bytes, exceeding the {max_bytes}-byte limit (contents not read past the limit)",
        },
        "recipes.id_conflict": {
            "zh-CN": "id {id} 与已装载的配方冲突（以 {winner_source} 那份为准）",
            "en": "id {id} conflicts with an already-loaded recipe (the {winner_source} copy takes precedence)",
        },
        "recipes.id_dirname_mismatch": {
            "zh-CN": "id({id}) 与目录名({dirname}) 不一致",
            "en": "id ({id}) does not match the directory name ({dirname})",
        },
        "recipes.id_invalid": {
            "zh-CN": "id 不合法: {id}",
            "en": "Invalid id: {id}",
        },
        "recipes.json_constant_not_allowed": {
            "zh-CN": "recipe.json 包含不允许的数值记号: {name}",
            "en": "recipe.json contains a disallowed numeric token: {name}",
        },
        "recipes.license_too_long": {
            "zh-CN": "license 不能超过 {max_len} 个字符",
            "en": "license cannot exceed {max_len} characters",
        },
        "recipes.not_configured": {
            "zh-CN": "studio.core.recipes 用前须先调用 configure()（通常由 studio.shell.server 在导入时完成）",
            "en": "studio.core.recipes must be configure()'d before use (normally done by studio.shell.server on import)",
        },
        "recipes.one_shot_must_be_object_or_null": {
            "zh-CN": "one_shot 必须是对象或 null",
            "en": "one_shot must be an object or null",
        },
        "recipes.one_shot_send_must_be_false": {
            "zh-CN": "one_shot.args 的 send 只能是 false（打开 Bambu Studio 必须是单独一步）",
            "en": "one_shot.args's send may only be false (opening Bambu Studio must be its own step)",
        },
        "recipes.one_shot_tool_invalid": {
            "zh-CN": "one_shot.tool 只能指向 studio_prepare，收到: {tool}",
            "en": "one_shot.tool may only point to studio_prepare, got: {tool}",
        },
        "recipes.provenance_date_invalid": {
            "zh-CN": "provenance[{i}].date 必须是 YYYY-MM-DD 格式: {date}",
            "en": "provenance[{i}].date must be in YYYY-MM-DD format: {date}",
        },
        "recipes.provenance_item_must_be_object": {
            "zh-CN": "provenance[{i}] 必须是对象",
            "en": "provenance[{i}] must be an object",
        },
        "recipes.provenance_note_too_long": {
            "zh-CN": "provenance[{i}].note 不能超过 {max_len} 个字符",
            "en": "provenance[{i}].note cannot exceed {max_len} characters",
        },
        "recipes.provenance_ref_invalid": {
            "zh-CN": "provenance[{i}].ref 必须是 1-{max_len} 个字符的非空字符串",
            "en": "provenance[{i}].ref must be a non-empty string of 1 to {max_len} characters",
        },
        "recipes.recipe_json_bad_json": {
            "zh-CN": "recipe.json 不是合法 JSON: {error}",
            "en": "recipe.json is not valid JSON: {error}",
        },
        "recipes.recipe_json_bad_utf8": {
            "zh-CN": "recipe.json 不是合法 UTF-8: {error}",
            "en": "recipe.json is not valid UTF-8: {error}",
        },
        "recipes.recipe_json_missing": {
            "zh-CN": "缺少 recipe.json（或它不是普通文件）",
            "en": "recipe.json is missing (or it is not a regular file)",
        },
        "recipes.recipe_json_must_be_object": {
            "zh-CN": "recipe.json 必须是 JSON 对象",
            "en": "recipe.json must be a JSON object",
        },
        "recipes.recipe_json_read_failed": {
            "zh-CN": "recipe.json 读取失败: {error}",
            "en": "Failed to read recipe.json: {error}",
        },
        "recipes.recipe_json_stat_failed": {
            "zh-CN": "recipe.json 无法读取文件大小: {error}",
            "en": "Could not read recipe.json's file size: {error}",
        },
        "recipes.recipe_json_too_large": {
            "zh-CN": "recipe.json 有 {size} 字节，超过 {max_bytes} 字节上限（超限不读内容）",
            "en": "recipe.json is {size} bytes, exceeding the {max_bytes}-byte limit (contents not read past the limit)",
        },
        "recipes.row_label_arrange": {
            "zh-CN": "分盘",
            "en": "Arrange",
        },
        "recipes.row_label_check": {
            "zh-CN": "试切",
            "en": "Test cut",
        },
        "recipes.row_label_color": {
            "zh-CN": "分色",
            "en": "Color split",
        },
        "recipes.row_label_connect": {
            "zh-CN": "连接",
            "en": "Connect",
        },
        "recipes.row_label_deliver": {
            "zh-CN": "交付",
            "en": "Deliver",
        },
        "recipes.row_label_export": {
            "zh-CN": "工艺",
            "en": "Process",
        },
        "recipes.row_label_export_mesh": {
            "zh-CN": "导出模型",
            "en": "Export model",
        },
        "recipes.row_label_inspect_mesh": {
            "zh-CN": "检查网格",
            "en": "Inspect mesh",
        },
        "recipes.row_label_joint": {
            "zh-CN": "关节",
            "en": "Joint",
        },
        "recipes.row_label_material": {
            "zh-CN": "材质",
            "en": "Material",
        },
        "recipes.row_label_model": {
            "zh-CN": "模型",
            "en": "Model",
        },
        "recipes.row_label_orient": {
            "zh-CN": "朝向",
            "en": "Orient",
        },
        "recipes.row_label_repair_mesh": {
            "zh-CN": "修复网格",
            "en": "Repair mesh",
        },
        "recipes.row_label_simplify_mesh": {
            "zh-CN": "减面",
            "en": "Simplify",
        },
        "recipes.row_label_source": {
            "zh-CN": "来源",
            "en": "Source",
        },
        "recipes.row_label_split": {
            "zh-CN": "拆件",
            "en": "Split",
        },
        "recipes.schema_field_invalid": {
            "zh-CN": "schema 字段必须是 {schema_id}，收到: {got}",
            "en": "The schema field must be {schema_id}, got: {got}",
        },
        "recipes.step_key_duplicate": {
            "zh-CN": "steps[{idx}].key 与前面的步骤重复: {key}",
            "en": "steps[{idx}].key duplicates an earlier step: {key}",
        },
        "recipes.step_key_invalid": {
            "zh-CN": "steps[{idx}].key 不合法: {key}",
            "en": "steps[{idx}].key is invalid: {key}",
        },
        "recipes.step_must_be_object": {
            "zh-CN": "steps[{idx}] 必须是对象",
            "en": "steps[{idx}] must be an object",
        },
        "recipes.step_optional_must_be_bool": {
            "zh-CN": "steps[{idx}].optional 必须是布尔值",
            "en": "steps[{idx}].optional must be a boolean",
        },
        "recipes.step_row_invalid": {
            "zh-CN": "steps[{idx}].row 不合法: {row}",
            "en": "steps[{idx}].row is invalid: {row}",
        },
        "recipes.step_tool_suffix_conflicts_args": {
            "zh-CN": "steps[{idx}].tool 的 #{suffix} 与 args.{field}={value} 不一致；二者只写一个，或写成一样",
            "en": "steps[{idx}].tool suffix #{suffix} conflicts with args.{field}={value}; give one of them, or make them agree",
        },
        "recipes.step_tool_ambiguous_task_suffix": {
            "zh-CN": "studio_task#{suffix} 同时是一个本地任务模板的 id 和一个已声明托管服务操作的 id，二者必须只留一个",
            "en": "studio_task#{suffix} is both a local task template id and a declared hosted-service operation id; only one may exist",
        },
        "recipes.step_tool_grammar_invalid": {
            "zh-CN": "steps[{idx}].tool 不符合语法（工具名，或工具名#细粒度能力名）: {tool}",
            "en": "steps[{idx}].tool does not match the grammar (a tool name, or tool name#fine-grained-capability): {tool}",
        },
        "recipes.step_tool_must_be_nonempty_string": {
            "zh-CN": "steps[{idx}].tool 必须是非空字符串",
            "en": "steps[{idx}].tool must be a non-empty string",
        },
        "recipes.step_who_invalid": {
            "zh-CN": "steps[{idx}].who 不合法: {who}",
            "en": "steps[{idx}].who is invalid: {who}",
        },
        "recipes.steps_max_items": {
            "zh-CN": "steps 最多 {max_steps} 步",
            "en": "steps allows at most {max_steps} step(s)",
        },
        "recipes.steps_min_items": {
            "zh-CN": "steps 至少要有 1 步",
            "en": "steps requires at least 1 step",
        },
        "recipes.version_invalid": {
            "zh-CN": "version 必须是 1-{max_len} 个字符的非空字符串",
            "en": "version must be a non-empty string of 1 to {max_len} characters",
        },
        "recipes.workspace_invalid": {
            "zh-CN": "workspace 必须是 print、edit 或 tasks",
            "en": "workspace must be print, edit, or tasks",
        },
        # --- recipes.py (workspace "tasks", added with the head-shell recipe) ---
        "recipes.args_task_recipe_start_only": {
            "zh-CN": "建模配方只能预选模板；来源、脚本和参数需在执行时提供",
            "en": "A modelling recipe may only preselect the template; the source, script, and parameters must be supplied at execution time",
        },
        "recipes.row_label_appearance": {
            "zh-CN": "外观复核",
            "en": "Appearance review",
        },
        "recipes.row_label_head_fit": {
            "zh-CN": "头部空间",
            "en": "Head clearance",
        },
        "recipes.row_label_shell_build": {
            "zh-CN": "生成头壳",
            "en": "Generate shell",
        },
        "recipes.row_label_shell_geometry": {
            "zh-CN": "几何与装配",
            "en": "Geometry & assembly",
        },
        "recipes.row_label_shell_plan": {
            "zh-CN": "尺寸与外观",
            "en": "Size & appearance",
        },
        "recipes.row_label_sight": {
            "zh-CN": "观察视线",
            "en": "Sightline",
        },
        "recipes.task_template_unsupported": {
            "zh-CN": "此模板尚未支持建模配方检查",
            "en": "This template does not yet support modelling-recipe checks",
        },
        "recipes.tasks_recipe_missing_checks": {
            "zh-CN": "建模配方必须包含完整检查步骤",
            "en": "A modelling recipe must include the complete set of check steps",
        },
        "recipes.tasks_recipe_no_one_shot": {
            "zh-CN": "建模配方不支持跳过中间判断的一键执行",
            "en": "A modelling recipe does not support a one-shot run that skips intermediate judgment",
        },
        "recipes.tasks_recipe_steps_must_be_required_you": {
            "zh-CN": "建模配方通过设置与复核入口执行",
            "en": "A modelling recipe is carried out through its own setup and review entry points",
        },
        "recipes.tasks_recipe_tool_template_mismatch": {
            "zh-CN": "建模配方工具与模板不匹配",
            "en": "The modelling recipe's tool does not match its template",
        },
    }
)
