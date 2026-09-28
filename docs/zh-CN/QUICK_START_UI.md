[English](../QUICK_START_UI.md)

# 找到模型和生成成果

在聊天中让 Agent 打开 3D 工作台。Codex 聊天卡片的「在右侧打开模型」按钮会打开编辑器。
卡片和工作台会显示项目名称；其他项目请从对应的聊天打开。
也可以直接打开聊天右侧的原生「3D 工作台」入口：插件使用本次请求的 `_meta.threadId`
自动绑定当前聊天，无需用户复制或填写 ID。

如果更新后原生入口仍显示「未绑定工作台」，请退出并重新打开 Codex，让 Python MCP
进程加载新代码。错误页的「重试」只重发请求，不会重载进程；模型和成果仍保存在磁盘上。
重启前可让 Agent 打开当前聊天的工作台，显式传入 ID 的入口兼容旧进程。

工作区标签下方的入口栏始终可用：

- **当前模型**：返回可编辑场景并适配视图。查看生成成果不会重复导入模型。
- **打开文件**：直接弹出本地文件选择器，支持 GLB、STL 等模型。宿主不支持上传时，展开本地路径输入。
- **最近成果**：显示当前项目／工作区已完成的建模与加工成果。按成果名称或文件名搜索，再选「查看结果」或「输出文件」。观察记录仍在「观察与测评」。
- **附加选区到对话**（仅 Codex 面板）：选中部件后，点击才将选区放入对话输入框；打开或导入模型不会自动添加。没有选区时按钮禁用。

选区卡片是上下文快照。更换或清空选区、修改模型或关闭面板时，会移除该面板添加的旧快照。
旧版两个面板可能各遗留一张卡片，可点击各自的 **×** 清除，不会删除模型。
关闭旧工作台面板并重新打开即可加载这项前端修复，无需为此重启 MCP 进程。

输出文件优先显示主模型／交互页面及 ZIP 包。「文件位置」可展开并选中本地路径，「保存」可下载文件。
「接回编辑」会往当前场景添加模型；模型已经导入时，点击顶部「当前模型」即可返回。

首次打开空白工作区时，中心直接显示「打开文件」，暂不使用的属性和交付面板会收起。
已有的面板展开偏好会保留。

`studio_open(presentation="browser", task_id="…")` 返回的浏览器链接包含目标工作区和任务，
打开后直接定位这份成果。已经运行的 MCP 进程需在下次重启时加载这项 Python 改动；网页修改刷新即可生效。

## 本轮改动与验证（2026-09-28）

| 文件 | 改动与原因 |
| --- | --- |
| `studio/web/quick-access.js`、`workspace.js`、`studio-layout.css` | 常驻模型／文件／成果入口，项目名称、成果搜索、窄屏布局；取代仅靠底部更新提示找成果。 |
| `studio/web/editor.js`、`studio-shell.js` | 空白首页直接选文件，折叠暂不需要的面板；复用原有导入流程。 |
| `studio/web/tasks.js` | 显示具体成果名称，主文件前置，可展开本地路径；从最近成果直达预览或文件清单。 |
| `studio/web/app.js`、`studio/shell/mcp_server.py` | 浏览器打开保留目标模式和任务，同时兼容旧的默认 URL。 |
| `studio/app/index.html`、`main.js`、`style.css`、`studio/web/locales/{zh-CN,en}.js` | 聊天卡片明确“在右侧打开模型”，显示项目名称，中英文本同步。 |
| `studio/web/i18n.js`、`sandboxed-html.js` | 修复沙箱内读取 localStorage 属性就抛异常的根因；对旧的冻结 HTML 加载时做无存储兼容，保持原文件和 iframe 沙箱权限。 |
| `studio/app/dist/{studio,delivery}.html` | 重建 MCP App 和后续离线交付模板。 |
| `tests/test_quick_access.mjs`、`test_browser_entry.py`、`test_i18n_dom.mjs`、`test_sandboxed_html.mjs` | 验证任务路由、时间、文件优先级、受限存储和冻结产物兼容。 |

实际浏览器验收：空白工作区点击顶部打开文件 → 导入梦幻 GLB（11 部件，638,734 面）；
成果搜索 → 输出文件；带任务的浏览器链接 → 梦幻交互预览；返回当前模型保持 11 部件。
沙箱预览的 localStorage 异常先用回归测试复现，再修正；原始 HTML 与模型文件不改写。
自动化：`npm test` 133 项通过；`uv run pytest tests/test_browser_entry.py tests/test_app_resource_reload.py tests/test_mcp_server.py -q` 27 项通过；App 与离线模板构建成功，`git diff --check` 无错误。

本轮未 commit、push 或发布。

## 原生入口修复与验证（2026-09-28）

根因：原生入口以空 `arguments` 调用 `studio_open`，聊天身份由 Codex 放在 MCP
`_meta.threadId` 中。服务端之前只读 `arguments.workspace_id` 和配置环境变量，在返回
界面资源前就拒绝了请求。此前浏览器验收没有覆盖此入口，测试夹具还预设了
`PRINT_PREP_WORKSPACE_ID`，掩盖了缺失的绑定逻辑。

- `studio/shell/mcp_server.py`：在 shell 层统一读取请求身份，供工具和模型资源读取使用。
  显式参数优先，其次是本次请求的宿主 ID，再其次是其他 MCP 宿主的环境变量配置。
  不记住连接的「上次工作区」，不取最近聊天，不修改核心层或几何文件。
- `tests/test_native_entry.py`：无 fallback 环境的真实 stdio 调用，覆盖空参数打开、
  UI 操作、模型资源读取、重复打开、跨聊天隔离、身份优先级和非法 ID 拒绝。
- 协议依据：[Codex 官方 MCP tool 测试](https://github.com/openai/codex/blob/main/codex-rs/app-server/tests/suite/v2/mcp_tool.rs)
  的 `context.meta["threadId"]`，并用本机桌面自带的 Codex CLI 实测确认。

验证：新增测试先复现相同「未绑定工作台」错误。修复后，原生入口、浏览器入口、UI
资源更新、MCP 服务与工作区隔离共 45 项回归通过。另在隔离的临时 CODEX_HOME 中启动
真实 `codex app-server`，用已有空工作台夹具调用 `mcpServer/tool/call`：
`arguments={}` 且不手工注入 MCP metadata，返回工作区与宿主 thread ID 一致，
界面资源已绑定，重复打开的 widget session 一致；未启动模型轮次。

桌面原生点击验收仍待重启后完成：本会话的 UI 自动化禁止操作 Codex 自身界面。
当前聊天显式 ID 的实际打开调用成功，读回 11 个对象、revision 1；这项不等同于
原生空参数入口的点击验收。

## 选区附件修复与验证（2026-09-28）

现象：画布没有选中对象，输入框仍显示两张相同的「模型编辑选区」卡片。
当前后端读回 `selection=[]`、11 个对象、revision 1；卡片是两个 UI 实例遗留的快照。
旧逻辑在恢复／导入选区和状态轮询时自动发送上下文，新实例读取空选区时不主动清除，
关闭时也未等待在途请求并清除附件。

- `studio/app/selection-context.js`：状态更新只记住当前选区，用户显式点击才添加；
  选区、模式、模型版本变化清除旧快照；清除与在途添加串行，避免关闭后卡片再次出现。
- `studio/app/main.js`：连接与重连后清除本实例旧上下文，关闭时等待清除完成。
- `studio/web/quick-access.js`、`workspace.js`、`studio-layout.css`、中英 locale：
  Codex 顶部增加「附加选区到对话」按钮，无选区时禁用，窄屏可换行；浏览器不显示聊天专用按钮。
- `tests/test_selection_context.mjs`、`test_app_connection.mjs`、`test_quick_access.mjs`：
  覆盖两个实例恢复、显式添加、轮询、清空、切换模式、重连及在途关闭。

验证：两个回归先复现失败；修复后 `npm test` 139 项通过，App 构建成功。
浏览器使用真实组件、模拟宿主传输的夹具，实际点击「选中部件 → 附加 → 清空」，确认
只在显式点击时添加并在清空后移除；这不等同于 Codex 原生输入框的点击验收。
现有旧实例卡片可能需手动点 ×；没有改动模型、几何或后端选区。
