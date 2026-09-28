> 中文：[zh-CN/AGENT_WORKSPACE.md](zh-CN/AGENT_WORKSPACE.md)

# Product Principle: Let AI Operate and Verify 3D the Way It Writes Code

Confirmed by the user on 2026-09-22: day-to-day work such as viewing models, observing, and evaluating new WaveAB routes should all happen inside this Codex workbench. Capability comparisons against external similar products are still kept for reference, but they are not the product boundary.

## Every Capability Must Close the Loop

1. **Read state**: objects, versions, units, coordinate systems, selections, and running tasks all return structured results. The AI should not have to guess controls from screenshots or parse terminal text to find a path.
2. **See evidence**: the model must be able to return real observation images directly. Bounding box, face count, or "execution succeeded" alone is not enough to judge whether shape and motion are correct.
3. **Execute and continue**: operations that existing tools can already do are called directly; open-ended tasks fall back to Blender/Python/CAD. Long-running jobs return an ID that can be queried, cancelled, and inspected for failure records; artifacts stay in the same workspace for continued processing.
4. **Compare and verify**: version comparisons share the same camera and scale, and separately retain quality evidence, run time, agent usage, and service cost. Unknown values stay unknown; observation-image render time is never counted as generation-route time.
5. **Humans take over on the same state**: common operations are done through selection and buttons, and AI and humans use the same backend. Manual input is never overwritten by polling; the version/pose the AI selects is shown in the workspace, and the human's selection can likewise be read by the AI.

Cost is measured against the consumption of completing the whole task, not just the number of tool calls. By default, a concise set of metrics plus one overview image is returned; single images, part lists, and logs are fetched on demand. Hidden views stop rendering, and multiple high-poly models are never kept resident at once.

## Selection Is Context

The current selection in the model-editing or print workspace becomes MCP context for the next message. The card title shows "Selected N part(s): name…"; the content only includes the ID/name, dimensions, face count, job, and version of the selected objects — never the mesh itself. Multi-selection preserves selection order; before making a change, the AI must still confirm the latest state with `studio_get_state`.

- No attachment is created for an initially empty selection. Old attachments are cleared when the selection is emptied, all selected objects are deleted, or the workspace switches to one with no part selection.
- Renames, dimension changes, and version changes update the snapshot; polling with unchanged state does not resend, and once the user closes the attachment it is not re-added by a subsequent unchanged poll.
- Rapid changes are submitted serially and intermediate states are coalesced, so an older request cannot overwrite a newer selection. If the host temporarily fails, the next refresh retries.
- The local Codex extension `ui/update-model-context` supports `presentation.composerLabel`. A clear request uses `content: []` and omits `structuredContent`; an empty structured object would still create a card. Standard MCP content and structured data are preserved; whether other hosts display the title depends on their own implementation.

Verified (2026-09-22): 50 front-end checks and 34 MCP/workspace regression checks passed. Using the actual shipped HTML, the actual Python MCP handlers, and an isolated backend, a browser test host exercised create, rename, multi-select, resize, deselect, and mode switching; receipts matched the selection, and the tests did not modify any real user job. Title and clear-field behavior were checked against the schema/handler code of an installed Codex; the browser test host is not equivalent to the visual acceptance of Codex's native composer.

## Shipped: Observation and Evaluation

New entry point on the right side, `studio_open({mode:"observe"})`. `studio_observe` has four actions:

```json
{"action":"start","inputs":["/absolute/baseline.glb","/absolute/candidate.glb"],"labels":["baseline","candidate"],"params":{"views":["front","right","top","iso"],"phases":[0],"resolution":512}}
```

You can also pass `source_tasks:["task A ID","task B ID"]` to compare directly against models already delivered by the workbench and read their measured `elapsed_seconds`. The two input sources are mutually exclusive. Up to four versions per run; one GLB or URDF represents one complete route — four parts must not be mistaken for four routes.

- `start` is non-blocking and reuses the persistent task executor. Once a task completes, `read` returns the report; the MCP attaches real PNG `ImageContent` by default, not base64 text stuffed into context.
- `read({id,image:false})` returns metrics only; `detail:true` includes the part list; `image_file` optionally returns a single original-resolution image listed in the report.
- `focus({id,variant:0,phase_index:1})` lets a human and the AI focus on the same version and pose. `read` without an `id` returns the current focus.
- `review({id,expected_sha256,verdict,note})` records a verdict; `expected_sha256` uses `read.report_sha256`. A reason is required, human and AI sources are listed separately, and a verdict on an old version is never silently applied to a newer artifact.

Model loading reuses Trimesh; URDF parsing and forward kinematics reuse the open-source yourdfpy, keeping intermediate links that have no visual. Rendering reuses the local Blender install; both the PNG and the interactive preview come from the same evaluated pose. All versions share the same bounding range and camera — none are individually centered or scaled in a way that would mask scale/position differences. Blender keeps only one version/pose resident at a time, to avoid stacking multiple high-poly models in memory.

URDF loading can specify `params.urdf_up:"z"|"y"`; some WaveAB artifacts are Y-up, so this must be confirmed at the source rather than inferred from the `.urdf` extension alone. STL/PLY are millimeters/Z-up; GLB is meters/Y-up. Every input and every URDF visual dependency has its SHA256 recorded, and the observation checks that it is unchanged when it finishes. Output saves the frozen-pose GLB, PNG, camera parameters, and JSON metrics; the model file itself is never modified.

## Hooking Up WaveAB Route Evaluation

The existing WaveAB runner and evaluation standard remain the authoritative source. The AI can call the existing runner, with its real parameters, from a trusted Python script inside `studio_task`, delivering the GLB and run report to the task output; a comparison can then be created from `source_tasks` or the artifact path. A second cutting/joint-solving route must not be duplicated just to hook into the workbench.

This round's real-world acceptance test used the WaveAB robot and windmill URDFs already present in the author's research repo, to validate artifact loading, motion sampling, the evidence chain, and the interaction chain. It is not a quality or performance ranking of a new route; no new remote generation batch was triggered automatically, and no missing token/cost data was inferred.

Still to be integrated as dedicated work: one-click discovery of arbitrary research directories/remote batches, a frozen evaluation protocol and batch scheduling, ground-truth-based quality metrics, full ingestion of elapsed time/tokens/service cost, and continuous-collision/motion-naturalness detection. The observation interface provides evidence; it does not auto-grade a model as "correct" when there is no standard to grade against.
