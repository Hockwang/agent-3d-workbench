> 中文：[zh-CN/ASSEMBLY_API.md](zh-CN/ASSEMBLY_API.md)

# Optional Assembly Workflow Service and Local Modeling

By default the workbench uses GPT-written scripts in the current Codex session to drive local Blender / CadQuery/OCP, delivering models, project files, images, and inspection reports. It does not require purchasing a generation API, but it still consumes the user's current GPT quota and local compute. Explicit operations can also directly pick templates, parameters, and selections.

Assembly is an optional remote processing service. This round was implemented from the company's internal API documentation (API flow, web joint animation, web skeletal motion). It processes existing GLBs or generates motion; it is not a text/image-to-geometry interface.

| operation | service template | receiving nodeName | delivers |
|---|---|---|---|
| assemble | workflow_assembly_prod | assembly_agent_cos_upload | animatable assembled asset package |
| segment | workflow_assembly_seg_prod | AssemblyAgentSegmentedGLBExport | split-part GLB / face labels |
| rig-glb | workflow_rig_glb_prod | AssemblyAgentRiggedGLBOutput | rigged GLB |
| rig | workflow_rig_prod | rig_package_zip | rig and motion asset package |
| motion | workflow_motion_generate_prod | AssemblyAgentKimodoMotionGenerate | motion ZIP / BVH; does not auto-bind to a model |

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

The web test entry point is `https://beta.aholo3d.cn`, path `/cubely/v1/api/workflow`, and requires a company login session; its credentials must also be supplied only via a configured environment variable reference. Do not fill in, guess, or spoof `x-qh-id` — the request body does not accept a user ID.

The optional `oneapi_appkey_env` references the OneAPI appkey used by the backend assembly inference (for example, a user-configured `ONEAPI_API_KEY`); it is only injected as `oneapiAppKey` at send time, and never enters the task parameters or the receipt. This appkey is not the same as the Assembly interface's login credential. `model` can override the assembly main-chain model depending on deployment permissions; it does not override every branch. Do not put a plaintext appkey in `params`.

The environment variable needs to reach the actual plugin backend process; restart/reconnect the backend after configuring it. The UI showing "configured" only means it's enabled and the reference exists — it does not mean the network, authentication, balance, or service quality have been verified.

### prod-test internal-network route (Option 0, added 2026-09-22)

Claude session `bfc7ec9a-9cf8-41b0-b2c8-0dde1058ed5e` provided an entry point that doesn't require modifying system networking. This round independently re-verified it:

- Connecting to `<your-assembly-endpoint>`, setting `Host: api-beta.aholo3d.cn` for that request only and not using an HTTP proxy, `/cubely/v1/workflow/history` returns HTTP 200, `c=-1`, `appKey missing`.
- The same entry point without setting Host returns HTTP 401. Connecting over HTTPS through this entry point, even while keeping the original domain's SNI, gets a `Kubernetes Ingress Controller Fake Certificate` — not a valid api-beta certificate.
- `/assets` returned HTTP 404 in this prod-test round; the diagnostic uses the already-deployed `/history` and a random, non-existent promptId — it does not submit a task or read existing assets.
- The install-cached smoke test once got an HTTP 502; source, curl, and the installed-version re-checks afterward all returned to `appKey missing`. The entry point being reachable does not mean the upstream service is stable; a 502 is not treated as authentication or generation passing.

"Zero cost" here means not modifying `/etc/resolver`, the proxy, the shell, or the VPN configuration — **it does not mean free generation or encrypted transport**. The default address, TLS verification, and other service behavior are all preserved. Credential-free re-check:

```bash
uv run --frozen python scripts/diagnose_assembly.py --internal-prodtest
```

Even if credentials already exist in the environment, they are not read to send a request by default. The output separately labels network, authentication, and generation status; HTTP 200 is not treated as a successful generation. This command does not write configuration or change the workspace.

When you actually need to run the internal-network service, add the following to Assembly in the out-of-repo `services.json`:

```json
{
  "assembly": {
    "enabled": true,
    "base_url": "https://api-beta.aholo3d.cn",
    "transport": "assembly-prodtest-http",
    "internal_origin": "http://<your-internal-ingress>",
    "allow_insecure_http": true,
    "key_env": null,
    "headers_env": {"Authorization": "ASSEMBLY_AUTHORIZATION"}
  }
}
```

`internal_origin` is the address this internal-network route actually connects to (it replaces `base_url` but keeps its `Host` header, see the previous section); it must be a bare HTTP(S) scheme + host with no credentials, path, or query parameters, and only takes effect under `transport: "assembly-prodtest-http"` — if unset, the request is rejected outright before sending. `ASSEMBLY_AUTHORIZATION` needs to be the full header value of a gateway credential this test environment actually accepts; the reference name above does not mean the credential exists or is usable. `allow_insecure_http=true` explicitly permits sending credentials and task parameters as HTTP plaintext on the internal network. Without this setting, only credential-free read-only diagnostics are allowed, and task creation is rejected up front. This option only applies to the fixed Assembly prod-test OpenAPI domain, the internal target `internal_origin` points to, and three documented paths — it cannot override the Host for an arbitrary domain, open up HTTP generally, or affect download requests.

Once configured, you can use `--with-auth` for a read-only check; success there only means `history` reached the business layer — it does not mean generation, balance, or quality passed. API redirects are still rejected, and the HTTP entry point does not auto-enable after an HTTPS failure.

Authentication basis: the Aholo OpenAPI developer guide (pointing to an independent gateway and test-permission flow) and the test OpenAPI documentation (describing test accounts, appkey/appsecret, and the signing method). The Aholo token mode and the company's old signing mode cannot be inferred purely from `appKey missing`; the current adapter supports a full Authorization header, but has not yet implemented the old appkey/appsecret dynamic signing. Do not fill in a OneAPI inference key here, and do not simulate a user identity. This round of checking found no service config file or Aholo gateway environment variables configured, and no old token was recovered from historical transcripts.

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
- The two test domains initially specified in the CF ticket both hit a TLS EOF in local Python/curl; browser access to the web test site reported `ERR_CONNECTION_CLOSED`. Afterward, Option 0 above received a real gateway authentication response, correcting the earlier "no reachable entry point" conclusion. A real billed task still hasn't been submitted, so true end-to-end still hasn't passed; TLS verification was not disabled, no identity was simulated, and system network settings were not changed.
- Mixed materials, URDF rendering, SVInput, and Lux3D text/image-to-model were not counted as integrated; they each need their own contract and real verification. This round also did not implement API plan sales, top-ups, or a billing system.

An example that reproduces without depending on a generation API:

```bash
uv run --frozen python scripts/verify_local_first.py --out /absolute/new/directory
```

It runs a GPT-written CadQuery script that makes an 80×40×50 mm, 4 mm wall-thickness L-bracket with two 6 mm-diameter holes; it reads the STEP back to verify volume, checks the STL's dimensions, watertightness, and hole topology, then renders it via Blender, saves the project and a GLB, and finally imports it into an isolated editing project. It does not call a generation service or change the user's current project. Local timings: CAD 4.33 seconds, Blender rendering and delivery 1.79 seconds, and re-importing into editing succeeded; this excludes GPT thinking time and tool round-trip time.
