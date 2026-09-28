#!/usr/bin/env bash
# print-prep installer (idempotent). macOS and Linux; Windows users follow the
# manual install steps in docs/CONFIGURATION.md instead.
#
# Usage:
#   ./install.sh                    install (idempotent); only prints the next command, doesn't run it
#   ./install.sh --add              install, then also run `codex plugin add print-prep@personal`
#   ./install.sh --claude           install, then register the MCP server with Claude Code (user scope,
#                                   name codex-3d-studio); the Codex CLI is optional in this mode
#   ./install.sh --uninstall        only print the uninstall steps; make no changes
#   ./install.sh --uninstall --yes  actually uninstall: remove the symlink, drop the marketplace entry
#                                   (backs up the marketplace file first)
#
# This script is only meant to be run by hand (by the user or the parent
# session); it is never invoked automatically during implementation/testing.
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_NAME="print-prep"
PLUGINS_DIR="${HOME}/plugins"
LINK="${PLUGINS_DIR}/${PLUGIN_NAME}"
MARKETPLACE_DIR="${HOME}/.agents/plugins"
MARKETPLACE_FILE="${MARKETPLACE_DIR}/marketplace.json"
# The one line to change if studio/shell/mcp_server.py ever moves.
MCP_ENTRY="studio/shell/mcp_server.py"
# If STUDIO_LANG is set when this script runs (e.g. STUDIO_LANG=zh-CN ./install.sh), the
# generated Codex .mcp.json carries it as the server's env, so the backend answers Codex
# in that language; unset means the server default (en).

DO_ADD=0
DO_CLAUDE=0
DO_UNINSTALL=0
DO_YES=0
HAVE_CODEX=1
# Claude Code has no per-conversation task ID to pass as workspace_id, so the
# server gets one fixed workspace via PRINT_PREP_WORKSPACE_ID (override with
# CLAUDE_WORKSPACE_ID=... ./install.sh --claude). STUDIO_LANG defaults to en.
CLAUDE_SERVER_NAME="codex-3d-studio"
CLAUDE_WORKSPACE_ID="${CLAUDE_WORKSPACE_ID:-claude-code}"

for arg in "$@"; do
  case "$arg" in
    --add) DO_ADD=1 ;;
    --claude) DO_CLAUDE=1 ;;
    --uninstall) DO_UNINSTALL=1 ;;
    --yes) DO_YES=1 ;;
    *)
      echo "Unknown argument: $arg" >&2
      echo "Usage: $0 [--add] [--claude] [--uninstall [--yes]]" >&2
      exit 1
      ;;
  esac
done

log() { echo "[print-prep/install] $*" >&2; }

# Prefer python3, fall back to python (some Linux distros/PATH setups only have one).
PYTHON_BIN="$(command -v python3 2>/dev/null || command -v python 2>/dev/null || true)"
if [ -z "$PYTHON_BIN" ]; then
  log "error: neither python3 nor python found on PATH; install Python 3 and retry."
  exit 1
fi

# ---------------------------------------------------------------------------
# Uninstall path
# ---------------------------------------------------------------------------
if [ "$DO_UNINSTALL" -eq 1 ]; then
  log "Uninstall steps (printed only by default; add --yes to actually run them):"
  echo "  1) codex plugin remove ${PLUGIN_NAME}@personal"
  if [ -L "$LINK" ]; then
    echo "  2) rm \"${LINK}\"  (currently points to: $(readlink "$LINK"))"
  else
    echo "  2) rm \"${LINK}\"  (currently: not a symlink or doesn't exist; will be skipped)"
  fi
  echo "  3) remove the \"${PLUGIN_NAME}\" plugin entry from ${MARKETPLACE_FILE} (backs up the whole file first)"

  if [ "$DO_YES" -ne 1 ]; then
    log "No --yes given; none of the above ran. Re-run with --yes once you've confirmed."
    exit 0
  fi

  # Confirm the marketplace file still parses before doing anything irreversible
  # (otherwise we could leave it half-uninstalled).
  if [ -f "$MARKETPLACE_FILE" ]; then
    if ! "$PYTHON_BIN" -c 'import json,sys; json.load(open(sys.argv[1], encoding="utf-8"))' "$MARKETPLACE_FILE"; then
      log "error: ${MARKETPLACE_FILE} is not valid JSON; made no changes. Fix it by hand and re-run."
      exit 1
    fi
  fi

  log "Running codex plugin remove ${PLUGIN_NAME}@personal ..."
  if ! codex plugin remove "${PLUGIN_NAME}@personal"; then
    log "codex plugin remove failed, or the plugin was never registered with codex; continuing."
  fi

  if [ -L "$LINK" ]; then
    rm "$LINK"
    log "Removed symlink ${LINK}"
  elif [ -e "$LINK" ]; then
    log "warning: ${LINK} exists but is not a symlink; left it alone for safety, please check by hand."
  else
    log "Symlink doesn't exist; skipping removal."
  fi

  if [ -f "$MARKETPLACE_FILE" ]; then
    BACKUP="${MARKETPLACE_FILE}.bak-$(date +%Y%m%d%H%M%S)"
    cp "$MARKETPLACE_FILE" "$BACKUP"
    log "Backed up the marketplace file to ${BACKUP}"
    "$PYTHON_BIN" - "$MARKETPLACE_FILE" "$PLUGIN_NAME" <<'PYEOF'
import json
import sys

path, name = sys.argv[1], sys.argv[2]
with open(path, "r", encoding="utf-8") as f:
    data = json.load(f)
plugins = data.get("plugins", [])
data["plugins"] = [p for p in plugins if p.get("name") != name]
with open(path, "w", encoding="utf-8") as f:
    json.dump(data, f, indent=1, ensure_ascii=False)
    f.write("\n")
PYEOF
    log "Removed the ${PLUGIN_NAME} entry from the marketplace file."
  else
    log "Marketplace file doesn't exist; skipping."
  fi

  log "Uninstall complete."
  exit 0
fi

# ---------------------------------------------------------------------------
# Install path
# ---------------------------------------------------------------------------
log "Plugin source directory: ${SRC}"

if ! command -v uv >/dev/null 2>&1; then
  log "error: uv not found (https://docs.astral.sh/uv/); install it and retry."
  exit 1
fi

if ! command -v codex >/dev/null 2>&1; then
  if [ "$DO_CLAUDE" -eq 1 ] && [ "$DO_ADD" -eq 0 ]; then
    HAVE_CODEX=0
    log "codex CLI not found; skipping the Codex marketplace step (--claude mode)."
  else
    log "error: codex CLI not found; install it and retry (or use --claude for Claude Code only)."
    exit 1
  fi
fi

# Best-effort heads-up only; the actual runtime discovery (BAMBU_STUDIO_APP /
# BAMBU_STUDIO_PATH, see docs/CONFIGURATION.md) is what matters at run time.
case "$(uname -s)" in
  Darwin) BAMBU_DEFAULT="/Applications/BambuStudio.app" ;;
  Linux) BAMBU_DEFAULT="$(command -v bambu-studio 2>/dev/null || true)" ;;
  *) BAMBU_DEFAULT="" ;;
esac
if [ -z "${BAMBU_STUDIO_APP:-}" ] && { [ -z "$BAMBU_DEFAULT" ] || [ ! -e "$BAMBU_DEFAULT" ]; }; then
  log "warning: Bambu Studio not found in its default location for this OS. inspect/orient/arrange don't need it, but export/check/open do; see docs/CONFIGURATION.md for BAMBU_STUDIO_APP/BAMBU_STUDIO_PATH."
fi

log "Syncing dependencies (uv sync --locked --project ${SRC})..."
uv sync --locked --project "$SRC"

mkdir -p "$PLUGINS_DIR"

if [ -L "$LINK" ]; then
  CURRENT_TARGET="$(readlink "$LINK")"
  if [ "$CURRENT_TARGET" != "$SRC" ]; then
    log "error: ${LINK} is already a symlink, but points elsewhere (${CURRENT_TARGET}); not overwriting. Remove it by hand and re-run."
    exit 1
  fi
  log "Symlink already exists and is correct: ${LINK} -> ${SRC} (skipping)"
elif [ -e "$LINK" ]; then
  log "error: ${LINK} already exists and is not a symlink; not overwriting. Remove it by hand and re-run."
  exit 1
else
  ln -s "$SRC" "$LINK"
  log "Created symlink: ${LINK} -> ${SRC}"
fi

# Generate the MCP config: point straight at the plugin's own virtualenv interpreter
# (Codex desktop launches subprocesses with a short PATH that may not have `uv` on
# it), with absolute paths through the ~/plugins symlink.
VENV_PY="${LINK}/.venv/bin/python"
if [ ! -x "${SRC}/.venv/bin/python" ]; then
  log "error: ${SRC}/.venv/bin/python doesn't exist; did uv sync fail?"
  exit 1
fi
"$PYTHON_BIN" - "$SRC/.mcp.json" "$VENV_PY" "$LINK" "$MCP_ENTRY" "${STUDIO_LANG:-}" <<'PYEOF'
import json
import sys

out, py, root, entry, lang = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5]
server = {
    "command": py,
    "args": [root + "/" + entry],
    "cwd": root,
}
if lang:
    server["env"] = {"STUDIO_LANG": lang}
cfg = {"mcpServers": {"print_prep_studio": server}}
with open(out, "w", encoding="utf-8") as f:
    json.dump(cfg, f, indent=2, ensure_ascii=False)
    f.write("\n")
PYEOF
log "Generated MCP config at ${SRC}/.mcp.json${STUDIO_LANG:+ (STUDIO_LANG=${STUDIO_LANG})}"

if [ "$HAVE_CODEX" -eq 1 ]; then
mkdir -p "$MARKETPLACE_DIR"

MARKET_RESULT="$("$PYTHON_BIN" - "$MARKETPLACE_FILE" "$PLUGIN_NAME" <<'PYEOF'
import json
import os
import sys
import time

path, name = sys.argv[1], sys.argv[2]
entry = {
    "name": name,
    "source": {"source": "local", "path": "./plugins/" + name},
    "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
    "category": "Productivity",
}

raw = None
if os.path.exists(path):
    with open(path, "r", encoding="utf-8") as f:
        raw = f.read()
    data = json.loads(raw)  # invalid JSON -> traceback, nothing written
else:
    data = {"name": "personal", "interface": {"displayName": "Personal"}, "plugins": []}

plugins = data.setdefault("plugins", [])
if any(p.get("name") == name for p in plugins):
    print("exists")
    sys.exit(0)

backup = ""
if raw is not None:
    backup = path + ".bak-" + time.strftime("%Y%m%d%H%M%S")
    with open(backup, "w", encoding="utf-8") as f:
        f.write(raw)
plugins.append(entry)
tmp = path + ".tmp"
with open(tmp, "w", encoding="utf-8") as f:
    json.dump(data, f, indent=1, ensure_ascii=False)
    f.write("\n")
os.replace(tmp, path)
print("added " + backup)
PYEOF
)"
case "$MARKET_RESULT" in
  exists) log "${PLUGIN_NAME} is already in the marketplace file; left it unchanged." ;;
  added*)
    BACKUP_PATH="${MARKET_RESULT#added}"
    BACKUP_PATH="${BACKUP_PATH# }"
    if [ -n "$BACKUP_PATH" ]; then
      log "Backed up the previous marketplace file to ${BACKUP_PATH}"
    fi
    log "Registered ${PLUGIN_NAME} in the marketplace file ${MARKETPLACE_FILE}."
    ;;
  *) log "error: unexpected output while registering the marketplace file: ${MARKET_RESULT}"; exit 1 ;;
esac
fi

log "Install complete."

if [ "$DO_ADD" -eq 1 ]; then
  log "Running codex plugin add ${PLUGIN_NAME}@personal ..."
  codex plugin add "${PLUGIN_NAME}@personal"
elif [ "$HAVE_CODEX" -eq 1 ]; then
  log "Next step for Codex (not run automatically; pass --add to have this script run it for you):"
  echo "  codex plugin add ${PLUGIN_NAME}@personal"
fi

# Claude Code (or any MCP client): the same stdio server, registered as a plain MCP
# server. No MCP App rendering there: ask for studio_open with presentation='browser'
# to get the panel URL, or use `uv run python -m studio.core` on the command line.
if [ "$DO_CLAUDE" -eq 1 ]; then
  if command -v claude >/dev/null 2>&1; then
    log "Registering ${CLAUDE_SERVER_NAME} with Claude Code (user scope, workspace ${CLAUDE_WORKSPACE_ID}) ..."
    claude mcp remove --scope user "${CLAUDE_SERVER_NAME}" >/dev/null 2>&1 || true
    claude mcp add --scope user "${CLAUDE_SERVER_NAME}" \
      -e "PRINT_PREP_WORKSPACE_ID=${CLAUDE_WORKSPACE_ID}" -e "STUDIO_LANG=${STUDIO_LANG:-en}" \
      -- "${VENV_PY}" "${LINK}/${MCP_ENTRY}"
    log "Done. In Claude Code, ask: open the 3D workbench in the browser (studio_open, presentation=browser)."
  else
    log "claude CLI not found; register by hand:"
    echo "  claude mcp add --scope user ${CLAUDE_SERVER_NAME} -e PRINT_PREP_WORKSPACE_ID=${CLAUDE_WORKSPACE_ID} -e STUDIO_LANG=en -- ${VENV_PY} ${LINK}/${MCP_ENTRY}"
  fi
fi
