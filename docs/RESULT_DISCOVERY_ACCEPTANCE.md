# Result discovery acceptance · 2026-09-29

Problem: the editor, generated task outputs and isolated demonstration workspaces
did not share a clear model identity. Recent task timestamps also placed probes or
reports ahead of the model the user wanted to see.

## Changes

| Files | Behavior and reason |
| --- | --- |
| `studio/web/quick-access.js:35`, `studio/web/result-model.js:28` | Persistent latest-delivery cards; actual viewing identity; models grouped by work and variant, ordered by completion time; older revisions folded. Reports remain in full run history. |
| `studio/web/tasks.js:68`, `studio/web/workspace.js:573` | Preview first; new-task form and unrelated recipe hidden while browsing a result. Files/logs start folded. Explicit append-to-editor and download actions. Returning to an already displayed preview restores the correct identity. |
| `studio/web/studio-layout.css`, `studio/web/locales/zh-CN.js`, `studio/web/locales/en.js` | Thumbnail cards, visible selected version, horizontal overflow on narrow displays, bilingual labels. |
| `studio/core/result_manifest.py:34`, `studio/core/task_worker.py:144` | Optional display metadata bound to delivered artifacts. Ordinary Python tasks can register an external GLB and real thumbnail into the current project without editing its scene. No MCP tool schema or service API change. |
| `tests/test_result_manifest.py`, `tests/test_result_model.mjs`, `tests/test_quick_access.mjs` | Artifact reference validation, source-byte preservation, editor preservation, persisted identity, work/variant grouping, legacy rebuilds and completion-time ordering. |
| `README.md`, `README.zh-CN.md`, `docs/RESULT_IDENTITY.md`, `docs/zh-CN/RESULT_IDENTITY.md`, quick-start and agent playbooks, `skills/print-prep/SKILL.md` | Human entry points and the agent's obligation to register deliveries in the actual project. |
| `studio/app/dist/studio.html` | Rebuilt native MCP App with the updated interface. |

## Fresh verification

- `uv run pytest -q`: **722 passed, 2 skipped** (210.69 seconds).
- `npm test`: **143 passed** after the final UI changes.
- App-resource reload and browser-entry regression: **3 passed** after rebuilding.
- `make lint` and `git diff --check`: passed.
- Built the app in the public source checkout and the locally installed plugin.

Real current-project acceptance used the existing cup comparison files; no new
generation API submission occurred. Three ordinary MCP registration tasks completed
and retained the source SHA256 values: local four-part model, generated single-mesh
model, and display-normalized two-part model.

In the real browser UI, each card opened the matching model and route/version/file
identity. The model search grouped all three under the same cup work and excluded
`network_probe` reports. New task remained accessible, and selecting the same result
again hid the form while retaining the correct preview. Files and logs were folded.
Reload preserved the registered results. Chinese/English and a 560 × 850 viewport
were inspected; the narrow shelf scrolls horizontally. The original viewport and
Chinese language were restored after checking.

Returning to the editor retained the Mew model: **11 objects, revision 1**, identical
object state and empty selection. No preview was imported. The native open tool
returned success with the generated cup task focused; host-rendered native pixels
were not separately inspected. Browser rendering and app resource reload were checked.

## Limits

Metadata is optional and is presentation, not geometry acceptance. Legacy tasks
without a shared work ID or rebuild ancestry stay separate; titles are not guessed
into groups. Source/test jobs that really contain a primary GLB remain in model
history. Thumbnails must be real supplied artifacts; missing thumbnails use a
placeholder. Registering a result is explicit rather than a global filesystem scan.
The generation demo's scale, split quality and material limitations are unchanged
and visible alongside its result.

## Editor hierarchy follow-up · 2026-09-29

The editor still combined project-wide cup deliveries, a full project workflow,
the Mew scene and empty property forms. Its object list started collapsed and put
import controls ahead of current parts. These independent scopes made it hard to
tell which model was actually being edited.

| Files | Follow-up change and reason |
| --- | --- |
| `studio/web/quick-access.js:183` | Keep Task overview available everywhere; show latest-delivery cards only in Modeling & tasks. The editor header identifies its current scene and revision. |
| `studio/web/workspace.js:542` | Wrap the existing project workflow in a disclosure, folded by default in the editor, without changing recipe state. |
| `studio/web/editor.js:96`, `studio/web/editor.js:122` | Open the current object outline by default; list parts before the collapsed Add models & assets import controls. Empty selection shows a guide; selected parts expose their existing controls. |
| `studio/web/studio-shell.js:9`, `studio/web/studio-layout.css:195` | Dock editor properties in the fixed delivery sidebar, retaining handlers while moving DOM nodes. Remove the inherited flex basis so the empty inspector does not reserve an unnecessary 310 px of height. |
| `studio/web/locales/en.js`, `studio/web/locales/zh-CN.js` | Matching Task overview, hierarchy, import and selection-guide labels; rename the sidebar Properties & delivery. |
| `README.md`, `README.zh-CN.md`, both quick-start guides and result-identity guides | Document Task overview → editing scene → Models & objects → object properties. Explain that the task result shelf is separate from the current scene. |
| `studio/app/dist/studio.html` | Rebuild and synchronize the eight changed UI source/build files to the installed plugin. |

Fresh verification after the follow-up: **143 JavaScript tests**, **3 browser-entry
and app-resource tests**, lint and `git diff --check` passed. The complete Python
suite reported earlier was not repeated for this frontend-only follow-up.

In the actual current-project browser, the outline displayed all 11 Mew parts.
Selecting `left_eye_white` showed its name and 61.35 × 34.07 × 85.03 mm dimensions;
clearing selection restored the guide. Task overview opened the Hunyuan cup result;
Back to editor restored Mew and hid the cup shelf. Import controls and the existing
workflow expanded correctly. English/Chinese labels were checked. At 560 × 850,
the cards moved below the viewport with no horizontal document overflow. The
original viewport and Chinese language were restored, leaving the editor open.

Browser automation pointer actions did not reliably activate targets in this host;
the interaction checks used the controls' keyboard activation instead. No browser
JavaScript errors were recorded. Native MCP App pixels were not separately tested.

MCP readback matched the original object state exactly: **11 objects, revision 1,
empty selection**. No geometry, recipe or task metadata was changed by this follow-up.
No commit, push or publication was performed.
