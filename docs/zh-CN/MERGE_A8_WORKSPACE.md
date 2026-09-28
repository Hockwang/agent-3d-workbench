> English: [../MERGE_A8_WORKSPACE.md](../MERGE_A8_WORKSPACE.md)

# Merge / A8 工作区试接入

2026-09-22。复用作者研究仓库中统一 merge_ui / A8 / URDF viewer 的内核，通过现有 Python 任务和离线 HTML 成果进入 Codex 右侧工作区。不启动新 HTTP 服务，不依赖该研究仓库的安装路径。来源工作树、逐文件 SHA 和适配范围见 `studio/core/kernels/scene_viewer/SOURCE.json`。

## 使用

「观察与测评 → 拆件与机构 → 审阅数据与记录」载入 A8 / Merge。两种模板和已有审阅记录不再出现在建模任务列表。执行机制仍复用 `studio_task`，不移动或重写历史任务文件。AI 先用 `studio_open({"mode":"observe"})` 打开观察区。

```json
{"action":"start","template":"merge-review","inputs":["/absolute/dataset/manifest.json"],"params":{"title":"拆件审阅","units":"m"}}
```

输入原 manifest 路径，保留它旁边的 GLB、可选 group.json 和 reference 图片。上传单独的 JSON 不能携带邻接资源。旧 merge 数据可能把毫米直接写入 GLB，必须显式选 `units:"mm"`，不按模型大小猜测。两个 manifest 会启用当前 / 对照 / 并排。

预览支持炸开、编号、选件高亮、原材质、X-ray、线框与逐件指标。输出 `parts.glb` 可点击「接回编辑」，使用现有合并、连通块拆分、撤销和 GLB/STL 导出。保留每个源节点的变换、UV 和材质；多 primitive 的部件可能导入成多个对象。合并仍是 L1 网格拼接，不等于实体布尔或自动封口。

```json
{"action":"start","template":"a8-review","inputs":["/absolute/catalog_registry.json"],"params":{"batch_id":"existing-batch","case_ids":"case-a,case-b"}}
```

也可输入原 `cases.json` / `cases.js`，同时传 `parts_dir` 的绝对路径。空 `case_ids` 取前 8 个本机可用案例；最多 8 案、每案 512 件、输入资产预算 90 MB。可选 `compare_case_id` 必须属于本次选定案，把它设为其他案的对照层。

A8 保留关节 parent/child、origin/rpy、axis、行程及上游审计事实。提供整体 phase、逐关节滑杆、播放、关节轴、炸开、参考图和键盘切案。上游 blocked/provisional 不因页面加载成功而改为通过。拒绝缺件、非法路径、循环关节图、未知运动类型和提供了 SHA 但不匹配的资源。

G/B 标记相互排斥，再点取消。**切换工作区或重开预览会重建 iframe，未导出的标记会丢失**。在工作台点「导出标记」通过现有上传接口保存到当前 job 的 `task-inputs/`，收到成功响应后显示实际路径；独立打开 HTML 时使用浏览器下载。不会写回原 A8 registry，也不宣称跨工作区自动同步。导出包含 executionKey、完整场景和实际资源字节绑定的 contentSha256。

## 与原应用的边界

- 已复用核心观察与机构预览，静态几何通过现有编辑器衔接。
- merge_ui 的连续点选自动合组、涂抹原面拆件、group.json 编辑回写尚未接入本轮界面。工作台已有按面 ID/球形区域提取，但不是原来的涂抹交互。
- A8 的注册表持久化、跨批次 Golden/Bad 汇总与审阅状态 MCP 同步尚未接入。AI 可以读取任务场景报告；预览内的临时选件/phase 还没有进入共享上下文。
- 机构不会静默扁平化导入静态编辑器。A8 任务保留关节在审阅结果中；更改关节结构、碰撞检验需调用对应模型任务。
- 当前打包所选资产为离线快照，适合小批审阅；不复制或打包整个历史 registry，也不声称大规模零复制流式浏览。

## 验证与性能

隔离证据目录：`~/test/claude-blender/runs/workbench-merge-a8-20260922/`。

- 犬夜叉 013 / A 两轮真实拆件：9+9 件对照；主版本接回编辑 9 件、571,892 面，合并两件为 8 件后总面数不变，撤销恢复所有原对象和变换，GLB 导出成功。
- 参数化 A8 真实四抽文件柜 / 单门床头柜：5 link / 4 prismatic、2 link / 1 revolute，整体开合、单关节端点、播放和轴向在嵌入页面验证。四抽行程 0.38642 m，门行程 0.976992 rad，来自原数据，不是新估计。
- A8 静止 4 秒：0 draw call、0 canvas resize。模拟连续调整 iframe 宽高 4 秒＋稳定 0.5 秒：2 次 canvas 属性写入（一次重建），51 个绘制调用（包括阴影与轴），无 >50 ms 长任务。复用工作台 RenderLoop 的 150ms resize 稳定策略。
- Merge 两版本并排、编号和炸开开启：静止 4 秒同样为 0 draw call / 0 canvas resize；连续调整宽高后一次画布重建、48 个绘制调用，无 >50 ms 长任务。宿主 RAF 最大间隔 15.1 ms、P95 13.9 ms；这不是模型持续动画的帧率。
- 此结果是隔离 MCP App 宿主页面测试，不代表 Codex 原生窗口整体 FPS。
- 测试覆盖单位转换、节点变换/材质、输入字节指纹、原文件只读、关节图/路径负例、离线打包完整性及现有任务/编辑回归。
- 完整 Python 回归：288 passed、2 deselected（排除 Bambu）；Node：59 passed。最终 DOF 数量调整后专项再次 8 passed。

构建：`npm run build:app`。专项：`uv run --frozen pytest -q tests/test_assembly_review.py`；`node --test tests/test_assembly_bundle.mjs tests/test_render_loop.mjs`。
