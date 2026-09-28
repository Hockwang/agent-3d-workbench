# 3D 服务自助配置与 Seed3D 验证 — 2026-09-22

本轮增加专业 API 的连接管理，不建立通用 LLM 网关。Hunyuan 既有真实生成/Part 验证见 [原报告](../HUNYUAN_API.md)。

## Seed3D 真实服务

- 使用已有公司专业服务凭据，只提交一次 `doubao-seed3d-2.0`。参考图来自本机 Blender 生成的木椅，无用户私有素材。
- 任务 `a2fd7e1ff4b54e15a000225a2a8fb8de`：294.827 秒完成。结果是 21,514,760 字节 GLB，1 个 mesh、499,986 面，包含纹理。
- GLB SHA256：`7112e39b39b4d63400d2f9d06df1bdad88a1ffb4f4e3abc9178078f7bf6171db`。
- 已进入工作台同一个 TaskPreview，并在 900/1200/1440 宽度完成加载和实际 WebGL 绘制；无 pageerror。初次截图必须等待 resize 防抖结束和非零三角形绘制，不能仅凭 canvas 已挂载认定模型可见。
- 观察任务 `ca414491445b4a0bae7c4fecc37dfbf3` 渲染 front/iso/top，已人工式读图确认木椅主体、椅背栏杆和纹理可见。报告 SHA256：`faf12ad1cde3e5a58a15aff8499e6a0502cd589c564c21480c6d83761d35566b`。
- 评价为 `needs_review`：这是接入链路验收；没有验证真实尺寸、机械结构或打印质量。模型是单网格，不能视为已有语义零件。几何统计 `all_watertight=false`，没有把生成成功等同于可制造。

本次直接调用专业 3D 模型，没有额外 GPT API 调用。未获得本轮可靠账单金额，不推算成本。

## 自动与界面验证

- Python 全量（排除真实 Bambu 打印机环境测试）：383 passed，2 deselected（120.95 秒）。
- Node 现有回归：62 passed。
- `npm run build:app`、`git diff --check` 通过。
- Playwright：添加连接、加密提交、保存/选择、只读鉴权、改变地址后不沿用旧凭据、删除以及 600/900/1100/1440 宽度；请求体未出现测试密钥明文。
- 密钥测试：长密钥跨 JS/Python 解密、改地址重放/篡改/过期拒绝、仓外 0600 保存、公开结果和任务快照不含 key、进程重启后凭据引用可解析、并发写冲突、旧配置参数保留。
- Seed3D HTTP 契约：ZIP 安全收件、下载失败后 resume 只有一次 POST、模糊提交不自动重试、CDN 请求和交付产物不带 API key。

此前已有 Meshy/Tripo 适配继续通过本地契约回归；没有它们的真实账户 key，本轮未跑官方付费生成。连接测试和真实生成分开记录。浏览器尺寸测试不能代替原生 Codex 窗口拖拽性能实测。

详细本机证据：`~/test/claude-blender/runs/workbench-byok-20260922/`，包含 `pytest.log`、`node-tests.log`、`ui-check.json`、`preview-check.json`、界面截图及真实任务目录。私有 CDN URL 缓存只保留在本机任务目录，不提交 Git。
