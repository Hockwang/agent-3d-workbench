# Motion editing (2026-09-23)

> 中文：[zh-CN/MOTION_EDITING.md](zh-CN/MOTION_EDITING.md)

Built after the user confirmed the [implementation proposal](history/MOTION_EDITING_PROPOSAL.md).
Motion editing reuses the same EditorViewport/WebGLRenderer, object selection, and project as mesh
editing. There is no embedded MotionForge webpage, and no second LLM service is called.

## Usage

- The default UI is for selection, timeline scrubbing, preview and export. Describe modeling, rigging and motion requests in the host chat. Joints, formulas, keyframes and clearing bindings stay under collapsed **Advanced editing**. Unsaved manual edits keep a visible save prompt even when that section is closed.
- Top bar "Motion Edit" or `studio_open(mode="motion")`. Select an object, add a mechanical joint,
  or import a skeleton GLB / motion ZIP.
- Changing a parameter/formula previews instantly; clicking "Save Motion" writes it into the
  shared project. Timeline scrubbing, play, pause, and loop only affect the preview.
- Mechanical: rotate/slide/fixed-follow, parent-child joints, pivot, limits, PKF
  parameters/steps/easing or explicit keyframes.
- Skeletal: preserves the original GLB skins, weights, inverse bind matrices, and clips; can trim
  the source clip / retime it, or edit local XYZ-rotation PKF by the original bone names. A plain
  clip does not automatically recover semantic parameters.
- Ask for rigging directly in Codex chat. GPT reads the geometry and then uses
  the existing local `rig-bind`, `skin-weights`, or a Blender script; it supports an uncompressed
  `.blend` with external resources already packed in. No extra GPT API call.
- A project ZIP can be imported into a brand-new task to keep editing. Mechanical projects contain
  the MotionForge v7 standard core; skeletal/mixed projects use the `studio-motion-package/v1`
  extension, which older MotionForge does not support.
- Saving an animated GLB bakes a sampled action; a skeletal export is one complete rig at a time.
  Static export continues to be served from the model-editing entry point.
- `studio_observe` can take phases `[0,.5,1]` of an exported GLB and return real PNGs with the
  corresponding deformed-mesh snapshots, so the AI and the human can check the result in the
  observation area rather than only checking the evaluated numbers.

## Direct motion with language

1. Ask “Open the drawers in order” directly in **Codex chat**. The agent reads the project, creates motion and the workbench previews it in **Motion Edit**.
2. To reference parts or a pose, select parts and scrub the timeline, then click **Attach selection to chat** above. This pauses playback and attaches object IDs, project revision and `motion.time_seconds`; it does not send a message.
3. Back in chat, ask “Hold here for two seconds; keep the others unchanged.” Changing selection, time or project revision invalidates the old attachment; attach again. Opening a page or restoring selection never attaches automatically.
4. A regular browser has no Codex attachment button. In the MCP client connected to the same workbench, specify part names and time, such as “Hold the middle drawer at its 2.4-second pose for two seconds.”
5. After manual parameter or keyframe edits, click **Save Motion** so the agent sees the version you previewed. Attachments mark unsaved previews; they are not saved backend motion.
6. Export an **editable motion ZIP** to reopen and edit parameters later. **Animated GLB** preserves sampled playback tracks, not necessarily the original semantic parameters.

Use GPT-6, another Codex model, or a general-purpose agent connected through the same MCP. The plugin does not require a second model account. Results depend on the input, agent and tools.
Mechanical motion requires identifiable, editable parts. Whole GLB instances, complex joints and characters may need structural preparation. Naturalness, contact and collisions require separate checks.

### Local replay (no model or service API calls)

From the repository root:

```bash
uv run python examples/motion_editing/verify_tutorial.py --out /tmp/workbench-motion-demo
```

The output directory must not already exist. The script creates a simple three-drawer fixture, uses real stdio MCP to animate it, extends only the middle drawer hold, exports ZIP and GLB, reopens in a separate workspace, and reduces its travel.
It checks geometry and untouched objects, sampled world translations and exported animation tracks. Stage files and `report.json` remain in the output directory.
This is a deterministic product-flow verification, **not a model leaderboard**. The host agent remains responsible for interpreting natural-language requests.

## Data and AI contract

`objects[].motion` is folded into the existing object version, lease, undo, project save, and
worktree branch. The `studio_motion` tool's `action` is `set/clear/import/export`, with `params`
using the same edit-parameter structure; the corresponding `studio_edit`
`motion_set/motion_clear/motion_import/motion_export` compatibility entry points also exist.
Always include the current task's `workspace_id` and a freshly-read `expected_revision`; for a
shared project it's recommended to include `expected_versions`.

```json
{
  "schema": "studio-motion/v1", "kind": "joint", "duration": 4, "fps": 30, "mode": "pkf",
  "joint": {"type":"revolute", "axis":"z", "origin":[0,0,0], "parent":null, "limits":[-180,180]},
  "parameters": [{"id":"angle", "default":60, "unit":"deg"}],
  "steps": [{"id":"open", "t_start":0, "t_end":4, "value_start":"0", "value_end":"angle", "easing":"ease-in-out"}],
  "keyframes": []
}
```

Mechanical coordinates: reuse MotionForge's original semantics; `axis` is the **world axis**;
MF X = Studio X, MF Y = Studio −Y, MF Z = Studio Z.
Rotation is in degrees, sliding in meters. `origin` is the parent joint's unscaled local frame
(meters, MF XYZ), or world coordinates when there is no parent.
Rendering/static editing is still millimeters and Z-up, while the GLB is meters and Y-up; the
adapter preserves geometric scale through a matrix transform and a zero-position offset.
The `axis` for a skeletal PKF, however, is the original glTF bone's local XYZ, with rotation in
degrees; the mechanical MF axis names must not be mixed in.

The server fills in `bound_asset`, `bound_transform`, and `bindings` to prevent silently reusing an
old motion after the geometry or parent object's zero position changes.
Topology/material machining on a bound asset is rejected and requires an explicit clear and
re-bind, or re-import after modifying the whole rig in Blender.
Cross parent-child mechanism edits check the dependency's version/lease; a part sub-chat without
the relevant scope gets `scope_violation`.
Source GLBs are stored separately by SHA256; a plain static proxy does not overwrite the skins;
source `.blend` files go into a separate `sources` store.
Save/import/worktree copy all carry these dependencies along. Export does not overwrite an
existing file.

## Reuse and implementation

- MotionForge pinned at `18a11fe175691538962b5659a4797c3d3c24ed17`; source, SHA, and patches are in
  `studio/web/vendor/motionforge/SOURCES.json`. MotionForge is the plugin author's own project, published under this repository's MIT license; see [third-party notices](THIRD_PARTY.md).
- jsep 1.4.0 parses formulas. Only parameters, numbers, arithmetic, and whitelisted math functions
  are allowed, with length/complexity/finiteness/limit validation.
  The original engine's `new Function` path has been disabled. The frontend and the Node worker
  share `motion-engine.js`.
- The exporter reuses the original `ResultPackageExporter`, with a fixed-30fps bug fixed. GLB
  sampling appends a standard TRS animation, preserving the source geometry/material/skin buffers
  without rewriting the rig with Trimesh.
- Requires Node.js 20+ locally; the prebuilt `studio/app/dist/motion-cli.cjs` ships with the
  plugin, no `npm install` needed. A single sampling pass caps at 500,000 node-frames to avoid an
  out-of-control export on a large project; shorten the clip / lower the fps / export per object to
  work around it.

## Explicit boundaries

The first batch requires an external MotionForge v7 import to have: zero position, a single clip,
fixed topology, independent mesh nodes; it does not accept reparent events, overflow, scene
markers, or unbindable group nodes, and it does not silently drop fields.
Morph targets and Draco/Meshopt/KTX2-compressed assets need to be cleaned up in Blender first;
skeletal motion is not a general IK/rig-controller editor.
Complex IK, constraints, contact correction, and motion blending are still solved and baked in
Blender; we do not claim automatic rigging or acceptable natural motion for an arbitrary character.
The caller must pre-pack external images for a `.blend` using Blender's Pack Resources; this
plugin does not execute scripts embedded in an imported `.blend`.

## Verification evidence

Automated tests are in `tests/test_motion.py` and `tests/test_motion_engine.mjs`, covering formula
injection, non-finite values, joint limits, reverse seek, parent-child FK, a broken binding, clip
retime/trim, package round-trip, native v7 core round-trip, per-part scope/version, and undo not
overwriting other chats.

Real verification material (outside the repo): `~/test/claude-blender/runs/studio-motion-20260923/`.
Blender created a real two-bone skinned GLB; a per-vertex check over 61 frames / 1488 vertices
found a maximum PKF-vs-baked-GLB error of `6.17e-9 m`; a new local X-bend channel had a maximum
error of `2.65e-8 m` with a vertex displacement of `0.566 m`. The source clip vs. re-baked
comparison had a maximum error of `1.25e-8 m`, with an actual vertex displacement of about
`0.120 m`.
The observation pipeline also reopened it in a real Blender instance, generating three poses ×
two views with the corresponding deformed-mesh snapshots.
UI verification used a real packaged MCP app, a real backend, and headless Chromium WebGL:
parameter changes/save, timeline playback, skeleton import, the "have GPT rig it" request,
continuous window resizing, and switching editing modes — no pageerror, and asset-request peak of
1. This is not the same as a human's hands-on acceptance of dragging in a native Codex window, nor
does it represent naturalness acceptance for a complex character.

This round's source tests: 85 Node and 76 Python/MCP regression tests passed. The install source
was kept and merged into another task's shell recipe, with 86 Node and 40 related Python/MCP
checks passing. The final cached version is `0.7.2+codex.20260923024845`. Old chats need to start a
new task to load the new tools; no server in use by another task's chat was interrupted.

High-face-count stress test: a 1,310,720-face, 55,051,304-byte GLB, using a real install cache +
an isolated backend + Chromium WebGL.
12 consecutive window-size changes took about 434 ms, with 3 draw calls total (including scene
helpers), 0 resource re-reads, 0 draws while paused and idle, and 0 pageerror. Recorded outside the
repo as `installed/performance.json`.
This test covers render scheduling and resource re-reads; it is not an equivalent test of the whole
window-composition performance of native Codex/Electron.
