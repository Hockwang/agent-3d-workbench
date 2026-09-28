> English: [../ARCHITECTURE.md](../ARCHITECTURE.md)

# 架构

本文档描述这个插件目前是如何组装起来的，以及它正在重构迈向的目标布局。这里的
任何内容都不会改变工具名称、磁盘格式或 MCP 资源 URI——那些是外部契约（参见
[配置](CONFIGURATION.md)）。

## 组件与请求流程

```
Codex
  |  stdio（MCP 协议）
  v
studio/shell/mcp_server.py            stdio MCP 服务器（官方 `mcp` SDK），注册 26
  |                             个工具，把每次 `tools/call` 转发到下方本机
  |                             HTTP 后端上的一个路由。
  |  HTTP，仅回环（127.0.0.1）
  v
studio/shell/server.py                Handler：token + Origin + fetch-site 校验，
  |                             静态文件服务，用于实时更新的 Server-Sent Events。
  |  进程内调用
  v
StudioBackend / Workspace /     业务逻辑：网格编辑（studio/core/editor.py）、
Tasks / Observations / ...      本机任务队列（studio/core/tasks.py）、动作
                                 （studio/core/motion.py）、观测、配方、打印
                                 准备（print_prep/*），以及可选的托管服务
                                 适配器（studio/adapters/*_service.py）。
```

同一批 HTTP 路由也能被浏览器直接访问到：MCP App UI（`studio/app`）和普通
浏览器 UI（`studio/web`）都会调用 `/api/*`，而且 `studio/web/tools.js`
还会把这套工具集额外注册成页面级的 WebMCP 工具（`navigator.modelContext`
风格），这样浏览器标签页里打开的一个页面就能像 Codex 工具调用一样被驱动。
实时状态变化（选区、撤销、任务进度）通过 Server-Sent Events 推送给已打开
的查看器，而不是靠轮询。

进入 HTTP 层的每一个请求在被处理之前，都会先检查 origin/fetch-site 请求
头——因为服务器虽然绑定在回环地址上，但浏览器打开的任何页面理论上都能
访问到它；正是这一步检查，防止了任意网页悄悄驱动这个工作台。

## 磁盘状态布局

所有本机状态都存放在 `PRINT_PREP_HOME` 下（默认是 `~/.print-prep`；每一个
路径和覆盖项见[配置](CONFIGURATION.md)）：

- `studio.json` —— 正在运行的服务器的会话文件（pid、端口、token、job 目录）。
- `job/` —— 默认的单工作区 job 目录（旧版布局）。
- `workspaces/<workspace_id>/job/` —— 每个文件夹工程 / Codex 任务各自一份
  job 目录，这样不同 worktree 里并发的任务就不会互相冲突。
- `workspaces/<parent>/part-chat/` —— 某个工作区子对话的 part-chat 授权
  与日志。
- `recipes/<id>/` —— 用户安装的配方，与仓库自带的 `recipes/` 目录里内置
  的配方并存。

托管适配器的配置（`services.json` 以及与它配对的私有凭据存储）单独存放，
默认在 `~/.config/codex-3d/` 下——具体形态见[配置](CONFIGURATION.md)。

## 包布局

```
studio/__init__.py            保留（进程辅助函数）：PRINT_PREP_HOME 解析、会话
                               文件读写，以及 server.py、mcp_server.py 和
                               scripts/studio.py 共用的"是不是真的在跑"检查。
studio/paths.py                唯一知道整棵目录树的地方 —— PLUGIN_ROOT、STUDIO_DIR、
                               CORE_DIR、ADAPTERS_DIR、SHELL_DIR、WEB_DIR、APP_DIR、
                               APP_DIST_DIR、CITY_DIR、KERNELS_DIR、RECIPES_DIR、
                               SCRIPTS_DIR、PRINT_PREP_DIR。
studio/core/   （本机）      editor.py geometry_store.py materials.py scene_assets.py city.py
                               collaboration.py branches.py history.py motion.py recipes.py
                               recipe_progress.py uploads.py viewer_presentation.py
                               assembly_review.py generated_editing.py projects.py workspaces.py
                               observation.py observation_render.py observation_run.py tasks.py
                               task_worker.py task_bootstrap.py task_operations.py
                               task_templates.py blender_catalog.py blender_ops.py + kernels/
                               editor_actions.py（动作注册表）print_state.py（打印准备状态）
                               cli.py + __main__.py（python -m studio.core）messages.py messages_scene.py
                               （vendored 几何内核：机构基元、离线场景查看器契约与适配器）
studio/adapters/ （托管）    services.py（对外统一入口：BUILTINS、config、catalog、prepare、run）
                               transport.py（纯 HTTP：validate_url、request、download、service_transport）
                               registry.py（ServiceAdapter Protocol、register、adapter_for）
                               lux3d_service.py lux3d_commerce.py lux3d_upload.py hunyuan_service.py
                               seed3d_service.py assembly_service.py meshy.py tripo.py
                               service_connections.py service_diagnostics.py evaluation.py platform_preview.py
                               messages.py messages_assembly.py（双语消息目录）
studio/shell/  （Codex + HTTP）server.py mcp_server.py tools_schema.py editor_schema.py
                               motion_schema.py task_schema.py evaluation_schema.py
                               recipe_schema.py codex_bridge.py part_chat.py app_resources.py
                               codex_projects.py messages.py
```

`studio/app/`、`studio/web/`、`studio/city/`（JS，不迁移）、`print_prep/`
（打印准备库与 CLI，不迁移——零导入 `studio`、零网络访问），以及
`.codex-plugin/plugin.json` / `install.sh`（插件清单与安装脚本）都和这三个
Python 包并列存在；这次分层重构不会挪动它们中的任何一个。

分层规则，由 `tests/test_layering.py` 强制执行：**core** 必须能在零
MCP/HTTP/Codex/网络依赖的情况下被导入——它不能导入 `studio.adapters` 或
`studio.shell`。**adapters** 包装可选的、按密钥启用的托管服务客户端，可以
导入 `core`，但不能导入 `shell`。**shell** 拥有每一个对外的接线契约（MCP
工具名称、`ui://` 资源 URI、HTTP 路由、Codex 线程桥接），可以导入包里的
任何东西，因为它是唯一被允许知道内部能力如何对外接线的地方。当 `core`
需要一个 `shell` 的能力时（例如解析某个 Codex 线程的工作目录），这个依赖
由 `shell` 里的调用方作为参数注入，而不是从 `core` 内部导入。

## 编辑器动作

`studio/core/editor.py` 里的 `Workspace._apply` 按名称分发每一个
`studio_edit` 动作；`city_`/`scene_`/`motion_` 开头的动作直接交给
`city.py` / `scene_assets.py` / `motion.py`，其余的——`import`、
`transform`、`plane_cut`、`material`、`inspect` 等等——则在
`studio/core/editor_actions.py` 的声明式注册表里查找
（`ACTIONS: dict[str, ActionSpec]`），它把每个动作名和对应的处理函数、以及
几个标志位（`snapshot`、`requires_selection`、`blocks_motion_scene`、
`read_only`）配成一对，精确描述了 `_apply`/`Workspace.execute` 对这个动作
名会做什么——所以 `_apply` 本身只是校验（跨子系统守卫）→ 查表（这个
注册表）→ 执行（处理函数）→ 后处理（不需要，每个处理函数都会返回自己
最终的结果）。新增一个 core 动作，意味着在那个模块里写一个函数、加一个
`@action(...)` 注册，而不是去改一条很长的 if/elif 链；具体步骤见该模块的
docstring，保持这个注册表和 `studio_edit` schema 枚举不脱节的测试见
`tests/test_editor_actions.py`。

## 直接使用 core 层

`python -m studio.core`（`studio/core/cli.py`）是比 `studio/shell/` 薄
得多的第二个适配器：一个直接调用 `studio.core.recipes`/`editor`/`tasks`/
`observation` 的 argparse CLI，进程内执行，不涉及 Codex，也不经过 HTTP
服务器。它存在的意义，是让一个不是 Codex 的调用方——一个 Blender 插件、
另一个 agent 的 skill——可以通过跑一个子进程、读 stdout 里的一行 JSON
来触达同样的能力，而不用去讲 MCP 或 HTTP。它读取的是
`studio/core/tool_schemas.json`（`studio.shell.tools_schema.get_tools()`
的一份已提交快照），而不是导入 `studio.shell`，这也是它能留在上面分层
规则里 `core` 一侧的原因。完整命令参考见 [docs/CORE_CLI.md](CORE_CLI.md)。

## 消息与语言

任何人能读到的字符串——错误信息、动作摘要、任务模板的标题和描述、
provider 标签、CLI 帮助文本——都来自一个消息目录，绝不会是代码路径里的
字面量。`studio/i18n.py` 保存着这个注册表：`MESSAGES` 把一个 code 映射到
`{"en": ..., "zh-CN": ...}`；`register()` 添加条目；`render(code,
**params)` 返回当前语言下的文本（回退顺序是 en -> zh-CN -> code 本身，
所以它永远不会抛异常）。`studio.i18n` 位于 `core`/`adapters`/`shell` 之外，
这样每一层都可以导入它。code 的格式是 `<module>.<snake_case_meaning>`，
一旦发布就成为 API 的一部分。

消息目录放在它们所服务的代码旁边，并从各自包的 `__init__.py` 里被导入
（为了触发它们的 `register()` 副作用）：

| 层 | 消息目录文件 | 覆盖范围 |
|---|---|---|
| `studio/core` | `messages.py`、`messages_scene.py`、`messages_tasks.py`、`messages_observation.py`、`messages_projects.py`、`messages_workspaces.py`、`messages_cli.py` | 编辑器、材质、历史、上传；场景/城市/动作；任务与模板；观测与打印状态；工程与配方；工作区；`python -m studio.core` |
| `studio/adapters` | `messages.py`、`messages_assembly.py` | Lux3D、Seed3D、Meshy、Tripo、services 统一入口；Hunyuan、assembly、evaluation、transport、registry、诊断 |
| `studio/shell` | `messages.py` | HTTP 错误体、MCP 服务器、Codex 桥接、part chat |
| `print_prep` | `messages.py` | 独立的打印准备包 |

`print_prep` 不能导入 `studio`（`tests/test_layering.py`），所以它自己
带了一份小小的注册表副本，配了一个 `language_provider` 钩子；当两者都被
加载时，`studio/i18n.py` 会把这个钩子指向 `get_language()`，这样语言仍然
会跟随请求走。MCP 工具的*描述*（`studio/shell/*_schema.py`、
`docs/TOOLS.md`）只有英文：它们是给模型读的，不会展示给人看。

抛出异常的地方用 `EditorError.coded(code, **params)`
（`studio/core/editor.py`）：它会用当前语言渲染消息，并把 `code`/
`params` 存在异常对象上，所以每个 JSON 错误体都带着 `{"ok": false,
"error": {"code", "message", "params"}}`。当一个已有的对外 wire code
必须保留时（`revision_conflict`、`busy`、`bad_arguments` 等等），
`coded(message_code, code=wire_code)` 会把两者分开保存。其他异常类型
（`RuntimeError`、`ValueError`、`UndoConflict`、`BridgeError`）保留自己
原来的类型，用 `render()` 拼出文本。任务模板目录（`task_operations.py`、
`blender_catalog.py`、`observation.py` 等文件里的 `CATALOG` 列表）在自己
的展示字段里存的是 code，由 `task_templates.localized_catalog()` 按每次
请求渲染。

当前语言是一个 `contextvars.ContextVar`
（`studio.i18n.current_language`），按每次请求设置而不是全局设置，这样
不同语言的并发请求就不会互相干扰：

- `studio/shell/server.py` 在分发请求之前，从请求的 `Accept-Language`
  请求头里设置它（回退到 `STUDIO_LANG`），处理完之后再重置。浏览器 UI 会
  在这个请求头里发送自己的 locale（`studio/web/api.js`），所以后端消息会
  跟随面板的语言切换。
- `studio/shell/mcp_server.py` 在进程启动时从 `STUDIO_LANG` 设置一次；
  任务子进程继承同一个环境变量。
- 测试固定用 `STUDIO_LANG=zh-CN`（`tests/conftest.py`），这样原来的中文
  断言仍然成立；新测试应该断言 `code`。

已知的例外：`studio/core/observation_render.py` 运行在 Blender 内部，
它的路径上没有 `studio` 包，所以直接从 `STUDIO_LANG` 里挑它唯一的那条
消息；`studio/core/blender_ops.py` 和 `studio/core/kernels/` 下 vendored
的内核只抛纯英文的 `ValueError`。面板自己的字符串放在
`studio/web/locales/{zh-CN,en}.js` 里（`studio/web/i18n.js`、
`t("key")`）；如果两个文件的 key 集合对不上，`npm test` 会失败。面向
用户的行为见 `docs/CONFIGURATION.md` -> "Language / `STUDIO_LANG`"，
工作流程见 `CONTRIBUTING.md` -> "Adding a user-facing message"。

## UI 构建流水线

MCP App 和浏览器 UI 都是预先构建好的，产物已经提交进仓库
（`studio/app/dist/`、`studio/web/vendor/`），所以一次全新的 clone 不需要
跑 Node 构建步骤就能用。改动 UI 源码之后要重新构建：

```bash
npm run build:app
```

这条命令依次运行：`build:ui`（`scripts/build_ui_assets.mjs`，把浏览器 UI
的 JS/CSS/字体依赖打包为 vendored 资源）、`scripts/build_gltf_codecs.mjs`
（Draco/KTX2/Meshopt 编解码器资源）、`scripts/build_motion.mjs`（离线
动作评测用的 Node 打包产物）、`scripts/build_delivery.mjs` 和
`scripts/build_assembly_review.mjs`（交付/爆炸视图 HTML 打包器），最后是
`scripts/build_app.mjs`（MCP App 打包本身，`studio/app/dist/*`）。
`make build` 跑的是同一套流程。
