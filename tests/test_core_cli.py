"""`python -m studio.core` —— exercised as a real subprocess (not an in-process
call) so this test also proves the module is actually invocable that way, the
way a Blender add-on or another agent's skill would call it. Kept fast: no
Blender, no network, no heavy fixtures — just the recipe catalog, the editor's
`primitive` action, and an empty task queue.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def run_core_cli(args: list[str]) -> tuple[int, dict]:
    """Runs `python -m studio.core <args>` from the repo root, inheriting the
    current environment (the autouse `_isolate_user_state` fixture in
    conftest.py has already pointed `PRINT_PREP_HOME` at a temp directory).
    Asserts stdout is exactly one JSON object, per the CLI's own contract."""
    result = subprocess.run(
        [sys.executable, "-m", "studio.core", *args],
        cwd=REPO_ROOT,
        env=os.environ,
        capture_output=True,
        text=True,
        timeout=60,
    )
    stdout = result.stdout.strip()
    assert stdout, f"stdout must not be empty; stderr was: {result.stderr}"
    lines = [line for line in stdout.splitlines() if line.strip()]
    assert len(lines) == 1, f"stdout must be exactly one JSON object, got: {stdout!r}"
    return result.returncode, json.loads(lines[0])


def test_recipes_list_returns_the_built_in_recipes():
    code, payload = run_core_cli(["recipes", "list"])
    assert code == 0
    assert payload["ok"] is True
    ids = {r["id"] for r in payload["recipes"]}
    # These ship in the repo's own recipes/ directory (see recipes/*/recipe.json).
    assert {"estimate-only", "cut-to-fit", "color-split", "figurine-whole"} <= ids
    assert isinstance(payload["rows"], list) and payload["rows"]
    assert payload["problems"] == []


def test_recipes_show_unknown_id_is_a_clean_error():
    code, payload = run_core_cli(["recipes", "show", "does-not-exist"])
    assert code == 1
    assert payload["ok"] is False
    assert payload["error"]["code"] == "unknown_recipe"


def test_recipes_check_validates_a_built_in_recipe_file():
    recipe_path = REPO_ROOT / "recipes" / "estimate-only" / "recipe.json"
    code, payload = run_core_cli(["recipes", "check", str(recipe_path)])
    assert code == 0
    recipe = payload["recipe"]
    assert recipe["id"] == "estimate-only"
    # Derived-availability fields that only exist after validation + finalize.
    assert recipe["availability"] in ("ready", "needs_tools")
    assert isinstance(recipe["missing_tools"], list)
    assert isinstance(recipe["route"], list) and recipe["route"]


def test_editor_apply_primitive_then_inspect_shows_one_object(tmp_path):
    doc = tmp_path / "workbench"
    code, apply_payload = run_core_cli(
        ["editor", "apply", "--doc", str(doc), "--action", "primitive", "--params", '{"kind": "box"}']
    )
    assert code == 0, apply_payload
    assert apply_payload["ok"] is True
    assert apply_payload["revision"] == 1

    code, inspect_payload = run_core_cli(["editor", "inspect", "--doc", str(doc)])
    assert code == 0
    assert inspect_payload["ok"] is True
    assert len(inspect_payload["objects"]) == 1
    assert inspect_payload["objects"][0]["name"] == "立方体"
    assert inspect_payload["revision"] == 1


def test_editor_apply_reports_editor_errors_as_json_not_a_traceback(tmp_path):
    doc = tmp_path / "workbench"
    code, payload = run_core_cli(
        ["editor", "apply", "--doc", str(doc), "--action", "primitive", "--params", "not json"]
    )
    assert code == 1
    assert payload["ok"] is False
    assert payload["error"]["code"] == "bad_arguments"
    assert "message" in payload["error"]


def test_tasks_list_on_an_empty_home_returns_an_empty_list(tmp_path):
    code, payload = run_core_cli(["tasks", "list", "--job", str(tmp_path / "job")])
    assert code == 0
    assert payload == {"ok": True, "tasks": []}


def test_tasks_status_unknown_id_is_a_clean_error(tmp_path):
    code, payload = run_core_cli(
        ["tasks", "status", "--job", str(tmp_path / "job"), "--id", "deadbeefdeadbeefdeadbeefdeadbeef"]
    )
    assert code == 1
    assert payload["ok"] is False
    assert "error" in payload


def test_unknown_subcommand_exits_1_with_a_json_error():
    code, payload = run_core_cli(["not-a-real-group"])
    assert code == 1
    assert payload["ok"] is False
    assert payload["error"]["code"] == "bad_arguments"
    assert "message" in payload["error"]


def test_unknown_verb_within_a_known_group_exits_1_with_a_json_error():
    code, payload = run_core_cli(["editor", "not-a-real-verb"])
    assert code == 1
    assert payload["ok"] is False
    assert payload["error"]["code"] == "bad_arguments"


def test_no_arguments_exits_1_with_a_json_error():
    code, payload = run_core_cli([])
    assert code == 1
    assert payload["ok"] is False
    assert payload["error"]["code"] == "bad_arguments"


def test_help_exits_zero_and_is_not_forced_into_json():
    result = subprocess.run(
        [sys.executable, "-m", "studio.core", "--help"],
        cwd=REPO_ROOT,
        env=os.environ,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0
    assert "recipes" in result.stdout and "editor" in result.stdout


def test_print_delegates_to_print_prep_cli(tmp_path):
    """`print ...` must behave exactly like `python -m print_prep.cli ...`
    (same JSON contract, same exit codes) rather than being re-parsed by
    studio.core's own argparse tree."""
    result = subprocess.run(
        [sys.executable, "-m", "studio.core", "print", "inspect", "--job", str(tmp_path / "job")],
        cwd=REPO_ROOT,
        env=os.environ,
        capture_output=True,
        text=True,
        timeout=60,
    )
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    # No files were given; print_prep.cli's own bad_arguments/exit_code=2 contract applies unchanged.
    assert result.returncode == 2
    assert payload["ok"] is False


def test_result_containing_nan_becomes_a_clean_error_not_a_traceback(monkeypatch, capsys):
    """`allow_nan=False` used to sit outside the try/except around
    `json.dumps(_success(result), ...)`, so a NaN anywhere in a handler's
    result printed a bare traceback to stdout instead of the CLI's own JSON
    contract. Exercised in-process (not a subprocess) so the monkeypatched
    handler is actually the one argparse dispatches to."""
    from studio.core import cli

    monkeypatch.setattr(cli, "cmd_recipes_list", lambda args: {"bad": float("nan")})
    code = cli.main(["recipes", "list"])
    assert code == 1
    out = capsys.readouterr().out.strip()
    lines = [line for line in out.splitlines() if line.strip()]
    assert len(lines) == 1, f"stdout must still be exactly one JSON object, got: {out!r}"
    payload = json.loads(lines[0])
    assert payload["ok"] is False
    assert payload["error"]["code"] == "internal_error"


def test_result_containing_an_unserialisable_object_is_saved_by_default_str(monkeypatch, capsys):
    """`default=str` is the fallback for values `json` doesn't know how to
    serialise (e.g. a stray `Path`) — those should come out as their string
    form, not crash the whole CLI call."""
    from pathlib import Path as _Path

    from studio.core import cli

    monkeypatch.setattr(cli, "cmd_recipes_list", lambda args: {"path": _Path("/tmp/example")})
    code = cli.main(["recipes", "list"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out.strip())
    assert payload["ok"] is True
    assert payload["path"] == str(_Path("/tmp/example"))


def test_tool_schemas_snapshot_matches_the_live_shell_list():
    """The checked-in snapshot studio.core.cli reads by default must not
    silently drift from studio.shell.tools_schema.get_tools() — that would
    let `recipes list/show/check`'s availability/missing_tools computation
    go stale without anyone noticing."""
    from studio.core.cli import _DEFAULT_TOOL_SCHEMAS
    from studio.shell.tools_schema import get_tools

    snapshot = json.loads(_DEFAULT_TOOL_SCHEMAS.read_text(encoding="utf-8"))
    assert snapshot == get_tools()
