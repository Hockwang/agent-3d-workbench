> 中文：[zh-CN/AGENT_PLAYBOOK.md](zh-CN/AGENT_PLAYBOOK.md)

# Agent playbook (long form)

**Result handoff**：Deliver outputs into the current project with a work title, route/stage, version and real thumbnail. Follow [the result identity contract](RESULT_IDENTITY.md); open the task preview without importing into the editing scene. Do not leave the only discoverable result in an isolated test workspace.

This is the detailed operating guide the skill file (`skills/print-prep/SKILL.md`) points to.

For the first-use tutorial, see [Getting started](GETTING_STARTED.md). In the current panel, selection
cards are added only by **Attach selection to chat**. Always read the live workspace
selection before modifying a part; an old message card is not current state.

## What it is

It's an MCP App panel plus a matching set of tools; both share the same local backend, and
state lives in exactly one place.
By default it opens in the Codex right-hand workspace via the plugin protocol, leaving only a
short entry point in the chat; it has both a global entry point and a per-task sidebar entry
point, and the original web page remains as a compatibility fallback.
The print-prep module has a six-step flow: model, orientation, plate layout, process, trial cut,
delivery. Each row can expand to show parameters; readiness is shown at the top, and the action
log is shown below.
People and the AI share the same selection. Orientation and plate layout are undoable; when an
upstream step changes, downstream steps prompt for redo. Below 860px width, the viewport sits
above the flow.
The preview is decimated on its own; the manufacturing mesh and output are unaffected. Both the
MCP App and HTTP support local file picking and chunked upload; the AI should prefer using an
existing absolute path directly.

So the default approach is: **open the panel for the user to see first, then do the work with
tools.** Don't drive the panel by clicking buttons — the tools are faster and more accurate;
only click the UI when no tool is available at all.

## Step one: open the panel

Call `studio_open` (the plugin's built-in MCP tool). By default it returns the MCP App resource
and the current state, and asks the host to expand it in the right-hand workspace.
If a workspace already exists, keep using the same set of tools — don't call `studio_open` again
for every step. Repeated opens for the same task and the same job use a stable session ID; hosts
that support it will reuse the workspace.
The small card in the chat has an "Open workspace" button to re-expand it; don't repeatedly
insert the full editor into the chat.
**Don't automatically open a localhost browser page.** Codex builds that support entry-point
extensions can open it directly from the Print Prep global entry point or the task tool entry
point.
UI buttons go through the App-only `studio_ui_action` and are recorded as `human`; the AI calls
the workflow tools below directly and those are recorded as `ai`. Don't use the UI-bridge tool
in place of the AI tools. The expanded panel syncs state roughly every 3 seconds, and refreshes
immediately after an action.

Only call `studio_open({"presentation":"browser"})` when the user asks for the web page or file
upload, or you've confirmed the host doesn't support MCP Apps.
This compatibility branch returns `{url, job, already_running}`; open `url` with the built-in
browser.

Only the legacy web mode needs you to check the "page tools" line in the panel's bottom status
bar:

- "N registered": the built-in browser supports page tools. From then on **prefer the
  same-named tools listed on the page** (they hit the same backend as the MCP tools and give
  identical results, just with one less hop).
- "This browser does not support page tools": use the plugin's built-in `studio_*` MCP tools
  directly; the functionality is the same.

If the `studio_open` tool doesn't exist (the MCP service hasn't started), fall back to the
command line to bring the service up:

```bash
~/plugins/print-prep/.venv/bin/python ~/plugins/print-prep/scripts/studio.py start
```

The JSON it prints out has a `url` field.

## Tool overview

See [`TOOLS.md`](TOOLS.md) for the full parameter tables (auto-generated; it has every tool's
inputs, required fields, and backend routing). Here we only repeat one general rule:

Every tool returns the backend's raw JSON. Always check `ok` first: when it's `false`, read
`error.code` and `error.message` and relay them faithfully — don't guess at the cause yourself.
`error.code == "busy"` means the previous step hasn't finished; wait and call again, don't run
concurrently.

## Standard flow

Print prep (`studio_open({"mode":"print"})`):

1. `studio_load`. Read each part's `fits_bed`, `watertight`, `components`, `extents_mm`,
   `suggested_scale`, and the top-level `warnings`:
   - Doesn't fit → check `suggested_scale` and ask the user whether to scale down, or use
     `target_max_mm`. This measures **the combined bounding box of all parts together** (each
     part keeps its position from the source file, i.e. the assembled overall size), with one
     shared factor applied to all of them; it's mutually exclusive with `scale`, and `scale`
     must be greater than 0.
   - Not watertight → say so plainly; print prep on its own never implicitly modifies the mesh.
     If the user asks for a repair, go into the model-editing module and handle it explicitly,
     then generate a new print copy.
   - Longest edge under 5 mm or over 2000 mm → the units are probably wrong; ask the user for
     the real size, don't guess at a multiply/divide factor yourself.
   - Scene-type files default to one part per geometry node (the part name comes from the node
     name); pass `merge: true` to combine them into a single part.
2. `studio_orient`. Pick `shape` from the morphology tags table below. Read each part's
   `print_up`, `strategy_used`, `warnings`, `top_candidates`:
   - `upright_rejected: true`: the source file's +Z orientation doesn't stand stably (less than
     20 mm² of bed contact) while another orientation does, so it was auto-switched; the reason
     is in `upright_rejected_reason`. Tell the user — this is not a failure.
   - `warnings` contains `unstable_contact`: the final orientation still has less than 20 mm² of
     bed contact (common for figurines, spherical shapes, or pointed-bottom parts). Tell the
     user plainly that this part will need supports and a brim to stand, or pick one from
     `top_candidates` and set it manually with `set`.
3. `studio_arrange`. If `single` doesn't fit, it errors and tells you how many plates `auto`
   would need; if a single part doesn't fit, it gives a `suggested_scale`.
4. `studio_export`. Read each plate's `project_3mf`, `bambu_moved_objects`, `unmatched_parts`: if
   either of the latter two is off-nominal (true, or a non-empty list), report it plainly to the
   user — don't say "laid out exactly as planned." Which process preset and filament preset were
   used, and which process settings were changed, are all in the return value.
5. (optional) `studio_check`. **If this step hasn't run, don't report grams or time** — just say
   it hasn't been estimated.
6. `studio_send_to_bambu`.

When you don't need to inspect every intermediate step, steps 1–4 can be replaced with a single
`studio_prepare` call; the panel refreshes step by step as it goes.

When the user says "this part," read `selection.parts` first, and only ask for clarification if
it's ambiguous. Undo invalidates export and trial-cut results; after switching models, old undo
entries are no longer usable. `readiness` only reflects the current step's status — it is not a
guarantee the print will succeed.

Files must be passed as **absolute paths**. If the user only gives a directory, list it yourself
to find the mesh file before passing it.

## Morphology tags

The morphology tag determines both the orientation strategy and the process tier. If you can't
tell which applies, pick one from the table below and tell the user which one you chose and why.

| Tag | Applies to | Orientation strategy | Layer-height tier & process deltas |
|---|---|---|---|
| `generic` | Uncertain | `support` (least overhang among the stable orientations) | 0.20 |
| `figurine` | Figurines, sculptures, characters | `upright` (keep the source orientation) | 0.16, tree supports, supports may land on the model, outer brim |
| `relief` | Reliefs, flat thin plates | `flat` (largest bed contact area) | 0.16, no supports |
| `mechanical` | Structural/functional parts | `flat` | 0.20, 4 wall loops, 20% infill, normal supports touch the bed only |

The default printer is `Bambu Lab P1S 0.4 nozzle`. To switch, call `studio_list_printers` first
and use the exact `name` it returns.

## Hard rules

- **Never send to the printer.** Every return has `print_submitted: false`. Even when the user
  says "print," go only as far as opening it in Bambu Studio — a person has to click print.
- **After sending, don't claim it's "loaded."** `loaded` in the return is always `"unverified"`;
  you can only say "requested Bambu Studio to open file X." When `was_running_before` is true,
  warn the user that Bambu Studio was already open and may pop up a prompt asking whether to
  save the current project first.
- **With multiple plates, only open plate 1 by default**, and list the full project-file paths
  for the remaining plates to the user; only pass `all: true` when the user explicitly asks for
  it.
- **Every number must come from a tool's return value** — never estimate grams, time, or volume
  from experience.
- **The print-prep module never modifies the original geometry.** When splitting or repair is
  needed, switch to model editing, then explicitly generate a copy and hand it to the print
  module.
- The backend only listens on the local loopback address, and write operations require a token.
  Don't try to bypass this from another page or script to directly edit files in the job
  directory.
- Launching Bambu Studio inside a restricted sandbox may be blocked: if it fails, ask the user
  to grant permission for this step — don't try to work around it another way.

## Command-line fallback

When neither the panel nor MCP is usable, the same capabilities have a command-line entry point;
each command's stdout is a single JSON object:

```bash
PP="$HOME/plugins/print-prep/.venv/bin/python $HOME/plugins/print-prep/scripts/print_prep.py"
$PP prepare --job ./job /absolute/path/a.stl /absolute/path/b.stl --shape figurine --check --open
```

The step-by-step subcommands are `printers`, `inspect`, `orient`, `arrange`, `export`, `check`,
`open`, and their parameters map one-to-one to the tool parameters above. On `prepare`, the two
different meanings of `--set` are renamed to `--orient-set part_name=x,y,z` and
`--export-set key=value`. Bad arguments still return JSON as well (`error.code =
"bad_arguments"`, exit code 2).

## What to report back to the user

If a step is missing, say it wasn't done — don't fill in the gap as if it had been:

- How many parts, how many plates; which parts have `unstable_contact` or
  not-watertight-type warnings
- The morphology tag and orientation strategy (or which parts were manually specified)
- Printer, process preset, filament preset, and which process settings were changed
- Whether a trial cut was run: if so, report grams and duration; if not, say it hasn't been
  estimated
- Which project file was requested to open in Bambu Studio, and the file paths for the remaining
  plates

## Folder projects and task identity

- On first use, read the current `CODEX_THREAD_ID` (read only this variable — don't dump the
  full environment); after that, every `studio_*` tool call carries a `workspace_id` fixed to
  that task ID. The examples below omit this common parameter. You cannot edit directly using
  another task's ID, and you cannot substitute an MCP connection or a PID for the task ID.
- If no stable ID is available, stop writing and say so explicitly — don't fall back to the old
  global project. The `workspace_id` a tool returns must match the current task.
- A new Codex task's first use fetches `cwd` from the official thread/read call; ordinary tasks
  under the same project/worktree root share a model, while selection, undo, and part scope stay
  independent. Existing projects and explicit part bindings take priority and are preserved.
  `studio_workspaces(action="project")` shows the current directory, and
  `open_project(worktree=directory)` connects explicitly; don't merge all historical tasks
  together. See [Folder projects](FOLDER_PROJECTS.md) for details.
- To reuse an old model: first `studio_workspaces(action="list")`, then
  `fork(source_id, expected_revision, workspace_id)` on the current task's workbench, before it
  has been opened. `legacy` is a read-only source pointing at the old shared project; after
  forking, the original is preserved, and selection, undo, and subsequent tasks are independent.
- Merging a branch must be an operation the user explicitly asked for:
  `studio_workspaces(action="merge", expected_revision=current_version_of_source_project,
  workspace_id=current_branch_task_id)`; a conflict on the same part is rejected, never
  auto-overwritten. The first phase does not do automatic geometry merging; continuing to edit
  the same part after a merge may require creating a new branch from the source.
- After an edit, an active UI on a shared project syncs on a roughly 1-second poll; an old
  standalone project polls roughly every 3 seconds. When a script/generation task finishes, a
  "model updated / open model" prompt appears; on delivery, use
  `studio_open(mode="tasks", task_id=result_task_id, workspace_id)` to locate the artifact. Each
  presentable stage uses the artifact of its own completed task; writing to a temp file does not
  trigger a preview.
- If an old entry point reports it's unbound, call `studio_open` again with the current task ID;
  don't switch to someone else's workbench just to restore the UI.

## Scene instances and character touch-up

- Import via "Model editing → Scene & characters" or
  `studio_edit(action="scene_import", params={files:[full_GLB_path]})`; one file is kept as one
  instance, including source hierarchy/skinning/animation. Don't use the ordinary static import,
  which would flatten a character.
- When a selection includes `objects[].scene`, `scene.asset` is the full source version and
  `scene.family` is the shared-origin identity; `objects[].asset` is the static proxy. Check the
  object ID, version, and scope before modifying.
- For external touch-up on a single part: `scene_export` with `ids` exports a local metric,
  Y-up source; GPT uses local Blender to inspect/rig/modify it, keeping the source origin and
  not re-baking the instance placement. After observing key poses, use `scene_replace` with
  `ids`, the candidate `path`, and the `expected_versions` captured at export time to write it
  back in place. A packed skeleton `blend_path` can be attached. No extra LLM API is required.
- A scene instance can be transformed, duplicated, and have its material edited directly;
  material edits preserve the source skinning/UV/animation and only update the current instance.
  Use `save` for saving the full scene and `studio_motion` for motion adjustments; a plain-mesh
  GLB export never silently flattens the scene. STL/print copies remain static proxies.
- A failed candidate leaves the original version intact; a write race on the same part, or a
  stale write, is rejected — it never borrows another task's ID. Writing back a new asset pauses
  the motion and resets it to the start. Passing a structural check does not mean the motion
  looks natural, or that contact and physics are correct.
- See [Scene contract](SCENE_EDITING.md) for full GLB instances; v0.8.3 has wired in the full
  Cubely city with local behavior linkage — see [City contract](CITY_RUNTIME.md) for supported
  scope.

## Observation, comparison, and evaluation

1. `studio_open({mode:"observe"})` opens the observation area; keep using it if a panel already
   exists. The goal is for the AI to read state, look at evidence, act, and verify again — all
   on the same workbench — instead of opening a separate localhost page for every model.
2. `studio_observe({action:"start",inputs,labels,params})`, or use `source_tasks` to compare
   against existing tasks on the workbench; each input file represents one complete version, up
   to four. GLB/STL/PLY/URDF are supported. Don't mistake several parts for several different
   routes.
3. Query with `read({id})`; once complete, it returns the actual PNG and condensed metrics
   directly. For a specific part use `detail=true`; for a single view, use `images[].file` from
   the report as `image_file`; `image=false` retrieves only the numbers. Don't claim the
   appearance is correct without having looked at the image.
4. URDF defaults to Z-up; some WaveAB artifacts are Y-up — confirm against the source and pass
   `params.urdf_up`. `phases:[0,.5,1]` samples across the joint range; GLB samples the current
   animation as imported by Blender. Coordinates, scale, and camera stay consistent across
   versions — they are not auto-normalized per version.
5. `focus({id,variant,phase_index})` lets the person see, on the right, the version/pose the AI
   is currently discussing; `read` without an `id` reads the current focus, which also reflects
   the person's own selection.
6. Look at the real evidence before calling `review`; pass `report_sha256` as `expected_sha256`,
   along with `verdict=good/bad/needs_review` and a specific `note`. Completing an operation is
   not the same as passing quality — human and AI assessments are attributed separately.
7. Route evaluation reuses the original runner and protocol, executing and collecting artifacts
   via `studio_task`; it does not reimplement WaveAB. Route time, observation time, tokens, and
   cost are recorded separately; missing values are not filled with 0, and a route's superiority
   is never declared from a single case. See [AI workbench](AGENT_WORKSPACE.md) for details.

## WaveAB platform review

"Observation & evaluation → route review" reuses the Assembly Evaluation Dashboard.
`studio_evaluation`:

1. `status` checks the connection; `connect` takes the actual platform root URL and an optional
   `auth_env` environment-variable name — never treat a GitLab branch URL as the service
   address, and never put a token in a parameter.
2. `catalog` reads existing batches/analyses; `read`'s `resource` can be `analysis`, `case`,
   `comparison`, `report`, etc.; it's condensed by default, and `detail:true` returns full
   evidence. The analysis matrix is paginated with `offset`/`limit`.
3. `focus` takes an analysis `id` and `case_run_id`, and is shared with the person's case
   selection in the matrix; a Case's `read` can omit `id` to read the current case.
4. `preview` takes 1–4 `case_run_ids` and returns a workbench task; check the artifact with
   `studio_tasks`. The preview only reflects the platform's `viewer_model` rigid-body joints —
   it makes no claim of physical correctness. `evaluate` kicks off the platform's asynchronous
   analysis; read its status via `analysis_job`.
5. `review` / `compare_review` must pass the `expected_sha256` just read. The AI only saves a
   suggestion; it enters the HUMAN gate only after a person fills it in, checks it, and submits
   it in the workbench. Impersonating a human via `studio_ui_action` is forbidden. With missing
   evidence, leave it as UNKNOWN/NOT_EVALUATED — never declare a route qualified based on
   successful execution or a two-case experiment.
6. `inspect` checks a local result ZIP; only call `intake` once the four-dimensional `factors`
   and `Case mappings` are explicit. `report` generates a deterministic, frozen report without
   calling any paid model; `export` saves the audit CSV or report Markdown and returns the real
   path.

When the production deployment address hasn't been configured, ask or read the existing settings
first — never guess the address, and never treat an isolated test platform as the production
data source. See [WaveAB platform integration](WAVEAB_EVALUATION_PLATFORM.md) for the detailed
contract, provenance, and limits.

## Build, service, and animation tasks

Professional APIs are configured under "Build & tasks → Manage 3D services," where connections
can be added, started/stopped, and read-only tested. The AI uses
`studio_services(action="list")` to check status and `probe` to check authentication; only the
environment-variable name is saved, and the key itself is entered encrypted by the user in the
UI — it must never go into the chat or a tool parameter. Pick the user's connection via
`studio_capabilities.services[].id`; don't hardcode a default provider. See
[Self-service setup](BYOK_SERVICES.md) for details.

Lux3D supports separate domestic/international connections, image/multi-image/text generation,
material repaint, four-view, reference images, and format conversion. Put local input files in
`inputs`; they upload automatically. Call
`studio_services(action="balance"|"quote",id=connection_id,operation,params,inputs)` first; a
plan quote uses the `items` array. Generation takes the original parameters plus `quote_id`, and
a plan item additionally carries `quote_item`; re-quote whenever the parameters or account
change. Execute against the budget and goal the user has already authorized — the quote is a
pre-discount estimate. Use `resume` to recover an existing task, or pass
`params.remote_task_id` as a string to collect the result, rather than resubmitting the
generation. View the real result with `observe` before delivering it; see [Lux3D](LUX3D.md) for
the complete field list, version limits, and verified scope.

Seed3D uses `provider:"seed3d"`, `operation:"image-to-3d"`; put one reference image in `inputs`
and it returns a GLB. It's currently wired to the company gateway's Seed3D 2.0 professional
model — although the transport uses `chat/completions`, it never calls a general-purpose LLM.
This is a synchronous interface with no reliable polling contract; only a download failure
*after* a result has been received can be resumed — an ambiguous submission cannot be
auto-retried.

The default preference is the current GPT plus local Blender/CAD, requiring no extra generation
API purchase, though it still consumes GPT quota and local compute. Read the selection,
dimensions, and constraints first, and check the real artifact after execution; open-ended
modeling is not limited by the number of templates.

Codex itself handles understanding, planning, and tool calls — the user does not need to also
wire up a GPT API. Hunyuan 3D / Part is an optional professional service: `provider:"hunyuan"`,
with operations `image-to-3d` / `text-to-3d` / `segment`. Put images in `inputs`; for part
splitting, use `source_task` to reference a task that has already generated an FBX, or pass an
accessible `file_url`. Fill in parameters from the `capabilities` templates, and choose FBX at
generation time so Part can continue afterward. Results reuse this workbench's viewer; Part's
generative splitting can change geometry and texture and does not guarantee original-face
identity. See [Hunyuan service](HUNYUAN_API.md) for configuration and examples.

Assembly Workflow is an optional service providing `assemble` / `segment` / `rig-glb` / `rig` /
`motion`. Pass parameters from the `operation_templates` in `studio_capabilities`; an existing
model requires a server-accessible `meshUrl` — it never auto-uploads local files or the current
selection. `motion` only generates a motion file. Credentials go through `key_env` /
`headers_env`, and the assembly-inference appkey goes through `oneapi_appkey_env` — never put
any of these directly in `params`. Never claim it has been verified working unless it's
connected and has actually generated something real. See
[Service contract and local examples](ASSEMBLY_API.md) for details.

1. `studio_open({"mode":"tasks"})` opens the right-hand task area; `studio_capabilities` reads
   local dependencies, the actual templates, and configured services. The UI lets you pick
   files, templates, and parameters directly.
2. For simple, well-defined operations, prefer an existing template; for open-ended modeling,
   use `studio_task({action:"start",engine:"blender"|"python",script,params,inputs,
   render_preview})`. The script's `workbench` variable holds `inputs` / `params` / `output`;
   Blender uses meters and Z-up, and automatically delivers a `.blend` plus a `.glb` with
   animation/skinning. No need to spin up a separate localhost page.
3. `start` returns an ID immediately; poll it with `studio_tasks({id})` — don't resubmit. At
   most two tasks run at once per workbench. Use `cancel` to cancel local modeling; tasks
   survive across HTTP restarts.
4. Generation calls `studio_task({action:"start",provider,operation,params,inputs})`. Keys are
   read from `key_env` — never write them into a script or task parameters. If credentials are
   missing, report that it's not configured; never fabricate a generation result. `resume` only
   collects a result against an existing remote ID; `cancel` only stops the local wait — the
   remote job may keep running and billing.
5. `completed` only means execution finished and the artifact was written to disk. Read the
   inspection report, verify the geometry/animation, and look at the actual preview; a `fail` in
   an assembly report does not become a pass just because the task is `completed`.
6. Bring a static GLB back into editing with
   `studio_task({action:"import",id,artifact_id,expected_revision})`; leave animation playing in
   the task area or open the Blender project. `open` only opens artifacts already registered
   under the current task.
7. Surface template fitting requires an explicit source and template; skeleton/motion requires
   `bones` / `bone_map`; face labeling needs the full node face order and `source_sha256`. If
   the input is incomplete, read from the existing project first — don't guess at authoritative
   labels, skeleton names, or identity-preservation results.
8. The hair-card template uses `points_m`, `width_mm`, and optional `atlas_uv` from `guides`;
   local smoothing uses `center_m`/`radius_mm`. Neither claims to automatically recognize
   hairstyles or faces. The AI can look at the model first, propose an explicit region, and only
   then call the deterministic operation.
9. `.blend` files, reports, renders, GLB, and offline HTML are all collected in the task results
   area. See [Task workbench](WORKBENCH_TASKS.md) for the complete method, coordinate/input
   contract, service configuration, and limits.
10. `container`, `hinge`, `generated-container`, and `local-dimensions` support going back and
    editing parameters: read `editable` via `studio_tasks({id})`;
    `studio_task({action:"rebuild",id,params:{...}})` generates a new task from the frozen
    original input, and the old result is kept. Inputs only accept self-contained
    GLB/STL/PLY; a change in the build implementation requires resubmitting the source. `start`
    can use `from_selection:true,expected_revision` to take a copy of the current selection, in
    which case `inputs` cannot also be passed.
11. `generated-container` machines a rectangular interior cavity, a removable lid, a locating
    lip, and an opening into a single closed solid; millimeters/Z-up. Confirm the source shape
    can contain the envelope first — don't paper over a failure by scaling the whole part. The
    machined result is a solid color; textured or multi-color input requires the user to
    explicitly accept the loss and pass `allow_material_loss=true`. Check the envelope,
    interference, and wall-thickness coverage in the `report` — physical fit still needs
    separate verification. `local-dimensions` only extrudes along an existing cross-section; the
    control plane must not pass through a triangle. Topology/UV are preserved; semantics are not
    auto-detected. Changing hinge `angle_deg` / `frames` changes the exported animation; the
    UI's playback speed only affects the preview.

## Motion editing and local GPT rigging

Natural-language requests come from the host chat. If an attached selection includes `motion.time_seconds`, use it and the snapshot object IDs to resolve the user's reference,
then reread live state and versions. Preserve untargeted parts and motion. The cursor identifies a pose,
not a new animation start. Keep editable parameters and inspect the resulting poses.
If `motion.unsaved_preview` is true, ask the user to save or explicitly discard the preview before editing backend motion. Do not infer a cursor time when no attachment or explicit time is provided.
Standalone projects may only expose `revision`; shared projects also expose object `version`.

1. `studio_open({mode:"motion"})` opens the viewport shared with the editor. Read
   `studio_get_state.workbench`, and use
   `studio_motion({action:"set"|"clear"|"import"|"export",expected_revision,expected_versions,
   params})`. Motion is stored on `objects[].motion`; writes are protected by part scope, lease,
   and version just like everywhere else.
2. For mechanical motion, `schema=studio-motion/v1`, `kind=joint`, `mode=pkf` or `keyframes`;
   see [Motion contract](MOTION_EDITING.md) for full examples and axis/pivot units. MotionForge's
   y-axis is Studio's −Y; rotation angles are in degrees and sliding in meters — you cannot feed
   workbench millimeters straight in. Plain GLB keyframes cannot be automatically decoded back
   into semantic parameters.
3. Rigging defaults to using the current GPT: observe the original model and its dimensions,
   decide the bone points and parent/child structure, then call `studio_task`'s existing
   `rig-bind` / `skin-weights` or a local Blender script. A rig that already qualifies should be
   reused first; check weight normalization, unweighted vertices, and whole-segment deformation
   — a successful export is not the same as a naturally qualified motion. No extra LLM API
   purchase is required.
4. `import`'s `path` takes a self-contained skinned GLB; `blend_path` can attach an uncompressed
   `.blend` that has had external resources packed into it in Blender. It preserves the source
   skeleton/weights; the editor also keeps a separate static proxy. For bones, use `mode=clip`
   to trim/retime, or `mode=pkf` to drive local XYZ rotations by the original bone names — read
   `motion.bones` and `motion.clips` first; don't guess at bone names.
5. `export` with `format=zip` outputs a re-editable motion project; `format=glb` outputs a
   sampled, baked motion. A skeleton GLB exports one complete rig at a time; a mixed project is
   delivered as a ZIP. After it returns `path`, use
   `studio_observe(action="start",inputs:[path],params:{phases:[0,.5,1]})` to see the real
   dynamic poses — `read` returns PNGs, and `focus` can display them in the observation area.
   GLB and PKF preview/export share the same evaluator.
6. Saved projects and worktree branches include the motion asset; geometry machining requires
   explicitly clearing/rebinding it first. A change to the parent object's zero position or
   geometry invalidates the old binding — you cannot silently apply the old weights. Complex
   mechanism changes need a main chat that covers the parent/child dependency.
7. The first batch of external v7 packages only accepts a single clip, fixed topology, and
   independent mesh joints; reparenting/overflow/group nodes and morph targets are explicitly
   rejected. IK, controllers, and motion blending are handled in Blender and then baked to GLB —
   it's never claimed that the old MotionForge can open Studio's skeleton extension.

## Model editing (v0.6)

### Merge / A8 review

`studio_task`'s `merge-review` / `a8-review` templates reuse the unified MDE viewer, previewed
under "Observation & evaluation → Part splitting & mechanisms"; call
`studio_open({"mode":"observe"})` first. A8 is an observation/evaluation capability, not part of
the build entry point. Use the original manifest/cases/registry paths — you can't just upload a
JSON with no adjacent resources. For a merge input, explicitly confirm the GLB unit (`m` or
`mm`); two manifests can be shown side by side, and the output `parts.glb` can be brought back
into editing. A8 takes `batch_id` / `case_ids`; a direct cases input also needs `parts_dir`, up
to 8 cases; it preserves joints and upstream audit data, and never treats `ready` as a pass on
motion quality. The G/B export buttons save JSON to the workspace; unexported temporary preview
marks and selections never automatically enter the shared state or write to the original
registry. See [Merge / A8 workspace](MERGE_A8_WORKSPACE.md) for details.

### Static editing

The plugin's compatibility ID is still `print-prep`; the product's display name is
"3D Workbench." Model editing opens by default; call `studio_open({"mode":"print"})` for a print
task.

1. Call `studio_open({"mode":"edit"})`, then read `studio_get_state.workbench`.
2. Use `studio_edit({action, expected_revision, params})`; `expected_revision` is taken from the
   current `workbench.revision` and updated after each completion. On `revision_conflict`, read
   the new state and re-evaluate first — never blindly replay the old command.
3. Object identity uses `workbench.objects[].id`, and selection uses `workbench.selection`.
   Print's `selection.parts` is a separate selection — the two must not be mixed.
4. Select parts with `select`, then apply `transform`, `rename`, `duplicate`, `delete`,
   `visibility`, `isolate`. Transform parameters are in millimeters/degrees; translation,
   rotation, and scale default to pivoting around the selection's shared center. For a single
   object, `matrix` is a 4×4 absolute world matrix.
5. `plane_cut` takes `normal` and `point_mm`, and requires a valid closed solid; `extract_faces`
   splits off a region by `face_ids` or `point_mm`/`radius_mm`, preserving the original
   faces/UVs without capping; `split_components` splits by connected component; `merge` only
   merges mesh data; for solid boolean operations, use `boolean`'s union/difference/intersection
   — for a difference, the first item in `ids` order is the object being subtracted from.
6. `inspect` is a read-only check; `repair` handles normals, duplicate/degenerate faces, and
   small holes; `simplify`'s `ratio` is the fraction of faces to keep. Look at the actual
   warnings — a successful `repair` call is not a guarantee of watertightness.
7. A geometry operation on a textured object requires `allow_material_loss=true`, and the result
   turns solid-colored. Only use this when the user's goal explicitly accepts that change — the
   original can be recovered with `undo`. `material` can modify color/roughness/metallic while
   keeping the texture; read the slot number from `objects[].materials`, and pass a single
   object's `ids` plus `material_slots` for a precise edit. `base_color_texture` is a local
   PNG/JPEG/WebP path, or `null` to remove it; a replacement requires valid original UVs, only
   modifies the specified channel, and preserves alpha and other textures. A standard GLB with
   multiple primitives is usually imported as multiple objects — operate on the actual
   object/slot.
8. Edits auto-save into `workbench/` under the current job; `undo`/`redo` manage the edit
   history. `save` outputs a self-contained `.3dworkbench` project, and `open` reads a project
   back in, undoably. Export via `export` supports GLB/STL; by default it exports all visible
   objects, or only the specified ones if explicit `ids` are given.
9. `import` appends a local file. GLB/GLTF default to meters, Y-up; the workbench is
   millimeters, Z-up, and exporting a GLB converts back to standard coordinates. STL/OBJ/PLY
   default to millimeters, Z-up; pass `units` when the user specifies a non-standard source.
   Animation, skinning, and morph targets are rejected — never claim they were preserved.
10. To bring an edit result into print: `print_copy` returns `files` for a millimeter STL copy,
    then call `studio_load({files})`. This step replaces the task input in the print module; the
    edit project and its assembly positions are unaffected by plate layout. To bring an existing
    print model into the editor, use `studio_get_state.print_sources` as `import`'s `files`,
    with `units=mm`.

See the `studio_edit` tool schema for all action parameters; an unknown object or a failed
operation must never be faked as a success. The AI calls tools directly; `studio_ui_action` is
reserved for UI buttons attributed to a human.

## The full Cubely city

This supports the source contract of the user-provided `cubely_lab_20260920.zip`; it is not a
generic parser for arbitrary city ZIPs.
`studio_edit(action="city_import", params={path:absolute_zip_path})` imports it into a
standalone project. Opening the model-editing viewport auto-starts the full city and
initializes a frozen instance manifest; `city_catalog` takes `query`/`offset`/`limit` to query
it, and `city_checkout(instance_id)` loads a single character or facility into local editing.
The city's root node is only a resource entry point — never treat it as a 1mm model to
modify/print. Save the full city with `save` to produce a `.3dworkbench`; don't treat a
select-all GLB/STL export as the city project.

- It's the same renderer / RAF / Three.js instance; paused by default, and the Run button
  resumes Cubely's local driving, walking, interaction, and NPC behavior.
- Workbench transforms are still in mm, Z-up; the city runtime auto-converts to m, Y-up. Moving
  a facility updates its own collision envelope, obstacle index, and interaction position.
- Exact object identity is in `objects[].city_link`. Local material edits, and `scene_export` →
  local Blender → `scene_replace`, preserve instance identity.
  Writing a character back must preserve the bone names in the `bones` semantic mapping, the
  source `source_clip`, and the full timeline. Set an appropriate fps before exporting; the
  attached character source is 30fps, and Blender's default of 24fps may truncate the last frame
  and get rejected. Deformation naturalness and the new motion's contact quality still need to
  be observed for real.
- Delete/duplicate/replace-with-an-incompatible-skeleton/direct `motion_set` are not yet open
  for city instances — these would break the original behavior binding. Motion mode can observe
  a local instance, and doing so closes the whole-city preview; go back to model editing and
  click "Open city" to restore it. Changing the source motion requires keeping a compatible clip
  in Blender and writing it back.
- The same project reuses part-chat scope/lease/version and undo; worktree branches stay
  independent. What gets saved is the edit layout and assets — driving position and story
  progress are per-preview transient state.
- The source-code adapter is compiled locally; it doesn't run the attachment's npm scripts or
  bring in its binaries — runtime resources are bound to the project and SHA-verified. A new
  machine needs an explicit source-package import to build a trust receipt; an archive script
  that hasn't been imported locally never runs automatically. Online NPC motion generation and
  the IndexedDB cache are turned off; basic walking comes from motions bundled in the package,
  with no extra LLM/API calls.

## Task recipes

First use `studio_list_recipes` to read current availability,
then `studio_get_recipe({id})` to read the steps and guide; `studio_use_recipe({id})` enables
it, and passing `null` disables it. Enabling a recipe does not execute anything. The user can do
the same thing via "Choose recipe" at the top right.

- Read current readiness and `missing_tools` from the recipe catalog; do not assume a fixed
  count of executable recipes. Tool availability does not certify that a particular asset
  passes the recipe. Optional hosted routes need separately configured services.
- `workspace=edit` uses `studio_edit`; read the version and selection before acting. An editing
  recipe records the actually-succeeded operations, and progress is invalidated by a geometry
  change, a selection change, or an undo. Completed progress is not a guarantee of watertight
  repair or of appearance quality.
- `workspace=print` uses the original print tools; model editing and print tasks are two
  separate states. Cross the modules with an explicit `print_copy`/`studio_load` — never
  silently swap an edit result in as the print input.
- A recipe is data and a reference guide — it grants no new permission. A third-party recipe
  must not preset file paths, object IDs, project versions, or accept texture loss on your
  behalf; every number and acceptance result is taken from the actual tool return.
- User recipes live at `~/.print-prep/recipes/<id>/recipe.json` and `guide.md`. They reload when
  a directory is opened; status polling does not re-read every recipe each time.

### Part-chat branches (live linkage in the same worktree)

When the user right-clicks a part and chooses "Create chat branch," the UI creates a real Codex
branch and binds it to the part directly through the app-only `studio_part_chat` — it no longer
sends a `ui/message` to the parent task or starts a touch-up turn. The first time, a person must
grant local access for the current project in the UI; this can be revoked from "Chat branch
settings." The bridge only uses the official App Server protocol, and the created result is
readable and openable on the desktop; it must not be expanded into a general-purpose RPC or used
to bypass an unauthorized state.

On entering the newly bound task, first read the state with your own
`workspace_id=CODEX_THREAD_ID`, check `collaboration.scope` and the selection, and only then
open the workbench — don't invite/join again or create a new model copy. An old ID may appear in
the inherited parent-task history; don't reuse it.

Only when the user explicitly asks in chat for the AI to create the branch can the native tool
route still be used:

1. This task still passes its own `workspace_id=CODEX_THREAD_ID`. Read the latest state, check
   the part ID, and call
   `studio_workspaces(action="invite", object_id=..., expected_revision=...,
   worktree=collaboration_directory)`. A new folder project uses
   `workbench.collaboration.worktree`; an old standalone project uses the current real `cwd`.
   This returns an `invitation` and `project_id`. Different worktrees do not share writes.
2. Use Codex's native `fork_thread(environment={type:"same-directory"})` to create the chat
   branch. Don't fake a rollout or rewrite Codex's private database, and don't open the new
   task's own workbench first. Skip this step when direct workbench creation has already
   succeeded.
3. Send a short prompt to the returned new task explaining which part the user asked to create a
   dedicated touch-up chat for, including `source_id`=the previous step's `project_id`,
   `invitation`, and `worktree`; ask the new task to first call
   `studio_workspaces(action="join", ...)` with its own `CODEX_THREAD_ID`, then `studio_open`. If
   no touch-up goal was given, wait for the user after binding rather than modifying the model on
   your own. Return the new task's entry point to the user.
4. The new task shares the model with the original one; selection, camera, and undo are each
   independent. The sub-task can only edit the bound part and parts split off from it. Pass
   `expected_versions={id: objects[].version}` and `expected_revision` on edits; on
   `part_locked` or `revision_conflict`, read the state and handle it — don't race to write or
   blindly retry.
5. Before a long external modeling session, `renew` the part lease (5 minutes); every submission
   afterward still validates the version. The lease you hold auto-renews while the workspace is
   open; use `release(ids=[...])` when done or handing it back — don't let the parent task
   borrow the sub-task's ID directly to bypass the lock.
6. External touch-up goes: export the selection → Blender/Python →
   `studio_edit(action="replace", params={ids:[original_part_id],
   files:[artifact_absolute_path]}, ...)`, or
   `studio_task(action="import", replace_ids=[original_part_id], ...)`. The artifact must keep
   the project's coordinates and units as of export time; it's never auto-aligned, and a plain
   `import` must not be used to append an overlapping copy. Every successful submission shows up
   in other open UIs within roughly a 1-second poll cycle.
7. To isolate a model experiment, open a separate worktree and, before the new task opens its
   workbench, use `open_project(worktree=target_empty_directory,source_id=...,
   expected_revision=...)` to create a model branch inside that directory; the old `fork` can
   still create a session copy. Merging still explicitly checks for part conflicts. A scene
   copied directly with Git is independent, but has no Studio merge baseline.

## Local fabrication contract

Before using `connect-parts`, `color-inlays`, `install-joint` or `motion-check`, read [PUBLIC_CAPABILITIES.md](PUBLIC_CAPABILITIES.md). Propose explicit geometry parameters from the current asset. Read each task report and import/reload its new artifacts before subsequent editing or print preparation. A completed task with `report.status=fail` is a failed geometric check; sampled clear values never imply a continuous safe range. No provider or generation-service key is needed.
