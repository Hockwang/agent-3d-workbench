# Scene instance editing

> 中文：[zh-CN/SCENE_EDITING.md](zh-CN/SCENE_EDITING.md)

2026-09-23, v0.8.2. Implements phase one of the [proposal](history/SCENE_EDITING_PROPOSAL.md):
full-GLB instances, local editing, skeleton and motion inspection, in-place backfill, project save,
and task collaboration.

## Host support

| Capability | Codex desktop (sidebar panel) | Browser page (any MCP host, e.g. Claude Code) | Plain MCP client, no page |
|---|---|---|---|
| Viewport click-select + Shift multi-select | yes | yes | no: no viewport to click |
| AI highlight (shared workbench selection) | yes, via `studio_edit(action:'select')`* | yes, same tool | yes, same tool |
| Selection visible to the AI (`studio_get_state.workbench.selection`) | yes | yes | yes |
| Edits with `expected_revision`, undo/redo, per-object versions (shared projects) | yes | yes | yes |
| `scene_import` / `scene_export` / `scene_replace` | yes | yes | yes |
| Part-chat branch from a right-click | yes, needs the local Codex CLI | only when the page belongs to a Codex task: the workspace id is read as the parent Codex thread (`studio/shell/part_chat.py`), so a fixed id such as Claude Code's `claude-code` cannot create one even with the CLI installed | no: no viewport to right-click |
| Opening a branch (deep link) | yes, via `ui/open-link` | only for a branch created from a Codex task, and if this machine's Codex desktop registered the `codex://` handler | no: nothing opens the returned URL |

\* Not `studio_select`/`/api/select`, which only recognizes names from the print-prep panel's own loaded-parts list, not Scene Editing objects.

The browser page renders the same `editor.js`/`editor-viewport.js` UI Codex shows inline; only the API
transport differs (MCP tool calls vs. a local HTTP fetch). A Claude Code user reaches it by having the
AI call `studio_open(presentation='browser')` and opening the returned local URL. The part-chat branch
is the only Codex-specific piece here: it forks a live Codex thread through the officially installed
CLI's App Server, so it needs that CLI on the machine and a Codex task as the parent: the workspace id is read as the parent thread id (`studio/shell/part_chat.py`), which is why Claude Code's fixed workspace id cannot create a branch even with the CLI installed.

## Human entry point

"Model Edit → Models & Objects → Scenes & Characters" imports a GLB; each file is kept as one
complete instance.
The scene object list shares selection with the viewport; after selecting a character, view its
skeleton under "Object Properties → Scene Instance," enter motion editing, or click
"Repair / Rig" to hand that object's task to the current Codex.

Move/rotate/scale and appearance parameters act on the current instance. Copied instances initially
share the immutable source asset; editing the material produces a new asset hash, and other
instances sharing the same source are unaffected. Material edits go directly into the GLB JSON; the
original skin, UV, normal map, and animation buffers are unchanged. Base-color texture replacement
and complex geometry/weight adjustments go through Blender, followed by importing the complete
candidate.

"External repair & backfill" can export an editing-source, then pick a candidate GLB to replace it
in place; it preserves the instance ID, name, visibility, and placement matrix.
A new candidate's motion is reloaded, the whole motion preview pauses and resets to the start; it
does not reuse the old bone indices.
A candidate with bad weights, a cyclic hierarchy, a corrupt buffer, or an invalid animation target
will not be submitted.
Structural validation is not the same as appearance/motion naturalness acceptance; key poses still
need to be observed after backfill.

## AI contract

Reuses `studio_edit`, always with the current task's `workspace_id`, after first reading
`studio_get_state.workbench`.

| action | params | behavior |
|---|---|---|
| `scene_import` | `files: [absolute GLB path]` | appends a complete instance; does not break apart the internal hierarchy/rig |
| `scene_export` | `ids: [single object ID]`, optional `path` | exports a local editing-source GLB; does not bake instance placement or unexported motion adjustments |
| `scene_replace` | `ids: [single object ID]`, `path`, optional skeleton `blend_path` | checks the candidate and then replaces it in place, preserving identity and placement |

The scene still uses millimeters and Z-up; the editing source and backfill GLB use local meters and
Y-up.
Do not reset the source model's origin or bake the scene placement into the candidate a second
time. Use `scene_export` for exporting a plain static object too, to avoid a regular
world-coordinate export being re-applied on backfill.

A long-running task should keep the object version from when it was exported, and submit
`expected_versions`; do not read a newer version and overwrite unconditionally right before
submitting. Existing part-chat scope, leases, and undo continue to apply, and `scene_replace` can
run inside a task bound to the object. It is rejected if a parent-child mechanism dependency's
scope is insufficient or if there's a conflict on the same part.

## Storage and reuse

`objects[].scene` is an optional `studio-scene-instance/v1`:

- `asset`: the current complete GLB's SHA256; `family`: the original shared-source identity.
- `kind`: static / skin / animated; `nodes` / `bones` / `clips` are a summary of the source asset.
- The existing `objects[].asset` is proxy geometry used only for static checks and manufacturing
  copies; it cannot stand in for the full source.
- `objects[].motion` continues to hold `skin`, plus a new `gltf` type carrying the source's native
  rigid-body-node clip.
- The instance matrix is kept separate from the source asset; edits to a shared source use a
  per-instance update over the immutable asset.

Saving the project and the motion ZIP carries the full source asset along; reopening/branching the
model keeps using the original identity, or a consistent remapping on import.
An old project without a `scene` field is read the old way and is not auto-migrated.
A plain GLB mesh export errors out on a scene instance and points to the full project/editing
source/animated GLB, to avoid silently losing the skeleton.
STL / print copies explicitly use the static proxy.

Reuses the existing EditorViewport, GLTFLoader, SkinMotion, Blender, project, and collaboration
backend.
This round did not copy any attachment's game code or bundle attachment assets into the plugin
distribution.

## Phase-one boundary

Currently this is full-asset instance editing within the scene; internal mesh and skeleton work is
handled by the motion panel or in Blender.
This page records the v0.8.2 boundary; the v0.8.3 full-city integration is in
[CITY_RUNTIME](./CITY_RUNTIME.md). v0.8.2 does not include driving, NPC behavior,
collision/navigation rebuilding, full-city streaming, or character/facility contact planning.
There is also no arbitrary scene-tree reparenting or one-click update of every instance sharing a
source.
A single complete asset caps at 500 MB, a proxy caps at 5 million faces, and a project caps at 500
objects.
Morph targets and compressed GLBs need to be cleaned up in Blender first; naturalness of automatic
rigging for an arbitrary character is not guaranteed.

Edit/motion mode reuses the same real GLB, no reload on switching; a failed candidate load keeps
the original view and can be retried.
Browser resize verification is recorded separately from the native Codex window's composition feel.
See [this round's acceptance](history/VALIDATION_20260923_SCENE.md) for the actual test.
