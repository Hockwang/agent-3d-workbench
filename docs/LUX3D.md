> 中文：[zh-CN/LUX3D.md](zh-CN/LUX3D.md)

# Lux3D Integration and Aholo Capability Parity

Independently implemented from the public interface contract of [Aholo-Lux3D](https://github.com/manycore-research/Aholo-Lux3D) commit `71779ccd8290e999d980621439c728524830f422`, baselined 2026-09-23. Does not copy its skill, client, or business logic.

## Configuration and operations

Under "Workbench top bar → API settings," pick the Lux3D domestic (CN) / global template; you can fill in an encrypted key or bind to an environment variable. Defaults are `LUX3D_CN_API_KEY` for domestic and `LUX3D_GLOBAL_API_KEY` for global; you can also bind an existing variable name such as `AHOLO_KEY`. MCP saving only accepts variable names, never key values. No GPT API configuration needed.

| Region | API root | Auth |
| --- | --- | --- |
| Domestic (CN) | `https://api.aholo3d.cn` | `Authorization: <raw key>` |
| Global | `https://api.aholo3d.com/global` | Same as above; accounts/keys are not shared between regions |

AI first calls `studio_services(action="list")` to find the actual connection ID, then `balance`, then `quote`. A single quote sends operation, params, and inputs; a quote for multiple items sends an `items` array (1–50 items). To generate, use `studio_task(action="start", provider=connection ID, operation=..., params={...original params, quote_id, quote_item}, inputs=[...])`. A single quote_item defaults to `"1"`; for a planned item, use the index string returned by the quote.

The UI provides balance, quoting, starting a task, remote history, and resuming collection by task ID. The quote is shown before starting; if the parameters, inputs, or account change, or the quote has expired, reuse is rejected. The quote is an estimated pre-discount credit cost, not the final charge. A generation target the user has already authorized can run against their quota; the quote itself does not substitute for authorization. Canceling the local wait does not mean a remote refund.

The quote requirement is enforced server-side, not only by the UI: the adapter's `prepare_payload` rejects any paid operation that arrives with neither a `quote_id` nor a `remote_task_id` (recovering an already-submitted remote task never spends again), so a caller that skips the UI and goes straight to `studio_task` cannot bypass quoting. A `services.json` entry can opt out with a declarative `allow_unquoted: true` flag; the built-in `lux3d`/`lux3d-global` templates never set it, so quoting is required by default.

## Capability parity

| Aholo capability | Studio entry point | Verification and boundaries |
| --- | --- | --- |
| Domestic/global key, balance, membership and trial info | `studio_services` / service panel | Contract and simulated service; real account still to be verified |
| Single-item and whole-plan quotes | `quote` single item or items | Bound to the request, account, and file SHA, with an expiry; never fabricates an unknown price |
| Single-image, multi-image generation | image-to-3d, multi-image-to-3d | G1/G1-Turbo; local upload or img/imgs; up to 32 images |
| Text-to-3D, style, face count, size parameters | text-to-3d | Validated per version; G1 and Turbo parameters cannot be mixed |
| Material repaint | material-transfer | GLB + reference image; version v3.0-standard |
| Four-view, reference-image assistance | four-view, multimodal-image | Fixed four-image order/count; the latter is an upstream internal helper endpoint |
| Multi-format conversion | multi-format-export | GLB or a native Lux3D ZIP → USDZ/OBJ ZIP/FBX ZIP/STL/3MF |
| Asset upload | Uses the regional Asset API automatically | Single file/chunked; the storage side only carries a short-lived OUS token, never the account key |
| Query, task history, resume collection | remote_task, remote_tasks, task resume | IDs are passed as strings; history supports pagination, status, and a millisecond time range |
| Failure recovery and duplicate-submission prevention | task receipt | POST is attempted only once; if the response is unknown the record is kept and never blindly resubmitted; a failed download can be resumed |
| GLB inspection, compressed assets, animation | Workbench preview and offline web page | Shares the Three.js loader; Draco, Meshopt, and KTX2 were actually tested, with zero external requests |
| Post-generation editing, layout, materials and parametric processing | `studio_edit`, local Blender/CAD, `studio_motion` | Reuses existing tools; the original artifact is kept, and editing produces a new asset/version |
| Scene assembly, motion, rendering and workflow orchestration | Current Codex + `studio_task` | Uses already-installed local tools; no need to configure another general-purpose model API |
| Offline model delivery, model switching, motion playback | viewer-page / interactive-scene | Self-contained HTML; can switch between multiple models, WASD and hotspots; reuses existing task templates |
| Interactive experiences/gameplay goals | GPT-written local scripts and web pages, as available today | General scripting capability is available; does not claim to cover every kind of gameplay or to have reached quality parity scene-by-scene |

After a normal Lux3D GLB is collected, you can "bring it back into editing" and then change materials, transforms, cut it, and save. **Preview/offline delivery** for compressed GLBs has been added; static editing and rigging are still constrained by what Trimesh/Blender can import — a complex source like KTX2 should first be converted to an editable, self-contained GLB, and a successful preview should not be described as lossless editing.

PLY is a fully-saved output file; there is currently no Gaussian-splat renderer, and the upstream Aholo viewer likewise displays mainly via GLB. ZIPs are saved as-is with an integrity check, and the contents' filenames are never guessed. Format conversion is not a mesh repair or a print-validity guarantee.

## Resuming

- Existing local task: `studio_task(action="resume", id=...)`, continuing to poll/download under the original task ID.
- Only a remote ID: keep the original operation/version/outputFormat, pass `params.remote_task_id="..."` to start collecting — this never creates a new remote generation. The UI's "resume collection" follows this route.
- Submission timed out with no reliable ID: use remote_tasks to reconcile first, find the task, then resume. Do not resubmit a paid generation just because the local run failed.
- A successful artifact carries a `service.json` recording the provider, region, task ID, and SHA256; you still need a real observation image for appearance acceptance. Signed result URLs never enter the delivery manifest.

## Verification status

This round used local HTTP fixtures to verify the request/response contract, upload, quoting, collection, identity checks, resume, errors, and key isolation; a browser test ran the full chain from quote to import-into-editing against the real Studio backend. Compressed models were verified with the Khronos Draco Box, a Three.js KTX2 sample, and a generated Meshopt triangle, and the offline canvas was checked to actually have an image.

No Lux3D-specific credentials were found in the company/personal environment configs or Studio connections examined on this machine, so **the domestic or global site's real-account balance, billing, and model-generation acceptance has not yet been completed, and full capability and quality parity cannot be claimed**. Once connected, run at least one real image-to-model or text-to-model job, and keep the task ID, quote, original artifact, edited artifact, and observation report.

### Open gap: LUX3D-LIVE-001

- Status: no Lux3D-specific key, pending a usable domestic or global account configuration. On 2026-09-23 the user asked for this gap to be recorded, and for an alternate-chain test using the company OneAPI Hunyuan.
- Alternate verification available: submission, polling, and collection through a professional 3D service, unified preview, bringing it back into editing, exporting, and Hunyuan Part splitting.
- Cannot substitute for: Lux3D regional auth, balance and plan quoting, asset upload, real billing, and server-side compatibility for the seven operation categories. A Hunyuan success does not close this gap.
- Closing condition: a valid regional key is configured, and at least one real Lux3D generation runs the full quote-to-collection, observation, and editing path; every other operation is recorded either as a real success or an explicit limitation — full capability parity is never inferred from one sample.

The company OneAPI alternate chain has been tested and passed; see [Hunyuan real verification and normal-fixing](history/VALIDATION_20260923_ONEAPI_HUNYUAN.md). This gap is still open.

Test entry points: `tests/test_lux3d.py`, `tests/test_projects.py`; run with `uv run pytest -q` and `node --test tests/*.mjs`; frontend with `npm run build:app`.
