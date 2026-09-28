> 中文：[zh-CN/HUNYUAN_API.md](zh-CN/HUNYUAN_API.md)

# Hunyuan 3D / Part

2026-09-23: ran another real generate → Part → edit → export → unified-preview pass through the company OneAPI, and fixed a bug where material editing lost vertex normals — see [0.8.1 validation record](history/VALIDATION_20260923_ONEAPI_HUNYUAN.md). This chain does not substitute for acceptance against a dedicated Lux3D account interface.

Codex is the existing inference and tool-calling entry point. The workbench only dispatches specialized tasks to Hunyuan 3D / Part; it does not add a GPT API, a chat-model account, or another viewer. The local Blender/CAD route can still be used independently.

## Interface and reuse

Adapts the `hunyuan-responses` protocol: POST `/responses` with `background:true`, then GET `/responses/{id}`; only accepts a model from `3d_generation_call`.
The contract comes from the company's internal batch part-splitting validation and interface-parameter documentation, and is consistent with the Hunyuan model already verified in the author's research repo.

This is the company's Responses-compatible 3D service interface, **not the native Tencent Cloud TC3 interface**. Other deployments must be compatible with this contract; you cannot just swap the base_url for a Tencent Cloud domain.

Reuses existing HTTP auth/redirect limits, task lifecycle, ZIP-safe intake, and the shared viewer. Does not introduce aigccat's OpenCode, LLM routing, or renderer, and does not copy its source.

## Configuration

Set the environment variable `HUNYUAN_API_KEY` outside the repo, so the process that launches the workbench inherits it. You can also point to an existing environment variable name in `~/.config/codex-3d/services.json`:

```json
{
  "hunyuan": {
    "base_url": "<your-openai-compatible-gateway>/v1",
    "key_env": "HUNYUAN_API_KEY"
  }
}
```

The configuration only stores a reference, not the secret itself. Do not copy the key file into the repo. This adapter ships with no default `base_url` at all — it describes a protocol (a Responses-compatible 3D generation interface), not one specific service; `base_url` must point at a gateway you yourself have access to, and you must not take the address or key from some document or example and use it as a shared default.

An upgrade install clears the old plugin cache. If the backend service is still coming from the old cache, restart it after confirming there's no active task; otherwise the old service may try to start a worker from a deleted directory. Upgrade verification should check the server, MCP, and frontend versions together, not just refresh the UI.

## Operations shared by humans and AI

Under "Modeling & Tasks" on the right, select **Hunyuan 3D / Part**. For image generation, pick one PNG/JPG/WebP (≤4 MB); for text generation, fill in a description. When you plan to continue on to splitting, choose FBX as the output format.

```json
{"action":"start","provider":"hunyuan","operation":"text-to-3d","params":{"prompt":"A simple wooden chair with four legs and a slatted backrest.","model":"hunyuan-3d-3.1-pro","output_format":"FBX","face_count":3000}}
```

For image-to-model, use `image-to-3d`, with the image's absolute path in `inputs`; you can also use `params.image_url` — pick one or the other. It will not pass off the current GLB selection as an image.

Once the generation task finishes, pick it from the dropdown in the Part UI; AI can also reference the task ID directly:

```json
{"action":"start","provider":"hunyuan","operation":"segment","params":{"source_task":"32-character ID of a completed generation task"}}
```

For an existing remote FBX, use `file_url` in place of `source_task` — do not treat a local file path as a URL. It currently does not auto-upload a local FBX. Once the server-side download link expires, you may need to provide the source again; it will not auto-rerun generation just to renew the link.

Each submission sends exactly one POST; once the remote ID comes back it's persisted immediately. After an interruption, `resume` queries and collects using the original ID, without regenerating. Stopping the wait does not guarantee stopping remote billing. A submission whose outcome is ambiguous, with no ID obtained, is never auto-retried.

Multiple Part GLBs are kept as-is and combined into `combined.glb` using each node's world transform; you can rotate it in the task area or import it into editing. The key never enters the task file or a download request; signed links only live in a task-private cache with permissions 0600, and never enter the output package.

## Acceptance boundaries

`completed` means the task ran and files landed on disk successfully — it does not mean the split quality passed. Part is generative splitting, and may change the original geometry, texture, scale, or part count; it should be judged through observation, geometry metrics, and comparison against the original model. Whether the company plan is billed follows the service's actual invoice; you cannot infer it's permanently free from an old experiment's "$0."

Protocol test coverage: real local HTTP, single submission, continuing to collect by ID, referencing a source task, image requests, model allowlist, ZIP packaging, path-traversal rejection, and credential/artifact isolation.

## 2026-09-22 real company-interface acceptance

All three tasks used the `/v1/responses` endpoint of our own OpenAI-compatible gateway, each submitted once, with credentials referenced from an existing out-of-repo configuration. Did not call the GPT API. The timing includes polling and collection time, not pure model inference time.

| Operation | Model | Time | Actual artifact |
| --- | --- | ---: | --- |
| Text-to-wooden-chair | hunyuan-3d-3.1-pro | 187.1 s | OBJ + GLB + FBX; 3,000 faces |
| FBX split | hunyuan-3d-1.5-part | 71.9 s | 5 GLBs + combined.glb; 1,340,205 faces |
| Reference-image generation | hunyuan-3d-rapid | 85.1 s | GLB; 50,000 faces |

The reference image is a local-Blender render of the wooden chair generated in this same run. All three artifacts had their geometry re-read and were actually observed through the workbench render. The split result was compared against the generated original at the same scale from front, oblique, and top views; the shape and placement are close, but the part grouping doesn't necessarily match assembly semantics — 27 boundary edges were detected, and the conclusion is kept as `needs_review`. Note in particular that the Part face count went from 3,000 up to about 1.34 million; this cannot be called a topology-preserving split of the original mesh.

The gateway's `actual_amount` values were 1.68, 0, and 0.72 respectively; these are only the receipt values as recorded here — no currency or long-term pricing is inferred from them.

Verification: `uv run --frozen pytest -q -m 'not bambu'`: 372 passed, 2 deselected; `node --test tests/*.mjs`: 62 passed. The app build succeeded; an isolated browser test exercised all three forms, the source-task dropdown, and input-type switching, with no pageerror. The real test case's task IDs, SHAs, and screenshots are kept in the local `workbench-hunyuan-20260922` evidence directory; private signed download links or keys are not committed to Git.
