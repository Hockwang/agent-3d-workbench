# 城市编辑拖动闪烁修复（0.8.6）

## 现象与根因

用户录屏中，完整城市进入编辑态并选中人物后，拖动视角会出现大片地面覆盖道路、
人行道与部分车身消失。已用同一城市的独立工程副本在 Chrome / Metal 重现。

`EditorViewport.fit()` 原本同时更新位置和相机裁剪范围。普通网格编辑以 mm 为单位，
城市以 m 为单位；适配约 2 m 的人物会把城市近裁剪面从 0.35 m 降到约 0.001 m，
而远裁剪面仍是 15000 m。过大的深度范围比例造成地面与道路的深度冲突，随视角改变闪烁。

修复保留城市运行时自己的 near/far；人物适配仍更新相机位置和目标。普通网格的裁剪
计算保持原逻辑。没有修改城市地形、道路、模型、材质或冻结运行包。

## 改动文件

- `studio/web/editor-viewport.js`：城市模式的 fit 不覆盖运行时裁剪范围。
- `tests/test_editor_pivot.mjs`：新增城市人物重复聚焦的裁剪范围、目标与位置回归。
- `.codex-plugin/plugin.json`、`studio/app/main.js`、`studio/mcp_server.py`：版本同步至 0.8.6。
- `studio/app/dist/studio.html`：重新构建原生工作台资源。
- `docs/CITY_RUNTIME.md`：记录城市相机单位和裁剪范围的所有权。

## 验证

- 新回归先在修复前失败：near 实际为 0.00107703296，期望为 0.35；修复后通过。
- 源码 `node --test tests/*.mjs`：97 项通过，0 失败。
- 安装源 `node --test tests/test_editor_pivot.mjs`：10 项通过，0 失败。
- 源码和安装源均完成自包含 HTML 构建及内联 JavaScript 解析。
- Chrome / Metal 隔离工程中按“选中人物 → 适配视图 → 连续拖动”复现，修复前 near=0.001，
  截图出现大块地面遮挡；修复后 near=0.35、far=15000，166 次渲染记录中范围保持稳定，
  18 张拖动采样截图未再出现该遮挡，无 pageerror。城市清单为 108 人物、106 设施。
- Codex 实际右侧 HTTP 工作区刷新后，再次聚焦已选人物，连续拖动两次并缩远，
  人行道、道路和车身显示正常，浏览器错误日志为空。
- 验证前后，独立城市工程和原 34 对象工程的 project.json SHA-256 均一致。
- 已安装 `print-prep@personal` 0.8.6；当前 HTTP 工作区通过刷新加载修复。

本机证据：`~/test/studio-city-flicker-20260923`，包括 `fit-road/` 修复前、
`baseline-road/` 对照、`fit-fixed/` 修复后截图和渲染记录，以及 `node-tests.log`。
这是本次特定闪烁的验证，不是全城性能基准。原生 MCP 连接的恢复状态仍见
[重连记录](RECONNECT_FIX_20260923.md)，本轮没有重启 Codex 或其他任务的服务。
