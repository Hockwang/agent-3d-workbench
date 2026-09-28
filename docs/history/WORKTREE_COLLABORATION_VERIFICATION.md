# 零件协作与 XYZ 控件交付记录

版本：0.7.2+codex.20260922204700（2026-09-22）。用户已确认同 worktree 共享模型、聊天视图独立的方案。

## 改动文件与原因

| 文件 | 改动与目的 |
|---|---|
| `studio/web/editor-viewport.js` | 独立中心代理修正 XYZ 原点；世界增量转回对象坐标；新模型未加载完成时禁止拖动旧预览；视口零件右键 |
| `studio/web/editor.js`、`editor.css`、`part-chat.js` | 统一右键菜单与零件分支请求；共享界面每秒同步，独立选区；续租/释放；外部重命名同步且保护未提交草稿 |
| `studio/collaboration.py` | 原子共享事务、一次性邀请、工作目录校验、逐件版本、5 分钟写租约、范围约束、每聊天连续撤销/重做 |
| `studio/workspaces.py` | session → 工程显式绑定，启动/绑定互斥，不覆盖已有工程；模型 fork 清除协作身份 |
| `studio/editor.py`、`editor_schema.py` | 共享事务接入；replace 保留零件 ID 和文件坐标，支持外部修缮回写 |
| `studio/branches.py` | 共享工程合入遵循零件租约、版本与会话撤销 |
| `studio/server.py`、`mcp_server.py` | HTTP/MCP 传聊天身份、协作入口、共享工程中的独立 widget 身份、带绑定的浏览器入口 |
| `studio/app/api.js`、`studio/web/api.js` | 原生 ui/message 分支请求、协作调用、HTTP 身份透传 |
| `studio/task_schema.py`、`studio/web/tasks.js` | 任务产物可替换选中零件，携带逐件版本 |
| `studio/app/dist/studio.html` | 随插件分发的自包含界面重新构建 |
| `.codex-plugin/plugin.json`、`skills/print-prep/SKILL.md` | 新版本与原生聊天分支操作协议 |
| `README.md`、`docs/SESSION_WORKSPACES.md`、`docs/WORKTREE_COLLABORATION*.md` | 最新协作契约、确认与验证记录 |
| `tests/test_editor_pivot.mjs`、`test_collaboration.py`、`test_workspaces.py`、`test_mcp_api.mjs`、`test_mcp_server.py` | 控件、持久化、冲突/租约、撤销、GLB 修缮回写、共享/隔离、界面请求与宿主身份回归 |

## 新鲜验证

- canonical 全量 Python：398 passed、2 skipped；Node：74 passed；自包含 App 构建通过，git diff --check 无误。
- 安装源合并后：158 项 Python 测试通过，包含零件协作和已有头壳配方；没有覆盖另一任务新增的头壳代码。
- 真实浏览器/WebGL：偏置几何中心 `[35,25,20]`，root 仍 `[0,0,0]`，XYZ 控件在中心。真实鼠标拖动 X 后成功提交 7.346 mm 位移。
- 双界面实测同步 798 ms，另一聊天镜头与选区保持不变。窗口宽度 700/1100/1440 后仍渲染，页面错误 0。
- 模拟 MCP 宿主内嵌界面：右键点击发送 1 条包含零件身份的 ui/message，请求原生 same-directory fork；未主动创建用户任务。旧无绑定入口继续显示恢复提示。
- 新安装包独立 MCP 连接：24 工具，包含 invite/join/renew/release，能打开本任务已有 34 对象工程。仅重启本任务空闲后台，project.json SHA-256 前后不变。

## 运行限制

- 同步发生在成功提交后，活动编辑界面约 1 秒轮询；没有逐帧广播尚未提交的拖动。
- 桌面真正创建新任务由用户右键触发后执行；本轮自动验证到宿主消息边界，未伪称已经替用户创建测试聊天。
- 已打开的 Codex MCP 连接缓存旧工具和 UI 字节。安装后需要重载插件或重启 Codex；本轮未中断其他活跃任务的 MCP 连接。
- 协作前的旧全工程 undo 快照保留在文件中，开启协作后的撤销使用新的按会话逆操作，不将旧全工程快照用于共享撤销。
- 安装源还有另一任务的头壳功能，因此安装包在保留它们的源码上重建，与本次 canonical 修复分支的 bundle 不同。

本机证据目录：`~/test/claude-blender/runs/workbench-collab-20260922`。包含 pytest.log、node-tests.log、installed-tests.log、ui-check.json、embedded-check.json、installed-mcp.json 与截图。
