> 中文：[zh-CN/CODEX_V05_INTEGRATION.md](zh-CN/CODEX_V05_INTEGRATION.md)

# v0.5 integration with the Codex right-hand workspace

## Implementation scope

Wires in v0.5's six-step flow, readiness, action log, undo, shared selection, and HTTP origin
checks, while keeping Codex's right-hand open mechanism, lightweight chat card, stable session
ID, and preview resource.

- `studio/web/workspace.js` takes a transport and wires together `Panel`, `Flow`, and `Viewport`.
  The HTTP page and the MCP App share the same controller and HTML; the build script extracts
  the workspace from `web/index.html`.
- `studio/app/api.js` routes UI write operations through the App-only `studio_ui_action`, which
  only allows registered POST tools and fixes the author to `human`. Ordinary MCP tools use
  `ai`; the author field is not a security boundary.
- The shape table is read via `print-prep://catalog/shapes`; the preview is obtained via the
  existing geometry resources. The MCP iframe never accesses HTTP directly, and no upload bridge
  is introduced.
- Keeps the `fullscreen` preference, the global/thread entry points, and the 148px card-height
  hint; the workspace respects safe-area margins. Collapsing stops rendering, and re-expanding
  reuses the geometry and selection.
- Both GET and POST carry the local token. HTTP's cookie is only used for SSE / mesh reads;
  write requests still verify the origin and the explicit token.
- Fixes cross-model undo after one-click prepare switches models: whether the whole flow
  succeeds or fails at the export stage, once the model has been swapped, the old undo,
  selection, and old step authorship are cleared.
- Reloading, re-orienting, re-arranging, exporting, or undoing resets the old delivery state; a
  one-click prepare only keeps this round's delivery when the open step actually ran.

## Verification

Automated verification entry points:

```bash
npm run build:app
uv run --locked pytest -m 'not bambu' -q
node --test tests/*.mjs
```

The stdio integration test uses a temporary `PRINT_PREP_HOME`, covering UI load, AI orientation,
human plate layout, shared selection, undo, shape resources, and error propagation. The
manufacturing mesh never changes because of the preview. An additional regression first
reproduced the cross-model undo and stale-delivery-state issues, then verified the fix.

An isolated browser host, using real test meshes and MCP handlers, verifies:

- The initial card doesn't read geometry; the six-step UI appears once expanded.
- A human clicks load and orient, the AI arranges the plate and selects a part, the UI syncs
  authorship and highlighting, and then the human undoes the AI's plate layout.
- The process form exports a geometric 3MF via MCP; no real trial cut is executed, and the Bambu
  GUI is not opened.
- 420×700, 420×420, 900×840, with the host covering 76px at the bottom; no horizontal overflow,
  and the flow area scrolls.
- Collapsing and re-expanding preserves the selection, and the geometry is still read only
  twice.
- The HTTP compatibility entry point shows the same state, registers 11 page tools, and can
  clear the shared selection.

The test host does not stand in for visual acceptance in the Codex native shell. Automated UI
tools are forbidden from operating Codex itself; after installing an update, open Print Prep in
a new task to confirm the actual right-hand tab. An existing task may still be using the old MCP
process and the old tool list.

## Maintenance

Prefer editing the shared workspace files, then rebuild `studio/app/dist/studio.html`. Don't
maintain two separately copied six-step HTML files.

Editing only the JavaScript source files does not update the already-packaged MCP App. Update
the cachebuster before reinstalling; keep the local `.mcp.json` out of version control.

A running HTTP backend needs a targeted restart to pick up Python changes. Check `busy` and back
up the job metadata before restarting; when verifying, only read user jobs — don't run write
tests against a real user model.
