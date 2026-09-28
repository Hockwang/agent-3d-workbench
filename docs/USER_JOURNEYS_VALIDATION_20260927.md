# End-to-end local user journeys — 2026-09-27

[中文](zh-CN/USER_JOURNEYS_VALIDATION_20260927.md)

Four representative jobs reached editable delivery, print-copy export, orientation,
plate layout, project 3MF readback and real Bambu Studio CLI slicing. All are
reported as **completed with gaps**, not unconditional product acceptance.
Two reproducible implementation defects were repaired during the run.

## Conditions and scope

- Real stdio MCP client, background Python/CadQuery tasks, local Blender renders
  and local Bambu Studio CLI on macOS Apple Silicon.
- Empty hosted-service configuration; no 3D service credentials passed. The MCP
  server and its children ran under a macOS sandbox denying external network
  access. Each case's worker verified that an external connection returned EPERM.
- Each case explicitly opened its own folder project outside an existing Git
  repository. Merely changing `PRINT_PREP_HOME` is insufficient: a real Codex
  conversation ID can automatically attach its repository's shared project.
- This checks deterministic agent-authored plans through MCP. It is not a test
  of a new agent interpreting an arbitrary prompt without guidance, a clean-machine
  install, native host UI interaction or physical printing.
- Blender/Python/slicer dependencies were already installed. No DiT or hosted 3D
  generation service was used. The general-purpose agent is supplied by its host.

## Jobs and measured outcomes

All five plates sliced with return code 0 and no reported slicer warnings.
Geometry and project readback passed; no unmatched or slicer-moved objects.

| Job | Executed path | Parts / plates | Slicer estimate |
|---|---|---|---|
| Dimensioned bracket | CadQuery 80×40×50 mm bracket with two Ø6 holes → editor scale/undo → interleaved part edit/undo/redo → archive save → print copy | 1 / 1 | 24.63 g; 36m24s |
| Oversize rail | 320×60×16 mm stock → oversize detection → plane cut → two keyed pins and blind sockets with 2 mm wall guards → replacement workaround → print copy | 4 / 1 | 131.38 g; 2h12m14s |
| Two-color badge | Blue body/red cross → solid 2.2 mm inlay and 0.2 mm clearance pocket → editor import → separate plates | 2 / 2 | 13.35 + 1.68 g; 24m38s + 9m38s |
| Mounted hinge | Two drilled mounting plates → local pin-hinge installation → new URDF → 21 motion configurations → 236 body-removal samples → three rendered poses → print copy | 2 / 1 | 7.19 g; 26m37s |

Printer: **Bambu Lab P1S 0.4 nozzle**, 256×256×250 mm bed. Actual presets:
`Bambu PLA Basic @BBL P1S 0.4 nozzle`; mechanical jobs use
`0.20mm Standard @BBL X1C`, badge uses `0.16mm Optimal @BBL X1C`.
These are the locally resolved preset names, including their X1C suffix.
Orientation used `flat`, plate gap 6 mm; badge used `per_part` layout.
Estimates are slicer outputs, not measured print duration or consumption.

Source/task artifact hashes are checked on task completion and again after the
entire journey. Every output remains available in the chosen evidence directory.
`studio_send_to_bambu` is called with `dry_run=true`: no GUI launch or printer
submission occurs; delivery readiness remains incomplete by design.

## Defects repaired

1. **Concave color patch fragments.** Unioning individual edge-touching triangle
   prisms split a valid GLB cross into nine components after float32 roundtrip.
   `color_inlays.extrude_patch` now builds a boundary-stitched shell from shared
   topology before intersecting the source. The regression verifies one closed
   connected insert and its 1372.8 mm³ volume; no fragments are discarded and no
   acceptance tolerance was relaxed.
2. **Interleaved undo falsely conflicts.** Editing part A, another part, then A
   prevented a later undo of A despite no foreign changes. Collaboration history
   now updates the nearest relevant inverse per part, skipping unrelated history
   entries. Reload/undo/redo and real foreign-edit rejection have regressions.
   The MCP bracket journey also exercises nine interleaved undo/redo operations.

## Remaining gaps, in implementation order

| Priority | Observed gap | Consequence / next acceptance |
|---|---|---|
| P1 | Multi-object task import cannot atomically replace multiple originals | `replace_ids` with the two cut halves is rejected. This run explicitly deletes only its owned test halves, then imports. Add an atomic, revision-checked replacement preserving unrelated objects and undo. |
| P1 | Color intent does not reach printing presets | GLB is blue/red, but STL print copies lose color and both 3MFs use default `#00AE42`. Users must choose the filament color for each separate plate. Add a part/plate color manifest and verified 3MF material assignment. No automatic AMS claim. |
| P1 | Recipe progress does not consume these task results | Cut stays at `plane_cut`; color at `color_split`; hinge at `pick_joint` despite completed tasks. Bind progress to source/output versions and report verdicts; do not treat task process completion as acceptance. |
| P2 | Archive reopen differs from reopening a folder project | Whole-project archive `open` is intentionally rejected in shared projects (`scope_violation`). Surface a clear independent-branch recovery path; retain the collaboration safeguard. Archive save succeeds. |
| P2 | Default renders hide functional details | Front/isometric assembly renders hide bracket holes and rail sockets/pins. Add targeted top, section and exploded inspection views before appearance/fit approval. |
| Follow-up evidence | Physical fit and host onboarding remain untested | Check pin clearance, inlay retention, M2 screw/nut insertion, support removal and strength on coupons. Separately exercise native host UI and a clean install. Digital checks do not establish these. |

The hinge hardware list contains one M2×8 screw and one M2 nut. The 236 removal
samples cover the two printed bodies, **not hardware insertion**. Motion is sampled,
not a continuous collision proof. The badge report does not certify global minimum
wall thickness. No printer was started.

## Reproduction and evidence

Fresh final verification: **690 Python tests passed, 2 skipped**; the two changed
test modules passed all **26** focused tests. Repository Ruff lint, formatting of
the five changed Python files, and whitespace checks passed. Both defects were
reproduced by failing regressions before their fixes. No frontend code changed.

From the repository with its local dependencies installed:

```bash
uv run --frozen python scripts/verify_user_journeys.py \
  --out /absolute/new/directory/outside/git \
  --workspace-id "$CODEX_THREAD_ID" \
  --deny-external-network
```

Use the actual host conversation identity; other MCP hosts supply their own
session identifier. Network sandbox mode currently requires macOS. A fresh output
directory is mandatory; the script rejects case folders normalized to an existing
Git repository. It stops only backends started in its isolated runtime homes.

`results.json` and each case's `calls.json`/`result.json` retain MCP arguments,
errors, workarounds, renders, artifact paths/hashes, print estimates and gap stages.
Background task artifacts live under each case's `project/.3dstudio/job/tasks`;
3MF projects under `project/.3dstudio/job/plates`. A failed case returns a nonzero
script exit code; a completed journey with documented gaps remains explicitly
`completed_with_gaps`.

Initial attempts are not counted as acceptance: one had a client timeout-argument
mistake, and another unintentionally auto-attached the existing empty repository
project. Explicit folder binding fixed the harness isolation. The unintended test
scene was backed up, its edits removed and its previously empty print state restored.

See [the public capability contract](PUBLIC_CAPABILITIES.md) for supported inputs
and [the preceding capability-level run](LOCAL_CAPABILITIES_VALIDATION_20260926.md)
for broader kernel coverage. These four journeys do not revalidate every advertised
rigging, texture, scene or 2D-derived workflow.
