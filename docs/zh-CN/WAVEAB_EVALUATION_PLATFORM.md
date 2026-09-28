> English: [../WAVEAB_EVALUATION_PLATFORM.md](../WAVEAB_EVALUATION_PLATFORM.md)

# WaveAB 评审平台接入

工作台「观察与测评 → 路线评审」通过原平台 API 读取批次和证据、保存评价。原平台继续持有数据库、指标算法、历史与冻结报告；插件只保存连接设置、共享当前案、AI 建议和导出文件。

## 复用来源

- 仓库：评审平台是作者团队的内部服务，代码不公开；本插件只实现客户端。
- 分支：`dashboard-source-data-center-e2e`
- 已验证提交：`ebd731c125e5cc79dfff20f815a91e4120aa1e8b`
- 模型协议：`assembly-dashboard-viewer-model/v1`
- 预览复用插件已有的、源自作者研究仓库的 `assembly-scene/v1` Viewer，不复制平台的 Next.js 应用或重写指标引擎。

## 已接入的操作

| 操作 | 工作台行为 |
|---|---|
| 批次与分析 | 列出平台分析，按路线版本、Spec 等级或生成器选择 1–8 批次建立分析 |
| 结果包 | 本机选择或路径输入 ZIP，先检查，再明确四个维度与 Case 对应关系后接入 |
| Case 对照矩阵 | 每页 25 行，本页搜索；缺结果、执行状态、质量状态、人工结论分开显示 |
| C0–C4 成绩单 | 原始门禁、可信度、通过率、均值、已评／未评／异常数量、标签切片与原因 |
| 模型预览 | 1–4 个 CaseRun，原尺度、坐标、刚体关节与版本切换／并排；按需创建一个 Viewer |
| 人工评价 | 结论、问题标签、依据、原平台评价历史，保存到原 CaseRun |
| 五维比较 | 每版本的语义、结构、关节、运动、几何评分，以及 Case 有效性和推荐依据 |
| 自动评测 | 调用平台异步分析任务，在当前工作台查询状态 |
| 报告 | 创建确定性冻结报告，查看内容，保存 Markdown 与审核 CSV 到当前 job |
| 资料库 | 读取 Case 库、冻结测试集和问题库，当前以结构化详情展示 |
| AI | `studio_evaluation` 读取同一平台证据、共享当前案、运行检查、预览和提出评价建议 |

现阶段没有迁移平台的数据中心生产、云端批量生成、问题工单编辑、Gallery 发布、Test Set 编辑、LLM 报告生成。既有单模型 `studio_observe` 不变。

## 连接与 AI 用法

平台地址应为实际提供 `/api/health` 的服务根地址；GitLab 分支 URL 不是部署地址。可填写末尾带 `/api` 的地址。若需要 Bearer 认证，只填写服务进程已有的环境变量名；不把 token 写进 URL、工程或任务参数。重定向不转发认证。

```json
{"action":"connect","base_url":"https://实际评审平台域名","auth_env":"DASHBOARD_TOKEN"}
{"action":"catalog"}
{"action":"read","resource":"analysis","id":"平台返回的分析ID","offset":0,"limit":25}
{"action":"focus","id":"平台返回的分析ID","case_run_id":"平台返回的CaseRunID"}
{"action":"read","resource":"case"}
```

以上均为 `studio_evaluation` 入参示例，ID 必须来自实际查询。`read` 返回 `sha256`，用于后续提交。默认精简大块分析与报告，`detail:true` 保留完整证据。`preview` 返回工作台任务，用 `studio_tasks` 查询结果，不重复提交。

原平台把所有 `human_reviews` 记录计入 HUMAN 门禁，与 reviewer 名称无关。因此 AI 的 `review` 和 `compare_review` 只保存为本地建议；人在表单里「填入 AI 建议」并检查、提交后，才写入平台。AI 不调用 `studio_ui_action` 模拟人工。切换平台时清空旧平台建议，人工草稿和 AI 建议均绑定证据 SHA。

`studio_get_state.evaluation_focus` 包含当前分析、CaseRun、分页位置和操作者。人在矩阵选案，AI 能读取；AI 调用 `focus`，界面会定位到相应案，未提交的单案草稿按证据 SHA 保留。

## 数据与边界

- 请求不自动重试，避免超时后重复写入。写前重新读取证据并比对 SHA；平台自身尚无原子 `If-Match`，不能承诺挡住检查与写入瞬间来自其他客户端的竞争。
- ZIP 检查只上传到用户选定的评审平台；检查不会自动建立批次。上限 8 包、总计 90 MB。原平台负责解析、校验与去重。
- 保留 `UNKNOWN`、`NOT_EVALUATED`、`ERROR` 及缺失项；不补成零、不重新计算或放宽平台门禁。成功运行不是质量通过。
- 模型预览只接受案内自包含 GLB；保留无 visual 的中间 Link 坐标节点。支持 fixed/revolute/continuous/prismatic，其他运动类型明确拒绝。预览以平台 viewer_model 为准，不宣称覆盖 URDF mimic、物理仿真或碰撞质量。
- 取件前后核对 CaseRun SHA；评测更新与预览并发时可能拒绝旧证据，等评测结束后重新预览。预览 G/B 标记关闭，评价统一在外层表单保存。
- 预览资产总量上限 90 MB、每案最多 512 Link、一次最多 4 案。矩阵只显示一页，不为每个单元格创建 WebGL；切出页面销毁预览 iframe，静止按需渲染。
- 连接、焦点、建议、写入审计在当前 job 的 `evaluation/`；导出位于 `evaluation/exports/`，返回实际路径、字节数和 SHA。

## 2026-09-22 集成验证

使用上述提交的原 FastAPI 后端、隔离数据库与回环端口。未修改正式评审平台或用户现有 3D 工程，未调用生成或付费 LLM API。

测试资产来自已有四抽文件柜、单开门床头柜的真实 GLB 与关节声明，转换成平台接入所需 URDF ZIP。同一模型包分别放在两个测试条件中，用于验证界面与接口，**不是 WaveAB 新路线实验，也不能用于路线优劣结论**。

开发证据（intake 回执、分析、任务预览、报告、测试日志）留存在本机之外的证据目录中；正式部署地址尚待配置。

验证结果：

- `uv run --frozen pytest -q -m 'not bambu'`：307 passed，2 deselected（真实 Bambu 测试未运行）。最终预览改动后针对性回归：27 passed。
- `node --test tests/*.mjs`：61 passed；MCP stdio 验证工具发现、共享焦点、AI 建议不写 HUMAN 门禁及 App 人工提交归因。
- 原平台真实后端：两包接入、两个条件矩阵、异步评测 COMPLETED、Case 待复核评价与五维 UNKNOWN 比较回写、冻结报告 READY、Markdown/CSV 文件导出。
- 浏览器：四抽柜滑轨从 0 到 0.386 m，床头柜姿态和并排比较，AI 选案同步及两类建议填入，380/600/1000 宽度界面。600 宽度工作区 `clientWidth == scrollWidth == 589`。
- 隔离 MCP App 宿主中模拟连续缩放 4 秒：78 次 WebGL draw call、4 次画布尺寸写入、无超过 50 ms 的长任务；静止 4 秒：0 draw call、0 画布写入。此结果不等于 Codex 原生窗口拖动实测，不能据此宣称宿主卡顿已完全消除。
- 预览与自动评测并发时触发旧 CaseRun SHA 拒绝，重新生成后成功；未把旧预览继续绑定到新证据。

主要实现文件：`studio/adapters/evaluation.py`（平台适配和证据保护）、`studio/adapters/platform_preview.py`（原模型预览）、`studio/shell/evaluation_schema.py`（AI 工具）、`studio/web/evaluation.js` / `.css`（原生工作区）、`studio/web/evaluation-metrics.js`（保真显示）。
