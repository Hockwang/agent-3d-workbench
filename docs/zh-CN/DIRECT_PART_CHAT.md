> English: [../DIRECT_PART_CHAT.md](../DIRECT_PART_CHAT.md)

# 直接创建零件聊天分支

2026-09-23：按用户确认的本地桥接方案实施。首次在零件右键菜单选择「创建聊天分支」，允许当前工程的本地接入后，由程序创建真实 Codex 分支并绑定同一工程及该零件。父任务不收到提示词；创建不执行 `turn/start`，有活动目标时通过 `deferGoalContinuation` 暂不自动接续。用户打开分支后输入修缮要求。

## 宿主支持

| 能力 | Codex 桌面端（侧栏面板） | 浏览器页面（任意 MCP 宿主，例如 Claude Code） | 纯 MCP 客户端（无页面） |
|---|---|---|---|
| 创建分支（右键「创建聊天分支」） | 是 | 只有页面属于某个 Codex 任务时可以：`create` 把工作区 id 当父线程读（`studio/shell/part_chat.py`），Claude Code 固定的 `claude-code` 在 `allow`/`create` 就会失败，只有 `deny` 能走 | 否：没有视口可右键；`studio_part_chat` MCP 工具标了 app-only，具体宿主是否会因此隐藏它未验证 |
| 打开分支（deep link） | 是，走 `ui/open-link` | 只对从 Codex 任务创建的分支有效，且本机 Codex 桌面端已注册 `codex://` 处理器 | 否：没有界面打开返回的 URL |
| 授权 / 撤销 | 是，走设置对话框 | 是，同一对话框、同一本机 HTTP 接口 | 未验证：没有对话框渲染，直接调工具未测试过 |
| Codex CLI 缺失或版本过旧 | 各宿主一致：`status` 报 `available: false`；`create` 会抛错 | 一致 | 一致 |

对这个功能来说浏览器页面同样是 Codex 内嵌展示的那套界面，只是走本机 HTTP 而不是 MCP
工具调用。Claude Code 用户走跟场景编辑一样的入口——`studio_open(presentation='browser')`。
这整个功能本来就是为 Codex 设计的：它的存在就是为了通过官方安装的 CLI 的 App Server fork
出一条真实 Codex 线程，所以不管哪个宿主在驱动 AI，走到这条路径都需要那个 CLI，还需要一个 Codex 任务当父级；在 Claude Code 的固定工作区 id 下，`allow` 和 `create` 会失败，只有 `deny` 能成功。

## 接入与授权

- `studio/shell/codex_bridge.py` 通过已安装的官方 Codex CLI 启动短期 stdio App Server，使用 `initialize`、`thread/read`、`thread/fork`、`thread/name/set`。不用私有 IPC、数据库或伪造 rollout，不修改已有桌面进程。
- `studio_part_chat` 是 app-only MCP 工具。HTTP 入口沿用本地 token、Host/Origin 与 actor 检查。没有任意 RPC、命令或客户端指定 child ID 的入口。
- `studio_part_chat`/`studio_ui_action` 上的 `app-only` 标记只是给会尊重它的宿主看的建议性提示，本身并不能阻止模型直接调用这两个工具。真正堵住这条路的是一个按工作区分发的 nonce：`studio_open` 铸造它，只通过 MCP `CallToolResult` 的 `_meta`（键 `studio/uiNonce`）带回——这是一条只有宿主可见、绝不会出现在 `content`/`structuredContent`（模型会读这两处）里的通道。打包界面从 `studio_open` 的工具结果里取到这个 nonce，并把它带在自己发起的每一次 `studio_ui_action`/`studio_part_chat` 调用里；带对 nonce 的调用记为 actor `human`，nonce 缺失或不对的调用记为 actor `ai`（不拒绝调用本身）——对 `studio_part_chat` 而言，这意味着会撞上 `studio/shell/part_chat.py` 里既有的仅限人类闸门，以 `human_required` 被拒绝。这只堵住了 MCP 工具这一条路——也是 Codex/Claude 宿主模型经由本插件唯一走得到的路——不代表整个系统都有授权证明。浏览器页面（`studio_open(presentation='browser')`）走的是直连 HTTP，那边 `studio/shell/server.py` 的 `_actor()` 只要调用方持有本机会话 token，就会相信它带来的任意 `X-Studio-Actor` 请求头，所以一个能拿到该 token 的模型（比如带 shell）在 HTTP 侧仍能自称 `human`；这条路径按信任边界（本地 token + 请求头）记录，不是授权证明，也不在 nonce 的覆盖范围内。nonce 失效——MCP 服务器进程重启，或宿主重放了旧的 `studio_open` 结果——会表现为 `human_required`（对 `studio_ui_action` 而言则只是被记成 actor `ai`）；`studio/app/api.js` 的恢复方式是重新调一次 `studio_open` 铸造新 nonce，再重试一次失败的调用；重连按钮（`studio/app/main.js`）在每次重连时也用同样方式主动重新铸造。宿主是否真的会把 `_meta` 传到 iframe 里，目前还没有在真实 Codex/Claude 宿主上验证过；如果某个宿主把它丢了，调用会降级成 actor `ai`，而不是硬失败。
- 默认未授权。授权约束到当前任务、工程、实际目录、Codex home 与 CLI 身份；可从「聊天分支设置」撤销。撤销阻止之后的创建，不删除已有分支。已在途操作与撤销由同一任务锁串行处理。
- 原生分支由 App Server 返回。后端复验 `id/cwd/forkedFromId`，再以明确的父任务协调操作绑定；不冒充子任务请求头去调用公共 join。
- `PRINT_PREP_WORKSPACES_HOME` 保留全局工作台注册根；后台服务器自己的 `PRINT_PREP_HOME` 仍用于当前服务日志，避免绑定位置多嵌套一层。
- 本机验证 CLI 0.154.0、桌面 26.915.31945。CLI 不存在/过旧时禁用；其他版本仍需实际宿主兼容性验证，不声称所有平台已验收。

## 一致性与界面

`~/.print-prep/workspaces/<parent>/part-chat/` 保存当前授权及逐操作记录。创建阶段为 prepared → forking → created → bound；绑定失败保留 child ID，可重试绑定。请求 ID 与重复点击均去重，同一父任务同一零件复用已有分支。

- App Server 发来 `thread/started` 时立即记录 child ID；即使最终 RPC 响应丢失，重试也只绑定原分支。
- 若进程在取得 child ID 前断开，状态为 uncertain；不盲目再次 fork。官方 fork 没有幂等键，这种情况需人工核对 Codex 任务列表后处理，不能宣称跨系统 exactly-once。
- 绑定前检查邀请版本、目录、范围与零件租约。邀请过期或零件更新时，只在用户显式重试并提供最新 revision 后刷新邀请；已有独立工程的子任务不得被覆盖。
- 所有零件编辑继续由原逐对象版本、租约、scope 与撤销规则约束；子任务始终使用自己的 CODEX_THREAD_ID。
- `studio/web/part-chat.js` 提供授权、进度、结果与打开入口；没有 `ui/message` 回退。`crypto.getRandomValues` 兼容缺少 randomUUID 的 iframe。
- 「打开分支」走 MCP App `ui/open-link` 的 Codex deep link；宿主拒绝时保留可点击任务链接和真实错误。HTTP 页面走同一个协议链接。

## 验证

- 真实官方 App Server 创建原型分支；连接关闭后，用 Codex 桌面 `read_thread` 读到持久历史和父来源，`navigate_to_codex_page` 返回成功。
- 真实打包 MCP App + Chromium WebGL + 实际后端 + 实际 Codex RPC，点击拒绝→设置允许→创建→打开入口；不是 mock 创建。
- 点击创建后的任务 `01a0cc50-03fc-7fd0-b4a6-793001a66ecb` 已绑定验证工程；父消息 0、页面错误 0。子任务改验收件后父界面轮询自动显示更新，范围外改名被 scope_violation 拒绝。
- 原头壳工程未改；测试资产位于专用验证任务工作台。未自动运行新分支模型回合。
- 自动回归覆盖授权/撤销、适配身份变化、重复操作、超时未知结果、响应丢失恢复、邀请更新、目标工程保护、越界编辑及真实 MCP 子进程注册根。
- 仓外证据：`~/test/claude-blender/runs/studio-direct-part-chat-20260923/`，含 `ui-evidence.json`、`direct-child.json`、界面截图和测试输出。

## 文件与官方协议

后端：`studio/shell/codex_bridge.py`、`studio/shell/part_chat.py`、`studio/core/collaboration.py`、`studio/shell/server.py`、`studio/shell/mcp_server.py`、`studio/core/workspaces.py`、`studio/__init__.py`。
界面：`studio/web/part-chat.js`、`studio/web/editor.js`、`studio/web/editor.css`、两套 API transport 和打包 app。

协议依据：[官方 App Server 文档](https://learn.chatgpt.com/docs/app-server)，并用安装的 CLI `generate-json-schema --experimental` 核对参数。

最终验证：源码 88 项 Node、42 项 Python/MCP 回归通过；安装源保留头壳增量，89 项 Node、42 项 Python/MCP 通过。已安装 `0.7.2+codex.20260923033510`。原任务后台在确认空闲后切换到新版，60 个对象及 project.json SHA256 不变，新接口未授权状态正常。旧任务若仍持有旧 MCP/UI 缓存，需重新加载插件工具或新开任务；安装不会替换其他活跃任务的运行进程。
