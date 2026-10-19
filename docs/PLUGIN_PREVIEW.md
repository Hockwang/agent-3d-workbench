[简体中文](zh-CN/PLUGIN_PREVIEW.md)

# Plugin developer preview · 0.9.0

This preview updates the existing `print-prep` MCP plugin and browser workbench.
Run it in Codex or another configured MCP host. It contains no standalone Agent
chat application, app-server runtime, Electron host or desktop installer.

## Included changes

- A start page, direct model/result selection, static copies of displayed animation
  poses, print-bed references and dimension-preserving cuts for oversized parts.
- Persistent manufacturing stages: inspect, bounded local repair, split, connect,
  tolerance coupons, sampled assembly audit, arrange/slice, compare, delivery and
  replacement parts. Source hashes, revisions and task receipts bind each stage.
- High-polygon wall sampling and incomplete-evidence handling. Missing, empty or
  incomplete wall measurements cannot become a passing audit; old audits require
  rechecking before a new delivery. Sampling does not prove global wall thickness.
- Explicit opaque part colors survive editor print copies and are checked against
  actual serialized Bambu project assignments. See [color intent](PRINT_COLOR_INTENT.md).
- Slicer discovery and preset catalogs for Bambu Studio, OrcaSlicer, ElegooSlicer,
  Snapmaker Orca and Creality Print. Preset availability is not hardware validation.
  Creality receives geometry for manual setup. Other exporters depend on the
  installed slicer/version; cross-slicer handoff requires explicit geometry-only mode.
- Optional source-bound segmentation adapter, Lux3D upload/quote compatibility
  fixes, workspace binding checks and host-compatible artifact downloads.
- Experimental board design/nesting and a local LightBurn import connector. This
  only prepares/imports files; it does not move or fire a laser.

The four added MCP tools are `studio_list_slicers`, `studio_send_to_slicer`,
`studio_manufacture` and `studio_laser`. The plugin registers 30 tools in total;
[TOOLS.md](TOOLS.md) is generated from the actual runtime schemas.

## Install or update

Use a separate checkout for the preview if you have local source changes:

```bash
git clone https://github.com/Hockwang/agent-3d-workbench.git
cd agent-3d-workbench
uv sync --locked
STUDIO_LANG=en ./install.sh --add
```

Reconnect the plugin or restart its host after updating so the Python backend
loads the new code. Existing plugin ID `print-prep` and project formats remain.
Open `studio_open` with mode `manufacture` for the manufacturing workflow, `print`
for the print pipeline, or `home` for the start page. Back up valuable projects
before trying new manufacturing operations; work on explicit copies of inputs.

Blender and slicers are separate optional installations. The committed browser
assets include the STL exporter needed to freeze an animation pose, so plugin
users do not need to run a Node build. Developers rebuild with `npm ci` and
`npm run build:app`.

## Optional segmentation

In **API settings**, choose **Model segmentation** and configure your own
compatible service. No server address or credential is bundled. Remote endpoints
must use HTTPS; HTTP is accepted only on loopback (`localhost`, `127.0.0.1`, `::1`).
The adapter submits one model to `POST /segment`, checks the returned mesh's ordered
triangle geometry and echoed parameters, and binds face labels to the input SHA256.
An ambiguous submission is not automatically retried. This protocol has no API-key
field; do not expose an unauthenticated deployment directly to the public internet.

The output is a segmentation proposal, not closed printable parts or verified
semantic ownership. Inspect boundaries before using the source-bound labels in
manufacturing. Standard local editing and printing do not require this service.

## Limits and verification

Automatic remote repair remains unavailable. Local repair handles a bounded set of
mesh defects. Assembly withdrawal and wall checks are sampled; successful slicing,
color mapping and file import do not establish physical fit, strength, loaded
filament, printer readiness or a successful print. No tool submits a print job.
LightBurn pairing is stored under `$PRINT_PREP_HOME/connections/lightburn.json`
(default `~/.print-prep`), independently of project artifacts.

The preview is verified on macOS. Other operating systems and installed slicer
versions require their own acceptance; this is not a portable desktop distribution.
Verified on 2026-10-19 (macOS Apple Silicon):

| Check | Result |
| --- | --- |
| Python full suite | 859 passed; 2 external-fixture cases skipped |
| JavaScript suite | 198 passed |
| Ruff / generated tool reference / whitespace | Passed with the existing lint rules |
| Browser assets | All four bundles rebuilt; STL exporter and manufacturing icon included |
| Real Bambu color export | Separate/shared plate cases passed; no print submitted |
| README stdio MCP tutorial | Five parts imported; transform, undo, save, export and reopen passed |
| New tools over stdio MCP | 30 tools; version 0.9.0; manufacturing inspection and laser design/panels/nesting passed |
| Browser smoke | Home, five-part upload, seven workspaces, segmentation settings and language toggle passed; no page errors or failed HTTP requests |
| Browser/MCP binding | Same project and bidirectional selection; wrong workspace rejected; geometry unchanged |

The UI check used isolated state and headless Chromium. LightBurn pairing/import,
physical fabrication and live hosted generation were not exercised in this run.
The release tree was checked for private deployment hosts/IPs, personal absolute
paths, credential patterns and excluded standalone application modules.

Reproduce the automated checks without a generation-service account:

```bash
uv run pytest -q
npm test
uvx ruff@0.14.3 check .
npm run build:app
uv run python scripts/gen_tool_reference.py --check
uv run python examples/demo/verify_tutorial.py
uv run pytest tests/test_print_colors.py -m bambu -v
```

The last command uses a local Bambu installation, generates its own blue/red badge
and verifies separate/shared plate exports. It never submits a print. Tests
requiring external real-part fixtures skip unless `PRINT_PREP_E2E_PARTS` is set.
Private deployment settings, local run logs and standalone application evidence
are excluded from this plugin distribution; the lint configuration is not relaxed.
