> 中文：[CONTRIBUTING.zh-CN.md](CONTRIBUTING.zh-CN.md)

# Contributing

## Setup

```bash
make install
```

runs `uv sync --locked` (Python, pinned by `uv.lock`) and `npm ci` (JavaScript). Both
are idempotent; re-run after pulling changes that touch `pyproject.toml`,
`package.json`, or their lockfiles. This installs dependencies for development; to
also register the plugin with Codex, run `./install.sh` (macOS/Linux) or follow
"Manual install (any OS, incl. Windows)" in [docs/CONFIGURATION.md](docs/CONFIGURATION.md).
(`studio/mcp_server.py` is only a compat stub for `.mcp.json` files an older
install already generated; new installs point at `studio/shell/mcp_server.py`.)

## Run without Codex

```bash
make dev
```

starts the local HTTP backend (`studio/shell/server.py`) standalone and prints its URL.
Open it in a browser and append `?mock=1` to run the interface against built-in
sample data with no backend calls at all — useful for iterating on UI without a
Codex session or a real model loaded. `make stop` stops the backend `make dev`
started.

For quick one-off checks of the `studio.core` capability layer itself (recipes,
editor, tasks, observation) you don't need the HTTP backend either: run
`uv run python -m studio.core <group> <verb> --help` for the command list, or see
[docs/CORE_CLI.md](docs/CORE_CLI.md).

## Tests

```bash
make test       # everything
make test-py    # pytest only
make test-js    # node --test only
```

To run a single Python test file or test function:

```bash
uv run pytest tests/test_editor.py
uv run pytest tests/test_editor.py::test_plane_cut -v
```

Tests that need a real, locally installed Bambu Studio are marked
`@pytest.mark.bambu` and are excluded by default configuration when you filter them
out explicitly (`pytest -m "not bambu"`); running the full `make test`/`pytest -q`
without a filter will attempt them too, and they skip cleanly if Bambu Studio isn't
present. Set `PRINT_PREP_HOME` to a temporary directory in any test that touches
server state — never let a test read or write the real `~/.print-prep`.

## Lint and format

```bash
make lint     # ruff check .
make format   # ruff format .
```

Configuration lives in `pyproject.toml` under `[tool.ruff]`. A block of rules
(`E501`, `E701`/`E702`, `E402`, `E401`, `E741`, `F401`, `F841`) is temporarily
ignored — the earliest code in this repository was written in a compressed style
before a planned repo-wide `ruff format` pass. Do not write new code that relies on
those ignores; they exist to avoid a noisy diff on old code, not to license new
one-liners. `studio/web`, `studio/app`, `studio/city`, and `node_modules` are
excluded from Python linting entirely (they're JavaScript).

## Building the UI and committing `dist`

UI source lives in `studio/web` (browser UI + WebMCP bridge) and `studio/app` (the
MCP App bundle); the *built* output (`studio/app/dist/`, vendored assets under
`studio/web/vendor/`) is committed to the repository so a fresh clone works without
running a Node build. After changing anything under `studio/web` or `studio/app`:

```bash
npm run build:app
```

and commit the resulting changes under `dist`/`vendor` alongside your source change
in the same commit — a source-only diff that leaves `dist` stale will pass review
only if you flag it explicitly. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md#ui-build-pipeline)
for what each build step produces.

## Adding an MCP tool

1. Add the tool's declaration (`name`, `inputSchema`, `readOnly`, and either an HTTP
   `method`/`path` pair or a direct MCP-server implementation) to the relevant
   `studio/shell/*_schema.py` file, or to `studio/shell/tools_schema.py` for a tool with no
   dedicated schema file yet.
2. If it's HTTP-backed, add the matching route to `studio/shell/server.py`'s
   `StudioBackend`.
3. Regenerate the reference doc:

   ```bash
   make tools-doc
   ```

   which runs `scripts/gen_tool_reference.py` and rewrites `docs/TOOLS.md` from the
   same tool list the stdio MCP server assembles at runtime, so the document can
   never drift out of sync with what Codex actually sees. Commit the regenerated
   file.

A tool's `name` and, for HTTP-backed tools, its `path` are an external contract —
existing installs, saved recipes, and any documentation referencing the tool by name
break if you rename one without a compatibility plan. See
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for which files carry this contract.

## Adding a recipe

A recipe is data, not code — see [recipes/README.md](recipes/README.md) for the
full concept. To add one:

```
recipes/<id>/
  recipe.json    # schema "print-prep.recipe/1"; steps, tool bindings, acceptance
                 # criteria, provenance
  guide.md       # judgment calls and pitfalls, for both the AI and a person
```

Validation rules (enforced when a recipe loads, and described fully in
`SPEC_RECIPES.md`): every step names a real, existing tool; preset step parameters
are validated field-by-field and never allowed to be a path (a recipe cannot make
the plugin read or write a file of its choosing); `date` fields are `YYYY-MM-DD`;
`ref`/`note` are capped at 120 characters, `author`/`license` at 60, `version` at 20.
Recipes are re-scanned on every `GET /api/recipes` call, so dropping a new one into
`~/.print-prep/recipes/<id>/` (or `$PRINT_PREP_HOME/recipes/<id>/`) is picked up
without restarting the server, and shows up in the UI's recipe drawer tagged as
third-party.

## Adding a hosted-service adapter

Hosted adapters live under `studio/adapters/*_service.py` and are wired into the generic
dispatcher in `studio/adapters/services.py`. A new adapter must:

- Never hard-code a default `base_url` pointing at a private or company-internal
  endpoint — the only way an endpoint is used is if it's explicitly present in
  `services.json` (see [docs/CONFIGURATION.md](docs/CONFIGURATION.md#servicesjson-format)).
- Read its credential only through `key_env` — an environment variable name that
  `services.json` names but never itself contains a value for.
- Fail cleanly (a structured error) when a key is missing or a request is rejected,
  rather than crashing the server; no adapter is called at server startup.
- Be reachable through `studio/adapters/service_connections.py`'s probe/execute path if it
  needs a "test connection" step in the UI.

## Adding a user-facing message

Text a person can read — error messages, action summaries, task-template titles,
provider labels — is never written inline in Python. Both languages live in a
message catalog and the code refers to a stable code:

- Register the code in the catalog of the layer you are in
  (`studio/core/messages*.py`, `studio/adapters/messages*.py`,
  `studio/shell/messages.py`; `print_prep/messages.py` for the standalone print
  package) with both `"en"` and `"zh-CN"`. Codes are `<module>.<snake_case_meaning>`
  and become part of the API once shipped: every JSON error body carries
  `code`, `message` and `params`.
- Raise with `EditorError.coded("module.meaning", **params)` (or keep another
  exception type and build its text with `studio.i18n.render(...)`); build
  summaries, titles and labels with `render(...)` at the point they are returned,
  not at import time, so they follow the request language.
- The language comes from `STUDIO_LANG` for the MCP process and from
  `Accept-Language` per HTTP request (the panel sends its own locale). Tests pin
  `STUDIO_LANG=zh-CN`; new tests should assert the `code`, not the wording.
- Panel text goes through `t("key", { name })` in JS, or `data-i18n="key"` /
  `data-i18n-attr="title=key"` on static markup (`studio/web/i18n.js`), with the key in
  both `studio/web/locales/zh-CN.js` (the source of truth) and
  `studio/web/locales/en.js`, keys sorted. `npm test` fails if the two key sets differ,
  if a key used in the sources is missing, or if Chinese appears outside comments in
  `studio/web` / `studio/app` (`tests/test_i18n_source_guard.mjs`; `mock.js` is the one
  exempt fixture). Keep English values short and literal; use `{placeholders}` instead of
  concatenating fragments.

## Documentation conventions

- English is primary. A Chinese mirror (`README.zh-CN.md`, `SPEC.zh-CN.md`,
  `CONTRIBUTING.zh-CN.md`, and `docs/zh-CN/<NAME>.md` for each `docs/<NAME>.md`)
  tracks the English source; update both in the same change when you touch either.
- `docs/history/` is frozen — dated validation/proposal records kept for provenance,
  not maintained going forward. Don't add new content there or expect it to be kept
  current; new documentation goes in `docs/` proper.
- Don't reference internal company infrastructure, internal hostnames, or another
  product's internals in anything meant to ship publicly.

## What must never be committed

- API keys, tokens, or any credential value (see
  [docs/CONFIGURATION.md](docs/CONFIGURATION.md) for where real credentials belong —
  never `services.json`, always the environment or the local encrypted store).
- Internal hostnames, internal ticket/wiki links, or other company-internal
  references.
- Code or written analysis copied from, or describing how a competitor's product was
  reverse-engineered or analyzed. Comparing capabilities in the abstract is fine;
  describing *how a competitor's internals were inspected* is not.

## Reporting an issue

Open an issue with: what you ran (command or Codex prompt), what you expected, what
happened instead, and the relevant lines from `~/.print-prep/studio.log`. If it's
adapter-related, include which provider (never the key itself). The `bug` label must
exist in the repository for the bug report form's `labels:` field to apply (GitHub
silently drops unknown labels).

## Reporting an edit that went wrong

If you pointed at a part and asked for a change that came out wrong, use the
[edit report template](.github/ISSUE_TEMPLATE/edit-report.yml) instead of a plain
issue; on GitLab, pick the "Edit report" description template from
`.gitlab/issue_templates/`. Every report needs four things: what you pointed at
(viewport click, object list, a `studio_edit(action: "select")` call, or a part-chat
branch, plus the object id from `studio_get_state.workbench.objects`), what you asked
for, what happened, and what you expected. The `edit-report` and `bug` labels must
exist in the repository for the forms' `labels:` field to apply.
