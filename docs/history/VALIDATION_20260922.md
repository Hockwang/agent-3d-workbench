# 3D 工作台本轮验证（2026-09-22）

运行根：`~/test/claude-blender/runs/workbench-parity-20260922`。
所有历史模型测试在独立副本/任务目录运行，没有向打印机发送任务。

| 验证 | 实际结果 | 证据（相对运行根） |
|---|---|---|
| 历史 196 模型（185 STL + 11 GLB） | 196 通过，1361 次操作，输入 SHA 全部不变，109.76 秒 | `full-replay/summary.json` |
| Python 完整测试 | 260 passed，2 个真实 Bambu 环境测试未在默认套件执行，60.41 秒 | `verification-logs/wb-full-python-final.log` |
| 后续 MCP / 服务 / 新操作 / 3MF 定向测试 | 36 passed，29.51 秒，含真实 stdio 任务与产物读取 | `verification-logs/wb-contract-final.log` |
| 前端自动测试 | 41 passed，最后的窄屏修正后重新运行 | `verification-logs/wb-node-final.log` |
| 可移植任务验收脚本 | 16 个实际 Blender/CAD/Python 任务通过，含闭合/尺寸/UV/拓扑/贴图产物断言 | `portable-verify/results.json` |
| CAD 3 操作、MDE 2 接口 | 外壳/拉伸/回转和销铰/薄回转试片完成；首个 CadQuery 冷启动 236.88 秒，热启动约 2.3 秒 | `operations-smoke.json` |
| 光顺、减面、实体化、体素、UV、拟合、场景、分层、标签拆件、动画处理 | 12 项实际任务完成 | `remaining-local.json` |
| 真实脸件 Blender 减面 | 136146 → 68072 面，0 开边/0 非流形边；尚需独立外观审阅 | `remaining-local.json` 最后一项 report.json |
| 动画/蒙皮数值读回 | 1488 顶点漏绑 0；权重和最大误差 5.96e-8；目标 Tip 0 → 0.79999977 rad（预期 .8）；实际变形最大 .37384m | `character-qa.json` 最后一项 numeric-qa.json |
| 局部光顺 | 区域内 312 顶点，受保护顶点逐值不变；最大位移 .182916mm | `character-qa.json` |
| 发片 | 2 条显式引导 → 4 个发片四边形及 UV；交付引导 JSON、GLB、Blender 工程 | `character-qa.json` |
| Bambu 新鲜正/负例 | base 工程导出读回通过；face 被拓扑门禁拒绝，保留完整 geometry.3mf | `bambu-fresh.json` |
| 旧五件 Bambu 工程反例 | 精确识别脸件 4 条非流形边，其余 4 件通过 | `bambu-geometry-gate.json` |
| 服务任务 | 本机 HTTP 模拟：单次提交、按原 ID 继续收件、模糊提交不盲重试、下载端不接收 API key、结果不含密钥 | `tests/test_services.py` |
| 已安装插件协议 | 从安装缓存启动真实 stdio：20 个工具、22 个模板、任务完成、产物内容读取验证通过 | `installed-protocol.json` |
| 原用户工程保护 | 15 个原文件 SHA256 全部不变，含五件 STL 和已有 3MF | `original-integrity.json` |

## 界面实测

使用 Codex 内置浏览器测试同一份共享界面：
- 铰链两片的蓝/黄色材质正确；时间滑杆改变开合姿态。
- 离线交互网页嵌入结果区，点击销轴热点后显示“已探索 1 / 1”，可播放动画。
- 人工新建球体、点击表面定位 5mm 区域、拆件：1 对象 → 2 对象，总面数保持 1280。
- 宽/窄侧栏切换；结果区与任务列表独立滚动，窄侧栏将结果置前。控制台检查没有错误。
- 已安装版本加载原五件 2,663,830 面模型，检查 600 / 1200 像素宽度；首次进入无任务时直接显示完整表单，避免空预览占据首屏。临时网页测试标签与隔离测试服务已关闭。
- 前端调度测试验证静止不持续渲染、隐藏停止、144Hz resize 事件最多触发约 30 次/秒绘制，稳定后恢复清晰度。该数据是调度器测试，不是整台 Codex 的 GPU 帧率测量。

原生 MCP App 的右侧入口元数据和 `studio_open` 调用已核验，**未完成 Codex 原生窗口的视觉验收**：Computer Use 明确禁止控制 `com.openai.codex`。上述浏览器测试不能替代宿主窗口拖拽的帧率测试；没有尝试绕过该限制。

## 本机安装

源仓为 `~/code/codex_plugin`；已将实现同步到 personal marketplace 指向的 `~/plugins/print-prep`，然后执行 `codex plugin add print-prep@personal`。同步前检查了相对旧安装缓存的差异，并备份被覆盖文件至运行根 `install-backup/`。原机器配置 `.mcp.json` 和用户工程保留。

Blender 5.1.2 和 CadQuery/OCP 可用；完整本地 Python 环境约 1.4 GB。插件更新后需要新开 Codex 任务来加载新增 MCP 工具和 skill；当前任务里已加载的旧工具 schema 不会因替换磁盘文件自动更新。

## 失败和边界保留

1. 旧静态编辑减面在真实脸件上仍可能触发水密门禁；没有降低门槛。本轮提供实际通过闭合检查的 Blender 替代路线。
2. Bambu 对部分极近顶点的工程写出仍会损坏拓扑。新增拦截防止误报保真，不能说已经修好了 Bambu。原始几何 3MF 可以独立保留。
3. 第一版权重修复把 glTF 骨骼显示辅助网格当皮肤，已排除；重定向输出曾额外导出源动作，已移除无用户动作，最终只含目标 clip。早期失败任务和日志保留。
4. 一次测试传了小写 root/tip，而模型实际骨名 Root/Tip，任务明确拒绝；改用已读取的骨名后通过，没有放宽名称检查。
5. Meshy/Tripo 没有真实账户配置，本轮未发起收费生成；模拟 HTTP 通过不等于真实云端质量验收。
6. 22 个模板和若干真实样件不等于 参照产品 41 个工作流均通过；人像感知/身份拟合、通用动作接地、完整游戏和品类制造套件仍需专项实现与验收。

## 复跑

```bash
uv run --frozen pytest -m 'not bambu' -q
node --test tests/*.mjs
npm run build:app
uv run --frozen python scripts/verify_task_runtime.py --out /absolute/new/check-directory
```

最后一条要求 Blender 已安装，目录必须是新目录，输出写在仓外；不会使用任何云端 API。
