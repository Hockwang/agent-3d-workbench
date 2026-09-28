# Local capability validation — 2026-09-26

[中文](zh-CN/LOCAL_CAPABILITIES_VALIDATION_20260926.md)

Four local fabrication tasks now implement the five previously unbound recipe
routes. The [public contract](PUBLIC_CAPABILITIES.md) defines their input limits.
The MCP surface remains 26 tools; the local template catalog contains 33 entries.
Of 18 recipes, 17 bind local capabilities; `image-to-print` is an optional hosted
extension. Tool availability does not certify an entire product workflow.

## Runtime evidence

Run on macOS with installed dependencies, an isolated workspace, an empty service
configuration and no credential environment variables. macOS `sandbox-exec`
denied external networking to MCP, the local backend and task subprocesses;
loopback remained available. A real task attempted an external socket connection
and received `EPERM`. No specialized generation model or hosted 3D service ran.

The final stdio MCP run made 114 tool calls. It completed task dispatch, polling,
artifact collection, four new-URDF rest-pose checks, an editor import with three
objects, and two Blender observation batches showing six generated scenes.
All 69 returned artifact hashes were independently recomputed and matched.

| Case | Measured outcome |
|---|---|
| Locating connection | Two machined bodies and a separate keyed pin; closed STL outputs, socket-wall guards and 21 withdrawal positions for each host. |
| Color inlay | Closed blue body and red insert; insert volume 480 mm³, 33 removal samples. Real UV-texture sampling is additionally covered by the regression suite. |
| Pin hinge | Two machined hosts, M2 hardware list and new STL-bound URDF; five declared-range poses pass. |
| Slew | Two hosts plus cap, with cap attached to the moving link; the full-circle fixture fails at half-turn poses where the two hosts collide. An explicit ±1.4 rad range passes 17 samples. The initial failure remains recorded. |
| Slider | Two machined hosts and URDF; five poses over ±10 mm pass. No end stops or retention claim. |
| Ball socket | Two hosts plus removable cap and a conical stem opening; 125 combinations over three ±0.35 rad joints pass. Frictional holding and physical assembly remain unverified. |
| Mixed-pose counterexample | Nine combinations, eight clear and one collision. The previous diagonal-only sweep misses that collision. Task execution completes while the geometric report correctly says `fail`. |

All motion outcomes apply to these procedural fixtures and the reported samples,
not arbitrary models or continuous trajectories. Geometry was also visually
reviewed in real Blender renders; this is not a native-host UI acceptance test.

## Regression coverage

The full Python run passes 687 tests with 2 skips; JavaScript passes 125 tests.
The fabrication suite contains 14 tests covering actual solid geometry, thin-wall
rejection, later holes damaging earlier guards, UV/color seam connectivity,
palette mismatch, all joint families, rotated/translated URDF frames, mixed-pose
collisions and bounded work. Final recipe checks pass 159 tests.
Ruff lint, formatting of the 11 touched Python files and the generated MCP tool
reference check pass. UI sources and generated bundles were not changed.

Failures found and corrected during implementation:

- Duplicate UV/color seam vertices incorrectly split a single color region.
- Texture-to-color conversion returns detached vertex colors; face averaging
  must use the source mesh's actual face indices.
- Later holes could violate an earlier connector's larger wall requirement.
- The slew cap must follow the moving link in the exported URDF.
- A straight ball-stem bore allowed twisting but blocked lateral swing; a conical
  opening was needed and is now checked over the full fixture grid.
- One recipe guide exceeded the existing size limit; its prose was shortened.

Recipe acceptance text was also corrected: geometric assembly checks do not
detect slicer support inside holes. Assembly-path steps now bind `removal-audit`;
support accessibility remains a separate inspection after slicing. Small inlays
are not claimed to meet an unmeasured whole-body minimum wall thickness.

## Reproduce

```bash
uv run --frozen pytest -q
npm test
uvx ruff@0.14.3 check .
uv run --frozen python scripts/gen_tool_reference.py --check
uv run --frozen python scripts/verify_local_capabilities.py --out /tmp/local-fabrication-proof --deny-external-network
```

Use a new output directory. The last option currently requires macOS; omit it for
an ordinary MCP run on another platform, which does **not** establish network
isolation. The script creates its own procedural inputs and stops only its own
backend. `results.json`, `mcp-calls.json`, task reports and rendered contact sheets
remain in the output directory. Other-platform acceptance was not performed here.

## Files changed in this implementation

| Files | Change and reason |
|---|---|
| `studio/core/fabrication.py` | Shared discovery examples, input/solid validation, hashes and deliverable readback. |
| `studio/core/connect_parts.py` | Round/keyed locating pins, blind sockets and guard/withdrawal checks. |
| `studio/core/color_inlays.py` | Explicit palette and UV sampling, closed inserts/pockets and removal checks. |
| `studio/core/install_joint.py` | Four host-integrated joint families and URDF bound to their new meshes. |
| `studio/core/motion_check.py` | Explicit and Cartesian configuration sampling with honest failure reports. |
| `studio/core/task_templates.py`, `studio/core/task_operations.py` | Register the tasks and reuse the URDF intersection engine while retaining the legacy default. |
| `tests/test_local_fabrication.py` | Geometry and failure regression coverage. |
| `tests/test_recipes.py`, `tests/test_recipe_workbench.py` | Validate the real updated recipe bindings. |
| `scripts/verify_local_capabilities.py` | Reproducible stdio MCP acceptance with optional OS-enforced network isolation. |
| `recipes/{color-split,cut-to-fit,mechanical-joints,poseable-figure,split-glue-kit}/{recipe.json,guide.md}`, `recipes/README.md` | Bind implemented tasks and state applicable inputs, report checks and physical limits. |
| `README.md`, `README.zh-CN.md` | Link the public contract. |
| `docs/{PUBLIC_CAPABILITIES,WORKBENCH_TASKS,AGENT_PLAYBOOK,index,LOCAL_CAPABILITIES_VALIDATION_20260926}.md` and their `docs/zh-CN/` mirrors | Promise inventory, usage, current counts and this acceptance record. |

## Remaining limits

No physical print, force/retention test, continuous collision proof, arbitrary
semantic automation, clean-machine installation or native Codex sidebar
acceptance is claimed. This change does not refresh installed plugin caches,
replace an existing workbench session or publish a release. Existing user edits
are preserved; this implementation was not committed or pushed.
