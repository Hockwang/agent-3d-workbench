# 城市联动验收 — 2026-09-23

本轮使用用户提供 Cubely ZIP，测试目录 `~/test/studio-city-20260923`。
测试工程与用户原 34 对象工程分开；不调用外部生成 API，不提交城市素材。

## 真实场景与编辑链

- 完整启动：108 人物、106 设施、1137 collider；保持地形、道路、建筑与包内行为。
- 设施 `tea-cabinet-2` 平移 4 m：画面和交互 x 坐标均增加 4 m；旧 collider 失效、旧 obstacle 移除，
  新位置路径查询受阻；collider 总数仍 1137。同源 `tea-cabinet-11` 的矩阵不变。
- 材质修改后原 `interaction_motion` 继续播放；撤销恢复原资产。设施加载继续使用原 clip 修正、循环和乘客逻辑。
- 人物 `person_1`：34 骨骼、22 语义角色、原 `Continuous_Pedestrian_Safety` 片段保留。
  真实 Blender 5.1.2 材质修缮、GLB 导出、原位回填通过；24 fps 截短候选先被拒绝，按源 30 fps 导出后通过。
  这不是任意骨架兼容或形变自然度全量验收。
- WASD 真实输入：两秒以上模拟后车辆前进约 4.1 m；同一个 renderer，城市内部 RAF=0。
  人物 1 原本静止；另选人物 4 修改材质并恢复模拟，实测行走 2.19 m、34 根骨骼保留。
- 真实 `.3dworkbench` 保存、读回：城市包、冻结清单及 3 个对象恢复一致；读回后 Blender 回填仍可用。
- HTTP 页面通过；MCP App bundle 在隔离 iframe 中经真实后端读写、二进制 resource bridge 通过。
  上下文含城市实例；动作模式时间轴实测到 1.09 / 17.90 s。不是原生 Codex 窗口的自动化验收。
- 视觉复核发现并修复两处定位错误：运行后选中人物时镜头曾对准临时行走位置，现对准保存的编辑实例；
  源 GLB 原点在身体中部，现把人物落地校准写入冻结实例矩阵。新版截图确认人物全身站在地面。
- 运行包的本机构建收据使用共享工作区根目录，不跟随任务日志目录。新增两任务切换回归，
  确认本机可复用，同时其他工程或另一信任根不能读取未授权运行包。

## 性能

Chrome + ANGLE Metal / Apple M5 Pro，1280×900 起始窗口，完整城市实际渲染。

- HTTP 初次启动至截图约 10.6 s（含测试额外等待，非纯首屏指标）。
- MCP 两次运行段共 291 / 280 个帧间隔：p50 **17.3 / 32.4 ms**、p95 **33.7 / 34.2 ms**，约 30–60 fps；
  该视角 320 draw calls、约 180.7 万 triangles。短样本，不代表整城最差情况。
- 连续调整窗口宽度：不增加资源请求、不重建 renderer、无 WebGL context loss；城市只用宿主帧循环。
- 资源桥峰值 2 个并发读取，未超过测试宿主的 4 请求限制。
- 早期 headless-shell 使用 SwiftShader 软件渲染，帧间隔约秒级；已明确识别，不能混作 Metal 性能。
- 原生 Codex 拖动外窗边缘的体验没有被本轮自动化直接测量，不能据上述浏览器结果声称该宿主问题完全解决。

## 回归与改动位置

- `studio/city.py`：冻结城市包、哈希/运行信任、实例清单、按需载入、回填约束、保存/恢复。
- `scripts/build_city_runtime.mjs`、`studio/city/*.js`：复用原 Cubely 源，接统一渲染与资源读取，联动人物、设施、碰撞、交互。
- `studio/web/city-panel.js`、`editor-viewport.js`、`editor.js`、`studio-layout.css`：城市入口、列表、运行控制、镜头/坐标切换和细节模式。
- `studio/editor.py`、`editor_schema.py`、`scene_assets.py`、`collaboration.py`、`branches.py`、`workspaces.py`：编辑契约、冲突保护、归档和分支资源。
- `studio/server.py`、`mcp_server.py`、`studio/web/api.js`、`studio/app/api.js`、`studio/app/selection-context.js`：工作台范围内资源通道、会话初始化和选区上下文。
- `tests/test_city.py`、`test_editor_pivot.mjs`、`test_webmcp.mjs`：资源隔离/损坏拒绝、归档、分支、scope/undo、城市单位转换和初始化。
- `.codex-plugin/plugin.json`、`README.md`、`skills/print-prep/SKILL.md`、`studio/app/dist/studio.html` 与本文档：版本、使用约束与构建产物。

源码回归：`uv run --locked pytest -m 'not bambu' -q` **465 passed、2 deselected**；
最终城市/场景定向回归 **20 passed**；`node --test tests/*.mjs` **92 passed**；构建和 `git diff --check` 通过。
安装源保留其他任务已有配方增量，合并后后端 **492 passed、2 deselected**，Node **93 passed**，构建通过。
最后坐标/信任修复后，安装源定向回归 **20 passed**、Node **93 passed**。
测试原始输出位于仓外上述证据目录。

独立示例工程：`~/code/cubely-studio-city`，只保留原始城市与冻结清单，不携带测试时的材质/位置修改。
用户可在 Codex 将该目录作为项目打开；当前任务既有工程保持独立。

最终安装：`print-prep@personal` **0.8.3**。安装构建经 MCP iframe 桥再次通过，
最后安装构建 Metal 281 样本 p50 32.5 ms / p95 33.8 ms，resize 资源读取增量 0，人物 4 修缮后行走 2.305 m，
动作模式 1.09 / 17.90 s，无页面异常。实测截图已查看。
新坐标版本工程再次保存/读回 3 个对象，Blender 候选回填通过；独立示例更新为新版冻结包和 214 项清单。
当前任务后端在确认无活动任务后升级；34 个对象保持不变，工程 SHA-256 升级前后一致：
`864336b97ae74ee21236a01021c8228e92cb643f00595762fdbb399801723865`。
