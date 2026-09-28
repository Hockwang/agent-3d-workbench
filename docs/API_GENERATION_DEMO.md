[简体中文](API_GENERATION_DEMO.zh-CN.md) · [README](../README.md)

# Optional generation API → local editing

This tutorial adds an optional image-to-3D route to the no-key local tutorial.
The agent sends an image to a configured 3D service, receives a real GLB, and uses
the same workbench to inspect and edit it. Local editing remains available without
any generation-service account.

The reference below is an original, procedural five-part mug rendered in Blender.
It is **input**, not the output of a generation API. Only this PNG is uploaded;
the generator does not receive the source geometry or part names.

![Input: procedural mug render](assets/api-generation/reference.png)

## 1. Choose a service

| Route | Setup | This demo's verification |
| --- | --- | --- |
| Hunyuan | A gateway implementing the workbench's `hunyuan-responses` 3D protocol and your own API key | Real run through an authorized gateway; see the evidence below |
| Hi3D | Official API with your own Access Key and Secret Key | Authentication/balance checked; live generation not run because API credit was unavailable |

“DiT generation API” describes the optional route at the product level. The
workbench neither ships the service's model nor verifies its underlying model
architecture. It sends a specialized 3D request, not a request to another chat LLM.

For Hunyuan, open **Modeling & Tasks → Manage 3D Services**, select **Hunyuan 3D / Part**,
enter your gateway URL and key locally, save and test the connection. Use only a
gateway you are authorized to access. This example is **not a publicly available
free endpoint**, and the adapter is not Tencent Cloud's native TC3 API. Ordinary
OpenAI-compatible text gateways do not necessarily implement 3D generation.

For an environment-based setup, inject `HUNYUAN_API_KEY` into the MCP process and
keep this configuration outside Git, in `~/.config/codex-3d/services.json`:

```json
{
  "hunyuan": {
    "base_url": "https://YOUR_GATEWAY.example/v1",
    "key_env": "HUNYUAN_API_KEY"
  }
}
```

Replace the URL with your own compatible gateway. `key_env` is a variable name,
not a key value. Restart the MCP server and its existing local backend after any
active tasks finish so they receive the new environment. For Hi3D use the
[AK/SK setup guide](HI3D.md); its current setup uses two environment variables.

## 2. Generate once

In **Modeling & Tasks**, select Hunyuan, choose **Image to 3D**, open the reference
PNG and select `hunyuan-3d-3.1-pro`, GLB, 60,000 requested faces and PBR enabled.
Start the task once. Generation can incur provider charges.

Or give your agent this instruction:

> Use my configured Hunyuan 3D service to generate one model from the reference
> image. Check the connection and available models first. Request a GLB with PBR
> and 60,000 faces, submit once and retain the returned task ID. After completion,
> show the result, inspect it, import it into this project's editor, demonstrate a
> 0.5× scale and undo, then save and export. Do not resubmit on a timeout, and do
> not claim that the generated object is already separated or print-ready.

The corresponding `studio_task` call, after `studio_capabilities` and
`studio_services {"action":"probe","id":"hunyuan"}`:

```json
{
  "action": "start",
  "workspace_id": "CURRENT_WORKSPACE_ID",
  "provider": "hunyuan",
  "operation": "image-to-3d",
  "title": "Hunyuan mug demo",
  "inputs": ["/absolute/reference.png"],
  "params": {
    "model": "hunyuan-3d-3.1-pro",
    "output_format": "GLB",
    "face_count": 60000,
    "pbr": true
  }
}
```

Use the actual workspace and file path. Poll `studio_tasks` with the **returned
local task ID**, not a made-up ID or the provider's remote ID. `completed` means
the files arrived, not that their appearance or manufacturability passed.

## 3. Find, inspect and edit the result

1. **Recent results → View result** opens the generated model. **Output files**
   provides downloads and disk locations.
2. **Import into editing** appends the model to the scene. It does not replace the
   old object automatically. Use **Current model** to return to the editing view.
3. Inspect the object's dimensions, topology and materials. A one-image result has
   unobserved surfaces; five source parts do not imply five generated parts.
4. Ask the agent to apply a reversible scale, undo it, save a `.3dworkbench` project
   and export a GLB. Use current object IDs and `expected_revision` each time.
5. For appearance review, use `studio_observe` or render the downloaded GLB. Read
   the actual image before judging; successful API execution alone is insufficient.

The scripted replay below creates a separate workspace, checks the delivered file
hash, imports it through MCP, scales it by 0.5, verifies dimensions, undoes the edit,
checks restored dimensions, saves a project, exports and rechecks the GLB bounds.
It does not click native UI buttons or test physical printing.

```bash
# Requires credentials in this process's environment and a private gateway config.
uv run python examples/api_generation/run_demo.py --provider hunyuan --probe \
  --service-config "$HOME/.config/codex-3d/services.json" --out /absolute/api-demo

# Paid generation; run once. Use a new output directory for each intentional new job.
uv run python examples/api_generation/run_demo.py --provider hunyuan --generate \
  --service-config "$HOME/.config/codex-3d/services.json" \
  --image docs/assets/api-generation/reference.png --out /absolute/api-demo

# Continue the same job after interruption; never sends another generation POST.
uv run python examples/api_generation/run_demo.py --provider hunyuan --resume \
  --service-config "$HOME/.config/codex-3d/services.json" --out /absolute/api-demo
```

The runner also accepts `--provider hi3d`; default API parameters follow the
[Hi3D guide](HI3D.md). It refuses a new generation when the output directory already
contains task state. If a crash occurred before the local checkpoint was written,
inspect that directory's task state; do not use a different output directory to
automatically retry. If interrupted after importing, review the existing scene
before continuing, so the script does not duplicate the model.

## Evidence from this run

The downloadable result, measured checks and appearance review are recorded in
[the run report](API_GENERATION_RESULTS_20260928.md). The reference and rendering
script are public; account credentials, gateway configuration, signed download
URLs and raw provider responses are not included.

To recreate the reference (Blender is only needed for rendering):

```bash
uv run python examples/demo/make_demo_parts.py --out /absolute/mug-source
blender -b --python examples/api_generation/render_model.py -- \
  /absolute/mug-source/demo-parts.glb /absolute/reference.png --reference
```

See [Hunyuan protocol and limitations](HUNYUAN_API.md) for details. Connection tests
do not create models. Resume retrieves the original task; cancel stops local
waiting without guaranteeing cancellation of remote billing. Unknown cost remains
unknown. Precise dimensions, watertight solids and printable parts require their
own checks and, where relevant, physical validation.
