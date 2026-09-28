> English: [../index.md](../index.md)

# 文档索引

文档默认用英文写；已经有中文版本的文档会用 `[中文](zh-CN/…)` 这样的形式
链到中文版。中文版本都放在 [`docs/zh-CN/`](./) 目录下（也就是本文件所在
目录），与英文文件一一对应。根目录下的规格文档遵循同样的模式：
[SPEC.md](../../SPEC.md) / [SPEC.zh-CN.md](../../SPEC.zh-CN.md)（工作台
规格）与 [SPEC_RECIPES.md](../../SPEC_RECIPES.md) /
[SPEC_RECIPES.zh-CN.md](../../SPEC_RECIPES.zh-CN.md)（配方格式）。

从这里开始：[TOOLS.md](../TOOLS.md)、[ARCHITECTURE.md](ARCHITECTURE.md)、
[CONFIGURATION.md](CONFIGURATION.md)、[CORE_CLI.md](CORE_CLI.md)，以及
[AGENT_PLAYBOOK.md](AGENT_PLAYBOOK.md)，分别是工具参考、系统架构、服务
配置、核心 CLI，以及面向 agent 的操作手册。

## 产品原则与范围

- [PUBLIC_CAPABILITIES.md](PUBLIC_CAPABILITIES.md) —— 无专用 3D 服务的本地能力承诺、输入条件与验收边界。
- [LOCAL_CAPABILITIES_VALIDATION_20260926.md](LOCAL_CAPABILITIES_VALIDATION_20260926.md) —— 真实 MCP、禁外网制造链路与回归验收。
- [AGENT_WORKSPACE.md](AGENT_WORKSPACE.md) —— 产品原则：AI 应该能够像写
  代码时那样读取状态、执行动作、收集证据并验证。
- [CAPABILITY_PARITY.md](CAPABILITY_PARITY.md) —— 用来定义一个功能"完成"
  与否的任务覆盖基准，以及目前的差距。
- [WORKBENCH_V06.md](WORKBENCH_V06.md) —— v0.6 功能总结：模型编辑与打印
  准备。
- [WORKBENCH_TASKS.md](WORKBENCH_TASKS.md) —— 建模、服务与产物任务工作区。

## 核心工作流

- [CITY_RUNTIME.md](CITY_RUNTIME.md) —— 完整的城市/世界工作台（需要用户
  提供场景包）。
- [CODEX_V05_INTEGRATION.md](CODEX_V05_INTEGRATION.md) —— v0.5 面板如何
  与 Codex 侧栏工作区集成。
- [DIRECT_PART_CHAT.md](DIRECT_PART_CHAT.md) —— 直接创建针对某个部件的
  对话分支（含宿主支持矩阵）。
- [FOLDER_PROJECTS.md](FOLDER_PROJECTS.md) —— 基于文件夹的项目/归属模型。
- [GENERATED_ASSET_EDITING.md](GENERATED_ASSET_EDITING.md) —— 生成资产从
  服务端返回后继续编辑。
- [HEAD_SHELL.md](HEAD_SHELL.md) —— 内置的「角色头壳制作」配方与任务
  模板。
- [MERGE_A8_WORKSPACE.md](MERGE_A8_WORKSPACE.md) —— 合并/A8 查看器工作区
  集成。
- [MOTION_EDITING.md](MOTION_EDITING.md) —— 动作/关键帧编辑功能。
- [SCENE_EDITING.md](SCENE_EDITING.md) —— 编辑场景实例（摆放、变换；含宿主支持矩阵）。
- [WORKTREE_COLLABORATION.md](WORKTREE_COLLABORATION.md) —— 跨 worktree
  协作编辑同一个部件。

## 服务集成

- [ASSEMBLY_API.md](ASSEMBLY_API.md) —— 可选的远程 Assembly workflow
  服务。
- [BYOK_SERVICES.md](BYOK_SERVICES.md) —— 第三方 3D 生成 API 的自带密钥
  （BYOK）配置。
- [HUNYUAN_API.md](HUNYUAN_API.md) —— Hunyuan 3D / Part 生成服务。
- [LUX3D.md](LUX3D.md) —— Lux3D 集成与能力说明。
- [WAVEAB_EVALUATION_PLATFORM.md](WAVEAB_EVALUATION_PLATFORM.md) —— 与
  一个内部评测平台的集成（需要你大概率没有的访问权限）。

## 许可

- [THIRD_PARTY.md](THIRD_PARTY.md) —— 第三方依赖与随附代码的署名；在
  重新分发之前请先阅读。

## 历史记录

`docs/history/` 存放已被取代的提案、带日期的验证/修复记录，以及其他项目
记录类材料。保留它们是为了留痕，但不会再维护，其中描述的状态可能早已被
产品淘汰——请把它们当作项目记录，而不是当前文档。
