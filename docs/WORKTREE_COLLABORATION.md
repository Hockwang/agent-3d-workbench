> 中文：[zh-CN/WORKTREE_COLLABORATION.md](zh-CN/WORKTREE_COLLABORATION.md)

# Part Collaboration Within the Same Worktree

Confirmed by the user on 2026-09-22: chat branches within the same project share the model; only a new worktree splits off a model copy. Existing independent projects are not merged automatically.

2026-09-23: new plain tasks connect to their [folder project](FOLDER_PROJECTS.md) by default; part subtasks keep their original scope. Existing independent projects are still shared only through an explicit invite.

## State and Entry Points

`workspace_id` is still the calling task ID. `workspaces/<session>/binding.json` explicitly binds to the task that owns the project, and all associated tasks reuse the same backend. The project document `collaboration` stores the normalized working directory, members, each member's selection/undo stack, a per-object monotonic version, a 5-minute write lease, and one-time invites. The whole document is committed atomically inside the original project lock; camera and tool state stay with each UI instance. A shared project's `widgetSessionId` also carries the task ID, so a host cannot reuse another chat's UI instance.

Right-click a model or a list entry → "Create chat branch" uses the app-only `studio_part_chat`, which forks directly through the already-authorized official App Server, verifies the source and directory, and binds the specified part; it does not message the parent task and does not start a repair round. The first local integration requires a human to turn it on in the UI. Users can still go through the native fork/invite/join flow when they explicitly ask for it in conversation. A git-subdirectory task forks in its original cwd; collaboration attributes to the project root.

`invite` requires the project version and the real working directory; `join` validates a one-time invite, the directory, the part version, and the lease, and refuses to overwrite an already-existing target project. A model `fork` drops collaboration-member information and becomes an isolated copy.

## Editing Rules

- Both humans and the AI go through the same editor transaction; the HTTP header `X-Studio-Workspace` carries the chat identity. A shared write without a member identity is rejected.
- Passing `expected_versions` is recommended. Other parts changing in the project does not block a commit to the current part; a stale version of the current part is always rejected, even if the lease has expired.
- A subtask may only modify its bound part and anything derived from it. Replacing the whole project wholesale is disabled in shared mode.
- `replace` swaps a repaired file into one original part while keeping the project's coordinate frame; a multi-mesh replacement becomes a derived part, and the first mesh keeps the original ID. "Replace selected part" from task artifacts is supported.
- Undo persists a per-object inverse operation for the current session; it does not restore a whole-project snapshot. A subsequent edit by anyone else invalidates that inverse operation instead of overwriting it; consecutive self undo/redo still works.
- Every edit persists a new model version; an active shared UI instance polls for updates once per second. This is bounded polling sync, not a frame-by-frame broadcast of an in-progress drag. During a drag, only a local preview is shown; sync happens after the drop is committed successfully.
- The lease defaults to 5 minutes; an open UI renews its own lease once a minute, and the menu can release it. Long-running background operations should renew actively; an abandoned lease simply expires. The lease never substitutes for a version check.

## XYZ Gizmo Fix

An imported GLB's root may sit at the origin while its mesh vertices are already at the assembled position. `TransformControls` is now bound to a standalone proxy whose position is the world-space bounding-box center of the part. Dragging produces a world-space delta, which is then multiplied by the object's original world matrix and converted back into the parent's local matrix. The geometry asset, its units, and its assembled position are never rewritten.

## Boundaries

This is a same-user, same-machine collaboration conflict mechanism, not a sandbox that isolates arbitrary local scripts. Directly modifying `project.json` to bypass the tools is outside this contract. What is shared is the model-editing project; print plans and task artifacts are still per-task resources. Part-view selection and camera stay independent per view — this does not claim that the entire print/observation module is isolated per chat.

Verification includes pure-math regression of the offset gizmo, dual-session MCP bind/conflict/isolated-branch tests, persistence/lease-expiry/consecutive-undo/external-repair-replace tests, and browser dual-UI sync. Native "create new chat" only runs after the user clicks it; automated verification uses a simulated host message and never creates a real user task on its own.
