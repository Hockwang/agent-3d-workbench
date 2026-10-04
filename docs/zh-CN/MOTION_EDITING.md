# 动作编辑（2026-09-23）

> English: [../MOTION_EDITING.md](../MOTION_EDITING.md)

用户确认 [实施方案](../history/MOTION_EDITING_PROPOSAL.md) 后接入。动作与网格编辑复用同一个
EditorViewport/WebGLRenderer、对象选择和工程。没有嵌套 MotionForge 网页，也不接入第二个 LLM 服务。

## 使用

- 界面默认用于选部件、定位时间、预览和导出；建模、绑骨、动作要求主要在宿主聊天输入。关节、公式、关键帧与清除绑定收在默认折叠的「高级编辑」。手动修改后即使折叠参数，仍显示未保存提示与「保存动作」。
- 顶栏「动作编辑」或 `studio_open(mode="motion")`。选择对象，添加机械关节或导入骨骼 GLB / 运动 ZIP。
- 修改参数/公式即时预览；点击「保存动作」后写入共享工程。时间轴拖动、播放、暂停、循环仅影响预览。
- 机械：旋转/滑动/固定跟随，父子关节，支点、限位，PKF 参数/步骤/缓动或显式关键帧。
- 骨骼：保留原 GLB skins、weights、inverse bind matrices 和 clips；可裁剪源片段/调速，
  或以原始骨骼名编辑局部 XYZ 旋转 PKF。普通 clip 不会自动恢复语义参数。
- 直接在 Codex 聊天中要求绑骨。GPT 读取几何后使用现有本地 `rig-bind`、
  `skin-weights` 或 Blender 脚本；支持附带已打包外部资源的未压缩 `.blend`。不额外调用 GPT API。
- 工程 ZIP 可从全新任务导入继续编辑。机械包含 MotionForge v7 标准核心；骨骼/混合工程
  使用 `studio-motion-package/v1` 扩展，旧 MotionForge 不支持该骨骼扩展。
- 动画 GLB 保存采样烘焙动作；骨骼一次导出一个完整 rig。静态导出继续由模型编辑入口提供。
- `studio_observe` 可对导出 GLB 取 phases `[0,.5,1]`，返回真实 PNG 与对应变形网格快照，
  AI 和人能在观察区检查结果，而非仅检查求值数值。

## 用语言编排动作

1. 在 **Codex chat** 直接说「让抽屉依次打开」。Agent 读取当前工程并创建动作，工作台 **动作编辑** 显示结果。
2. 要指明部件或姿态，在视口／对象列表中选中部件，拖动时间轴，再点顶部 **附加选区到对话**。它会暂停播放，将对象 ID、工程版本和 `motion.time_seconds` 附加到聊天；不会自动发送消息。
3. 回到 chat 说「这里停两秒，其余动作保持」。附加后若改变选区、时间或工程版本，旧附件失效，需要重新附加；打开页面或恢复旧选区不会自动添加附件。
4. 普通浏览器不提供 Codex 附件按钮；在连接同一工作台的 MCP 客户端聊天中说明部件名称和时间，如「中间抽屉在 2.4 秒的姿态停两秒」。
5. 手动调整参数或关键帧后先点 **保存动作**，让 Agent 读到你正在看的版本。未保存预览会在附件中标明，不能当作后端已保存动作。
6. 导出 **可编辑运动包 ZIP**，重开后仍能调整参数；**动画 GLB** 保留采样播放轨道，不保证恢复原有语义参数。

可以用 GPT-6、其他 Codex 模型，或连接同一 MCP 的通用 Agent。插件不内置第二个模型账号；效果取决于输入、所选 Agent 和工具。
机械动作需能识别并编辑对应部件；整体 GLB、复杂关节或角色骨架可能需要先处理结构。骨骼自然度、接触与碰撞另验。

### 本地复现（不调用模型或服务 API）

在仓库根运行：

```bash
uv run python examples/motion_editing/verify_tutorial.py --out /tmp/workbench-motion-demo
```

输出目录必须尚不存在。脚本生成一个简单三抽屉模型，并经真实 stdio MCP 依次创建开合、只延长中间抽屉停顿、导出 ZIP 和 GLB、从独立工作区重开、再缩短行程。
它检查源几何及未选中部件保持不变、逐帧位移和导出动画轨道。各轮文件与 `report.json` 留在输出目录。
这是确定性产品流程验证，**不是多模型能力排名**；人的自然语言请求仍需由宿主 Agent 理解执行。

## 数据与 AI 契约

`objects[].motion` 纳入原有对象版本、租约、撤销、工程保存与 worktree 分支。
工具 `studio_motion` 的 action 为 `set/clear/import/export`，params 用同一编辑参数结构；
对应 `studio_edit motion_set/motion_clear/motion_import/motion_export` 兼容入口。
始终带当前任务 workspace_id 和刚读取的 expected_revision；共享工程建议带 expected_versions。

```json
{
  "schema": "studio-motion/v1", "kind": "joint", "duration": 4, "fps": 30, "mode": "pkf",
  "joint": {"type":"revolute", "axis":"z", "origin":[0,0,0], "parent":null, "limits":[-180,180]},
  "parameters": [{"id":"angle", "default":60, "unit":"deg"}],
  "steps": [{"id":"open", "t_start":0, "t_end":4, "value_start":"0", "value_end":"angle", "easing":"ease-in-out"}],
  "keyframes": []
}
```

机械坐标：复用 MotionForge 原语义，axis 为**世界轴**；MF X=Studio X、MF Y=Studio −Y、MF Z=Studio Z。
旋转用度，滑动用米。origin 是无缩放的父关节局部框架（米，MF XYZ），无父级时为世界坐标。
渲染/静态编辑仍为毫米 Z-up，GLB 为米 Y-up；适配通过矩阵变换与零位增量保留几何缩放。
骨骼 PKF 的 axis 则是原 glTF 骨骼局部 XYZ，旋转为度；不能混用机械 MF 轴名。

服务端填入 bound_asset、bound_transform、bindings，防止几何或父对象零位更改后悄悄复用旧动作。
带绑定的拓扑/材质加工会拒绝，需明确清除并重新绑定，或在 Blender 修改整个 rig 后重新导入。
跨父子机构编辑检查依赖的版本/租约，零件子聊天没有相关范围时返回 scope_violation。
源 GLB 按 SHA256 单独存储，普通静态代理不会覆盖 skins；源 `.blend` 存入独立 sources。
保存/导入/worktree 复制都带上这些依赖。导出不覆盖已有文件。

## 复用与执行

- MotionForge pin `18a11fe175691538962b5659a4797c3d3c24ed17`，来源、SHA 与补丁见
  `studio/web/vendor/motionforge/SOURCES.json`。MotionForge 为插件作者的自有项目，按本仓 MIT 许可发布；见[第三方声明](THIRD_PARTY.md)。
- jsep 1.4.0 解析公式。仅允许参数、数字、算术与白名单数学函数，长度/复杂度/有限性/限位有验证。
  已禁用原内核 `new Function` 路径。前端与 Node worker 共同使用 `motion-engine.js`。
- 导出器复用原 ResultPackageExporter，修复固定 30 fps。GLB 采样追加标准 TRS 动画，
  保留源几何/材质/蒙皮 buffer，不用 Trimesh 重写 rig。
- 本机需 Node.js 20+，构建好的 `studio/app/dist/motion-cli.cjs` 随插件分发，不需运行 npm install。
  单次采样最多 50 万节点帧，避免大工程导出失控；可缩短片段/降低 fps/分对象导出。

## 明确边界

首批外部 MotionForge v7 导入要求：零位、单片段、固定拓扑、独立网格节点；
不接受 reparent events、overflow、scene markers 或无法绑定的组节点，不静默丢字段。
Morph targets、Draco/Meshopt/KTX2 压缩资产需先在 Blender 整理；骨骼动作不是通用 IK/控制器编辑器。
复杂 IK、约束、接触修正、动作混合仍由 Blender 求解并烘焙，不宣称任意角色自动绑骨或自然动作均合格。
`.blend` 的外部图片由调用者先用 Blender Pack Resources 打包；本插件不执行导入 `.blend` 中的脚本。

## 验证证据

自动测试见 `tests/test_motion.py` 与 `tests/test_motion_engine.mjs`，覆盖公式注入、非有限数值、
关节限位、反向 seek、父子 FK、失效绑定、clip 调速裁剪、包往返、原生 v7 核心往返、
逐件范围/版本与撤销不覆盖其他聊天。

真实验证素材（仓外）：`~/test/claude-blender/runs/studio-motion-20260923/`。
Blender 创建真实两骨蒙皮 GLB；61 帧/1488 顶点逐顶点对账：PKF 与烘焙 GLB 最大误差
`6.17e-9 m`；新增局部 X 弯曲通道最大误差 `2.65e-8 m`、顶点位移 `0.566 m`。源 clip 与重新烘焙最大误差 `1.25e-8 m`，实际顶点位移约 `0.120 m`。
另经观察管线真实 Blender 重开，生成三姿态 × 两视图及对应形变网格快照。
UI 使用真实打包 MCP App、真实后端和 headless Chromium WebGL：参数修改/保存、时间轴播放、
骨骼导入、GPT 绑骨请求、窗口连续缩放、切换编辑模式；无 pageerror，资产请求峰值 1。
这不等同于人工拖动原生 Codex 窗口的体感验收，也不代表复杂角色自然度验收。

本轮源码测试：85 项 Node 与 76 项 Python/MCP 回归通过。安装源保留并合入其他任务头壳配方，86 项 Node 与 40 项相关 Python/MCP 检查通过。最终缓存版本为 `0.7.2+codex.20260923024845`。旧聊天需新开任务以加载新增工具，未中断其他任务正在使用的服务器。

高面数压力测试：1310720 面、55051304 字节 GLB，真实安装缓存 + 隔离后端 + Chromium WebGL。
12 次连续窗口尺寸变化约 434 ms，总计 3 次 draw 调用（含场景辅助线），资源重读 0，
暂停后静止 draw 0，pageerror 0。记录为仓外 `installed/performance.json`。
该测试覆盖渲染调度与资源重读，未等价测试原生 Codex/Electron 的整个窗口合成性能。
