> 中文：[zh-CN/DIRECT_PART_CHAT.md](zh-CN/DIRECT_PART_CHAT.md)

# Direct Part-Chat Branching

2026-09-23: implemented per the user-approved local-bridge design. The first time a user picks
"Create chat branch" from a part's right-click menu and authorizes local access for the current
project, the program creates a real Codex branch and binds it to that same project and that part.
The parent task receives no prompt; creation does not run `turn/start`, and while a goal is active,
`deferGoalContinuation` holds off automatic continuation. Once the user opens the branch, they type
their fix request there.

## Host support

| Capability | Codex desktop (sidebar panel) | Browser page (any MCP host, e.g. Claude Code) | Plain MCP client, no page |
|---|---|---|---|
| Creating a branch (right-click "Create chat branch") | yes | only when the page belongs to a Codex task: `create` reads the workspace id as the parent Codex thread (`studio/shell/part_chat.py`), so Claude Code's fixed `claude-code` id fails at `allow`/`create`; only `deny` goes through | no: no viewport to right-click; the `studio_part_chat` MCP tool is marked app-only, not verified whether a given client hides it |
| Opening it (deep link) | yes, via `ui/open-link` | only for a branch created from a Codex task, and if this machine's Codex desktop registered the `codex://` handler | no: nothing opens the returned URL |
| Authorization / revocation | yes, via the settings dialog | yes, same dialog, same local HTTP endpoint | not verified: no dialog is rendered; a direct tool call is untested |
| Codex CLI absent or too old | same for every host: `status` reports `available: false`; `create` raises an error | same | same |

The browser page is the exact UI Codex shows inline for this feature too, just talking to the local
backend over HTTP instead of MCP tool calls. A Claude Code user reaches it the same way as scene
editing, via `studio_open(presentation='browser')`. This whole feature is Codex-specific by design:
it exists to fork a real Codex thread through the officially installed CLI's App Server, so every
path through it needs that CLI and a Codex task as the parent, regardless of which host is driving
the AI; from Claude Code's fixed workspace id, `allow` and `create` fail and only `deny` succeeds.

## Access and Authorization

- `studio/shell/codex_bridge.py` starts a short-lived stdio App Server through the officially
  installed Codex CLI, using `initialize`, `thread/read`, `thread/fork`, and `thread/name/set`. It
  does not use a private IPC channel, a database, or a forged rollout, and it does not modify the
  running desktop process.
- `studio_part_chat` is an app-only MCP tool. The HTTP entry point reuses the existing local token,
  Host/Origin, and actor checks. There is no arbitrary-RPC, no command execution, and no path that
  lets a client specify a child ID.
- The `app-only` marking on `studio_part_chat`/`studio_ui_action` is an advisory hint for hosts that
  honor it; it does not by itself stop a model from calling either tool directly. What closes that
  path is a per-workspace nonce: `studio_open` mints it and returns it only in the MCP
  `CallToolResult`'s `_meta` (`studio/uiNonce`), a host-only channel never surfaced in `content` or
  `structuredContent`, which the model does read. The packaged UI picks the nonce up from
  `studio_open`'s tool result and attaches it to every `studio_ui_action`/`studio_part_chat` call it
  makes; a call presenting the correct nonce is recorded as actor `human`, and a call with a missing
  or wrong nonce is recorded as actor `ai` (never denied) — which for `studio_part_chat` means it hits
  the existing human-only gate in `studio/shell/part_chat.py` and is rejected with `human_required`.
  This closes only the MCP tool path, the one path the Codex/Claude host model actually has through
  the plugin; it is not an authorization proof for the whole system. The browser page
  (`studio_open(presentation='browser')`) talks HTTP directly instead, and there
  `studio/shell/server.py`'s `_actor()` trusts whatever `X-Studio-Actor` header a caller sends as long
  as it holds the local session token, so a model with shell access to that token can still claim
  `human` over HTTP; that path is documented as a trust boundary (local token + header), not an
  authorization proof, and is not covered by the nonce. A stale nonce — the MCP server process
  restarted, or a host replayed an old `studio_open` result — surfaces as `human_required` (or, for
  `studio_ui_action`, is simply recorded as actor `ai`); `studio/app/api.js` recovers by calling
  `studio_open` again for a fresh nonce and retrying the failed call once, and the retry button
  (`studio/app/main.js`) re-mints it the same way on every reconnect. Whether a given host actually
  delivers `_meta` to the iframe at all has not been verified on a live Codex/Claude host; if a host
  drops it, calls degrade to actor `ai`, never a hard failure.
- Authorization is off by default. It is scoped to the current task, project, actual directory, Codex
  home, and CLI identity, and can be revoked from "Chat branch settings." Revoking blocks future
  creation without deleting existing branches. In-flight operations and revocation are serialized
  through the same task lock.
- The native branch is returned by the App Server. The backend re-verifies `id`/`cwd`/`forkedFromId`
  and only then binds the operation to an explicit parent-task coordinator; it never impersonates a
  child task's headers to call the public join.
- `PRINT_PREP_WORKSPACES_HOME` remains the root for the global workspace registry; the background
  server's own `PRINT_PREP_HOME` is still used for the current service's logs, so as not to add
  another layer of nesting to the binding location.
- Verified locally on CLI 0.154.0, desktop 26.915.31945. It is disabled when the CLI is absent or too
  old; compatibility with other versions and hosts still needs real-world verification and is not
  claimed to be accepted everywhere.

## Consistency and UI

`~/.print-prep/workspaces/<parent>/part-chat/` stores the current authorization and a per-operation
record. Creation goes through the phases prepared → forking → created → bound; if binding fails, the
child ID is kept so binding can be retried. Request IDs and duplicate clicks are deduplicated — the
same parent task and the same part reuse an existing branch.

- When the App Server sends `thread/started`, the child ID is recorded immediately; even if the final
  RPC response is lost, a retry only binds the original branch.
- If the process disconnects before a child ID is obtained, the state becomes uncertain and it does
  not blindly fork again. The official fork has no idempotency key, so this case needs a human to
  reconcile it against the Codex task list — we cannot claim cross-system exactly-once here.
- Before binding, the invite's version, directory, scope, and part lease are checked. When an invite
  has expired or the part has been updated, the invite is only refreshed after the user explicitly
  retries and supplies the latest revision; a child task that already has its own project must not be
  overwritten.
- All part edits continue to be governed by the existing per-object revision, lease, scope, and undo
  rules; a child task always uses its own `CODEX_THREAD_ID`.
- `studio/web/part-chat.js` provides authorization, progress, result, and open entry points, with no
  `ui/message` fallback. `crypto.getRandomValues` works around iframes that lack `randomUUID`.
- "Open branch" uses the MCP App's `ui/open-link` Codex deep link; when the host refuses it, a
  clickable task link and the real error are still shown. The HTTP page uses the same protocol link.

## Verification

- A real official App Server created a prototype branch; after the connection closed, Codex desktop's
  `read_thread` read back persistent history and the parent origin, and `navigate_to_codex_page`
  returned success.
- A real packaged MCP App + Chromium WebGL + a real backend + real Codex RPC: clicked deny → set
  allow → create → open entry — not a mock creation.
- Task `01a0cc50-03fc-7fd0-b4a6-793001a66ecb` created by clicking was bound to the verification
  project; 0 messages went to the parent, 0 page errors. After the child task revised the accepted
  part, the parent UI's polling automatically showed the update, and an out-of-scope rename was
  rejected with `scope_violation`.
- The original host project was untouched; the test assets live in a dedicated verification-task
  workspace. No turn was auto-run on the new branch's model.
- Automated regression covers authorization/revocation, identity changes mid-flow, duplicate
  operations, unknown result after timeout, recovery from a lost response, invite refresh, protecting
  the target project, out-of-scope edits, and the real MCP subprocess's registration root.
- Off-repo evidence: `~/test/claude-blender/runs/studio-direct-part-chat-20260923/`, containing
  `ui-evidence.json`, `direct-child.json`, UI screenshots, and test output.

## Files and Official Protocol

Backend: `studio/shell/codex_bridge.py`, `studio/shell/part_chat.py`, `studio/core/collaboration.py`,
`studio/shell/server.py`, `studio/shell/mcp_server.py`, `studio/core/workspaces.py`, `studio/__init__.py`.
UI: `studio/web/part-chat.js`, `studio/web/editor.js`, `studio/web/editor.css`, both API transports,
and the packaged app.

Protocol reference: [official App Server docs](https://learn.chatgpt.com/docs/app-server), cross-checked
against the installed CLI's `generate-json-schema --experimental` for the arguments.

Final verification: 88 Node tests and 42 Python/MCP tests passed from source; with the installed
distribution, which keeps the host's increment, 89 Node tests and 42 Python/MCP tests passed.
`0.7.2+codex.20260923033510` is installed. The original task's background switched to the new version
after confirming it was idle; 60 objects and the project.json SHA256 were unchanged, and the new
endpoint behaves correctly when unauthorized. Old tasks still holding an old MCP/UI cache need to
reload the plugin's tools or start a new task; installation does not replace the running process of
other active tasks.
