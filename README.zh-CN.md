[English](README.md) · [使用教程](docs/zh-CN/GETTING_STARTED.md) · [Agent 手册](docs/zh-CN/AGENT_PLAYBOOK.md)

# Agent 3D Workbench

[![💬 加入 Discord 社群](docs/assets/discord-join.zh-CN.svg)](https://discord.gg/r8BVSGtR8H)

**让通用 AI Agent 调用你选择的工具建模、分件，再和你一起查看、修改结果。**

Codex、Claude Code 等 MCP 客户端都可以使用。本地代码路线无需 DiT、3D 服务账号或 3D API key；
也可以接入自己的 Hunyuan、Assembly 等服务。Agent 的账号／订阅与 3D 服务费用分别计算。

## 能做什么？

人和 Agent 共用同一个工程、模型和选区。下面这些能力可在本地完成；Blender、Node.js、切片软件按任务安装。

| 功能 | 你可以做什么 |
| --- | --- |
| **查看与编辑** | 导入 GLB／STL，选中部件，移动、旋转、缩放，撤销／重做；让 Agent 只修改指定对象。 |
| **代码建模** | 让 Agent 用 Python／CadQuery／Blender 创建模型，指定尺寸和部件，生成可继续修改的脚本。 |
| **分件与修复** | 平面切割、布尔、连通块拆分、按明确面标签拆分、小洞修复和减面。 |
| **材质与外观** | 调整选中部件或材质槽的颜色、粗糙度、金属度，替换贴图，执行 UV／烘焙任务。 |
| **结构加工** | 按明确尺寸与加工区域制作内腔、盖子、头壳、定位销／孔、分色嵌件及关节模块。 |
| **骨架与动作** | 按明确骨架绑定和修复权重；编辑机械关节、骨骼姿态及关键帧，预览和导出动画。 |
| **观察与检查** | 查看真实渲染、尺寸与网格报告，对指定关节姿态做碰撞采样，记录发现的问题。 |
| **打印准备** | 调整朝向、排盘，导出 STL／3MF 工程；配置切片软件后估算打印时间与用料。 |
| **工程与交付** | 保存、重开工程，在任务总览查找成果和版本，导出 GLB／STL，继续编辑生成模型。 |

这些是可调用的工具，具体任务仍需满足输入条件；自动语义分件、自然动作和实物可制造性需要另行验收。
[完整能力与条件](docs/zh-CN/PUBLIC_CAPABILITIES.md) · [第一次编辑教程](docs/zh-CN/GETTING_STARTED.md)

## 在工作台里和 Agent 一起编辑

![在 3D 工作台里选中杯子部件，由 Agent 修改，再撤销](docs/assets/point-and-edit.gif)

**选中部件 → 让 Agent 修改 → 查看变化 → 撤销。** 杯子示例展示人和 AI 共用模型、选区和操作记录。
当前界面中，点击 **「附加选区到对话」** 可把选区带入消息；Agent 也可以通过 MCP 读取实时选区。
[跟着完成第一次编辑 →](docs/zh-CN/GETTING_STARTED.md)

**皮卡丘头套：继续编辑已有的 13 个部件。**

![在工作台选中并移动皮卡丘耳朵、撤销，再移开后壳查看内腔](docs/assets/pikachu-head-shell/workbench-edit.gif)

选中耳朵的黄色件和黑色件一起移动 → 撤销 → 移开后壳查看内腔 → 还原。
这是用 v6 交付模型重新操作的关键帧演示，通过本地 MCP 编辑，无需生成 API。
头围按 60 cm 设计；仍是结构样稿，视线受阻、未打印或试戴。[查看从原始 STL 到分件、磁吸结构的完整案例 →](docs/PIKACHU_HEAD_SHELL.zh-CN.md)

需要图片生成 3D 或专用分件服务时，也可以选择 API 路线。下面用实际结果说明区别。

## 建模：写代码，还是调用生成模型？

同一张杯子参考图，两种工具得到不同的结果：

| 参考图 | Codex · 代码建模 | Agent + Hunyuan · DiT 建模 |
| --- | --- | --- |
| ![杯子参考图](docs/assets/cup-comparison/reference.png) | ![本地代码建模结果](docs/assets/cup-comparison/local.png) | ![Hunyuan 生成结果](docs/assets/cup-comparison/generated.png) |
| 同一张输入图片 | 用 Python 构建杯身、把手、杯盖、旋钮，4 个部件可分别编辑 | 调用 Hunyuan 3D 生成带 PBR 贴图的模型，可再交给 Part 分件 |
| 怎么选 | 希望明确设定尺寸、结构，并继续用代码调整 | 希望从图片得到带表面细节的 3D 初稿 |

本地结果简化了轮廓与纹理；Hunyuan 结果也改变了比例与光泽。
图片不能确定真实尺寸。[查看模型、提示词与复现步骤 →](docs/CUP_COMPARISON.zh-CN.md)

## 分件：本地代码，还是专用 API？

前两列是**同一个风扇**；Hunyuan Part 使用**杯子案例**。这里展示工具会做什么，不是三路同输入排名。

| GPT-6 · 本地分件 | GPT-6 + Assembly · P3RW | Agent + Hunyuan Part |
| --- | --- | --- |
| ![本地代码将风扇分为七件](docs/assets/assembly-comparison/gifs/fan-segment-local.gif) | ![P3RW 将同一风扇分为九件](docs/assets/assembly-comparison/gifs/fan-segment-p3.gif) | ![Hunyuan Part 将杯子把手分离](docs/assets/cup-comparison/api-parts.png) |
| Agent 写代码处理网格，本例 7 件，保留源三角面 | 调用专用分割服务，本例 9 件，保留源三角面 | 调用生成式分件服务，本例 2 件：把手、杯身＋盖＋旋钮 |
| 后网罩混入了部分底座面，仍需调整规则 | 部分功能件仍合并，需要继续细分 | 杯盖仍粘连；拓扑改变，PBR 贴图变成分件色 |
| 想指定拆分规则，并继续让 Agent 改代码 | 想先获得专用分割器给出的部件草稿 | 想给生成模型增加可单独编辑的部件 |

三种结果都需要检查，件数更多不等于分得更好，也不等于可直接打印。
[风扇动图、token／耗时／估价](docs/ASSEMBLY_COMPARISON.zh-CN.md#token时间与估算价格) · [Hunyuan Part 结果与限制](docs/CUP_COMPARISON.zh-CN.md#分件后实际得到了什么)

API 路线需要自己的服务权限。[Hunyuan 接入](docs/API_GENERATION_DEMO.zh-CN.md) · [Assembly 接入](docs/zh-CN/ASSEMBLY_API.md)。
P3RW 演示使用原生 Assembly 服务；插件 OpenAPI 网关的端到端接入仍待验证。

## 开始使用

准备 Git、[uv](https://docs.astral.sh/uv/)、Python 3.12+、Codex 桌面端及支持插件的 Codex CLI：

```bash
git clone https://github.com/Hockwang/agent-3d-workbench.git
cd agent-3d-workbench
STUDIO_LANG=zh-CN ./install.sh --add
```

安装后重开 Codex，发送：**「打开当前聊天的 3D 工作台。」**
工作台支持中英文；Blender 等工具按所选任务另行安装。
[Claude Code／其他 MCP 客户端、完整安装与首次编辑教程 →](docs/zh-CN/GETTING_STARTED.md)

把参考图或模型交给 Agent，再明确选择工具，例如：

- **代码建模：**「参考这张图，用本地代码建模，让杯身、把手、杯盖分别可编辑。不要调用生成 API。」
- **DiT 建模：**「使用我配置的 Hunyuan 服务，按这张图生成模型。」
- **分件：**「对这个模型使用本地代码／Assembly P3RW／Hunyuan Part 分件，展示拆分结果，并告诉我哪些部件仍粘连。」三选一即可。

在工作台点 **「打开文件」** 查看已有模型，点 **「任务总览」** 找到生成结果；选中部件后继续让 Agent 修改、撤销或导出。
AI 执行前应读 [Agent 手册](docs/zh-CN/AGENT_PLAYBOOK.md)，确认可用工具、当前工作区与选区，再操作和检查实际产物。

更多案例：[皮卡丘头套](docs/PIKACHU_HEAD_SHELL.zh-CN.md) · [绑骨与抽屉驱动](docs/ASSEMBLY_COMPARISON.zh-CN.md)。
[能力清单](docs/zh-CN/PUBLIC_CAPABILITIES.md) · [工具参考](docs/TOOLS.md) · [贡献](CONTRIBUTING.zh-CN.md) · [反馈](https://github.com/Hockwang/agent-3d-workbench/issues)

pre-1.0；macOS 已验证完整桌面流程，Linux／Windows 待验证。[MIT](LICENSE) · [第三方声明](docs/zh-CN/THIRD_PARTY.md)
