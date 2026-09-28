# MCP 工作台重连修复（0.8.4）

用户截图中只有黑底和“请在对话中重新打开本任务的 3D 工作台”提示。
后端实时读取成功，34 个对象、revision 21，工程文件没有丢失。

## 根因与修复

- `studio/app/main.js` 原重连按钮在 `!connected || !workspaceId` 时直接返回，
  没有再次调用 `app.connect()`，因此首次握手失败后无法自恢复。
  现在按钮执行真正握手，合并并发尝试，失败保留原始错误；握手有 15 秒超时。
- 旧入口只接工具结果中的任务身份，忽略宿主提前送达的 `tool-input`。
  现在在连接前注册该事件，接受宿主明确提供的任务 ID；仍拒绝切换为另一任务。
- 断开时暂停工作区，重连后重新应用宿主显示状态并恢复渲染和轮询。
  不重建已存在的工作区、不猜测其他任务身份、不修改工程模型。
- `.codex-plugin/plugin.json` 和 `studio/mcp_server.py` 更新为 0.8.4；重建 `studio/app/dist/studio.html`。

截图本身不能区分最初是宿主握手失败还是任务身份缺失。本轮确认并修复的是上述
可复现的恢复缺陷，不能把隔离宿主测试表述为已直接观察原生 Codex 右侧画面。

## 验证

- `tests/test_app_connection.mjs`：先复现失败，再验证首次握手失败后重试、延迟身份输入、
  拒绝跨任务绑定、并发点击合并、连接中断后恢复原工作区及活动状态。
- 源码 Node 回归 96 项通过；安装源（保留其他任务增量）Node 97 项通过。
- `tests/test_mcp_server.py tests/test_workspaces.py`：真实 stdio MCP 与工作区回归 26 项通过。
- Chrome / Metal 隔离 iframe 加真实后端，只读当前工程：模拟首次握手返回错误，点击重连后
  成功显示 34 个对象；无初始任务 ID 时，单独送达宿主 tool-input 也能恢复完整界面。
  两种场景均无页面错误、错误横幅消失。源码与安装构建均验证，真实截图已查看。
- 工程 SHA-256 前后一致：
  `864336b97ae74ee21236a01021c8228e92cb643f00595762fdbb399801723865`。

本机证据：`~/test/studio-reconnect-20260923`。

## 安装后仍需刷新旧 MCP 连接

16:46 核验：Codex 的四个 Print Prep MCP 进程启动于 14:15–14:17，均早于新版构建（16:43）。
`studio/app_resources.py` 在模块加载时冻结 `UI_HTML/UI_URI`，因此 CLI 安装更新磁盘文件不会
更新旧服务内存里的页面；单纯再次 `studio_open` 可能继续返回旧入口。

按 [官方 App Server 文档](https://learn.chatgpt.com/docs/app-server#api-overview) 核对了
`config/mcpServer/reload`。本机官方 `codex app-server proxy` 无法连接默认 control socket
（该 socket 不存在，桌面进程也没有公开 `--listen` 入口），本轮没有强杀其他任务的 MCP 进程，
也没有重启整个 Codex。需要用户完整退出并重新启动 Codex，之后从当前任务重新打开工作台。
这项原生恢复仍待用户确认，前面的隔离宿主验收不能替代它。

修复已本地提交；GitLab SSH 22 超时，HTTPS 443 TLS 连接也失败，远端同步未完成。

## 用户再次报告黑屏后的复核（0.8.5）

用户新截图中左侧卡片已读取 34 个对象，但右侧仍显示 0.8.4 已删除的旧提示。
再次核验，四个 MCP 进程仍是 14:15–14:17 启动。这不能表述成原生面板已恢复。

本次先经 `studio_open(presentation="browser", workspace_id=当前任务)` 取得同一后端，
用 Codex 内置浏览器在右侧打开兼容工作台。已通过实际浏览器截图看到皮卡丘头壳、
34 个对象、3,872,446 面与 8 条操作记录，标签已保留；不是隔离 iframe 的模拟截图。
工程 revision 21、上述 SHA-256 未变。该视图仍走本机 HTTP，属于临时恢复，
不等于原生 MCP App 面板或选择进入聊天上下文的链路已经验收。

进一步修复升级时冻结界面的问题：

- `studio/app_resources.py`：移除进程启动时固定的 `UI_HTML/UI_URI`，请求时读取一份界面快照，
  从同一份内容计算 URI 和面板 session 标识；旧 URI 仍兼容读取当前资源。
- `studio/mcp_server.py`：工具描述、资源列表和打开结果采用新快照；只改变界面身份，
  不改变 workspace 或模型。版本升为 0.8.5。
- `scripts/build_app.mjs`：构建写临时文件后原子替换，避免运行中的服务读到半份 HTML。
- `tests/test_app_resource_reload.py`：先复现旧实现在同一进程读取旧资源失败，再验证更新后的
  工具描述、资源列表、打开结果、面板身份及历史 URI；全过程保持同一任务。
- `tests/test_mcp_server.py`：相应更新资源契约断言；manifest、前端版本与构建同步更新。

新鲜验证：源码后端定向 27 项通过；源码及安装源各 4 项重连测试通过，安装源升级回归
1 项通过；两处自包含 HTML 均重新构建并通过内联 JavaScript 解析。

边界：0.8.5 的资源按需读取仅在宿主加载这版 Python 服务代码后生效，不能修改目前旧进程
内存里的 Python 代码，也不会强行刷新已有 iframe。没有操作宿主私有 IPC、强杀其他任务
或重启整个 Codex。当前可确认的是兼容视图恢复，原生标签恢复仍待宿主重新加载后验证。
