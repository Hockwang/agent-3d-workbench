"""studio.core.recipes —— 配方（Recipe）的装载、校验与和流程状态的融合（SPEC_RECIPES.md）。

配方 = 数据（`recipe.json` + `guide.md`），描述一条穿过能力行的预设路线；本模块
只读文件、做校验、算派生字段（`source`/`route`/`missing_tools`/`availability`），
再把配方步骤跟 `readiness`/`stale`/`busy` 拼成 `steps[].status`/`next`/`done`/
`total`——不含任何"执行"逻辑，真正干活仍然是 `studio/shell/server.py` 里已有的
`api_load`/`api_orient`/... 等方法。

`load_recipes()` 的两个目录参数（内置/用户）**都是必填的构造参数，本模块不读
任何环境变量、不取任何默认路径**：生产代码（`studio/shell/server.py`）传
`BUILTIN_RECIPES_DIR`（插件根下的 `recipes/`）与
`studio.print_prep_home() / "recipes"`；测试直接传 `tmp_path` 下的临时目录，
两侧都能被完全隔离，不会碰真实的 `recipes/` 或 `~/.print-prep/recipes/`。

本模块不直接 import `studio.shell`（层规则，见 `docs/ARCHITECTURE.md`）：校验
步骤需要的"当前完整工具列表"通过 `configure()` 从外部注入，由
`studio.shell.server` 在导入时调用一次，传 `tools_schema.get_tools`。
"""

from __future__ import annotations

import json
import hashlib
import math
import re
from pathlib import Path
from typing import Any, Callable, Optional

from studio.core import capabilities
from studio.i18n import render
from studio.paths import PLUGIN_ROOT as _PLUGIN_ROOT

_tool_schemas_provider: Optional[Callable[[], list[dict[str, Any]]]] = None
_hosted_operations_provider: Optional[Callable[[], set[str]]] = None


def configure(
    tool_schemas_provider: Callable[[], list[dict[str, Any]]],
    hosted_operations_provider: Optional[Callable[[], set[str]]] = None,
) -> None:
    """由 `studio.shell.server` 在导入时调用一次，把"去哪里拿当前完整工具
    列表"注入进来；本模块因此不需要直接 import `studio.shell.tools_schema`
    （层规则）。测试通过 `import studio.shell.server` 间接触发同一次配置。

    `hosted_operations_provider` 是可选的第二个注入点：返回当前服务目录里
    任一 provider 声明过的托管操作 id 集合（`studio.adapters.services`，
    同样出于层规则不能被本模块直接 import），用来把 `studio_task#<operation>`
    这类步骤（比如 image-to-3d）纳入 `studio.core.capabilities.build()` 的
    能力表；不传时对应能力表里没有任何托管操作，只有本地任务模板。"""
    global _tool_schemas_provider, _hosted_operations_provider
    _tool_schemas_provider = tool_schemas_provider
    _hosted_operations_provider = hosted_operations_provider


def _current_tools() -> list[dict[str, Any]]:
    if _tool_schemas_provider is None:
        raise RuntimeError(render("recipes.not_configured"))
    return _tool_schemas_provider()


# 内置配方目录：插件根下的 `recipes/`（SPEC_RECIPES.md §1）。生产代码用这个
# 常量；测试装载"真的内置配方"时也读它（唯一一处允许接触真实目录的用例）。
BUILTIN_RECIPES_DIR = _PLUGIN_ROOT / "recipes"

_ID_RE = re.compile(r"^[a-z][a-z0-9-]{2,40}$")
_STEP_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{1,24}$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# `steps[].tool`：裸的工具名（`studio_edit`），或者工具名后跟 `#` + 一个细粒度
# 能力名（`studio_edit#plane_cut`、`studio_task#assembly-audit`）——后者用来
# 引用一个真实工具下、还没有单独建成顶层工具的具体能力，见 `_step_available()`
# 和 `studio.core.capabilities`。
_TOOL_RE = re.compile(r"^studio_[a-z_]+(#[a-z0-9_-]+)?$")
# `tool#suffix` 与哪个 args 字段说的是同一件事（见 `_validate_step`）。
_SUFFIX_ARG_FIELDS = {
    "studio_edit": ("action",),
    "studio_motion": ("action",),
    "studio_task": ("template", "operation"),
}

_VALID_INPUTS = {"mesh", "mesh_set", "labels", "cut_plan", "image", "urdf"}
_VALID_BACKENDS = {"image_to_3d", "segmentation", "llm"}
_VALID_WHO = {"you", "ai", "either"}
_BANNED_ARG_KEYS = {"files", "file", "path", "paths", "job", "out", "output"}
# 布尔语义的键：跨工具统一只接受 JSON 布尔（防 `1`/`"yes"` 这类"看着像真"的值
# 蒙混过关——消费端一律是 `bool(body.get(...))`，非布尔真值会被当真执行）。
_BOOL_ONLY_ARG_KEYS = {"merge", "no_project", "check", "dry_run"}
_MAX_ARGS_BYTES = 2048
_MAX_RECIPE_JSON_BYTES = 64 * 1024
_MAX_GUIDE_BYTES = 8192
_MAX_PROVENANCE_ITEMS = 8
_MAX_REF_LEN = 120
_MAX_NOTE_LEN = 120
_MAX_AUTHOR_LEN = 60
_MAX_LICENSE_LEN = 60
_MAX_VERSION_LEN = 20
_MAX_STEPS = 24
_MAX_INPUTS_ITEMS = 10
_MAX_BACKENDS_ITEMS = 10
_SCHEMA_ID = "print-prep.recipe/1"

# SPEC_RECIPES.md §2：行表。前六行面板上已经有；后五行是预留给后续能力的行，
# 现在面板上没有，配方引用到时显示成灰色（由前端负责，这里只如实报 `exists`）。
# `label` 是消息码，不是文本——`load_recipes()` 每次调用都重新渲染（不像
# `observation.py` 的 `CATALOG` 是导入期建好、需要 `task_templates.localized_catalog()`
# 那套单独的延迟渲染机制；这里的 `ROW_TABLE` 只在按请求跑的 `load_recipes()`
# 里被消费，可以直接在那儿渲染）。
ROW_TABLE: tuple[dict[str, Any], ...] = (
    {"key": "source", "label": "recipes.row_label_source", "exists": False},
    {"key": "model", "label": "recipes.row_label_model", "exists": True},
    {"key": "split", "label": "recipes.row_label_split", "exists": True},
    {"key": "inspect_mesh", "label": "recipes.row_label_inspect_mesh", "exists": True},
    {"key": "repair_mesh", "label": "recipes.row_label_repair_mesh", "exists": True},
    {"key": "simplify_mesh", "label": "recipes.row_label_simplify_mesh", "exists": True},
    {"key": "material", "label": "recipes.row_label_material", "exists": True},
    {"key": "export_mesh", "label": "recipes.row_label_export_mesh", "exists": True},
    {"key": "shell_plan", "label": "recipes.row_label_shell_plan", "exists": True},
    {"key": "shell_build", "label": "recipes.row_label_shell_build", "exists": True},
    {"key": "shell_geometry", "label": "recipes.row_label_shell_geometry", "exists": True},
    {"key": "head_fit", "label": "recipes.row_label_head_fit", "exists": True},
    {"key": "sight", "label": "recipes.row_label_sight", "exists": True},
    {"key": "appearance", "label": "recipes.row_label_appearance", "exists": True},
    {"key": "connect", "label": "recipes.row_label_connect", "exists": False},
    {"key": "joint", "label": "recipes.row_label_joint", "exists": False},
    {"key": "color", "label": "recipes.row_label_color", "exists": False},
    {"key": "orient", "label": "recipes.row_label_orient", "exists": True},
    {"key": "arrange", "label": "recipes.row_label_arrange", "exists": True},
    {"key": "export", "label": "recipes.row_label_export", "exists": True},
    {"key": "check", "label": "recipes.row_label_check", "exists": True},
    {"key": "deliver", "label": "recipes.row_label_deliver", "exists": True},
)
ROW_KEYS: tuple[str, ...] = tuple(r["key"] for r in ROW_TABLE)

# §3.3：行 <-> job.json 步骤名/`busy.op` 的对应。"deliver" 没有对应的 job.json
# 步骤（`send` 不产出 job.json 段落，见 `studio/core/history.py` 的 `_steps_produced`），
# 所以不在 `_ROW_TO_STALE_STEP` 里，只出现在 `_ROW_TO_BUSY_OPS` 里。
_ROW_TO_STALE_STEP = {
    "model": "inspect",
    "orient": "orient",
    "arrange": "arrange",
    "export": "export",
    "check": "check",
}
_ROW_TO_BUSY_OPS = {
    "model": ("inspect", "load"),
    "orient": ("orient",),
    "arrange": ("arrange",),
    "export": ("export",),
    "check": ("check",),
    "deliver": ("send",),
}
_KNOWN_ROWS = ("model", "orient", "arrange", "export", "check", "deliver")

_SUMMARY_KEYS = (
    "workspace",
    "task_template",
    "id",
    "version",
    "title",
    "goal",
    "use_when",
    "not_for",
    "inputs",
    "backends",
    "route",
    "source",
    "availability",
    "missing_tools",
    "provenance",
)

_STEP_VIEW_KEYS = ("key", "row", "tool", "who", "optional", "decide", "accept", "args", "call")


class RecipeError(Exception):
    """§3.2 的非 200 情形（配方不存在 / 不可用）：不是参数错也不是环境错，是一种
    独立的状态。`studio.shell.server._cli_call` 识别这个类型后映射成对应的 HTTP 状态
    码，`payload` 会原样合并进响应体顶层（比如 `missing_tools`）。"""

    def __init__(self, code: str, message: str, status: int, payload: Optional[dict[str, Any]] = None):
        super().__init__(message)
        self.code = code
        self.status = status
        self.payload = payload or {}


class _InvalidRecipe(Exception):
    """装载单个配方目录时的校验失败；只在 `_load_one()` 内部使用，被捕获后进
    `problems` 列表，不会让别的配方也装不上。"""


def _require(cond: bool, message: str) -> None:
    if not cond:
        raise _InvalidRecipe(message)


def _require_str_len(value: Any, field: str, max_len: int, *, allow_empty: bool = False) -> str:
    _require(isinstance(value, str), render("recipes.field_must_be_string", field=field))
    if not allow_empty:
        _require(bool(value.strip()), render("recipes.field_must_not_be_empty", field=field))
    _require(len(value) <= max_len, render("recipes.field_too_long", field=field, max_len=max_len, actual=len(value)))
    return value


# ---------------------------------------------------------------------------
# `args` 校验（SPEC_RECIPES.md §1 的限制列表）
# ---------------------------------------------------------------------------


def _is_valid_scalar(value: Any) -> bool:
    """JSON 标量；浮点数额外要求有限（拒绝 `NaN`/`Infinity`/`-Infinity`——它们
    能通过 Python 的 `json` 往返，但穿到响应体里会让浏览器 `JSON.parse` 直接
    炸掉，见 SPEC_RECIPES.md §3 小补丁）。"""
    if value is None or isinstance(value, (str, bool, int)):
        return True
    if isinstance(value, float):
        return math.isfinite(value)
    return False


def _is_false_literal(value: Any) -> bool:
    """严格意义的"字面 false"：必须是 JSON 布尔类型且值为 false。`0`/`""`/
    `"false"` 这类"看着假"但类型不对的值一律不算数。"""
    return isinstance(value, bool) and value is False


def _validate_arg_value_shape(value: Any, field: str) -> None:
    """值只能是 JSON 标量、标量数组，或一层的标量字典。"""
    if _is_valid_scalar(value):
        return
    if isinstance(value, list):
        for item in value:
            _require(_is_valid_scalar(item), render("recipes.args_array_item_invalid", field=field))
        return
    if isinstance(value, dict):
        for k, v in value.items():
            _require(isinstance(k, str), render("recipes.args_key_must_be_string", field=field))
            _require(_is_valid_scalar(v), render("recipes.args_dict_value_invalid", field=f"{field}.{k}"))
        return
    raise _InvalidRecipe(render("recipes.args_value_type_unsupported", field=field, type=type(value).__name__))


def _scan_banned_keys(args: dict[str, Any], field: str) -> None:
    """任何层级都不允许出现路径类的键（顶层 + 一层嵌套字典的键）。"""
    for k, v in args.items():
        _require(k not in _BANNED_ARG_KEYS, render("recipes.args_banned_key", field=field, key=repr(k)))
        if isinstance(v, dict):
            for kk in v:
                _require(
                    kk not in _BANNED_ARG_KEYS,
                    render("recipes.args_banned_key", field=f"{field}.{k}", key=repr(kk)),
                )


def _validate_args(
    raw_args: Any, field: str, tool_name: str, tools_by_name: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    args = raw_args if raw_args is not None else {}
    _require(isinstance(args, dict), render("recipes.args_must_be_object", field=field))
    for k, v in args.items():
        _require(isinstance(k, str), render("recipes.args_key_must_be_string", field=field))
        _validate_arg_value_shape(v, f"{field}.{k}")
        if k in _BOOL_ONLY_ARG_KEYS:
            _require(
                isinstance(v, bool),
                render("recipes.args_bool_only", field=f"{field}.{k}", value=repr(v)),
            )
    _scan_banned_keys(args, field)
    size = len(json.dumps(args, ensure_ascii=False).encode("utf-8"))
    _require(
        size <= _MAX_ARGS_BYTES,
        render("recipes.args_too_large", field=field, size=size, max_bytes=_MAX_ARGS_BYTES),
    )

    tool = tools_by_name.get(tool_name)
    if tool is not None:
        schema = tool.get("inputSchema") or {}
        if not schema.get("additionalProperties"):
            allowed = set((schema.get("properties") or {}).keys())
            unknown = sorted(k for k in args if k not in allowed)
            _require(
                not unknown,
                render("recipes.args_unknown_params", field=field, tool_name=repr(tool_name), unknown=unknown),
            )
    # 工具还没接进来（"缺能力"）时没有 schema 可查键名，只能跳过这一条；上面的
    # 形状/路径键/大小校验对任何工具都照跑。

    if tool_name == "studio_send_to_bambu" and "all" in args:
        # 只要出现就必须是字面 false；`1`/`"yes"` 这类非布尔真值以前能靠
        # `is not True` 蒙混过去，消费端却是 `bool(...)`，等价于真的打开了全部盘。
        _require(_is_false_literal(args["all"]), render("recipes.args_all_must_be_false", field=field))
    if tool_name == "studio_edit":
        _require("expected_revision" not in args, render("recipes.args_no_expected_revision"))
        _require(
            args.get("action")
            in {"import", "inspect", "repair", "simplify", "plane_cut", "split_components", "material", "export"},
            render("recipes.args_unsupported_edit_action"),
        )
        params = args.get("params", {})
        _require(isinstance(params, dict), render("recipes.args_edit_params_must_be_object"))
        _require("ids" not in params, render("recipes.args_no_preset_ids"))
        _require("allow_material_loss" not in params, render("recipes.args_material_loss_must_be_confirmed"))
    if tool_name in ("studio_task", "studio_observe"):
        # A modelling recipe (SPEC_RECIPES.md workspace "tasks") may only preselect
        # which template to open; the source file, script and parameters are never
        # preset by the recipe and must be supplied when the step is actually run.
        allowed = {"action", "template"} if tool_name == "studio_task" else {"action"}
        _require(
            set(args) <= allowed and args.get("action") == "start",
            render("recipes.args_task_recipe_start_only"),
        )
    return dict(args)


# ---------------------------------------------------------------------------
# `recipe.json` 校验
# ---------------------------------------------------------------------------


def _validate_step(raw: Any, idx: int, seen_keys: set[str], tools_by_name: dict[str, dict[str, Any]]) -> dict[str, Any]:
    _require(isinstance(raw, dict), render("recipes.step_must_be_object", idx=idx))
    key = raw.get("key")
    _require(
        isinstance(key, str) and bool(_STEP_KEY_RE.match(key)),
        render("recipes.step_key_invalid", idx=idx, key=repr(key)),
    )
    _require(key not in seen_keys, render("recipes.step_key_duplicate", idx=idx, key=repr(key)))
    seen_keys.add(key)

    row = raw.get("row")
    _require(row in ROW_KEYS, render("recipes.step_row_invalid", idx=idx, row=repr(row)))

    tool = raw.get("tool")
    _require(isinstance(tool, str) and bool(tool), render("recipes.step_tool_must_be_nonempty_string", idx=idx))

    if tool == "studio_plane_cut":
        # 兼容别名（SPEC_RECIPES.md）：旧配方规范化为 studio_edit(action=plane_cut)；
        # 新配方应该直接写 `studio_edit#plane_cut` + `args.action`（见下面的语法）。
        raw = {**raw, "tool": "studio_edit", "args": {"action": "plane_cut"}, "who": "you"}
        tool = "studio_edit"

    _require(bool(_TOOL_RE.match(tool)), render("recipes.step_tool_grammar_invalid", idx=idx, tool=repr(tool)))
    base_tool = tool.split("#", 1)[0]

    who = raw.get("who")
    _require(who in _VALID_WHO, render("recipes.step_who_invalid", idx=idx, who=repr(who)))

    decide = _require_str_len(raw.get("decide"), f"steps[{idx}].decide", 80)
    accept = _require_str_len(raw.get("accept"), f"steps[{idx}].accept", 80)

    optional = raw.get("optional", False)
    _require(isinstance(optional, bool), render("recipes.step_optional_must_be_bool", idx=idx))

    # `args` 的键名/形状校验，以及 studio_edit/studio_task/studio_observe/
    # studio_send_to_bambu 各自的专项限制，都只认真实工具（`#` 之前那半）：
    # `tool#action` 的 `action` 只影响下面 `_finalize()` 算的可用性与 `call`。
    args = _validate_args(raw.get("args"), f"steps[{idx}].args", base_tool, tools_by_name)

    # `tool#suffix` 与 `args` 里指同一件事的字段（studio_edit / studio_motion 的
    # action、studio_task 的 template / operation）如果都写了，必须一致，否则可用性
    # 按后缀算、实际调用按 args 走，两边会各说各话。studio_task 的 `args.action`
    # 是 start / cancel 这类任务动作，不是模板名，所以不在比对之列。
    _, suffix = _split_tool(tool)
    if suffix is not None and isinstance(args, dict):
        for field in _SUFFIX_ARG_FIELDS.get(base_tool, ()):
            value = args.get(field)
            _require(
                value is None or value == suffix,
                render(
                    "recipes.step_tool_suffix_conflicts_args", idx=idx, suffix=suffix, field=field, value=repr(value)
                ),
            )

    return {
        "key": key,
        "row": row,
        "tool": tool,
        "who": who,
        "args": args,
        "decide": decide,
        "accept": accept,
        "optional": bool(optional),
    }


def _validate_one_shot(raw: Any, tools_by_name: dict[str, dict[str, Any]]) -> Optional[dict[str, Any]]:
    if raw is None:
        return None
    _require(isinstance(raw, dict), render("recipes.one_shot_must_be_object_or_null"))
    _require(
        raw.get("tool") == "studio_prepare",
        render("recipes.one_shot_tool_invalid", tool=repr(raw.get("tool"))),
    )
    args = _validate_args(raw.get("args"), "one_shot.args", "studio_prepare", tools_by_name)
    if "send" in args:
        # `api_prepare()` 把 `body["send"]` 当布尔映射成 `ns.open`；只要出现就
        # 必须是字面 false，`1`/`"yes"` 一样能在消费端触发"打开 Bambu Studio"。
        _require(_is_false_literal(args["send"]), render("recipes.one_shot_send_must_be_false"))
    return {"tool": "studio_prepare", "args": args}


def _validate_provenance(raw: Any) -> list[dict[str, Any]]:
    _require(
        isinstance(raw, list) and len(raw) >= 1,
        render("recipes.field_min_items", field="provenance", min_len=1),
    )
    _require(
        len(raw) <= _MAX_PROVENANCE_ITEMS,
        render("recipes.field_max_items", field="provenance", max_len=_MAX_PROVENANCE_ITEMS),
    )
    out: list[dict[str, Any]] = []
    for i, item in enumerate(raw):
        _require(isinstance(item, dict), render("recipes.provenance_item_must_be_object", i=i))
        ref = item.get("ref")
        date = item.get("date")
        _require(
            isinstance(ref, str) and bool(ref) and len(ref) <= _MAX_REF_LEN,
            render("recipes.provenance_ref_invalid", i=i, max_len=_MAX_REF_LEN),
        )
        _require(
            isinstance(date, str) and bool(_DATE_RE.match(date)),
            render("recipes.provenance_date_invalid", i=i, date=repr(date)),
        )
        entry = {"ref": ref, "date": date}
        note = item.get("note")
        if note is not None:
            _require(
                isinstance(note, str) and len(note) <= _MAX_NOTE_LEN,
                render("recipes.provenance_note_too_long", i=i, max_len=_MAX_NOTE_LEN),
            )
            entry["note"] = note
        out.append(entry)
    return out


def _validate_str_list(
    raw: Any, field: str, *, min_len: int = 0, max_len: Optional[int] = None, item_max_len: int = 60
) -> list[str]:
    """自由文本数组（`use_when`/`not_for`）：只限条数与单条长度，不限取值。"""
    values = raw if raw is not None else []
    _require(isinstance(values, list), render("recipes.field_must_be_array", field=field))
    _require(len(values) >= min_len, render("recipes.field_min_items", field=field, min_len=min_len))
    if max_len is not None:
        _require(len(values) <= max_len, render("recipes.field_max_items", field=field, max_len=max_len))
    return [_require_str_len(item, f"{field}[{i}]", item_max_len) for i, item in enumerate(values)]


def _validate_enum_list(raw: Any, field: str, valid: set[str], *, max_len: Optional[int] = None) -> list[str]:
    """取值受限的数组（`inputs`/`backends`）：每项必须在 `valid` 里，条数有上限
    （防止靠重复灌一个巨大数组）。"""
    values = raw if raw is not None else []
    _require(isinstance(values, list), render("recipes.field_must_be_array", field=field))
    if max_len is not None:
        _require(len(values) <= max_len, render("recipes.field_max_items", field=field, max_len=max_len))
    out: list[str] = []
    for i, item in enumerate(values):
        _require(
            isinstance(item, str) and item in valid,
            render("recipes.enum_item_invalid", field=f"{field}[{i}]", value=repr(item)),
        )
        out.append(item)
    return out


def _validate_recipe_json(raw: Any, dirname: str, tools_by_name: dict[str, dict[str, Any]]) -> dict[str, Any]:
    _require(isinstance(raw, dict), render("recipes.recipe_json_must_be_object"))
    _require(
        raw.get("schema") == _SCHEMA_ID,
        render("recipes.schema_field_invalid", schema_id=repr(_SCHEMA_ID), got=repr(raw.get("schema"))),
    )

    rid = raw.get("id")
    _require(isinstance(rid, str) and bool(_ID_RE.match(rid)), render("recipes.id_invalid", id=repr(rid)))
    _require(rid == dirname, render("recipes.id_dirname_mismatch", id=repr(rid), dirname=repr(dirname)))

    version = raw.get("version")
    _require(
        isinstance(version, str) and bool(version) and len(version) <= _MAX_VERSION_LEN,
        render("recipes.version_invalid", max_len=_MAX_VERSION_LEN),
    )

    title = _require_str_len(raw.get("title"), "title", 16)
    goal = _require_str_len(raw.get("goal"), "goal", 60)

    use_when = _validate_str_list(raw.get("use_when"), "use_when", min_len=1, max_len=5, item_max_len=60)
    not_for = _validate_str_list(raw.get("not_for"), "not_for", min_len=0, max_len=5, item_max_len=60)
    inputs = _validate_enum_list(raw.get("inputs"), "inputs", _VALID_INPUTS, max_len=_MAX_INPUTS_ITEMS)
    backends = _validate_enum_list(raw.get("backends"), "backends", _VALID_BACKENDS, max_len=_MAX_BACKENDS_ITEMS)

    steps_raw = raw.get("steps")
    _require(isinstance(steps_raw, list) and len(steps_raw) >= 1, render("recipes.steps_min_items"))
    _require(len(steps_raw) <= _MAX_STEPS, render("recipes.steps_max_items", max_steps=_MAX_STEPS))
    seen_keys: set[str] = set()
    steps = [_validate_step(s, i, seen_keys, tools_by_name) for i, s in enumerate(steps_raw)]

    one_shot = _validate_one_shot(raw.get("one_shot"), tools_by_name)
    provenance = _validate_provenance(raw.get("provenance"))

    author = raw.get("author", "")
    _require(
        isinstance(author, str) and len(author) <= _MAX_AUTHOR_LEN,
        render("recipes.author_too_long", max_len=_MAX_AUTHOR_LEN),
    )
    license_ = raw.get("license", "")
    _require(
        isinstance(license_, str) and len(license_) <= _MAX_LICENSE_LEN,
        render("recipes.license_too_long", max_len=_MAX_LICENSE_LEN),
    )

    workspace = raw.get("workspace", "print")
    _require(workspace in ("print", "edit", "tasks"), render("recipes.workspace_invalid"))
    if workspace == "edit":
        _require(all(s["tool"] == "studio_edit" for s in steps), render("recipes.edit_recipe_only_studio_edit"))
        _require(one_shot is None, render("recipes.edit_recipe_no_one_shot"))
    task_template = raw.get("task_template")
    if workspace == "tasks":
        from studio.core.task_recipe_progress import TEMPLATES, CHECKS

        _require(task_template in TEMPLATES, render("recipes.task_template_unsupported"))
        _require({s["key"] for s in steps} == CHECKS, render("recipes.tasks_recipe_missing_checks"))
        _require(
            all(s["who"] == "you" and not s["optional"] for s in steps),
            render("recipes.tasks_recipe_steps_must_be_required_you"),
        )
        _require(
            all(
                (s["tool"] == "studio_task" and s["args"].get("template") == task_template)
                or (s["tool"] == "studio_observe" and s["key"] == "appearance")
                for s in steps
            ),
            render("recipes.tasks_recipe_tool_template_mismatch"),
        )
        _require(one_shot is None, render("recipes.tasks_recipe_no_one_shot"))
    return {
        "workspace": workspace,
        "task_template": task_template,
        "schema": _SCHEMA_ID,
        "id": rid,
        "version": version,
        "title": title,
        "goal": goal,
        "use_when": use_when,
        "not_for": not_for,
        "inputs": inputs,
        "backends": backends,
        "steps": steps,
        "one_shot": one_shot,
        "provenance": provenance,
        "author": author,
        "license": license_,
    }


# ---------------------------------------------------------------------------
# 目录扫描 / 装载
# ---------------------------------------------------------------------------


def _is_plain_dir(path: Path) -> bool:
    """不跟随符号链接：配方目录本身必须是真目录，不能是指向别处的链接。"""
    return path.is_dir() and not path.is_symlink()


def _is_plain_file(path: Path) -> bool:
    """`recipe.json`/`guide.md` 必须是配方目录内的普通文件，不能是符号链接
    （防止用户目录里的一个链接把内容指到目录之外）。"""
    return path.is_file() and not path.is_symlink()


def _reject_json_constant(name: str) -> Any:
    """喂给 `json.loads(parse_constant=...)`：拒绝 `NaN`/`Infinity`/
    `-Infinity` 这三个 Python `json` 模块能解析、但不是合法 JSON、会让浏览器
    `JSON.parse` 直接失败的记号（SPEC_RECIPES.md §3 小补丁）。"""
    raise _InvalidRecipe(render("recipes.json_constant_not_allowed", name=name))


def _load_one(dir_path: Path, source: str, tools_by_name: dict[str, dict[str, Any]]) -> dict[str, Any]:
    recipe_json_path = dir_path / "recipe.json"
    guide_path = dir_path / "guide.md"

    _require(_is_plain_file(recipe_json_path), render("recipes.recipe_json_missing"))
    try:
        recipe_json_size = recipe_json_path.stat().st_size
    except OSError as exc:
        raise _InvalidRecipe(render("recipes.recipe_json_stat_failed", error=str(exc))) from exc
    _require(
        recipe_json_size <= _MAX_RECIPE_JSON_BYTES,
        render("recipes.recipe_json_too_large", size=recipe_json_size, max_bytes=_MAX_RECIPE_JSON_BYTES),
    )
    try:
        raw_text = recipe_json_path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise _InvalidRecipe(render("recipes.recipe_json_bad_utf8", error=str(exc))) from exc
    except OSError as exc:
        raise _InvalidRecipe(render("recipes.recipe_json_read_failed", error=str(exc))) from exc
    try:
        raw = json.loads(raw_text, parse_constant=_reject_json_constant)
    except json.JSONDecodeError as exc:
        raise _InvalidRecipe(render("recipes.recipe_json_bad_json", error=str(exc))) from exc

    recipe = _validate_recipe_json(raw, dir_path.name, tools_by_name)

    _require(_is_plain_file(guide_path), render("recipes.guide_md_missing"))
    try:
        guide_size = guide_path.stat().st_size
    except OSError as exc:
        raise _InvalidRecipe(render("recipes.guide_md_stat_failed", error=str(exc))) from exc
    _require(
        guide_size <= _MAX_GUIDE_BYTES,
        render("recipes.guide_md_too_large", size=guide_size, max_bytes=_MAX_GUIDE_BYTES),
    )
    try:
        guide_bytes = guide_path.read_bytes()
    except OSError as exc:
        raise _InvalidRecipe(render("recipes.guide_md_read_failed", error=str(exc))) from exc
    try:
        guide_md = guide_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise _InvalidRecipe(render("recipes.guide_md_bad_utf8", error=str(exc))) from exc

    recipe["guide_md"] = guide_md
    recipe["source"] = source
    recipe["content_digest"] = hashlib.sha256((raw_text + "\0" + guide_md).encode()).hexdigest()
    return recipe


def _split_tool(tool: str) -> tuple[str, Optional[str]]:
    """`"studio_edit#plane_cut"` -> `("studio_edit", "plane_cut")`；裸工具名
    -> `(tool, None)`。"""
    base, sep, suffix = tool.partition("#")
    return base, (suffix if sep else None)


def _step_available(tool: str, tools_by_name: dict[str, dict[str, Any]], capability_map: dict[str, set[str]]) -> bool:
    """基础工具必须存在；只有带 `#` 后缀（引用一个细粒度能力）的步骤，还要求
    这个能力名出现在 `capability_map[base_tool]` 里（由
    `studio.core.capabilities.build()` 建）。`capability_map` 里没有这个基础
    工具（没有细粒度命名空间，比如 `studio_load`）不影响裸工具名的步骤——
    那只说明这个工具没有 `#` 形式可用。"""
    base, suffix = _split_tool(tool)
    if base not in tools_by_name:
        return False
    if suffix is None:
        return True
    return suffix in capability_map.get(base, set())


def _step_call(tool: str, task_template_ids: set[str], hosted_ops: set[str]) -> dict[str, Any]:
    """派生的附加字段 `steps[].call`：这一步具体该怎么调，用该工具自己 schema
    里已经在用的键名拼成 `{tool, <key>: <value>}`（studio_edit/studio_motion
    用 `action`，本地 studio_task 模板用 `template`，托管 studio_task 操作用
    `operation`），不发明新键名。裸工具名（没有 `#`）没有更多信息可加。

    一个 `studio_task#<suffix>` 如果同时是某个本地任务模板的 id、又是某个已声明
    服务的托管操作 id，两边该信哪个没有默认答案——静默偏向模板会让配方作者以为在调
    本地确定性工具，实际却可能因为服务目录后来声明了同名操作而在别的环境里被路由成
    托管调用（反之亦然）；这种歧义必须在装载时就暴露成一条 `problems`，不能悄悄选
    一个赢家（`_finalize()` 捕获这里抛出的 `_InvalidRecipe`）。"""
    base, suffix = _split_tool(tool)
    if suffix is None:
        return {"tool": base}
    if base == "studio_task":
        is_template = suffix in task_template_ids
        is_hosted = suffix in hosted_ops
        if is_template and is_hosted:
            raise _InvalidRecipe(render("recipes.step_tool_ambiguous_task_suffix", suffix=suffix))
        return {"tool": base, "template" if is_template else "operation": suffix}
    return {"tool": base, "action": suffix}


def _finalize(
    recipe: dict[str, Any],
    tools_by_name: dict[str, dict[str, Any]],
    capability_map: dict[str, set[str]],
    task_template_ids: set[str],
    hosted_ops: Optional[set[str]] = None,
) -> dict[str, Any]:
    """补 §3.1 的派生字段：`route`/`missing_tools`/`availability`，以及每步
    附加的 `call`（见 `_step_call()`）；一个步骤的 `studio_task#<suffix>` 同时
    撞上本地模板和托管操作时，`_step_call()` 会抛 `_InvalidRecipe`，原样让调用方
    （`load_recipes()`）接住、记成这一条配方的装载失败。

    `hosted_ops` 默认 `None`（当 `set()` 用）：`studio.core.cli.cmd_recipes_check`
    没有托管服务目录可问（层规则，见该函数的文档字符串），直接吃这个默认值，等价
    于"这个 CLI 看不到任何托管操作"这一份已经记在文档里的已知差距，不是本函数
    新增的行为，也不会让那条调用路径意外报出歧义。"""
    hosted_ops = hosted_ops or set()
    route: list[str] = []
    for step in recipe["steps"]:
        if step["row"] not in route:
            route.append(step["row"])

    missing_tools: list[str] = []
    steps_out: list[dict[str, Any]] = []
    for step in recipe["steps"]:
        if not step["optional"] and not _step_available(step["tool"], tools_by_name, capability_map):
            if step["tool"] not in missing_tools:
                missing_tools.append(step["tool"])
        steps_out.append({**step, "call": _step_call(step["tool"], task_template_ids, hosted_ops)})

    out = dict(recipe)
    out["steps"] = steps_out
    out["route"] = route
    out["missing_tools"] = missing_tools
    out["availability"] = "ready" if not missing_tools else "needs_tools"
    return out


def load_recipes(builtin_dir: Path, user_dir: Path) -> dict[str, Any]:
    """扫描内置目录与用户目录，返回
    `{"recipes": [...], "rows": [...], "problems": [...]}`。

    内置目录先读、用户目录后读；`id` 撞了以内置为准，用户那份进 `problems`（不
    影响其它配方装载）。每次调用都重新扫描，不缓存（SPEC_RECIPES.md §3.1）。
    """
    tools_by_name = {t["name"]: t for t in _current_tools()}
    # Read the raw hosted-operations set once here (rather than letting
    # `capabilities.build()` call the provider again on its own) so `_finalize()`
    # can tell a `studio_task#<suffix>` ambiguous between a local template and a
    # hosted operation apart from one that's merely a hosted operation — the
    # union `capabilities.build()` folds them into loses that distinction.
    hosted_ops = set(_hosted_operations_provider()) if _hosted_operations_provider else set()
    capability_map = capabilities.build(tools_by_name, (lambda: hosted_ops) if _hosted_operations_provider else None)
    task_template_ids = capabilities.task_template_ids()
    problems: list[dict[str, Any]] = []
    by_id: dict[str, dict[str, Any]] = {}

    def scan(base: Path, source: str) -> None:
        """一个坏的第三方配方目录（甚至一整个扫不了的目录）绝不能拖垮别的
        配方或整个接口——`MemoryError` 之外的任何 `Exception`（含
        `RecursionError`/`OSError`/`PermissionError`/`UnicodeDecodeError`/
        `ValueError`/我们自己的 `_InvalidRecipe`）都转成一条 `problems`，
        `MemoryError` 才继续往外抛（那是真的资源耗尽，不该被当成"坏配方"吞掉）。"""
        base = Path(base)
        try:
            if not base.is_dir():
                return
            entries = sorted(base.iterdir(), key=lambda p: p.name)
        except MemoryError:
            raise
        except Exception as exc:  # noqa: BLE001 —— 整个目录都扫不了（权限等），记一条就继续
            problems.append(
                {"dir": str(base), "source": source, "error": render("recipes.dir_scan_failed", error=str(exc))}
            )
            return
        for entry in entries:
            if not _is_plain_dir(entry):
                continue  # 非目录（比如 recipes/README.md）或符号链接目录：静默跳过，不是"坏配方"
            try:
                recipe = _load_one(entry, source, tools_by_name)
            except MemoryError:
                raise
            except Exception as exc:  # noqa: BLE001 —— 见函数 docstring
                problems.append({"dir": str(entry), "source": source, "error": f"{type(exc).__name__}: {exc}"})
                continue
            rid = recipe["id"]
            if rid in by_id:
                # 内置先扫完才轮到用户目录，所以撞上时后来者一定是要退让的那份。
                winner_source = by_id[rid]["source"]
                problems.append(
                    {
                        "dir": str(entry),
                        "source": source,
                        "error": render("recipes.id_conflict", id=repr(rid), winner_source=winner_source),
                    }
                )
                continue
            by_id[rid] = recipe

    scan(builtin_dir, "builtin")
    scan(user_dir, "user")

    recipes_out: list[dict[str, Any]] = []
    for r in by_id.values():
        try:
            recipes_out.append(_finalize(r, tools_by_name, capability_map, task_template_ids, hosted_ops))
        except MemoryError:
            raise
        except _InvalidRecipe as exc:
            # Same "one bad recipe can't take the rest down" contract as `scan()`'s
            # per-directory try/except; this one can only fire post-scan (`_finalize()`
            # needs the capability map), so it needs its own problems-list entry here.
            problems.append({"dir": r["id"], "source": r["source"], "error": str(exc)})
    return {
        "recipes": recipes_out,
        "rows": [{**r, "label": render(r["label"])} for r in ROW_TABLE],
        "problems": problems,
    }


def find_recipe(catalog: dict[str, Any], recipe_id: Optional[str]) -> Optional[dict[str, Any]]:
    if not recipe_id:
        return None
    return next((r for r in catalog["recipes"] if r["id"] == recipe_id), None)


def summarize(recipe: dict[str, Any]) -> dict[str, Any]:
    out = {k: recipe[k] for k in _SUMMARY_KEYS}
    out["has_one_shot"] = bool(recipe.get("one_shot"))
    return out


def sorted_summaries(catalog: dict[str, Any]) -> list[dict[str, Any]]:
    """§3.2 的排序：ready 在前；同组内内置在前；再按 id。"""
    summaries = [summarize(r) for r in catalog["recipes"]]
    summaries.sort(
        key=lambda s: (0 if s["availability"] == "ready" else 1, 0 if s["source"] == "builtin" else 1, s["id"])
    )
    return summaries


# ---------------------------------------------------------------------------
# §3.3：配方步骤状态 <- readiness / stale / busy 的纯函数
# ---------------------------------------------------------------------------


def compute_step_status(
    row: str, *, readiness_by_key: dict[str, str], stale_keys: set[str], busy_op: Optional[str]
) -> str:
    """单个 `row` 的状态：面板上还没有的行恒为 `todo`；已有的六行先取
    `readiness.items` 里同名项的状态，命中 `stale` 就升级成 `redo`，`busy.op`
    正在跑的就是它就升级成 `running`（`prepare` 整体运行时不标任何一行）。"""
    if row not in _KNOWN_ROWS:
        return "todo"
    status = readiness_by_key.get(row, "todo")
    stale_step = _ROW_TO_STALE_STEP.get(row)
    if stale_step and stale_step in stale_keys:
        status = "redo"
    if busy_op and busy_op != "prepare" and busy_op in _ROW_TO_BUSY_OPS.get(row, ()):
        status = "running"
    return status


def compute_recipe_view(
    recipe: dict[str, Any],
    *,
    readiness_items: list[dict[str, Any]],
    stale: dict[str, Any],
    busy: Optional[dict[str, Any]],
    print_data: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """把配方的 `steps[]` 跟当前 `readiness`/`stale`/`busy` 拼成
    `{"steps": [...带 status], "next": key_or_None, "done": n, "total": n}`
    （SPEC_RECIPES.md §3.3；`next`/`done`/`total` 只数非 `optional` 的步骤）。"""
    readiness_by_key = {it["key"]: it["status"] for it in readiness_items}
    stale_keys = set(stale or {})
    busy_op = (busy or {}).get("op")

    steps_out: list[dict[str, Any]] = []
    for step in recipe["steps"]:
        status = compute_step_status(
            step["row"], readiness_by_key=readiness_by_key, stale_keys=stale_keys, busy_op=busy_op
        )
        # For a pre-cut route, an oversize but valid mesh is a useful input,
        # not a reason to return to loading forever. Printing readiness remains unchanged.
        if step["row"] == "model" and print_data and any(s["row"] == "split" for s in recipe["steps"]):
            parts = (print_data.get("inspect") or {}).get("parts", [])
            if parts and all(p.get("faces", 0) > 0 and p.get("watertight") for p in parts):
                status = "pass"
        # `call` 是 `_finalize()` 才会补的派生字段（见 `_step_call()`）；直接手搭
        # `recipe["steps"]`（不经过 `load_recipes()`）传进来做单测时可能没有它,
        # 缺了就留 `None`，不强制要求调用方复刻这份派生逻辑。
        view = {k: (step.get(k) if k == "call" else step[k]) for k in _STEP_VIEW_KEYS}
        view["status"] = status
        steps_out.append(view)

    non_optional = [s for s in steps_out if not s["optional"]]
    done = sum(1 for s in non_optional if s["status"] == "pass")
    next_key = next((s["key"] for s in non_optional if s["status"] != "pass"), None)
    return {"steps": steps_out, "next": next_key, "done": done, "total": len(non_optional)}
