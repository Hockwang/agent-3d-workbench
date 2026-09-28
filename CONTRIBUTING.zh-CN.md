> English: [CONTRIBUTING.md](CONTRIBUTING.md)

# 贡献指南

## 环境搭建

```bash
make install
```

会运行 `uv sync --locked`（Python，版本锁定在 `uv.lock`）和 `npm ci`
（JavaScript）。两者都是幂等的；拉取涉及 `pyproject.toml`、`package.json`
或它们锁文件的改动后请重新执行一遍。这一步只安装开发依赖；如果还要把插件
注册进 Codex，运行 `./install.sh`（macOS/Linux），或者按
[docs/zh-CN/CONFIGURATION.md](docs/zh-CN/CONFIGURATION.md) 里的"手动安装
（任意操作系统，含 Windows）"操作。（`studio/mcp_server.py` 只是给旧版
安装已经生成的 `.mcp.json` 文件用的兼容存根；新安装指向的是
`studio/shell/mcp_server.py`。）

## 不启动 Codex 运行

```bash
make dev
```

会独立启动本地 HTTP 后端（`studio/shell/server.py`）并打印出它的 URL。用
浏览器打开并在后面加上 `?mock=1`，界面就会跑在内置的示例数据上、完全不
发起任何后端调用——适合在没有 Codex 会话、也没有加载真实模型的情况下迭代
界面。`make stop` 会停掉 `make dev` 启动的后端。

如果只是想快速单独检查一下 `studio.core` 能力层本身（recipes、editor、
tasks、observation），甚至连 HTTP 后端都不需要：运行
`uv run python -m studio.core <group> <verb> --help` 看命令列表，或参见
[docs/zh-CN/CORE_CLI.md](docs/zh-CN/CORE_CLI.md)。

## 测试

```bash
make test       # everything
make test-py    # pytest only
make test-js    # node --test only
```

运行单个 Python 测试文件或测试函数：

```bash
uv run pytest tests/test_editor.py
uv run pytest tests/test_editor.py::test_plane_cut -v
```

需要本机真实安装 Bambu Studio 的测试标记为 `@pytest.mark.bambu`；默认配置
下，只有你显式过滤掉它们（`pytest -m "not bambu"`）才会被排除。不加过滤
直接跑完整的 `make test`/`pytest -q` 也会尝试运行它们，如果本机没有
Bambu Studio，它们会干净地跳过。任何涉及服务器状态的测试都要把
`PRINT_PREP_HOME` 设成一个临时目录——绝不能让测试读写真实的
`~/.print-prep`。

## Lint 与格式化

```bash
make lint     # ruff check .
make format   # ruff format .
```

配置放在 `pyproject.toml` 的 `[tool.ruff]` 下。有一批规则（`E501`、
`E701`/`E702`、`E402`、`E401`、`E741`、`F401`、`F841`）暂时被忽略——这个
仓库最早的代码是在计划做一次全仓 `ruff format` 之前、以一种压缩风格写的。
不要写依赖这些忽略规则的新代码；它们存在的目的是避免给旧代码制造一堆噪音
diff，而不是给新代码的单行写法开绿灯。`studio/web`、`studio/app`、
`studio/city` 和 `node_modules` 完全排除在 Python lint 之外（它们是
JavaScript）。

## 构建界面并提交 `dist`

界面源码放在 `studio/web`（浏览器界面 + WebMCP 桥接）和 `studio/app`
（MCP App 包）里；*构建产物*（`studio/app/dist/`、`studio/web/vendor/`
下的 vendored 资源）会提交进仓库，这样全新克隆下来的仓库不用跑 Node
构建就能用。改动 `studio/web` 或 `studio/app` 下任何内容之后：

```bash
npm run build:app
```

并把 `dist`/`vendor` 下产生的改动和你的源码改动放进同一个提交——只改
源码、让 `dist` 停留在旧状态的 diff，只有在你明确标注出来的情况下才能
通过评审。每一步构建产出什么见
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md#ui-build-pipeline)。

## 新增一个 MCP 工具

1. 把工具的声明（`name`、`inputSchema`、`readOnly`，以及一对 HTTP
   `method`/`path`，或者一个直接的 MCP-server 实现）加到对应的
   `studio/shell/*_schema.py` 文件里；如果这个工具还没有专属的 schema
   文件，就加到 `studio/shell/tools_schema.py`。
2. 如果是 HTTP 驱动的，就把对应的路由加到 `studio/shell/server.py` 的
   `StudioBackend` 里。
3. 重新生成参考文档：

   ```bash
   make tools-doc
   ```

   这会运行 `scripts/gen_tool_reference.py`，用 stdio MCP 服务器在运行时
   组装出的同一份工具列表重写 `docs/TOOLS.md`，所以这份文档永远不会和
   Codex 实际看到的内容脱节。提交重新生成后的文件。

工具的 `name`，以及对 HTTP 驱动的工具而言它的 `path`，都是对外契约——
如果不带兼容方案就重命名，会破坏现有安装、已保存的配方，以及任何按名字
引用该工具的文档。哪些文件承载着这份契约见
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)。

## 新增一个配方

配方是数据，不是代码——完整概念见 [recipes/README.md](recipes/README.md)。
新增一个配方：

```
recipes/<id>/
  recipe.json    # schema "print-prep.recipe/1"; steps, tool bindings, acceptance
                 # criteria, provenance
  guide.md       # judgment calls and pitfalls, for both the AI and a person
```

校验规则（配方加载时强制执行，完整说明见 `SPEC_RECIPES.md`）：每一步都
必须指向一个真实存在的工具；预置的步骤参数会逐字段校验，并且永远不允许
是一个路径（配方不能让插件读写它指定的任意文件）；`date` 字段格式是
`YYYY-MM-DD`；`ref`/`note` 上限 120 字符，`author`/`license` 上限 60
字符，`version` 上限 20 字符。每次 `GET /api/recipes` 调用都会重新扫描
配方目录，所以往 `~/.print-prep/recipes/<id>/`（或
`$PRINT_PREP_HOME/recipes/<id>/`）里丢一个新配方，不用重启服务器就能
生效，并会在界面的配方抽屉里被标记为第三方。

## 新增一个托管服务适配器

托管适配器放在 `studio/adapters/*_service.py` 下，并接入
`studio/adapters/services.py` 里的通用分发器。新增的适配器必须满足：

- 绝不写死一个指向私有或公司内网端点的默认 `base_url`——一个端点唯一会被
  用到的方式，是它已经被显式写进 `services.json`（见
  [docs/zh-CN/CONFIGURATION.md](docs/zh-CN/CONFIGURATION.md#servicesjson-格式)）。
- 只能通过 `key_env` 读取凭据——`services.json` 只给出这个环境变量的名字，
  本身绝不包含它的值。
- 当 key 缺失或请求被拒绝时要干净地失败（返回一个结构化错误），而不是让
  服务器崩溃；服务器启动时不会调用任何适配器。
- 如果界面上需要一个"测试连接"步骤，就要能通过
  `studio/adapters/service_connections.py` 的 probe/execute 路径访问到。

## 新增一条面向用户的提示文本

人能读到的文本——错误信息、动作摘要、任务模板标题、provider 标签——从不
直接写在 Python 代码里。两种语言都放在一个消息目录里，代码只引用一个
稳定的 code：

- 在你所在那一层对应的目录里注册这个 code（`studio/core/messages*.py`、
  `studio/adapters/messages*.py`、`studio/shell/messages.py`；独立的
  打印包用 `print_prep/messages.py`），同时给出 `"en"` 和 `"zh-CN"` 两个
  版本。code 的格式是 `<module>.<snake_case_meaning>`，一旦发布就成为
  API 的一部分：每个 JSON 错误体都带着 `code`、`message` 和 `params`。
- 用 `EditorError.coded("module.meaning", **params)` 抛出（或者保留其他
  异常类型，用 `studio.i18n.render(...)` 拼出文本）；摘要、标题、标签都
  要在返回的那一刻用 `render(...)` 生成，而不是在 import 时就生成，这样
  才能跟随请求的语言。
- MCP 进程的语言来自 `STUDIO_LANG`，HTTP 则按每个请求的
  `Accept-Language`（面板会发送自己的 locale）。测试固定用
  `STUDIO_LANG=zh-CN`；新写的测试应该断言 `code`，而不是断言具体文案。
- 面板文本在 JS 里走 `t("key", { name })`，静态标记里用 `data-i18n="key"` /
  `data-i18n-attr="title=key"`（见 `studio/web/i18n.js`）；key 要同时存在于
  `studio/web/locales/zh-CN.js`（以它为准）和 `studio/web/locales/en.js` 里，按字母序排。
  两边 key 集合对不上、源码用了表里没有的 key、或者 `studio/web` / `studio/app` 的注释之外
  又出现中文（`tests/test_i18n_source_guard.mjs`，只豁免 `mock.js` 这份假数据），`npm test`
  都会失败。英文写短、写直白；用 `{占位符}`，不要拼接片段。

## 文档写作约定

- 英文是主版本。中文镜像（`README.zh-CN.md`、`SPEC.zh-CN.md`、
  `CONTRIBUTING.zh-CN.md`，以及每个 `docs/<NAME>.md` 对应的
  `docs/zh-CN/<NAME>.md`）跟随英文原文；改动其中一份时，要在同一次改动
  里把两份都更新。
- `docs/history/` 是冻结的——里面是带日期的验证/提案记录，保留下来是为了
  留痕，以后不会再维护。不要往里面添加新内容，也不要指望它保持最新；新
  文档一律放进 `docs/` 正式目录。
- 任何打算公开发布的内容里，都不要提及公司内部基础设施、内网主机名，或
  另一款产品的内部实现。

## 绝不能提交的内容

- API key、token，或任何凭据值（真实凭据该放在哪里见
  [docs/zh-CN/CONFIGURATION.md](docs/zh-CN/CONFIGURATION.md)——绝不放进
  `services.json`，永远放在环境变量或本地加密存储里）。
- 内网主机名、内部工单/wiki 链接，或其他公司内部引用。
- 复制自竞品、或描述竞品是如何被逆向/分析的代码或文字分析。抽象地比较
  能力没问题；描述*具体是怎么探查竞品内部实现的*则不行。

## 报告问题

提 issue 时请包含：你运行了什么（命令或 Codex 提示词）、你期望的结果、
实际发生的情况，以及 `~/.print-prep/studio.log` 里的相关行。如果和适配器
有关，请说明是哪个 provider（但永远不要附上 key 本身）。`bug` 这个 label
必须在仓库里存在，bug 反馈表单的 `labels:` 字段才会生效（GitHub 会静默丢弃
不存在的 label）。

## 报告一次没编辑对的操作

如果你指向了某个部件、提了修改要求，结果不对，请用
[编辑反馈模板](.github/ISSUE_TEMPLATE/edit-report.zh-CN.yml)，而不是提普通
issue；在 GitLab 上则选 `.gitlab/issue_templates/` 里的「编辑反馈」描述模板。
每份反馈都需要四件事：你指向了什么（视口点击、对象列表、调用
`studio_edit(action: "select")`，或一个 part-chat 分支，以及
`studio_get_state.workbench.objects` 里的对象 id）、你提出了什么要求、实际
发生了什么、你期望的结果是什么。`edit-report` 和 `bug` 这两个 label 必须在
仓库里存在，表单的 `labels:` 字段才会生效。
