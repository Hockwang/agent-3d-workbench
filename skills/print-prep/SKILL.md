---
name: print-prep
description: Observe, edit, split, model, animate and print-prep 3D assets in the Codex sidebar. studio_observe returns real render images; studio_evaluation connects to the WaveAB review platform; studio_motion edits animation, studio_edit edits meshes, studio_task runs modeling jobs; human and AI share one workbench state.
---

# print-prep

## What this is

An MCP App panel plus a matching set of tools, sharing one local backend and one state. It
opens in the Codex sidebar as a 3D workbench: model editing, service/modeling tasks, motion,
and a six-step print pipeline (model, orient, arrange, export, check, deliver). Human and AI
share selection and edit history; call tools directly rather than clicking panel buttons.

## First step

Read `CODEX_THREAD_ID` once per task (only that variable, never dump the full environment) and
pass it as `workspace_id` on every `studio_*` call for the rest of the session. Never use another
task's id, never substitute an MCP connection id or PID, and never fall back to a legacy/global
workspace when no stable id is available.

Open the workbench with `studio_open({"mode": ...})`, mode one of `edit` (default), `motion`,
`print`, `tasks`, `observe`. Reuse the same open workbench across calls; do not reopen it before
every step. Only pass `{"presentation":"browser"}` if the host cannot show MCP Apps or the user
asks for a browser/file-upload flow.

## Public naming

Use capability names in task titles, result titles/notes, animation labels, and user-facing
explanations: automatic rigging, motion generation, or part segmentation. Do not expose
internal research/model implementation names in those surfaces. Keep protocol identifiers,
asset bindings, original evidence, and required dependency license notices intact.

## Tool overview

All 26 tools share `workspace_id`. Full parameter tables: [`../../docs/TOOLS.md`](../../docs/TOOLS.md).

| Tool | What it does |
|---|---|
| `studio_get_state` | Read panel state: parts, orient/arrange/export/check history, readiness, stale flags |
| `studio_select` | Highlight parts in the viewport without changing geometry |
| `studio_undo` | Undo the last undoable orient/arrange step |
| `studio_list_printers` | List printer presets |
| `studio_load` | Load mesh files and measure geometry |
| `studio_orient` | Choose a print orientation per shape label |
| `studio_arrange` | Pack oriented parts onto the bed |
| `studio_export` | Write a Bambu Studio 3MF project |
| `studio_check` | Headless slice estimate (grams/time); can take minutes |
| `studio_send_to_bambu` | Open the project in Bambu Studio's GUI; never submits a print |
| `studio_prepare` | Load -> orient -> arrange -> export in one call, optionally check/send |
| `studio_edit` | Static mesh editing, scene/city import, materials |
| `studio_motion` | Set/clear/import/export joint or clip animation |
| `studio_list_recipes` / `studio_get_recipe` / `studio_use_recipe` | Browse and toggle task recipes (data only, grants no new capability) |
| `studio_services` | Manage BYOK 3D-generation service connections |
| `studio_observe` | Render and compare real models/animations, review evidence |
| `studio_capabilities` | Report local deps, templates, configured services |
| `studio_tasks` / `studio_task` | Query / start / cancel / import modeling and generation jobs |
| `studio_evaluation` | Connect to the WaveAB review platform |
| `studio_part_chat` | App-only: create/inspect a part-scoped chat branch |
| `studio_open` | Open the workbench in a given mode |
| `studio_ui_action` | Panel-button-only; records as human, never call it as the AI |
| `studio_workspaces` | Project/fork/merge/invite/join across folder workspaces |

## Standard flow

**Print pipeline**: `studio_open({"mode":"print"})` then `load` -> `orient` -> `arrange` ->
`export` -> optional `check` -> `send_to_bambu` (or `studio_prepare` for the first four steps
in one call). After each step, read the real warnings before moving on: `fits_bed` /
`watertight` / `suggested_scale` from load, `upright_rejected` / `unstable_contact` from orient,
`unmatched_parts` from export. Earlier steps invalidate later ones (`undo`, a reload, a new
orient) — re-check `readiness` and do not report stale numbers as current.

**Edit loop**: `studio_open({"mode":"edit"})`, read `studio_get_state.workbench`, then call
`studio_edit` with the current `expected_revision`. On `revision_conflict`, re-read state before
retrying; never blind-replay a stale instruction.

**Task loop**: `studio_open({"mode":"tasks"})`, `studio_capabilities` to see what is available,
`studio_task(action:"start", ...)` to launch, `studio_tasks({id})` to poll. `completed` only
means the job ran and wrote files — read the actual report before calling geometry or motion
correct.

**Result handoff**: Deliver into the current project, not only an isolated test workspace
or a filesystem link. Give each work stable identity, route/stage, version and a real
thumbnail via optional `workbench-result.json`; see [result identity](../../docs/RESULT_IDENTITY.md).
Existing external GLBs can be copied with `register_existing(workbench)` in an ordinary
Python task. Reuse matching completed registrations. Poll completion, then open the task
preview; do not import into the editor merely to make a result visible.

**Observe loop**: `studio_open({"mode":"observe"})`, `studio_observe(action:"start", inputs, ...)`
with up to four versions, then `read({id})` for real PNGs and metrics. Never claim an appearance
or motion judgment without having looked at the returned image. Observation applies one camera
and one scale to every input with no re-centering, so a source-vs-result comparison must use
inputs already in the same units: for a `shell-kit` task compare the artifact
`inspection/source-reference/scene.glb` with `scene.glb` (both under the task output), not the
raw uploaded STL, which is still in its original scale and renders as a tiny white blob.

## Hard rules

1. Never submit a print job. Every response carries `print_submitted: false`; "print" from the
   user means open the project in Bambu Studio and stop there.
2. After `studio_send_to_bambu`, `loaded` is always `"unverified"` — say "requested Bambu Studio
   to open X", not "loaded".
3. With multiple plates, open only plate 1 by default and list the other project file paths;
   pass `all: true` only if the user explicitly asks.
4. Report only numbers that came back from a tool call. Never estimate grams, time, or volume.
5. The print module never modifies source geometry; route repairs/splits through model editing
   and hand the print module an explicit copy.
6. Secrets (service API keys, platform auth) are read from environment variable names configured
   by the user in the panel; never put a key or token in a tool argument or in chat.
7. `studio_ui_action` is for panel buttons only and is attributed to the human; call the
   `studio_*` tools directly as the AI.
8. Materials/textures: geometry ops on textured meshes need explicit `allow_material_loss=true`
   and only when the user has accepted that tradeoff; `undo` restores the original.
9. Scene/city instances, rigged characters, and generative-part-split results do not preserve
   original face identity or guarantee natural motion — verify by observation, not by "the call
   succeeded".
10. A completed task, a `ready` merge, or a passed geometry check is not a claim of physical
    correctness, watertightness, or natural motion; state only what was actually verified.
11. Only open a real service/generation connection the user configured (`studio_capabilities` /
    `studio_services`); never hardcode a default provider or fabricate a generation result when
    credentials are missing.
12. Attempting to launch Bambu Studio inside a restricted sandbox may be blocked — ask the user
    to allow it rather than working around the block.
13. Merging one workspace into another (`studio_workspaces(action="merge")`) happens only on the
    user's explicit request; a conflicting part is refused, never overwritten, and no geometry is
    auto-merged.

## CLI fallback

If the panel and MCP tools are both unavailable, the same pipeline is reachable from the shell,
one JSON object per command on stdout:

```bash
PP="$HOME/plugins/print-prep/.venv/bin/python $HOME/plugins/print-prep/scripts/print_prep.py"
$PP prepare --job ./job /abs/path/a.stl /abs/path/b.stl --shape figurine --check --open
```

Subcommands: `printers`, `inspect`, `orient`, `arrange`, `export`, `check`, `open`, matching the
tool parameters above (`--orient-set part=x,y,z`, `--export-set key=value`). Bad arguments return
`error.code = "bad_arguments"` with exit code 2.

If `studio_open` itself is missing (MCP server not running):

```bash
~/plugins/print-prep/.venv/bin/python ~/plugins/print-prep/scripts/studio.py start
```

## What to report back to the user

State plainly what was NOT done rather than implying it was:

- Part count and plate count; which parts have `unstable_contact` or non-watertight warnings
- Shape label and orientation strategy chosen (or which parts were set manually)
- Printer, process preset, filament preset, and any process overrides
- Whether a slice check ran — grams/time only if it did, otherwise say it was not estimated
- Which project file was sent to Bambu Studio, and the paths of any other plates

## Head shell (built-in recipe)

To hollow out an existing character model into a wearable head shell, read the built-in guide with
`studio_list_recipes` / `studio_get_recipe(id="wearable-head-shell")`, then enable it with
`studio_use_recipe(id="wearable-head-shell")` — all bound to the current `workspace_id`. Run the
`shell-kit` template under modeling/tasks; the source file, dimensions, and local parameters come
from this request, no separate personal skill needed. Full usage and parameter examples ship with
the workbench in `recipes/wearable-head-shell/guide.md` and `examples/head-shell/`.

The original eye outline is protected by default; never extend the inner eye corner or change the
mouth shape just to pass the sightline check, and head circumference cannot derive a real wearer's
eye position. Watertightness/assembly, the declared head envelope, sightline rays through the
actual eye mesh, and human appearance confirmation are reported separately; rebuilding with new
parameters requires re-checking the new version. Missing evidence or a blocked ray stays
unresolved — a successful generation is not a wearable finished product. The AI review uses its own
actor and cannot fill in a human "good".

## Where to read more

- [`../../docs/AGENT_PLAYBOOK.md`](../../docs/AGENT_PLAYBOOK.md) — full operating guide (folder
  workspaces, scene/city instances, observation, WaveAB review, recipes, part-chat branches)
- [`../../docs/TOOLS.md`](../../docs/TOOLS.md) — generated tool reference
- [`../../docs/CONFIGURATION.md`](../../docs/CONFIGURATION.md)
- [`../../docs/FOLDER_PROJECTS.md`](../../docs/FOLDER_PROJECTS.md)
- [`../../docs/MOTION_EDITING.md`](../../docs/MOTION_EDITING.md)
- [`../../docs/SCENE_EDITING.md`](../../docs/SCENE_EDITING.md)
- [`../../docs/WORKBENCH_TASKS.md`](../../docs/WORKBENCH_TASKS.md)
- [`../../docs/AGENT_WORKSPACE.md`](../../docs/AGENT_WORKSPACE.md)
- [`../../docs/CITY_RUNTIME.md`](../../docs/CITY_RUNTIME.md)
- [`../../docs/HEAD_SHELL.md`](../../docs/HEAD_SHELL.md)
- [`../../recipes/README.md`](../../recipes/README.md)
