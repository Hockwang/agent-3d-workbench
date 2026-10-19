# Assembly 接入与本机路线交付记录

## 结果

Assembly 五项操作的适配器、UI 和收件流程已验证；真实服务仍需按部署完成鉴权和生成验收；协议、配置与边界见 [接入文档](../ASSEMBLY_API.md)。当前工作台默认使用 GPT 和本机工具，不要求生成 API。

## 改动文件与原因

| 文件 | 改动与原因 |
|---|---|
| `studio/assembly_service.py`、`studio/services.py` | 按工作流协议处理模板、参数、外层状态码、一次提交、按 ID 收件与 ZIP；凭据使用环境变量引用，兼容独立的 OneAPI 推理 appkey |
| `studio/tasks.py`、`studio/task_schema.py` | 公开本机路线和可选服务能力；拒绝误传本机模型给远端，设置合适的异步等待时间 |
| `studio/web/tasks.js`、`studio/web/tasks.css`、`studio/app/dist/studio.html` | 默认本机方式，增加 GPT 使用说明与五项服务参数；远端方式隐藏本机输入，修正 hidden 标签被 display 覆盖的问题 |
| `skills/print-prep/SKILL.md`、`README.md`、`docs/ASSEMBLY_API.md` | 说明默认路线、远端契约、计费与能力边界，不把动作生成说成模型生成 |
| `tests/test_assembly_service.py` | 29 项契约、异常恢复、资产包与凭据隔离验证 |
| `scripts/verify_local_first.py` | 可复现的自定义 CAD→Blender→编辑器例子，不受现有模板数量限制 |
| `.codex-plugin/plugin.json` | 安装版本更新为 `0.6.0+codex.20260922073412` |

## 新鲜验证

- `uv run --frozen pytest -m 'not bambu' -q`：339 passed，2 deselected；真实打印机测试未运行。
- `node --test tests/*.mjs`：62 passed。
- `npm run build:app`：通过，打包 UI 1,775,079 bytes。
- 本机例子：CAD 4.33 秒；Blender 渲染、GLB 和工程交付 1.79 秒，不含 GPT 思考和工具通信。80×40×50 mm、壁厚 4 mm、两孔直径 6 mm；STEP 体积 27293.80532894153 mm³，理论体积 27293.805328941537 mm³；水密，Euler=-2；接回编辑成功，实际 PNG 已查看。
- 隔离 MCP App 宿主：默认本机入口、Assembly 五项操作、动作参数、未配置禁用、本机文件控件隐藏/恢复均验证；用 UI 加入支架 GLB，点击接回编辑后显示 80.00×40.00×50.00 mm。
- 2,044 面支架，DPR=2，4 秒模拟工作区缩放：389 帧，帧间隔 P95=17.5 ms，最大 26.5 ms，0 个超过 50 ms 的长任务，2 次 canvas 尺寸写入，3 次绘制调用。该结果不覆盖重模型、加载期间或 Codex 原生窗口边缘拖动。
- CLI 安装成功；12 个改动实现/资源文件与安装缓存哈希一致。分发 README 保留原先独立的来历段落，只加入本次说明。运行后端重启前确认无活动任务，重启后两份用户工程元数据哈希完全一致，原有 1 个编辑对象保留。
- 新 stdio MCP 连接读取安装缓存的 capabilities 和 UI。旧的已打开 MCP 连接可能保留旧 UI 字节；本次未取得 Codex 原生窗口的视觉验收。

本机证据目录：`~/test/claude-blender/runs/workbench-assembly-api-20260922/`，包括 `pytest.log`、`node-tests.log`、`build.log`、`local-first-v2/results.json`、`local-first-v2/editor-import.json`、`installed-source-match.json`、`installed-capabilities.json`、`installed-protocol.json` 和用户工程重启前后快照。证据与测试产物不随源码提交。

## 公共发布说明

历史部署诊断与私人运行标识不随插件分发。上述为当时的本地协议验证，当前预览版验证见 [PLUGIN_PREVIEW](../PLUGIN_PREVIEW.md)。
