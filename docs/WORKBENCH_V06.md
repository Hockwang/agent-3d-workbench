> 中文：[zh-CN/WORKBENCH_V06.md](zh-CN/WORKBENCH_V06.md)

# v0.6: Model editing and print prep

## Implementation

`studio/core/editor.py` implements static-mesh operations using Trimesh / Manifold; it does not
reimplement a geometry kernel.

The project lives at `<job>/workbench/`; the original file is never rewritten, and meshes are
stored as immutable GLBs keyed by SHA256. `project.json` atomically saves objects, transforms,
visibility, selection, and history.

Geometry changes keep up to 30 undo states; the `.3dworkbench` produced by `save` contains the
current model and selection, but not the full undo history.

Internal units are millimeters, Z-up. A standard GLB/GLTF import is converted from meters/Y-up,
and converted back on GLB export; STL/OBJ/PLY default to millimeters/Z-up, with a choice of
units at import time.

A GLB/GLTF's multi-level nodes are flattened into objects by their world transform, preserving
geometry and materials but not the original parent/child hierarchy; skeleton, animation, and
morph-target inputs are rejected.

Ordinary transforms support exporting with the original texture; cutting, boolean, repair,
split-components, merge, and decimation output solid color — textured, multi-color, or
multi-material input needs explicit permission.

Every human button and AI operation goes through `studio_edit` and must carry the project
version. Editing against a stale version returns 409, and a failure never commits project state.

Output never overwrites an existing file. Reading in a `.3dworkbench` checks the asset SHA,
identity, matrix, and size — it never extracts the ZIP path directly onto the filesystem.

## UI and the print handoff

- The top of the right-hand panel switches between model editing and print prep; the chat still
  shows a lightweight entry card.
- Model editing provides an object tree, multi-select, transform controls, parameters, a
  cut-plane preview, split/repair/material tabs, save, and export.
- `studio_get_state.workbench` is the editing state; the original top-level `parts` /
  `selection.parts` remains the print state.
- "Send a copy to the print module" explicitly creates a world-coordinate millimeter STL and
  loads it into the existing print flow. The STL copy has no texture; printing never changes the
  editing asset.
- An editing copy can be generated from an existing print part. The print state and the editing
  state never automatically overwrite each other.
- The HTTP compatibility UI is retained; the MCP iframe reads the GLB via a resource, with
  textures coming from embedded data — it never fetches images from the outside network.
- On a narrow panel the layout stacks vertically, with parameters scrolling independently;
  collapsing the workspace pauses WebGL, and reopening it reuses the objects and camera.

## Current boundaries

- Applies to static triangle meshes: up to 5,000,000 faces per object and up to 500 objects per
  project. The editing preview uses the actual mesh, so memory and load time for large models
  grow with face count; this differs from the print module's 30,000-face display preview.
- Cutting/boolean requires a valid closed solid. If the plane doesn't pass through the solid it
  fails, without deleting the original object. Repair only covers normals, duplicate/degenerate
  faces, and small holes; the output may still have openings, and a warning is returned.
- No face-level brush selection, free-curve cutting, SEG service, joint/skinning, or generation
  API. These belong to later batches in the original plan.
- The current project save format preserves geometry, materials, object transforms, and
  selection; it is not a Blender project format.
- No push to a physical printer. Real slicing, the Bambu GUI, and physical-part quality are kept
  separate from editing verification.

## Verification entry points

```bash
uv run --locked pytest -m 'not bambu' -q
node --test tests/*.mjs
npm run build:app
```

`tests/test_editor.py` covers: cutting a solid/volume, rollback on failure, version conflicts,
round-tripping a textured GLB's units/coordinates/names, multi-select transforms, exporting
hidden objects, persistence and project-SHA verification, boolean/connected-components,
repair/decimation, rejecting animation input, and HTTP origin/token checks.

`tests/test_mcp_server.py` adds a real stdio test: a human creates → the AI cuts → the human
undoes → GLB resource read and export.

An isolated browser host verifies the real MCP handlers and embedded HTML; this does not
substitute for visual acceptance in Codex's native right-hand panel.

Automated UI tools cannot operate Codex itself; only a new task after installation reliably
picks up the updated tools and skill.

2026-09-21 results for this round: 94 Python tests passed, 2 real-hardware Bambu tests not run;
14 Node tests passed; the self-contained MCP App build succeeded.

Isolated UI verification covered host sizes 420×700, 420×420, and 900×840, a textured GLB,
cutting/transforms, GLB export, the print-copy handoff, and loading an existing print part.
