# 角色头壳内置流程：交付验证

2026-09-22。已安装工作台 0.7.1+codex.20260922195729，未创建个人 Codex skill，未 commit / push。开发 worktree 为 `aac-head-shell-skill`。

## 变更与原因

- `recipes/wearable-head-shell/recipe.json`、`guide.md`：内置六步配方，记录尺寸与外观约束，防止把生成成功当成可穿戴验收。
- `studio/shell_kit.py`、`shell_kit_audit.py`、`shell_vision.py`、`shell_sight_audit.py`：参数化掏空、前后分壳、颈口、磁铁、已有色件、原眼内网孔及真实几何检查。
- `studio/task_templates.py`、`tasks.py`：注册可调模板，从冻结输入重建并校验实现版本。
- `studio/task_recipe_progress.py`、`recipes.py`、`server.py`：进度绑定任务和证据 SHA；重建清空旧复核，人工外观和 AI 评价分开。
- `studio/web/{workspace,tasks,observe,recipes}.js`、`recipes.css`：模板入口、按当前参数重建、来源对照和逐项检查。
- `examples/head-shell/`、`docs/HEAD_SHELL_SKILL.md`、插件内 `skills/print-prep/SKILL.md`：通用使用说明及绑定来源 SHA 的 Pikachu 参数例。
- `pyproject.toml`、`uv.lock`：增加内壁重建依赖 scikit-image；manifest 和 MCP 版本更新。
- 新增或更新测试：shell_kit、shell_vision、task_recipe_progress、recipe_workbench、recipes、recipes_ui。

## 实测

完整 Python 回归 415 passed，2 个实机 Bambu 用例未运行。之后补充实际眼网挡光测试（7 passed），调整相关模块回归（26 passed）；正式安装目录对配方、头壳视线及工作台隔离验证 43 passed。前端 67 passed。JavaScript 语法检查通过。

浏览器实测：内置流程逐项显示、点击外观创建同尺度对照、点击生成步骤打开当前冻结版本参数（600 mm、Ø6×3 mm、原眼保护勾选），未替用户做人工 good 确认。

正式生成任务 `a86689a47a7348fb82f86a3f7fe3edb3`，观察任务 `c77e81e15055427c95f1c3598cf1c2ea`，workspace `01a0c8dd-549b-7ff0-9bb0-8176a06a13c9`。通过注册模板生成、主模型已导入当前任务编辑器，原始 STL 保留。

11 件单体水密，0 开边 / 非流形边，1097 个装配位姿检查无待解决部件；声明头部包络无干涉。磁铁直径 6 mm、厚度 3 mm，孔直径 6.2 mm。含实际眼网的正前方射线仍被挡，流程 4/6，视线待解决、人工外观待确认；AI needs_review 已单独记录。真人试戴、通风和实物配合未验证。

正式源目录与插件缓存的本次 30 个变更文件 SHA 全部匹配，原 `.mcp.json` 完整保留。只在当前独立 workspace 建模，未改其他任务或 legacy 工程。
