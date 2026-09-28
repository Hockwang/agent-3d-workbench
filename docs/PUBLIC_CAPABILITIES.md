# Public capability contract

[中文](zh-CN/PUBLIC_CAPABILITIES.md)

The local workbench lets a general-purpose agent read shared 3D state, execute
local operations, inspect real evidence, revise the result and deliver editable
assets. It needs no specialized 3D generation model, 3D service account or 3D API
key. The agent is supplied by the host; Python/Node, Blender and a slicer remain
local prerequisites for the operations that use them. Installation can download
dependencies. This is a runtime claim, not an offline-install claim.

## What we promise

| Capability | Contract and acceptance |
|---|---|
| Shared editing | Import supported assets; read objects, units, selection and revisions; perform scoped edits, undo and save. Reopen folder projects; whole-archive replacement requires an independent model branch and is rejected in shared projects. An incompatible/stale edit fails without replacing the source. |
| Local modeling | Execute agent-authored Python, CadQuery and Blender scripts; deliver STEP/STL/GLB/Blender artifacts where applicable. Inspect actual output dimensions and solids; arbitrary artistic quality is not guaranteed. |
| Mesh processing | Transforms, boolean/plane cuts, connected components, explicitly labeled face splitting, small-hole repair, simplification. Face labels are supplied; automatic semantic ownership is not promised. |
| Materials and surfaces | Edit material slots, replace local textures, UV unwrap, bake and perform explicitly bounded smoothing/stretching. UV seams and source appearance need inspection after geometry changes. |
| Functional machining | Explicit cavity/lid, head-shell and local-dimension plans; the four fabrication tasks below provide additional checked operations. Applicable geometry and protected regions must be specified. |
| Rigging and motion | Explicit skeleton binding, weight repair, explicit bone-map retargeting, joint/keyframe editing and baked animation export. Natural motion, automatic anatomy and pose holding are separate acceptance questions. |
| Scene and 2D-derived assets | Local scene layout/rendering, offline interactive delivery, grayscale heightmap relief and SVG slices. Source assets or procedural geometry are supplied locally. |
| Observation | Real render images, comparable cameras/scales, geometry metrics and version-bound reviews. Successful execution is not a quality verdict. |
| Mechanical checks | Exact intersections at declared discrete poses, bounded combined-joint sampling and discrete removal checks. Reports retain the checked configurations and uncovered conditions. |
| Print preparation | Orientation, plate layout, geometry/project export and slicer estimates when the local slicer is installed. Physical fit, strength, wear and printer execution are outside digital acceptance. |

## Newly supplied fabrication tasks

All use `studio_task(action="start", template=..., inputs=[...], params={...})`,
then `studio_tasks(id=...)`. Paths are local absolute paths. Read `report.json`
and the actual artifacts: `completed` is process completion, while the report's
`status` is the geometric result. Source files stay unchanged. Import output
through the existing revision-checked editor or reload the new STL parts with
`studio_load` before orientation/export. Tasks do not replace the current model
or advance an entire recipe automatically.

### `connect-parts`

Two closed connected static objects meeting on a plane. `parts` lists their
scene node names in negative-axis/positive-axis order. `connectors` contains
1–16 plans with `center_mm`, `axis`, optional `x_hint`, `profile` (`round` or
`keyed`), `radius_mm` (2), `depth_mm` (6), `clearance_mm` (0.2), and
`min_wall_mm` (1.6). Multiple pins must use parallel axes.

Outputs: two bodies with blind sockets, separate pins, STL/GLB and report.
The entire conservative socket-wall/bottom guard must fit inside the host;
thin walls, disconnected output and sampled withdrawal collisions are rejected.
The measured wall bound applies to these sockets, not every wall on the model.
These are clearance/glue pins, not certified friction fits.

### `color-inlays`

One closed static object with opaque vertex/face colors or UV texture. Supply
`palette_rgb` (2–8 RGB byte triples, first color is the retained body),
`pull_direction`, `depth_mm` (1.2), `clearance_mm` (0.15),
`min_patch_area_mm2` (4), `max_color_distance` (0.25 in normalized RGB distance)
and `min_pull_cosine` (0.25). At most 5000 selected triangles are processed.

Texture colors are sampled at UV vertices and averaged per triangle; subdivide
coarse geometry upstream if its faces span tiny texture details. UV/color seams
do not split geometric connectivity. Selected regions must face one common pull
direction. Small regions are reported as paint-only, never silently declared
manufacturable. Each retained patch is extruded inward and intersected with the
source; the pocket has an axis-aligned L-infinity clearance envelope. Outputs
are closed, palette-colored inserts and a pocketed body, with 33 withdrawal
samples. Texture preservation and global minimum wall thickness are not claimed.
Back-wrapping regions, translucency, palette mismatch and obstructed sampled
withdrawal fail explicitly. Additional pins are optional and require a planar
mating interface suitable for `connect-parts`.

### `install-joint`

Two closed host objects. Supply `parts` (`fixed`, then `moving` node names),
`family` (`pin_hinge`, `slew`, `slider`, `ball_socket`), `center_mm`, `axis`,
optional `x_hint`, two world-coordinate `anchors_mm`, and a world-aligned
`machining_box_mm: [[xmin,ymin,zmin],[xmax,ymax,zmax]]`. `mount_radius_mm`
controls the connector beams. Every mount must actually intersect retained host
material. No added or removed volume may escape the machining box.

Closed connected output, rest-pose intersections, source hashes, changed volumes,
separate hardware items and an `assembly.urdf` referencing the **new** STL files
are delivered. Mechanical input dimensions are mm; URDF limits use radians/metres.
`joint_limits` is one `[lower,upper]` pair per joint (three for a ball socket),
and must include zero. These are proposed bounds, not a checked safe range.

The pin hinge uses an M2 screw/nut; the slew has a bonded retaining cap; the slider
has no end stops; the ball socket has a removable cap and two M2 through-bolts.
Ball-socket geometry does not establish frictional pose holding. Run
`motion-check` on the new URDF and separately inspect assembly order, appearance
and a physical test coupon. Telescopic linkages and arbitrary joint families are
not provided by this task.

Ball sockets accept `ball_radius_mm` (5), `socket_wall_mm` (2), and
`stem_swing_rad` (0.55), which opens a conical stem clearance. This opening angle
is not a certified travel range; check the combined poses of the mounted hosts.

### `motion-check`

One local URDF with local closed meshes. `sampling="grid"` samples the Cartesian
product of joint values, `steps` (default 5) per independent joint. Alternatively
use `sampling="explicit"` and `configurations`, each containing every independent
joint name. At most 4096 configurations; larger requests fail rather than silently
reduce coverage. `joint_ranges` can provide explicit ranges, and continuous joints
require them. Fixed-link groups and mimic joints follow the existing URDF loader.

`motion-check.json`/`report.json` include each configuration and colliding pair,
`clear_configurations` and `sampled_clear_values`, plus dependency hashes.
Per-axis clear values **must not be recombined into a safe range**: one value can
be safe only when another joint has a particular value. Continuous collision,
retention, force and wear remain unchecked. A collision produces report status
`fail`; successful task execution never changes that verdict to pass.

## Explicitly outside the promise

Arbitrary photo-to-3D generation, automatic semantic disassembly, identity-preserving
portrait reconstruction, universally natural animal animation, guaranteed physical
assembly/strength and automatic printer execution. Hosted adapters and the
`image-to-print` recipe are optional extensions, not part of the local promise.
Mouse/native-host integration and clean-machine installation must be verified on
each supported host; local kernel tests do not certify them.

## Verification

See the [2026-09-26 validation record](LOCAL_CAPABILITIES_VALIDATION_20260926.md) for measured results and remaining limits.
The [2026-09-27 user journeys](USER_JOURNEYS_VALIDATION_20260927.md) follow four jobs
through real slicing and record multi-part replacement, color handoff and recipe-progress gaps.

`uv run pytest -q tests/test_local_fabrication.py` checks real solids, thin-wall
rejection, color-seam connectivity, all four joint families, new-URDF rest-pose
readback and a collision missed by simultaneous diagonal motion but detected by
combined sampling. Use `scripts/verify_local_capabilities.py` for a fresh stdio
MCP/background-worker acceptance run and artifacts. A recipe marked ready means
its tools are bound, not that an arbitrary input or physical product has passed.
