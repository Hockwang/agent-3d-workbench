[中文](zh-CN/QUICK_START_UI.md)

# Find your models and results

Ask your agent to open the 3D Workbench. In Codex, the chat card's **Open model in
side panel** button opens the editor. The card and the workbench show the project
name; open another project's workbench from its own chat. You can also open the
native **3D Workbench** entry directly in a Codex chat: it binds automatically
using that request's `_meta.threadId`, without asking you to copy an ID.

If an older running version reports **No workspace bound** when opening this
entry, quit and reopen Codex after updating the plugin. The error page's **Retry**
button repeats the call; it does not reload the Python MCP process. Your models
and results remain on disk. Until restart, asking the agent to open the current
chat's workbench supplies the ID explicitly and works with the old process.

The entry bar below the workspace tabs is always available:

- **Latest delivery**, in Modeling & tasks, shows thumbnail cards for the latest work, with its local,
  generated and split variants together. Click a card to preview; the header identifies
  the route, version, completion time and actual file.
- **Back to editor** returns to the editable scene and fits the view. Viewing a
  generated result does not import another copy into this scene.
- **Open file** opens the local file chooser directly. Supported inputs include
  GLB and STL. If a host cannot upload files, the local-path field opens instead.
- **Task overview** groups completed GLB results by work and folds older
  revisions of the same variant. Search by title or filename. Logs and report-only
  tasks stay under **All task history**; observation runs remain in Observe.
- **Attach selection to chat** (Codex panel only) adds the selected parts to the
  message composer when clicked. Opening or importing a model does not attach
  anything automatically. The button is disabled without a selection.

Model editing follows **Task overview → editing scene → Models & objects → object properties**.
The object list opens by default and puts current parts first; **Add models & assets**
contains the import tools. Selecting a part reveals its controls in the fixed right
sidebar. With no selection, a short guide replaces the empty forms. **Project workflow**
starts folded in the editor and can be expanded when needed.

Selection attachments are snapshots, not model files. Changing or clearing the
selection, changing the model, or closing the panel removes its attached snapshot.
Two old panels may have left two cards in the composer in earlier versions; use
each card's **×** to remove them without deleting your model. Close old workbench
panels and reopen the workbench to load this UI update; no MCP process restart is
needed for this change.

Output files place the main model/interactive page and ZIP package first.
**File location** exposes a selectable local path; **Save** downloads the file.
**Add to editing scene** adds the result to the current scene; use Back to editor to
return to a model that is already imported.

An empty workspace presents Open file in the centre and folds the editing and
delivery panels until they are needed. Existing panel preferences are retained.

Browser links returned by `studio_open(presentation="browser", task_id="…")`
include the target workspace and task, so opening one selects that result.
Existing running MCP processes load this Python change on their next restart;
web UI files take effect on page reload.

While browsing a result, the new-task form is hidden and files/logs start folded.
Use **New task** when you want to create another model. Agents should follow the
[result handoff contract](RESULT_IDENTITY.md) so new outputs appear here.
