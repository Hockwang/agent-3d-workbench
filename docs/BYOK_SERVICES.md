> 中文：[zh-CN/BYOK_SERVICES.md](zh-CN/BYOK_SERVICES.md)

# Bring Your Own Professional 3D API

Inside the workbench, Codex is responsible for planning, calling tools, and acceptance; the local Blender/CAD install continues to handle modeling and editing it can do directly. Users can bring their own professional 3D API for generation, part splitting, texturing, or rigging, without adding another API configuration for a general-purpose model like GPT.

## Usage

Start with the bilingual [real API generation demo](API_GENERATION_DEMO.md).
For Hi3D's two-part credentials, follow [Hi3D setup](HI3D.md); the current single-key
dialog below does not configure AK/SK.

1. Open "Modeling & Tasks → Manage 3D Services".
2. Pick a built-in connection, or add a new connection using the same protocol, filling in a name, API base URL, and API key; advanced settings can also reference a variable name already injected into the backend environment.
3. Save, then click "Test Connection". It reads a model list or balance without generating; Hi3D first exchanges AK/SK for a token. A successful connection does not mean generation quality has been accepted.
4. Back in "Execution Method", pick this connection, choose a task, and provide input. Once the model is received in the background it reuses the current viewer, and can be imported into a project for further editing or sent into the observation/evaluation flow.

Multiple connections can map to different accounts of the same vendor, or to compatible gateways. Saving does not reset the project or the viewport. An empty key field keeps the existing credential; changing the address automatically clears the inherited credential and requires re-entering it. Disabling/deleting only affects new tasks; existing tasks keep the configuration they were submitted with, for continued delivery.

| Template | Current protocol and capability | Read-only test |
| --- | --- | --- |
| Hunyuan 3D / Part | Responses-compatible gateway; text/image generation, FBX part splitting | GET /models, filtered to already-adapted models |
| Seed3D | OpenAI-compatible gateway chat/completions; fixed doubao-seed3d-2.0 image generation | GET /models, checks for Seed3D |
| Meshy | Official Bearer API; reuses existing generation, texturing, decimation, rigging, and animation adapters | GET /openapi/v1/balance |
| Tripo | Official V2 OpenAPI Bearer API; reuses existing adapter | GET /user/balance |
| Hi3D (environment setup) | Official AK/SK API; single-image geometry or textured GLB | POST auth/token, then GET balance; no generation |

Hunyuan's Tencent Cloud SecretId/SecretKey (TC3 signing) is not the Responses-gateway protocol; Seed3D's direct Volcano Engine interface likewise cannot be treated as compatible just by swapping the base URL. Assembly's custom auth is still configured through `services.json`. An adapter without real vendor credentials must not be marked as having passed real-service acceptance.

Whether `studio_task`'s `inputs` (local files) can be attached, and how long a task on a given provider is allowed to run before timing out, are declared per provider (`local_inputs_allowed`/`default_timeout_seconds` in `services.json`, see [Configuration](CONFIGURATION.md)) — not hard-coded to a specific adapter name. Assembly ships with local inputs disabled, since it only accepts remotely reachable URLs; Assembly, Hunyuan, Seed3D, and Lux3D all ship with a longer default timeout than Meshy/Tripo, since their hosted jobs typically run longer. Lux3D also has its own `allow_unquoted` opt-out from the quote-before-generate requirement — see [Lux3D](LUX3D.md).

## Keys and Recovery

- The legacy `~/.config/codex-3d/services.json` remains valid. UI-created connections are stored in `connections.private.json` in the same directory, written atomically with 0600 permissions, and contain private credentials; this is local file-permission protection, **not OS-keychain encryption**. When `WORKBENCH_SERVICE_CONFIG` points to a different config file, the private store sits next to it. Do not put the config directory inside a Git repo.
- The plaintext key exists only on the local settings page and in the backend. The page encrypts it with WebCrypto AES-GCM and wraps the AES key with the backend's temporary RSA-OAEP public key; only ciphertext ever appears in MCP tool parameters. The ciphertext is bound to the service address, and old sealed envelopes become invalid after a backend restart. Server responses, task parameters, and the project never store anything but a credential reference.
- API requests never follow automatic redirects, and CDN downloads never carry the service key. Changing the address never inherits the old credential; the old reference is kept only so an already-created task can keep receiving results. To revoke a vendor key, do it on the vendor's side.
- Hunyuan keeps polling with GET using the persisted response ID, and never POSTs again. Seed3D's synchronous submission has no adapted query endpoint: it is submitted exactly once; once the artifact URL is received it is cached privately, and downloads are resumed from that cache. If a submission times out or the response can't be parsed, check the upstream record first — automatically resubmitting is forbidden.
- `studio_services`'s list/save/delete/probe go through the same local interface as the UI; writing the config is version-checked and protected by a cross-process file lock. Keys can never be submitted through plain params or a plaintext config field.

## Why We Didn't Build a sub2api Platform

[aigccat's service-management implementation](https://github.com/RainNameless/aigccat/blob/94bdaa3d9af4345d0eb88da9a2f35434997d249a/web/src/services.rs) served as a reference for multi-connection management, enable/disable, and configuration state. This plugin borrows that interaction pattern, reusing the existing task executor, delivery pipeline, viewer, and standard credential store; it does not copy its vendor/subscription code.

The current user need is to bring one's own professional API for Codex to call directly; there is no need for an additional general-purpose-model proxy, subscription-session conversion, automatic account rotation, or a centralized billing server. Selling first-party professional 3D API packages later could be added as one more standard professional-service connection, with its own server-side auth, quotas, and billing built independently.

## Verification

Automated tests cover: cross-JS/Python decryption of the sealed envelope, long keys, rejection of tampering/expiry/address-change, permissions, no plaintext ever returned, credential binding for existing tasks, enable/disable/delete, concurrent version conflicts, read-only auth, and redirect rejection. The Seed3D tests use a real local HTTP service to verify ZIP delivery, resuming a download without resubmitting, no retry on an ambiguous submission, and that the API key never leaks into artifacts or the CDN.

Browser tests cover adding, saving, testing, switching, changing the address, deleting, and different widths; this is not the same as having tested native Codex's drag-resize performance. Real-vendor test results are recorded in this round's validation report.
