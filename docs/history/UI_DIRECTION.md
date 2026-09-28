# 3D 工作台 UI 专线

2026-09-22 用户确认：**整个工作台直接沿用 Claude v0.4 的布局与交互，保留现有功能**。以原版源码为依据，不再沿用 v0.5 六步折叠流程作为主界面，也不再用上一版两个大型 `details` 面板替代原版的卡片与固定栏。

## 开发与参考入口

- UI worktree：`~/code/codex-plugin-ui`，分支 `codex/ui-lux3d`，起点 `a20e108`。
- 功能仓：`~/code/codex_plugin`。UI 已整合到功能基线 `4c6f382`，包含 `edf8222` 的窗口缩放性能优化和最新材质、参数重建功能。下方独立 UI 轮次的未安装说明为历史记录。
- 本机预览：<http://127.0.0.1:8998/>。使用 `~/test/claude-blender/runs/workbench-ui-lux3d-20260922/` 下独立 `job/` 和 `home/`。
- Claude v0.4 完整源码：`~/test/claude-blender/runs/recovered-claude-ui-20260922/v04/`，版本 `0.4.0+codex.20260921093258`。同级 `source-manifest.json` 保存每个文件的来源与 SHA-256；这是此前 Claude 自写界面的快照。

## 采用的交互

1. 满铺视口，左上模型/任务/观察记录卡，右上设置卡，最右固定计划或交付栏。
2. 卡片头部用原版箭头按钮收折；收起变为小胶囊。已有模型或记录时默认收起左侧卡，用户选择优先并用 localStorage 记忆。
3. 右侧固定栏用 × 关闭，在视口右上显示同名胶囊按钮重新打开。
4. 600px 以下把同一组卡片节点移入右栏顶部，形成上下布局；保留表单输入、事件、选择与展开状态。浮动视口宽度小于 560px 时，未手动设置过的设置卡默认收起。
5. 视口画布保持完整，通过相机投影偏移和取景空间避开卡片。用户操作过相机后不自动重置视角；适配视图按钮可主动重新取景。
6. 延续 Lux3D 的近黑底、半透明面板、品牌蓝、圆角和底部胶囊条。

## 四个工作区

- 模型编辑：模型与对象在左上卡；编辑 / 拆件 / 修复 / 外观在右上属性卡；工程、导出、历史在固定栏；「将副本送到打印模块」固定在右栏底部。原有导入、编辑、撤销、保存和共享选区接口保留。
- 建模与任务：左上任务卡、右上建模设置卡、右侧产物与运行记录；动画胶囊条在底部，适配视图独立可见。
- 观察与测评：左上观察记录卡，右侧固定评价栏；版本切换与姿态控制位于视口；多版本指标、证据图、评价和保存报告保留。
- 打印准备：直接恢复 v0.4 的模型卡、摆盘设置卡、按选区出现的左下零件卡、打印计划和底部导出/选盘/发送。v0.5 的就绪度、历史撤销、失效步骤重做保留在计划栏；配方跳转打开对应原版卡片或区域。

## 改动文件及原因

| 文件 | 改动 |
| --- | --- |
| `studio/web/index.html` | 恢复原版打印 DOM，保留四工作区入口、就绪度、历史和重做入口。 |
| `studio/web/style.css` | 从 v0.4 恢复悬浮卡、固定栏、按钮条和原始断点样式，适配当前宿主 ID。 |
| `studio/web/studio-shell.js` | 将原版收折、记忆、侧栏开关和响应式节点停靠复用于编辑、任务和观察。 |
| `studio/web/studio-layout.css` | 将原版空间布局接入四工作区；修复高分屏画布 CSS 尺寸，防止固有像素尺寸溢出。 |
| `studio/web/workbench.css` | 统一现有组件的 Lux3D 深色控件样式，替代前一版浅色方案。 |
| `studio/web/panel.js` | 恢复原版卡片交互与模型数量摘要；保留当前动作参数校验。 |
| `studio/web/workspace.js` | 恢复打印卡片停靠及相机留白；配方跳转打开实际卡片；清理新增媒体查询监听和观察器。 |
| `studio/web/flow.js` | 六步 DOM 移除后，仍保留就绪度、共享选区说明、历史和失效步骤重做。 |
| `studio/web/editor.js` | 将现有控件接入共用卡片/固定栏；错误和配方跳转自动展开对应卡片。 |
| `studio/web/tasks.js` | 接入任务卡、设置卡和产物栏，保留原有任务/动画事件。 |
| `studio/web/observe.js` | 接入观察卡和固定评价栏；保留纵向指标和证据图，未就绪时隐藏评价。 |
| `studio/web/viewport-frame.js` | 共用完整画布上的遮挡留白和取景计算；响应卡片收折与画布尺寸变化。 |
| `studio/web/editor-viewport.js` / `studio/web/task-preview.js` | 使用共用取景计算，保留原选区、变换、动画和相机逻辑；编辑网格中性灰、选区浅蓝。 |
| `tests/test_v04_workspace.mjs` | 回归悬浮卡避让/收起释放空间、隐藏视口，以及无六步 DOM 时的失效步骤重做。 |
| `scripts/build_app.mjs` | 离线 MCP App 打包新布局；新增 JS 模块由现有 esbuild 入口递归打包。 |
| `scripts/build_ui_assets.mjs` / `studio/web/vendor/ui/icons.js` | 本地属性图标（前一轮 UI 专线修改）。 |
| `studio/app/index.html` / `studio/app/dist/studio.html` | 深色宿主和重新生成的离线包。 |
| `README.md` / `docs/UI_REFRESH_20260922.md` | 指向当前方向，浅色草案仅保留历史。 |

## 验证与边界

本轮证据目录：`~/test/claude-blender/runs/workbench-ui-lux3d-20260922/evidence-v04-replica/`。

- `npm run build:app` 成功，离线包 1,728,140 bytes；`node --test --test-reporter=spec tests/*.mjs`：52 项通过；`git diff --check` 无空白错误。
- 浏览器 error / warn 记录为空，四工作区创建后没有重复 DOM id；打印画布 CSS 尺寸与视口相等。
- 真实数据：编辑区 5 件 / 2,663,830 面；任务区已有铰链动画；观察区 WaveAB 机器人；打印区已有 5 件单盘模型。
- 380 / 599 / 600 / 1000 / 1280px × 四工作区，共 20 组：页面无横向溢出、画布尺寸非零、无可见错误；详见 `layout.json`。
- 交互证据见 `interactions.json`：零件选中及清空、计划栏关闭和 Enter 重开、属性卡收折、配方展开属性卡并定位检查入口、动画播放/暂停、观察姿态切换。
- 宽屏与窄屏截图以各工作区命名；控制台记录为 `browser-logs.json`。
- 这轮只验证 UI、现有真实产物预览与可逆交互，没有重新执行生成、几何加工、试切或发送。未实测原生 MCP 宿主 GPU 帧率；离线包只做构建及现有契约测试。
- 未 commit、push、合并、安装或修改正式插件；完整改动留在独立 UI worktree。

## v0.4 布局 + v0.5 状态反馈（后续确认）

用户比较两个版本后同意：以 v0.4 为界面骨架，将 v0.5 的就绪度、操作记录、失效提示和下一步引导收进计划栏及配方条。

- `index.html` / `studio-layout.css`：计划栏增加一张紧凑的当前进度卡；六项就绪明细默认折叠、可点击定位，历史摘要显示条数。沿用当前卡片、控件和配色。
- `flow.js`：统一计算普通进度、告警、失效、忙碌与完成状态；失效标记覆盖旧的 pass，避免旧结果仍计入就绪数。无配方时显示下一步或需核对项；启用配方后由原配方条给下一步，避免出现两份不同指引。
- `workspace.js`：配方、就绪明细和进度卡共用同一个定位函数，展开目标卡片并聚焦控件。导航本身不执行加工、试切或发送。
- `tests/test_v04_workspace.mjs`：补空状态、部分完成、过期 pass、告警、忙碌和完成状态回归；`studio/app/dist/studio.html` 重新构建。

验证：`npm run build:app` 成功（1,733,186 bytes）；全部 56 项 Node 测试通过，`git diff --check` 无空白问题。真实 5 件模型显示「核对朝向 / 4 件有警告」与「就绪 3 / 6」。实测就绪条目定位载入和试切、下一步展开朝向卡，后端 revision 在纯导航前后保持 rev 34；配方接管/停用后恢复提示正常；380px 下无横向溢出，状态导航仍定位到已停靠卡片。失效/忙碌/空状态由自动化测试覆盖，没有为制造这些状态执行真实加工。

证据：`~/test/claude-blender/runs/workbench-ui-lux3d-20260922/evidence-v04-v05-feedback/`，含宽/窄屏截图、`interactions.json` 和 `browser-logs.json`。本轮未修改后端接口、未合并正式插件。

## 2026-09-22 正式功能仓整合

将 `codex/ui-lux3d`（基点 `a20e108`）的 UI 工作区改动接入 `codex/print-prep-v05-workspace`（整合前 `4c6f382`）。保留 UI 原工作区，未回退材质槽/纹理、冻结输入参数重建、预览播放速度或 resize 暂停渲染。整合时保留 `.task-check` 布局，并补上“修改参数”自动展开设置卡，确保新布局能看到回填参数。

- 新鲜构建：`npm run build:app`；studio 离线包 1,739,365 bytes。
- `node --test tests/*.mjs`：58 通过；`uv run --frozen pytest -m 'not bambu' -q`：277 通过、2 项设备相关测试未运行。
- 隔离真实模型：编辑 5 件 / 2,663,830 面，打印 5 件单盘，铰链动画，WaveAB 机器人观察。四个工作区 × 380 / 599 / 600 / 1000 / 1280px 共 20 组：无横向溢出、加载完成后画布尺寸均非零。
- 材质粗糙度修改及撤销通过；参数卡自动展开；0.7 mm 间隙在 380px 停靠后保留，生成新纸巾盒任务 `fca619809e0246438d90512d4f763545`（约 2.59 秒）。新旧版本同时保留，四项几何包络/重叠检查均为 0，未验证实际打印配合。
- 铰链预览可选择 0.5× 并播放/暂停；观察姿态切换 50%；打印下一步展开朝向卡；固定栏可关闭并使用 Enter 重开。
- 266 万面编辑场景连续宽度变化 4 秒，停止 500 ms 后累计 7 次 draw call（最终完整场景一帧）、2 次画布尺寸写入、0 次超过 50 ms 的主线程任务。该测量为隔离 IAB 中的尺寸变化，不能据此宣称原生 Codex 窗口 GPU/FPS 已测或卡顿完全消失。
- IAB 日志出现一条未归因的 MutationObserver 异常，离线包及测试 harness 未包含该调用；上述可见操作正常。未宣称宿主控制台完全无错误。

整合证据位于 `~/test/claude-blender/runs/workbench-ui-integration-20260922/`：`validation.json`、`rebuild-evidence.json`、`node-tests.log`、`python-tests.log`。只修改复制的测试任务，没有执行试切、发送打印或收费生成。

安装版本：`0.6.0+codex.20260922033545`；96 个运行时、构建及 skill 文件已核对源码、marketplace 源目录与安装缓存的 SHA-256 一致。

## UI 升级后仍显示旧界面：缓存修复

用户截图证实正式右侧面板仍是旧浅色布局。已安装资源内容虽更新，但 MCP 的 UI URI 固定为 `ui://print-prep/studio-v6.html`，`widgetSessionId` 也只由 job 路径决定；宿主会继续命中旧模板或复用现有 iframe。仅提高 plugin.json 版本和检查安装文件不足以验证显示更新。实际运行中的连接在重新安装后仍通过 `resources/list` 返回旧 URI，这一项已现场确认。

- `studio/app_resources.py`：按离线 HTML 内容的 SHA-256 生成资源 URI；进程内快照内容和 URI 一起固定。工作区 ID 同时绑定 job 和 UI URI，同构建重复打开稳定复用，UI 升级换新实例，持久工程路径保持不变。
- `studio/mcp_server.py`：tool 描述、资源列表、读取内容和打开工作区共用这一版本；保留旧固定 URI 的读取兼容入口。
- `tests/test_mcp_server.py`：新增内容改变使 URI 失效、UI/工程改变使 session ID 失效、旧入口兼容测试。`uv run --frozen pytest -q tests/test_mcp_server.py`：17 通过。
- 已安装 `0.6.0+codex.20260922034222`。新启动的 MCP 连接返回 `ui://print-prep/studio-7df60a3ddd256d1757e7.html`，已核对与正式离线包 SHA-256 一致。安装不能替换已经运行的旧 MCP 连接；旧连接须由宿主重新连接后才会返回新标识。

证据：`~/test/claude-blender/runs/workbench-ui-cache-fix-20260922/`。新连接回执不等于原生窗口视觉验收；CUA 拒绝访问 Codex 原生应用，未绕过限制。可让用户在宿主重新连接插件，必要时重启 Codex 后再打开 3D 工作台。

官方依据：[MCP UI 文档](https://developers.openai.com/plugins/build/chatgpt-ui) 要求把资源 URI 当作缓存键，HTML/JS/CSS 变化时更新 URI 及所有工具引用。

## 统一审阅界面与功能归属（2026-09-22）

用户指出 A8 暖纸色审阅页像另一个插件，并明确 A8 属于观察评测。本轮将 A8 / Merge 的入口与历史记录迁至「观察与测评 → 拆件与机构」，与模型观察、路线评审并列；任务执行、原始路径与产物不迁移。

- `studio/web/theme.css` 成为编辑、任务、观察、打印和离线审阅的共同主题来源。构建内联同一组 IBM Plex 字体和 Lux3D tokens。A8 改为深色卡片、蓝色操作、统一字级与中性灯光。
- A8 / Merge / 平台 preview 继续共用 assembly viewer，并进一步复用主工作台 `ViewportFrame` 和 `RenderLoop`。取景为卡片和播放条留白；用户旋转后宽度变化不自动重置相机。
- `presentation=studio` 只从可识别的旧离线成果提取 JSON 数据，用当前 viewer 显示；原始 HTML 下载不变，资源字节、provenance、内容 SHA、curationEnabled 保留。自定义 HTML 不转换。平台禁用 G/B 的策略由共同 viewer 根据数据处理，不再注入另一份 CSS。
- 修正旧响应式样式对检查面板强制 54vh，以及无任务时隐藏整个 stage、连带隐藏设置卡的问题。

验证：完整 Python 310 passed / 2 deselected（排除 Bambu）；Node 62 passed；离线包构建与脚本解析通过。隔离 IAB 验证已有 A8 四抽柜的 0.38642 m 端点、独立关节、380px 折叠面板、Merge 两版本并排、600px 空建模区及模板归类。静止 4 秒 0 绘制 / 0 canvas 写入；连续宽高变化 4 秒后 39 draw calls、2 次 canvas 尺寸属性写入（一次画布重建）、0 次 >50ms 长任务。不是 Codex 原生窗口整体 FPS 测量。

证据：`~/test/claude-blender/runs/workbench-unified-review-20260922/`。

### 共同 Viewer 的下一层边界

目标是一套 Viewer 内核，按编辑 / 观察 / 打印加载不同工具。A/B 比较使用同一内核的双视口，不要求永远只有一个 canvas。当前共享主题、Three.js 版本、取景和渲染调度，**仍有多个 renderer 与独立场景状态**；A8 iframe 的临时选区、姿态与编辑器撤销尚未合并。本轮不能称为统一场景架构已经完成。

后续迁移先定义稳定对象 ID、来源版本、单位和坐标适配，再将 GLB 动画、刚体关节和打印叠加层接入可复用 ViewerHost。共享选区与相机状态，几何修改统一经过带 revision 的命令；评测证据保持只读，不因查看或切模式而扁平化关节、修改源模型。逐种模式替换现有视口，并用材质/姿态/选区/撤销一致性及 idle/resize 指标验收。此项涉及场景与状态架构，需单独确认迁移范围。
