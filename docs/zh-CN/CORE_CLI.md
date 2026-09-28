> English: [../CORE_CLI.md](../CORE_CLI.md)

# 核心 CLI（`python -m studio.core`）

这个插件的核心主张是："shell（Codex 插件、Blender 插件、别的 agent 的
skill）只是一层适配器；真正的能力都在 `studio.core` 里。"过去进入这一层的
入口只有 stdio MCP 服务器和本地 HTTP 服务器（`studio/shell/`），两者都是
面向 Codex 的。`python -m studio.core` 是第三个、也薄得多的入口：一个直接
调用 `studio.core.recipes`/`editor`/`tasks`/`observation` 的 argparse
CLI——调的和 shell 调的是同一批函数——完全不涉及 Codex 进程，也不经过
HTTP 服务器。免安装：只要 checkout 后同步好依赖（`uv sync`），在仓库根目录
运行 `uv run python -m studio.core <group> <verb> [options]` 即可。它和
服务器一样遵循 `PRINT_PREP_HOME`（默认 `~/.print-prep`）；不引入任何新的
环境变量。

## 契约

stdout 永远只输出恰好一个 JSON 对象。成功时：底层调用返回的字典，如果里面
没有 `"ok": true` 就在最外层补上（有些调用，比如 `Workspace.execute`/
`Tasks.start`，本身已经带了）。失败时：
`{"ok": false, "error": {"code": "...", "message": "..."}}`，退出码 1。
`--help` 在每个子命令上都能用（普通的 argparse 文本，退出码 0）——不会被
强制包成 JSON。

## 命令

### `recipes`（`studio.core.recipes`）

```bash
uv run python -m studio.core recipes list
uv run python -m studio.core recipes show cut-to-fit
uv run python -m studio.core recipes check recipes/cut-to-fit/recipe.json
```

`list`/`show <id>` 需要当前的工具列表来计算 `availability`/
`missing_tools`（和 `GET /api/recipes` 一样）；默认情况下它们读取仓库里
已提交的 `studio/core/tool_schemas.json`（由 `tools_schema.get_tools()`
生成，由 `tests/test_core_cli.py` 保证与之同步；可用 `--tool-schemas
path.json` 覆盖）。`--user-dir path` 用于覆盖用户配方目录（默认
`PRINT_PREP_HOME/recipes`）。`check <path-to-recipe.json>` 单独校验一个
配方目录（该文件本身 + 同目录的 `guide.md`）——在本地写配方时很有用。

### `editor`（`studio.core.editor.Workspace`）

```bash
uv run python -m studio.core editor apply --doc ~/.print-prep/job/workbench \
    --action primitive --params '{"kind": "box"}'
uv run python -m studio.core editor inspect --doc ~/.print-prep/job/workbench
```

`--doc` 是工作区目录（`project.json`/`assets`/`exports`）；默认是
`PRINT_PREP_HOME/job/workbench`，和 shell 的 `/api/edit` 默认 job 一致。
`apply` 执行一次 `Workspace.execute()` 动作；`--params` 是一个 JSON 对象
（或 `@file.json`）；`--expected-revision` 默认取工作区当前的 revision
（会先读一次），所以脚本里裸调 `apply` 不用额外多读一次。`inspect` 就是
一次普通的 `Workspace.state()` 读取——不带 revision，也绝不会产生修改。

动作名并没有被限制在 `choices=` 里（`Workspace.execute` 对未知动作本身就会
抛出清晰的错误）；`--help` 会尽力列出它们——优先从
`studio.core.editor_actions.ACTIONS`（如果这个模块存在）读取，否则退回到
从 `Workspace._apply`/`scene_assets.apply`/`city.apply`/`motion.apply`
里手工摘出的静态列表。Motion/scene/city 相关动作
（`motion_*`/`scene_*`/`city_*`）也是通过同一条路径可达——在
`Workspace.execute()` 内部按前缀分发，而不是一种独立能力——所以并不存在
单独的 `motion`/`scene`/`city` 子命令。

### `tasks`（`studio.core.tasks.Tasks`）

```bash
uv run python -m studio.core tasks list --job ~/.print-prep/job
uv run python -m studio.core tasks start --job ~/.print-prep/job \
    --request '{"template": "container", "params": {...}}'
uv run python -m studio.core tasks status --job ~/.print-prep/job --id <task-id> --log
uv run python -m studio.core tasks artifact --job ~/.print-prep/job --id <task-id> \
    --artifact <artifact-id> --out ./scene.glb
```

`--job` 默认是 `PRINT_PREP_HOME/job`；队列存放在 `<job>/tasks`，与 shell
一致（`cancel --id <task-id>` 用于请求取消一个正在运行的任务）。
`--request` 是 `Tasks.start` 所期望的 JSON body（也支持 `@file.json`）。
`artifact --out` 会在重新校验 sha256/大小之后把字节内容拷贝出来；不加这个
参数时，只报告元数据和任务自己持有的源路径。

`--request '{"provider": "...", "operation": "...", ...}'` 会*在进程内*
运行托管服务适配器（Lux3D/Hunyuan/Seed3D/Assembly/Meshy/Tripo）：
`Tasks.start` 会在 CLI 自己的进程里同步调用
`studio.adapters.services.prepare()`，先校验凭据、构建请求 payload，然后
才会把真正提交请求的任务子进程排进队列。`python -m studio.core` 不依赖
shell（没有 Codex、没有 MCP、没有 HTTP 服务器）——但它并不是不依赖适配器。

### `observe run`（`studio.core.observation.Observations`）

```bash
uv run python -m studio.core observe run --job ~/.print-prep/job \
    --input /abs/a.glb --input /abs/b.glb --label before --label after \
    --params '{"views": ["front", "iso"], "phases": [0, 1]}'
```

将 `model-observe` 模板排入队列（1-4 个 GLB/STL/PLY/URDF 输入，或用
`--source-task <id>` 复用之前某个任务的 GLB），走的是与 shell 的
`POST /api/observation` 路由相同的
`Observations.execute({"action": "start", ...})` 调用——因为它只和
`Tasks` 打交道，属于名副其实的 `studio.core`。读回一次已完成的观测
（`read`/`review`/`focus`）目前还没有专门的子命令；除此之外它就是一个
普通任务，所以用 `tasks status --id <id>` / `tasks artifact` 就能拿到
同样的输出文件。

### `print`（`print_prep.cli`）

```bash
uv run python -m studio.core print inspect --job ~/.print-prep/job --files a.stl
```

`print_prep` 本身已经自带一套完整的 CLI，有它自己的契约（`ok`/`command`/
`job`/`print_submitted`，退出码 0/1/2/3——见 `print_prep/cli.py`）。这里
只是一个纯粹的别名：`print` 之后的所有内容都原样未解析地传给
`print_prep.cli.main()`，因此输出/退出码与 `python -m print_prep.cli ...`
完全一致——它只是让已经在用 `studio.core` 的脚本不必为打印再学一套调用
方式。

## 从 shell 脚本以外的地方调用它

像 `tests/test_core_cli.py` 那样用 `subprocess` 拉起子进程即可——不需要
MCP 客户端或 HTTP 客户端，只需要"一个进程、stdout 上一行 JSON、退出码 0
或 1"：

```python
import json, subprocess, sys
result = subprocess.run(
    [sys.executable, "-m", "studio.core", "editor", "inspect", "--doc", workspace_dir],
    cwd=plugin_root, capture_output=True, text=True, check=False,
)
payload = json.loads(result.stdout)
```
