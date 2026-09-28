> 中文：[zh-CN/CORE_CLI.md](zh-CN/CORE_CLI.md)

# Core CLI (`python -m studio.core`)

The plugin's thesis is "the shell (Codex plugin, a Blender add-on, another agent's
skill) is only an adapter; the capability lives in `studio.core`." The only entry
points into that layer used to be the stdio MCP server and the local HTTP server
(`studio/shell/`), both aimed at Codex. `python -m studio.core` is a third, much
thinner one: an argparse CLI calling `studio.core.recipes`/`editor`/`tasks`/
`observation` directly — the same functions the shell calls — with no Codex process
and no HTTP server involved. Install-free: from a checkout with dependencies synced
(`uv sync`), run `uv run python -m studio.core <group> <verb> [options]` from the
repo root. Respects `PRINT_PREP_HOME` exactly like the servers do (default
`~/.print-prep`); no new environment variables.

## Contract

stdout is always exactly one JSON object. Success: the dict the underlying call
returned, with `"ok": true` added at the top if missing (some, e.g.
`Workspace.execute`/`Tasks.start`, already include one). Failure:
`{"ok": false, "error": {"code": "...", "message": "..."}}`, exit code 1. `--help`
works on every subcommand (plain argparse text, exit 0) — not forced into JSON.

## Commands

### `recipes` (`studio.core.recipes`)

```bash
uv run python -m studio.core recipes list
uv run python -m studio.core recipes show cut-to-fit
uv run python -m studio.core recipes check recipes/cut-to-fit/recipe.json
```

`list`/`show <id>` need the current tool list to compute `availability`/
`missing_tools` (same as `GET /api/recipes`); by default they read the checked-in
`studio/core/tool_schemas.json` (generated from `tools_schema.get_tools()`, kept in
sync by `tests/test_core_cli.py`; override with `--tool-schemas path.json`).
`--user-dir path` overrides the user recipes directory (default
`PRINT_PREP_HOME/recipes`). `check <path-to-recipe.json>` validates one recipe
directory (file + sibling `guide.md`) alone — useful while authoring locally.

### `editor` (`studio.core.editor.Workspace`)

```bash
uv run python -m studio.core editor apply --doc ~/.print-prep/job/workbench \
    --action primitive --params '{"kind": "box"}'
uv run python -m studio.core editor inspect --doc ~/.print-prep/job/workbench
```

`--doc` is the workspace directory (`project.json`/`assets`/`exports`); defaults to
`PRINT_PREP_HOME/job/workbench`, same as the shell's `/api/edit` default job.
`apply` runs one `Workspace.execute()` action; `--params` is a JSON object (or
`@file.json`); `--expected-revision` defaults to the workspace's current revision,
read first, so a bare `apply` from a script works without an extra read. `inspect`
is a plain `Workspace.state()` read — no revision, never mutates.

Action names aren't restricted to `choices=` (`Workspace.execute` already raises a
clear error for an unknown one); `--help` lists them best-effort, from
`studio.core.editor_actions.ACTIONS` if that module exists, else a static list read
by hand from `Workspace._apply`/`scene_assets.apply`/`city.apply`/`motion.apply`.
Motion/scene/city actions (`motion_*`/`scene_*`/`city_*`) are reachable the same way
— dispatched by prefix inside `Workspace.execute()`, not a separate capability —
so there is no separate `motion`/`scene`/`city` subcommand.

### `tasks` (`studio.core.tasks.Tasks`)

```bash
uv run python -m studio.core tasks list --job ~/.print-prep/job
uv run python -m studio.core tasks start --job ~/.print-prep/job \
    --request '{"template": "container", "params": {...}}'
uv run python -m studio.core tasks status --job ~/.print-prep/job --id <task-id> --log
uv run python -m studio.core tasks artifact --job ~/.print-prep/job --id <task-id> \
    --artifact <artifact-id> --out ./scene.glb
```

`--job` defaults to `PRINT_PREP_HOME/job`; the queue lives at `<job>/tasks`, same as
the shell (`cancel --id <task-id>` requests cancellation of a running one).
`--request` is the JSON body `Tasks.start` expects (`@file.json` works too).
`artifact --out` copies the bytes out after re-verifying sha256/size; without it,
just reports metadata and the task-owned source path.

`--request '{"provider": "...", "operation": "...", ...}'` runs the hosted-service
adapters (Lux3D/Hunyuan/Seed3D/Assembly/Meshy/Tripo) *in-process*: `Tasks.start`
calls `studio.adapters.services.prepare()` synchronously, in the CLI's own process,
to validate credentials and build the request payload, before ever queuing the
task subprocess that actually submits it. `python -m studio.core` is shell-free
(no Codex, no MCP, no HTTP server) — it is not adapter-free.

### `observe run` (`studio.core.observation.Observations`)

```bash
uv run python -m studio.core observe run --job ~/.print-prep/job \
    --input /abs/a.glb --input /abs/b.glb --label before --label after \
    --params '{"views": ["front", "iso"], "phases": [0, 1]}'
```

Queues the `model-observe` template (1-4 GLB/STL/PLY/URDF inputs, or
`--source-task <id>` to reuse a prior task's GLB), via the same
`Observations.execute({"action": "start", ...})` call the shell's
`POST /api/observation` route makes — genuine `studio.core`, since it only talks to
`Tasks`. Reading back a finished observation (`read`/`review`/`focus`) has no
dedicated subcommand yet; it's a normal task otherwise, so `tasks status --id <id>`
/ `tasks artifact` reach the same output files.

### `print` (`print_prep.cli`)

```bash
uv run python -m studio.core print inspect --job ~/.print-prep/job --files a.stl
```

`print_prep` already ships a complete CLI with its own contract (`ok`/`command`/
`job`/`print_submitted`, exit codes 0/1/2/3 — see `print_prep/cli.py`). This is a
plain alias: everything after `print` goes to `print_prep.cli.main()` unparsed, so
output/exit code match `python -m print_prep.cli ...` exactly — it just spares a
script already using `studio.core` a second invocation style for printing.

## Calling it from something other than a shell script

Shell out with `subprocess`, as `tests/test_core_cli.py` does — no MCP client or
HTTP client needed, just "one process, one line of JSON on stdout, exit 0 or 1":

```python
import json, subprocess, sys
result = subprocess.run(
    [sys.executable, "-m", "studio.core", "editor", "inspect", "--doc", workspace_dir],
    cwd=plugin_root, capture_output=True, text=True, check=False,
)
payload = json.loads(result.stdout)
```
