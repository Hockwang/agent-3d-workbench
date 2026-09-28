> 中文：[zh-CN/CONFIGURATION.md](zh-CN/CONFIGURATION.md)

# Configuration

## Environment variables

Every environment variable actually read by the code, grep-verified against
`studio/`, `print_prep/`, and `scripts/`:

| Variable | Default | Read by | Meaning |
|---|---|---|---|
| `PRINT_PREP_HOME` | `~/.print-prep` | `studio/__init__.py` | Root of all local server state (session file, log, default job dir). Every other state path below is relative to this unless noted. Tests must point this at a temporary directory rather than touching the real one. |
| `PRINT_PREP_WORKSPACES_HOME` | same as `PRINT_PREP_HOME` | `studio/core/city.py`, `studio/core/workspaces.py`, `studio/__init__.py` (passed through to the spawned server) | Root of the per-workspace registry (`workspaces/<id>/...`), kept separate from a scoped `PRINT_PREP_HOME` so cross-chat/cross-worktree workspace lookup still resolves to the original registry even when a single session's home is nested elsewhere. |
| `PRINT_PREP_WORKSPACE_ID` | none | `studio/core/workspaces.py` | Fallback workspace id when a tool call omits `workspace_id`. Hosts without a per-conversation task ID (Claude Code, plain MCP clients) set it in the server environment; `install.sh --claude` does so. |
| `WORKBENCH_SERVICE_CONFIG` | `~/.config/codex-3d/services.json` | `studio/adapters/services.py`, `studio/adapters/service_connections.py` | Path to the hosted-adapter configuration file (see below). The private credential store lives beside it, at the same path with `connections.private.json` as the filename. |
| `WORKBENCH_BLENDER` | none (falls back to a per-platform default, then `blender` on `PATH` — see below) | `studio/core/tasks.py` | Explicit path to a Blender executable, for Blender-backed tasks (rigging, retargeting, mesh templates). |
| `CODEX_HOME` | `~/.codex` | `studio/shell/codex_bridge.py` | Where the Codex CLI's own state lives; used to talk to `codex app-server` for thread identity. |
| `BAMBU_STUDIO_APP` | none (falls back to a per-platform default — see below) | `print_prep/profiles.py` | Path to the Bambu Studio application (the `.app` bundle on macOS; the executable itself on Windows/Linux), used to export/open print projects. |
| `BAMBU_STUDIO_PATH` | derived from `BAMBU_STUDIO_APP` | `print_prep/profiles.py` | Path to the Bambu Studio command-line binary, used for headless slice checks. On macOS this is inside the `.app` bundle; on Windows/Linux it's the same executable as `BAMBU_STUDIO_APP`. |
| `MFG_BAMBU_PROFILE_ROOT` | derived from `BAMBU_STUDIO_APP` | `print_prep/profiles.py` | Path to Bambu Studio's bundled printer/material profile data. |
| `STUDIO_LANG` | `en` | `studio/i18n.py` | Process-wide fallback language for backend error messages (see "Language / `STUDIO_LANG`" below). Accepts `en`, `zh`, `zh-CN`, or any `zh-*`/`zh_*` tag (case-insensitive); anything else, or unset, means English. |

None of these are required for local editing, tasks, motion, or observation to work.
`BAMBU_STUDIO_APP`/`BAMBU_STUDIO_PATH`/`MFG_BAMBU_PROFILE_ROOT` only matter for the
print-preparation workspace's export/check/send steps, and `WORKBENCH_BLENDER` only
for Blender-backed task templates; both fail with a clean, JSON-shaped error rather
than crashing when the underlying tool is absent.

### Per-platform defaults for Bambu Studio / Blender

Neither Bambu Studio nor Blender has a single install location across operating
systems, so `print_prep/profiles.py` and `studio/core/tasks.py` pick a default at
runtime based on `sys.platform`, always overridable by the environment variables
above:

| | macOS | Windows | Linux |
|---|---|---|---|
| Bambu Studio (`BAMBU_STUDIO_APP`) | `/Applications/BambuStudio.app` | `%ProgramFiles%\Bambu Studio\bambu-studio.exe` (or `%LOCALAPPDATA%\Programs\Bambu Studio\...`) | whatever `bambu-studio` resolves to on `PATH`, else `~/.local/bin/bambu-studio` |
| Bambu Studio profiles (`MFG_BAMBU_PROFILE_ROOT`) | `<app>/Contents/Resources/profiles/BBL` | `%APPDATA%\BambuStudio\system\BBL` | `~/.config/BambuStudio/system/BBL` |
| Blender (`WORKBENCH_BLENDER`) | `/Applications/Blender.app/Contents/MacOS/Blender` | newest `C:\Program Files\Blender Foundation\Blender */blender.exe` | `blender` on `PATH`, else `/usr/bin/blender`, `/snap/bin/blender`, `~/.local/bin/blender` |

A Flatpak install of Bambu Studio has no single executable path on disk; point
`BAMBU_STUDIO_APP` (or `BAMBU_STUDIO_PATH`) at a one-line wrapper script that runs
`flatpak run com.bambulab.BambuStudio "$@"` instead. The Windows/Linux profile-root
defaults are unverified across every packaging — if `print_prep` reports the
profile directory as missing, set `MFG_BAMBU_PROFILE_ROOT` to wherever your install
actually keeps `machine/`, `process/`, and `filament/` JSON.

### Language / `STUDIO_LANG`

Backend error messages come from a small code -> `{"en": ..., "zh-CN": ...}`
catalog (`studio/i18n.py`, populated by `studio/core/messages.py`,
`studio/shell/messages.py`, ...; see `docs/ARCHITECTURE.md` -> "Messages and
languages"). Every backend raise and every user-facing string in an API payload goes
through this catalog. Recipe files (`recipes/*/recipe.json`, `guide.md`) and
`.codex-plugin/plugin.json` are content and stay in one language on purpose. Text that a
task writes into an artifact at run time (for example the check details in a `shell-kit`
`report.json`) is rendered in the language of the process that wrote it and does not
change afterwards.

Two things pick the language for a converted message:

- **The local HTTP server** (`studio/shell/server.py`) reads the request's
  `Accept-Language` header and uses it for that request only, falling back to
  `STUDIO_LANG` (then English) if the header is absent or names a language
  the catalog doesn't have.
- **The stdio MCP server** (`studio/shell/mcp_server.py`) reads `STUDIO_LANG` once at
  process startup and sends it as `Accept-Language` on every call it proxies to the
  local HTTP server, so tool results follow the MCP server's environment even when the
  per-workspace HTTP server was started earlier under a different setting. `install.sh`
  copies the `STUDIO_LANG` present in its own environment into the generated `.mcp.json`
  (`STUDIO_LANG=zh-CN ./install.sh`); `install.sh --claude` passes it to `claude mcp add`
  (default `en`).
- **The panel** (the browser page and the MCP App) picks its own locale in this order: a
  choice stored in that browser by the panel's language toggle (`localStorage` key
  `studio.locale`), then the `STUDIO_LANG` of the process that served the page when one was
  set (stamped into `<meta name="studio-language">` by `studio/shell/server.py` for the
  browser page and by `studio/shell/app_resources.py` for the MCP App; left empty when
  `STUDIO_LANG` is unset), then the browser language, then `zh-CN`. So
  `STUDIO_LANG=zh-CN ./install.sh` makes the panel Chinese too, a default install follows
  the browser, and the toggle in the top bar overrides both for one browser. The panel sends its locale as
  `Accept-Language`, so backend messages shown in it follow the same choice. All panel
  strings live in `studio/web/locales/{zh-CN,en}.js`; `npm test` fails if the two key sets
  differ or if hard-coded Chinese reappears in the UI sources.

## State and config file locations

| Location | Purpose |
|---|---|
| `PRINT_PREP_HOME/studio.json` | The running local HTTP server's session file: pid, port, an access token, the bound job directory, mode `0600`. |
| `PRINT_PREP_HOME/studio.log` | The local server's stdout/stderr. |
| `PRINT_PREP_HOME/job/` | The default, single-workspace job directory (legacy layout, still used when no per-workspace id is in play). |
| `PRINT_PREP_WORKSPACES_HOME/workspaces/<workspace_id>/job/` | Per-folder-project / per-Codex-task job directory. |
| `PRINT_PREP_WORKSPACES_HOME/workspaces/<parent>/part-chat/` | Part-chat authorization and log for a workspace's child conversations. |
| `PRINT_PREP_HOME/recipes/<id>/` | User-installed recipes (`recipe.json` + `guide.md`), read alongside the ones built into the repository's own `recipes/` directory. |
| `~/.config/codex-3d/services.json` (or `$WORKBENCH_SERVICE_CONFIG`) | Hosted-adapter configuration: which providers are enabled, their `base_url`, and which environment variable holds each one's key. Never contains a credential value itself. |
| `~/.config/codex-3d/connections.private.json` (same directory as the file above) | The private credential store: an encrypted envelope, file mode `0600`. This is filesystem permission protection, not OS-keychain-grade encryption. |
| `~/plugins/print-prep` | Symlink Codex loads the plugin from, created by `install.sh` and pointing back at the cloned repository. |

Every path under `PRINT_PREP_HOME`/`PRINT_PREP_WORKSPACES_HOME` respects those two
environment variables; nothing here is hard-coded to a specific user account.

## `services.json` format

A hosted adapter is only used if it is explicitly configured here — there is no
default hosted endpoint, and no adapter is called at server startup. Example
(credential values are never stored in this file; only the name of the environment
variable that holds one):

```jsonc
{
  "providers": {
    "my-hunyuan": {
      "title": "My Hunyuan endpoint",
      "adapter": "hunyuan-responses",
      "base_url": "https://your-own-gateway.example.com/v1",
      "key_env": "MY_HUNYUAN_API_KEY",
      "enabled": true
    }
  }
}
```

- `adapter` selects which client module in `studio/adapters/*_service.py` handles requests for
  this provider (`hunyuan-responses`, `seed3d-chat`, `lux3d`, `assembly`, `meshy`,
  `tripo`, ...).
- `base_url` is validated before use and is never defaulted to a private endpoint by
  the code itself; every built-in provider template ships with `enabled` effectively
  off until a real key is present. The `hunyuan` and `seed3d` built-ins ship with
  `base_url: ""` and `requires_base_url: true` — they speak an OpenAI-compatible
  gateway protocol, not one specific vendor's API, so there is no single correct
  default to hard-code; `studio_capabilities`/the UI show them as needing a
  `base_url` until you set one, and `prepare()`/`run()` refuse to submit until you
  do (see [Hunyuan](HUNYUAN_API.md) and [BYOK services](BYOK_SERVICES.md)).
- `internal_origin` is an Assembly-only, opt-in field for the fixed
  `transport: "assembly-prodtest-http"` route: see [Assembly](ASSEMBLY_API.md) for
  what it does and its constraints (no credentials, no path, no query string).
- `local_inputs_allowed` (default `true`) declares whether `studio_task`'s `inputs`
  (local file paths) may be attached to a task on this provider. It defaults to
  `false` on the built-in `assembly` entry, which only accepts remotely reachable
  URLs and never auto-uploads a local file; a custom provider that never sets this
  key keeps today's "local inputs allowed" behavior.
- `default_timeout_seconds` (default `600`) is the task timeout used when a
  `studio_task` call does not pass its own `timeout_seconds`. The built-in
  `assembly`, `hunyuan`, `seed3d`, `lux3d`, and `lux3d-global` entries set this to
  `1800`, since those adapters' remote jobs commonly run longer than the
  Meshy/Tripo-style default; a custom provider that never sets this key keeps the
  `600`-second default.
- Both of the two keys above are also backfilled for a BYOK connection saved
  through the panel (or a plain `services.json` entry) from before either key
  existed in `BUILTINS`: `services.config()` fills in whichever one is still
  missing from the built-in template the connection was created from
  (`connection_template`), or, for an untemplated entry, from the first
  `BUILTINS` entry sharing its `adapter` id — so a connection saved under an
  older version of this plugin keeps its intended timeout and local-input
  policy after an upgrade instead of silently falling back to `600`/`true`. A
  value already present on the saved entry always wins over the backfill.
- `allow_unquoted` (Lux3D adapter only, default `false`) opts a `lux3d`/`lux3d-global`
  entry out of the server-side quote requirement, so a paid operation can be
  submitted without a prior `quote_id`; the built-in templates never set it — see
  [Lux3D](LUX3D.md) for the quote-to-collection flow this bypasses.
- `key_env` names an environment variable the process's own environment must already
  provide; the file itself never holds the key value. A UI-entered key is encrypted
  client-side, decrypted only in-process, and stored in the adjacent
  `connections.private.json`, not in `services.json`.
- Payloads and URLs are validated (`validate_url`/`validate_payload` in
  `studio/adapters/services.py`) before any request is sent, and outgoing requests never
  follow redirects.

See [BYOK services](BYOK_SERVICES.md) for the end-to-end setup flow through the UI,
and [Assembly](ASSEMBLY_API.md) / [Hunyuan](HUNYUAN_API.md) / [Lux3D](LUX3D.md) for
provider-specific detail.

## `.mcp.json`

`install.sh` generates `.mcp.json` at the repository root; it is not tracked in git
and does not exist in a fresh clone until you run the installer. Its shape:

```json
{
  "mcpServers": {
    "print_prep_studio": {
      "command": "/absolute/path/to/plugin/.venv/bin/python",
      "args": ["/absolute/path/to/plugin/studio/shell/mcp_server.py"],
      "cwd": "/absolute/path/to/plugin"
    }
  }
}
```

`command` points at the plugin's own virtual environment interpreter (through the
`~/plugins/print-prep` symlink) rather than relying on `uv`/`python3` being on
`PATH`, since Codex desktop launches subprocesses with a short one. If you are
wiring this up by hand instead of running `install.sh`, write this file with real
absolute paths substituted in; the MCP server key (`print_prep_studio`) and the
script path (`studio/shell/mcp_server.py`) are the only two Codex reads.

### Manual install (any OS, incl. Windows)

`install.sh` is bash, so it only runs on macOS/Linux out of the box. On any OS
(including Windows, or macOS/Linux without running the script) you can wire the
plugin up by hand:

1. `uv sync` inside the plugin directory to create `.venv` and install dependencies.
2. Copy [`.mcp.json.example`](../.mcp.json.example) to `.mcp.json` in the same
   directory and replace `<ABSOLUTE_PATH_TO_PLUGIN>` with the plugin's real absolute
   path. On Windows, the interpreter is at `.venv\Scripts\python.exe` (not
   `.venv/bin/python`), and use backslashes or forward slashes consistently for the
   other two paths — both work in a JSON string as long as you don't mix an
   unescaped backslash with something after it that looks like an escape sequence.
3. Register the plugin with Codex (`codex plugin add <name>@<scope>`, or however
   your Codex build discovers a local `.mcp.json`).
4. Set any environment variables you need from the table above (`WORKBENCH_BLENDER`,
   `BAMBU_STUDIO_APP`/`BAMBU_STUDIO_PATH`, `WORKBENCH_SERVICE_CONFIG`, ...) in the
   environment that launches Codex, then restart/reconnect the backend.

None of this requires `install.sh`, the `~/plugins` symlink, or the marketplace
file it maintains — those are conveniences for the common case, not a requirement
of the MCP contract itself.

## Ports

The local HTTP backend listens on `127.0.0.1:8977` by default (`DEFAULT_PORT` in
`studio/__init__.py`); `scripts/studio.py start` accepts a different port
explicitly if 8977 is taken.

## Platform notes

`BAMBU_STUDIO_APP`/`WORKBENCH_BLENDER`'s defaults, and the commands used to
launch/detect Bambu Studio (`open -a` on macOS, `os.startfile` on Windows,
`xdg-open` on Linux) and check whether it's already running (`pgrep` on
macOS/Linux, `tasklist` on Windows), are all platform-dispatched — see
[Per-platform defaults](#per-platform-defaults-for-bambu-studio--blender) above. You
can always override any of them with the explicit environment variables; if the
underlying binary still can't be found or launched, the affected step fails with a
clean, JSON-shaped error rather than crashing the server. Editing, tasks that don't
need Blender, motion, and observation have no OS-specific path in their own code.
