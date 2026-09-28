> 中文：[SPEC.zh-CN.md](SPEC.zh-CN.md)

# print-prep Spec (v0.1, revision 1)

> The current six-step UI and shared state follow [SPEC_V05.md](docs/history/SPEC_V05.md) (historical record) and the [Codex integration notes](docs/CODEX_V05_INTEGRATION.md); this file keeps the underlying manufacturing/API contract and older history.

A Codex plugin that turns one or more mesh files into a printable Bambu Studio project and opens it in the Bambu Studio GUI, where it waits for a human to click print.

## 0. Boundaries

- **Everything here is original code.** Orienting, arranging, 3MF writing, and preset expansion are adapted from the author's earlier private research code (`manufacturing_kit/engine/print_waveab_v0/kitlib/{plate,slice_p1s,gates}.py`, same author, not part of this repo). **Do not** reference, translate, or port any private source code or numeric tables from any third-party product.
- **Don't touch the engine.** That research code is not vendored or imported. The plugin is self-contained (Codex copies the plugin into a cache directory on install, which would break relative paths).
- **Never send to a printer.** No action ever connects to or sends to a printer. Every JSON output carries `"print_submitted": false`.
- **Don't touch user config.** Implementation and tests must never read or write `~/.codex`, `~/.agents`, or `~/plugins`. Installation is done by `install.sh`, and only the main session runs it.
- Tests must never pop up a GUI: `open` is always tested with `--dry-run`.

## 1. Layout

```
print-prep/
  .codex-plugin/plugin.json        # B
  skills/print-prep/SKILL.md       # B
  install.sh                       # B
  README.md                        # B
  SPEC.md                          # this file (read-only)
  pyproject.toml  uv.lock          # A
  scripts/print_prep.py            # A  entry point: from print_prep.cli import main
  print_prep/__init__.py           # A
  print_prep/cli.py                # A  argparse + exit codes + JSON output
  print_prep/job.py                # A  job.json read/write, sha256
  print_prep/mesh_io.py            # A  loading and stats
  print_prep/profiles.py           # A  Bambu Studio preset index/expansion/bed params
  print_prep/shape_table.py        # A  shape label → orientation strategy + process selection (our own values)
  print_prep/orient.py             # A
  print_prep/arrange.py            # A
  print_prep/export3mf.py          # A  geometric 3MF write-out + read-back
  print_prep/bambu.py              # A  CLI wrapper (export project / test-slice) + open GUI
  tests/                           # A
```

A = code implementer, B = packaging implementer. Neither writes the other's files.

Dependencies are pinned to match the engine: `numpy==2.4.6`, `scipy==1.17.1`, `trimesh==4.12.2`, `pytest>=8`, `requires-python >=3.12`. The run command is fixed as `uv run --project <plugin root> python <plugin root>/scripts/print_prep.py …`.

## 2. Environment Variables (same names as the engine)

| Variable | Default |
|---|---|
| `BAMBU_STUDIO_APP` | `/Applications/BambuStudio.app` |
| `BAMBU_STUDIO_PATH` | `$BAMBU_STUDIO_APP/Contents/MacOS/BambuStudio` |
| `MFG_BAMBU_PROFILE_ROOT` | `$BAMBU_STUDIO_APP/Contents/Resources/profiles/BBL` |

## 3. CLI Contract

General rules:
- Every command prints **exactly one JSON object to stdout** (`ensure_ascii=False`); human-readable progress lines go to stderr.
- Exit codes: `0` success; `2` user-side error (bad argument, doesn't fit, file not found, mesh unusable); `3` environment error (Bambu Studio / preset directory not found, CLI call failed); `1` unexpected exception. On non-zero exit, stdout is still JSON: `{"ok": false, "error": {"code": "...", "message": "..."}}`.
- **Argument-parsing errors must also produce JSON** (unknown subcommand, missing subcommand, invalid enum value, unknown argument): exit code 2, `error.code = "bad_arguments"`, stdout must never be empty.
- The success JSON always has `"ok": true, "command": "...", "job": "<absolute path>", "print_submitted": false` at the top level.
- `--job DIR` is the working directory; state is stored in `DIR/job.json`, and each command reads/writes it as needed. Re-running the same step overwrites that step's artifacts and invalidates the record of every step after it (their keys are removed from job.json).

### 3.1 `printers [--filter STR]`
Does not need `--job`. Lists every machine preset under the preset directory `machine/` with `instantiation == "true"` (after expanding `inherits`):
`{"printers":[{"name","printer_model","nozzle_mm","bed_mm":[x,y,z],"exclude_areas":[[x0,y0,x1,y1],...],"default_process","default_filament"}]}`
- `bed_mm` comes from the bounding box of `printable_area` (a corner-point string like `"256x256"`) plus `printable_height`; `exclude_areas` comes from the bounding box of the corner-point string in `bed_exclude_area` (`[]` if empty).

### 3.2 `inspect --job DIR FILES... [--printer NAME] [--scale F | --target-max-mm H] [--merge]`
- Loads STL / OBJ / PLY / GLB / GLTF / 3MF. For scene-type files, node transforms **must be applied** before taking the geometry (trimesh 4.12.2's `geometry.values()` drops the transform; use `scene.graph` to transform each node, or `scene.to_mesh()`/`dump(concatenate=...)`). By default each geometry node in the scene becomes one part; `--merge` collapses a whole file into one part.
- Connectivity and watertightness are measured on **a copy with UV dropped and vertices merged by position** (a UV seam splits vertices that share a position, producing false fragments). The original geometry is left unchanged.
- Units are millimeters. `--scale F` scales uniformly, and **F must be > 0** (0 or negative → exit code 2; a negative value would mirror the part). `--target-max-mm H` scales the **combined bounding box of all parts** (each part kept at its position in the source file, i.e. the assembly frame) so its longest edge becomes H, using one shared factor for everything; H must be > 0. The two options are mutually exclusive.
- Default printer is `Bambu Lab P1S 0.4 nozzle`.
- Per part: `name` (a single-geometry file uses the file's base name; a scene file uses the node name; duplicates get a `_2` suffix), `source`, `source_sha256`, `faces`, `vertices`, `extents_mm`, `volume_cm3` (`null` if not watertight), `watertight`, `components`, `fits_bed` (whether, among the six axis-up orientations, at least one fits inside the usable area), `suggested_scale` (given when it doesn't fit, rounded down to 3 decimal places).
- Usable area = bed size minus `margin_mm` on every side (default 5) and minus 5 in height.
- The scaled mesh is saved as `DIR/parts/<name>.stl` (binary); later steps read only that file. **When later steps load it, vertices must be merged by position** (an STL read-back has `faces × 3` vertices with no merging; without merging, writing it into a 3MF leaves the slicer looking at a pile of open edges).
- Warnings list `warnings`: not watertight, multiple connected components, more than 2 million faces, longest edge under 5 mm or over 2000 mm (usually a unit mistake).

### 3.3 `orient --job DIR [--strategy auto|flat|support|upright] [--shape LABEL] [--set NAME=x,y,z ...]`
- `LABEL ∈ {generic, figurine, relief, mechanical}`, default `generic`. `auto` = take the strategy from `shape_table`.
- Candidate up directions: the reverse of large-face-cluster normals (normals binned and summed by area, keeping bins with a share ≥ 3%) + the six coordinate axes; the `support` strategy additionally adds 200 Fibonacci-sphere directions.
- Metrics (per candidate): `contact_area_mm2` (faces within 0.05 mm of the lowest point and facing down), `overhang_area_mm2` (faces whose normal's dot product with −up exceeds cos(threshold), threshold defaults to 30 degrees, excluding faces already touching the bed), `height_mm`.
- **Performance requirement**: overhang area is first computed on a "normal histogram" (bin face normals into roughly 1-degree bins, sum area per bin, then sum bins per candidate). **The pre-filter only applies to Fibonacci-sphere candidates**: the top 12 with the smallest histogram-estimated overhang go on to exact evaluation; large-face-cluster candidates and the six coordinate axes go to exact evaluation **unconditionally** (there are few of them, and "largest flat face down" is exactly the case where the histogram estimate is worst, so a pre-filter would throw out the right answer). A single 2-million-face mesh should finish within 30 seconds.
- **Stability floor**: `STABLE_CONTACT_MM2 = 20`. Candidates whose bed-contact area falls below this are considered unstable.
- Strategies: `flat` takes the largest bed-contact area (ties broken by overhang); `support` takes the smallest overhang area among **stable candidates** (ties broken by height), or the smallest overhang overall if there are no stable candidates at all; `upright` keeps the source file's +Z as up, and only falls back to the `support` result when +Z is unstable and a stable candidate exists, in which case it also writes `upright_rejected: true` and `upright_rejected_reason`.
- Whichever orientation is chosen — by any strategy or manually — if its bed-contact area is below `STABLE_CONTACT_MM2`, that part's `warnings` must include `unstable_contact`.
- `--set NAME=x,y,z` sets it manually and takes priority over the strategy. A zero vector or an invalid number → exit code 2.
- Per part output: `print_up` (unit vector), `strategy_used`, the three metrics, `warnings` (list), `top_candidates` (top 3 with their metrics).

### 3.4 `arrange --job DIR [--mode single|per_part|auto] [--gap 4]`
- The mode is **one enum used end to end**: the CLI, job.json, and internal functions all use the same set of literal values, with no alias translation.  Default is `auto`.
- v0.1 has **no** `--group-by` (the load step doesn't parse color, so keeping it would just be an accepted-but-inert argument).
- `--gap` must be ≥ 0, otherwise exit code 2.
- Each part is first rotated so `print_up` becomes +Z, then rotated 0 or 90 degrees around Z: prefer putting the long edge along X (shelf-packing gets a smaller row height that way); if that would make the width exceed the usable area, use the other rotation. Then a shelf-packing layout (largest parts first); exclude areas are avoided (a part pushed into an exclude zone first tries to dodge to the right; if there isn't enough room to the right, it starts a new row and is raised above the top edge of the exclude zone); parts are spaced by `gap`.
- **Post-placement validation**: after each part is placed, it must lie entirely inside the usable area and must not intersect any exclude zone, otherwise this plate is treated as "doesn't fit" (open a new plate or report an error) — a part is never left in an invalid position.
- `single`: everything on one plate; if it doesn't fit → exit code 2, with the error message stating how many plates `auto` would need. `per_part`: one part per plate. `auto`: pack in order, opening a new plate whenever the current one is full.
- A part that can't fit on its own (larger than the usable area, or permanently unplaceable because of exclude zones) → exit code 2, with a `suggested_scale`. This must never end in an unexpected exception (exit code 1).
- Output `plates:[{index(starting at 1), parts, placements:[{part, T(4x4), x_mm, y_mm, footprint_mm}]}]`.
- **No silently dropped parts allowed**: every part must appear exactly once, verified at the end of the function with an explicit `raise` (not `assert`, which `python -O` strips out).

### 3.5 `export --job DIR [--process NAME] [--filament NAME] [--shape LABEL] [--set key=value ...] [--no-project]`
Two steps per plate:
1. Write a geometric 3MF `DIR/plates/plate_NN.geometry.3mf` (each part's geometry in its local frame + the build item's `transform` holding the arranged placement + `Metadata/model_settings.config` carrying part names). After writing, **read it back**; `pass` means the nearest-vertex two-way error is ≤ 0.01 mm **and** every part's transform matrix matches the request; otherwise exit code 1. Vertices and triangles are written out with chunked string concatenation, not by building an element-by-element XML tree (a multi-million-face part would otherwise eat several GB).
2. Call the Bambu Studio CLI to produce the actual project file `DIR/plates/plate_NN.project.3mf`:
   `--datadir DIR/bambu-cli-data --load-settings machine.json;process.json --load-filaments filament.json --orient 0 --arrange 0 --ensure-on-bed --outputdir … --export-3mf … --export-settings …`, **without `--slice`**. If testing shows the CLI refuses to export without slicing, switch to including `--slice 0` and record that fact both in job.json's `export.notes` and in the README's "Known Limitations".
   After generation, read the build-item transform back from the project 3MF and compare it against the requested placement transform (max difference in translation and rotation separately), and include this in the output; a difference over 0.01 mm / 1e-6 is not treated as a failure, but must be reported truthfully as `bambu_moved_objects: true`.
   Bambu re-centers each part's geometry when it stores it, and records the centering offset in `Metadata/model_settings.config` as `source_offset_{x,y,z}` (in the part's local frame). If the file's transform is `(R_b, t_b)`, the translation to compare against the request is **`t_b − R_b · offset`** (not `t_b − offset`; the two are only equal when `R_b = I`).
   **Any part that can't be matched up in the project file** (name mismatch) → `bambu_moved_objects: true`, with an `unmatched_parts` list in the output; never report "nothing moved" by only comparing the parts that did match.
- Presets: the machine preset comes from the job's printer; the process preset defaults to the layer-height tier from `shape_table`, looking under `process/` for a system preset whose `compatible_printers` includes that machine and whose `layer_height` equals that tier (falling back to the machine's `default_print_profile` with a warning if none is found); `--process NAME` sets it directly. The filament defaults to the machine's `default_filament_profile[0]`.
- Override order: system preset ← `shape_table`'s deltas ← `--set`. All of it is recorded in `DIR/profiles/provenance.json` (including the sha256 of each source preset file, the final overrides, and `machine_gcode_modified: false`). **Machine G-code is never modified.**
- `--no-project` performs only step 1.

### 3.6 `check --job DIR [--plate N]`
Runs a headless test-slice with `--slice 0` into `DIR/check/plate_NN/`, using the same geometric 3MF and presets the project uses (kept separate from the project file that gets opened). Per plate output: `grams`, `seconds`, `warnings`, `returncode`, `wall_seconds`. Failures never raise; they honestly return `null` and an error string with exit code 3. Default timeout is 1500 seconds.

### 3.7 `open --job DIR [--plate N | --all] [--dry-run]`
- Runs `open -a $BAMBU_STUDIO_APP <project.3mf>`. Default `--plate 1`. `--all` opens them one at a time, 3 seconds apart.
- `--dry-run` only prints the command that would run.
- Afterward, waits up to 20 seconds using `pgrep -x BambuStudio` to confirm the process came up. Output `launched` (boolean) and `loaded: "unverified"` — **the CLI has no way to confirm the file actually loaded in the GUI, and must never claim that it did**.
- App not found → exit code 3.

### 3.8 `prepare --job DIR FILES... [options from the steps above] [--check] [--open]`
The two `--set` options are disambiguated at this level: `--orient-set NAME=x,y,z`, `--export-set key=value`.
Runs inspect → orient → arrange → export (→ check) (→ open) in sequence, stopping at the first failure. Output is a summary: the key result of each step plus a list of artifact paths.

## 4. `shape_table` (our own values, can be overridden by `--set`)

| Label | Orientation strategy | Layer-height tier | Process deltas |
|---|---|---|---|
| `generic` | `support` | 0.20 | none |
| `figurine` | `upright` | 0.16 | `enable_support=1`, `support_type=tree(auto)`, `support_on_build_plate_only=0`, `brim_type=outer_only`, `brim_width=3` |
| `relief` | `flat` | 0.16 | `enable_support=0` |
| `mechanical` | `flat` | 0.20 | `wall_loops=4`, `sparse_infill_density=20%`, `enable_support=1`, `support_type=normal(auto)`, `support_on_build_plate_only=1` |

Each row has a one-line comment in the code explaining the reasoning (ordinary slicing know-how is enough).

## 5. Tests (owned by A)

`uv run --project . pytest -q` must pass fully. Must cover at least:
1. `printers` lists `Bambu Lab P1S 0.4 nozzle`, bed 256×256×250, exclude zone `[0,0,18,28]`.
2. A synthetic box goes through inspect → orient → arrange → export `--no-project`: read-back error < 0.01 mm; `flat` puts the largest face of a 30×20×5 box down.
3. `arrange`'s three modes: 20 boxes of 60×60×10 exit with code 2 under `single`, with the message stating how many plates are needed; `auto` produces multiple plates with every part appearing exactly once; `per_part` produces 20 plates.
4. A mesh with a UV seam (artificially splitting a cube's vertices along a face) still has `components == 1`, `watertight == true`.
5. A GLB scene with a translated node loads with the correct bounding-box position (verifying the transform wasn't dropped).
6. `open --dry-run` prints the correct command and starts no process.
7. The histogram-based overhang approximation and the exact per-face value differ by < 2% on a synthetic part combining a sphere and an overhanging box.
9. `flat` pre-filter regression: a 12-sided prism (circumradius 20, height 20) with `--strategy flat` must select the flat end down (bed-contact area about 1200 mm², height 20), not a side face.
10. Project read-back math: hand-build a Bambu-style project 3MF (requested transform = 90-degree Z rotation + translation, geometry re-centered with `offset=(7,-3,11)` and `source_offset_*` written). Scene A, unmoved → `bambu_moved_objects == false`. Scene B, genuinely shifted by (4,-10,0) → `true`, with a translation difference of about 10.77 mm. Scene C, one of two parts with a mismatched name → `true`, with a non-empty `unmatched_parts`.
11. Read-back gate: a cube requested with a 90-degree Z rotation but written with the identity transform → `pass == false`.
12. CLI contract: four inputs — unknown subcommand / no subcommand / `--mode bogus` / `prepare … --set a=b` — all produce a single JSON on stdout with exit code 2. `--scale -2`, `--scale 0`, `--gap -5`, `orient --set x=0,0,0` all exit with code 2.
13. Post-placement arrangement validation: a 240×40×10 strip must fit on a P1S (shifted above the exclude zone's top edge); a 240×225×10 plate can't dodge the exclude zone → exit code 2 with a `suggested_scale` below 1; every placement that does succeed is verified part-by-part to be inside the usable area, non-overlapping, and clear of exclude zones.
14. `--target-max-mm`: three 100 mm boxes in a GLB at (0,0,0)/(900,0,0)/(0,900,0), `--target-max-mm 180` → `scale_applied == 0.18`.
8. Real end-to-end test (marked `@pytest.mark.bambu`, only runs on a machine with Bambu Studio): run `prepare --shape figurine` (without `--open`) on five already-repaired sample STLs, asserting the project 3MF exists, is a valid zip, and contains `Metadata/project_settings.config`, while printing out the two facts observed in practice: "does the CLI refuse to export without slicing" and "did Bambu move any objects". **Also run a second arm with `--shape mechanical`** (its orientation involves an actual rotation; the `figurine` arm always has `R` as the identity, so it never exercises the read-back formula): both arms must assert `bambu_moved_objects == false`, `unmatched_parts == []`, and a translation difference < 0.01 mm. Artifacts are written to pytest's `tmp_path`, never into the repo.

---

# Part Two: Studio Panel (v0.2)

Target shape: a visual panel opened in Codex's right-side built-in browser. A user can click it, and Codex can drive it directly; both sides go through the same backend, with the view kept in real-time sync. The CLI from Part One is its backend.

```
User clicks a button ─┐
Page-registered WebMCP tools (Codex calls them via the built-in browser) ─┤→ local HTTP API → print_prep library → job directory
Plugin's own stdio MCP server (fallback channel) ─────────┘                     ↑ state lives only here
```

## 6. Layout (new)

```
studio/__init__.py
studio/shell/server.py          # P1  local service: static pages + JSON API + SSE
studio/shell/mcp_server.py      # P1  stdio MCP server (official mcp SDK), tools → HTTP
studio/shell/tools_schema.py    # P1  single source of truth for tool names/descriptions/input schema (also served to the page via /api/tools)
scripts/studio.py         # P1  entry point: start | stop | status | url
tests/test_studio_api.py  # P1
tests/test_mcp_server.py  # P1
studio/web/index.html     # P2
studio/web/app.js         # P2
studio/web/style.css      # P2
studio/web/vendor/**      # P2  copied from the author's research tooling (manufacturing_kit/articulation/vendor/): three.module.js, addons/controls/OrbitControls.js, addons/loaders/STLLoader.js (MIT, license headers kept)
```

No external network resources are used (no CDN, no linked fonts). The front end has no build step: native ES modules + an import map.

## 7. Local Service `studio/shell/server.py`

- Listens only on `127.0.0.1`. Default port 8977; if taken, it walks forward to find a free one. Startup args: `--job DIR` (default `~/.print-prep/job`), `--port`.
- On startup it generates a random token and writes `{pid, port, token, job, url, started}` into `~/.print-prep/studio.json` (permissions 0600). `scripts/studio.py start` launches it in the background and waits for the health check to pass; if it's already running, it just returns the existing info. `stop` kills the process and deletes that file.
- **Anti-cross-site**: every request checks that the `Host` header is `127.0.0.1:<port>` or `localhost:<port>`; every `POST` additionally requires the `X-Studio-Token` header to equal the token (the page gets the token from a same-origin `GET /api/session`; that endpoint rejects requests carrying an `Origin` header that isn't same-origin). No CORS-allow headers are ever sent.
- Write operations are single-flight: only one runs at a time; other write requests during that window get a 409 `{"ok":false,"error":{"code":"busy",...}}`. A write operation **blocks until it's done** before returning (export takes roughly ten-odd seconds per plate; a test-slice can take several minutes).
- Write operations call `print_prep.cli`'s `cmd_*` functions directly (constructing an `argparse.Namespace`), mapping a `CliError` to `{"ok":false,"error":{code,message}, ...payload}` plus an HTTP status (400 for a user error, 502 for an environment error, 500 for unexpected). No spawning a subprocess to run the CLI.
- Revision number `rev`: incremented once when a write operation starts and once when it finishes. `GET /api/events` is SSE and pushes `data: {"rev":N}` on every change, plus a keep-alive comment line every 15 seconds.

Endpoints:

| Method Path | Input | Description |
|---|---|---|
| `GET /` and static files | | `studio/web/` |
| `GET /api/session` | | `{token, url, job}` |
| `GET /api/tools` | | The content of `tools_schema`, used by the page to register WebMCP tools |
| `GET /api/state` | | See below |
| `GET /api/events` | | SSE |
| `GET /api/printers` | `?filter=` | Same as the `printers` command |
| `GET /api/shapes` | | The shape-label table (orientation strategy, layer-height tier, process deltas), used by the "Print Enhancements" card |
| `GET /api/part/<name>.stl` | | `parts/<name>.stl` from the job (part-local frame, already scaled). The name must match a part registered in the job, to prevent directory traversal |
| `POST /api/load` | `{files:[absolute paths], printer?, scale?, target_max_mm?, merge?}` | = inspect |
| `POST /api/upload` | multipart, or raw bytes with `?name=` | Stored under `DIR/uploads/`, returns the absolute path (a browser file picker can't hand back a local path, so drag-and-drop upload goes through here). 500 MB per-file limit; only accepts stl/obj/ply/glb/gltf/3mf |
| `POST /api/orient` | `{strategy?, shape?, set?:{part name: [x,y,z]}}` | |
| `POST /api/arrange` | `{mode?, gap?}` | |
| `POST /api/export` | `{shape?, process?, filament?, set?:{k:v}, no_project?}` | |
| `POST /api/check` | `{plate?}` | |
| `POST /api/send` | `{plate?, all?, dry_run?}` | = open, opens it in the Bambu Studio GUI |
| `POST /api/prepare` | load + each step's options + `check?` + `send?` | One shot; missing steps use their defaults |

Shape of `GET /api/state` (authoritative for both P1 and P2; `null` means that step hasn't run yet, or has been invalidated):

```json
{"ok": true, "rev": 12, "print_submitted": false,
 "busy": null, "last_error": null, "job": "/abs/dir",
 "printer": {"name": "Bambu Lab P1S 0.4 nozzle", "bed_mm": [256,256,250], "exclude_areas": [[0,0,18,28]], "margin_mm": 5},
 "options": {"shape": "generic", "strategy": "auto", "mode": "auto", "gap": 4},
 "steps": {"inspect": true, "orient": true, "arrange": true, "export": false, "check": false},
 "warnings": ["..."],
 "parts": [{"name": "body", "faces": 994890, "extents_mm": [60,40,120], "volume_cm3": 88.1, "watertight": true,
            "components": 1, "fits_bed": true, "suggested_scale": null, "source_center_mm": [0,0,60],
            "stl_url": "/api/part/body.stl?rev=3",
            "orient": {"print_up": [0,0,1], "strategy_used": "upright", "contact_area_mm2": 310.2, "overhang_area_mm2": 1520.0,
                       "height_mm": 120.0, "upright_rejected": false, "upright_rejected_reason": null, "warnings": [],
                       "top_candidates": [{"print_up": [0,0,1], "contact_area_mm2": 310.2, "overhang_area_mm2": 1520.0, "height_mm": 120.0}]}}],
 "plates": [{"index": 1, "parts": ["body"], "placements": [{"part": "body", "T": [[1,0,0,20],[0,1,0,30],[0,0,1,0],[0,0,0,1]], "x_mm": 20, "y_mm": 30, "footprint_mm": [60,40]}]}],
 "export": {"process_preset": "0.16mm Optimal @BBL X1C", "filament_preset": "Bambu PLA Basic @BBL P1S 0.4 nozzle", "overrides": {"enable_support": "1"},
            "plates": [{"index": 1, "project_3mf": "/abs/plate_01.project.3mf", "geometry_3mf": "/abs/plate_01.geometry.3mf", "bambu_moved_objects": false, "unmatched_parts": []}], "notes": []},
 "check": {"plates": [{"index": 1, "grams": 196.57, "seconds": 45000, "warnings": [], "returncode": 0}]},
 "sent": {"plates": [1], "launched": true, "loaded": "unverified", "was_running_before": false, "at": "2026-09-19T16:40:00+08:00"}}
```

`busy` is `{"op": "export", "since": "<ISO timestamp>"}` while something is running; `last_error` is the most recent failure as `{"op","code","message"}`, cleared by the next successful write operation.

## 8. Tools (WebMCP and stdio MCP share names and params, defined in one place)

`GET /api/tools` returns `{"ok": true, "tools": [{"name", "description", "inputSchema" (JSON Schema, object at the root), "readOnly" (boolean), "method" ("GET"|"POST"), "path" (e.g. "/api/orient")}]}`; a `GET`-style tool's input is turned into a query string. `studio_open` only exists on the stdio side and never appears in this list.

`studio_get_state` (read-only), `studio_list_printers` (read-only), `studio_load`, `studio_orient`, `studio_arrange`, `studio_export`, `studio_check`, `studio_send_to_bambu`, `studio_prepare`. Inputs match the corresponding endpoint in §7. The return value is always the endpoint's JSON response verbatim. Descriptions are written in Chinese and must state clearly that "this tool never sends anything to a printer" and that "`loaded` is always unverified — never claim it has actually loaded".

The stdio MCP additionally has a `studio_open`: it makes sure the local service is running and, by default, returns an MCP App (`ui://print-prep/studio-v2.html`) plus structured state; the resource is self-contained `text/html;profile=mcp-app` and renders embedded in supporting hosts. Tool metadata declares `global`/`thread` entry points through `openai/ui.entrypoints`, and requests the right-side workspace with `preferredModelDisplayMode: "fullscreen"` (verified against the installed Codex 26.915.31945 (9922) extension's schema and right-tab routing code). The tool result's `openai/widgetSessionId` is a hash of the job path, allowing the panel to be reused within the same task. Inline chat rendering shows only a brief entry point and an expand button; the standalone global entry point only supports inline, but already has a full workspace of its own. The old `{url, job, already_running}` web address is only returned when `presentation: "browser"` is explicitly requested. Every stdio-side tool call first makes sure the service is running.

The embedded prototype UI's source is `studio/app/`; `npm run build:app` generates `dist/studio.html`, which ships with the plugin. Buttons reuse the backend through MCP `tools/call`; the selection is sent through `ui/update-model-context`. State is fetched every 5 seconds, and controls are only redrawn when the data has actually changed. The preview resource `print-prep://preview/<encoded-part-name>?v=<mtime_ns>` only accepts parts already registered in the current job and checks the version — it does not support an arbitrary file path. A display copy capped at 30,000 faces per part is cached in memory; the original STL, the job, and the manufacturing output are unchanged. The full upload form, process form, and test-slice/send UI still live on the old web page; existing MCP tool capabilities are unchanged.

The workspace uses a fixed-usable-height layout: the viewport scales, the properties panel scrolls internally and can be collapsed, and the bottom action bar is independent. It respects `safeAreaInsets` to avoid the host's input area covering it. The workspace sets its own background and text color explicitly, rather than depending on the host document's light/dark theme. WebGL is created lazily when the workspace expands; collapsing keeps the camera/selection and pauses rendering; it never repeatedly requests fullscreen on its own, and the user is free to collapse it manually.

Page side: it prefers `document.modelContext` if it has a `registerTool` or `provideContext` method (the current official Codex interface), falling back to the older `navigator.modelContext`. An empty object does not count as an available interface; each `registerTool({name, description, inputSchema, annotations, execute})` call is awaited in turn (or, if only `provideContext` exists, that single call is awaited); an async rejection must show a registration failure — it must never report success early or silently switch channels after a rejection. `execute` internally is just a `fetch` to the corresponding endpoint, returning `{content:[{type:"text", text: JSON string}]}`. Registration status is shown in the page's status bar: "Page tools: N registered" or "Page tools: this browser doesn't support it, Codex needs the plugin's own MCP server".

## 9. Panel (P2)

**Look v0.4 (2026-09-20; after seeing v0.3 the user said "copying it wholesale doesn't feel quite right" and pointed us at our own Lux3D editor)**: the layout is identical to v0.3 — only the visual language changed, to match our own Lux3D workbench's look. The reference is Lux3D editor's real logged-in UI (viewed with the user's authorization, from his Chrome login session) plus the numeric values from its publicly loaded stylesheet. Key points:

- The base color is a neutral near-black (the viewport is `#000` with a soft glow in the top-left corner and a bit of blue glow behind the model; the plan sidebar is `#080808`; floating cards are `rgba(16,16,18,.86)` with a 20 px blur, a 1 px 12%-white border, and 18 px rounded corners).
- The accent color is brand blue. `--accent #2261f5` is only used as a fill with white text on top (5.1:1 contrast); currently only "Send" uses it; accent text/icons on dark backgrounds use a lighter `--accent-text #79b7ff`.
- "Selected" is standardized to one visual pattern everywhere: a dark blue background `#0d1528` + a light blue border `rgba(113,153,242,.9)` + a 1 px outer ring. The orientation-strategy radio cards, the shape/plate-split chips, and the selected row in the part list all use it; a selected part in the viewport gets the same light-blue `#79b7ff` outline.
- The shape / plate-split segmented controls changed from "a slider inside one track" to a row of independent chips (gray when unselected, as above when selected).
- Green/orange/red now only indicate status (`--ok #34d399`, `--warn #ffbc33`, `--danger #fb7185`) and no longer double as accent colors; the X/Y/Z axis letters use the same set.
- The view-button bar and the "reopen Print Plan" button are dark-gray pills (`#292d32`, 20%-white border, drop shadow); the selected state inside the button bar is a neutral 16%-white highlight.
- "One-Click Prepare" is a steel-blue gradient secondary button (`#2e5a91 → #244774`), leaving the brightest brand blue for "Send".
- The "Print Enhancements" card is a subtle brand-blue-to-indigo gradient with a light blue border, title in `--accent-text`; the drag-and-drop upload zone is a dark checkerboard.
- Viewport: the canvas background is now transparent, letting the stylesheet show through; the bed surface is cool gray `#17191e`, with a 10 mm fine grid under a 50 mm major grid.
- Fixed two issues left over from v0.3 while we were at it: the view buttons' selected state never showed (an ID-based selector was overriding it); `font: 12px inherit` inside inputs is not a valid declaration and never took effect.
- Added `prefers-reduced-motion`: turns off transitions and progress-bar animation.

The look went through several iterations early on; the page structure, stylesheet, scripts, and icons are all our own, with no third-party source code copied. Functionality, endpoints, tools, and the state shape are unchanged; every item in the "Settings Sidebar, Top to Bottom" list below is still present, just relocated:

- Floating card "Plate Setup" (top-right of the viewport): printer row, shape (4 chips), orientation strategy (2×2 radio cards), plate-split strategy (3 chips) + spacing, model size (combined bounding box, read-only + target longest edge / scale), buttons "Choose Orientation", "Arrange", "One-Click Prepare".
- Floating card "Model" (top-left of the viewport, collapsed by default once parts exist): path, drag-and-drop upload, merge, load, the part list and warnings.
- Floating card "Selected Part" (bottom-left of the viewport, appears only when something is selected; card header shows the part's name): three small metric blocks for contact / overhang / height, warnings (codes translated to plain language), candidate orientations; the button next to each candidate is shortened to "Use" (hover tooltip still says "use this orientation").
- The view-button bar (plate tabs, Assembly/Plate, Fit View) sits centered at the bottom of the viewport. A selected part in the viewport is outlined in light blue (it was orange in v0.3). The 3D view auto-avoids the side covered by an expanded "Plate Setup" card; once the user manually rotates the view, auto-framing stops. When the viewport column is narrower than 560 px and the user hasn't manually toggled it, "Plate Setup" collapses by default.
- With multiple plates, the viewport's plate tabs and the action-bar plate dropdown stay in sync with each other; "Bed Utilization" and "Plate Footprint" both state which plate they refer to; `placements[].x_mm / y_mm` is the bottom-left corner of the footprint rectangle, not its center. When a test-slice hasn't produced numbers for every plate, the total filament/time is prefixed with "≥" and notes how many plates are missing numbers.
- Right sidebar "Print Plan": Plate Quality (parts/plate, bed utilization, contact area, overhang area, warnings) → Print Estimate (final size, plate footprint, filament, time, with a "Test Slice" link next to the section title) → Print Enhancements (the current shape's layer-height tier, orientation strategy, and process deltas, sourced from `GET /api/shapes`) → 3MF Project Parameters (printer, process, filament, overrides, units, advanced) → Export and Send results. The sidebar is collapsible.
- Bottom action bar: Export Project (icon button), plate selector (including "All Plates"), "Send". A small fixed line above it reads "Only opens in Bambu Studio, never sends to a printer."
- While busy, a progress card appears in the lower-middle of the viewport (operation name, elapsed time, indeterminate progress bar; no cancel).
- Below 600 px width, the layout switches to vertical: viewport on top, the three cards and the Print Plan sections stacked below, and the action bar pinned to the bottom.

Original layout (v0.2, now superseded by the above): a 3D viewport filling the remaining width on the left, a 360 px settings sidebar on the right (moved below the viewport under 900 px width). Follows the system's light/dark theme. All copy is in Chinese and is our own wording.

3D viewport (three.js):
- Print bed: drawn from `printer.bed_mm` as a grid with a border; exclude zones are translucent red, with a dashed box `margin_mm` in from every edge. Z is up.
- Two views: "Assembly" = each part at its position in the source file (`parts/*.stl` is in the local frame; the source position is `source_center_mm`, or the origin if absent); "Plate" = the selected plate's `placements[].T` applied to the matching part. Whenever `plates` exists, "Plate" view is the default, with tabs above to switch plates (Plate 1 / Plate 2 …).
- Each part gets a stable color; hovering shows the part name; clicking selects it and shows that part's metrics in the sidebar (contact/overhang/height/warnings) along with its top three candidate orientations, each with a "Use This Orientation" button (= `POST /api/orient` with `set`).
- Large meshes: STL loading happens in the background with a progress indicator; a part over 1.5 million faces is shown as-is with `geometry` but with per-frame picking disabled (raycasting only happens on click).
- Orbit controls; a "Fit View" button; after `rev` changes, only the parts that actually changed are rebuilt (a part's STL URL carries `rev`, so it isn't re-downloaded if unchanged).

Settings sidebar, top to bottom:
1. **Model**: a path input (can be multi-line) + drag-and-drop/file-picker upload; scale (a factor, or an overall longest-edge in millimeters); a "merge into one part" checkbox; a "Load" button. Below it, a part table: name, dimensions, face count, watertight, whether it fits, with warnings highlighted in yellow.
2. **Printer and Shape**: printer dropdown (from `/api/printers`, defaulting to P1S 0.4); shape label, one of four (generic / figurine / relief slab / mechanical part); orientation strategy (auto / max bed contact / least support / keep original orientation); a "Choose Orientation" button.
3. **Plate Split**: single plate / one part per plate / automatic; spacing; a "Arrange" button. Shows the plate count and parts per plate.
4. **Process and Export**: shows the process preset and filament preset that will be used (shown as actual values after export); an editable override table (key = value); an "Export Project" button. After export, each plate's file path, `bambu_moved_objects`, and `unmatched_parts` (highlighted red if non-empty) are shown.
5. **Test-Slice Estimate (optional)**: a "Test Slice" button; per-plate grams, time (converted to h:min), and warnings. Shows "not estimated yet" if it hasn't run.
6. **Send**: a plate picker + a "Send to Bambu Studio" button. On success: "Requested Bambu Studio to open plate_01.project.3mf, loading not confirmed"; if `was_running_before` is true, an extra line: "Bambu Studio was already running and may ask whether to save the current project first." A fixed line of small text: "This panel never sends anything to a printer — printing is confirmed by you in Bambu Studio."
7. A "One-Click Prepare" button at the top = `POST /api/prepare` (using the current settings-sidebar options).

Status bar (bottom): the name and elapsed time of whatever's busy, the most recent error (dismissible), page-tool registration status, `rev`. While any write operation is in progress, every button that would trigger a write is disabled.

Debugging: with `?mock=1`, the page doesn't connect to the backend and instead uses a built-in sample state and two procedurally generated box renders, for offline testing.

## 10. Tests (P1)

- `test_studio_api.py`: starts the service against a temporary job and a random port; a POST without a token is rejected (403); a bad `Host` header is rejected; two synthetic boxes go through load → orient → arrange → export (`no_project`), checking that `/api/state` has every field, `rev` increments, and `steps` is correct; `/api/part/../x` is rejected; a concurrent second write request gets 409; `send` with `dry_run` starts no process; SSE pushes a new `rev` after a write operation.
- `test_mcp_server.py`: starts `mcp_server.py` with the official SDK's stdio client; `tools/list` includes all ten tools; `studio_open` can bring the service up; `studio_get_state` matches the HTTP result; the test stops the service when it's done. The environment variable `PRINT_PREP_HOME` can redirect `~/.print-prep` to a temporary directory, and tests must use it — never touching the real `~/.print-prep`.
