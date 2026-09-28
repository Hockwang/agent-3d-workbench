> 中文：[zh-CN/FOLDER_PROJECTS.md](zh-CN/FOLDER_PROJECTS.md)

# Folder-Based 3D Project Management

2026-09-23, per user confirmation: a project folder owns its models and scene, tasks in the same
directory collaborate, and a new worktree is isolated.

## Usage

- The first time a new task created inside a Codex project calls Studio, it reads the real cwd via
  the official `thread/read`. A subdirectory inside a Git repo is attributed to the current worktree
  root; a plain directory uses its absolute path.
- Plain tasks in the same directory connect to the same project, backend, and assets. After a model
  edit is committed, other open editor UIs sync roughly once a second; during a drag, only the local
  preview updates.
- Each task still passes its own `workspace_id=CODEX_THREAD_ID`. Selection, undo/redo, and part scope
  are independent; the camera belongs to the current page. You cannot borrow someone else's task ID to
  get around scope or a write lock.
- Only one editor at a time can hold a lease on a given part. Different parts can be edited in
  parallel; a stale lease renewal from an old page cannot reclaim a part that has already been
  released. Edits still require `expected_versions` and `expected_revision`.
- A chat branch created via right-click keeps its designated part scope; auto-connect, reconnect, or
  opening the project does not widen it to the whole scene.
- The "Project & Delivery" UI shows the project directory. A plain directory needs neither Git nor a
  new GPT API.

`studio_workspaces(action="project")` shows the current binding; `action="open_project",
worktree="/absolute/dir"` opens one explicitly. `list` includes folder, owner_workspace_id, revision,
and object count. If the current task is already bound to another directory, switching is rejected, so
an old panel can't submit operations against a new project.

## Storage

Model data lives inside the project:

```text
<folder>/.3dstudio/project.json           # project entry point
<folder>/.3dstudio/job/workbench/         # scene, assets, motion, history
<folder>/.3dstudio/job/tasks/             # modeling tasks and their outputs
~/.print-prep/workspaces/project-<hash>/  # port, access token, directory location
~/.print-prep/workspaces/<task>/          # task binding and local chat-access grants
```

The run ID is computed from the normalized directory; two worktrees with byte-identical files still
don't connect to the same backend. Symlinking `.3dstudio/job` to another directory is rejected. The
first time a copied project is opened, it clears the old directory's members, leases, and undo history
while keeping the model and assets. A project can be moved and reopened; an old task's binding still
points at the old path and is not silently redirected.

`job/tasks` is working material — it may contain raw input URLs, temporary requests, and logs — and
should not be treated as a public deliverable bundle wholesale. For external use, go through `save`,
`export`, or an offline-output template. Professional-service keys and the local port token are never
written into the project entry point or into model deliverables.

## Original Projects and Model Branches

An old session's project and an explicit chat binding are kept in priority and are never auto-merged
with an existing model history in the same directory. Migrating into a folder requires an explicit
`open_project(source_id=current task, expected_revision=original revision, worktree=empty directory)`;
this copies the model and motion assets, leaving the old files unchanged. It never migrates an old
generation task, print plating, or an external `.blend` working directory.

Isolated experiment: before a new task in a different directory/worktree opens anything for the first
time, run `open_project(source_id=source task or a project ID returned by list, expected_revision=source
revision, worktree=empty target directory)`. This preserves a branch baseline; changes do not write back
to the source. `merge(expected_revision=source's current revision)` checks conflicts part by part before
explicitly merging them in. The old `fork` can still create a session-scoped copy.

Copying an existing `.3dstudio` directly with Git produces an independent scene, but does not
automatically generate Studio's merge baseline; to use Studio's `merge`, branch via the explicit
`source_id` method above instead. There is currently no automatic rebase or geometry conflict merging.

## Verification

`tests/test_projects.py` covers concurrent connections, independent selection and undo, conflicts on
the same part, restart recovery, an unchanged old source hash, scope not widening, isolation across
directory copies, branching-then-merging from a project ID, and symlink rejection. `tests/test_part_chat.py`
covers a chat in a Git subdirectory still forking at the original cwd, and joining the project root's
part scope.

Two-page MCP App integration test: quote → simulate generation → receive → import into editor → rename
in another session → the original session updates, measured sync at 534 ms; continuous window resizing
produced no white screen. It verifies the UI collaborating with a real Studio backend, with the
generation provider being a local test service.
