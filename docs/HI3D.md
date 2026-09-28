[简体中文](HI3D.zh-CN.md) · [API demo](API_GENERATION_DEMO.md)

# Optional Hi3D API

Local modeling/editing still needs no generation service. This adapter adds an
optional, paid **single-image → GLB** operation using Hi3D's public API. It does
not bundle a model or an account. Hi3D API credits and host-agent access are separate.

## Configure locally

Provide both `HI3D_ACCESS_KEY` and `HI3D_SECRET_KEY` in the environment of the process
that starts the MCP server. Use your host's secret/environment configuration, or a
private launcher that sources a file outside the repository. Never paste values
into a chat, task params, README or committed MCP configuration.

The built-in endpoint is `https://api.hitem3d.ai`. No config file is needed when
using the default variable names. Advanced overrides in your private
`~/.config/codex-3d/services.json` contain **names**, not values:

```json
{
  "hi3d": {
    "key_env": "HI3D_ACCESS_KEY",
    "secret_key_env": "HI3D_SECRET_KEY"
  }
}
```

Restart the MCP server and any workbench backend it previously started, after
active tasks finish. The current single-key connection dialog does not accept an
AK/SK pair: configure these two environment variables instead. Hi3D then appears
under **Modeling & Tasks**. Do not put the pair into the generic API-key box.

## Human and agent workflow

1. `studio_capabilities`: check that `hi3d.configured` is true.
2. `studio_services` with `{"action":"probe","id":"hi3d"}`: performs token
   authentication and a balance query, without generating. `positive_balance:false`
   means add API credits before the demo; a positive balance is not a price quote.
3. In **Modeling & Tasks**, select Hi3D, choose **Image to 3D**, and provide one
   PNG/JPEG/WebP up to 20 MB. Or ask the agent to call `studio_task`:

```json
{
  "action": "start",
  "workspace_id": "CURRENT_WORKSPACE_ID",
  "provider": "hi3d",
  "operation": "image-to-3d",
  "inputs": ["/absolute/reference.png"],
  "params": {
    "model": "hitem3dv2.1",
    "resolution": "1536fast",
    "request_type": 3,
    "face": 100000,
    "format": 2,
    "pbr": 1,
    "rmbg": 1,
    "shading": 0.5
  }
}
```

4. Save the returned local task ID. Poll `studio_tasks` with that ID; do not repeat
   `start`. Open **Recent results → View result**, then **Import into editing**.
5. Check shape, topology, materials and scale before further edits. A generated
   mesh does not promise separate semantic parts or correct physical dimensions.

This version exposes geometry (`request_type:1`) or geometry plus texture (`3`),
GLB only (`format:2`), and 100,000–2,000,000 requested faces. Supported model and
resolution pairs are listed below; they are API options, not a claim that every
combination has been tested against a live account.

| Model | Resolution |
| --- | --- |
| `hitem3dv1.5` | `512`, `1024`, `1536`, `1536pro` |
| `hitem3dv2.0` | `1536`, `1536pro` |
| `hitem3dv2.1` | `1536fast`, `1536pro` |
| `hi3dv3.0` | `2048quality`, `2048master` |

The adapter omits PBR/de-shading fields for v1.5. Multiview, retexturing, relief,
segmentation and multicolor APIs are not exposed by this adapter yet.

## Recovery and evidence

The generation POST is attempted once. Its task ID is persisted before polling;
`studio_task` with `action:"resume"` refreshes authentication and queries the same
remote task, then downloads again if needed. An ambiguous submission without an ID
is never automatically resubmitted. Cancel stops local waiting; it does not cancel
provider billing. Token expiry can be recovered with `resume` when the ID is known.

AK/SK and access tokens stay out of task files. CDN requests carry no service key.
`service.json` contains parameters, input hashes, timestamps and task identity, not
tokens or signed download links. The query contract has no per-task cost field;
the adapter reports `cost:null` rather than inferring a charge from account balance.

Live validation on 2026-09-28 reached successful authentication and balance queries,
but the tested API accounts had no available credits. **No live Hi3D generation is
claimed.** Local HTTP integration tests exercise multipart upload, GLB delivery,
MCP import/edit/export, failure handling and no-resubmission recovery. The published
[real generation demo](API_GENERATION_DEMO.md) uses Hunyuan through an authorized
Responses-compatible gateway instead.

Public protocol sources: [authentication](https://docs.hi3d.ai/en/api/api-reference/list/get-token),
[submission](https://docs.hi3d.ai/en/api/api-reference/list/create-task),
[query](https://docs.hi3d.ai/en/api/api-reference/list/query-task),
[balance](https://docs.hi3d.ai/zh/api/api-reference/list/query-balance).
This is an independent public-API implementation; no Hi3D desktop source is included.
