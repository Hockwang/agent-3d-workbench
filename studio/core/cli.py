"""studio.core.cli —— `python -m studio.core`: the same capabilities as the
Codex MCP/HTTP shell, without Codex.

The plugin's thesis is "the shell is only an adapter; the capability lives in
the local layer" (`docs/ARCHITECTURE.md`). This module is the second adapter
that proves it: it calls `studio.core.recipes` / `studio.core.editor` /
`studio.core.tasks` / `studio.core.observation` directly — the exact same
functions `studio/shell/server.py` and `studio/shell/mcp_server.py` call —
and never imports `studio.shell` or `studio.adapters` (enforced by
`tests/test_layering.py`). A Blender add-on or a non-Codex agent skill can
shell out to this module instead of speaking HTTP or MCP.

Contract (see `docs/CORE_CLI.md`):
- stdout is always exactly one JSON object, for both success and failure.
- success: the object returned by the underlying `studio.core.*` call,
  with a top-level `"ok": true` added if the call didn't already include one
  (several already do, e.g. `Workspace.execute`, `Tasks.start`).
- failure: `{"error": {"code": ..., "message": ...}}`, exit code 1.
- `--help` works for every command via argparse; it prints text (not JSON)
  and exits 0, same as every other Python CLI.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Optional

import studio
from studio.core import capabilities
from studio.core import recipes
from studio.core.editor import EditorError, Workspace
from studio.core.observation import Observations
from studio.core.recipes import RecipeError
from studio.core.tasks import Tasks
from studio.i18n import render

# Generated once with `uv run python -c "..."` from studio.shell.tools_schema
# (see docs/CORE_CLI.md); checked in so this module never imports studio.shell.
# tests/test_core_cli.py asserts it stays equal to the live shell list.
_DEFAULT_TOOL_SCHEMAS = Path(__file__).resolve().with_name("tool_schemas.json")

# Action names dispatched by studio.core.editor.Workspace._apply (directly, or
# via the "scene_"/"city_"/"motion_" prefixed handoffs to scene_assets.py /
# city.py / motion.py). Read from studio/core/editor.py by hand on 2026-09-24;
# used only for `editor apply --help` text, never to reject a value — an
# unrecognised action already gets a clear error from Workspace.execute itself.
_FALLBACK_EDITOR_ACTIONS: tuple[str, ...] = (
    "boolean",
    "city_catalog",
    "city_checkout",
    "city_import",
    "city_register",
    "delete",
    "duplicate",
    "export",
    "extract_faces",
    "import",
    "inspect",
    "isolate",
    "material",
    "merge",
    "motion_clear",
    "motion_export",
    "motion_import",
    "motion_set",
    "open",
    "plane_cut",
    "primitive",
    "print_copy",
    "redo",
    "rename",
    "replace",
    "save",
    "scene_export",
    "scene_import",
    "scene_replace",
    "select",
    "show_all",
    "simplify",
    "split_components",
    "transform",
    "undo",
    "visibility",
)


class _CliError(Exception):
    """A CLI-side error (bad JSON, bad file, unknown recipe/artifact) that
    isn't already one of `EditorError`/`RecipeError`. Same shape as those
    once it reaches `main()`."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class _ArgError(Exception):
    """Raised by `_Parser.error()` instead of argparse's default
    print-usage-and-`sys.exit(2)`, so `main()` can turn it into the same
    JSON error shape as every other failure."""


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise _ArgError(message)


def _editor_action_names() -> list[str]:
    """Action names for `editor apply --help`. Prefers the canonical registry
    in `studio.core.editor_actions` if that module exists (a future refactor
    may extract `Workspace._apply`'s if/elif chain into one); falls back to
    the static list above otherwise. Import is deferred so this keeps working
    whether or not that module has landed yet."""
    try:
        from studio.core import editor_actions  # type: ignore[import-not-found]
    except ImportError:
        return sorted(_FALLBACK_EDITOR_ACTIONS)
    actions = getattr(editor_actions, "ACTIONS", None)
    if actions is None:
        return sorted(_FALLBACK_EDITOR_ACTIONS)
    names = actions.keys() if isinstance(actions, dict) else actions
    return sorted(str(name) for name in names)


def _load_tool_schemas(path: Optional[str]) -> list[dict[str, Any]]:
    target = Path(path).expanduser() if path else _DEFAULT_TOOL_SCHEMAS
    try:
        raw = target.read_text(encoding="utf-8")
    except OSError as exc:
        raise _CliError("bad_arguments", render("cli.tool_schemas_read_failed", path=target, error=exc)) from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise _CliError("bad_arguments", render("cli.tool_schemas_bad_json", path=target, error=exc)) from exc
    if not isinstance(data, list):
        raise _CliError("bad_arguments", render("cli.tool_schemas_not_array", path=target))
    return data


def _configure_recipes(tool_schemas_path: Optional[str]) -> None:
    tools = _load_tool_schemas(tool_schemas_path)
    recipes.configure(lambda: tools)


def _recipe_user_dir(explicit: Optional[str]) -> Path:
    """Mirrors `studio.shell.server._recipe_user_dir()`: `PRINT_PREP_HOME/recipes`,
    overridable for tests/scripts that want an isolated recipes directory."""
    return Path(explicit).expanduser() if explicit else (studio.print_prep_home() / "recipes")


def _parse_json_arg(value: Optional[str], default: Any) -> Any:
    """Parses `value` as JSON. `@path` reads the JSON from a file instead of
    the argument itself, for request bodies too large to type inline."""
    if value is None:
        return default
    text = value
    if value.startswith("@"):
        file_path = Path(value[1:]).expanduser()
        try:
            text = file_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise _CliError("bad_arguments", render("cli.json_file_read_failed", path=file_path, error=exc)) from exc
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise _CliError("bad_arguments", render("cli.not_valid_json", error=exc)) from exc


def _parse_json_object(value: Optional[str], field: str) -> dict[str, Any]:
    parsed = _parse_json_arg(value, default={})
    if not isinstance(parsed, dict):
        raise _CliError("bad_arguments", render("cli.field_must_be_json_object", field=field))
    return parsed


def _success(result: Any) -> dict[str, Any]:
    if not isinstance(result, dict):
        return {"ok": True, "result": result}
    return result if "ok" in result else {"ok": True, **result}


# ---------------------------------------------------------------------------
# recipes
# ---------------------------------------------------------------------------


def cmd_recipes_list(args: argparse.Namespace) -> dict[str, Any]:
    _configure_recipes(args.tool_schemas)
    catalog = recipes.load_recipes(recipes.BUILTIN_RECIPES_DIR, _recipe_user_dir(args.user_dir))
    return {
        "recipes": recipes.sorted_summaries(catalog),
        "rows": catalog["rows"],
        "problems": catalog["problems"],
    }


def cmd_recipes_show(args: argparse.Namespace) -> dict[str, Any]:
    _configure_recipes(args.tool_schemas)
    catalog = recipes.load_recipes(recipes.BUILTIN_RECIPES_DIR, _recipe_user_dir(args.user_dir))
    match = recipes.find_recipe(catalog, args.id)
    if match is None:
        raise _CliError("unknown_recipe", render("cli.unknown_recipe", recipe_id=args.id))
    return {"recipe": match}


def cmd_recipes_check(args: argparse.Namespace) -> dict[str, Any]:
    """Validates a single `recipe.json` (+ sibling `guide.md`) without
    scanning any other directory — reuses `recipes._load_one`/`_finalize`
    directly (the same functions `load_recipes()` calls per-directory) since
    there is no public single-recipe entry point and this must not reinvent
    the validation rules."""
    path = Path(args.path).expanduser().resolve()
    if path.name != "recipe.json":
        raise _CliError("bad_arguments", render("cli.recipe_check_path_not_recipe_json"))
    tools_by_name = {t["name"]: t for t in _load_tool_schemas(args.tool_schemas)}
    try:
        recipe = recipes._load_one(path.parent, "user", tools_by_name)  # noqa: SLF001
    except recipes._InvalidRecipe as exc:  # noqa: SLF001
        raise _CliError("invalid_recipe", str(exc)) from exc
    # This CLI has no hosted-service catalog to ask (no `studio.shell`/
    # `studio.adapters` import, see the module docstring), so a
    # `studio_task#<hosted-operation>` step (e.g. image-to-3d) always reads as
    # missing here even when `GET /api/recipes` reports it ready — the one
    # documented gap between this CLI's recipe listing and the MCP/HTTP one.
    capability_map = capabilities.build(tools_by_name)
    task_template_ids = capabilities.task_template_ids()
    return {"recipe": recipes._finalize(recipe, tools_by_name, capability_map, task_template_ids)}  # noqa: SLF001


# ---------------------------------------------------------------------------
# editor
# ---------------------------------------------------------------------------


def cmd_editor_apply(args: argparse.Namespace) -> dict[str, Any]:
    ws = Workspace(Path(args.doc).expanduser())
    params = _parse_json_object(args.params, "--params")
    revision = args.expected_revision
    if revision is None:
        revision = ws.state()["revision"]
    body = {"action": args.action, "params": params, "expected_revision": revision}
    return ws.execute(body, actor=args.actor)


def cmd_editor_inspect(args: argparse.Namespace) -> dict[str, Any]:
    return Workspace(Path(args.doc).expanduser()).state()


# ---------------------------------------------------------------------------
# tasks
# ---------------------------------------------------------------------------


def _tasks_for(job: Optional[str]) -> Tasks:
    job_dir = Path(job).expanduser() if job else studio.default_job_dir()
    return Tasks(job_dir / "tasks")


def cmd_tasks_list(args: argparse.Namespace) -> dict[str, Any]:
    return {"tasks": _tasks_for(args.job).list()}


def cmd_tasks_start(args: argparse.Namespace) -> dict[str, Any]:
    body = _parse_json_object(args.request, "--request")
    return _tasks_for(args.job).start(body, args.actor)


def cmd_tasks_status(args: argparse.Namespace) -> dict[str, Any]:
    return _tasks_for(args.job).state(args.id, include_log=args.log)


def cmd_tasks_cancel(args: argparse.Namespace) -> dict[str, Any]:
    return _tasks_for(args.job).cancel(args.id)


def cmd_tasks_artifact(args: argparse.Namespace) -> dict[str, Any]:
    path, item = _tasks_for(args.job).artifact(args.id, args.artifact)
    if args.out:
        out_path = Path(args.out).expanduser()
        out_path.write_bytes(path.read_bytes())
        return {"artifact": item, "path": str(out_path)}
    return {"artifact": item, "path": str(path)}


# ---------------------------------------------------------------------------
# observe
# ---------------------------------------------------------------------------


def cmd_observe_run(args: argparse.Namespace) -> dict[str, Any]:
    job_dir = Path(args.job).expanduser() if args.job else studio.default_job_dir()
    observations = Observations(Tasks(job_dir / "tasks"))
    body: dict[str, Any] = {"action": "start"}
    if args.input:
        body["inputs"] = args.input
    if args.source_task:
        body["source_tasks"] = args.source_task
    if args.params is not None:
        body["params"] = _parse_json_object(args.params, "--params")
    if args.label:
        body["labels"] = args.label
    if args.title:
        body["title"] = args.title
    return observations.execute(body, args.actor)


# ---------------------------------------------------------------------------
# argparse wiring
# ---------------------------------------------------------------------------


def _build_parser() -> _Parser:
    parser = _Parser(
        prog="python -m studio.core",
        description=render("cli.description"),
        epilog=render("cli.epilog"),
    )
    group = parser.add_subparsers(dest="group", required=True, parser_class=_Parser)

    recipes_p = group.add_parser("recipes", help=render("cli.recipes_group_help"))
    recipes_verb = recipes_p.add_subparsers(dest="verb", required=True, parser_class=_Parser)

    recipes_list_p = recipes_verb.add_parser("list", help=render("cli.recipes_list_help"))
    recipes_list_p.add_argument(
        "--tool-schemas", help=render("cli.tool_schemas_help", default_name=_DEFAULT_TOOL_SCHEMAS.name)
    )
    recipes_list_p.add_argument("--user-dir", help=render("cli.user_dir_help"))
    recipes_list_p.set_defaults(handler=cmd_recipes_list)

    recipes_show_p = recipes_verb.add_parser("show", help=render("cli.recipes_show_help"))
    recipes_show_p.add_argument("id")
    recipes_show_p.add_argument("--tool-schemas")
    recipes_show_p.add_argument("--user-dir")
    recipes_show_p.set_defaults(handler=cmd_recipes_show)

    recipes_check_p = recipes_verb.add_parser("check", help=render("cli.recipe_check_help"))
    recipes_check_p.add_argument("path", help=render("cli.recipe_check_path_help"))
    recipes_check_p.add_argument("--tool-schemas")
    recipes_check_p.set_defaults(handler=cmd_recipes_check)

    editor_p = group.add_parser("editor", help=render("cli.editor_group_help"))
    editor_verb = editor_p.add_subparsers(dest="verb", required=True, parser_class=_Parser)

    default_doc = str(studio.default_job_dir() / "workbench")
    editor_apply_p = editor_verb.add_parser(
        "apply",
        help=render("cli.editor_apply_help"),
        epilog=render("cli.editor_apply_epilog", actions=", ".join(_editor_action_names())),
    )
    editor_apply_p.add_argument("--doc", default=default_doc, help=render("cli.doc_help", default_doc=default_doc))
    editor_apply_p.add_argument("--action", required=True, help=render("cli.action_help"))
    editor_apply_p.add_argument("--params", help=render("cli.params_action_help"))
    editor_apply_p.add_argument(
        "--expected-revision",
        type=int,
        default=None,
        help=render("cli.expected_revision_help"),
    )
    editor_apply_p.add_argument("--actor", default="human", help=render("cli.actor_help"))
    editor_apply_p.set_defaults(handler=cmd_editor_apply)

    editor_inspect_p = editor_verb.add_parser("inspect", help=render("cli.editor_inspect_help"))
    editor_inspect_p.add_argument("--doc", default=default_doc, help=render("cli.doc_help", default_doc=default_doc))
    editor_inspect_p.set_defaults(handler=cmd_editor_inspect)

    tasks_p = group.add_parser("tasks", help=render("cli.tasks_group_help"))
    tasks_verb = tasks_p.add_subparsers(dest="verb", required=True, parser_class=_Parser)

    tasks_list_p = tasks_verb.add_parser("list", help=render("cli.tasks_list_help"))
    tasks_list_p.add_argument("--job", help=render("cli.job_help"))
    tasks_list_p.set_defaults(handler=cmd_tasks_list)

    tasks_start_p = tasks_verb.add_parser("start", help=render("cli.tasks_start_help"))
    tasks_start_p.add_argument("--job")
    tasks_start_p.add_argument(
        "--request",
        required=True,
        help=render("cli.request_help"),
    )
    tasks_start_p.add_argument("--actor", default="human")
    tasks_start_p.set_defaults(handler=cmd_tasks_start)

    tasks_status_p = tasks_verb.add_parser("status", help=render("cli.tasks_status_help"))
    tasks_status_p.add_argument("--job")
    tasks_status_p.add_argument("--id", required=True)
    tasks_status_p.add_argument("--log", action="store_true", help=render("cli.log_help"))
    tasks_status_p.set_defaults(handler=cmd_tasks_status)

    tasks_cancel_p = tasks_verb.add_parser("cancel", help=render("cli.tasks_cancel_help"))
    tasks_cancel_p.add_argument("--job")
    tasks_cancel_p.add_argument("--id", required=True)
    tasks_cancel_p.set_defaults(handler=cmd_tasks_cancel)

    tasks_artifact_p = tasks_verb.add_parser("artifact", help=render("cli.tasks_artifact_help"))
    tasks_artifact_p.add_argument("--job")
    tasks_artifact_p.add_argument("--id", required=True)
    tasks_artifact_p.add_argument("--artifact", required=True, help=render("cli.artifact_help"))
    tasks_artifact_p.add_argument("--out", help=render("cli.out_help"))
    tasks_artifact_p.set_defaults(handler=cmd_tasks_artifact)

    observe_p = group.add_parser("observe", help=render("cli.observe_group_help"))
    observe_verb = observe_p.add_subparsers(dest="verb", required=True, parser_class=_Parser)

    observe_run_p = observe_verb.add_parser("run", help=render("cli.observe_run_help"))
    observe_run_p.add_argument("--job")
    observe_run_p.add_argument("--input", action="append", default=[], help=render("cli.input_help"))
    observe_run_p.add_argument(
        "--source-task",
        action="append",
        default=[],
        dest="source_task",
        help=render("cli.source_task_help"),
    )
    observe_run_p.add_argument("--params", help=render("cli.params_observe_help"))
    observe_run_p.add_argument("--label", action="append", default=[], help=render("cli.label_help"))
    observe_run_p.add_argument("--title", help=render("cli.title_help"))
    observe_run_p.add_argument("--actor", default="human")
    observe_run_p.set_defaults(handler=cmd_observe_run)

    return parser


def main(argv: Optional[list[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    if argv and argv[0] == "print":
        from print_prep.cli import main as print_main

        return print_main(argv[1:])

    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except _ArgError as exc:
        print(json.dumps({"ok": False, "error": {"code": "bad_arguments", "message": str(exc)}}, ensure_ascii=False))
        return 1

    try:
        result = args.handler(args)
    except _CliError as exc:
        print(json.dumps({"ok": False, "error": {"code": exc.code, "message": str(exc)}}, ensure_ascii=False))
        return 1
    except EditorError as exc:
        code = getattr(exc, "code", "bad_arguments")
        print(json.dumps({"ok": False, "error": {"code": code, "message": str(exc)}}, ensure_ascii=False))
        return 1
    except RecipeError as exc:
        print(json.dumps({"ok": False, "error": {"code": exc.code, "message": str(exc)}}, ensure_ascii=False))
        return 1
    except Exception as exc:  # noqa: BLE001 -- stdout must stay JSON-only, never a traceback
        print(
            json.dumps(
                {"ok": False, "error": {"code": "internal_error", "message": f"{type(exc).__name__}: {exc}"}},
                ensure_ascii=False,
            )
        )
        return 1

    try:
        # `default=str` saves otherwise-unserialisable objects (e.g. a stray
        # Path) instead of crashing; `allow_nan=False` still turns NaN/Infinity
        # into a ValueError rather than emitting invalid JSON — either failure
        # must become an error body, never a bare traceback on stdout.
        payload = json.dumps(_success(result), ensure_ascii=False, allow_nan=False, default=str)
    except (TypeError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": {"code": "internal_error", "message": render("cli.result_not_serializable", error=exc)},
                },
                ensure_ascii=False,
            )
        )
        return 1

    print(payload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
