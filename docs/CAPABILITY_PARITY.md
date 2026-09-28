> 中文：[zh-CN/CAPABILITY_PARITY.md](zh-CN/CAPABILITY_PARITY.md)

# Product Acceptance Baseline: Task Scope and Definition of Done

> This document is about task scope against commercial products, not about host parity. For
> which capabilities work on which host (Codex desktop vs. the browser page any MCP client
> including Claude Code opens), see the host support tables in
> [docs/SCENE_EDITING.md](SCENE_EDITING.md#host-support) and [docs/DIRECT_PART_CHAT.md](DIRECT_PART_CHAT.md#host-support).

**2026-09-22 re-review**: the current 27 task templates have all passed a local smoke test; the full evaluation record is kept in the author's private project records and is not published with the public repo. The template count does not equal the number of fully covered tasks.

**2026-09-22 product-direction addendum**: the workbench needs to support day-to-day model inspection and the comparison/evaluation of pipelines such as WaveAB, letting AI read state, act, gather evidence, and verify the way it writes code. Comparable external products are a capability reference, not a limit on this scope. The observation tools already implemented and the guidelines that follow are in [AI Workbench](AGENT_WORKSPACE.md).

**Same-day Rodin Agent research, first batch implemented**: material-region/base-color texture editing, generating interior cavities and lids on solids, rebuilding from frozen source parameters, locally extending between existing cross-sections, and hinge angle/frame-count and preview-speed control are wired up. A real 499,980-face generated tissue-box machining pass and a manual gap-change rebuild both took about 2.3 seconds. Applicability, verification, and remaining gaps are in [Continued Editing of Generated Assets](GENERATED_ASSET_EDITING.md); automatic semantic parameterization of arbitrary meshes, texture preservation across boolean machining, and a general CAD feature graph are still not implemented.

Implementation status updated 2026-09-22; on 2026-09-21 the user made it explicit: the user tasks and output capability of mainstream commercial 3D-generation-style workbench products is the product baseline.
The existing editing tools, print module, and 17 recipes are part of what has been implemented, not the final scope.
The author's own research repo is a source of reusable implementations, historical examples, and quality evidence — it is not used to narrow the product scope.

## Benchmark and definition of done

The capability target is set against commercial 3D-generation-style workbench products, covering three tiers — base tools, skills, and workflows — plus desktop interaction.
These capabilities are organized by tier; the same implementation may cover multiple entry points, so the tiers cannot simply be added up and claimed as a count of independent product features. The comparison catalog also does not mean every workflow listed has actually been verified to succeed.
Future versions need incremental reconciliation. This document does not claim the current workbench has reached capability parity.

Acceptance is measured per complete task: given an input and a user requirement, the workbench performs the operation and delivers an artifact that can be opened, continued to be edited, and meets the requirement.
Each record captures the same input, output constraints, human intervention, quality conclusion, total time, agent usage, service cost, and retry count.
A tool merely existing, a recipe being selectable, a research script passing, or a command succeeding — none of these alone marks the item as done.

## Task scope to cover

| Capability family | What the user can accomplish | Current workbench state and gaps |
|---|---|---|
| Generation and service processing | Text/reference-image to image, single/multi-view image-to-model generation, texturing, relief, and other mesh services; pick a result and keep editing | Asynchronous tasks, Meshy/Tripo BYOK, and a generic contract adapter are wired up; mock-HTTP recovery has been verified, real accounts are not yet configured. Image generation can reuse host capabilities; no new paid service was added |
| Procedural and parametric modeling | AI builds a model, shell, cavity, loft, thread, container, lamp, or other product from an image/dimensions; keeps an editable project | Blender/Python execution, CadQuery/OCP, and project/render/STEP recovery are wired up; containers, hinges, and CAD shells/extrusions/revolves have actually run. Each product category still needs case-by-case quality acceptance |
| Mesh and appearance processing | Inspect, repair, smooth, decimate/retopologize, UV-unwrap, bake, texture-preserving local edits | 196 historical assets pass regression; UV, baking, locally shape-preserving smoothing, and face-region splitting are wired up. Real face-model decimation in Blender is free of open edges/non-manifold geometry; the static editor's own decimation can still be rejected by the quality gate for that case |
| Part splitting and assembly | Get parts from a whole model/reference image, manually trim seams, add pin holes/snap-fits/joints, test coupons, tolerance and assembly checks | Face-region/explicit-label splitting, the interface test-coupon method from the author's research repo, and explicit-motion-sample interference checks are wired up; there is still no automatic guarantee of semantic correctness, and no automatic end-to-end path from an arbitrary model to a manufacturing interface |
| Portrait and character-specific processing | Local facial-feature repair, template fitting, low-poly heads, hair cards, identity and surface preservation | Local smoothing, template Shrinkwrap, and explicitly guided hair-card generation are wired up; automatic keypoints, identity preservation, donor blend seams, and the full character pipeline are still not validated |
| Skeleton, skinning, and animation | Rigging, weight repair, action retargeting, multi-clip handling, collision/grounding checks, animation-asset export | New standalone animation tasks and preview added; rigging/weighting/explicit-bone-name retargeting and GLB clips have actually run; general motion naturalness, grounding, and self-collision constraints are not done |
| Scene, rendering, and interactive output | Multi-asset scenes, offline rendering, dioramas/memory spaces, playable games and showcase pages, returning an editable project and an experience entry point | Scene projects, real offline rendering, and animation/hotspot/walkthrough web pages already exist; browser interaction has been verified. General games and per-category scenes still need concrete-content acceptance; no website has been published |
| Manufacturing and delivery | Print kits, color separation, plate layout, process selection, test cuts, 3MF/slicer handoff, laser cutting, reproducible delivery packages | Printing, SVG layering, and interface test coupons are usable; damage detection on Bambu-project read-back has been verified and the original geometry's 3MF is kept. Automatic multi-color assignment, complete per-category kits, and physical-object verification still have gaps |

Work such as deploying a dedicated service or publishing a web page can use host capabilities, but delivery must go through a workbench task and its result must be verified — a host theoretically being able to write code does not by itself count as passed.

## Three execution modes share one workspace

1. **Explicit small operations**: a human completes them directly with selection, buttons, and parameters; AI calls the same operation, using the same state, undo, and version checks.
2. **Open-ended modeling and complex editing**: an agent uses a full tool environment such as Blender/CAD, composes existing algorithms, and writes modeling code per task; the workbench receives the project, preview, run status, and traceable artifacts.
3. **Generation and specialized processing**: executed through service adapters, with unified handling of credential references, task state, cancellation, results, and consumption info.

All three connect around the same task and asset version. Users can click, adjust, preview, and take over at key steps, without having to translate every change into natural language.
There's no requirement to hard-code a dedicated set of buttons for every category; complex workflows reuse underlying capabilities and methods, and common deterministic operations get a shortcut UI.

## Implementation and acceptance order

1. Fix existing geometry-fidelity issues; establish trustworthy project saving and output read-back checks.
2. Add general execution and artifact-recovery capability: Blender/CAD projects, rendering, and asynchronous tasks. This lets open-ended modeling happen inside a unified workspace.
3. Integrate generation/processing services and the part-splitting, interface, joint, and texturing capabilities already in the author's research repo, each offering both AI invocation and necessary manual controls.
4. Accept complete pipelines against user tasks, covering modeling, assembly, character animation, scenes/games, and manufacturing delivery. This order does not narrow the final scope.

Acceptance status is one of: not reconciled, not integrated, integrated pending acceptance, passed, has defects. Each item is attached with actual artifacts and evidence, avoiding the use of unit-test counts as a stand-in for product completeness.
Prefer reusing the author's own implementations of known provenance, open-source libraries, and legitimate services; the specific implementation does not need to match any particular third-party product.

## Where the existing evidence stands

[Historical model replay](history/HISTORICAL_REPLAY_20260921.md) is evidence of basic operations and known defects, not a capability-parity conclusion.
[v0.6 implementation](WORKBENCH_V06.md) describes the current product; [original scope planning](history/WORKBENCH_SCOPE.md) preserves the code provenance and historical implementation background.
The code and evidence delivered this round are in [Task Workspace](WORKBENCH_TASKS.md) and [Validation Record](history/VALIDATION_20260922.md). Executable low-level tools are not treated as equivalent to every workflow's finished product having passed.
