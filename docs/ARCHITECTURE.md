# Architecture

> 中文：[zh-CN/ARCHITECTURE.md](zh-CN/ARCHITECTURE.md)

This document describes how the plugin is put together today, and the target layout
it is being refactored toward. Nothing here changes tool names, on-disk formats, or
MCP resource URIs — those are external contracts (see [Configuration](CONFIGURATION.md)).

## Components and request flow

```
Codex
  |  stdio (MCP protocol)
  v
studio/shell/mcp_server.py            stdio MCP server (official `mcp` SDK), registers 26
  |                             tools, forwards each `tools/call` to a route on the
  |                             local HTTP backend below.
  |  HTTP, loopback only (127.0.0.1)
  v
studio/shell/server.py                Handler: token + Origin + fetch-site checks, static
  |                             file serving, Server-Sent Events for live updates.
  |  in-process calls
  v
StudioBackend / Workspace /     Business logic: mesh editing (studio/core/editor.py),
Tasks / Observations / ...      the local task queue (studio/core/tasks.py), motion
                                 (studio/core/motion.py), observation, recipes, print
                                 preparation (print_prep/*), and the optional
                                 hosted-service adapters (studio/adapters/*_service.py).
```

The same HTTP routes are also reachable directly from the browser: the MCP App UI
(`studio/app`) and the plain browser UI (`studio/web`) both call `/api/*`, and
`studio/web/tools.js` additionally registers the tool set as page-level WebMCP tools
(`navigator.modelContext`-style) so a page open in a browser tab can be driven the
same way a Codex tool call would drive it. Live state changes (selection, undo,
task progress) reach open viewers over Server-Sent Events rather than polling.

Every request into the HTTP layer is checked for an origin/fetch-site header before
it is handled, since the server binds to loopback but is still reachable from any
page a browser has open; this is what keeps an arbitrary web page from silently
driving the workbench.

## On-disk state layout

All local state lives under `PRINT_PREP_HOME` (default `~/.print-prep`; see
[Configuration](CONFIGURATION.md) for every path and override):

- `studio.json` — the running server's session file (pid, port, token, job dir).
- `job/` — the default, single-workspace job directory (legacy layout).
- `workspaces/<workspace_id>/job/` — one job directory per folder project /
  Codex task, so concurrent tasks in different worktrees do not collide.
- `workspaces/<parent>/part-chat/` — part-chat authorization and log for a
  workspace's child conversations.
- `recipes/<id>/` — user-installed recipes, alongside the built-in ones shipped in
  the repository's own `recipes/` directory.

Hosted-adapter configuration (`services.json` and its paired private credential
store) lives separately, under `~/.config/codex-3d/` by default — see
[Configuration](CONFIGURATION.md) for its exact shape.

## Package layout

```
studio/__init__.py            stays (process helpers): PRINT_PREP_HOME resolution, session
                               file read/write, the "is it actually running" check shared by
                               server.py, mcp_server.py, and scripts/studio.py.
studio/paths.py                the single place that knows the tree — PLUGIN_ROOT, STUDIO_DIR,
                               CORE_DIR, ADAPTERS_DIR, SHELL_DIR, WEB_DIR, APP_DIR, APP_DIST_DIR,
                               CITY_DIR, KERNELS_DIR, RECIPES_DIR, SCRIPTS_DIR, PRINT_PREP_DIR.
studio/core/   (local)        editor.py geometry_store.py materials.py scene_assets.py city.py
                               collaboration.py branches.py history.py motion.py recipes.py
                               recipe_progress.py uploads.py viewer_presentation.py
                               assembly_review.py generated_editing.py projects.py workspaces.py
                               observation.py observation_render.py observation_run.py tasks.py
                               task_worker.py task_bootstrap.py task_operations.py
                               task_templates.py blender_catalog.py blender_ops.py + kernels/
                               editor_actions.py (action registry) print_state.py (print-prep state)
                               cli.py + __main__.py (python -m studio.core) messages.py messages_scene.py
                               (vendored geometry kernels: mechanical primitives, the offline
                               scene-viewer contract and adapters)
studio/adapters/ (hosted)     services.py (public façade: BUILTINS, config, catalog, prepare, run)
                               transport.py (pure HTTP: validate_url, request, download, service_transport)
                               registry.py (ServiceAdapter Protocol, register, adapter_for)
                               lux3d_service.py lux3d_commerce.py lux3d_upload.py hunyuan_service.py
                               seed3d_service.py assembly_service.py meshy.py tripo.py
                               service_connections.py service_diagnostics.py evaluation.py platform_preview.py
                               messages.py messages_assembly.py (bilingual message catalogs)
studio/shell/  (Codex + HTTP) server.py mcp_server.py tools_schema.py editor_schema.py
                               motion_schema.py task_schema.py evaluation_schema.py
                               recipe_schema.py codex_bridge.py part_chat.py app_resources.py
                               codex_projects.py messages.py
```

`studio/app/`, `studio/web/`, `studio/city/` (JS, unmoved), `print_prep/` (the print-preparation
library and CLI, unmoved — zero imports of `studio`, zero network), and
`.codex-plugin/plugin.json` / `install.sh` (plugin manifest and installer) sit alongside these
three Python packages; none of them move as part of this layering.

Layer rule, enforced by `tests/test_layering.py`: **core** is importable with zero MCP/HTTP/
Codex/network dependency — it must not import `studio.adapters` or `studio.shell`. **adapters**
wraps optional, key-gated hosted-service clients and may import `core`, but not `shell`.
**shell** owns every external wire contract (MCP tool names, `ui://` resource URIs, HTTP routes,
the Codex thread bridge) and may import anything in the package, since it is the one place
allowed to know how internal capabilities are wired up to the outside world. Where `core` needs
a `shell` capability (for example resolving a Codex thread's working directory), the dependency
is injected as a parameter by the caller in `shell` rather than imported from within `core`.

## Editor actions

`studio/core/editor.py`'s `Workspace._apply` dispatches every `studio_edit` action
by name; `city_`/`scene_`/`motion_` actions go straight to `city.py` /
`scene_assets.py` / `motion.py`, and everything else — `import`, `transform`,
`plane_cut`, `material`, `inspect`, and so on — is looked up in the declarative
registry in `studio/core/editor_actions.py` (`ACTIONS: dict[str, ActionSpec]`),
which pairs each action name with its handler function and a few flags
(`snapshot`, `requires_selection`, `blocks_motion_scene`, `read_only`) describing
exactly what `_apply`/`Workspace.execute` do with that name — so `_apply` itself
is just validate (cross-subsystem guards) → look up (this registry) → run (the
handler) → post-process (none needed, each handler returns its own final result).
Adding a new core action means writing one function and one `@action(...)`
registration in that module, not editing a long if/elif chain; see its module
docstring for the exact steps, and `tests/test_editor_actions.py` for the test
that keeps this registry and the `studio_edit` schema enum from drifting apart.

## Using the core layer directly

`python -m studio.core` (`studio/core/cli.py`) is a second, much thinner adapter than
`studio/shell/`: an argparse CLI that calls `studio.core.recipes`/`editor`/`tasks`/
`observation` directly, in-process, with no Codex and no HTTP server involved. It
exists so a caller that isn't Codex — a Blender add-on, another agent's skill — can
reach the same capabilities by shelling out to one process and reading one line of
JSON from stdout, instead of speaking MCP or HTTP. It reads
`studio/core/tool_schemas.json` (a checked-in snapshot of
`studio.shell.tools_schema.get_tools()`) rather than importing `studio.shell`, which
is how it stays on the `core` side of the layer rule above. See
[docs/CORE_CLI.md](CORE_CLI.md) for the full command reference.

## Messages and languages

Every string a person can read — error messages, action summaries, task-template
titles and descriptions, provider labels, CLI help — comes from a message
catalog, never from a literal in the code path. `studio/i18n.py` holds the
registry: `MESSAGES` maps a code to `{"en": ..., "zh-CN": ...}`; `register()`
adds entries; `render(code, **params)` returns the text in the current
language (falling back en -> zh-CN -> the code itself, so it never raises).
`studio.i18n` sits outside `core`/`adapters`/`shell` so every layer may import
it. Codes are `<module>.<snake_case_meaning>` and are part of the API once
shipped.

Catalogs live next to the code they serve and are imported (for their
`register()` side effect) from each package's `__init__.py`:

| Layer | Catalog files | Covers |
|---|---|---|
| `studio/core` | `messages.py`, `messages_scene.py`, `messages_tasks.py`, `messages_observation.py`, `messages_projects.py`, `messages_workspaces.py`, `messages_cli.py` | editor, materials, history, uploads; scene/city/motion; tasks and templates; observation and print state; projects and recipes; workspaces; `python -m studio.core` |
| `studio/adapters` | `messages.py`, `messages_assembly.py` | Lux3D, Seed3D, Meshy, Tripo, the services facade; Hunyuan, assembly, evaluation, transport, registry, diagnostics |
| `studio/shell` | `messages.py` | HTTP error bodies, MCP server, Codex bridge, part chat |
| `print_prep` | `messages.py` | the standalone print-preparation package |

`print_prep` may not import `studio` (`tests/test_layering.py`), so it carries
its own tiny copy of the registry with a `language_provider` hook;
`studio/i18n.py` points that hook at `get_language()` when both are loaded, so
the language still follows the request. MCP tool *descriptions*
(`studio/shell/*_schema.py`, `docs/TOOLS.md`) are English only: they are read
by the model, not shown to a person.

Raise sites use `EditorError.coded(code, **params)` (`studio/core/editor.py`):
it renders the message in the current language and stores `code`/`params` on
the exception, so every JSON error body carries
`{"ok": false, "error": {"code", "message", "params"}}`. Where an existing wire
code must survive (`revision_conflict`, `busy`, `bad_arguments`, ...),
`coded(message_code, code=wire_code)` keeps the two apart. Other exception
types (`RuntimeError`, `ValueError`, `UndoConflict`, `BridgeError`) keep their
type and build their text with `render()`. Task-template catalogs (`CATALOG`
lists in `task_operations.py`, `blender_catalog.py`, `observation.py`, ...)
hold codes in their display fields and are rendered per request by
`task_templates.localized_catalog()`.

The current language is a `contextvars.ContextVar`
(`studio.i18n.current_language`), set per request rather than globally so
concurrent requests in different languages don't interfere:

- `studio/shell/server.py` sets it from the request's `Accept-Language` header
  (falling back to `STUDIO_LANG`) before dispatching and resets it afterwards.
  The browser UI sends its own locale in that header (`studio/web/api.js`), so
  backend messages follow the panel's language toggle.
- `studio/shell/mcp_server.py` sets it once from `STUDIO_LANG` at process
  startup; task subprocesses inherit the same environment variable.
- Tests pin `STUDIO_LANG=zh-CN` (`tests/conftest.py`) so the original Chinese
  assertions still hold; new tests should assert the `code`.

Known exceptions: `studio/core/observation_render.py` runs inside Blender
without the `studio` package on its path and picks its one message from
`STUDIO_LANG` directly; `studio/core/blender_ops.py` and the vendored kernels
under `studio/core/kernels/` raise English-only `ValueError`s. The panel's own
strings live in `studio/web/locales/{zh-CN,en}.js` (`studio/web/i18n.js`,
`t("key")`); `npm test` fails if the two files' key sets differ. See
`docs/CONFIGURATION.md` -> "Language / `STUDIO_LANG`" for the user-facing
behaviour and `CONTRIBUTING.md` -> "Adding a user-facing message" for the
workflow.

## UI build pipeline

The MCP App and browser UI are prebuilt and their output is committed to the
repository (`studio/app/dist/`, `studio/web/vendor/`), so a fresh clone works without
a Node build step. To rebuild after changing UI source:

```bash
npm run build:app
```

which runs, in order: `build:ui` (`scripts/build_ui_assets.mjs`, vendors the browser
UI's JS/CSS/font dependencies), `scripts/build_gltf_codecs.mjs` (Draco/KTX2/Meshopt
codec assets), `scripts/build_motion.mjs` (the offline motion-evaluation Node
bundle), `scripts/build_delivery.mjs` and `scripts/build_assembly_review.mjs`
(delivery/exploded-view HTML bundlers), and finally `scripts/build_app.mjs` (the MCP
App bundle itself, `studio/app/dist/*`). `make build` runs the same sequence.
