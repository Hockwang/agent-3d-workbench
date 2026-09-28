[简体中文](README.zh-CN.md) · [Agent playbook](docs/AGENT_PLAYBOOK.md) · [Tool reference](docs/TOOLS.md)

# Agent 3D Workbench

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

![Selecting and editing a part](docs/assets/point-and-edit.gif)

The animation demonstrates shared selection. In the current Codex panel, use
**Attach selection to chat** to add a selection card to your message explicitly.
Selecting or importing a model no longer automatically adds that card.

> **Status:** pre-1.0. macOS is the platform tested end to end. Linux/Windows paths
> exist, but full desktop workflows still need validation on those platforms.
> A geometric check is not proof of printability, fit, strength, or wearability.

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
3. Check **Current model · 5 parts**. The objects are `body`, `handle`, `lid`, `knob`, `base`.

Alternatively, tell your agent:

> Import the demo-parts.glb generated in this checkout. Resolve its absolute path,
> read the current workspace first, and report the imported part names and dimensions.

Import appends objects. If this project already contains a model, use a separate
project for this tutorial or deliberately keep both. Reopening an already imported
model only needs **Current model**; importing it again creates another copy.

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

Use **Recent results** at the top, search by title or filename, then choose
**View result** or **Output files**. **File location** shows its local path.
**Import to editor** adds a generated result to the editable scene; previewing it
alone does not. For replacing an existing part, ask the agent to replace its ID
instead of importing a second overlapping copy.

## 3. Try a local modeling task

Paste this into your agent:

> Use only local tools. Create an L bracket with an 80 × 40 × 4 mm base, an
> 80 × 4 × 50 mm upright, and two 6 mm through-holes spaced 50 mm apart in the base.
> Use Python/CadQuery, export STEP and STL plus a GLB preview, and verify dimensions,
> solid validity and the holes. Show the result and its report. Do not use a hosted
> generation service. Ask if a dimension or hole placement is ambiguous.

The agent writes a script, runs it as a local task, inspects the output, and imports
it when requested. **Recent results** contains the task and its artifacts. Blender
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
6. **Deliver clearly.** Return output paths, checks and remaining limitations. Import
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
| Cannot find the model | Use Current model for the editing scene, Recent results for task outputs, or Open file for a file on disk. |
| Old selection cards appear | Remove each card with × and reopen the workbench after updating. New versions attach only on an explicit click; removing a card does not delete the model. |
| “No workspace bound” | Update and restart the MCP host. Codex native entries bind from host metadata; other clients need a configured workspace ID. Retry alone does not reload an old Python process. |
| Model appears twice | Import appends. Undo the duplicate import; use Current model to return to an existing scene. |
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

## License

MIT — see [LICENSE](LICENSE). Bundled third-party components retain their own licenses;
see [THIRD_PARTY.md](docs/THIRD_PARTY.md) and the notices under `studio/web/vendor/`.
The demo generator is included. User models, credentials and local workspace state
are not part of the repository.
