> 中文：[zh-CN/MERGE_A8_WORKSPACE.md](zh-CN/MERGE_A8_WORKSPACE.md)

# Merge / A8 Workspace Trial Integration

2026-09-22. Reuses the unified merge_ui / A8 / URDF viewer kernel from the author's research repo, brought into the Codex right-side workspace through the existing Python tasks and offline HTML artifacts. Does not start a new HTTP service, and does not depend on that research repo's install path. Source worktree, per-file SHAs, and adaptation scope are in `studio/core/kernels/scene_viewer/SOURCE.json`.

## Usage

Under "Observe & Evaluate → Splits & Mechanisms → Review Data & Records," load A8 / Merge. The two templates and existing review records no longer show up in the modeling task list. Execution still reuses `studio_task`, and does not move or rewrite historical task files. AI first opens the observation area with `studio_open({"mode":"observe"})`.

```json
{"action":"start","template":"merge-review","inputs":["/absolute/dataset/manifest.json"],"params":{"title":"Part review","units":"m"}}
```

Point it at the original manifest path, keeping the GLB, optional group.json, and reference images next to it. Uploading a standalone JSON cannot carry its neighboring resources. Old merge data may write millimeters directly into the GLB, so you must explicitly choose `units:"mm"` rather than guessing from the model's size. Providing two manifests enables current / comparison / side-by-side.

The preview supports exploded view, numbering, part-selection highlighting, original materials, X-ray, wireframe, and per-part metrics. The output `parts.glb` can be clicked into "bring back to editing," using the existing merge, connected-component split, undo, and GLB/STL export. Each source node's transform, UV, and material are preserved; a multi-primitive part may import as multiple objects. Merging is still L1 mesh stitching — it is not a solid boolean or automatic sealing.

```json
{"action":"start","template":"a8-review","inputs":["/absolute/catalog_registry.json"],"params":{"batch_id":"existing-batch","case_ids":"case-a,case-b"}}
```

You can also input the original `cases.json` / `cases.js`, while also passing the absolute path of `parts_dir`. An empty `case_ids` takes the first 8 locally available cases; at most 8 cases, 512 parts per case, with a 90 MB input-asset budget. An optional `compare_case_id` must belong to the currently selected cases, and sets it as the comparison layer for the other cases.

A8 preserves the joint parent/child, origin/rpy, axis, range of motion, and upstream audit facts. It provides overall phase, per-joint sliders, playback, joint axes, exploded view, reference images, and keyboard case-switching. An upstream blocked/provisional status is not changed to passing just because the page loaded successfully. It rejects missing parts, invalid paths, cyclic joint graphs, unknown motion types, and a resource whose provided SHA doesn't match.

G/B marks are mutually exclusive, and clicking again cancels. **Switching workspaces or reopening the preview rebuilds the iframe, and any un-exported mark is lost.** Clicking "export marks" in the workbench saves it to `task-inputs/` in the current job through the existing upload interface, and on a successful response it shows the actual path; when opening the HTML standalone, use the browser's download instead. This does not write back to the original A8 registry, and does not claim to auto-sync across workspaces. The export includes the executionKey, the full scene, and a contentSha256 bound to the actual resource bytes.

## Boundaries relative to the original app

- Already reuses the core observation and mechanism preview, with static geometry hooked into the existing editor.
- merge_ui's continuous-click auto-grouping, paint-to-split on the original faces, and group.json edit-and-write-back are not yet wired into this round's UI. The workbench already has extraction by face ID / spherical region, but that is not the original paint interaction.
- A8's registry persistence, cross-batch Golden/Bad aggregation, and MCP sync of review status are not yet integrated. AI can read the task's scene report; the temporary part-selection/phase inside the preview is not yet in the shared context.
- Mechanisms are not silently flattened when imported into the static editor. An A8 task keeps its joints in the review result; changing the joint structure or checking for collisions requires calling the corresponding model task.
- The currently packaged selection of assets is an offline snapshot, suited to reviewing a small batch; it does not copy or package the entire historical registry, nor does it claim large-scale zero-copy streaming browsing.

## Verification and performance

Isolated evidence directory: `~/test/claude-blender/runs/workbench-merge-a8-20260922/`.

- Two real splitting rounds of Inuyasha 013 / A: 9+9 parts compared; the main version brought back into editing has 9 parts, 571,892 faces; merging two parts into 8 leaves the total face count unchanged; undo restored all original objects and transforms; GLB export succeeded.
- Parametric A8 with a real four-drawer file cabinet / single-door nightstand: 5 links / 4 prismatic joints, 2 links / 1 revolute joint; overall open/close, single-joint endpoints, playback, and axis direction were verified in the embedded page. Four-drawer travel is 0.38642 m, door travel is 0.976992 rad, taken from the original data and not a new estimate.
- A8 idle for 4 seconds: 0 draw calls, 0 canvas resizes. Simulating 4 seconds of continuously resizing the iframe's width/height plus 0.5 seconds settled: 2 canvas-attribute writes (one rebuild), 51 draw calls (including shadows and axes), no task over 50 ms. Reuses the workbench RenderLoop's 150ms resize-settling strategy.
- Merge with two versions side by side, numbering and exploded view on: likewise 0 draw calls / 0 canvas resizes idle for 4 seconds; after continuously resizing width/height, one canvas rebuild, 48 draw calls, no task over 50 ms. Host RAF max interval 15.1 ms, P95 13.9 ms; this is not the frame rate of continuous model animation.
- This result is from testing an isolated MCP App host page, and does not represent overall FPS in a native Codex window.
- Test coverage includes unit conversion, node transforms/materials, input byte fingerprinting, read-only original files, joint-graph/path negative cases, offline package integrity, and regression of existing tasks/editing.
- Full Python regression: 288 passed, 2 deselected (Bambu excluded); Node: 59 passed. After the final DOF-count adjustment, a targeted rerun: 8 passed.

Build: `npm run build:app`. Targeted: `uv run --frozen pytest -q tests/test_assembly_review.py`; `node --test tests/test_assembly_bundle.mjs tests/test_render_loop.mjs`.
