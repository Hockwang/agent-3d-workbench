# Continuing to edit a generated asset: first batch and next steps

> 中文：[zh-CN/GENERATED_ASSET_EDITING.md](zh-CN/GENERATED_ASSET_EDITING.md)

2026-09-22. The user asked us to evaluate whether the capabilities surfaced by "researching Rodin
Agent's features" could be added to the workbench. Initial capability baseline: `edf8222`; the
user then asked to "add the feature first." This first batch reuses the existing project and
background-task machinery; it does not migrate the project schema.

## First batch shipped

| Capability | Human entry point | AI entry point and result |
| --- | --- | --- |
| Precise material regions | Model Edit → Appearance → Material Regions | `objects[].materials`; `studio_edit` material's `ids` + `material_slots`, changes only the specified parameters |
| Base-color texture replace/remove | Appearance → pick image → apply material | `base_color_texture` local image path / null; valid UV, preserves alpha, normal, and other channels; supports undo, project save/reopen |
| Generated-model feature machining | Modeling & Tasks → Generated Model → adjustable interior cavity and lid; optional current-selection checkbox | `generated-container` template; interior dimensions/position, wall thickness, locating lip, clearance, opening; delivers body/lid STL, GLB, and an inspection report |
| Parametric rebuild | Task Log → modify parameters → generate a new version | `studio_task({action:"rebuild",id,params})`; four templates record parameters, freeze the input, and the source task, and rebuild from the original input each time |
| Local dimensioning | Modeling & Tasks → Local Dimensions · shape-preserving stretch | `local-dimensions`'s `axis`/`start_mm`/`end_mm`/`delta_mm`; the front side stays fixed, the back side translates rigidly, and the middle stretches linearly |
| Animation control | Open/close angle and frame count for a hinge motion sample; preview playback speed | Changing `hinge`'s `angle_deg`/`frames` changes the exported animation; 0.25–4x playback speed only affects the preview, and time position does not shift with the speed multiplier |

Rebuild supports `container`, `hinge`, `generated-container`, and `local-dimensions`. Rebuild is
rejected if the original input, script, or implementation fingerprint fails verification; after an
implementation upgrade, a task must be resubmitted as a new source. The project archive saves the
edited asset; the current first-batch parameter history is stored in the task directory and is not
yet packaged into the `.3dworkbench` as a CAD feature graph.

### Verified so far, and limits

- Materials: single-slot edits preserve the unselected slot / original alpha / UV / normal map;
  base-color replace, save-and-reopen, undo/redo, and rollback on an invalid slot all pass. On a
  two-object interface, an actual test changed only the ear-cushion roughness from 0.4→0.8 while
  the shell stayed at 0.4. GLB multi-primitive meshes are usually split into objects; addressing
  follows the post-import object/material-slot structure and does not promise to preserve an
  arbitrary source's slot hierarchy.
- A real Hunyuan tissue-box case: 499,980 faces, geometry converted to millimeters/Z-up by the
  existing pipeline. 180×110×80 mm interior envelope, 2.4 mm wall thickness, 4 mm locating lip,
  100×30 mm top opening. The AI built the 0.4 mm clearance version in about 2.33 seconds; a human
  changed the clearance to 0.6 mm in the UI and rebuilt in about 2.32 seconds; the original input
  hash matched, the old artifact was kept, body/lid were each a single closed solid, and STL
  export/read-back passed. All four envelope/interference-volume figures in the report were 0.
- Fixed a geometry issue exposed by a real case: `source - (source ∩ lower_box)` produced
  zero-volume slivers on high-face-count coplanar surfaces; switched to Manifold's
  `split_by_plane` instead of loosening the connectivity check or discarding genuine fragments.
- The machining template requires a single static closed solid; it only checks the wall-thickness
  envelope around the full rectangular cavity, not other thin details on the source surface. Output
  is single-color; textured/multi-color input requires explicit opt-in. Not verified by an actual
  print.
- Local stretch was verified on a four-cross-section model with base-color/normal maps: the middle
  section was lengthened 10 mm, the front side stayed fixed and the back side translated, and
  face order/UV/textures were preserved; the control plane matches GLB float32 precision. A
  request is rejected if any control plane passes through a triangle; semantic region recognition
  and free-form deformation cages are not implemented.
- Real Blender test with a 60°/48-frame hinge: reading the project back shows an intermediate
  frame of 60.000002°, and the GLB animation previews in the workbench; the animation preview is
  not treated as joint-collision or manufacturing acceptance.
- Verification: 277 non-device Python tests passed (2 real-device tests not run), 52 frontend
  tests passed, the offline app build passed; after adding the implementation-fingerprint check,
  the related 12 Python tests passed, and the final real tissue-box build/rebuild took 2.58/2.59
  seconds respectively, with the inspection still all-zero.
- Local verification records are at `~/test/claude-blender/runs/generated-editing-20260922/`; they
  are not an install dependency. No paid generation service was called.

The rest of this document keeps the original evaluation, which describes a broader goal; the first
batch of features should not be read as achieving the whole goal.

## Conclusion and product experience

Worth building. The point is to leave a generated result with materials, local shape, and
functional-structure parameters that stay editable afterward.
The source model can come from any generation service, a user import, or procedural modeling; the
editing capability is not tied to Rodin.
A human picks a part and adjusts values; the AI reads the same selection, parameters, and version
and calls the same operations.

For example, after selecting a tissue box the user says "widen the interior by 10 mm, keep the
face unchanged, and loosen the lid a bit." The workbench should show the interior dimensions, the
machining region, the protected region, and the clearance; preview the change, run the inspection,
confirm to apply, and support undo and continued editing after saving. "Just make the eyes black"
must be scoped to the eye object or material region, and must not change a same-named or shared
material on the body.

## Capabilities and gaps from the first evaluation (pre-implementation baseline)

| Researched capability | Currently confirmed foundation | What's needed | Suggested order |
| --- | --- | --- | --- |
| Material-region editing | `studio/core/editor.py`'s material operation supports PBR color, roughness, metalness; `studio/web/editor.js` already has an appearance page | Enumerate and select material slots; edit precisely by object and material slot; read out the current value; preserve unselected regions, UV, textures, and other channels | 1 |
| Texture swap, material enhancement | Existing GLB texture preservation, Blender materials, and the `texture-bake` template; the service adapter layer has retexture-related operations | Local texture selection, mapping/scaling, channel management, and undoable replacement; explicitly bake for procedural material export, bill service retexture separately | 1, follow-up |
| DIT appearance + parametric functional structure | The author's research repo's tissue-box case uses Manifold to build the cavity, cut the lid, the locating lip, the opening, tab slots, and real lettering; the plugin already has Manifold, Blender, CadQuery/OCP | Extract the case's parameters into rebuildable machining features; record the source asset, coordinates, machining/protected regions, dependencies, and inspection results | 2 |
| Local dimension control | Currently has whole/object transforms, local smoothing, template fitting, and Blender script tasks | Nameable control regions, anchors, direction, and protected regions; support both procedural-feature rebuild and explicit region mesh deformation separately; whole-object scaling must not pass as local adjustment | 3 |
| Animation presets and motion control | Already has hinge/rotation templates, rigging, weight repair, retargeting, animated GLB preview; the observation area supports URDF pose evidence | Parameter controls bound to joints/actions; named presets, speed/range, state saving, and export consistency; naturalness and collision are accepted separately | 3 |
| Input understanding and modeling-path selection | Codex can understand reference material and organize existing generation, Blender/CAD tasks | Record the reference material, units, constraints, and chosen method into the task; the result should leave editable controls and verifiable artifacts | Cross-cutting |
| Rodin generation and BANG | Codex currently has the 7 official Hyper3D MCP tools loaded | After downloading a result, bring it into the workbench as an asset and task source; a formal service adapter is still needed if a human is to call it directly from the task panel | Can be integrated independently |
| URDF/manufacturing delivery | Already has URDF observation and print prep; CAD tasks can deliver STEP | Joint editing and export, geometry and motion checks, manufacturing/assembly acceptance; a web-page export checkbox must not stand in for a quality pass | Per-task acceptance |

The current `material` operation iterates over all materials on the selected objects. Multiplying
color with the original base-color map is not the same as generating a wood-grain texture or
swapping a texture.
Existing templates such as `container` accept parameters and store the task input, but that is not
the same as editing an existing feature dependency in a project, changing a parameter back, and
automatically rebuilding.

## Reuse approach and engineering trade-offs

Reuse the existing `studio_edit`, task executor, immutable assets, version-conflict checks,
artifact recycling, and observation evidence.
Precise material-slot editing can be extended inside the existing edit operation; we are not
building a dedicated panel for every competitor demo.

For the parametric part, we recommend a general "editable control" abstraction: name, unit, valid
range, current value, target object/region, anchor and dependencies, build method, and
verification method. The agent creates controls for a specific model, and the frontend generates
the usual widgets from them.
This persistence design touches the project schema and needs a separate compatibility decision
before implementation; this document does not freeze field names or the execution protocol.

- **Precise functional structure**: reuse Manifold/CadQuery/Blender, rebuilding from the immutable
  source model and parameters; the cavity, lid opening, holes/slots, lettering, etc. are
  recomputable features. Fail explicitly when the source shape can't fit the request, rather than
  silently stretching the whole object.
- **Local shape adjustment**: models with a construction history modify the construction
  parameters; plain meshes go through explicit regions, a skeleton, or a deformation cage. Each
  path discloses its applicability and must not claim to have recovered CAD history that never
  existed in an arbitrary DIT mesh.
- **Materials and appearance**: reuse PBR, Blender nodes, and existing baking; material parameters,
  texture replacement, and generative retexturing are recorded separately. After a topology change,
  re-verify UV, material slots, and region bindings; if old face indices are no longer valid, do
  not silently keep editing.
- **Lightweight interaction**: dragging a parameter only produces a merged preview; expensive
  boolean/baking operations go to a background task, computed once the adjustment stops or Apply
  is clicked. A stale result must not overwrite newer parameters, and the completed window-resize
  optimization must be preserved.

## First-batch full acceptance tasks

1. **Multi-material model**: change only the ear-cushion or eye material. Compare against the
   unselected material, textures, and geometry; save-and-reopen, undo/redo, and re-import after
   GLB export all give the same result. Cover shared materials, duplicate names, and invalid slots;
   a failure must keep the original project intact.
2. **Generated tissue box**: reuse an already-frozen generation source, explicitly specifying the
   interior envelope, lid-cut plane, and protected region. Modify the interior width, the opening,
   and the lid clearance separately, rebuilding from the original source each time; verify the
   envelope, the local wall-thickness inspection range, static interference, the protected-region
   surface, and export/read-back. At least one out-of-range request should fail and keep the
   previous version.
3. **Local dimensioning and animation**: pick a procedural house or mechanism, modify one part, and
   verify the anchor, protected parts, and related-component relationships; preview pose should
   match export/read-back. Verify the mesh-deformation path separately on a generated model — a
   procedural house passing does not stand in for an arbitrary mesh passing.

Each covers human operation → AI reads → AI modifies → human continues adjusting, recording actual
time spent, retries, and service cost.
Digital inspection does not replace post-print assembly, retention-force, and functional
acceptance.

## Hyper3D integration boundary and sources

As of 2026-09-22, the actual MCP list for the authorized account includes `rodin_generate`,
`rodin_create_uploads`, `rodin_import_images`, `rodin_generate_bang`, `rodin_get_status`,
`rodin_wait`, and `rodin_get_result`.
We re-checked the current tool catalog this time; all 7 are present; no new paid task was
submitted.

That MCP's BANG input is a Rodin generation ID, with no arbitrary external-model upload parameter;
this differs in scope from the full HTTP API.
The MCP does not expose the material editing, local-dimension parameters, or animation interface of
the web Agentic Mode.
So integrating the MCP can only add the services it actually publishes; it cannot directly gain
the full editing capability shown in the web demo.
We keep the already-authorized Codex connection; we do not copy OAuth credentials into the plugin
config, and we do not revive the default BANG production route deprecated in the research repo.

Sources:

- Codex task "researching Rodin Agent's features": `01a0c6eb-cd28-7cf2-804d-cf901e12e84d`,
  including the user-pasted article, GIF analysis, public-case observations, and the actual MCP
  check.
- Local verification records: research and testing evidence produced during development, kept in
  the author's own research repo; not shipped with this repo and not an install dependency.
- Digital prep for the tissue-box case is complete, but an equipment homing fault caused a
  cancellation before the first layer; this should not be recorded as a physical print with
  functional acceptance passed.
- Current implementation: `studio/core/editor.py`, `studio/web/editor.js`,
  `studio/core/task_templates.py`, `studio/core/blender_catalog.py`, `studio/core/tasks.py`,
  `studio/adapters/services.py`.

A general feature-dependency graph, semantic protected regions, free-form deformation of an
arbitrary mesh, procedural-material baking, a Rodin-panel service adapter, and general joint
editing remain out of scope for now.
