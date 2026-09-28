> 中文：[zh-CN/HEAD_SHELL.md](zh-CN/HEAD_SHELL.md)

# Built-in workbench capability: character head-shell fabrication

2026-09-22. Scope is "existing character model -> adjustable head-shell draft". Built on the
workbench's existing recipes, task templates, and observation; no separate personal Codex skill
and no extra per-user recipe copy are added.

## Entry point and implementation

`recipes/wearable-head-shell/recipe.json` and `guide.md` provide the built-in flow;
`studio/core/head_shell.py` is the parametric template, `head_shell_audit.py` checks assembly,
`head_shell_vision.py` generates the local eye mesh/smile vents, and `head_shell_sight.py` checks
the declared eye points. `scikit-image` is a dependency of the interior-wall voxel reconstruction.
`head_shell_audit.py`'s geometric core is now a standalone function, `audit_parts`, also exposed as
the `removal-audit` task template so any set of watertight STL parts (not only a head shell) can get
the same discrete removal/assembly-order check.

Once the recipe is enabled the workbench opens the generation template, and the six checks are
shown separately. The source/result observation comparison is created from the currently
generated, already-registered artifacts. A task's "edit parameters" rebuilds from the frozen
input and keeps the old version; the previous version's human appearance review does not carry
over to the new version.

`studio/core/task_recipe_progress.py` binds progress to a task ID, a check report SHA, and an
observation asset SHA; missing evidence, a version mismatch, a failure, or a modified artifact can
never show as complete. A human "good" review represents only appearance confirmation, and the AI
review is kept separate. If the attached recipe record fails after a task successfully starts, the
response returns a warning rather than misleading the caller into starting again.

It continues to use the v0.7 `workspace_id = the current Codex task ID` isolation mechanism; it
does not modify any other task or legacy project.

## Parameters and protection conventions

The input must be a single static, closed, positive-volume model; the template does not repair it
implicitly. Z is up, the face points -Y. After scaling to the total width, centering in XY, and
zeroing the bottom, every local point uses millimetres. Head circumference is a declared
approximate envelope input and must not be treated as an actual measurement of eye position.

`preserve_eye_outline=true` by default rejects `extension_outline_xz_mm`. The eye mesh keeps a
margin inside the original eye; the white highlight stays an independent piece. An eye-shape
conflict must be reported back first — the character's expression must never be changed just to
pass the sightline check automatically. The mouth shape/ventilation position require explicit
parameters; there is no generic facial-semantic recognition.

Source colour components are treated as closed connected components; names, colours, the eye mesh,
and local coordinate schemes are all bound to the source SHA. STL carries no original colour
information — colour is an explicit component plan. Texture loss requires explicit
`allow_material_loss`. The template's preset 600 mm head circumference and O6x3 mm magnets are only
adjustable starting values.

## Evidence and maturity

The report keeps watertightness/assembly, the head envelope, sightline, and physical fit separate,
and `wearable_ready` is fixed to false. Passing geometry does not mean it is wearable by an actual
person. Both the assembly path and the sightline are sampled with a finite number of samples; local
minimum wall thickness, ventilation volume, padding comfort, and magnet retention have not yet
completed physical verification.

`inspection/` holds check assets and must not be mixed into the printable BOM. The primary model is
the root `scene.glb`; the primary STLs are the root-level parts.

The Pikachu case: 60 cm, 4 pairs of O6x3 mm magnets, 11 parts; the full round eyes and closed mouth
were restored, with the mesh hidden inside the original black eye. The provisional eye points are
still blocked by the yellow face shell, so the sightline stays unresolved. Case parameters are in
`examples/head-shell/pikachu-round-eyes.json`; they must not be extrapolated to any other character
or used directly as a final wearing dimension.
