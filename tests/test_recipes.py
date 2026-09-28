"""SPEC_RECIPES.md：配方层测试——装载/校验（`studio.core.recipes`）与本机服务接口
（`GET /api/recipes`、`GET /api/recipe`、`POST /api/recipe/use`、
`/api/state.recipe`、三个新工具）。

装载/校验部分直接调 `studio.core.recipes.load_recipes()`，两个目录参数全部指向
`tmp_path` 下的临时目录，不碰真实的 `recipes/`——唯一例外是"内置 `recipes/`
下每个配方都能装载"那一条，它专门验证仓库里当前那份内置目录；里面还没有任何
配方子目录时（别人可能还在并行写）就 `skip`，不 `fail`。

接口部分沿用 `test_studio_v05.py` 的写法：`create_httpd()` 在进程内起一个绑定
随机端口的实例，`PRINT_PREP_HOME` 指到临时目录；用配方时统一把测试配方放进
`<PRINT_PREP_HOME>/recipes/<id>/`（也就是"用户目录"），同样不碰仓库内置目录，
足够测完 GET/POST 的全部行为（可用性、启用/停用、幂等、history、
`state.recipe`、持久化、鉴权）。
"""

from __future__ import annotations

import http.client
import json
import os
import shutil
import sys
import threading
import time
from pathlib import Path
from typing import Any, Optional

import pytest

from .conftest import write_box_stl

from studio.core import recipes
from studio.shell.server import StudioBackend
from tests.helpers import Client


# ===========================================================================
# 装载 / 校验（`studio.core.recipes.load_recipes`），全部用临时目录
# ===========================================================================


def _good_step(**overrides: Any) -> dict[str, Any]:
    step = {
        "key": "load",
        "row": "model",
        "tool": "studio_load",
        "who": "either",
        "args": {},
        "decide": "尺寸单位对不对。",
        "accept": "readiness 里 model 为 pass。",
        "optional": False,
    }
    step.update(overrides)
    return step


def _base() -> dict[str, Any]:
    """一份能通过全部校验的最小配方；每次调用都是全新的 dict，测试可以随便改。"""
    return {
        "schema": "print-prep.recipe/1",
        "id": "demo-kit",
        "version": "0.1.0",
        "title": "示例配方",
        "goal": "示例：从载入到选朝向走一遍。",
        "use_when": ["示例场景一"],
        "not_for": [],
        "inputs": ["mesh_set"],
        "backends": [],
        "steps": [
            _good_step(
                key="load",
                row="model",
                tool="studio_load",
                who="either",
                decide="尺寸单位对不对。",
                accept="readiness 里 model 为 pass。",
            ),
            _good_step(
                key="orient",
                row="orient",
                tool="studio_orient",
                who="ai",
                decide="选哪种朝向策略。",
                accept="readiness 里 orient 为 pass。",
            ),
        ],
        "one_shot": None,
        "provenance": [{"ref": "fdm_preprint/demo", "date": "2026-09-21", "note": "测试用"}],
        "author": "print-prep",
        "license": "同仓库",
    }


def _write_recipe(base_dir: Path, dirname: str, data: dict[str, Any], guide: str = "guide text") -> Path:
    d = base_dir / dirname
    d.mkdir(parents=True, exist_ok=True)
    (d / "recipe.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    (d / "guide.md").write_text(guide, encoding="utf-8")
    return d


def _assert_rejected(
    tmp_path: Path, data: dict[str, Any], *, dirname: Optional[str] = None, guide: str = "guide text"
) -> dict[str, Any]:
    rid = dirname or data.get("id") or "demo-kit"
    _write_recipe(tmp_path / "builtin", rid, data=data, guide=guide)
    catalog = recipes.load_recipes(tmp_path / "builtin", tmp_path / "user")
    assert catalog["recipes"] == [], f"应该被拒绝的配方却装载成功: {data!r}"
    assert len(catalog["problems"]) == 1, catalog["problems"]
    return catalog["problems"][0]


def test_a_valid_recipe_loads_with_derived_fields(tmp_path):
    _write_recipe(tmp_path / "builtin", "demo-kit", data=_base())
    catalog = recipes.load_recipes(tmp_path / "builtin", tmp_path / "user")
    assert catalog["problems"] == []
    assert len(catalog["recipes"]) == 1
    r = catalog["recipes"][0]
    assert r["id"] == "demo-kit"
    assert r["source"] == "builtin"
    assert r["route"] == ["model", "orient"]
    assert r["missing_tools"] == []
    assert r["availability"] == "ready"
    assert r["guide_md"] == "guide text"
    assert len(catalog["rows"]) == 22
    assert {row["key"] for row in catalog["rows"]} == set(recipes.ROW_KEYS)


def test_missing_directories_are_fine(tmp_path):
    catalog = recipes.load_recipes(tmp_path / "no-such-builtin", tmp_path / "no-such-user")
    assert catalog["recipes"] == []
    assert catalog["problems"] == []
    assert len(catalog["rows"]) == 22


def test_non_directory_entries_in_recipes_dir_are_ignored(tmp_path):
    builtin = tmp_path / "builtin"
    builtin.mkdir()
    (builtin / "README.md").write_text("# not a recipe", encoding="utf-8")
    catalog = recipes.load_recipes(builtin, tmp_path / "user")
    assert catalog["recipes"] == []
    assert catalog["problems"] == []


def test_missing_recipe_json_rejected(tmp_path):
    d = tmp_path / "builtin" / "demo-kit"
    d.mkdir(parents=True)
    (d / "guide.md").write_text("guide", encoding="utf-8")
    catalog = recipes.load_recipes(tmp_path / "builtin", tmp_path / "user")
    assert catalog["recipes"] == []
    assert len(catalog["problems"]) == 1


def test_invalid_json_rejected(tmp_path):
    d = tmp_path / "builtin" / "demo-kit"
    d.mkdir(parents=True)
    (d / "recipe.json").write_text("{not json", encoding="utf-8")
    (d / "guide.md").write_text("guide", encoding="utf-8")
    catalog = recipes.load_recipes(tmp_path / "builtin", tmp_path / "user")
    assert catalog["recipes"] == []
    assert len(catalog["problems"]) == 1


def test_missing_guide_md_rejected(tmp_path):
    d = tmp_path / "builtin" / "demo-kit"
    d.mkdir(parents=True)
    (d / "recipe.json").write_text(json.dumps(_base(), ensure_ascii=False), encoding="utf-8")
    catalog = recipes.load_recipes(tmp_path / "builtin", tmp_path / "user")
    assert catalog["recipes"] == []
    assert len(catalog["problems"]) == 1


def test_guide_md_size_limit(tmp_path):
    _write_recipe(tmp_path / "builtin", "demo-kit", data=_base(), guide="x" * 8193)
    catalog = recipes.load_recipes(tmp_path / "builtin", tmp_path / "user")
    assert catalog["recipes"] == []
    assert len(catalog["problems"]) == 1


def test_recipe_json_size_limit_rejected_without_reading_content(tmp_path):
    """§4：`recipe.json` 先 `stat` 再读，> 64 KB 直接进 `problems`、不读内容。"""
    d = tmp_path / "builtin" / "demo-kit"
    d.mkdir(parents=True)
    # 塞一个真的能通过 JSON 解析（否则测的是 JSON 校验而不是大小校验）但超过
    # 64 KB 的 recipe.json：用一条很长的 use_when 项把体积撑大。
    data = _base()
    data["use_when"] = ["x" * 60]
    padded = json.dumps(data, ensure_ascii=False)
    assert len(padded.encode("utf-8")) < 65536
    d_json = d / "recipe.json"
    # 直接写一个 65536+ 字节、仍是合法 JSON 顶层对象的文件：在最后一个键后面
    # 塞一段会被官方 schema 忽略、但撑体积用的超长字符串值。
    oversized_obj = dict(data)
    oversized_obj["_padding_for_size_test"] = "x" * (70000 - len(padded))
    (d_json).write_text(json.dumps(oversized_obj, ensure_ascii=False), encoding="utf-8")
    assert d_json.stat().st_size > 65536
    (d / "guide.md").write_text("guide", encoding="utf-8")

    catalog = recipes.load_recipes(tmp_path / "builtin", tmp_path / "user")
    assert catalog["recipes"] == []
    assert len(catalog["problems"]) == 1
    assert "64" in catalog["problems"][0]["error"] or "recipe.json" in catalog["problems"][0]["error"]


# --------------------------------------------------------------------- 顶层字段


def test_schema_field_must_match(tmp_path):
    data = _base()
    data["schema"] = "print-prep.recipe/2"
    _assert_rejected(tmp_path, data)


def test_id_pattern_invalid(tmp_path):
    data = _base()
    data["id"] = "Bad_ID"
    _assert_rejected(tmp_path, data, dirname="Bad_ID")


def test_id_must_match_directory_name(tmp_path):
    data = _base()  # id == "demo-kit"
    _assert_rejected(tmp_path, data, dirname="different-dir-name")


def test_version_must_be_nonempty_string(tmp_path):
    data = _base()
    data["version"] = ""
    _assert_rejected(tmp_path, data)


def test_version_length_limit(tmp_path):
    data = _base()
    data["version"] = "0." + "1" * 20  # 22 个字符，超过 20
    _assert_rejected(tmp_path, data)


def test_author_length_limit(tmp_path):
    data = _base()
    data["author"] = "x" * 61
    _assert_rejected(tmp_path, data)


def test_license_length_limit(tmp_path):
    data = _base()
    data["license"] = "x" * 61
    _assert_rejected(tmp_path, data)


def test_title_must_not_be_empty(tmp_path):
    data = _base()
    data["title"] = ""
    _assert_rejected(tmp_path, data)


def test_title_length_limit(tmp_path):
    data = _base()
    data["title"] = "一二三四五六七八九十一二三四五六七"  # 17 个字符，超过 16
    _assert_rejected(tmp_path, data)


def test_goal_length_limit(tmp_path):
    data = _base()
    data["goal"] = "x" * 61
    _assert_rejected(tmp_path, data)


def test_use_when_must_have_at_least_one(tmp_path):
    data = _base()
    data["use_when"] = []
    _assert_rejected(tmp_path, data)


def test_use_when_max_five(tmp_path):
    data = _base()
    data["use_when"] = [f"场景{i}" for i in range(6)]
    _assert_rejected(tmp_path, data)


def test_use_when_item_length_limit(tmp_path):
    data = _base()
    data["use_when"] = ["x" * 61]
    _assert_rejected(tmp_path, data)


def test_not_for_max_five(tmp_path):
    data = _base()
    data["not_for"] = [f"场景{i}" for i in range(6)]
    _assert_rejected(tmp_path, data)


def test_inputs_enum_invalid_value(tmp_path):
    data = _base()
    data["inputs"] = ["not_a_real_input_type"]
    _assert_rejected(tmp_path, data)


def test_backends_enum_invalid_value(tmp_path):
    data = _base()
    data["backends"] = ["not_a_real_backend"]
    _assert_rejected(tmp_path, data)


def test_inputs_count_limit(tmp_path):
    data = _base()
    data["inputs"] = ["mesh"] * 11  # 上限 10
    _assert_rejected(tmp_path, data)


def test_backends_count_limit(tmp_path):
    data = _base()
    data["backends"] = ["llm"] * 11  # 上限 10
    _assert_rejected(tmp_path, data)


# --------------------------------------------------------------------- steps


def test_steps_must_have_at_least_one(tmp_path):
    data = _base()
    data["steps"] = []
    _assert_rejected(tmp_path, data)


def test_steps_count_limit(tmp_path):
    data = _base()
    data["steps"] = [_good_step(key=f"s{i}", row="model", tool="studio_load") for i in range(25)]  # 上限 24
    _assert_rejected(tmp_path, data)


def test_step_key_pattern_invalid(tmp_path):
    data = _base()
    data["steps"][0]["key"] = "Bad Key!"
    _assert_rejected(tmp_path, data)


def test_step_key_duplicate(tmp_path):
    data = _base()
    data["steps"].append(dict(data["steps"][0]))
    _assert_rejected(tmp_path, data)


def test_step_row_invalid(tmp_path):
    data = _base()
    data["steps"][0]["row"] = "not_a_row"
    _assert_rejected(tmp_path, data)


def test_step_tool_must_be_nonempty_string(tmp_path):
    data = _base()
    data["steps"][0]["tool"] = ""
    _assert_rejected(tmp_path, data)


def test_step_who_invalid(tmp_path):
    data = _base()
    data["steps"][0]["who"] = "robot"
    _assert_rejected(tmp_path, data)


def test_step_decide_length_limit(tmp_path):
    data = _base()
    data["steps"][0]["decide"] = "x" * 81
    _assert_rejected(tmp_path, data)


def test_step_accept_length_limit(tmp_path):
    data = _base()
    data["steps"][0]["accept"] = "x" * 81
    _assert_rejected(tmp_path, data)


def test_step_optional_must_be_bool(tmp_path):
    data = _base()
    data["steps"][0]["optional"] = "yes"
    _assert_rejected(tmp_path, data)


def test_route_dedupes_rows_in_order(tmp_path):
    data = _base()
    data["steps"] = [
        _good_step(key="s1", row="model", tool="studio_load"),
        _good_step(key="s2", row="orient", tool="studio_orient"),
        _good_step(key="s3", row="model", tool="studio_load"),
    ]
    _write_recipe(tmp_path / "builtin", "demo-kit", data=data)
    catalog = recipes.load_recipes(tmp_path / "builtin", tmp_path / "user")
    assert catalog["problems"] == []
    assert catalog["recipes"][0]["route"] == ["model", "orient"]


def test_missing_tool_marks_needs_tools_but_still_loads(tmp_path):
    data = _base()
    data["steps"].append(
        {
            "key": "split",
            "row": "split",
            "tool": "studio_split",
            "who": "ai",
            "args": {},
            "decide": "怎么切。",
            "accept": "件数对。",
            "optional": False,
        }
    )
    _write_recipe(tmp_path / "builtin", "demo-kit", data=data)
    catalog = recipes.load_recipes(tmp_path / "builtin", tmp_path / "user")
    assert catalog["problems"] == []
    assert len(catalog["recipes"]) == 1
    r = catalog["recipes"][0]
    assert r["availability"] == "needs_tools"
    assert r["missing_tools"] == ["studio_split"]
    assert "split" in r["route"]


def test_optional_step_missing_tool_does_not_block_availability(tmp_path):
    data = _base()
    data["steps"].append(
        {
            "key": "split",
            "row": "split",
            "tool": "studio_split",
            "who": "ai",
            "args": {},
            "decide": "怎么切。",
            "accept": "件数对。",
            "optional": True,
        }
    )
    _write_recipe(tmp_path / "builtin", "demo-kit", data=data)
    catalog = recipes.load_recipes(tmp_path / "builtin", tmp_path / "user")
    r = catalog["recipes"][0]
    assert r["availability"] == "ready"
    assert r["missing_tools"] == []


# --------------------------------------------------------------------- `tool#action` 语法


def test_step_tool_accepts_hash_action_suffix_for_a_real_capability(tmp_path):
    """`studio_edit` 是真实工具，`repair` 是 `editor_actions.ACTIONS` 里真实
    存在的动作——`tool#action` 形式应该跟裸 `studio_edit` 一样判定为可用，
    并且额外带上按这个 action 派生出的 `call`。"""
    data = _base()
    data["steps"][1] = _good_step(key="fix", row="repair_mesh", tool="studio_edit#repair", args={"action": "repair"})
    _write_recipe(tmp_path / "builtin", "demo-kit", data=data)
    catalog = recipes.load_recipes(tmp_path / "builtin", tmp_path / "user")
    assert catalog["problems"] == []
    r = catalog["recipes"][0]
    assert r["availability"] == "ready"
    assert r["missing_tools"] == []
    step = next(s for s in r["steps"] if s["key"] == "fix")
    assert step["tool"] == "studio_edit#repair"
    assert step["call"] == {"tool": "studio_edit", "action": "repair"}


def test_step_tool_hash_suffix_must_agree_with_args(tmp_path):
    """`studio_edit#repair` 配 `args.action: simplify` 是自相矛盾的配方：可用性按
    后缀算、真正调用按 args 走。这种要在装载时拒绝，而不是留给运行期各说各话。"""
    data = _base()
    data["steps"][1] = _good_step(key="fix", row="repair_mesh", tool="studio_edit#repair", args={"action": "simplify"})
    _assert_rejected(tmp_path, data)


def test_step_tool_hash_suffix_not_in_capability_map_is_missing(tmp_path):
    """`studio_edit` 真实存在，但 `editor_actions.ACTIONS` 里没有名叫
    `not_a_real_action` 的动作——即使基础工具都在，细粒度能力查不到也要算
    「缺能力」，不能只看基础工具存不存在。"""
    data = _base()
    # 用 studio_task：它的 args.action 是任务动作（start），不参与后缀比对；后缀指向一个
    # 不存在的模板，只应影响可用性判定，不应拒绝装载。
    data["steps"][1] = _good_step(
        key="fix", row="repair_mesh", tool="studio_task#not-a-real-template", args={"action": "start"}
    )
    _write_recipe(tmp_path / "builtin", "demo-kit", data=data)
    catalog = recipes.load_recipes(tmp_path / "builtin", tmp_path / "user")
    r = catalog["recipes"][0]
    assert r["availability"] == "needs_tools"
    assert r["missing_tools"] == ["studio_task#not-a-real-template"]


def test_step_tool_hash_suffix_with_no_capability_map_entry_at_all_is_missing(tmp_path):
    """`studio_load` 是真实工具，但它没有任何细粒度命名空间（不在
    `capabilities.build()` 的结果里）——给它加一个 `#` 后缀应该判定为缺能力，
    不能因为 capability_map 里压根没有这个基础工具的条目就默认放行。"""
    data = _base()
    data["steps"][0] = _good_step(tool="studio_load#anything")
    _write_recipe(tmp_path / "builtin", "demo-kit", data=data)
    catalog = recipes.load_recipes(tmp_path / "builtin", tmp_path / "user")
    r = catalog["recipes"][0]
    assert r["availability"] == "needs_tools"
    assert r["missing_tools"] == ["studio_load#anything"]


def test_step_tool_hash_suffix_for_hosted_task_operation_is_ready_with_operation_call(tmp_path):
    """`studio_task#image-to-3d`：`image-to-3d` 不是本地任务模板，是某个托管
    服务声明过的操作 id（见 `studio.shell.server._hosted_task_operations`，
    module import 时已经通过 `recipes.configure()` 注入）——应该判定可用，
    且 `call` 用 `operation` 这个键，不是 `template`。"""
    data = _base()
    data["steps"][1] = _good_step(
        key="generate", row="source", tool="studio_task#image-to-3d", who="either", args={"action": "start"}
    )
    _write_recipe(tmp_path / "builtin", "demo-kit", data=data)
    catalog = recipes.load_recipes(tmp_path / "builtin", tmp_path / "user")
    r = catalog["recipes"][0]
    assert r["availability"] == "ready", r["missing_tools"]
    step = next(s for s in r["steps"] if s["key"] == "generate")
    assert step["call"] == {"tool": "studio_task", "operation": "image-to-3d"}


def test_step_tool_hash_suffix_ambiguous_between_local_template_and_hosted_operation_is_rejected(tmp_path, monkeypatch):
    """`studio_task#<suffix>` 同时是一个本地任务模板的 id（`joint-coupon`，见
    `task_operations.CATALOG`）又是某个服务目录声明过的托管操作 id 时，谁该赢
    没有默认答案——`_step_call()` 必须整条配方一起拒绝装载，不能悄悄偏向模板。"""
    monkeypatch.setattr(recipes, "_hosted_operations_provider", lambda: {"joint-coupon"})
    data = _base()
    data["steps"][1] = _good_step(
        key="fix", row="repair_mesh", tool="studio_task#joint-coupon", args={"action": "start"}
    )
    problem = _assert_rejected(tmp_path, data)
    assert "joint-coupon" in problem["error"]


@pytest.mark.parametrize(
    "tool",
    [
        "",
        "studio_edit#",
        "studio_edit#Repair",
        "studio_edit#re pair",
        "not_studio_edit",
        "studio_",
    ],
)
def test_step_tool_grammar_rejects_malformed_strings(tmp_path, tool):
    data = _base()
    data["steps"][0]["tool"] = tool
    _assert_rejected(tmp_path, data)


def test_args_validated_against_base_tool_for_suffixed_tool(tmp_path):
    """`steps[].args` 的键名校验要认 `#` 之前那半（真实工具）的 schema，不是
    整个 `tool#action` 字符串——`studio_edit` 的 `inputSchema` 里没有
    `totally_unknown_key`，带没带后缀都一样拒。"""
    data = _base()
    data["steps"][1] = _good_step(
        key="fix",
        row="repair_mesh",
        tool="studio_edit#repair",
        args={"action": "repair", "totally_unknown_key": 1},
    )
    _assert_rejected(tmp_path, data)


def test_all_builtin_recipes_missing_tools_are_only_genuinely_missing(tmp_path):
    """真的内置 `recipes/` 目录，配合真的工具表与 `studio.core.capabilities`
    能力表：配方步骤必须绑定已实现的本地任务或显式托管能力。
    工具绑定可用不代表任意输入、完整自动执行或实物成品已验收。"""
    if not recipes.BUILTIN_RECIPES_DIR.is_dir():
        pytest.skip("recipes/ 目录还不存在")
    subdirs = [p for p in recipes.BUILTIN_RECIPES_DIR.iterdir() if p.is_dir() and not p.is_symlink()]
    if not subdirs:
        pytest.skip("recipes/ 下还没有任何配方子目录")
    genuinely_missing = set()
    import tempfile

    with tempfile.TemporaryDirectory() as empty_user:
        catalog = recipes.load_recipes(recipes.BUILTIN_RECIPES_DIR, Path(empty_user))
    assert catalog["problems"] == []
    all_missing = {name for r in catalog["recipes"] for name in r["missing_tools"]}
    assert all_missing <= genuinely_missing, all_missing - genuinely_missing


# --------------------------------------------------------------------- args 的限制


def test_args_key_must_be_known_to_tool_schema(tmp_path):
    data = _base()
    data["steps"][1]["args"] = {"totally_unknown_key": 1}
    _assert_rejected(tmp_path, data)


def test_args_forbid_path_like_keys_even_with_additional_properties_tool(tmp_path):
    data = _base()
    data["steps"][0]["tool"] = "studio_prepare"  # additionalProperties: true，跳过键名检查
    data["steps"][0]["args"] = {"path": "/etc/passwd"}
    _assert_rejected(tmp_path, data)


def test_args_forbid_path_like_keys_nested_one_level(tmp_path):
    data = _base()
    data["steps"][1]["args"] = {"set": {"job": "foo"}}  # "set" 合法，但里面的 "job" 是路径类键
    _assert_rejected(tmp_path, data)


def test_args_value_array_must_contain_scalars(tmp_path):
    data = _base()
    data["steps"][0]["tool"] = "studio_prepare"
    data["steps"][0]["args"] = {"weird": [{"a": 1}]}
    _assert_rejected(tmp_path, data)


def test_args_value_dict_can_only_be_one_level(tmp_path):
    data = _base()
    data["steps"][1]["args"] = {"set": {"nested": {"too": "deep"}}}
    _assert_rejected(tmp_path, data)


def test_args_size_limit(tmp_path):
    data = _base()
    data["steps"][0]["tool"] = "studio_prepare"
    data["steps"][0]["args"] = {"note": "x" * 3000}
    _assert_rejected(tmp_path, data)


def test_args_forbid_all_true_for_send_to_bambu(tmp_path):
    data = _base()
    data["steps"][0]["tool"] = "studio_send_to_bambu"
    data["steps"][0]["row"] = "deliver"
    data["steps"][0]["who"] = "you"
    data["steps"][0]["args"] = {"all": True}
    _assert_rejected(tmp_path, data)


@pytest.mark.parametrize("value", [1, "yes", "true", 1.0])
def test_args_forbid_all_non_bool_truthy_for_send_to_bambu(tmp_path, value):
    """盲审 2：以前用 `is not True` 判断，`"all": 1`/`"all": "yes"` 这类非布尔
    真值能绕过去，但消费端是 `bool(body.get("all"))`——一样会打开全部盘。"""
    data = _base()
    data["steps"][0]["tool"] = "studio_send_to_bambu"
    data["steps"][0]["row"] = "deliver"
    data["steps"][0]["who"] = "you"
    data["steps"][0]["args"] = {"all": value}
    _assert_rejected(tmp_path, data)


def test_args_all_false_is_allowed_for_send_to_bambu(tmp_path):
    data = _base()
    data["steps"][0]["tool"] = "studio_send_to_bambu"
    data["steps"][0]["row"] = "deliver"
    data["steps"][0]["who"] = "you"
    data["steps"][0]["args"] = {"all": False}
    _write_recipe(tmp_path / "builtin", "demo-kit", data=data)
    catalog = recipes.load_recipes(tmp_path / "builtin", tmp_path / "user")
    assert catalog["problems"] == []


@pytest.mark.parametrize("key", ["merge", "no_project", "check", "dry_run"])
@pytest.mark.parametrize("value", [1, 0, "true", "false", "yes"])
def test_boolean_semantic_arg_keys_reject_non_bool_values(tmp_path, key, value):
    """盲审 2：`merge`/`no_project`/`check`/`dry_run` 这几个布尔语义的键只接受
    JSON 布尔类型，`1`/`0`/字符串都要拒绝（哪怕数值上"看起来"对）。"""
    data = _base()
    data["steps"][0]["tool"] = "studio_prepare"
    data["steps"][0]["args"] = {key: value}
    _assert_rejected(tmp_path, data)


def test_boolean_semantic_arg_keys_accept_real_bools(tmp_path):
    data = _base()
    data["steps"][0]["tool"] = "studio_prepare"
    data["steps"][0]["args"] = {"merge": True, "no_project": False, "check": True, "dry_run": False}
    _write_recipe(tmp_path / "builtin", "demo-kit", data=data)
    catalog = recipes.load_recipes(tmp_path / "builtin", tmp_path / "user")
    assert catalog["problems"] == []


def test_one_shot_tool_must_be_prepare(tmp_path):
    data = _base()
    data["one_shot"] = {"tool": "studio_orient", "args": {}}
    _assert_rejected(tmp_path, data)


def test_one_shot_forbids_send_true(tmp_path):
    data = _base()
    data["one_shot"] = {"tool": "studio_prepare", "args": {"send": True}}
    _assert_rejected(tmp_path, data)


@pytest.mark.parametrize("value", [1, "yes", "true", 1.0])
def test_one_shot_forbids_send_non_bool_truthy(tmp_path, value):
    """盲审 2：同 all，`"send": 1`/`"send": "yes"` 以前能绕过 `is not True`。"""
    data = _base()
    data["one_shot"] = {"tool": "studio_prepare", "args": {"send": value}}
    _assert_rejected(tmp_path, data)


def test_one_shot_send_false_is_allowed(tmp_path):
    data = _base()
    data["one_shot"] = {"tool": "studio_prepare", "args": {"send": False}}
    _write_recipe(tmp_path / "builtin", "demo-kit", data=data)
    catalog = recipes.load_recipes(tmp_path / "builtin", tmp_path / "user")
    assert catalog["problems"] == []


def test_one_shot_valid_is_kept(tmp_path):
    data = _base()
    data["one_shot"] = {"tool": "studio_prepare", "args": {"shape": "generic"}}
    _write_recipe(tmp_path / "builtin", "demo-kit", data=data)
    catalog = recipes.load_recipes(tmp_path / "builtin", tmp_path / "user")
    assert catalog["problems"] == []
    r = catalog["recipes"][0]
    assert r["one_shot"] == {"tool": "studio_prepare", "args": {"shape": "generic"}}
    assert recipes.summarize(r)["has_one_shot"] is True


# --------------------------------------------------------------------- NaN/Infinity（盲审 3）


@pytest.mark.parametrize("token", ["NaN", "Infinity", "-Infinity"])
def test_recipe_json_rejects_out_of_range_json_constants(tmp_path, token):
    """§3(a)：`json.loads(parse_constant=...)` 在装载时直接拒绝这三个 Python
    `json` 能解析、但不是合法 JSON 的记号——它们穿到响应体里会让浏览器
    `JSON.parse` 失败，面板整块变空且不报错。"""
    d = tmp_path / "builtin" / "demo-kit"
    d.mkdir(parents=True)
    raw = json.dumps(_base(), ensure_ascii=False)
    injected = raw[:-1] + f', "_extra_number_for_test": {token}}}'
    (d / "recipe.json").write_text(injected, encoding="utf-8")
    (d / "guide.md").write_text("guide", encoding="utf-8")

    catalog = recipes.load_recipes(tmp_path / "builtin", tmp_path / "user")
    assert catalog["recipes"] == []
    assert len(catalog["problems"]) == 1


def test_validate_arg_value_shape_rejects_non_finite_floats():
    """§3(b)：校验 `args` 值的函数级独立防线——即便不经过 JSON 文本解析，直接
    传一个 Python 的非有限浮点数也要被拒绝（防的是万一将来有别的调用路径不
    经过 `json.loads`）。"""
    with pytest.raises(recipes._InvalidRecipe):
        recipes._validate_arg_value_shape(float("nan"), "steps[0].args.x")
    with pytest.raises(recipes._InvalidRecipe):
        recipes._validate_arg_value_shape(float("inf"), "steps[0].args.x")
    with pytest.raises(recipes._InvalidRecipe):
        recipes._validate_arg_value_shape(float("-inf"), "steps[0].args.x")
    with pytest.raises(recipes._InvalidRecipe):
        recipes._validate_arg_value_shape([1, float("nan")], "steps[0].args.x")
    with pytest.raises(recipes._InvalidRecipe):
        recipes._validate_arg_value_shape({"a": float("inf")}, "steps[0].args.x")
    recipes._validate_arg_value_shape(1.5, "steps[0].args.x")  # 有限浮点数不该被拒绝


# --------------------------------------------------------------------- provenance / author / license


def test_provenance_required_nonempty(tmp_path):
    data = _base()
    data["provenance"] = []
    _assert_rejected(tmp_path, data)


def test_provenance_entry_requires_ref_and_date(tmp_path):
    data = _base()
    data["provenance"] = [{"ref": "x"}]  # 缺 date
    _assert_rejected(tmp_path, data)


def test_provenance_count_limit(tmp_path):
    data = _base()
    data["provenance"] = [{"ref": f"fdm_preprint/demo{i}", "date": "2026-09-21"} for i in range(9)]  # 上限 8
    _assert_rejected(tmp_path, data)


def test_provenance_ref_length_limit(tmp_path):
    data = _base()
    data["provenance"] = [{"ref": "x" * 121, "date": "2026-09-21"}]
    _assert_rejected(tmp_path, data)


def test_provenance_date_must_be_iso_format(tmp_path):
    data = _base()
    data["provenance"] = [{"ref": "fdm_preprint/demo", "date": "2026/09/21"}]
    _assert_rejected(tmp_path, data)


def test_provenance_note_length_limit(tmp_path):
    data = _base()
    data["provenance"] = [{"ref": "fdm_preprint/demo", "date": "2026-09-21", "note": "x" * 121}]
    _assert_rejected(tmp_path, data)


def test_provenance_note_within_limit_is_kept(tmp_path):
    data = _base()
    data["provenance"] = [{"ref": "fdm_preprint/demo", "date": "2026-09-21", "note": "x" * 120}]
    _write_recipe(tmp_path / "builtin", "demo-kit", data=data)
    catalog = recipes.load_recipes(tmp_path / "builtin", tmp_path / "user")
    assert catalog["problems"] == []
    assert catalog["recipes"][0]["provenance"][0]["note"] == "x" * 120


# --------------------------------------------------------------------- 用户目录 / id 冲突


def test_user_recipe_id_conflict_with_builtin_goes_to_problems(tmp_path):
    _write_recipe(tmp_path / "builtin", "demo-kit", data=_base())
    conflicting = _base()
    conflicting["title"] = "冒充的"
    _write_recipe(tmp_path / "user", "demo-kit", data=conflicting)

    catalog = recipes.load_recipes(tmp_path / "builtin", tmp_path / "user")
    assert len(catalog["recipes"]) == 1
    assert catalog["recipes"][0]["source"] == "builtin"
    assert catalog["recipes"][0]["title"] != "冒充的"
    assert len(catalog["problems"]) == 1
    assert catalog["problems"][0]["source"] == "user"


def test_user_only_recipe_loads_with_user_source(tmp_path):
    other = _base()
    other["id"] = "user-kit"
    _write_recipe(tmp_path / "user", "user-kit", data=other)
    catalog = recipes.load_recipes(tmp_path / "builtin", tmp_path / "user")
    assert catalog["problems"] == []
    assert len(catalog["recipes"]) == 1
    assert catalog["recipes"][0]["source"] == "user"


def test_symlinked_recipe_directory_is_silently_skipped(tmp_path):
    """配方目录本身是符号链接：不当"坏配方"报出来，静默跳过（跟非目录条目一
    样），不跟随到目录之外。"""
    real_dir = tmp_path / "real-demo"
    _write_recipe(tmp_path, "real-demo", data=_base())
    user_dir = tmp_path / "user"
    user_dir.mkdir()
    (user_dir / "demo-kit").symlink_to(real_dir, target_is_directory=True)

    catalog = recipes.load_recipes(tmp_path / "empty-builtin", user_dir)
    assert catalog["recipes"] == []
    assert catalog["problems"] == []


def test_symlinked_recipe_json_is_rejected(tmp_path):
    """配方目录是真目录，但 `recipe.json` 是指向目录外的符号链接：拒绝并报
    problem（跟"缺文件"同一条路径）。"""
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.json").write_text(json.dumps(_base(), ensure_ascii=False), encoding="utf-8")
    user_dir = tmp_path / "user"
    d = user_dir / "demo-kit"
    d.mkdir(parents=True)
    (d / "recipe.json").symlink_to(outside / "secret.json")
    (d / "guide.md").write_text("guide", encoding="utf-8")

    catalog = recipes.load_recipes(tmp_path / "empty-builtin", user_dir)
    assert catalog["recipes"] == []
    assert len(catalog["problems"]) == 1
    assert catalog["problems"][0]["source"] == "user"


# --------------------------------------------------------------------- summarize / 排序


def test_summarize_fields_match_spec(tmp_path):
    _write_recipe(tmp_path / "builtin", "demo-kit", data=_base())
    catalog = recipes.load_recipes(tmp_path / "builtin", tmp_path / "user")
    summary = recipes.summarize(catalog["recipes"][0])
    assert set(summary) == {
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
        "has_one_shot",
        "provenance",
        "workspace",
        "task_template",
    }


def test_sorted_summaries_orders_ready_before_needs_tools_then_builtin_before_user_then_id(tmp_path):
    ready_builtin = _base()
    ready_builtin["id"] = "zzz-ready"
    _write_recipe(tmp_path / "builtin", "zzz-ready", data=ready_builtin)

    needs = _base()
    needs["id"] = "aaa-needs"
    needs["steps"].append(
        {
            "key": "split",
            "row": "split",
            "tool": "studio_split",
            "who": "ai",
            "args": {},
            "decide": "x",
            "accept": "y",
            "optional": False,
        }
    )
    _write_recipe(tmp_path / "builtin", "aaa-needs", data=needs)

    ready_user = _base()
    ready_user["id"] = "aaa-ready-user"
    _write_recipe(tmp_path / "user", "aaa-ready-user", data=ready_user)

    catalog = recipes.load_recipes(tmp_path / "builtin", tmp_path / "user")
    ids = [s["id"] for s in recipes.sorted_summaries(catalog)]
    assert ids == ["zzz-ready", "aaa-ready-user", "aaa-needs"]


def test_all_builtin_recipes_load_with_no_problems():
    """真的内置 `recipes/` 目录：如果现在一个配方子目录都没有（别人还在并行
    写），就跳过——这不是"没有配方"的失败，是"还没有人交"的中性状态。"""
    if not recipes.BUILTIN_RECIPES_DIR.is_dir():
        pytest.skip("recipes/ 目录还不存在")
    subdirs = [p for p in recipes.BUILTIN_RECIPES_DIR.iterdir() if p.is_dir() and not p.is_symlink()]
    if not subdirs:
        pytest.skip("recipes/ 下还没有任何配方子目录")
    import tempfile

    with tempfile.TemporaryDirectory() as empty_user:
        catalog = recipes.load_recipes(recipes.BUILTIN_RECIPES_DIR, Path(empty_user))
    assert catalog["problems"] == [], catalog["problems"]
    assert len(catalog["recipes"]) == len(subdirs)


# --------------------------------------------------------------------- 健壮性：一个坏配方不能拖垮整个装载（盲审 1a/1b）


def test_deeply_nested_json_recursion_error_becomes_a_problem_not_a_crash(tmp_path):
    """§1(a)：极深嵌套数组会让 `json.loads` 抛 `RecursionError`（不是
    `JSONDecodeError`）；这必须落进 `problems`，不能把 `load_recipes()` 本身
    炸掉（进而拖垮 `GET /api/recipes`）。"""
    good = tmp_path / "builtin"
    _write_recipe(good, "demo-kit", data=_base())

    bad_dir = tmp_path / "builtin" / "bad-kit"
    bad_dir.mkdir(parents=True)
    (bad_dir / "recipe.json").write_text("[" * 20000 + "]" * 20000, encoding="utf-8")
    (bad_dir / "guide.md").write_text("guide", encoding="utf-8")

    catalog = recipes.load_recipes(tmp_path / "builtin", tmp_path / "user")
    ids = {r["id"] for r in catalog["recipes"]}
    assert ids == {"demo-kit"}  # 坏配方没有拖累好配方
    assert any(p["dir"].endswith("bad-kit") for p in catalog["problems"])


@pytest.mark.skipif(sys.platform == "win32", reason="chmod 权限语义在 Windows 上不一样")
def test_permission_denied_directory_scan_becomes_a_problem_not_a_crash(tmp_path):
    """§1(b)：整个来源目录扫不了（这里用 chmod 000 模拟权限拒绝）时，记一条
    `problems`（`dir` 是目录名），另一个来源照常装载，不能让 `load_recipes()`
    整体抛异常。"""
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        pytest.skip("以 root 运行时权限位不生效")

    good = tmp_path / "builtin"
    _write_recipe(good, "demo-kit", data=_base())

    blocked_user = tmp_path / "user"
    blocked_user.mkdir()
    (blocked_user / "somedir").mkdir()
    os.chmod(blocked_user, 0)
    try:
        catalog = recipes.load_recipes(good, blocked_user)
    finally:
        os.chmod(blocked_user, 0o700)  # 恢复权限，方便 tmp_path 清理

    assert len(catalog["recipes"]) == 1  # builtin 那份照常装载
    assert catalog["recipes"][0]["id"] == "demo-kit"
    assert len(catalog["problems"]) == 1
    assert catalog["problems"][0]["source"] == "user"
    assert catalog["problems"][0]["dir"] == str(blocked_user)


# ===========================================================================
# `compute_step_status` / `compute_recipe_view`：纯函数（不需要起服务）
# ===========================================================================


def test_compute_step_status_unknown_row_always_todo():
    assert (
        recipes.compute_step_status("split", readiness_by_key={"split": "pass"}, stale_keys=set(), busy_op=None)
        == "todo"
    )


def test_compute_step_status_known_row_reads_readiness():
    assert (
        recipes.compute_step_status("orient", readiness_by_key={"orient": "pass"}, stale_keys=set(), busy_op=None)
        == "pass"
    )
    assert (
        recipes.compute_step_status("orient", readiness_by_key={"orient": "warn"}, stale_keys=set(), busy_op=None)
        == "warn"
    )
    assert recipes.compute_step_status("orient", readiness_by_key={}, stale_keys=set(), busy_op=None) == "todo"


def test_compute_step_status_stale_overrides_to_redo():
    status = recipes.compute_step_status(
        "arrange", readiness_by_key={"arrange": "todo"}, stale_keys={"arrange"}, busy_op=None
    )
    assert status == "redo"


def test_compute_step_status_busy_overrides_to_running():
    status = recipes.compute_step_status(
        "orient", readiness_by_key={"orient": "todo"}, stale_keys=set(), busy_op="orient"
    )
    assert status == "running"


def test_compute_step_status_busy_load_maps_to_model_row():
    status = recipes.compute_step_status("model", readiness_by_key={"model": "todo"}, stale_keys=set(), busy_op="load")
    assert status == "running"


def test_compute_step_status_busy_send_maps_to_deliver_row():
    status = recipes.compute_step_status(
        "deliver", readiness_by_key={"deliver": "todo"}, stale_keys=set(), busy_op="send"
    )
    assert status == "running"


def test_compute_step_status_prepare_does_not_mark_any_row_running():
    status = recipes.compute_step_status(
        "orient", readiness_by_key={"orient": "todo"}, stale_keys=set(), busy_op="prepare"
    )
    assert status == "todo"


def test_compute_recipe_view_next_done_total_only_count_non_optional():
    recipe = {
        "steps": [
            {
                "key": "a1",
                "row": "model",
                "tool": "studio_load",
                "who": "either",
                "optional": False,
                "decide": "d",
                "accept": "a",
                "args": {},
            },
            {
                "key": "b1",
                "row": "orient",
                "tool": "studio_orient",
                "who": "ai",
                "optional": True,
                "decide": "d",
                "accept": "a",
                "args": {},
            },
            {
                "key": "c1",
                "row": "arrange",
                "tool": "studio_arrange",
                "who": "ai",
                "optional": False,
                "decide": "d",
                "accept": "a",
                "args": {},
            },
        ]
    }
    view = recipes.compute_recipe_view(
        recipe,
        readiness_items=[
            {"key": "model", "status": "pass"},
            {"key": "orient", "status": "todo"},
            {"key": "arrange", "status": "todo"},
        ],
        stale={},
        busy=None,
    )
    assert view["total"] == 2  # 只数非 optional（a1、c1）
    assert view["done"] == 1
    assert view["next"] == "c1"  # 跳过 optional 的 b1
    statuses = {s["key"]: s["status"] for s in view["steps"]}
    assert statuses == {"a1": "pass", "b1": "todo", "c1": "todo"}


def test_compute_recipe_view_all_pass_next_is_none():
    recipe = {
        "steps": [
            {
                "key": "a1",
                "row": "model",
                "tool": "studio_load",
                "who": "either",
                "optional": False,
                "decide": "d",
                "accept": "a",
                "args": {},
            }
        ]
    }
    view = recipes.compute_recipe_view(
        recipe, readiness_items=[{"key": "model", "status": "pass"}], stale={}, busy=None
    )
    assert view["next"] is None
    assert view["done"] == view["total"] == 1


# ===========================================================================
# 本机服务接口：GET /api/recipes、GET /api/recipe、POST /api/recipe/use、
# /api/state.recipe、鉴权、持久化。
# ===========================================================================


def _install_recipe(home: Path, rid: str, data: dict[str, Any], guide: str = "guide text") -> None:
    _write_recipe(home / "recipes", rid, data=data, guide=guide)


def test_api_recipes_lists_and_reports_rows(studio_env):
    home: Path = studio_env["home"]
    client: Client = studio_env["client"]
    _install_recipe(home, "demo-kit", _base())

    status, resp = client.get("/api/recipes")
    assert status == 200 and resp["ok"] is True
    assert resp["problems"] == []
    assert len(resp["rows"]) == 22
    assert {r["key"] for r in resp["rows"]} == set(recipes.ROW_KEYS)
    ids = {r["id"] for r in resp["recipes"]}
    assert "demo-kit" in ids
    demo = next(r for r in resp["recipes"] if r["id"] == "demo-kit")
    assert demo["source"] == "user"
    assert demo["availability"] == "ready"
    assert demo["route"] == ["model", "orient"]


def test_recipes_get_endpoints_require_token(studio_env):
    port = studio_env["port"]
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request("GET", "/api/recipes")
    resp = conn.getresponse()
    body = json.loads(resp.read())
    conn.close()
    assert resp.status == 403
    assert body["error"]["code"] == "forbidden"


def test_api_recipe_get_success_and_errors(studio_env):
    home: Path = studio_env["home"]
    client: Client = studio_env["client"]
    _install_recipe(home, "demo-kit", _base())

    status, resp = client.get("/api/recipe?id=demo-kit")
    assert status == 200 and resp["ok"] is True
    assert resp["recipe"]["id"] == "demo-kit"
    assert resp["recipe"]["guide_md"] == "guide text"
    assert resp["recipe"]["availability"] == "ready"

    status, resp = client.get("/api/recipe")
    assert status == 400
    assert resp["error"]["code"] == "bad_arguments"

    status, resp = client.get("/api/recipe?id=nope")
    assert status == 404
    assert resp["error"]["code"] == "unknown_recipe"


def test_recipe_use_unknown_and_unavailable(studio_env):
    home: Path = studio_env["home"]
    client: Client = studio_env["client"]
    needs = _base()
    needs["id"] = "needs-kit"
    needs["steps"].append(
        {
            "key": "split",
            "row": "split",
            "tool": "studio_split",
            "who": "ai",
            "args": {},
            "decide": "x",
            "accept": "y",
            "optional": False,
        }
    )
    _install_recipe(home, "needs-kit", needs)

    status, resp = client.post("/api/recipe/use", {"id": "does-not-exist"})
    assert status == 404
    assert resp["error"]["code"] == "unknown_recipe"

    status, resp = client.post("/api/recipe/use", {"id": "needs-kit"})
    assert status == 409
    assert resp["error"]["code"] == "recipe_unavailable"
    assert resp["missing_tools"] == ["studio_split"]

    _, state = client.get("/api/state")
    assert state["recipe"] is None  # 两次都没有真的切换


def test_recipe_use_start_records_history_and_state(studio_env):
    home: Path = studio_env["home"]
    client: Client = studio_env["client"]
    _install_recipe(home, "demo-kit", _base())

    status, resp = client.post("/api/recipe/use", {"id": "demo-kit"}, headers={"X-Studio-Actor": "human"})
    assert status == 200 and resp["ok"] is True
    assert resp["action"] == "start" and resp["id"] == "demo-kit" and resp["title"] == "示例配方"

    status, state = client.get("/api/state")
    assert state["recipe"]["id"] == "demo-kit"
    assert state["recipe"]["title"] == "示例配方"
    assert state["recipe"]["source"] == "user"
    assert state["recipe"]["by"] == "human"
    assert state["recipe"]["started_at"]
    assert state["recipe"]["total"] == 2
    assert state["recipe"]["done"] == 0
    assert state["recipe"]["next"] == "load"
    assert state["recipe"]["one_shot"] is None  # demo-kit 没有 one_shot

    assert state["history"][0]["op"] == "recipe"
    assert state["history"][0]["actor"] == "human"
    assert state["history"][0]["undoable"] is False
    assert state["history"][0]["summary"] == {"action": "start", "id": "demo-kit", "title": "示例配方"}


def test_state_recipe_carries_one_shot_verbatim(studio_env):
    """SPEC_RECIPES.md §3.3（小补丁）：`/api/state.recipe.one_shot` 原样带出
    `recipe.json` 的 `one_shot`，面板靠它决定要不要显示「一键走完」。"""
    home: Path = studio_env["home"]
    client: Client = studio_env["client"]
    data = _base()
    data["one_shot"] = {"tool": "studio_prepare", "args": {"shape": "generic"}}
    _install_recipe(home, "demo-kit", data)

    assert client.post("/api/recipe/use", {"id": "demo-kit"})[0] == 200
    _, state = client.get("/api/state")
    assert state["recipe"]["one_shot"] == {"tool": "studio_prepare", "args": {"shape": "generic"}}


def test_recipe_use_idempotent_does_not_duplicate_history(studio_env):
    home: Path = studio_env["home"]
    client: Client = studio_env["client"]
    _install_recipe(home, "demo-kit", _base())

    assert client.post("/api/recipe/use", {"id": "demo-kit"})[0] == 200
    _, state1 = client.get("/api/state")
    n1 = len(state1["history"])

    status, resp = client.post("/api/recipe/use", {"id": "demo-kit"})
    assert status == 200 and resp["ok"] is True
    assert resp["already_active"] is True

    _, state2 = client.get("/api/state")
    assert len(state2["history"]) == n1  # 幂等：没有多一条记录


def test_recipe_use_stop(studio_env):
    home: Path = studio_env["home"]
    client: Client = studio_env["client"]
    _install_recipe(home, "demo-kit", _base())
    assert client.post("/api/recipe/use", {"id": "demo-kit"})[0] == 200

    status, resp = client.post("/api/recipe/use", {"id": None})
    assert status == 200 and resp["ok"] is True
    # 盲审 6：停用时的 id/title 是"被停用的是哪个配方"，不是新状态（新状态
    # 已经是"没在用"了，state.recipe 才是 null）——否则历史记录会显示成空的
    # 「停用配方「」」。
    assert resp["action"] == "stop"
    assert resp["id"] == "demo-kit"
    assert resp["title"] == "示例配方"

    _, state = client.get("/api/state")
    assert state["recipe"] is None
    assert state["history"][0]["op"] == "recipe"
    assert state["history"][0]["summary"] == {"action": "stop", "id": "demo-kit", "title": "示例配方"}


def test_recipe_use_stop_when_already_stopped_is_idempotent(studio_env):
    home: Path = studio_env["home"]
    client: Client = studio_env["client"]
    _install_recipe(home, "demo-kit", _base())
    _, state0 = client.get("/api/state")
    n0 = len(state0["history"])

    status, resp = client.post("/api/recipe/use", {"id": None})
    assert status == 200 and resp["already_active"] is True
    _, state1 = client.get("/api/state")
    assert len(state1["history"]) == n0


def test_recipe_persists_across_backend_instances(studio_env):
    home: Path = studio_env["home"]
    client: Client = studio_env["client"]
    job_dir: Path = studio_env["job_dir"]
    _install_recipe(home, "demo-kit", _base())
    assert client.post("/api/recipe/use", {"id": "demo-kit"}, headers={"X-Studio-Actor": "human"})[0] == 200

    new_backend = StudioBackend(job_dir, token="irrelevant-token-for-this-test")
    active = new_backend.history_store.public_active_recipe()
    assert active is not None
    assert active["id"] == "demo-kit"
    assert active["by"] == "human"


def test_recipe_state_becomes_null_when_recipe_removed(studio_env):
    home: Path = studio_env["home"]
    client: Client = studio_env["client"]
    _install_recipe(home, "demo-kit", _base())
    assert client.post("/api/recipe/use", {"id": "demo-kit"})[0] == 200
    _, state = client.get("/api/state")
    assert state["recipe"] is not None

    shutil.rmtree(home / "recipes" / "demo-kit")
    _, state2 = client.get("/api/state")
    assert state2["recipe"] is None


def test_get_state_survives_unexpected_exception_while_assembling_recipe(studio_env, monkeypatch):
    """盲审 1c：`build_state()` 装配 `recipe` 字段那一段必须单独兜底——出任何
    异常 -> `recipe: null`，`/api/state` 本身必须仍然是 200 ok:true（改前会让
    整个请求直接断连，面板冻住且连"停用配方"都点不到）。"""
    home: Path = studio_env["home"]
    client: Client = studio_env["client"]
    _install_recipe(home, "demo-kit", _base())
    assert client.post("/api/recipe/use", {"id": "demo-kit"})[0] == 200

    from studio.shell import server as server_mod

    def boom(*args, **kwargs):
        raise RuntimeError("simulated failure while assembling recipe state")

    monkeypatch.setattr(server_mod.recipes, "compute_recipe_view", boom)

    status, state = client.get("/api/state")
    assert status == 200
    assert state["ok"] is True
    assert state["recipe"] is None
    # 别的字段照常，不是整份响应都被吞了。
    assert "parts" in state and "history" in state


def test_recipe_use_stop_succeeds_even_if_catalog_scan_raises(studio_env, monkeypatch):
    """盲审 1d：`POST /api/recipe/use {"id": null}` 在目录扫描失败时也必须能
    成功停用——取标题失败不该连"清掉 active_recipe"这个动作本身都做不成。"""
    home: Path = studio_env["home"]
    client: Client = studio_env["client"]
    _install_recipe(home, "demo-kit", _base())
    assert client.post("/api/recipe/use", {"id": "demo-kit"})[0] == 200

    from studio.shell import server as server_mod

    def boom():
        raise RuntimeError("simulated catalog scan failure")

    monkeypatch.setattr(server_mod, "_load_recipe_catalog", boom)

    status, resp = client.post("/api/recipe/use", {"id": None})
    assert status == 200
    assert resp["ok"] is True
    assert resp["action"] == "stop"
    assert resp["id"] == "demo-kit"  # 标题查不到，但 id 还在

    monkeypatch.undo()  # 停用之后 state.recipe 走的是"没有 active_recipe"的早退路径，不再碰 catalog
    _, state = client.get("/api/state")
    assert state["recipe"] is None


def test_state_recipe_steps_status_tracks_readiness_and_stale(studio_env, tmp_path):
    home: Path = studio_env["home"]
    client: Client = studio_env["client"]
    data = _base()
    data["steps"] = [
        _good_step(key="load", row="model", tool="studio_load"),
        _good_step(key="orient", row="orient", tool="studio_orient"),
        _good_step(key="arrange", row="arrange", tool="studio_arrange"),
    ]
    _install_recipe(home, "demo-kit", data)
    assert client.post("/api/recipe/use", {"id": "demo-kit"})[0] == 200

    _, state = client.get("/api/state")
    by_key = {s["key"]: s["status"] for s in state["recipe"]["steps"]}
    assert by_key == {"load": "todo", "orient": "todo", "arrange": "todo"}
    assert state["recipe"]["next"] == "load"
    assert state["recipe"]["done"] == 0

    box1 = write_box_stl(tmp_path, "box1", (30, 20, 5))
    box2 = write_box_stl(tmp_path, "box2", (15, 10, 40))
    assert client.post("/api/load", {"files": [str(box1), str(box2)]})[0] == 200
    _, state = client.get("/api/state")
    by_key = {s["key"]: s["status"] for s in state["recipe"]["steps"]}
    assert by_key["load"] == "pass"
    assert state["recipe"]["next"] == "orient"
    assert state["recipe"]["done"] == 1

    assert client.post("/api/orient", {"shape": "generic"})[0] == 200
    assert client.post("/api/arrange", {"gap": 4})[0] == 200
    _, state = client.get("/api/state")
    assert state["recipe"]["done"] == 3
    assert state["recipe"]["next"] is None

    # 再 orient 一次：arrange 因失效级联进 stale -> 对应步骤变成 redo。
    assert client.post("/api/orient", {"shape": "relief"})[0] == 200
    _, state = client.get("/api/state")
    by_key = {s["key"]: s["status"] for s in state["recipe"]["steps"]}
    assert by_key["arrange"] == "redo"
    assert state["recipe"]["next"] == "arrange"


def test_recipe_use_returns_409_busy_when_write_lock_held(studio_env):
    backend = studio_env["backend"]
    client: Client = studio_env["client"]

    def slow_op():
        time.sleep(0.4)
        return {"ok": True, "command": "load"}

    result_holder: dict[str, Any] = {}

    def run_slow():
        result_holder["result"] = backend.run_write("load", slow_op)

    t = threading.Thread(target=run_slow)
    t.start()
    time.sleep(0.1)
    status, resp = client.post("/api/recipe/use", {"id": "demo-kit"})
    t.join(timeout=5)

    assert status == 409
    assert resp["error"]["code"] == "busy"
    assert result_holder["result"][0] == 200


def test_recipe_use_post_with_cookie_only_is_rejected(studio_env):
    home: Path = studio_env["home"]
    client: Client = studio_env["client"]
    port = studio_env["port"]
    backend: StudioBackend = studio_env["backend"]
    _install_recipe(home, "demo-kit", _base())

    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request(
        "POST",
        "/api/recipe/use",
        body=json.dumps({"id": "demo-kit"}).encode("utf-8"),
        headers={"Cookie": f"studio_token={backend.token}", "Content-Type": "application/json"},
    )
    resp = conn.getresponse()
    body = json.loads(resp.read())
    conn.close()
    assert resp.status == 403
    assert body["error"]["code"] == "forbidden"

    _, state = client.get("/api/state")
    assert state["recipe"] is None  # 没有真的执行


# ===========================================================================
# 三个新工具：tools_schema / /api/tools
# ===========================================================================


def test_tools_schema_has_the_three_recipe_tools():
    from studio.shell import tools_schema

    names = {t["name"] for t in tools_schema.get_tools()}
    assert {"studio_list_recipes", "studio_get_recipe", "studio_use_recipe"}.issubset(names)
    by_name = {t["name"]: t for t in tools_schema.get_tools()}
    assert by_name["studio_list_recipes"]["method"] == "GET"
    assert by_name["studio_list_recipes"]["path"] == "/api/recipes"
    assert by_name["studio_list_recipes"]["readOnly"] is True
    assert by_name["studio_get_recipe"]["method"] == "GET"
    assert by_name["studio_get_recipe"]["path"] == "/api/recipe"
    assert by_name["studio_get_recipe"]["inputSchema"]["required"] == ["id"]
    assert by_name["studio_use_recipe"]["method"] == "POST"
    assert by_name["studio_use_recipe"]["path"] == "/api/recipe/use"
    assert by_name["studio_use_recipe"]["readOnly"] is False
    id_schema = by_name["studio_use_recipe"]["inputSchema"]["properties"]["id"]
    assert set(id_schema["type"]) == {"string", "null"}


def test_studio_get_recipe_description_warns_about_needs_tools(tmp_path):
    """盲审 5：SPEC §4 第三点（needs_tools 的配方不要用别的办法硬凑）要出现在
    `studio_get_recipe` 的说明里，不能只在 `studio_list_recipes`/
    `studio_use_recipe` 里提。"""
    from studio.shell import tools_schema

    by_name = {t["name"]: t for t in tools_schema.get_tools()}
    assert "needs_tools" in by_name["studio_get_recipe"]["description"]
    assert "working around it some other way" in by_name["studio_get_recipe"]["description"]


def test_api_tools_endpoint_includes_recipe_tools(studio_env):
    client: Client = studio_env["client"]
    status, resp = client.get("/api/tools")
    assert status == 200
    names = {t["name"] for t in resp["tools"]}
    assert {"studio_list_recipes", "studio_get_recipe", "studio_use_recipe"}.issubset(names)
