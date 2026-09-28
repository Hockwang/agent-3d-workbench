# 观察工作区验收（2026-09-22）

产品方向见 [AGENT_WORKSPACE.md](../AGENT_WORKSPACE.md)。本轮补齐直接看模型、同尺度比较、姿态采样、人和 AI 共用焦点及评价的闭环。

证据根：`~/test/claude-blender/runs/workbench-observe-20260922`。

| 验证 | 结果 | 证据 |
|---|---|---|
| Python 完整回归 | 271 passed，2 个真实 Bambu 环境用例按既有配置排除 | `verification-logs/observe-full-tests-final.log` |
| 前端调度、协议与界面单元测试 | 41 passed | `verification-logs/observe-node-final.log` |
| MCP App 构建 | 成功，单文件 1,486,224 bytes | `verification-logs/observe-build-final.log` |
| 真实 stdio 协议 | 默认 PNG ImageContent、精简指标、禁止读取报告外图像路径 | `tests/test_mcp_server.py::test_observe_returns_image_content_and_compact_metrics` |
| WaveAB 机器人 URDF | 6 部件 / 60,000 面 / 5 DOF，3 姿态 × 2 视图；最终观察任务约 3.10 秒 | `tasks/c5290ceaaf604156ab66c42076a8080f/output/observation.json` |
| WaveAB 风车 URDF | 3 姿态 × 2 视图生成成功 | `casual_windmill-task.json` |
| 两个实际建模任务的动画对照 | 40/55mm 铰链，2 版本 × 3 姿态 × 2 视图，约 3.88 秒 | `tasks/7dccfab2443e4928898444665b3b1b75/output/observation.json` |
| 动画求值正确性 | GLB 采样 frame 1 / 40.5 / 80；中间姿态的冻结 GLB 包围范围发生变化 | 同上 `snapshots/` 和 `camera.json` |
| 来源耗时 | 分别精确引用原建模任务的 1.04915 / 1.03476 秒；费用/token 为空 | 同上 report 的 provenance |
| 原始输入保护 | 机器人 URDF 及 visual 依赖 SHA256 均未改变，3 个冻结姿态包围范围不同 | `robot-snapshot-validation.json` |

在 Codex 内置浏览器验收共享界面：600px 窄面板正常显示；AI 选 B 版本/50% 姿态，界面同步；人选机器人/50%，后端读取同一焦点且 actor 为 human。评价草稿按记录保存，切到另一记录不会携带，切回后恢复。浏览器 error/warn 检查为空。

## 性能和结论边界

- 上述秒数是该机器、该样件的实际观察任务耗时，不能当成 WaveAB 生成路线耗时或总体性能结论。
- 观察工作区复用一个 WebGL 预览器，版本切换释放旧模型；隐藏时停绘。Blender 一次只加载一个版本/姿态，先收集公共边界再逐项渲染。没有用多个高面数场景同时常驻实现对照。
- 未测 Codex 原生窗口的整机 GPU 帧率；浏览器布局检查和调度器测试不能替代该项。
- 复用了 yourdfpy / Trimesh / Blender，没有重写 WaveAB 求解路线。本轮读取历史真实产物，没有运行新的远端路线批次，也没有给路线排质量名次。
- URDF 相位线性采样不等于连续碰撞检测；GLB 当前导入动画采样不等于任意 clip 的覆盖。几何指标明确标记计算姿态，不作为语义、外观或动作正确性的分数。
- 初次完整测试的 2 个失败来自 HTTP 工具数由 18 增为 19 后的旧断言；更新期望并显式断言 `studio_observe` 后，完整 271 项重新通过。没有跳过失败用例。

## 主要改动

- `studio/observation.py`：观察任务入口、来源指纹、焦点及带版本指纹的评价。
- `studio/observation_run.py` / `observation_render.py`：真实几何指标、URDF 正向运动学、共同相机、冻结姿态 GLB 和 PNG。
- `studio/web/observe.js` / `observe.css` / `task-preview.js`：观察工作区、保留相机的版本切换、人工评价、按记录隔离草稿。
- `studio/mcp_server.py` / `server.py` / `task_schema.py`：21 个 MCP 工具中的新增观察接口，以及 PNG 原生图像内容。
- `skills/print-prep/SKILL.md` / `docs/AGENT_WORKSPACE.md`：AI 读状态、看图、执行、验证、人接手的工作方式。
