# 0.8.0 文件夹工程与 Lux3D 验证

日期：2026-09-23。范围是本轮文件夹工程、Lux3D 接入和统一 GLB 预览；不是对所有历史功能或所有 Aholo 使用场景的重新验收。

## 改动与原因

| 文件 | 行为与原因 |
| --- | --- |
| `studio/projects.py`、`workspaces.py`、`mcp_server.py` | 从官方 Codex `thread/read` 获取目录，新任务以文件夹归属模型；同目录共享，worktree 隔离，旧工程显式迁入，避免跨任务相互覆盖。 |
| `studio/collaboration.py`、`part_chat.py` | 保留零件聊天范围、独立选区与撤销；迟到的续租不重新夺取零件；Git 子目录聊天按项目根协作。 |
| `studio/lux3d_service.py`、`lux3d_commerce.py`、`lux3d_upload.py` | 国内/国际接口、七类操作、余额/计划报价、上传、任务对账恢复与收件校验；提交结果未知时不自动重复收费请求。 |
| `studio/web/tasks.js`、`service-settings.js`、`task_schema.py` | 人和 AI 均可配置专业 3D API、报价、启动或恢复任务，再接回现有模型编辑。 |
| `studio/web/gltf-loader.js`、三个 viewer、构建脚本与 vendor | 共用本地 Draco/Meshopt/KTX2 解码器，按需加载；离线交付支持多模型切换，动画绑定各自场景。随产物保留第三方许可。 |

详细契约：[文件夹工程](../FOLDER_PROJECTS.md)、[Aholo 能力对照及限制](../LUX3D.md)。

## 验证结果

- 发布仓完整 Python 回归：440 passed / 2 skipped；Node：88 passed。随后接口契约补充与可选 prompt 修改后，Lux3D 定向回归 21 passed。
- 安装源保留其他任务增量并合并后：Python 471 passed / 2 skipped，Node 89 passed。不是用发布仓文件整树覆盖安装源。
- 提交前再次运行文件夹工程、Lux3D、协作与零件聊天的定向回归：46 passed（18.58 秒）。
- `npm run build:app` 成功；`git diff --check` 通过。Draco/Basis 运行数据从已锁定 Three.js 包生成。
- 双页面 MCP App iframe + 真实 Studio 后台 + 本地 Lux3D fixture：余额 → 报价 → 一次生成 POST → 下载 → 接回编辑 → 另一任务改名 → 原任务同步。实测同步 534 ms，页面错误 0，五种视口尺寸切换后模型仍可见。该结果不代表 Codex 原生窗口拖动性能已经全面验收。
- 压缩 GLB：Khronos Draco Box、Meshopt 三角形、KTX2 贴图三角形均完成加载与渲染；离线 HTML 切换模型正常，画布像素非空，外部请求与页面错误均为 0。
- 通过官方宿主接口确认当前任务目录；实际已安装插件的 capabilities/services 可返回两区域 Lux3D 连接与七项操作。
- 0.8.0 已安装；两个原有工作台分别保留 34 与 60 个对象，升级前后工程文件 SHA256 不变。安装缓存的 53 个本轮文件与安装源逐一核对一致。

## 尚未验收

未在本机已查阅配置中发现 Lux3D 专用 key。国内/国际余额接口匿名访问均返回 HTTP 401，证明地址可达，**不证明账户鉴权、实际扣费或生成成功**。这些必须在配置合法的区域 key 后实测，不能用本地 fixture 代替。

Codex 原生窗口检查被 Computer Use 工具的应用访问限制拒绝；没有绕过。右侧打开请求已由 Studio 工具成功返回，但本轮压缩解码与缩放的视觉证据来自浏览器测试，宿主 CSP/原生窗口仍需实际体验验证。

当前没有 Gaussian splat viewer。压缩 GLB 可预览不等于任意复杂源可无损导入静态编辑；详见能力对照。

## 证据与升级经验

本机原始证据在 `~/test/studio-projects-lux3d-20260923`，不提交模型或账户配置：

- `merged-python-tests.log`、`merged-node-tests.log`
- `ui-evidence.json`、`ui-api-calls.json` 与 UI 截图
- `codecs/evidence.json`、压缩样本与离线交付截图
- `host-project-read.json`、`public-endpoints.json`
- `installed-files.json`、`workspace-upgrades.json`

真实工作台重启必须使用安装源自己的 uv 环境。首次升级误用了发布仓环境，其中缺少安装源额外功能所需的 scikit-image，导致 capabilities 请求断开；改用安装源环境后恢复，模型数据未变。不要因此删除安装源已有增量或在运行中直接混用不同 checkout 的 Python 环境。
