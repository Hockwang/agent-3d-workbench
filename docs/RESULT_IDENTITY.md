[中文](zh-CN/RESULT_IDENTITY.md)

# Make a delivered model findable

In Modeling & tasks, the **Latest delivery** shelf shows the most recently completed work in the current
project. Its latest variants remain side by side (for example, local, generated,
and split). **Task overview** groups other work and folds earlier versions.
The header identifies the actual preview file, route, version and completion time.
Previewing a result preserves the editing scene. **Add to editing scene** is a
separate, explicit append operation.

**Task overview** is available across workspaces. The editor shows only its current
scene and object list; latest-delivery cards stay in the task view. The project
workflow is folded by default. This hierarchy does not assert that an imported
scene came from a particular task; provenance must come from actual result metadata.

## Agent handoff

Do not finish with only a filesystem link or a result in a disposable test workspace.
Deliver through a task bound to the user's current project. If the files were made
elsewhere, register only the explicitly chosen model and thumbnail with an ordinary
Python task:

```json
{
  "action": "start",
  "engine": "python",
  "script": "from studio.core.result_manifest import register_existing\nregister_existing(workbench)",
  "inputs": ["/absolute/path/cup.glb", "/absolute/path/render.png"],
  "params": {
    "work_id": "cup-demo",
    "work_title": "Cup",
    "variant": "Local · four parts",
    "version": "v1",
    "note": "Dimensions are design assumptions; no physical test."
  },
  "title": "Cup · Local · v1",
  "render_preview": false
}
```

Use the current `workspace_id` binding described in [the agent playbook](AGENT_PLAYBOOK.md).
The thumbnail input is optional. The helper copies the specified files, verifies
their hashes, and writes display metadata. It does not import, merge workspaces,
call a generation API or copy credentials. Poll `studio_tasks` until completed;
check `result` and the actual GLB artifact. Then use
`studio_open(mode="tasks", task_id=ID)` to show the result. Verify the editing
scene's revision and object IDs remain unchanged when only previewing.

Before retrying a completed registration, check current tasks for the same work,
variant, version and model SHA256; reuse that result instead of creating duplicates.
Use a stable `work_id` for one work and a stable `variant` per route/stage. Increment
`version` for a new revision. Changing `variant` creates a parallel card rather
than an older version of the same route.

## Optional manifest for task authors

A task that already writes a GLB can also write `workbench-result.json` into its
output directory. It uses the same fields above, plus:

```json
{
  "schema": "workbench-result/v1",
  "work_id": "cup-demo",
  "work_title": "Cup",
  "variant": "Generated",
  "version": "v1",
  "note": "Single mesh; scale is not measured.",
  "primary": "scene.glb",
  "thumbnail": "preview.png"
}
```

`primary` must refer to a delivered GLB; optional `thumbnail` must refer to a
delivered PNG, JPEG or WebP. These are artifact names, never external URLs. Titles
and notes are plain text, and notes describe limitations rather than verified
acceptance badges. The worker rejects malformed metadata or missing references.
No manifest is required for older tasks: they still appear when they have a primary
GLB, with rebuilds grouped by `source_task`. Successful probes and report-only tasks
remain under **All task history** and are not presented as models.
