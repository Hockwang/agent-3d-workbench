# print-prep v0.5 规格

v0.5 的目标：界面骨架换成自己的——「视口 + 一列流程行 + 操作记录」，人和 AI 共用同一条操作线。
v0.3 / v0.4 的「视口上的悬浮卡 + 右侧打印计划栏 + 底部操作条」整体取消。视觉沿用 v0.4 的配色与圆角。

后端的流水线（`inspect → orient → arrange → export → check`，改前一步就作废后面的步骤）本来就是这个形状，
界面只是把它照实画出来。

## 1. 界面（`studio/web/`）

- 顶部一条：文件名、件数 / 打印机、右侧「就绪 n / 6」。
- 视口：左上角是选区说明（零件名、尺寸、「AI 也看得到这个选区」），底部居中是胶囊工具条（装配 / 盘 1..n / 复位）。
- 流程：六行——模型、朝向、分盘、工艺、试切、交付。每行 = 状态点 + 名称 + 一句带数字的结论 + 谁做的。
  点一行展开它的控件，同一时间只展开一行。「一键准备」在流程标题右侧；「打开」按钮在「交付」行里。
- 行的五种状态：没做 / 正在做 / 通过 / 有警告 / 要重做（前面的步骤改了，这一步的结果作废，显示「上次是 …」）。
- 记录：人和 AI 的操作按时间排在一起，能撤销的条目带「撤销」。
- 宽度 < 860 px 单列（视口在上），≥ 860 px 两列（视口在左，流程与记录在右 384 px）。

## 2. 后端新增（`studio/server.py` 等）

### 2.1 谁做的

写接口读请求头 `X-Studio-Actor`，取值 `human` 或 `ai`，缺省按 `ai` 记。
面板里用户点出来的请求带 `human`；页面工具（WebMCP）与 stdio MCP 带 `ai`。

### 2.2 `/api/state` 新增字段

```jsonc
{
  "busy": {"op": "check", "since": "…", "actor": "ai"},                          // 原有字段，v0.5 多了 actor
  "selection": {"parts": ["arm_L"], "by": "human", "at": "2026-09-21T09:22:01Z"},   // 没选中时 parts 为 []；载入新模型后清空
  "step_actors": {"inspect": "human", "orient": "ai"},      // 只含当前仍有效的步骤
  "stale": {"arrange": {"plates": 2}, "check": {"grams_total": 196.0, "seconds_total": 45000}},
  "readiness": {"passed": 4, "total": 6, "items": [
    {"key": "model",   "status": "pass", "detail": "5 件，全部水密，放得下"},
    {"key": "orient",  "status": "pass", "detail": ""},
    {"key": "arrange", "status": "pass", "detail": ""},
    {"key": "export",  "status": "pass", "detail": ""},
    {"key": "check",   "status": "warn", "detail": "1 条警告"},
    {"key": "deliver", "status": "todo", "detail": ""}
  ]},
  "history": [                       // 新的在前，最多 50 条
    {"id": 7, "at": "…", "actor": "ai", "op": "check", "ok": true, "undoable": false, "undone": false,
     "summary": {"plates": [{"index": 1, "grams": 118.0, "seconds": 25320, "warnings": 0}],
                 "grams_total": 118.0, "seconds_total": 25320, "warnings_total": 0}}
  ]
}
```

- `stale`：某次写操作之前存在、之后因为失效级联被删掉的步骤，值是它被删之前的摘要；该步骤重新跑过就从 `stale` 里去掉；`load` 成功后整个清空。
- `readiness.items[].status`：`pass` / `warn` / `todo`。`passed` 只数 `pass`。
  - `model`：没有 inspect → todo；有零件不水密、放不下或 inspect 带警告 → warn；否则 pass。
  - `orient`：没有 → todo；任一零件的朝向结果带 `warnings` → warn；否则 pass。
  - `arrange`：没有 → todo；否则 pass。
  - `export`：没有 → todo；任一盘有 `unmatched_parts` 或 `used_slice_fallback` → warn；否则 pass。
  - `check`：没有 → todo；任一盘 `returncode != 0` 或带警告 → warn；否则 pass。
  - `deliver`：本次服务进程里成功 `send` 过（非 dry-run）→ pass；否则 todo。
- `history[].summary` 按操作给小而稳定的数字：
  - `load`：`{"parts": n, "files": [文件名…]}`
  - `orient`：`{"strategy", "shape", "manual_parts": [名字…], "overhang_mm2_before": 数或 null, "overhang_mm2_after": 数}`（所有零件 `overhang_area_mm2` 之和）
  - `arrange`：`{"mode", "gap_mm", "plates": n}`
  - `export`：`{"shape", "process_preset", "plates": n}`
  - `check`：见上例
  - `send`：`{"plates": [盘号…], "dry_run": bool}`
  - `prepare`：`{"steps": [实际跑了的步骤名…]}`
  - `undo`：`{"target_id": 5, "target_op": "orient"}`
  - 失败的操作也记一条，`ok: false`，`summary` 为 `{"error": "错误码"}`，不可撤销。

### 2.3 新接口

- `POST /api/select`，请求体 `{"parts": ["arm_L"]}`：名字必须都在当前零件里（否则 400 `unknown_part`）；
  不占写锁、不进记录；`rev` 加一，SSE 照常推。
- `POST /api/undo`，请求体 `{"id": 5}`（可省略）：撤销最近一条「可撤销且还没撤销」的记录；给了 `id` 但不是那一条 → 409 `not_latest`；
  没有可撤销的 → 409 `nothing_to_undo`。走写操作单飞。
  - 只有 `orient`、`arrange` 两种操作可撤销（它们只改 `job.json`，不落别的文件）。
  - 撤销 = 把 `job.json` 里的 `orient` / `arrange` 两段还原成那次操作之前的快照，并按失效级联删掉 `export`、`check`；
    被撤销的那条标 `undone: true`；另记一条 `op: "undo"`。
  - 还原回来的两段仍算原来那个人做的（`step_actors` 一并还原）；被撤销拿掉的步骤不进 `stale`（撤销是明说的动作，不是失效级联）。
  - 快照也存进 `studio_meta.json`，否则重启后 `undoable: true` 就是假话。
  - 之后如果又跑了 `load`，此前所有记录一律变为不可撤销。

### 2.4 两个新工具（`studio/tools_schema.py`，页面工具与 stdio MCP 同名同参）

- `studio_select`：`{"parts": [名字…]}`，让 AI 也能在视口里指给人看。
- `studio_undo`：`{"id": 整数（可选）}`。
- `studio_get_state` 的说明里补一句：返回里有 `selection`（人在视口里点中的零件）、`history`、`readiness`、`stale`。

工具总数 9 → 11。`mcp_server.py` 里 17:30 之后新增的 MCP App 声明（`_meta`、资源）原样保留。

### 2.5 持久化

`selection` 只在内存里。`history`、`step_actors`、`stale` 存 `<job>/studio_meta.json`（原子写），服务重启后读回；
`load` 到一个新模型时清空 `stale` 与 `step_actors`，`history` 保留但全部标为不可撤销。

### 2.6 令牌与来源校验

- 令牌默认只认请求头 `X-Studio-Token`。`GET /api/session` 成功时另外下发
  `Set-Cookie: studio_token=<令牌>; HttpOnly; SameSite=Strict; Path=/`，**这个 cookie 只给两处用**：
  `GET /api/events`（EventSource）和 `GET /api/part/*.stl`（three.js 的加载器）——它们由浏览器自己发请求，带不了自定义请求头。
- 其余 `GET /api/*`（`state`、`printers`、`shapes`、`tools`）要求请求头令牌；缺 → 403。静态文件不要求。
- 所有 `POST`：只认请求头令牌，**不认 cookie**；请求带 `Origin` 且不是本服务自己的来源、或带 `Sec-Fetch-Site` 且不是
  `same-origin` / `none` → 403 `bad_origin`。命令行与 stdio MCP 不带这两个头，照常放行。
  原因：`SameSite=Strict` 按「站点」算、端口不算，本机别的端口上的网页发来的 POST 会带上 cookie；认了就没有跨站防护
  （初稿让写接口也认 cookie，盲审实测一个只带 cookie 的 `POST /api/load` 返回 200 并真的载入了文件，已改）。
- `GET /api/session`：带 `Sec-Fetch-Site` 且不是 `same-origin` / `none` → 403。
- 页面端：令牌失效（本机服务重启后令牌会换）收到 403 时，重新取一次令牌再重试一遍，不用刷新页面。
- 说明：同一用户下的其他本机进程读得到 `~/.print-prep/`，不在防护范围内；这里防的是浏览器里的别的网页。

## 3. 不做的

- 不改 `print_prep/` 里的几何与导出逻辑。
- 不发打印机（照旧）。
- `studio/app/`（嵌入式 MCP App 界面）这一版先不动；v0.5 的界面定稿后再让两套前端共用一份。
