> English: [../CONFIGURATION.md](../CONFIGURATION.md)

# 配置

## 环境变量

以下是代码里实际会读取的每一个环境变量，已对照 `studio/`、`print_prep/` 和
`scripts/` 逐一核实：

| 变量 | 默认值 | 读取方 | 含义 |
|---|---|---|---|
| `PRINT_PREP_HOME` | `~/.print-prep` | `studio/__init__.py` | 本机服务器全部状态的根目录（会话文件、日志、默认 job 目录）。除非另有说明，下面其余状态路径都相对于它。测试必须把它指向一个临时目录，不能碰真实目录。 |
| `PRINT_PREP_WORKSPACES_HOME` | 与 `PRINT_PREP_HOME` 相同 | `studio/core/city.py`、`studio/core/workspaces.py`、`studio/__init__.py`（会透传给拉起的子服务器） | 按工作区（workspace）注册表的根目录（`workspaces/<id>/...`），与作用域收窄的 `PRINT_PREP_HOME` 分开存放，这样即使某个会话的 home 被嵌套到别处，跨对话/跨 worktree 的工作区查找仍能解析到原始注册表。 |
| `PRINT_PREP_WORKSPACE_ID` | 无 | `studio/core/workspaces.py` | 当工具调用没有显式给出 `workspace_id` 时使用的兜底工作区 id。没有逐对话任务 ID 的宿主（Claude Code、普通 MCP 客户端）在服务环境变量里设它；`install.sh --claude` 会自动设。 |
| `WORKBENCH_SERVICE_CONFIG` | `~/.config/codex-3d/services.json` | `studio/adapters/services.py`、`studio/adapters/service_connections.py` | 托管适配器配置文件的路径（见下文）。私有凭据存储与它同目录，文件名为 `connections.private.json`。 |
| `WORKBENCH_BLENDER` | 无（回退到按平台的默认值，再回退到 `PATH` 上的 `blender`——见下文） | `studio/core/tasks.py` | 显式指定 Blender 可执行文件的路径，供依赖 Blender 的任务使用（绑骨、重定向、网格模板）。 |
| `CODEX_HOME` | `~/.codex` | `studio/shell/codex_bridge.py` | Codex CLI 自身状态所在位置；用于与 `codex app-server` 通信以获取线程身份。 |
| `BAMBU_STUDIO_APP` | 无（回退到按平台的默认值——见下文） | `print_prep/profiles.py` | Bambu Studio 应用程序的路径（macOS 上是 `.app` 包本身；Windows/Linux 上是可执行文件本身），用于导出/打开打印工程。 |
| `BAMBU_STUDIO_PATH` | 从 `BAMBU_STUDIO_APP` 推导 | `print_prep/profiles.py` | Bambu Studio 命令行二进制文件的路径，用于无界面切片检查。在 macOS 上它位于 `.app` 包内部；在 Windows/Linux 上它与 `BAMBU_STUDIO_APP` 是同一个可执行文件。 |
| `MFG_BAMBU_PROFILE_ROOT` | 从 `BAMBU_STUDIO_APP` 推导 | `print_prep/profiles.py` | Bambu Studio 内置打印机/材料预设数据的路径。 |
| `STUDIO_LANG` | `en` | `studio/i18n.py` | 后端错误信息的进程级兜底语言（见下文"语言 / `STUDIO_LANG`"）。接受 `en`、`zh`、`zh-CN`，或任意 `zh-*`/`zh_*` 标记（大小写不敏感）；其他值或未设置均视为英文。 |

本地编辑、任务、动作或观测功能都不依赖以上任何一项。
`BAMBU_STUDIO_APP`/`BAMBU_STUDIO_PATH`/`MFG_BAMBU_PROFILE_ROOT` 只在打印准备
工作区的导出/检查/发送步骤中起作用，`WORKBENCH_BLENDER` 只用于依赖 Blender
的任务模板；当底层工具缺失时，二者都会返回一个干净的 JSON 格式错误，而不是
让程序崩溃。

### Bambu Studio / Blender 的按平台默认值

Bambu Studio 和 Blender 在不同操作系统上都没有统一的安装位置，因此
`print_prep/profiles.py` 和 `studio/core/tasks.py` 会在运行时根据
`sys.platform` 选取一个默认值，且始终可以被上面的环境变量覆盖：

| | macOS | Windows | Linux |
|---|---|---|---|
| Bambu Studio（`BAMBU_STUDIO_APP`） | `/Applications/BambuStudio.app` | `%ProgramFiles%\Bambu Studio\bambu-studio.exe`（或 `%LOCALAPPDATA%\Programs\Bambu Studio\...`） | `PATH` 上 `bambu-studio` 解析到的位置，否则用 `~/.local/bin/bambu-studio` |
| Bambu Studio 预设（`MFG_BAMBU_PROFILE_ROOT`） | `<app>/Contents/Resources/profiles/BBL` | `%APPDATA%\BambuStudio\system\BBL` | `~/.config/BambuStudio/system/BBL` |
| Blender（`WORKBENCH_BLENDER`） | `/Applications/Blender.app/Contents/MacOS/Blender` | `C:\Program Files\Blender Foundation\Blender */blender.exe` 中版本最新的一个 | `PATH` 上的 `blender`，否则依次尝试 `/usr/bin/blender`、`/snap/bin/blender`、`~/.local/bin/blender` |

以 Flatpak 方式安装的 Bambu Studio 在磁盘上没有单一的可执行文件路径；这种
情况下让 `BAMBU_STUDIO_APP`（或 `BAMBU_STUDIO_PATH`）指向一个单行的包装脚本，
脚本内容改为运行 `flatpak run com.bambulab.BambuStudio "$@"`。Windows/Linux
的预设根目录默认值未针对所有打包方式验证过——如果 `print_prep` 报告预设目录
缺失，就把 `MFG_BAMBU_PROFILE_ROOT` 设成你的安装实际存放 `machine/`、
`process/`、`filament/` JSON 的位置。

### 语言 / `STUDIO_LANG`

后端错误信息来自一个小型的 code -> `{"en": ..., "zh-CN": ...}` 目录
（`studio/i18n.py`，由 `studio/core/messages.py`、`studio/shell/messages.py`
等填充；参见 `docs/ARCHITECTURE.md` -> "Messages and languages"）。后端所有抛出的异常和 API 载荷里给人看的字符串都走这个目录。配方文件
（`recipes/*/recipe.json`、`guide.md`）和 `.codex-plugin/plugin.json` 属于内容，有意只保留一种语言。
任务在运行时写进产物的文字（例如 `shell-kit` 的 `report.json` 里的检查说明）按写它的那个进程的语言渲染，
之后不再变化。

有两个因素决定一条已改造消息使用的语言：

- **本地 HTTP 服务器**（`studio/shell/server.py`）会读取请求的
  `Accept-Language` 头，仅对该请求生效；如果这个头缺失，或指定了目录里没有
  的语言，就回退到 `STUDIO_LANG`（再退到英文）。
- **stdio MCP 服务器**（`studio/shell/mcp_server.py`）在进程启动时读取一次 `STUDIO_LANG`，
  并在每次转发给本地 HTTP 服务器的调用上带 `Accept-Language`，所以工具结果的语言跟着 MCP
  进程的环境走，即使按工作区常驻的 HTTP 服务器是早先用另一个设置启动的。`install.sh` 会把
  自己环境里的 `STUDIO_LANG` 写进生成的 `.mcp.json`（`STUDIO_LANG=zh-CN ./install.sh`）；
  `install.sh --claude` 则把它交给 `claude mcp add`（默认 `en`）。
- **面板本身**（浏览器页和 MCP App）按这个顺序决定自己的语言：这台浏览器里用顶栏语言开关
  存下的选择（`localStorage` 的 `studio.locale`），其次是给出这张页面的那个进程的
  `STUDIO_LANG`（设置了才写：浏览器页由 `studio/shell/server.py`、MCP App 由
  `studio/shell/app_resources.py` 写进 `<meta name="studio-language">`；没设置就留空），
  再次是浏览器语言，最后是 `zh-CN`。所以 `STUDIO_LANG=zh-CN ./install.sh` 也会让面板变中文，
  默认安装跟浏览器走，顶栏的开关只对当前这台浏览器覆盖前两者。
  面板把自己的语言作为 `Accept-Language` 发出去，面板里显示的后端消息跟着同一个选择走。
  面板全部文案在 `studio/web/locales/{zh-CN,en}.js`；两边 key 集合不一致，或界面源码里又出现
  写死的中文，`npm test` 会失败。

## 状态与配置文件位置

| 位置 | 用途 |
|---|---|
| `PRINT_PREP_HOME/studio.json` | 正在运行的本地 HTTP 服务器的会话文件：pid、端口、访问令牌、绑定的 job 目录，文件权限 `0600`。 |
| `PRINT_PREP_HOME/studio.log` | 本地服务器的 stdout/stderr。 |
| `PRINT_PREP_HOME/job/` | 默认的单工作区 job 目录（旧版布局，在没有涉及具体工作区 id 时仍会使用）。 |
| `PRINT_PREP_WORKSPACES_HOME/workspaces/<workspace_id>/job/` | 按文件夹项目/按 Codex 任务划分的 job 目录。 |
| `PRINT_PREP_WORKSPACES_HOME/workspaces/<parent>/part-chat/` | 某个工作区子对话的 part-chat 授权信息与日志。 |
| `PRINT_PREP_HOME/recipes/<id>/` | 用户安装的配方（`recipe.json` + `guide.md`），会与仓库自带 `recipes/` 目录里的配方一起被读取。 |
| `~/.config/codex-3d/services.json`（或 `$WORKBENCH_SERVICE_CONFIG`） | 托管适配器配置：哪些 provider 被启用、它们的 `base_url`，以及各自的密钥保存在哪个环境变量里。这个文件本身永远不包含凭据值。 |
| `~/.config/codex-3d/connections.private.json`（与上面文件同目录） | 私有凭据存储：一个加密信封，文件权限 `0600`。这是文件系统权限层面的保护，不是操作系统钥匙串级别的加密。 |
| `~/plugins/print-prep` | Codex 加载插件所用的符号链接，由 `install.sh` 创建，指回克隆下来的仓库。 |

`PRINT_PREP_HOME`/`PRINT_PREP_WORKSPACES_HOME` 下的每一条路径都遵循这两个
环境变量；这里没有任何路径写死绑定到具体某个用户账号。

## `services.json` 格式

只有在这里显式配置了某个托管适配器，它才会被使用——没有默认的托管端点，
服务器启动时也不会调用任何适配器。示例（凭据值永远不会存在这个文件里，
只存放保存该值的环境变量名）：

```jsonc
{
  "providers": {
    "my-hunyuan": {
      "title": "My Hunyuan endpoint",
      "adapter": "hunyuan-responses",
      "base_url": "https://your-own-gateway.example.com/v1",
      "key_env": "MY_HUNYUAN_API_KEY",
      "enabled": true
    }
  }
}
```

- `adapter` 决定由 `studio/adapters/*_service.py` 中的哪个客户端模块来处理
  这个 provider 的请求（`hunyuan-responses`、`seed3d-chat`、`lux3d`、
  `assembly`、`meshy`、`tripo` 等）。
- `base_url` 在使用前会被校验，代码本身从不会给它一个私有端点的默认值；
  每个内置 provider 模板出厂时 `enabled` 实际上都是关闭的，直到填入真实的
  key 为止。内置的 `hunyuan` 和 `seed3d` 出厂自带 `base_url: ""` 与
  `requires_base_url: true`——它们说的是一种兼容 OpenAI 的网关协议，而不是
  某一家厂商专属的 API，因此没有唯一正确的默认值可以写死；在你设置
  `base_url` 之前，`studio_capabilities`/界面都会显示它们还需要一个
  `base_url`，`prepare()`/`run()` 也会拒绝提交（参见 [Hunyuan](HUNYUAN_API.md)
  与 [BYOK 服务](BYOK_SERVICES.md)）。
- `internal_origin` 是仅供 Assembly 使用、需要显式开启的字段，用于固定的
  `transport: "assembly-prodtest-http"` 路由：它的作用与约束（不带凭据、
  不带路径、不带查询字符串）见 [Assembly](ASSEMBLY_API.md)。
- `local_inputs_allowed`（默认 `true`）声明这个 provider 上的任务是否可以携带
  `studio_task` 的 `inputs`（本机文件路径）。内置的 `assembly` 条目默认为
  `false`——它只接受服务端可访问的远程 URL，从不自动上传本机文件；自定义
  provider 不设置这个字段时保留今天「允许本机输入」的行为。
- `default_timeout_seconds`（默认 `600`）是 `studio_task` 调用没有自带
  `timeout_seconds` 时使用的任务超时。内置的 `assembly`、`hunyuan`、`seed3d`、
  `lux3d`、`lux3d-global` 条目把它设为 `1800`，因为这些适配器的远端任务通常比
  Meshy/Tripo 那类默认跑得更久；自定义 provider 不设置这个字段时保留
  `600` 秒的默认值。
- 上面这两个字段，对于在这两个字段进入 `BUILTINS` 之前就已经通过面板保存的
  BYOK 连接（或一条纯 `services.json` 条目），同样会被回填：`services.config()`
  会从这个连接创建时所用的内置模板（`connection_template`）里补上缺失的那个
  字段；没有模板的条目，则从与它 `adapter` 相同的第一个 `BUILTINS` 条目里取——
  这样一个在旧版本插件下保存的连接，升级后仍然保留原本的超时与本机输入策略，
  而不会悄悄退化成 `600`/`true`。保存的条目上已经存在的值永远优先于回填。
- `allow_unquoted`（仅 Lux3D 适配器，默认 `false`）让 `lux3d`/`lux3d-global`
  条目退出服务端强制报价，付费操作可以不带 `quote_id` 直接提交；内置模板
  从不设置它——报价到收件的流程见 [Lux3D](LUX3D.md)。
- `key_env` 指定一个环境变量的名字，进程自身的环境必须已经提供这个变量；
  文件本身永远不保存 key 的值。通过界面输入的 key 会在客户端加密，只在
  进程内解密，存放在同目录的 `connections.private.json` 里，而不是
  `services.json`。
- 在发出任何请求之前，payload 和 URL 都会先经过校验（
  `studio/adapters/services.py` 中的 `validate_url`/`validate_payload`），
  并且发出的请求永远不会跟随重定向。

完整的界面配置流程见 [BYOK 服务](BYOK_SERVICES.md)，各 provider 的具体细节见
[Assembly](ASSEMBLY_API.md) / [Hunyuan](HUNYUAN_API.md) / [Lux3D](LUX3D.md)。

## `.mcp.json`

`install.sh` 会在仓库根目录生成 `.mcp.json`；它不受 git 跟踪，在全新克隆的
仓库里不存在，直到你运行安装脚本。它的结构如下：

```json
{
  "mcpServers": {
    "print_prep_studio": {
      "command": "/absolute/path/to/plugin/.venv/bin/python",
      "args": ["/absolute/path/to/plugin/studio/shell/mcp_server.py"],
      "cwd": "/absolute/path/to/plugin"
    }
  }
}
```

`command` 指向插件自己虚拟环境里的解释器（通过 `~/plugins/print-prep` 这个
符号链接），而不是依赖 `uv`/`python3` 在 `PATH` 上可用，因为 Codex 桌面端
启动子进程时用的 `PATH` 很短。如果你是手动接线而不是跑 `install.sh`，写这个
文件时要换成真实的绝对路径；Codex 实际读取的只有两处：MCP server 的 key
（`print_prep_studio`）和脚本路径（`studio/shell/mcp_server.py`）。

### 手动安装（任意操作系统，含 Windows）

`install.sh` 是 bash 脚本，开箱即用只能在 macOS/Linux 上跑。在任何操作系统上
（包括 Windows，或不想跑脚本的 macOS/Linux），都可以手动把插件接上：

1. 在插件目录内执行 `uv sync`，创建 `.venv` 并安装依赖。
2. 把 [`.mcp.json.example`](../../.mcp.json.example) 复制到同目录下的
   `.mcp.json`，并把 `<ABSOLUTE_PATH_TO_PLUGIN>` 替换成插件的真实绝对路径。
   在 Windows 上，解释器路径是 `.venv\Scripts\python.exe`（不是
   `.venv/bin/python`），另外两处路径统一用反斜杠或统一用正斜杠都行——只要
   不把未转义的反斜杠和后面看起来像转义序列的字符混在一起，两种写法在
   JSON 字符串里都能用。
3. 把插件注册进 Codex（`codex plugin add <name>@<scope>`，或者你所用的
   Codex 版本用来发现本地 `.mcp.json` 的其他方式）。
4. 在启动 Codex 的环境里设置上表中你需要的环境变量（`WORKBENCH_BLENDER`、
   `BAMBU_STUDIO_APP`/`BAMBU_STUDIO_PATH`、`WORKBENCH_SERVICE_CONFIG` 等），
   然后重启/重新连接后端。

以上流程都不需要 `install.sh`、`~/plugins` 符号链接，或它维护的 marketplace
文件——那些只是常见场景下的便利做法，不是 MCP 契约本身的硬性要求。

## 端口

本地 HTTP 后端默认监听 `127.0.0.1:8977`（`studio/__init__.py` 里的
`DEFAULT_PORT`）；如果 8977 被占用，`scripts/studio.py start` 可以显式接受
一个不同的端口。

## 平台差异说明

`BAMBU_STUDIO_APP`/`WORKBENCH_BLENDER` 的默认值，以及用来启动/探测 Bambu
Studio（macOS 上的 `open -a`、Windows 上的 `os.startfile`、Linux 上的
`xdg-open`）和检查它是否已在运行（macOS/Linux 上的 `pgrep`、Windows 上的
`tasklist`）的命令，全部按平台分发——见上文
[按平台默认值](#bambu-studio--blender-的按平台默认值)。你始终可以用显式的
环境变量覆盖其中任何一项；如果底层的可执行文件仍然找不到或启动不了，受
影响的步骤会返回一个干净的 JSON 格式错误，而不会让服务器崩溃。编辑、不
依赖 Blender 的任务、动作与观测功能本身的代码里都没有操作系统专属的路径
分支。
