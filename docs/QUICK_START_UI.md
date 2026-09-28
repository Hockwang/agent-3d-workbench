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

The bar below the workspace tabs is always available:

- **Current model** returns to the editable scene and fits the view. Viewing a
  generated result does not import another copy into this scene.
- **Open file** opens the local file chooser directly. Supported inputs include
  GLB and STL. If a host cannot upload files, the local-path field opens instead.
- **Recent results** lists completed modelling and processing outputs in the
  current project/workspace. Search by result title or filename, then choose
  **View result** or **Output files**. Observation runs remain in Observe.
- **Attach selection to chat** (Codex panel only) adds the selected parts to the
  message composer when clicked. Opening or importing a model does not attach
  anything automatically. The button is disabled without a selection.

Selection attachments are snapshots, not model files. Changing or clearing the
selection, changing the model, or closing the panel removes its attached snapshot.
Two old panels may have left two cards in the composer in earlier versions; use
each card's **×** to remove them without deleting your model. Close old workbench
panels and reopen the workbench to load this UI update; no MCP process restart is
needed for this change.

Output files place the main model/interactive page and ZIP package first.
**File location** exposes a selectable local path; **Save** downloads the file.
**Import to editor** adds the result to the current scene; use Current model to
return to a model that is already imported.

An empty workspace presents Open file in the centre and folds the editing and
delivery panels until they are needed. Existing panel preferences are retained.

Browser links returned by `studio_open(presentation="browser", task_id="…")`
include the target workspace and task, so opening one selects that result.
Existing running MCP processes load this Python change on their next restart;
web UI files take effect on page reload.
