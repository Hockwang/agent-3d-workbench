[简体中文](zh-CN/PRINT_COLOR_INTENT.md)

# Part colors in print projects

This fixes the color-intent gap recorded in the two-color badge journey on
2026-09-27. It does not certify AMS configuration, loaded filament, physical
color accuracy, fit, or a real print. No printer submission is added.

## Inputs and mapping

- A uniformly colored opaque solid retains its explicit face/vertex color or
  untextured PBR base color during inspect. Textures, gradients, transparent
  materials, and multicolor solids are not averaged into a guessed print color.
- Editor `print_copy` still exports STL geometry. For a uniform solid it also
  writes `<file>.stl.color.json`, binding `color` to `stl_sha256` and schema
  `version: 1`. Keep this adjacent file when moving the STL. Inspect rejects a
  stale manifest. The persisted inspect part record carries the color onward.
- Override or supply colors with repeated `--part-color 'NAME=#RRGGBB'` on
  `export` or `prepare`. Names are the inspect part names. HTTP/MCP export and
  prepare accept `part_colors: {"NAME": "#RRGGBB"}`. These explicit values win
  over imported colors; invalid values and unknown names are rejected.
- The existing color-inlay palette can be supplied as an explicit mapping:
  `body` uses palette entry 0; the generated insert name uses its region's
  `palette_index`. No color is inferred from a filename or a default STL visual.

For example, after inspect/orient/arrange:

```bash
uv run python -m print_prep export --job /absolute/job \
  --part-color 'body=#0000FF' --part-color 'cross=#FF0000'
```

Each plate gets a deterministic deduplicated palette, one-based filament slots,
and `color_mapping` in its export record. Separate badge plates each get their
own correct single color. When uncolored parts share a colored plate, slot 1
retains the selected preset's default color for those parts. Color changes only
the copied filament preset's `filament_colour`; it does not choose a different
physical material or change temperature profiles. `check` uses the same plate
filament profiles rather than reverting to `filament-0.json`.

Geometry 3MF writes an object `pid`/`pindex` into a standard Materials extension
`m:colorgroup`, plus Bambu object metadata `extruder`. These are separate from
local vertices and build-item placement transforms. The Bambu importer consumes
`m:colorgroup` and maps object colors to extruders; see the upstream
[Bambu importer](https://github.com/bambulab/BambuStudio/blob/master/src/libslic3r/Format/bbs_3mf.cpp)
(`_handle_start_color_group`, `_handle_start_color`, and object assembly).

## Acceptance and limits

After Bambu exports a project, `compare_project_colors` reads its actual
`Metadata/project_settings.config` filament colors and resolves each named build
object's `extruder`, including volume-level overrides and inherited/default slot
1. It never accepts the source color manifest or 3MF display color as proof of
project assignment. Part names must match uniquely, allowing only known mesh
extension suffixes; there is no positional fallback. Missing/ambiguous parts,
out-of-range slots, wrong colors, missing project settings, and painted volumes
fail the check. A mismatch raises `project_color_changed` and leaves the job's
export/check readiness invalidated. Existing geometry/topology and placement
checks still run.

`--no-project` produces color intent and geometry only: it has no successful
actual-project color readback claim. Unspecified colors retain existing behavior.

Automated coverage includes a blue body/red cross GLB through editor print-copy,
STL manifest, inspect, separate plates, and geometry 3MF; independent synthetic
Bambu-style project fixtures test default-green collapse, duplicate slots,
invalid slots, reordered objects/palettes, and volume overrides. CLI serializer
test doubles check the export gate and preservation of geometry/placements.

Run the optional real Bambu regression on a host with Bambu Studio and its vendor
profiles installed (or configured through `BAMBU_STUDIO_PATH` and
`MFG_BAMBU_PROFILE_ROOT`):

```bash
uv run pytest tests/test_print_colors.py -m bambu -v
```

It generates its own blue/red badge and checks separate-plate and shared-plate
project exports. It does not require the old external STL fixtures, launch the
GUI, configure AMS, or print. A skip is not evidence that Bambu serialization
passed. The plugin preview validation records its real serializer results in
[PLUGIN_PREVIEW.md](PLUGIN_PREVIEW.md).
