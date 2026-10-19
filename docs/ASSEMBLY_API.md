> 中文：[zh-CN/ASSEMBLY_API.md](zh-CN/ASSEMBLY_API.md)

# Optional Assembly Workflow Service and Local Modeling

By default the workbench uses GPT-written scripts in the current Codex session to drive local Blender / CadQuery/OCP, delivering models, project files, images, and inspection reports. It does not require purchasing a generation API, but it still consumes the user's current GPT quota and local compute. Explicit operations can also directly pick templates, parameters, and selections.

Assembly is an optional remote processing service. The adapter implements a configurable workflow protocol for assembly, rigging and motion. It processes existing GLBs or generates motion; it is not a text/image-to-geometry interface.

| operation | service template | delivers |
|---|---|---|
| assemble | workflow_assembly_prod | animatable assembled asset package |
| segment | workflow_assembly_seg_prod | split-part GLB / face labels |
| rig-glb | workflow_rig_glb_prod | rigged GLB |
| rig | workflow_rig_prod | rig and motion asset package |
| motion | workflow_motion_generate_prod | motion ZIP / BVH; does not auto-bind to a model |

## Configuration

Disabled by default. The config file lives outside the repo at `~/.config/codex-3d/services.json`, or point `WORKBENCH_SERVICE_CONFIG` at another file. Only fill in the deployment address and environment variable references:

```json
{
  "assembly": {
    "enabled": true,
    "base_url": "https://api-beta.aholo3d.cn",
    "workflow_path": "/cubely/v1/workflow",
    "key_env": null,
    "headers_env": {}
  }
}
```

This example is not a complete authentication configuration. OpenAPI authentication should be configured per the actual deployment's specification, and cannot be derived from how the web login works. If the deployment requires an Authorization header, you can set `"headers_env":{"Authorization":"ASSEMBLY_AUTHORIZATION"}`; the corresponding environment variable is the full header value. If you're definitely using a Bearer API key, you can instead configure `key_env`, and the adapter will prepend `Bearer `. Don't configure two sources for the same header at once.


The optional `oneapi_appkey_env` references the OneAPI appkey used by the backend assembly inference (for example, a user-configured `ONEAPI_API_KEY`); it is only injected as `oneapiAppKey` at send time, and never enters the task parameters or the receipt. This appkey is not the same as the Assembly interface's login credential. `model` can override the assembly main-chain model depending on deployment permissions; it does not override every branch. Do not put a plaintext appkey in `params`.

The environment variable needs to reach the actual plugin backend process; restart/reconnect the backend after configuring it. The UI showing "configured" only means it's enabled and the reference exists — it does not mean the network, authentication, balance, or service quality have been verified.

### Connection diagnostics

Use the endpoint and authentication scheme supplied by your service operator. Run
`uv run python scripts/diagnose_assembly.py` for a read-only diagnostic against the
configured service. Its default request sends no credentials and submits no task;
`--with-auth` explicitly uses the configured credential reference. Reachability,
authentication and generation are reported separately. A successful connectivity
check does not establish billing, service quality or a completed generation.

No private deployment address, session identifier or internal network diagnostic
record is distributed with this preview. Legacy transport settings require an
explicitly configured destination and do not activate after an HTTPS failure.

## Invocation and receiving

After reading `studio_capabilities`, call:

```json
{
  "action": "start",
  "provider": "assembly",
  "operation": "segment",
  "params": {
    "meshUrl": "https://your-storage.example/model.glb",
    "meshUpAxis": "y_up"
  }
}
```

The input must be a link the service can access, and must preserve the GLB's actual up axis. It currently does not upload local files or selections on the user's machine; such inputs are explicitly rejected. The input link is retained in the local task parameters. Segmentation can configure `cutBackend:"cube"` and 1–8 `cubeParts`; a full assembly needs `prompt`. Advanced parameters support the documented `from` for already-split inputs. Motion needs `prompt`, and `inputUrl` refers to JSON, not a GLB.

1. A creation request is only submitted once, and the `promptId` is persisted immediately. If it's unclear whether it was accepted, it is not auto-resubmitted.
2. The first wait is 30 seconds, then it polls every 10 seconds, up to 70 times; status is parsed from the outer `c` field, and a non-existent `d.status` is never read.
3. `10001` means waiting; `10002` is a short retry, and after three in a row the ID is kept; `-1` or an unknown status ends this round of waiting. After a network/download failure or timeout, you can continue receiving with `resume` using the same ID.
4. Stopping the wait only stops the local process — it does not cancel the remote computation or billing. When the service doesn't report a cost, it's recorded as null, and is never marked as free.
5. Download URLs never enter the receipt/run log; downloads do not carry an API auth header. The original ZIP is kept; after size-limiting, geometry and data files are extracted, and out-of-bounds paths, symlinks, conflicts, and encrypted entries are rejected, excluding scripts/HTML.
6. `glbUrl` may also point to a ZIP — it must not be renamed to pretend it's a GLB. A static GLB can be previewed and brought back into editing; a rigged/animated GLB stays in the task preview or Blender. BVH is motion data; this round does not implement automatic matching to an unknown character rig.

## Verification and boundaries (2026-09-22)

- Added 29 Assembly tests, which together with the existing service tests bring the total to 33 passing. Verified the five templates, status polling, failure recovery, single submission, artifact unpacking, and credential isolation using real local HTTP plus an independent task subprocess. A simulated service does not prove the real backend model's quality.
- Full suite: 339 Python tests passed, 2 real Bambu tests excluded; 62 Node tests passed; `npm run build:app` passed.
- Mixed materials, URDF rendering, SVInput, and Lux3D text/image-to-model were not counted as integrated; they each need their own contract and real verification. This round also did not implement API plan sales, top-ups, or a billing system.

An example that reproduces without depending on a generation API:

```bash
uv run --frozen python scripts/verify_local_first.py --out /absolute/new/directory
```

It runs a GPT-written CadQuery script that makes an 80×40×50 mm, 4 mm wall-thickness L-bracket with two 6 mm-diameter holes; it reads the STEP back to verify volume, checks the STL's dimensions, watertightness, and hole topology, then renders it via Blender, saves the project and a GLB, and finally imports it into an isolated editing project. It does not call a generation service or change the user's current project. Local timings: CAD 4.33 seconds, Blender rendering and delivery 1.79 seconds, and re-importing into editing succeeded; this excludes GPT thinking time and tool round-trip time.
