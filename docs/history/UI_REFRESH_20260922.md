# 工作台 UI 整理（2026-09-22）

> 历史记录：本次浅色方案随后被用户否定。当前 UI 方向与独立 worktree 入口见 [UI_DIRECTION.md](UI_DIRECTION.md)，以 参照产品式编辑器层级和原有 Lux3D 深灰 / 品牌蓝为准。

用户希望复用成熟 UI，改善四个模块各有一套样式的问题。本轮沿用现有原生 HTML + Three.js，实现统一浅色控制面板、深色模型视口；控件基础复用 Pico CSS，图标复用 Lucide，字体使用本地 IBM Plex Sans。来源及许可证见 [THIRD_PARTY.md](../THIRD_PARTY.md)。

## 改动

- `studio/web/workbench.css`：统一字号、间距、边框、按钮、表单、焦点和状态色；取消编辑工具条的 backdrop blur，窄面板使用两行导航，380px 保留按钮名称和可访问标签。
- `studio/web/editor.js`：工具条及撤销/重做/保存使用 SVG 图标；文件选择优先展示，路径输入和工程打开折叠；导出区可展开。功能与共享选区保持原契约。
- `studio/web/tasks.js`：任务与观察记录分别显示；输出文件列表折叠并显示数量，减少窄屏长页面；路径参数折叠。
- `studio/web/observe.js`：与编辑区共用视觉语言，保留姿态与版本切换、指标、评价。
- `studio/web/index.html` / `workspace.js`：统一导航和本地静态资产。
- `scripts/build_ui_assets.mjs` / `build_app.mjs` / `package.json`：可复现打包 Pico、13 个 SVG 和三份字体；MCP App 完全内嵌，HTTP 入口使用同源文件。

## 验证

运行根：`~/test/claude-blender/runs/workbench-ui-20260922`，测试使用原工程的独立副本。

- Node 前端测试：41 passed，覆盖现有协议、配方、按需绘制和 resize 调度。
- MCP 集成测试：14 passed，包含资源加载和观察图返回。
- `npm run build:app` 成功；`git diff --check` 无错误。
- 内置浏览器检查全部四个工作区；380 / 600 / 1100px 页面未出现整体横向溢出，窄屏表格在自己的区域横向滚动。
- 编辑器通过界面载入真实 5 件、2,663,830 面模型；缩放宽度后仍正常显示对象、模型和工具条。打印视口也实载五件模型。
- 建模任务的真实铰链预览可播放/暂停；观察区切换到机器人 100% 姿态，实际页面与后端焦点同步。浏览器 error/warn 检查为空。
- 检查中修正了原有高优先级文件输入背景、打印流程行宽度、select 箭头，以及新样式影响到的间距。

以上是共享页面和调度器验证。没有测得 Codex 原生窗口的 GPU 帧率，因此不把它写成“宿主缩放卡顿已经彻底解决”。本轮没有增加 UI 框架运行时；新增长度主要来自本地 CSS/字体，最终包尺寸见运行根构建日志。
