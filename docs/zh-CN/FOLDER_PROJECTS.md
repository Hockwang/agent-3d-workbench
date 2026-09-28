> English: [../FOLDER_PROJECTS.md](../FOLDER_PROJECTS.md)

# 按文件夹管理 3D 工程

2026-09-23，用户确认以项目文件夹作为模型与场景的所有者，同目录任务协作，新 worktree 隔离。

## 使用

- 在 Codex 项目中创建的新任务，第一次调用 Studio 时通过官方 `thread/read` 读取真实 cwd。Git 仓内子目录归到当前 worktree 根；普通目录使用其绝对路径。
- 同一目录的普通任务连接同一工程、后台与资产。模型编辑提交后，其他打开的编辑界面约每秒同步；拖动过程只本地预览。
- 每个任务仍传自己的 `workspace_id=CODEX_THREAD_ID`。选择、撤销/重做和零件 scope 独立；相机属于当前页面。不能借用别人的任务 ID 绕过范围或写锁。
- 一个零件同时只有一个编辑者持有租约。不同零件可并行修改；旧页面迟到的续租不能重新取得已释放的零件。修改仍需 `expected_versions` 与 `expected_revision`。
- 右键创建的零件聊天继续保留指定零件 scope；自动连接、重连、打开项目不会把它扩大到整个场景。
- UI「工程与交付」显示项目目录。普通目录不需要 Git，也不需要新增 GPT API。

`studio_workspaces(action="project")` 查看当前绑定；`action="open_project", worktree="/绝对目录"` 显式打开。`list` 包含 folder、owner_workspace_id、revision 和对象数。当前任务已经绑定另一目录时拒绝切换，避免旧面板对新工程提交操作。

## 存储

模型数据在项目内：

```text
<folder>/.3dstudio/project.json           # 工程入口
<folder>/.3dstudio/job/workbench/         # 场景、资产、动作、历史
<folder>/.3dstudio/job/tasks/             # 建模任务与产物
~/.print-prep/workspaces/project-<hash>/  # 端口、访问令牌、目录位置
~/.print-prep/workspaces/<task>/          # 任务绑定和本地聊天接入许可
```

运行 ID 从规范化目录计算；两个 worktree 即使文件完全相同，也不会连接同一后台。拒绝 `.3dstudio/job` 软链接到另一目录。复制的工程首次打开时清除旧目录的成员、租约与撤销，保留模型和资产。项目可以搬移后重新打开；旧任务绑定仍指向旧路径，不静默重定向。

`job/tasks` 是工作资料，可能含原始输入 URL、临时请求和日志；不要直接把整个目录当公开交付包。对外使用 `save`、`export` 或离线成果模板。专业服务 key 与本机端口令牌不写入项目入口或模型交付包。

## 原工程与模型分支

旧 session 工程与显式聊天绑定优先保留，不自动合并同目录的历史模型。迁入文件夹需显式 `open_project(source_id=当前任务, expected_revision=原版本, worktree=空目录)`；复制模型与动作资产，旧文件不变。不会搬迁旧生成任务、打印排盘或外部 `.blend` 工作目录。

隔离试验：在另一个目录/worktree 的新任务首次打开前，执行 `open_project(source_id=来源任务或list返回的工程ID, expected_revision=来源版本, worktree=目标空目录)`。保留分支基线，修改不会回写来源；`merge(expected_revision=来源当前版本)` 逐零件检查冲突，再显式合入。旧 `fork` 仍可创建 session 存储的副本。

直接用 Git 复制已有 `.3dstudio` 会得到独立场景，但不自动生成 Studio 的合入基线；要用 Studio `merge`，应使用上述显式 source_id 分支。当前没有自动 rebase 或几何冲突融合。

## 验证

`tests/test_projects.py` 覆盖并发连接、独立选区与撤销、同件冲突、重启恢复、旧源哈希不变、scope 不扩大、目录复制隔离、从工程 ID 分支合入与软链接拒绝。`tests/test_part_chat.py` 覆盖 Git 子目录中的聊天仍在原 cwd fork，并加入项目根的零件范围。

双页面 MCP App 联调：报价→模拟生成→收件→编辑导入→另会话改名→原会话更新，实测同步 534 ms；连续改变窗口大小未白屏。它验证 UI 与真实 Studio 后台协作，生成提供方为本地测试服务。
