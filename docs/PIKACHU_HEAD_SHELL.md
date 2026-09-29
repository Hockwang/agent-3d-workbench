[简体中文](PIKACHU_HEAD_SHELL.zh-CN.md) · [Back to README](../README.md)

# Pikachu head shell: local fabrication from an existing model

This is the custom v6 case from 2026-09-23. A general-purpose agent took an existing
character model, worked locally on the cavity, front/back shells, accessories and
magnet mounts, then used the workbench to observe, inspect and save an editable project.
This fabrication workflow needs no DiT or hosted 3D-generation API. It does not
include generating the input character model.

## The assembled model and its internal structure

| Assembled | Inside the two shells | Magnet mount section |
| --- | --- | --- |
| ![Assembled Pikachu v6](assets/pikachu-head-shell/assembled.png) | ![Rear cover on the left, front shell on the right, with cavities and overlapping tabs](assets/pikachu-head-shell/opened-magnet-tabs.png) | ![Magnet mount section](assets/pikachu-head-shell/magnet-section.png) |

All three images render the delivered meshes. The open view shows the rear cover
on the left and front shell on the right. Grey blocks in the section are magnet
placeholders, excluded from the printed-part count. Processing marks remain visible
on the inner walls and seams; human appearance acceptance is still pending.

## What this case demonstrates

1. **Build a cavity around declared dimensions.** Use a 600 mm head-circumference
   envelope rather than infer someone's measurements from a photograph.
2. **Preserve the exterior while separating parts.** Front shell, rear cover,
   yellow ears, black ear tips, eyes, highlights, cheeks and nose total 13 parts.
   The round eye outlines and closed smile remain; eye lattices and highlights are separate.
3. **Iterate against a structural reference.** v6 replaced end-face magnet mounts
   with overlapping tabs extending from the front shell. The rear cover slides
   over them and magnets face pockets on its inner wall. The other 11 accessories
   are byte-for-byte identical to v5.
4. **Inspect and deliver.** Save a colored GLB, 13 STL parts, an editable project
   and inspection records bound to the specific version.

| Design item | Case parameter |
| --- | --- |
| Declared head circumference | 600 mm; actual head shape, eye positions and padding need calibration |
| Exterior including ears | Approximately 400 × 306.49 × 417.63 mm, width × depth × height |
| Magnets | Six pairs: twelve Ø10×2 mm magnets, not printed parts |
| Pockets | Ø10.2×2.2 mm; at least 2 mm of floor material and a 2.2 mm side-wall design value |
| Interfaces | 0.4 mm magnet face gap; 0.25 mm tab clearance allowance |

## Recorded digital checks and remaining work

These results come from this delivery's verification records. While preparing this
page, the GLB and all 13 STL SHA256 values were checked against those records. The
model was not regenerated and assembly sampling was not rerun for this documentation update.

| Check | Recorded result |
| --- | --- |
| Part meshes | All 13 single-component, watertight and positive-volume; workbench readback found zero boundary or non-manifold edges |
| Declared head envelope | Zero intersection with every part; applies only to the specified ellipsoid |
| Accessory assembly | 1,333 discrete poses passed; not a continuous collision guarantee |
| Shell removal | 61 poses from 0 to 30 mm in 0.5 mm steps, without interference |
| Magnet insertion | Each of 12 magnets sampled along its installation axis from 0 to 25 mm in 0.5 mm steps, without interference |
| Sightline | **`forward_blocked`: the yellow face shell still blocks forward vision from the provisional eye points** |
| Physical validation | Not split for a printer bed, sliced, printed or worn; magnet retention, adhesive strength, tolerances and ventilation remain unverified |

GLB SHA256: `427845497cfe5263060a3b8da12c5c822e9005bdc05ae90d7349fb128396891f`.
Images match the original delivery; see [image provenance and hashes](assets/pikachu-head-shell/README.md).

## Start your own head-shell task

The public plugin includes the [base head-shell workflow](HEAD_SHELL.md) and an
[older 11-part parameter example](../examples/head-shell/README.md) bound to one source SHA.
The **13-part v6 design and its Ø10×2 mm overlapping magnet mounts were custom work
and are not included in the current built-in template**. The old parameters are
not a reproduction script for this showcase.

Provide your own source model and ask your agent:

> Make a head-shell design draft from my character model. First inspect its orientation,
> dimensions and parts, and confirm which exterior features must be preserved. Use a
> 60 cm circumference as an initial design assumption. Plan the front/back shells,
> accessories and connectors; adapt local structures to this actual model. Save a
> separate version and report watertightness, cavity clearance, assembly paths,
> sightlines and unverified items separately. Show the exterior and inside in the
> workbench. If sightlines conflict with the character's appearance, explain the
> conflict instead of marking the design ready to wear.

The source STL, GLB and project archive are not included in this repository. This
page demonstrates a workflow and the limits of digital checks. For a directly
reproducible bundled model, start with the [five-part README tutorial](../README.md).
