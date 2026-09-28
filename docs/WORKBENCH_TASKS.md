> 中文：[zh-CN/WORKBENCH_TASKS.md](zh-CN/WORKBENCH_TASKS.md)

# 2026-09-22: Modeling, Service, and Artifact Workspaces

This round extends the plugin from static editing/printing into three workspaces: model editing, modeling & tasks, and print preparation.
Compatible plugin ID `print-prep`, display name "3D 工作台" ("3D Workbench"). It still expands by default as an MCP App in the Codex right-hand panel.

## Capabilities wired up so far

- 33 local task templates, plus the ability to run AI-written, trusted Blender/Python scripts. Blender handles engineering, meshes, UVs, baking, rigging, and animation; CadQuery/OCP handles precise solids and STEP; Trimesh/Manifold handles part splitting, cross-sections, and solid checks.
- Parametric containers, hinges, CAD shells/extrusions/revolves, and the pin-hinge and thin-rotary test coupons from the author's research repo; provenance is recorded in `studio/core/kernels/SOURCES.json`.
- Smoothing/decimation/solidification/voxel remeshing/UV unwrapping, high-to-low-poly albedo and normal baking, fixed-topology surface fitting, locally bounded Taubin smoothing, and explicitly guided hair-card generation.
- Face-label splitting that preserves the original faces and UVs; the editor adds click-to-place spherical region picking plus splitting, and results are not auto-capped.
- Automatic weighting from an explicit skeleton, weight normalization with an influence-count limit, action retargeting via explicit bone-name mapping, animation merging and preview, scene staging, and offline rendering.
- Grayscale-image closed embossing, millimeter SVG layering, and solid interference checks for static and explicitly sampled motion; `assembly-audit` also has a URDF mode that sweeps every actuated, non-mimic joint from a single URDF's own limits (or a `joint_ranges` override) simultaneously and linearly along the diagonal of joint-configuration space — one straight line, not every combination, so a collision that only happens at a mixed configuration is not covered. Mimic joints still move (resolved from their master by `yourdfpy`, not by this sweep), links joined only by `fixed` joints are merged into one solid per rigid group before testing, and overlaps are checked per group in millimetres. `removal-audit` runs the same discrete removal/assembly-order sampling the head-shell task uses, on any set of watertight STL parts.
- Offline interactive HTML: embeds the raw GLB, animation, orbit/walkthrough, and clickable hotspots; does not include a physics engine or general game logic.
- The right-hand panel can view GLB/animation, renders, JSON reports, and a sandboxed interactive web page; static results can be pulled back for continued editing, a Blender/STEP project can be opened, and files can be saved. Animations are never force-downgraded into a static editing project.
- MCP and HTTP share a chunked-upload path (a single directory, contiguous offsets, retransmission verification); files can be picked by the user instead of every path being typed in.

## Task contract

`studio_capabilities` returns the actual templates, execution environment, and service-configuration status; `studio_task` returns an ID immediately after starting; `studio_tasks` queries status, tail logs, and artifacts.
A task lives at `<job>/tasks/<id>` and holds the request, a script digest, input SHA256s, a run record, status, and artifact SHA256s.
A standalone worker can resume execution across HTTP restarts, up to two jobs at once; timeouts and cancellation kill the job's own process group rather than a PID that might have been reused.

Scripts use `workbench = {inputs, params, output}`. Blender units are meters, Z-up; it auto-saves the `.blend`, the animation `.glb`, and an optional render; other outputs are written to `output`.
`completed` means the process succeeded and produced an artifact — it does not mean aesthetics, identity, manufacturability, or motion naturalness have been accepted. The report still has to be read and the actual model still has to be checked.
Scripts run with the same privileges as the user's shell; this is a trusted code-execution entry point, not a sandbox for running untrusted code in isolation.
Static editing operations and artifact imports both keep project-version checks; a failure never overwrites the current geometry.

## Bring-your-own APIs

Meshy and Tripo are built in, referencing `MESHY_API_KEY` / `TRIPO_API_KEY` respectively. Keys are only read from the service process's environment; they are never written into task parameters, artifacts, or the frontend.
No real accounts were configured this round, so only the contract/recovery/credential-isolation behavior of an actual HTTP mock service was verified — this is not a claim that cloud-generation quality has passed.
Setting `WORKBENCH_SERVICE_CONFIG` or `~/.config/codex-3d/services.json` can wire up other asynchronous services with a known contract:

```json
{
  "my-service": {
    "title": "My model service",
    "adapter": "generic",
    "base_url": "https://api.example.com",
    "key_env": "MY_3D_API_KEY",
    "operations": {
      "generate": {
        "submit": "/jobs",
        "poll": "/jobs/{id}",
        "id_path": "id",
        "status_path": "status",
        "success": ["completed"],
        "failure": ["failed"],
        "artifacts_path": "artifacts"
      }
    }
  }
}
```

See `studio/adapters/services.py` for the exact fields; download entries are confirmed file URLs. `$file` is converted to a data URI locally, following a service's documented contract — it never guesses at a private API.
Intent is persisted before submission, and only one POST is ever attempted. If a remote ID already exists, `resume` can keep polling/collecting it; when it's unknown whether a submission succeeded, the uncertain state is kept rather than auto-resubmitting.
A completed hosted-service task's `output/service.json` records `provider`, `operation`, `adapter`, `model` (the request's model/version selection when the adapter exposes one — e.g. Hunyuan's `model`, Lux3D's `version`, Assembly's `workflowTemplateId` — or a fixed single model, such as Seed3D's, when there is only one), `remote_id`, `status`, `cost`/`cost_unit`, `request_params` (the submitted payload, sanitized before being written: any key whose name contains key/token/secret/authorization is removed entirely, any string value that looks like a URL has its query string and fragment stripped, and any `$file` marker is reduced to just the referenced file's name — credentials cannot reach it in the first place, since `validate_payload` already rejects them), `input_sha256` (name + SHA256 for every local input file), and `submitted_at`/`received_at`. It never contains `base_url`, a signed download URL, or the raw provider response. This applies uniformly across the generic REST-job adapter and every dedicated vendor adapter (Lux3D, Assembly, Hunyuan, Seed3D). The same `cost`/`cost_unit`/`model`/`adapter`/`submitted_at`/`polled_at`/`received_at` fields are also echoed live in `studio_tasks`' `service` object while the task is still running.
"Stop waiting" only cancels local polling — it does not mean the provider stops computing or stops billing. A service being configured also does not mean that service is live and healthy right now.
Meshy's public docs for reference: [text-to-3D](https://docs.meshy.ai/en/api/text-to-3d), [rigging](https://docs.meshy.ai/en/api/rigging), [animation](https://docs.meshy.ai/en/api/animation).

## Precision and performance

Edited assets keep a float64 authoritative geometry alongside the standard float32 GLB display data, used for reopening the engineering file and further processing; ASCII STL is used when a float32 STL would merge distinct vertices.
GLB export to external software is still bound by the format's float32 precision — display precision is never described as manufacturing precision.
3MF vertices are written with 17 significant digits; reading a Bambu project back compares the vertex, face, and topology fingerprints of source and result. On damage, delivering that project is refused and the original geometry's 3MF is kept — this does not repair Bambu's own serialization.

Static views render on demand and stop rendering when hidden; draw calls are coalesced and capped at 30 Hz while resizing/zooming, using a temporary 1x pixel ratio and restoring full sharpness after 150 ms of stability.
Wide side panels scroll the form and results independently; narrow side panels prioritize showing results. Animations run only while playing; hidden interactive web pages have their iframe unmounted so they don't keep playing in the background.
CadQuery's first cold load measured about 237 seconds locally, and about 2.3 seconds afterward; a warm-start time should not be mistaken for first-use time.

## Acceptance, and what's not yet covered

Evidence: [historical validation record](history/VALIDATION_20260922.md). This round is not a claim of full capability parity with any specific third-party product.
Automatic facial keypoints, nose-donor blend seams, identity-preserving automatic head-model fitting, complete general motion grounding/naturalness evaluation, and case-by-case finished-product acceptance for 41 specific product workflows are still not done.
General-purpose Blender execution, template surface fitting, and hair-card generation each provide a low-level entry point respectively — they are not claimed as equivalent to the specialized pipelines above already having passed.
Validating with a real cloud account needs an available API environment; the fixed-topology portrait pipeline needs a target template of known provenance plus a keypoint contract. The five formerly missing routes now bind to local `connect-parts`, `color-inlays`, `install-joint` and `motion-check` tasks. See the [public capability contract](PUBLIC_CAPABILITIES.md) for inputs and acceptance. Ready means tool binding, not automatic execution or arbitrary-model/physical acceptance. `image-to-print` remains a hosted extension outside the local promise.
No private code from any third-party product was reused, no external service was deployed, no website was published, and no job was ever sent to a real printer.
