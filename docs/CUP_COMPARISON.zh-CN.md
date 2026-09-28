[English](CUP_COMPARISON.md) · [README](../README.zh-CN.md)

# 同一张图，两条 3D 工作流

同一张独立生成的参考图，分别走 **Codex 本地建模 → 可编辑部件** 和
**Hunyuan 生成 → Hunyuan Part 分件 → 可编辑部件**，最后都在工作台中检查和修改。
生成 API 路线也能分件，不能把分件当成本地建模独有的能力。

| 共同输入 | Codex + 本地 Python | Hunyuan 3D 3.1 Pro |
| --- | --- | --- |
| ![共同参考图](assets/cup-comparison/reference.png) | ![本地模型](assets/cup-comparison/local.png) | ![API 模型](assets/cup-comparison/generated.png) |

参考图由内置图片生成工具独立生成，不来自任一路线的 3D 模型。
[完整提示词](assets/cup-comparison/reference-prompt.txt)。两条路线使用同一个 PNG，SHA-256：
`3931bd17e4593f39242c25697a33c33e0e3566aa08d054f9db024f77ccb8b74d`。
这是一个流程演示，不是基准测试，也不是通用效果排名。

## 分件后实际得到了什么

| 本地：四个建模部件，展开显示 | API：两个生成式分件，已移开把手 |
| --- | --- |
| ![本地分件](assets/cup-comparison/local-parts.png) | ![API 分件](assets/cup-comparison/api-parts.png) |

本地 Agent 在建模时就把**杯身、把手、杯盖、旋钮**分别构建。
这是“按部件建模”，不代表它已对任意现成网格完成自动语义分割。
Hunyuan Part 本轮返回**把手**和**杯身＋杯盖＋旋钮**，杯盖仍与杯身合在一起。
两件不天然比四件差，但本轮这两件无法提供独立可拆的杯盖。

| 实测项 | 本地路线 | 生成 + Part 路线 |
| --- | --- | --- |
| 3D 生成服务 | 无 | `hunyuan-3d-3.1-pro` → `hunyuan-3d-1.5-part` |
| 几何 | 4 对象，共 41,710 面 | 分件前 60,000 面；分件后 2 件，共 1,735,888 面 |
| 合并几何重合顶点后的拓扑 | 4 件均水密，无开边、无非流形边 | 每件 6 条开边，0 条非流形边；两件都不水密 |
| 材质 | 程序设定的陶瓷纯色 | 生成有 PBR；Part 输出分件顶点色，没有贴图图片 |
| 尺寸 | 明确设定杯身直径 88 mm、高 90 mm；内腔是设计假设 | 图片无法确定实物尺寸；仅为展示统一到 114 mm 总高 |
| 单件编辑 | 把手平移 +25 mm、撤销、导出、保存并重开：通过 | 相同流程：通过 |
| API 提交 | 0 次 | 生成 1 次、分件 1 次，均未重复生成 |
| 服务耗时（含收件） | 不适用 | 生成 211.88 秒 + 分件 78.56 秒 |
| 网关回执金额 | 无 3D 服务费用 | 生成 2.16、分件 0；未给出币种 |

[机器可读证据](assets/cup-comparison/report.json) 中的本地 Python 执行时间不包含
Codex 思考、编写脚本和渲染，**不能直接拿来与 API 时间比较整体效率**。
费用也未包含 Agent 宿主和参考图生成的用量。分件本次回执为 0，不代表以后免费。

外观判断：本地模型用旋转体和扫掠把手近似轮廓，但简化了陶瓷纹理与形状；
API 保留了更多图像式表面变化，也改变了比例和光泽。
Part 保留大体摆放，却改变拓扑、颜色和面数。
两条路线都只到可检查的草稿；未实打，未验证食品接触、强度和装配保持力，
水密也不等于通过这些验证。

## 先下载模型体验

下载 [模型包](https://github.com/Hockwang/agent-3d-workbench/releases/download/demo-cup-20260928/cup-comparison.zip)，
在工作台顶部点击 **「打开文件」**：

- `local/scene.glb`：本地四部件，旁边附单件 STL。
- `api/generated.glb`：未修改的带纹理 API 生成结果。
- `api/split.glb`：未修改的两件分件结果，使用供应商返回的分件颜色。
- `api/display-114mm.glb`：上述分件结果的展示缩放版，明确统一为 114 mm 高。

选中把手，让 Agent 只移动它，再撤销。**「当前模型」** 返回编辑视图；
新运行的任务在 **「最近成果」** 中。导入会追加模型，不要反复导入来切换页面。

## 分别复现两条路线

先安装仓库依赖。本地路线不需要 3D 服务 key。
API 路线需要实现 [Hunyuan 3D Responses 协议](zh-CN/HUNYUAN_API.md) 的网关，
自己的有效凭据须在启动进程环境中，并使用私有 `services.json`。
作者的公司端点与密钥不作为公共服务提供。配置方法见 [API 接入教程](API_GENERATION_DEMO.zh-CN.md)。

```bash
mkdir -p /absolute/cup-demo
cp docs/assets/cup-comparison/reference.png /absolute/cup-demo/reference.png

# 本地建模，不调用生成 API。
uv run python examples/cup_comparison/run_comparison.py local \
  --out /absolute/cup-demo

# 付费 API 生成；请求 FBX，供后续 Part 使用。
uv run python examples/cup_comparison/run_comparison.py generate \
  --out /absolute/cup-demo --service-config "$HOME/.config/codex-3d/services.json"

# 分件，费用由服务套餐决定；引用已经保存的生成任务。
uv run python examples/cup_comparison/run_comparison.py split \
  --out /absolute/cup-demo --service-config "$HOME/.config/codex-3d/services.json"

# 无 API 调用：在独立 MCP 工作区验证单件编辑。
uv run python examples/cup_comparison/verify_edits.py --out /absolute/cup-demo
```

重复运行未变更的阶段会查询／恢复原任务，模糊提交不会重发；本地代码改变时会创建本地新版本。
生成不是确定性的：`verify_edits.py` 针对本轮的四件／两件与已识别把手做断言；
新生成结果应先人工或 Agent 看图检查，再调整对应断言。
验证器拒绝覆盖此前的验证工作区。

公开的本地脚本是 Codex **看过这一张图后**编写的重建结果。
只替换 PNG 不会让固定脚本自动建出另一个物体；新物体需要 Agent 重新观察并编写模型。

## 给 Agent 的提示词与 MCP 步骤

**本地提示词：**“观察这张参考图，用 Python/CadQuery/Blender 在本机近似建模，
让杯身、把手、杯盖、旋钮可分别编辑。声明设定尺寸和遮挡部分的假设。
不要调用 3D 生成 API。检查实体、展示渲染，再演示单件修改和撤销。”

**API 提示词：**“用我配置的 Hunyuan 服务根据同一张图生成一次，输出 FBX 供 Part 使用。
随后调用一次 Part，检查实际分组、材质和拓扑，导入后演示单件修改。
如有部件粘连、贴图丢失或开边，明确报告；不能把执行完成等同验收通过。”

API 路线先调用 `studio_capabilities` 和
`studio_services(action:"probe", id:"hunyuan")`。
用 `studio_task` 提交生成（`provider:"hunyuan"`、`operation:"image-to-3d"`，
参数 `output_format:"FBX"`、`face_count:60000`、`pbr:true`），完成后再分件：

```json
{
  "action": "start",
  "workspace_id": "CURRENT_WORKSPACE_ID",
  "provider": "hunyuan",
  "operation": "segment",
  "params": {"source_task": "LOCAL_GENERATION_TASK_ID"}
}
```

编辑时读取新鲜的工作区、对象 ID 和版本；看过实际结果再命名部件。
这些脚本使用真实 stdio MCP，不冒充原生 UI 按钮点击测试。
[验证与限制记录](API_GENERATION_RESULTS_20260928.md)。
