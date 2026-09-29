[简体中文](README.zh-CN.md) · [Agent playbook](docs/AGENT_PLAYBOOK.md) · [Tool reference](docs/TOOLS.md)

# Agent 3D Workbench

[![💬 Join Discord](docs/assets/discord-join.svg)](https://discord.gg/r8BVSGtR8H)

**Open a model, point at a part, and let your agent edit it with you.**

A local 3D workbench for people and general-purpose AI agents. The viewport and MCP
tools operate on the same project: inspect parts, model with Python/CadQuery/Blender,
make targeted edits, check the result, and export it. Codex can show the workbench in
its side panel; other MCP clients can use the same tools and a local browser page.

**No DiT model, 3D-generation service account, or 3D API key is required for local
work.** Your AI agent comes from your host application and may require its own account
or subscription. Installing dependencies needs internet access; local geometry work
does not require a hosted 3D service. Optional service adapters are separate and disabled
until configured.

## Showcase: from a small Pikachu STL to an iterated head-shell design

The user supplied a Pikachu model about 63 mm tall and asked to **hollow it into a
head shell, split it into front and back halves, make room for magnets, and separate
parts by color**. They then specified a **60 cm head circumference**. The agent worked
on the meshes locally while the user inspected the results and directed revisions:

1. **Turn the display model into a shell.** Inspect the STL's 10 separate solids,
   scale it, create the cavity and neck opening, and split the shell and accessories.
   Add clearances and insertion channels where parts such as the cheeks could not fit.
2. **Revise the eye openings with the user.** Try eye lattices and inner-eye windows,
   then restore the original round outlines at the user's request. Recheck sightlines
   and record the remaining obstruction.
3. **Adapt a helmet reference.** Separate the yellow ears and add keyed locators.
   After the user corrected the mounting arrangement, move the magnets onto overlapping
   front-shell tabs and the rear cover's inner wall.
4. **Save an inspectable result.** v6 has **13 parts and six pairs of Ø10×2 mm magnets**,
   delivered as a colored GLB, separate STLs, an editable project and inspection records.

| v6 assembled model | v5 exploded parts | v6 shells and magnet mounts |
| --- | --- | --- |
| ![Real mesh render of the assembled Pikachu v6 head shell](docs/assets/pikachu-head-shell/assembled.png) | ![The 13 v5 parts: shells, yellow ears, black ear tips, eye lattices, highlights, cheeks and nose](docs/assets/pikachu-head-shell/v5-exploded.png) | ![v6 shell cavities and overlapping tabs across the seam](docs/assets/pikachu-head-shell/opened-magnet-tabs.png) |

These are renders of delivered meshes. The middle image shows the v5 part layout;
v6 changed the two shells' magnet mounts and kept the other 11 parts unchanged.
**The user guided the design while the agent wrote missing geometry operations and
checked each revision.** The source STL contained no color values; an explicit part
plan assigned them. Processing required no DiT or hosted 3D API. All 13 parts passed
watertightness checks, but forward vision remains blocked and physical printing and
fitting are pending. The built-in recipe covers the base workflow; the custom v6
structure is not yet a one-click template.
[Read the design iterations, assembly details and verification limits](docs/PIKACHU_HEAD_SHELL.md).

**Want image-to-3D generation too?** The cup's [same-image comparison](docs/CUP_COMPARISON.md) demonstrates local modeling and API generation plus splitting. Follow the [API setup tutorial](docs/API_GENERATION_DEMO.md):
reference image → Hunyuan API → real GLB → MCP inspection, edit, undo and export.
[Hi3D AK/SK setup](docs/HI3D.md) is also available. These optional routes need your own service access.

## Edit with your agent

![Selecting and editing a part](docs/assets/point-and-edit.gif)

The animation demonstrates shared selection. In the current Codex panel, use
**Attach selection to chat** to add a selection card to your message explicitly.
Selecting or importing a model no longer automatically adds that card.

> **Status:** pre-1.0. macOS is the platform tested end to end. Linux/Windows paths
> exist, but full desktop workflows still need validation on those platforms.
> A geometric check is not proof of printability, fit, strength, or wearability.

## Languages / 语言

**English and Simplified Chinese are supported.**

| Surface | How to choose |
| --- | --- |
| This tutorial | [English](README.md) / [简体中文](README.zh-CN.md) |
| Workbench interface | Click **中文** to switch to Chinese, or **EN** to switch to English, at the top right. The page reloads to apply the choice. |
| MCP responses and backend messages | Set `STUDIO_LANG=en` or `STUDIO_LANG=zh-CN` in the MCP server's environment, then restart/reconnect that server. |
| Agent's conversational replies | Ask your agent to reply in English or Chinese; the workbench does not override the host's conversation language. |

For a first installation in your preferred language:

```bash
STUDIO_LANG=en ./install.sh --add       # English
# Or:
STUDIO_LANG=zh-CN ./install.sh --add    # 简体中文
```

The interface prefers its saved choice, then the configured server language, then
browser language. In hosts that block browser storage, the toggle is hidden; set
`STUDIO_LANG` instead and reopen the workbench after restarting its MCP server.
A UI language switch affects subsequent UI requests; it does not change the MCP
server's configured language. Model names, user text and existing generated files
are preserved rather than translated. See [language configuration](docs/CONFIGURATION.md#language--studio_lang).

## 1. Choose how you want to use it

| You use | Model interface | Agent interface |
| --- | --- | --- |
| Codex desktop + CLI | Native side panel or browser | MCP tools + bundled skill |
| Claude Code | Local browser | The same stdio MCP tools |
| Another MCP client | Local browser; inline UI only if it supports MCP Apps | The same stdio MCP tools |
| No agent | Local browser or command line | `python -m studio.core` |

Part-specific chat branches require Codex. Basic editing and local modeling do not.
The display name is **3D Workbench**; the compatibility plugin ID remains `print-prep`.

### Prerequisites

- Git, [uv](https://docs.astral.sh/uv/), and Python 3.12+ (the installer also needs
  `python3` or `python` on PATH).
- For Codex installation: Codex desktop and a Codex CLI with `codex plugin add`.
- For Claude Code installation: the `claude` CLI.
- Node.js 20+ for motion verification/export or rebuilding the interface. Prebuilt
  browser assets are included; ordinary static editing does not need `npm install`.
- Optional: **Blender** for Blender-backed tasks/rendering; **Bambu Studio** for its
  printer profiles, 3MF project export, and slice estimates. Neither is needed for
  the five-part editing tutorial below.

### Install for Codex (macOS/Linux)

```bash
git clone https://github.com/Hockwang/agent-3d-workbench.git
cd agent-3d-workbench
./install.sh --add
```

The installer creates the Python environment, links the checkout into `~/plugins/`,
writes a local `.mcp.json`, and registers `print-prep@personal`. It does not install
Blender or Bambu Studio. Reopen Codex after installation, then ask:

> Open the 3D Workbench for this chat in model editing mode.

For Chinese server messages, use `STUDIO_LANG=zh-CN ./install.sh --add`. The panel's
language toggle changes its own interface language. Run `./install.sh` without
`--add` to prepare the local registration and print the final add command.

### Install for Claude Code

From the cloned repository:

```bash
CLAUDE_WORKSPACE_ID=my-model-project ./install.sh --claude
```

This registers `codex-3d-studio` at **user scope**. Its fixed workspace is shared by
conversations using that registration. Use a distinct project-scoped configuration
for independent projects; changing the chat alone does not isolate their model.
Then ask:

> Read this repository's README and docs/AGENT_PLAYBOOK.md. Open the 3D Workbench
> in the browser using studio_open with presentation="browser".

### Configure another MCP client

Run `uv sync --locked` in the checkout, then add this server to your client's MCP
configuration. Replace **all three** `/absolute/path/agent-3d-workbench` paths:

```json
{
  "mcpServers": {
    "print_prep_studio": {
      "command": "/absolute/path/agent-3d-workbench/.venv/bin/python",
      "args": ["/absolute/path/agent-3d-workbench/studio/shell/mcp_server.py"],
      "cwd": "/absolute/path/agent-3d-workbench",
      "env": {"PRINT_PREP_WORKSPACE_ID": "my-model-project", "STUDIO_LANG": "en"}
    }
  }
}
```

On Windows, use `.venv/Scripts/python.exe`. Set one workspace ID per independent
project. Request `studio_open` with `presentation="browser"` when your host does
not render MCP Apps. See [Configuration](docs/CONFIGURATION.md) for executable
paths and manual setup.

## 2. Complete your first edit

This example builds its own five-part model. You do not need a downloaded model,
a service key, Blender, a GPU, or a printer.

### Step A — make the demo

From the repository directory:

```bash
uv run python examples/demo/make_demo_parts.py
```

The command prints the absolute GLB path and writes `examples/demo/out/demo-parts.glb`
and five STL files. This is a toy modeling example, not a food-safe cup design.

### Step B — open it

1. Ask your agent to **open the 3D Workbench**, or open its entry in Codex's right panel.
2. Click **Open file** at the top and choose `demo-parts.glb`.
3. Check **Editing · 5 parts**. The objects are `body`, `handle`, `lid`, `knob`, `base`.

Alternatively, tell your agent:

> Import the demo-parts.glb generated in this checkout. Resolve its absolute path,
> read the current workspace first, and report the imported part names and dimensions.

Import appends objects. If this project already contains a model, use a separate
project for this tutorial or deliberately keep both. Reopening an already imported
model only needs **Back to editor**; importing it again creates another copy.

### Step C — select and ask for a change

Click the handle in the viewport or object list. In Codex, click **Attach selection
to chat** if you want the selection included as a message card. The button is disabled
when nothing is selected. Other hosts can read the live selection through MCP.

Send:

> Read the current selection. Scale only the selected handle uniformly by 1.5 around
> its center. Keep the other parts unchanged. Report its dimensions before and after.

Expected handle dimensions: approximately **14 × 8 × 23 mm → 21 × 12 × 34.5 mm**.
The viewport and operation log should update. If a different object is selected,
the agent should resolve that mismatch before modifying it.

### Step D — inspect and undo

Rotate the view and look at the handle's connections. This scaling exercise does not
preserve a manufactured fit automatically. Ask:

> Inspect the modified handle and report actual geometry warnings. Undo the last edit,
> then read back the dimensions to confirm the original size is restored.

Use the UI's **Undo** as an alternative. A completed tool call and an attractive
preview do not establish that the part can be manufactured or assembled.

### Step E — save and export

Open **Project & delivery**:

| Action | Result | Use it for |
| --- | --- | --- |
| Save project | `.3dworkbench` archive | Reopen an editable project |
| Export GLB | Model with supported materials | Viewing or passing to another 3D tool |
| Export STL | Geometry in millimetres | Slicing or other manufacturing tools; no color/materials |
| Copy to print workspace | A separate manufacturing copy | Orientation, layout and slicing without moving the editing assembly |

Ask the agent to return the **absolute output paths** and verify the exported files.
Model edits auto-save in the project's working state; an explicit project archive is
useful for moving the work to another machine. See [Folder projects](docs/FOLDER_PROJECTS.md).

To replay the edit, undo, save, export and reopen steps over real MCP in an isolated
workspace (no UI clicks or host account needed):

```bash
uv run python examples/demo/verify_tutorial.py
```

The command prints a report path and preserves its demo outputs in a temporary directory.
It checks the tool workflow, not native desktop button behavior.

### Where did my generated result go?

Open **Task overview** from any workspace to choose a result. In **Modeling & tasks**,
the **Latest delivery** cards keep local, generated and split
variants of the same work together. Click a card to preview it; the header shows
its route, version and actual filename. For earlier work, open **Task overview**,
search by title or filename, then choose a model or **Output files**. **File location** shows its local path.
**Add to editing scene** adds a generated result to the editable scene; previewing it
alone does not. For replacing an existing part, ask the agent to replace its ID
instead of importing a second overlapping copy.

In **Model editing**, the left **Models & objects** list starts with the current scene
and opens by default. Select a part to see its properties in the fixed right sidebar.
Import tools are under **Add models & assets**. The project workflow starts folded;
result cards stay in the task view so they cannot be mistaken for the scene being edited.

## 3. Try a local modeling task

Paste this into your agent:

> Use only local tools. Create an L bracket with an 80 × 40 × 4 mm base, an
> 80 × 4 × 50 mm upright, and two 6 mm through-holes spaced 50 mm apart in the base.
> Use Python/CadQuery, export STEP and STL plus a GLB preview, and verify dimensions,
> solid validity and the holes. Show the result and its report. Do not use a hosted
> generation service. Ask if a dimension or hole placement is ambiguous.

The agent writes a script, runs it as a local task, inspects the output, and imports
it when requested. **Task overview** contains the task and its artifacts. Blender
is only needed for the tasks that use it. Local scripting enables modeling; arbitrary
artistic quality and photo-to-3D reconstruction are not guaranteed.

| Goal | Local route | What still needs checking |
| --- | --- | --- |
| Cut or repair a mesh | Plane cut, booleans, components, repair, simplify | Closed solids, retained details and materials |
| Add alignment pins | `connect-parts` with explicit mating planes | Wall thickness, withdrawal, physical tolerance |
| Separate color inserts | `color-inlays` with explicit palette/direction | Applicable color regions, removal and fit |
| Add a mechanical joint | `install-joint`, then `motion-check` | Sampled collisions, assembly order and physical retention |
| Make a head shell | Head-shell recipe with supplied/procedural source | Cavity, openings, sight lines, actual fit and ventilation |
| Animate or pose | Explicit skeleton/joints/keyframes and local Blender | Skin deformation, collisions and naturalness |
| Prepare a print | Orientation, plate layout, export, optional slicer check | Real printer/material behavior; a person starts printing |

Read the [public capability contract](docs/PUBLIC_CAPABILITIES.md) for exact
preconditions and unsupported cases. Optional generation-service recipes are not
part of the no-key local tutorial.

### Same image: local modeling and generation + splitting

| Shared reference | Codex local model | Hunyuan API model |
| --- | --- | --- |
| ![Reference](docs/assets/cup-comparison/reference.png) | ![Local](docs/assets/cup-comparison/local.png) | ![Generated](docs/assets/cup-comparison/generated.png) |

We generated an independent cup image, then ran both routes through MCP. Codex
built four editable local components. Hunyuan generated the model and its Part API
split it into two editable pieces. Both completed a single-handle move, undo,
export, project save and reopen.

The Part result keeps the lid fused to the body, uses segment colors instead of
PBR textures, and has open edges. Local dimensions are explicit design assumptions.
Neither result is a verified printable product. Follow the
[bilingual comparison tutorial](docs/CUP_COMPARISON.md), including input, assembled
and separated views, measured limitations and downloadable models.

## 4. Instructions for AI agents

Read this section before acting, then [AGENT_PLAYBOOK.md](docs/AGENT_PLAYBOOK.md).
Discover the installed tool schemas rather than inventing arguments.

1. **Bind the right workspace.** In Codex, use this chat's `CODEX_THREAD_ID` as
   `workspace_id`; native entry requests can receive it through host metadata.
   Never copy a thread ID from a prior conversation. Other hosts use their configured
   `PRINT_PREP_WORKSPACE_ID`. Do not use one workspace for unrelated projects.
2. **Read first.** Call `studio_open`, then `studio_get_state`. Read `workbench.objects`,
   `workbench.selection`, units and `workbench.revision`. A message attachment is a
   snapshot; it does not override live state. Editing IDs and print part names differ.
3. **Make a scoped edit.** Resolve IDs from that response. Send the latest
   `expected_revision` with `studio_edit`; on `revision_conflict`, re-read and
   reconsider the operation before retrying. Use the actual object version where required.
4. **Run local tasks when needed.** Read `studio_capabilities`; choose an available
   local engine/template via `studio_task`, then poll `studio_tasks`. Missing Blender
   or a slicer is a missing prerequisite, not a reason to use a paid service silently.
5. **Verify evidence.** Read reports and artifacts. `completed` means execution ended;
   a report can still say `fail`. View/render the model when appearance matters.
   Sampled collision checks do not certify an entire motion range or physical safety.
6. **Deliver clearly.** Register the model in the current project with a work title,
   route/stage, version and real thumbnail ([result handoff](docs/RESULT_IDENTITY.md));
   results left in isolated experiments do not appear in the user’s project. Open the
   task preview, then return output paths, checks and remaining limitations. Import
   the new result or use `replace` on the intended part as appropriate. Re-read the
   project after the change. UI-only `studio_ui_action` is reserved for human controls.

Example MCP edit (substitute values from **fresh** state; this is a protocol example,
not a shell command):

```json
{
  "workspace_id": "CURRENT_WORKSPACE_ID",
  "action": "transform",
  "expected_revision": 3,
  "params": {"ids": ["CURRENT_HANDLE_OBJECT_ID"], "scale": [1.5, 1.5, 1.5]}
}
```

Workspace length units are mm; angles are degrees unless a tool says otherwise.
Standard GLB import/export uses metres and Y-up; STL defaults to mm and Z-up.
Use scene import for GLB assets whose skeleton/animation must be retained;
static import is not an animation-preserving route. Request texture-loss approval
before operations that require `allow_material_loss=true`.

## Troubleshooting

| Symptom | Next step |
| --- | --- |
| Cannot find the model | Use Back to editor for the editing scene, Latest delivery / Task overview for task outputs, or Open file for a file on disk. |
| Old selection cards appear | Remove each card with × and reopen the workbench after updating. New versions attach only on an explicit click; removing a card does not delete the model. |
| “No workspace bound” | Update and restart the MCP host. Codex native entries bind from host metadata; other clients need a configured workspace ID. Retry alone does not reload an old Python process. |
| Model appears twice | Import appends. Undo the duplicate import; use Back to editor to return to an existing scene. |
| Blender/slicer unavailable | Install/configure that optional application or use a task without it. See Configuration. |
| Model has the wrong size | Check source units and import settings. Do not compensate with an unexplained scale. |
| `revision_conflict` | Re-read state and resolve the conflict; do not blindly resend. |
| Plugin changes do not appear | Reopen the panel for a rebuilt UI. Python changes require restarting the host; cached plugin manifest/skill changes may require remove/add. See Configuration. |

## Development and further reading

```bash
make install      # uv sync --locked + npm ci; does not register a plugin
make test         # Python and JavaScript tests
make lint         # Python lint
make build        # rebuild committed UI bundles
```

An optional [GitHub Actions template](docs/ci.github-actions.yml) runs these checks
on Linux. It is shipped as a template; hosted CI is not enabled for the initial release.

- [UI guide](docs/QUICK_START_UI.md) · [Configuration](docs/CONFIGURATION.md)
- [Tools](docs/TOOLS.md) · [Core CLI](docs/CORE_CLI.md) · [Architecture](docs/ARCHITECTURE.md)
- [Tasks](docs/WORKBENCH_TASKS.md) · [Motion](docs/MOTION_EDITING.md) · [Recipes](recipes/README.md)
- [Contributing](CONTRIBUTING.md) · [Capability contract](docs/PUBLIC_CAPABILITIES.md)

## Community and feedback

Join the [Discord community](https://discord.gg/r8BVSGtR8H) for setup help, work in
progress, and workflow feedback. English and Chinese are both welcome. Use
[GitHub Issues](https://github.com/Hockwang/agent-3d-workbench/issues) for reproducible
bugs so reports and fixes stay easy to find. Remove API keys and private data before
sharing logs or models.

## License

MIT — see [LICENSE](LICENSE). Bundled third-party components retain their own licenses;
see [THIRD_PARTY.md](docs/THIRD_PARTY.md) and the notices under `studio/web/vendor/`.
The demo generator is included. User models, credentials and local workspace state
are not part of the repository.
