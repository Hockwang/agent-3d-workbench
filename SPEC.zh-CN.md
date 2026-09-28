> English: [SPEC.md](SPEC.md)

# print-prep 规格（v0.1，修订 1）

> 当前六步界面与共享状态以 [SPEC_V05.md](docs/history/SPEC_V05.md)（历史记录）和 [Codex 融合说明](docs/zh-CN/CODEX_V05_INTEGRATION.md) 为准；本文件保留基础制造/API 契约与旧版记录。

Codex 插件：把一个或多个网格文件做成可打印的 Bambu Studio 工程，并在 Bambu Studio 图形界面里打开，停在那里等人点打印。

## 0. 边界

- **全部是自有代码。** 朝向、排盘、3MF 写出、预设展开改编自作者早期私有研究代码 `manufacturing_kit/engine/print_waveab_v0/kitlib/{plate,slice_p1s,gates}.py`（同一作者，不在本仓）。**不得**参考、翻译或搬运任何第三方产品的私有源码或数值表。
- **不改引擎。** 那份研究代码不随本仓发布、也不被 import。插件自包含（Codex 安装时会把插件拷进缓存目录，相对路径会断）。
- **不发打印机。** 任何动作都不连接、不发送到打印机。所有 JSON 输出带 `"print_submitted": false`。
- **不碰用户配置。** 实现与测试阶段不得读写 `~/.codex`、`~/.agents`、`~/plugins`。安装由 `install.sh` 做，且只由主 session 运行。
- 测试不得弹出图形界面：`open` 一律用 `--dry-run` 测。

## 1. 目录

```
print-prep/
  .codex-plugin/plugin.json        # B
  skills/print-prep/SKILL.md       # B
  install.sh                       # B
  README.md                        # B
  SPEC.md                          # 本文件（只读）
  pyproject.toml  uv.lock          # A
  scripts/print_prep.py            # A  入口：from print_prep.cli import main
  print_prep/__init__.py           # A
  print_prep/cli.py                # A  argparse + 退出码 + JSON 输出
  print_prep/job.py                # A  job.json 读写、sha256
  print_prep/mesh_io.py            # A  载入与统计
  print_prep/profiles.py           # A  Bambu Studio 预设索引/展开/床参数
  print_prep/shape_table.py        # A  形态标签 → 朝向策略 + 工艺选择（自有数值）
  print_prep/orient.py             # A
  print_prep/arrange.py            # A
  print_prep/export3mf.py          # A  几何 3MF 写出 + 读回
  print_prep/bambu.py              # A  命令行封装（导出工程 / 试切）+ 图形界面打开
  tests/                           # A
```

A = 代码实现者，B = 打包实现者。互不写对方的文件。

依赖钉版本，与引擎一致：`numpy==2.4.6`、`scipy==1.17.1`、`trimesh==4.12.2`、`pytest>=8`，`requires-python >=3.12`。运行方式固定为 `uv run --project <插件根> python <插件根>/scripts/print_prep.py …`。

## 2. 环境变量（与引擎同名）

| 变量 | 默认 |
|---|---|
| `BAMBU_STUDIO_APP` | `/Applications/BambuStudio.app` |
| `BAMBU_STUDIO_PATH` | `$BAMBU_STUDIO_APP/Contents/MacOS/BambuStudio` |
| `MFG_BAMBU_PROFILE_ROOT` | `$BAMBU_STUDIO_APP/Contents/Resources/profiles/BBL` |

## 3. 命令行契约

通用：
- 每个命令 **stdout 只输出一个 JSON 对象**（`ensure_ascii=False`），给人看的进度行写 stderr。
- 退出码：`0` 成功；`2` 用户侧错误（参数错、放不下、文件不存在、网格不可用）；`3` 环境错误（找不到 Bambu Studio / 预设目录、命令行失败）；`1` 未预期异常。非 0 时 stdout 仍是 JSON：`{"ok": false, "error": {"code": "...", "message": "..."}}`。
- **参数解析错误也必须输出 JSON**（未知子命令、缺子命令、非法枚举值、未知参数）：退出码 2，`error.code = "bad_arguments"`，stdout 不得为空。
- 成功 JSON 顶层恒有 `"ok": true, "command": "...", "job": "<绝对路径>", "print_submitted": false`。
- `--job DIR` 是工作目录，状态存 `DIR/job.json`；命令按需读写它。重复执行同一步会覆盖该步产物并使后续步骤的记录失效（从 job.json 里删掉后续步骤的键）。

### 3.1 `printers [--filter STR]`
不需要 `--job`。列出预设目录 `machine/` 下所有 `instantiation == "true"` 的机器预设（展开 inherits 后）：
`{"printers":[{"name","printer_model","nozzle_mm","bed_mm":[x,y,z],"exclude_areas":[[x0,y0,x1,y1],...],"default_process","default_filament"}]}`
- `bed_mm` 由 `printable_area`（`"256x256"` 这类角点串）的包围盒与 `printable_height` 得出；`exclude_areas` 由 `bed_exclude_area` 的角点串取包围盒（空则 `[]`）。

### 3.2 `inspect --job DIR FILES... [--printer NAME] [--scale F | --target-max-mm H] [--merge]`
- 载入 STL / OBJ / PLY / GLB / GLTF / 3MF。场景类文件**必须应用节点变换**后再取几何（trimesh 4.12.2 的 `geometry.values()` 会丢变换；用 `scene.graph` 逐节点变换或 `scene.to_mesh()`/`dump(concatenate=...)`）。默认场景里每个几何节点一件，`--merge` 把一个文件并成一件。
- 连通性与水密性在**丢掉 UV、按位置合并顶点后的副本**上测（UV 缝会把同一位置的顶点拆开，造成假碎片）。原始几何不改。
- 单位按毫米。`--scale F` 统一缩放，**F 必须 > 0**（0 或负数 → 退出码 2；负数会镜像零件）。`--target-max-mm H` 把**全体零件的合并包围盒**（各件保持在源文件里的位置，即装配坐标系）的最长边缩到 H，全体用同一系数；H 必须 > 0。两者互斥。
- 默认打印机 `Bambu Lab P1S 0.4 nozzle`。
- 每件：`name`（单几何文件取文件主名；场景文件取节点名；重名加 `_2`）、`source`、`source_sha256`、`faces`、`vertices`、`extents_mm`、`volume_cm3`（不水密则 `null`）、`watertight`、`components`、`fits_bed`（六个轴向朝上里是否存在一个能放进可用区）、`suggested_scale`（放不下时给，保留 3 位小数，向下取）。
- 可用区 = 床尺寸四周各减 `margin_mm`（默认 5），高度减 5。
- 把缩放后的网格存成 `DIR/parts/<name>.stl`（二进制），后续步骤只读这份。**后续步骤载入它时必须按位置合并顶点**（STL 读回来顶点数是面数乘 3，不合并就写进 3MF 会让切片器看到一堆开边）。
- 警告列表 `warnings`：不水密、多连通块、面数超过 200 万、最长边小于 5 mm 或大于 2000 mm（多半是单位错）。

### 3.3 `orient --job DIR [--strategy auto|flat|support|upright] [--shape LABEL] [--set NAME=x,y,z ...]`
- `LABEL ∈ {generic, figurine, relief, mechanical}`，默认 `generic`。`auto` = 按 `shape_table` 取策略。
- 候选朝上方向：大平面片法向的反方向（按法向分箱聚合面积，份额 ≥3%）+ 六个坐标轴；`support` 策略再加 200 个斐波那契球面方向。
- 指标（每个候选）：`contact_area_mm2`（离最低点 0.05 mm 内且朝下的面）、`overhang_area_mm2`（面法向与 −up 的点积 > cos(阈值)，阈值默认 30 度，不含贴床面）、`height_mm`。
- **性能要求**：悬空面积先在「法向直方图」上算（把面法向按约 1 度分箱、累加面积，每个候选只对箱子求和）。**预筛只作用于斐波那契球面候选**：取直方图悬空最小的前 12 个进入精确评估；大平面片候选与六个坐标轴**无条件**进入精确评估（它们数量少，而「大平底朝下」的直方图悬空恰恰最差，预筛会把正确答案筛掉）。200 万面的网格单件应在 30 秒内完成。
- **稳定下限**：`STABLE_CONTACT_MM2 = 20`。贴床面积不到它的候选视为不稳。
- 策略：`flat` 贴床面积最大（平手比悬空）；`support` 在**稳定候选**里取悬空面积最小（平手比高度），没有任何稳定候选时取全体悬空最小；`upright` 保持源文件 +Z 朝上，仅当 +Z 不稳定且存在稳定候选时退到 `support` 的结果，并写 `upright_rejected: true` 与 `upright_rejected_reason`。
- 任何方式选出的朝向（含手工指定）若贴床面积 < `STABLE_CONTACT_MM2`，该件 `warnings` 里都要有 `unstable_contact`。
- `--set NAME=x,y,z` 手工指定，优先于策略。零向量或非法数字 → 退出码 2。
- 每件输出：`print_up`（单位向量）、`strategy_used`、三项指标、`warnings`（列表）、`top_candidates`（前 3 名及指标）。

### 3.4 `arrange --job DIR [--mode single|per_part|auto] [--gap 4]`
- 模式是**同一个枚举走到底**：命令行、job.json、内部函数用同一组字面量，不做别名转换。默认 `auto`。
- v0.1 **没有** `--group-by`（载入阶段不解析颜色，留着就是一个接受了却什么都不做的参数）。
- `--gap` 必须 ≥ 0，否则退出码 2。
- 每件先按 `print_up` 转到 +Z，再绕 Z 取 0 度或 90 度：优先让长边沿 X（货架法的行高更小），若那样宽度超出可用区则取另一个。然后货架法排布（大件优先）；避开 `exclude_areas`（压到避让区先往右躲，右边不够宽就另起一行并抬到避让区上沿之外）；件间距 `gap`。
- **放置后置校验**：每件落位后必须整体在可用区内、且不与任何避让区相交，否则视为「这一盘放不下」（开新盘或报错），不得带病落位。
- `single`：全部一盘，放不下 → 退出码 2，错误信息里给出「改用 auto 需要几盘」。`per_part`：一件一盘。`auto`：按顺序装，当前盘放不下就开新盘。
- 单件放不下（超出可用区，或因避让区永远落不了位）→ 退出码 2，并给 `suggested_scale`。不得以未预期异常（退出码 1）收场。
- 输出 `plates:[{index(从1起), parts, placements:[{part, T(4x4), x_mm, y_mm, footprint_mm}]}]`。
- **不许静默丢件**：所有零件必须恰好出现一次，函数末尾用显式 `raise` 校验（不用 `assert`，`python -O` 会剥掉）。

### 3.5 `export --job DIR [--process NAME] [--filament NAME] [--shape LABEL] [--set key=value ...] [--no-project]`
每盘两步：
1. 写几何 3MF `DIR/plates/plate_NN.geometry.3mf`（零件局部系几何 + build item 的 `transform` 存摆盘变换 + `Metadata/model_settings.config` 挂零件名）。写完**读回**，`pass` = 逐顶点最近邻双向误差 ≤ 0.01 mm **且** 每件的变换矩阵与请求一致；不通过则退出码 1。顶点与三角形用分块字符串拼接写出，不要逐元素建 XML 树（千万面级的件会吃掉几个 GB）。
2. 调 Bambu Studio 命令行生成真正的工程文件 `DIR/plates/plate_NN.project.3mf`：
   `--datadir DIR/bambu-cli-data --load-settings machine.json;process.json --load-filaments filament.json --orient 0 --arrange 0 --ensure-on-bed --outputdir … --export-3mf … --export-settings …`，**不带 `--slice`**。若实测命令行在不切片时拒绝导出，则改为带 `--slice 0` 并把这一事实写进 job.json 的 `export.notes` 与 README 的「已知限制」。
   生成后读回工程 3MF 的 build item 变换，与请求的摆盘变换比较（平移与旋转各自的最大差），写进输出；差异超过 0.01 mm / 1e-6 不算失败，但要如实报 `bambu_moved_objects: true`。
   Bambu 会把每件几何重新居中存储，居中量记在 `Metadata/model_settings.config` 的 `source_offset_{x,y,z}`（零件局部系）。设文件里的变换为 `(R_b, t_b)`，则与请求比较的平移是 **`t_b − R_b · offset`**（不是 `t_b − offset`；两者只在 `R_b = I` 时相等）。
   **任何一件没能在工程文件里对上号**（名字对不上）→ `bambu_moved_objects: true`，并输出 `unmatched_parts` 列表；不得只比较对上的那部分就报「没动」。
- 预设：机器预设取 job 里的打印机；工艺预设默认按 `shape_table` 的层高档位，在 `process/` 里找 `compatible_printers` 含该机器、`layer_height` 等于该档位的系统预设（找不到则退回机器的 `default_print_profile` 并写 warning）；`--process NAME` 直接指定。耗材默认机器的 `default_filament_profile[0]`。
- 覆盖项顺序：系统预设 ← `shape_table` 的增量 ← `--set`。全部记录进 `DIR/profiles/provenance.json`（含每个来源预设文件的 sha256、最终覆盖项、`machine_gcode_modified: false`）。**不修改机器 G-code。**
- `--no-project` 只做第 1 步。

### 3.6 `check --job DIR [--plate N]`
对工程所用的同一份几何 3MF 与预设，带 `--slice 0` 无头试切到 `DIR/check/plate_NN/`（与要打开的工程文件分开存）。每盘输出 `grams`、`seconds`、`warnings`、`returncode`、`wall_seconds`。失败不抛异常，如实返回 `null` 与错误串，退出码 3。超时默认 1500 秒。

### 3.7 `open --job DIR [--plate N | --all] [--dry-run]`
- 执行 `open -a $BAMBU_STUDIO_APP <project.3mf>`。默认 `--plate 1`。`--all` 逐个打开，每个之间等 3 秒。
- `--dry-run` 只输出将执行的命令。
- 之后用 `pgrep -x BambuStudio` 最多等 20 秒确认进程起来。输出 `launched`（布尔）与 `loaded: "unverified"`——**命令行无法确认文件已在界面里载入，不得声称已载入**。
- 找不到应用 → 退出码 3。

### 3.8 `prepare --job DIR FILES... [上述各步的选项] [--check] [--open]`
两个 `--set` 在这一层改名消歧：`--orient-set NAME=x,y,z`、`--export-set key=value`。
依次执行 inspect → orient → arrange → export（→ check）（→ open），任一步失败即停。输出汇总：每步的关键结果 + 产物路径清单。

## 4. `shape_table`（自有数值，可被 `--set` 覆盖）

| 标签 | 朝向策略 | 层高档位 | 工艺增量 |
|---|---|---|---|
| `generic` | `support` | 0.20 | 无 |
| `figurine` | `upright` | 0.16 | `enable_support=1`、`support_type=tree(auto)`、`support_on_build_plate_only=0`、`brim_type=outer_only`、`brim_width=3` |
| `relief` | `flat` | 0.16 | `enable_support=0` |
| `mechanical` | `flat` | 0.20 | `wall_loops=4`、`sparse_infill_density=20%`、`enable_support=1`、`support_type=normal(auto)`、`support_on_build_plate_only=1` |

每行在代码里配一句注释说明取值理由（常识性的切片经验即可）。

## 5. 测试（A 负责）

`uv run --project . pytest -q` 全过。至少覆盖：
1. `printers` 能列出 `Bambu Lab P1S 0.4 nozzle`，床 256×256×250、避让区 `[0,0,18,28]`。
2. 合成盒子走 inspect → orient → arrange → export `--no-project`：读回误差 < 0.01 mm；`flat` 把 30×20×5 的盒子最大面朝下。
3. `arrange` 三种模式：20 个 60×60×10 盒子在 `single` 下退出码 2 且信息里有所需盘数；`auto` 给出多盘且零件恰好各出现一次；`per_part` 给 20 盘。
4. 带 UV 缝的网格（人为把一个立方体的顶点按面拆开）`components == 1`、`watertight == true`。
5. 带节点平移的 GLB 场景载入后包围盒位置正确（验证没有丢变换）。
6. `open --dry-run` 输出的命令正确且没有启动任何进程。
7. 悬空面积的直方图近似与逐面精确值在一个球体加一个悬臂盒的合成件上相差 < 2%。
9. `flat` 预筛回归：12 边棱柱（外接半径 20、高 20）`--strategy flat` 必须选到平底朝下（贴床面积约 1200 mm²、高度 20），不得选到侧面。
10. 工程读回的数学：手工合成一个 Bambu 风格工程 3MF（请求变换 = 绕 Z 90 度 + 平移，几何按 `offset=(7,-3,11)` 居中并写 `source_offset_*`）。场景 A 未移动 → `bambu_moved_objects == false`；场景 B 真实挪动 (4,-10,0) → `true` 且平移差约 10.77 mm；场景 C 两件里一件名字对不上 → `true` 且 `unmatched_parts` 非空。
11. 读回闸门：请求绕 Z 90 度、文件里写单位阵的立方体 → `pass == false`。
12. 命令行契约：未知子命令 / 无子命令 / `--mode bogus` / `prepare … --set a=b` 四种输入，stdout 都是单个 JSON、退出码 2。`--scale -2`、`--scale 0`、`--gap -5`、`orient --set x=0,0,0` 退出码 2。
13. 排盘后置校验：P1S 上 240×40×10 的长条件必须放得下（往上挪过避让区上沿）；240×225×10 的板躲不开避让区 → 退出码 2 且 `suggested_scale` 小于 1；任意通过的排盘结果逐件验证在可用区内、互不重叠、不压避让区。
14. `--target-max-mm`：三个 100 mm 盒子分别在 (0,0,0)/(900,0,0)/(0,900,0) 的 GLB，`--target-max-mm 180` → `scale_applied == 0.18`。
8. 真实端到端（标 `@pytest.mark.bambu`，本机有 Bambu Studio 才跑）：对一批已修复好的示例 STL 五件跑 `prepare --shape figurine`（不带 `--open`），断言工程 3MF 存在、是合法 zip、含 `Metadata/project_settings.config`，并把「命令行不切片能否导出」「Bambu 是否移动了对象」两条实测结论打印出来。**再跑一臂 `--shape mechanical`**（朝向会带旋转；`figurine` 那臂 R 恒为单位阵，测不到读回公式）：两臂都断言 `bambu_moved_objects == false`、`unmatched_parts == []`、平移差 < 0.01 mm。产物写到 pytest 的 `tmp_path`，不写进仓库。

---

# 第二部分：Studio 面板（v0.2）

目标形态：一块在 Codex 右侧栏内置浏览器里打开的可视化面板。用户能点，Codex 也能直接操控；两边走同一组后端接口，画面实时同步。第一部分的命令行库是它的后端。

```
用户点按钮 ─┐
页面登记的 WebMCP 工具（Codex 经内置浏览器调）─┤→ 本机 HTTP 接口 → print_prep 库 → job 目录
插件自带的 stdio MCP 服务（兜底通道）─────────┘                     ↑ 状态只存这一处
```

## 6. 目录（新增）

```
studio/__init__.py
studio/shell/server.py          # P1  本机服务：静态页 + JSON 接口 + SSE
studio/shell/mcp_server.py      # P1  stdio MCP 服务（官方 mcp SDK），工具 → HTTP
studio/shell/tools_schema.py    # P1  工具名 / 说明 / 输入 schema 的唯一来源（服务端也经 /api/tools 发给页面）
scripts/studio.py         # P1  入口：start | stop | status | url
tests/test_studio_api.py  # P1
tests/test_mcp_server.py  # P1
studio/web/index.html     # P2
studio/web/app.js         # P2
studio/web/style.css      # P2
studio/web/vendor/**      # P2  从作者研究工具（manufacturing_kit/articulation/vendor/）拷 three.module.js、addons/controls/OrbitControls.js、addons/loaders/STLLoader.js（MIT，保留许可证头）
```

不走任何外网资源（无 CDN、无外链字体）。前端不要构建步骤：原生 ES module + importmap。

## 7. 本机服务 `studio/shell/server.py`

- 只监听 `127.0.0.1`。默认端口 8977，被占则顺延找空闲端口。启动参数 `--job DIR`（默认 `~/.print-prep/job`）、`--port`。
- 启动时生成随机令牌，把 `{pid, port, token, job, url, started}` 写进 `~/.print-prep/studio.json`（权限 0600）。`scripts/studio.py start` 后台拉起并等健康检查通过；已在运行则直接返回现有信息；`stop` 结束进程并删该文件。
- **防跨站**：所有请求校验 `Host` 头是 `127.0.0.1:<port>` 或 `localhost:<port>`；所有 `POST` 还要求请求头 `X-Studio-Token` 等于令牌（页面从同源的 `GET /api/session` 拿令牌；该接口拒绝带 `Origin` 且非同源的请求）。不发任何 CORS 放行头。
- 写操作单飞：同时只跑一个，期间其他写请求返回 409 `{"ok":false,"error":{"code":"busy",...}}`。写操作**阻塞到完成**再返回（导出约十几秒一盘，试切可达数分钟）。
- 写操作内部直接调用 `print_prep.cli` 的 `cmd_*` 函数（构造 `argparse.Namespace`），把 `CliError` 映射成 `{"ok":false,"error":{code,message}, ...payload}` 与 HTTP 状态（用户错 400 / 环境错 502 / 未预期 500）。不要起子进程跑命令行。
- 状态修订号 `rev`：任何写操作开始、结束各加一。`GET /api/events` 是 SSE，每次 `rev` 变化推一条 `data: {"rev":N}`，另每 15 秒一条注释行保活。

接口：

| 方法 路径 | 入参 | 说明 |
|---|---|---|
| `GET /` 与静态文件 | | `studio/web/` |
| `GET /api/session` | | `{token, url, job}` |
| `GET /api/tools` | | `tools_schema` 的内容，页面据此登记 WebMCP 工具 |
| `GET /api/state` | | 见下 |
| `GET /api/events` | | SSE |
| `GET /api/printers` | `?filter=` | 同命令行 `printers` |
| `GET /api/shapes` | | 形态标签表（朝向策略、层高档位、工艺增量），面板「打印增强」卡用 |
| `GET /api/part/<name>.stl` | | job 里 `parts/<name>.stl`（零件局部系、已缩放）。名字只许匹配 job 里登记的零件，防目录穿越 |
| `POST /api/load` | `{files:[绝对路径], printer?, scale?, target_max_mm?, merge?}` | = inspect |
| `POST /api/upload` | multipart 或 `?name=` 加原始字节 | 存到 `DIR/uploads/`，返回绝对路径（浏览器文件选择器拿不到本地路径，拖拽上传走这里）。单文件上限 500 MB，只收 stl/obj/ply/glb/gltf/3mf |
| `POST /api/orient` | `{strategy?, shape?, set?:{零件名:[x,y,z]}}` | |
| `POST /api/arrange` | `{mode?, gap?}` | |
| `POST /api/export` | `{shape?, process?, filament?, set?:{k:v}, no_project?}` | |
| `POST /api/check` | `{plate?}` | |
| `POST /api/send` | `{plate?, all?, dry_run?}` | = open，在 Bambu Studio 图形界面打开 |
| `POST /api/prepare` | load + 各步选项 + `check?` + `send?` | 一步到位；缺省步骤用默认值 |

`GET /api/state` 的形状（P1、P2 以此为准；`null` 表示该步还没跑或已失效）：

```json
{"ok": true, "rev": 12, "print_submitted": false,
 "busy": null, "last_error": null, "job": "/abs/dir",
 "printer": {"name": "Bambu Lab P1S 0.4 nozzle", "bed_mm": [256,256,250], "exclude_areas": [[0,0,18,28]], "margin_mm": 5},
 "options": {"shape": "generic", "strategy": "auto", "mode": "auto", "gap": 4},
 "steps": {"inspect": true, "orient": true, "arrange": true, "export": false, "check": false},
 "warnings": ["..."],
 "parts": [{"name": "body", "faces": 994890, "extents_mm": [60,40,120], "volume_cm3": 88.1, "watertight": true,
            "components": 1, "fits_bed": true, "suggested_scale": null, "source_center_mm": [0,0,60],
            "stl_url": "/api/part/body.stl?rev=3",
            "orient": {"print_up": [0,0,1], "strategy_used": "upright", "contact_area_mm2": 310.2, "overhang_area_mm2": 1520.0,
                       "height_mm": 120.0, "upright_rejected": false, "upright_rejected_reason": null, "warnings": [],
                       "top_candidates": [{"print_up": [0,0,1], "contact_area_mm2": 310.2, "overhang_area_mm2": 1520.0, "height_mm": 120.0}]}}],
 "plates": [{"index": 1, "parts": ["body"], "placements": [{"part": "body", "T": [[1,0,0,20],[0,1,0,30],[0,0,1,0],[0,0,0,1]], "x_mm": 20, "y_mm": 30, "footprint_mm": [60,40]}]}],
 "export": {"process_preset": "0.16mm Optimal @BBL X1C", "filament_preset": "Bambu PLA Basic @BBL P1S 0.4 nozzle", "overrides": {"enable_support": "1"},
            "plates": [{"index": 1, "project_3mf": "/abs/plate_01.project.3mf", "geometry_3mf": "/abs/plate_01.geometry.3mf", "bambu_moved_objects": false, "unmatched_parts": []}], "notes": []},
 "check": {"plates": [{"index": 1, "grams": 196.57, "seconds": 45000, "warnings": [], "returncode": 0}]},
 "sent": {"plates": [1], "launched": true, "loaded": "unverified", "was_running_before": false, "at": "2026-09-19T16:40:00+08:00"}}
```

`busy` 进行中时为 `{"op": "export", "since": "<ISO 时间>"}`；`last_error` 为最近一次失败的 `{"op","code","message"}`，下一次成功的写操作清空它。

## 8. 工具（WebMCP 与 stdio MCP 同名同参，定义只写一份）

`GET /api/tools` 返回 `{"ok": true, "tools": [{"name", "description", "inputSchema"（JSON Schema，根为 object）, "readOnly"（布尔）, "method"（"GET"|"POST"）, "path"（如 "/api/orient"）}]}`；`GET` 类工具的入参拼成查询串。`studio_open` 只在 stdio 侧有，不出现在这个列表里。

`studio_get_state`（只读）、`studio_list_printers`（只读）、`studio_load`、`studio_orient`、`studio_arrange`、`studio_export`、`studio_check`、`studio_send_to_bambu`、`studio_prepare`。入参与 §7 对应接口一致。返回值一律是接口返回的 JSON 原文。说明文字用中文，写清「本工具不会向打印机发送任何东西」「`loaded` 恒为 unverified，不得声称已载入」。

stdio MCP 另有一个 `studio_open`：确保本机服务在跑，默认返回 MCP App（`ui://print-prep/studio-v2.html`）和结构化状态；资源为自包含 `text/html;profile=mcp-app`，在支持的宿主中嵌入显示。工具 metadata 通过 `openai/ui.entrypoints` 声明 `global` / `thread` 入口，并用 `preferredModelDisplayMode: "fullscreen"` 请求右侧工作区（Codex 26.915.31945 (9922) 扩展，已核对本机 schema 和右侧标签页路由）。工具结果的 `openai/widgetSessionId` 来自 job 路径哈希，允许同一任务内复用面板。对话内 inline 只呈现简短入口和展开按钮；全局独立入口只支持 inline，但本身已有完整空间。只有显式 `presentation: "browser"` 时，返回旧的 `{url, job, already_running}` 网页地址。stdio 侧每个工具调用前都先确保服务在跑。

嵌入原型的 UI 源码为 `studio/app/`，`npm run build:app` 生成随插件分发的 `dist/studio.html`。按钮通过 MCP `tools/call` 复用后台；选区通过 `ui/update-model-context` 发送。每 5 秒获取状态，只在数据变化时重绘控件。预览资源 `print-prep://preview/<encoded-part-name>?v=<mtime_ns>` 只接受当前 job 的已登记部件并检查版本，不支持任意文件路径；每件最多 30,000 面的显示副本在内存缓存，原 STL / job / 制造输出不变。完整的上传、工艺表单、试切/发送 UI 仍在旧网页；现有 MCP 工具能力保持不变。

工作区采用固定可用高度布局，视口伸缩、属性区内部滚动和可折叠、底部操作独立；尊重 `safeAreaInsets`，避免宿主输入区遮挡。工作区自身明确设置背景和字色，不依赖宿主文档的深浅主题。WebGL 延迟到工作区展开时创建；收起保留相机/选区并暂停渲染；不自动反复请求 fullscreen，允许用户主动收起。

页面侧：优先使用具备 `registerTool` 或 `provideContext` 方法的 `document.modelContext`（当前 Codex 官方接口），兼容旧 `navigator.modelContext`。空对象不算可用接口；逐个等待 `registerTool({name, description, inputSchema, annotations, execute})` 完成（若只有 `provideContext` 则等待它一次性提供）；异步拒绝必须显示登记失败，不得提前报成功或在拒绝后切换通道；`execute` 内部就是 `fetch` 对应接口，返回 `{content:[{type:"text", text: JSON 字符串}]}`。登记结果显示在页面状态栏：「页面工具：已登记 N 个」或「页面工具：此浏览器不支持，Codex 需走插件自带的 MCP 服务」。

## 9. 面板（P2）

**外观 v0.4（2026-09-20，用户看过 v0.3 后说「全方面照搬感觉不太好」，并指定参考自家的 Lux3D 编辑器）**：布局与 v0.3 完全相同，只换视觉语言，改成和公司自己的 Lux3D 工作台一家的样子。对照来源 = Lux3D 编辑器登录后的真实界面（用户授权从他的 Chrome 登录态里看）加上它公开加载的样式表里的数值。要点：

- 底色是中性近黑（视口 `#000` 上叠一层左上角的柔光和模型背后一点蓝色光晕，计划栏 `#080808`，悬浮卡 `rgba(16,16,18,.86)` 加 20 px 模糊、1 px 白 12% 描边、圆角 18 px）。
- 强调色是品牌蓝。`--accent #2261f5` 只做填充、上面放白字（对比度 5.1:1），目前只有「发送」在用；深底上的强调文字与图标用浅一档的 `--accent-text #79b7ff`。
- 「选中」统一成一种写法：深蓝底 `#0d1528` + 浅蓝描边 `rgba(113,153,242,.9)` + 1 px 外环。朝向策略的单选卡、形态 / 分盘的小片、零件列表的选中行都是它；视口里选中的零件用同一个浅蓝 `#79b7ff` 的框。
- 形态 / 分盘两组分段控件从「一条槽里滑动的分段」改成一排独立的小片（没选中灰底，选中如上）。
- 绿 / 橙 / 红只表示状态（`--ok #34d399`、`--warn #ffbc33`、`--danger #fb7185`），不再兼作强调色；坐标轴 X / Y / Z 的字母颜色取同一组。
- 视图按钮条与「打印计划」重开按钮是深灰胶囊（`#292d32`、白 20% 描边、投影）；按钮条里的选中态是中性的白 16% 亮底。
- 「一键准备」是钢蓝渐变的次级主按钮（`#2e5a91 → #244774`），把最亮的品牌蓝留给「发送」。
- 「打印增强」卡是一层品牌蓝到靛蓝的淡渐变加浅蓝描边，标题用 `--accent-text`；拖拽上传区是深色棋盘格。
- 视口：画布改成透明，背景交给样式表；床面冷灰 `#17191e`，10 mm 细网格之上加一层 50 mm 主网格。
- 顺手修掉两个 v0.3 就有的问题：视图按钮的选中态一直没显示（被带 id 的选择器压住）；输入框里 `font: 12px inherit` 是无效写法、一直没生效。
- 加了 `prefers-reduced-motion`：关掉过渡与进度条动画。

外观在早期迭代中经历过多轮调整；页面结构、样式表、脚本、图标均为自行编写，没有拷贝任何第三方源码。功能、接口、工具与状态形状不变，下文「设置栏自上而下」列的各项功能都还在，只是搬了位置：

- 悬浮卡「摆盘设置」（视口右上）：打印机行、形态（四段）、朝向策略（2×2 单选卡）、分盘策略（三段）+ 间距、模型尺寸（合并包围盒只读 + 目标最长边 / 缩放）、按钮「选朝向」「排盘」「一键准备」。
- 悬浮卡「模型」（视口左上，已有零件时默认收起）：路径、拖拽上传、合并、载入、零件列表与告警。
- 悬浮卡「选中零件」（视口左下，选中才出现，卡头显示零件名）：贴床 / 悬空 / 高度三个小指标块、告警（代码译成中文）、候选朝向；每个候选旁的按钮文字缩短为「采用」（悬停提示仍是「用这个朝向」）。
- 视图按钮条（盘页签、装配 / 盘、适配视图）在视口底部居中。视口里选中的零件用浅蓝色框标出（v0.3 时是橙色）。三维画面会自动避开被展开的「摆盘设置」卡盖住的一侧；用户自己转过视角之后不再自动取景。视口列窄于 560 px 且用户没手动点过时，「摆盘设置」卡默认收起。
- 多盘时，视口的盘页签与操作条里的选盘下拉互相跟随，「床利用率」「摆盘尺寸」标明是哪一盘；`placements[].x_mm / y_mm` 是占位矩形的左下角，不是中心。试切有盘没出数时，耗材 / 时长合计前加「≥」并注明几盘没出数。
- 右侧栏「打印计划」：摆盘质量（零件 / 盘、床利用率、贴床面积、悬空面积、告警）→ 打印预估（成品尺寸、摆盘尺寸、耗材、时长，节标题旁「试切」）→ 打印增强（当前形态的层高档位、朝向策略与工艺增量，数据来自 `GET /api/shapes`）→ 3MF 工程参数（打印机、工艺、耗材、覆盖项、单位、高级）→ 导出与发送结果。栏可收起。
- 底部操作条：导出工程（图标按钮）、选盘（含「全部盘」）、「发送」。上方固定小字「只在 Bambu Studio 里打开，不会发送到打印机」。
- 忙碌时视口中下部出现进度卡（操作名、已用时长、不确定进度条；没有取消）。
- 宽度小于 600 px 时改为纵向：视口在上，三张卡与打印计划各节排在下方，操作条吸底。

原布局（v0.2，已被上面取代）：左侧三维视口占满剩余宽度，右侧 360 px 设置栏（窄于 900 px 时设置栏改到下方）。跟随系统深浅色。文案全中文，自有措辞。

三维视口（three.js）：
- 打印床：按 `printer.bed_mm` 画网格与边框，避让区半透明红，四周 `margin_mm` 虚线框。Z 朝上。
- 两种视图：「装配」= 各件在源文件里的位置（`parts/*.stl` 是局部系，源位置见 `source_center_mm`；没有就都放原点）；「盘」= 选中盘的 `placements[].T` 应用到对应零件。有 `plates` 时默认「盘」视图，上方页签切盘（盘 1 / 盘 2 …）。
- 每件一个稳定的颜色；悬停显示零件名；点击选中并在设置栏显示该件指标（贴床 / 悬空 / 高度 / 告警）与前三名候选朝向，每个候选旁有「用这个朝向」按钮（= `POST /api/orient` 带 `set`）。
- 大网格：STL 载入在后台进行并显示进度；单件超过 150 万面时用 `geometry` 原样显示但关闭逐帧拾取（只在点击时做一次射线检测）。
- 轨道控制器；「适配视图」按钮；`rev` 变化后只重建有变化的部分（零件 STL 的 URL 带 `rev`，未变就不重新下载）。

设置栏自上而下：
1. **模型**：路径输入框（可多行）+ 拖拽 / 选择文件上传；缩放（系数 或 整体最长边毫米数）；「合并成一件」勾选；按钮「载入」。下面列出零件表：名称、尺寸、面数、水密、是否放得下，有告警的标黄。
2. **打印机与形态**：打印机下拉（来自 `/api/printers`，默认 P1S 0.4）；形态标签四选一（通用 / 手办雕像 / 浮雕薄板 / 结构件）；朝向策略（自动 / 贴床最大 / 少支撑 / 保持原向）；按钮「选朝向」。
3. **分盘**：单盘 / 一件一盘 / 自动；间距；按钮「排盘」。显示盘数与每盘件数。
4. **工艺与导出**：显示将用的工艺预设与耗材预设（导出后显示实际值）；可增删的覆盖项表（键 = 值）；按钮「导出工程」。导出后逐盘显示文件路径、`bambu_moved_objects`、`unmatched_parts`（非空标红）。
5. **试切估算（可选）**：按钮「试切」；逐盘显示克数、时长（换算成 时:分）、告警。没跑过就写「尚未估算」。
6. **发送**：盘选择 + 按钮「发送到 Bambu Studio」。成功后写「已请求 Bambu Studio 打开 plate_01.project.3mf，未确认是否载入」；`was_running_before` 为真时加一句「Bambu Studio 原本就开着，可能会先问要不要保存当前工程」。固定一行小字：「本面板不会向打印机发送任何东西，打印由你在 Bambu Studio 里确认。」
7. 顶部一个「一键准备」按钮 = `POST /api/prepare`（用当前设置栏的选项）。

状态栏（底部）：忙碌中的操作名与已用时长、最近一次错误（可关闭）、页面工具登记情况、`rev`。任何写操作进行中，所有会触发写操作的按钮置灰。

调试：`?mock=1` 时不连后端，用内置的一份示例状态与两个程序生成的盒子渲染，方便离线自测。

## 10. 测试（P1）

- `test_studio_api.py`：起服务到临时 job 与随机端口；缺令牌的 POST 被拒（403）；`Host` 头不对被拒；用两个合成盒子走 load → orient → arrange → export（`no_project`）并核对 `/api/state` 各字段齐全、`rev` 递增、`steps` 正确；`/api/part/../x` 被拒；并发第二个写请求得 409；`send` 带 `dry_run` 不启动任何进程；SSE 在写操作后推了新 `rev`。
- `test_mcp_server.py`：用官方 SDK 的 stdio 客户端起 `mcp_server.py`，`tools/list` 含全部十个工具，`studio_open` 能拉起服务，`studio_get_state` 返回与 HTTP 一致；测试结束把服务停掉。环境变量 `PRINT_PREP_HOME` 可把 `~/.print-prep` 改到临时目录，测试必须用它，不得碰真实的 `~/.print-prep`。
