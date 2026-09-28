> 中文：[zh-CN/WAVEAB_EVALUATION_PLATFORM.md](zh-CN/WAVEAB_EVALUATION_PLATFORM.md)

# WaveAB Evaluation Platform Integration

The workbench's "Observe & Evaluate → Route Review" reads batches and evidence through the original platform's API, and saves reviews there. The original platform continues to own the database, metric algorithms, history, and frozen reports; the plugin only stores connection settings, the currently shared case, AI suggestions, and export files.

## Reuse sources

- Repository: the evaluation platform is the author's team's internal service; the code is not public. This plugin only implements the client.
- Branch: `dashboard-source-data-center-e2e`
- Verified commit: `ebd731c125e5cc79dfff20f815a91e4120aa1e8b`
- Model protocol: `assembly-dashboard-viewer-model/v1`
- The preview reuses the plugin's existing `assembly-scene/v1` viewer, itself sourced from the author's research repo; it does not copy the platform's Next.js app or reimplement the metrics engine.

## Integrated operations

| Operation | Workbench behavior |
|---|---|
| Batches & analyses | List platform analyses; select 1–8 batches by route version, spec tier, or generator to build an analysis |
| Result package | Choose locally or provide a path to a ZIP, check it, then explicitly map the four dimensions to cases before ingesting |
| Case comparison matrix | 25 rows per page, in-page search; missing results, execution status, quality status, and human conclusion are shown separately |
| C0–C4 report card | Raw gate, confidence, pass rate, mean, evaluated/unevaluated/anomaly counts, tag slices, and reasons |
| Model preview | 1–4 CaseRuns, original scale, coordinates, rigid-body joints, version switching / side-by-side; a viewer is created only as needed |
| Human review | Conclusion, issue tags, rationale, original platform review history — saved to the original CaseRun |
| Five-dimension comparison | Per-version semantic, structural, joint, motion, and geometry scores, plus case validity and the recommendation rationale |
| Automated evaluation | Invokes the platform's async analysis job, queried for status in the current workbench |
| Report | Creates a deterministic frozen report, views its contents, saves Markdown and an audit CSV to the current job |
| Library | Reads the case library, frozen test sets, and issue library, currently shown as structured detail |
| AI | `studio_evaluation` reads the same platform evidence, shares the current case, runs checks, previews, and proposes review suggestions |

At this stage, the platform's data-center production, cloud-scale batch generation, issue-ticket editing, Gallery publishing, and Test Set editing, and LLM report generation have not been migrated. The existing single-model `studio_observe` is unchanged.

## Connecting and AI usage

The platform address should be the service root that actually serves `/api/health`; a GitLab branch URL is not a deployment address. You can fill in an address ending in `/api`. If Bearer auth is needed, only fill in the name of an environment variable the service process already has; never write the token into the URL, the project, or task parameters. Redirects do not forward authentication.

```json
{"action":"connect","base_url":"https://your-actual-eval-platform-domain","auth_env":"DASHBOARD_TOKEN"}
{"action":"catalog"}
{"action":"read","resource":"analysis","id":"analysis ID returned by the platform","offset":0,"limit":25}
{"action":"focus","id":"analysis ID returned by the platform","case_run_id":"CaseRun ID returned by the platform"}
{"action":"read","resource":"case"}
```

The above are all example arguments for `studio_evaluation`; the IDs must come from a real query. `read` returns an `sha256`, used for subsequent submissions. Large blocks of analysis and reports are trimmed by default; `detail:true` keeps the full evidence. `preview` returns a workbench task; query the result with `studio_tasks` rather than resubmitting.

The original platform counts every `human_reviews` record toward the HUMAN gate, regardless of the reviewer's name. Because of this, AI's `review` and `compare_review` are only saved as local suggestions; only after a human "fills in the AI suggestion" in the form, checks it, and submits does it get written to the platform. AI does not call `studio_ui_action` to simulate a human. Switching platforms clears old platform suggestions; human drafts and AI suggestions are both bound to the evidence SHA.

`studio_get_state.evaluation_focus` includes the current analysis, CaseRun, pagination position, and operator. When a human selects a case in the matrix, AI can read it; when AI calls `focus`, the UI navigates to that case, and an unsubmitted single-case draft is kept keyed by evidence SHA.

## Data and boundaries

- Requests are not auto-retried, to avoid duplicate writes after a timeout. Re-read the evidence and compare SHAs before writing; the platform itself doesn't yet have an atomic `If-Match`, so a race with another client between the check and the write cannot be guaranteed to be blocked.
- ZIP checking only uploads to the evaluation platform the user selected; checking does not automatically create a batch. Limit: 8 packages, 90 MB total. The original platform is responsible for parsing, validation, and deduplication.
- `UNKNOWN`, `NOT_EVALUATED`, `ERROR`, and missing items are preserved; they are never filled in as zero, recomputed, or used to relax the platform's gates. A successful run is not a quality pass.
- The model preview only accepts a self-contained GLB inside the case; Links with no visual are kept as coordinate-only nodes. Supports fixed/revolute/continuous/prismatic; other motion types are explicitly rejected. The preview follows the platform's viewer_model as ground truth, and does not claim to cover URDF mimic joints, physics simulation, or collision quality.
- CaseRun SHA is checked before and after fetching; if evaluation updates and preview happen concurrently, the older evidence may be rejected — re-preview after the evaluation finishes. Preview G/B marking is disabled; reviews are always saved from the outer form.
- Preview asset total is capped at 90 MB, at most 512 Links per case, and at most 4 cases at once. The matrix only shows one page, and does not create a WebGL context per cell; leaving the page destroys the preview iframe, and idle frames render on demand only.
- Connection, focus, suggestions, and write audits live under `evaluation/` in the current job; exports go to `evaluation/exports/`, returning the actual path, byte size, and SHA.

## 2026-09-22 integration verification

Used the original FastAPI backend at the commit above, an isolated database, and a loopback port. Did not modify the production evaluation platform or the user's existing 3D projects; did not call a generation or paid LLM API.

Test assets came from a real four-drawer cabinet and a single-door nightstand's real GLB and joint declarations, converted into the URDF ZIP the platform ingestion expects. The same model package was placed in two test conditions to verify the UI and interface — **this is not a new WaveAB route experiment, and cannot be used to draw route-quality conclusions**.

Development evidence (intake receipts, analyses, task previews, reports, test logs) is kept in an evidence directory outside this machine; the production deployment address is still to be configured.

Verification results:

- `uv run --frozen pytest -q -m 'not bambu'`: 307 passed, 2 deselected (real Bambu tests not run). Targeted regression after the final preview change: 27 passed.
- `node --test tests/*.mjs`: 61 passed; MCP stdio verified tool discovery, shared focus, that AI suggestions don't write to the HUMAN gate, and App-side human-submission attribution.
- Real backend on the original platform: two packages ingested, two condition matrices, async evaluation COMPLETED, a case pending re-review evaluation and five-dimension UNKNOWN comparison written back, frozen report READY, Markdown/CSV files exported.
- Browser: four-drawer cabinet slide from 0 to 0.386 m, nightstand pose and side-by-side comparison, AI case-selection sync and both kinds of suggestions filled in, UI tested at 380/600/1000 widths. At 600 width, the workspace `clientWidth == scrollWidth == 589`.
- Simulating 4 seconds of continuous zoom in an isolated MCP App host: 78 WebGL draw calls, 4 canvas-size writes, no task over 50 ms; 4 seconds idle: 0 draw calls, 0 canvas writes. This result is not the same as a real measurement of dragging a native Codex window, and cannot be used to claim host stutter is fully resolved.
- Preview and automated evaluation running concurrently triggered a stale CaseRun SHA rejection; it succeeded after regenerating, and the old preview was not left bound to the new evidence.

Main implementation files: `studio/adapters/evaluation.py` (platform adapter and evidence protection), `studio/adapters/platform_preview.py` (original model preview), `studio/shell/evaluation_schema.py` (AI tools), `studio/web/evaluation.js` / `.css` (native workspace), `studio/web/evaluation-metrics.js` (fidelity display).
