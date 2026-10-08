> English: [../THIRD_PARTY.md](../THIRD_PARTY.md)

# v0.6 几何与界面复用来源

| 依赖 | 锁定版本 | 用途 | 许可证 |
| --- | --- | --- | --- |
| Three.js | 0.185.0 | 渲染、OrbitControls、TransformControls、GLTFLoader | MIT |
| Trimesh | 4.12.2 | 场景导入导出、变换、几何检查、组件拆分、小洞修复 | MIT |
| Manifold / manifold3d | 3.3.2 | 实体平面切割、并集/差集/交集 | Apache-2.0 |
| fast-simplification | 0.2.0 | Trimesh 调用的 quadric 减面内核 | MIT |
| Pillow | 12.3.0 | glTF 内嵌贴图读写 | MIT-CMU |
| NetworkX | 3.6.1 | Trimesh 修复使用的图操作 | BSD-3-Clause |
| lxml | 6.1.3 | Trimesh 的 3MF XML 读取依赖 | BSD-3-Clause（wheel 内附其依赖许可） |

Python 精确依赖以 `uv.lock` 为准；前端以 `package-lock.json` 为准。NumPy、SciPy 与 MCP 等原依赖继续沿用各自包内许可。

2026-09-23：预览与离线交付新增 Three.js r185 的 DRACOLoader/KTX2Loader、Meshoptimizer、Draco/Basis WASM、ktx-parse/zstddec。完整许可与构建说明在 `studio/web/vendor/CODECS-NOTICES.txt` 及同目录 LICENSE 文件；npm 锁版本不变，decoder 不依赖 CDN。Aholo-Lux3D 仅作为接口和能力对照，未复制其业务代码；契约固定到 `71779ccd8290e999d980621439c728524830f422`。

Three.js 的 GLTFLoader、TransformControls、BufferGeometryUtils、SkeletonUtils 直接取自 npm `three@0.185.0/examples/jsm/`，与已有 r185 内核配套。
未修改官方插件源码；发行副本在 `studio/web/vendor/addons/`，MIT 声明保留在 `studio/web/vendor/THREE-LICENSE.txt`。
安装使用已打包的 HTML 和 vendored 模块，静态编辑不要求 Node.js；动作编辑验证/导出新增依赖本机 Node.js 20+（已打包 worker，无须 npm install）。Python 依赖从锁文件安装，各 wheel 自带许可证。

参考：[Three.js GLTFLoader](https://threejs.org/docs/pages/GLTFLoader.html)、[Manifold](https://manifoldcad.org/docs/html/classmanifold_1_1_manifold.html)、[Trimesh](https://trimesh.org/)。

本轮未搬入作者研究仓库中的 模型研究 fork 或第三方私有源码；作者研究仓库中的切割和工作流实验用于识别操作边界与验收条件。
本项目自有代码采用仓库根目录 `LICENSE` 中的 MIT 许可证。第三方依赖保留各自许可证与声明。

## 2026-09-22 新增复用

- CadQuery 2.8.0（Apache-2.0）及其 OCP/OpenCascade 内核：精确实体、STEP/STL。
- Shapely 2.1.2（BSD-3-Clause）：截面二维几何；具体版本以 uv.lock 为准。
- Blender 5.1.2（外部安装，GPL）：通过后台进程调用其公开 bpy 操作，不把 Blender 二进制放入源码仓。
- 作者研究仓库/自有 mechanical_joints：拷入独立小型内核，出处与 SHA256 见 `studio/core/kernels/SOURCES.json`，不隐式导入其他仓。
- 离线网页复用现有 Three.js / GLTFLoader / OrbitControls；构建产物由 scripts/build_delivery.mjs 生成。
- Meshy/Tripo 为自备账户的公共 API 适配；没有复用任何第三方产品的私有代码、凭据或专属服务。

## 模型观察

yourdfpy 0.0.60（MIT）用于 URDF 解析、link 图和正向运动学；通过锁文件分发依赖，不复制任何第三方产品的私有实现。上游文档：https://yourdfpy.readthedocs.io/en/latest/api/yourdfpy.html 。适配层关闭网格自动处理，避免观察工具隐式焊接/修复被测几何；实际模型和 mesh 文件指纹保留。

## 统一工作台 UI

- [Pico CSS](https://github.com/picocss/pico) 2.1.1，MIT：复用原生 HTML 表单、select、details 和焦点样式。放在低优先级 CSS layer，工作台统一皮肤负责密度、色彩与模型视口布局。
- [Lucide](https://github.com/lucide-icons/lucide) / lucide-static 1.47.0，ISC（包内同时保留派生图标说明）：仅打包使用的 15 个 SVG，不引入图标运行时。
- IBM Plex Sans（@fontsource/ibm-plex-sans 5.3.0），SIL OFL 1.1：本地打包 400/500/600 三个字重的 Latin WOFF2，中文使用系统已有中文字库。

构建入口 `scripts/build_ui_assets.mjs`，发行资产与完整许可证在 `studio/web/vendor/ui/`。MCP App 将字体内嵌为 data URI，图标为静态 SVG；没有字体 CDN、外部图标请求或新增持续 JavaScript 动画。

## 2026-09-23 动作编辑

- jsep 1.4.0（MIT）：公式 AST 解析。Studio 只解释数字、参数与白名单数学运算，不运行用户 JS。声明在 `studio/web/vendor/JSEP-LICENSE`。
- JSZip 3.10.2（选择 MIT 许可）：MotionForge ZIP 导出。声明在 `studio/web/vendor/JSZIP-LICENSE`。
- MotionForge 的 `KeyframeManager`、`ResultPackageExporter`：MotionForge 是插件作者自己的项目，公开在 https://github.com/Hockwang/MotionForge（本仓库内的文件对应 commit `18a11fe`），随本仓库一起以同一许可证发布；见 LICENSE。锁定 commit、原文件及本地修改后 SHA、三项补丁见 `studio/web/vendor/motionforge/SOURCES.json`。
- 能力目标参照商用同类产品设定，仅作只读能力对照，没有复制其私有工作流、代码或提示词。本地绑骨继续使用自有工作流与外部 Blender。
