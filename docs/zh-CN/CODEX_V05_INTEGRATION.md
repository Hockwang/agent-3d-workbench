> English: [../CODEX_V05_INTEGRATION.md](../CODEX_V05_INTEGRATION.md)

# v0.5 与 Codex 右侧工作区的融合

## 实现边界

接入 v0.5 的六步流程、就绪度、操作记录、撤销、共享选区和 HTTP 来源校验，保留 Codex 的右侧打开方式、轻量对话卡片、稳定 session ID 与预览资源。

- `studio/web/workspace.js` 接收 transport，串起 `Panel`、`Flow`、`Viewport`。HTTP 页与 MCP App 共用控制器和 HTML；构建脚本从 `web/index.html` 提取工作区。
- `studio/app/api.js` 把界面写操作交给仅 App 可见的 `studio_ui_action`，后者只允许已登记的 POST 工具并固定 `human` 作者。普通 MCP 工具使用 `ai`；作者不是认证边界。
- 形态表通过 `print-prep://catalog/shapes` 读取；预览通过既有 geometry resources 获取。MCP iframe 不直接访问 HTTP，也不引入上传桥。
- 保留 `fullscreen` 偏好、global/thread 入口、148px 卡片高度提示；工作区遵守安全边距。收起停止渲染，重新展开复用几何和选区。
- GET 与 POST 都传本机令牌。HTTP 的 cookie 仅用于 SSE / 网格读取；写请求继续校验来源和显式令牌。
- 修复一键准备换模型后的跨模型撤销：无论全流程成功还是导出阶段失败，已更换模型就清除旧撤销、选区与旧步骤作者。
- 重新载入、调整朝向、排盘、导出或撤销会重置旧交付状态；一键准备真正执行了打开步骤时才保留本次交付。

## 验证

自动验证入口：

```bash
npm run build:app
uv run --locked pytest -m 'not bambu' -q
node --test tests/*.mjs
```

stdio 集成测试使用临时 `PRINT_PREP_HOME`，覆盖界面载入、AI 朝向、人排盘、共享选区、撤销、形态资源与错误传递。制造网格不因预览改变。额外回归先复现了跨模型撤销、旧交付状态残留，再验证修复。

隔离浏览器宿主使用真实测试网格和 MCP handlers，验证：

- 初始卡片不读取几何；展开后显示六步界面。
- 人点击载入和朝向，AI 排盘并选择零件，界面同步作者和高亮，再由人撤销 AI 排盘。
- 工艺表单通过 MCP 导出几何 3MF；未执行真实试切或打开 Bambu GUI。
- 420×700、420×420、900×840，宿主底部覆盖 76px；无横向溢出，流程区域可滚动。
- 收起再展开保留选区，几何读取仍为 2 次。
- HTTP 兼容入口显示同一份状态、登记 11 个页面工具，并可清除共享选区。

测试宿主不代表 Codex 原生壳可视验收。自动 UI 工具禁止操作 Codex 自身；安装更新后需在新任务打开 Print Prep，确认实际右侧标签页。已有任务可能仍使用旧 MCP 进程和旧工具列表。

## 维护

优先改共享工作区文件，再重建 `studio/app/dist/studio.html`。不要各自复制维护两套六步 HTML。
只改 JavaScript 源文件不会更新已打包的 MCP App。重新安装前更新 cachebuster；保持本机 `.mcp.json` 在版本控制之外。

运行中的 HTTP 后端需要定向重启才能加载 Python 改动。重启前检查 `busy` 并备份 job 元数据；验证时只读用户 job，不用真实模型跑写入测试。
