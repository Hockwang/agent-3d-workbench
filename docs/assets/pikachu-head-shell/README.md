# Pikachu case image provenance / 图片来源

These PNGs are unchanged renders from two local deliveries. They were copied
byte-for-byte from the respective `delivery/previews/` folders and checked against
each delivery's `manifest.json`. They were not generated or retouched for the README.

四张 PNG 直接取自两个版本的本地交付，逐字节复制并核对各自的原交付清单；
没有为 README 另行生成或修饰模型效果。拆件展开、两半壳内侧和剖面是检查视图；
剖面中的灰色磁铁是占位件。

| Version / 版本 | Delivery / 交付 | Files / 图片 |
| --- | --- | --- |
| v6 · 2026-09-23 | `pikachu-overlap-magnets-20260923` | `assembled.png`, `opened-magnet-tabs.png`, `magnet-section.png` |
| v5 · 2026-09-22 | `pikachu-helmet-reference-20260922` | `previews/exploded-iso.png` → `v5-exploded.png` |

| File | Bytes | SHA256 |
| --- | --- | --- |
| `assembled.png` | 795283 | `b30fb6225e36a2ce57e19105bd378df5fe809870c2178d65ba615af3adb4110f` |
| `opened-magnet-tabs.png` | 825132 | `0c5e48bb204d5536b3f1d481f78d4b781efd16225787c94ed95ad77be7a90b68` |
| `magnet-section.png` | 724057 | `e0f48e235f4deca36b54a4112ffbb2e6a5793aa252e7eb3034631e44033f2b79` |
| `v5-exploded.png` | 800795 | `73d47dd7460ecae47e7504f9ef830b58d69fbf2a7a26e5ce265640fe41e6026c` |

The v6 assembled GLB is bound by SHA256
`427845497cfe5263060a3b8da12c5c822e9005bdc05ae90d7349fb128396891f`.
The v5 assembled GLB is bound by SHA256
`108d63aef45c4330dddf337e22f9594af7ac447691ce4cab9b8fabbd27461069`.
The v5 exploded render shows the 13-part layout before the v6 magnet-mount correction.
All 11 accessory STLs are unchanged between those versions; the two shells differ.

v5 展开图展示 13 件的布局，不能当作 v6 磁吸结构的图。两版的 11 个附件 STL 字节相同，
两半壳不同。

This folder contains documentation images, not source geometry or a reproduction kit.

See the [English case study](../../PIKACHU_HEAD_SHELL.md) /
[中文案例](../../PIKACHU_HEAD_SHELL.zh-CN.md) for the recorded checks and outstanding
sightline, print and physical-fit validation.
