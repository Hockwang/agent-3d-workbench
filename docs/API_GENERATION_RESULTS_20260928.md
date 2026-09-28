# API demo verification / API 演示验证 · 2026-09-28

## Shared-image comparison / 同图对照

Read the complete tutorial in [English](CUP_COMPARISON.md) or [简体中文](CUP_COMPARISON.zh-CN.md).
Both routes used the same independently generated image, then real stdio MCP tasks
and edits. 两条路线使用同一张独立生成的参考图，并通过真实 stdio MCP 执行任务与编辑。

- Local: 4 authored parts, 41,710 faces; all watertight after geometric welding.
  本地构建四件，均水密，尺寸与遮挡处内腔是设计假设。
- Hunyuan generation: 1 mesh, 60,000 faces, 211.88 s including collection.
  Hunyuan Part: 2 segments, 1,735,888 faces, 78.56 s.
  生成一次、分件一次，没有重复提交。
- Part separated the handle but left body/lid/knob together, replaced PBR textures
  with segment vertex colors, and left 6 boundary edges per part.
  分件未得到独立杯盖，材质改变，两件均有开边。
- Both routes passed independent handle translation by 25 mm, unchanged-other-part
  checks, undo, GLB export bounds, project save and reopening through MCP.
  两边单件编辑与工程读回都通过；这不是原生 UI 点击验收。
- Gateway amounts: 2.16 for generation, 0 for Part; currency was not specified.
  这些是本次回执，不是公开定价，也不是以后免费承诺。

Evidence / 证据：[JSON report](assets/cup-comparison/report.json),
[model bundle](https://github.com/Hockwang/agent-3d-workbench/releases/download/demo-cup-20260928/cup-comparison.zip).
Original files are preserved. Display scaling is explicit and does not calibrate
real-world dimensions. 原始模型保留；展示缩放不代表测得真实尺寸。未打印、未验收装配或食品接触安全。

Bundle / 模型包：`cup-comparison.zip`, 65,774,648 bytes, 16 entries.
SHA-256: `e89aa90c27c749a00a18924418917ba692e0822fb7e94c99453403823e5f7fad`.
ZIP integrity and every file in the included `SHA256SUMS` manifest were checked.
已检查压缩包完整性及包内每个文件的 SHA-256。

## Earlier connection demonstration / 前一轮接入验证

The [API setup walkthrough](API_GENERATION_DEMO.md) uses a different reference: a
Blender render of the repository's procedural five-part mug. It is a connection and
editing test, not the independent-image comparison above.
前一轮使用程序杯子渲染图，作为接口与编辑验证保留，不混进同图对照结论。

That real Hunyuan run returned a 28,182,272-byte GLB in 259.00 s, with 60,000 faces
and one connected, watertight mesh. MCP import, 0.5× scaling, undo, project save and
export bounds were checked. The gateway's reported amount was 1.92, unspecified
currency. [Sanitized report](assets/api-generation/run-report.json).

**Material limitation / 材质限制:** static import/export retained the decoded pixels
of base-color, normal and metallic/roughness textures, but removed the
`KHR_materials_specular` extension. Image indices were reordered; comparisons were
made by material slot. 静态编辑往返保留了三类贴图像素，但丢失该高光扩展，不能宣称材质完全无损。
The untouched generated GLB remains the source of truth.

## Hi3D and automated checks / Hi3D 与自动检查

Hi3D's new public-API adapter passed live authentication and balance queries, but
the tested API accounts had no credits, so no live Hi3D generation is claimed.
详见 [Hi3D 中文说明](HI3D.zh-CN.md) / [English](HI3D.md)。

Fresh validation for this change:

- Python suite: **718 passed, 2 skipped**, macOS. Includes local HTTP Hi3D multipart,
  token auth, error paths, no-repeat submission, download resume and real stdio MCP
  demo integration. These mocked-provider tests are separate from the real Hunyuan run.
- `make lint` and `git diff --check` passed.
- Frontend suite: **139 passed**, 0 failed (`npm test`).
- After the example runner adjustments: **20 passed** in the focused Hi3D/registry
  suite; the documented local command also completed without a service configuration.
- The two comparison routes additionally ran real task scripts and MCP editing
  assertions on their actual outputs; neither required fake geometry substitutes.
- Original keys, private gateway configuration, raw provider responses and signed
  URLs are excluded from the public bundle. Scans are bounded checks, not an exhaustive
  security audit. Hosted GitHub Actions remains unconfigured, as explained in the
  [initial release verification](RELEASE_VALIDATION_20260928.md).
