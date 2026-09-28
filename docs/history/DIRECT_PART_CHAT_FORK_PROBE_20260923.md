# 官方 App Server 直建分支：补充实测

2026-09-23，本任务用户确认"创建"后执行。使用当前测试零件，不涉及皮卡丘模型。

## 结果

- 父任务：`01a0cc50-03fc-7fd0-b4a6-793001a66ecb`。
- 真实子任务：`01a0cc52-feda-7b12-aab7-6d2138844279`。
- 最终任务标题：`修缮 · 零件分支验收件 · 同步成功`。
- 共享工程：`01a0cc41-040a-7ae1-9b6d-e4d67e0b1277`；目录 `/path/to/user/code/model-domain-eval`。
- 子任务 scope 仅含测试零件 `e6b219ed485441018a3c0ad3e17b8211`。
- 仅创建一个分支，没有发送父任务提示词，没有执行 `turn/start`。

## 实测方法与边界

1. 使用桌面附带的官方 Codex 0.155.0-alpha.9.2 生成协议 schema；独立 App Server 只读取得当前任务身份和目录。
2. `thread/fork` 使用 `beforeTurnId` 排除当前未完成回合，并设置 `excludeTurns`、`deferGoalContinuation`。创建进程退出后另起只读连接，分支仍可读取，`ephemeral=false`，父任务来源与目录一致。
3. Codex 原生 `read_thread` 能读到新任务，`navigate_to_codex_page` 返回成功；打开后 `list_threads` 中出现该任务且状态为 idle。刚创建时第一次列表读取尚未出现，不能把 RPC 成功等同于桌面已刷新。
4. 使用共享源码现有的 `studio/part_chat.py` 协调器。为已经确认的 child ID 恢复"created、尚未绑定"操作记录，在真实浏览器工作台允许本测试工程的直接接入，再点击零件菜单，由后端完成绑定。这样验证的是首次真实 RPC 创建与后续界面恢复绑定，未额外创建第二个测试任务。
5. 界面显示"聊天分支已就绪"和"打开分支"。操作记录为 bound、仅一份记录；同一工程的两个对象的名称、资产和变换均与基线一致，模型 revision 保持 4。
6. 随后点击浏览器内的"打开分支"被 Browser Use 安全策略拦截 `codex://` 导航。没有尝试绕过；此前的原生导航验证仍有效，但本次浏览器深链点击不能记为通过。也不能由此声称 MCP iframe 的 `openLink` 已端到端验收。

## 复验工具

`scripts/probe_direct_chat.py` 是一次性验证入口，收据文件使用独占创建，已有收据时拒绝再次 fork；`--verify-only` 只核对子任务身份、来源与目录，不创建任务。

本轮接入过程发现共享源码已包含完整直建协调器、授权 UI 与测试，保留并使用该实现。此补充脚本适配它的接口，不替换协作权限或模型编辑逻辑。

证据目录：`/path/to/user/test/print-prep-direct-chat-20260923/`。

- `fork-receipt.json`：真实创建及退出后持久化收据。
- `binding-baseline.json`：绑定前的模型基线与操作 ID。
- `verification.json`：绑定、范围、模型不变与浏览器跳转限制。
- `schema/`：本机桌面 Codex 生成的官方协议 schema。

## 验证

最终运行：Python 零件聊天、工作区、MCP 与协作回归 42 项通过（34.20 秒），Node 聊天控制器/MCP API 7 项通过；`npm run build:app` 成功。脚本语法检查通过，已有收据拒绝再次创建的实跑检查通过且收据 SHA 不变。真实分支在桌面可读、可打开，工作台恢复绑定实测通过；浏览器深链限制如上。
