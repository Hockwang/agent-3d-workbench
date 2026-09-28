# 场景实例编辑

> English: [../SCENE_EDITING.md](../SCENE_EDITING.md)

2026-09-23，v0.8.2。实现 [提案](../history/SCENE_EDITING_PROPOSAL.md) 的第一阶段：完整 GLB 实例、
局部编辑、骨架与动作检查、原位回填、工程保存和任务协作。

## 宿主支持

| 能力 | Codex 桌面端（侧栏面板） | 浏览器页面（任意 MCP 宿主，例如 Claude Code） | 纯 MCP 客户端（无页面） |
|---|---|---|---|
| 视口点选 + Shift 多选 | 是 | 是 | 否：没有视口可点 |
| AI 高亮（共享工作台选区） | 是，走 `studio_edit(action:'select')`* | 是，同一工具 | 是，同一工具 |
| AI 可读取选区（`studio_get_state.workbench.selection`） | 是 | 是 | 是 |
| 带 `expected_revision`、撤销/重做、逐对象版本（共享工程）的编辑 | 是 | 是 | 是 |
| `scene_import` / `scene_export` / `scene_replace` | 是 | 是 | 是 |
| 右键创建聊天分支 | 是，需要本机装 Codex CLI | 只有页面属于某个 Codex 任务时可以：工作区 id 会被当作父线程读（`studio/shell/part_chat.py`），Claude Code 那种固定 id（`claude-code`）装了 CLI 也建不了 | 否：没有视口可右键 |
| 打开分支（deep link） | 是，走 `ui/open-link` | 只对从 Codex 任务创建的分支有效，且本机 Codex 桌面端已注册 `codex://` 处理器 | 否：没有界面打开返回的 URL |

\* 不是 `studio_select`/`/api/select`——那个只认打印准备面板自己加载的部件列表，不适用于场景编辑的对象。

浏览器页面渲染的是 Codex 内嵌展示的同一套 `editor.js`/`editor-viewport.js` 界面，只是 API
传输层不同（MCP 工具调用 vs 本机 HTTP fetch）。Claude Code 用户可以让 AI 调用
`studio_open(presentation='browser')` 拿到的本机 URL 打开它。聊天分支是这里唯一
Codex 专属的部分：它通过官方安装的 CLI 的 App Server fork 出一条真实 Codex 线程，
所以不管哪个宿主在驱动 AI，都需要机器上装有这个 CLI，还需要一个 Codex 任务当父级：工作区 id 会被当作父线程 id 读（`studio/shell/part_chat.py`），这就是 Claude Code 的固定工作区 id 装了 CLI 也建不了分支的原因。

## 人的入口

「模型编辑 → 模型与对象 → 场景与人物」导入 GLB，每个文件保留为一个完整实例。
场景对象列表与视口共用选区；选中人物后在「对象属性 → 场景实例」查看骨架，进入动作编辑，
或点击「修缮 / 绑骨」把该对象的任务交给当前 Codex。

移动、旋转、缩放和外观参数作用于当前实例。复制实例最初共享不可变源资产，修改材质后
生成新的资产哈希，其他同源实例不变。材质直接改 GLB JSON，原始蒙皮、UV、法线与动画
buffer 不变。底色贴图替换和复杂几何/权重调整走 Blender，再导入完整候选。

「外部修缮与回填」可导出编辑源、选择候选 GLB 原位替换；保持实例 ID、名称、可见性与
摆放矩阵。新候选的动作重新载入，整个动作预览暂停并回到起点；不沿用旧骨骼索引。
有坏权重、循环层级、损坏 buffer 或无效动画目标的候选不会提交。
结构验证不等于外观/动作自然度验收，回填后仍需观察关键姿态。

## AI 契约

复用 `studio_edit`，始终使用当前任务 workspace_id，并先读 `studio_get_state.workbench`。

| action | params | 行为 |
|---|---|---|
| `scene_import` | `files: [绝对GLB路径]` | 追加完整实例；不拆散内部层级/rig |
| `scene_export` | `ids: [单个对象ID]`，可选 `path` | 导出局部编辑源 GLB，不烘焙实例摆放与未导出的动作调整 |
| `scene_replace` | `ids: [单个对象ID]`, `path`，可选骨架 `blend_path` | 检查候选后原位替换，保留身份与摆放 |

场景仍使用毫米 Z-up；编辑源和回填 GLB 使用局部米制 Y-up。
不要重置源模型原点或把场景摆放再次烘焙到候选中。导出普通静态对象也用 `scene_export`，
避免普通世界坐标导出在回填时重复应用变换。

长任务保留导出时的对象版本，提交 `expected_versions`；不要在提交前读新版本后无条件
覆盖。现有零件聊天 scope、租约及撤销继续有效，`scene_replace` 可以在绑定对象的任务中
执行。父子机构依赖范围不够或发生同件冲突时拒绝。

## 存储与复用

`objects[].scene` 为可选的 `studio-scene-instance/v1`：

- `asset`：当前完整 GLB SHA256；`family`：初始同源资产身份。
- `kind`：static / skin / animated；nodes / bones / clips 为源资产摘要。
- 既有 `objects[].asset` 为只用于静态检查和制造副本的代理几何，不能覆盖完整源。
- `objects[].motion` 沿用 skin，新增 gltf 类型承载刚体节点原生 clip。
- 实例矩阵与源资产分离，同源修改采用不可变资产的按实例更新。

保存工程和运动 ZIP 带上完整源资产，重开/模型分支继续沿用原身份或导入时一致重映射。
旧工程没有 scene 字段，按旧路径读取，不自动迁移。
普通 GLB 网格导出对场景实例报错并指向完整工程/编辑源/动画 GLB，避免静默丢失骨架。
STL / 打印副本明确使用静态代理。

复用既有 EditorViewport、GLTFLoader、SkinMotion、Blender、工程和协作后台。
本轮没有复制附件游戏代码或把附件素材打进插件发行包。

## 第一阶段边界

当前是场景中的完整资产实例编辑；内部网格和骨骼由动作面板或 Blender 深入处理。
本页记录 v0.8.2 的边界；v0.8.3 完整城市接入见 [CITY_RUNTIME](./CITY_RUNTIME.md)。v0.8.2 不包含驾驶、NPC 行为、碰撞/导航重建、完整城市流式加载与
人物设施接触规划尚未接入。也没有任意场景树重新挂父级或一键更新全部同源实例。
单个完整资产最多 500 MB、代理最多 500 万面；工程最多 500 个对象。
Morph、压缩 GLB 需先在 Blender 整理；任意角色自动绑骨的自然度不作保证。

编辑/动作模式复用同一个真实 GLB，切换不重新加载；候选加载失败保留原画面并可重试。
浏览器 resize 验证与原生 Codex 窗口合成体感分开记录。
实测见 [本轮验收](../history/VALIDATION_20260923_SCENE.md)。
