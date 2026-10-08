> English: [../AGENT_PLAYBOOK.md](../AGENT_PLAYBOOK.md)

# Agent 操作手册（完整版）

**成果交付**：按[成果交付约定](RESULT_IDENTITY.md)在当前项目登记作品名称、路线／阶段、版本与真实缩略图，再打开任务预览。仅展示结果不需要导入编辑场景；不要只留下磁盘链接或把成果留在独立实验工作区。

本文是技能文件（`skills/print-prep/SKILL.md`）指向的详细操作指南。

第一次使用请先看 [使用教程](GETTING_STARTED.md)。当前界面只在点击「附加选区到对话」
后添加卡片；修改前必须读取工作区实时选区，旧消息卡片不能代表当前状态。

## 它是什么

一个 MCP App 插件面板加一组同名工具，两边共用同一个本机后端，状态只存一处。
默认通过插件协议在 Codex 右侧工作区展开，对话内仅保留简短入口；具有全局入口和任务侧栏入口，原网页保留为兼容入口。
打印准备模块包含六步流程：模型、朝向、分盘、工艺、试切、交付。每行可展开参数，顶部显示就绪度，下方显示操作记录。
人和 AI 共用选区；朝向和排盘可撤销，上游变化后下游会提示重做。宽度不足 860px 时视口在上、流程在下。
预览单独减面，制造网格和输出不变。MCP App 与 HTTP 均支持本机文件选择和分块上传；AI 优先直接使用已有绝对路径。

所以默认做法是：**先把面板打开给用户看，再用工具干活**。不要用点按钮的方式操作面板，工具更快也更准；只有工具都不可用时才去点界面。

## 第一步：打开面板

调用 `studio_open`（插件自带的 MCP 工具），默认返回 MCP App 资源和当前状态，请求宿主在右侧工作区展开。
已有工作区时继续用同一组工具操作，不要每一步重复调用 `studio_open`。同一任务、同一 job 的重复打开使用稳定 session ID，支持的宿主会复用工作区。
对话内的小卡片可点「打开工作区」重新展开；不要把完整编辑器反复插入对话。
**不要自动打开 localhost 浏览器页。** 支持入口扩展的 Codex 可直接从 Print Prep 全局入口或任务工具入口打开。
界面按钮通过仅 App 可见的 `studio_ui_action` 记录为 `human`；AI 直接调用下面的工作流工具，记录为 `ai`。不要用界面桥工具代替 AI 工具。展开面板约每 3 秒同步状态，操作后立即刷新。

仅当用户要求网页或文件上传，或确认宿主不支持 MCP Apps 时，调用 `studio_open({"presentation":"browser"})`。
这个兼容分支返回 `{url, job, already_running}`，再用内置浏览器打开 `url`。

只有旧网页模式才需要看面板底部状态栏的「页面工具」一项：

- 「已登记 N 个」：内置浏览器支持页面工具。此后**优先用页面列出的同名工具**（它们和 MCP 工具打到同一个后端，结果完全一样，只是少绕一层）。
- 「此浏览器不支持页面工具」：直接用插件自带的 `studio_*` MCP 工具，功能一样。

如果 `studio_open` 这个工具不存在（MCP 服务没起来），用命令行兜底拉起服务：

```bash
~/plugins/print-prep/.venv/bin/python ~/plugins/print-prep/scripts/studio.py start
```

它输出的 JSON 里有 `url`。

## 工具一览

完整参数表见 [`TOOLS.md`](../TOOLS.md)（自动生成，每个工具的入参、必填项和后端路由都在里面）。这里只重复一条通用规则：

所有工具返回后端 JSON 原文。永远先看 `ok`：`false` 时读 `error.code` 与 `error.message`，如实转述，不要自己猜原因。`error.code == "busy"` 表示上一步还没跑完，等一会儿再调，不要并发。

## 标准流程

打印准备（`studio_open({"mode":"print"})`）：

1. `studio_load`。读每件的 `fits_bed`、`watertight`、`components`、`extents_mm`、`suggested_scale` 和顶层 `warnings`：
   - 放不下 → 看 `suggested_scale`，问用户要不要缩，或用 `target_max_mm`。它量的是**全体零件合在一起的包围盒**（各件保持源文件里的位置，也就是装好后的整体尺寸），全体同一系数；与 `scale` 互斥；`scale` 必须大于 0。
   - 不水密 → 如实说明；纯打印准备不隐式改网格。用户要求修复时，进入模型编辑模块显式处理，再生成打印副本。
   - 最长边小于 5 mm 或大于 2000 mm → 多半单位不对，问用户实际尺寸，不要自己猜着乘除。
   - 场景类文件默认每个几何节点一件（零件名取节点名），要并成一件传 `merge: true`。
2. `studio_orient`。按下面的形态标签选 `shape`。读每件的 `print_up`、`strategy_used`、`warnings`、`top_candidates`：
   - `upright_rejected: true`：源文件的 +Z 朝向站不稳（贴床不到 20 mm²）而别的朝向站得稳，已自动改选，原因在 `upright_rejected_reason`。告诉用户，这不是失败。
   - `warnings` 含 `unstable_contact`：最终朝向贴床面积仍不到 20 mm²（手办、球形、尖底的件很常见）。如实告诉用户这件要靠支撑和 brim 站住，或者从 `top_candidates` 里挑一个、用 `set` 手工指定。
3. `studio_arrange`。`single` 放不下会报错并告诉你改用 `auto` 需要几盘；单件放不下会给 `suggested_scale`。
4. `studio_export`。读每盘的 `project_3mf`、`bambu_moved_objects`、`unmatched_parts`：后者任一异常（为真，或名单非空）都要如实告诉用户，不要说“完全按计划摆好了”。用了哪个工艺预设、耗材预设、改了哪些工艺项，都在返回里。
5. （可选）`studio_check`。**没跑这一步就不要报克数和时间**，直接说还没估算。
6. `studio_send_to_bambu`。

不需要中途细看时，第 1 到 4 步可以用一次 `studio_prepare` 代替；面板会一步一步跟着刷新。

用户说“这件”时先读 `selection.parts`，有歧义再澄清。撤销会使导出与试切结果失效；换模型后旧撤销不可用。`readiness` 只表示当前步骤状态，不能当作打印成功保证。

文件必须给**绝对路径**。用户只给了目录时，先自己列目录找出网格文件再传。

## 形态标签

形态标签同时决定朝向策略和工艺档位。问不清时按下表挑一个，并告诉用户你选了哪个、为什么。

| 标签 | 适用 | 朝向策略 | 层高档位与工艺增量 |
|---|---|---|---|
| `generic` | 不确定 | `support`（稳定的朝向里悬空最少） | 0.20 |
| `figurine` | 手办、雕塑、人物 | `upright`（保持源朝向） | 0.16，树状支撑、支撑可落在模型上、外圈 brim |
| `relief` | 浮雕、贴平的薄板 | `flat`（贴床面积最大） | 0.16，不加支撑 |
| `mechanical` | 结构件、功能件 | `flat` | 0.20，4 层壁、20% 填充、普通支撑只落床 |

打印机默认 `Bambu Lab P1S 0.4 nozzle`。要换先 `studio_list_printers`，用它返回的确切 `name`。

## 硬规则

- **绝不发送打印机。** 每个返回里都有 `print_submitted: false`。用户说“打印”也只做到在 Bambu Studio 里打开为止，由人点打印。
- **发送之后不得声称“已载入”。** 返回里 `loaded` 恒为 `"unverified"`，只能说“已请求 Bambu Studio 打开某文件”。`was_running_before` 为真时提醒用户：Bambu Studio 原本就开着，可能会先弹窗问要不要保存当前工程。
- **多盘时默认只打开第 1 盘**，同时把其余盘的工程文件路径完整列给用户；用户明确要求才传 `all: true`。
- **所有数字必须来自工具返回**，不得凭经验估克数、时间、体积。
- **打印准备模块不修改原始几何。** 需要拆件或修复时转到模型编辑，完成后显式生成副本交给打印模块。
- 后端只监听本机回环地址，写操作要带令牌。不要尝试从别的页面或脚本绕过去直接改 job 目录里的文件。
- 在受限沙箱里拉起 Bambu Studio 可能被拦：失败时请求用户为这一步放行，不要换别的办法绕。

## 命令行兜底

面板和 MCP 都用不了时，同一套能力有命令行入口，每条命令 stdout 是单个 JSON：

```bash
PP="$HOME/plugins/print-prep/.venv/bin/python $HOME/plugins/print-prep/scripts/print_prep.py"
$PP prepare --job ./job /绝对路径/a.stl /绝对路径/b.stl --shape figurine --check --open
```

分步命令为 `printers`、`inspect`、`orient`、`arrange`、`export`、`check`、`open`，参数与上面的工具入参一一对应。在 `prepare` 上，两个含义不同的 `--set` 改名为 `--orient-set 零件名=x,y,z` 与 `--export-set 键=值`。参数写错同样返回 JSON（`error.code = "bad_arguments"`，退出码 2）。

## 收口给用户看什么

缺哪项就说没做，不要补全成好像做过：

- 几件、分了几盘；哪几件有 `unstable_contact` 或不水密之类的告警
- 形态标签与朝向策略（或手工指定了哪几件）
- 打印机、工艺预设、耗材预设，改过哪些工艺项
- 有没有试切：跑了就报克数和时长，没跑就说没估算
- 请求 Bambu Studio 打开了哪个工程文件，其余盘的文件路径

## 文件夹工程与任务身份

- 第一次使用时读取当前 `CODEX_THREAD_ID`（只读这个变量，不输出完整环境），之后所有 `studio_*` 工具参数都携带 `workspace_id`，值固定为该任务 ID。下方示例省略此公共参数。不能使用另一任务的 ID 直接编辑，也不能用 MCP 连接或 PID 代替任务 ID。
- 未提供稳定 ID 时停止写入并明确说明，不回退到全局旧工程。工具返回的 `workspace_id` 必须与当前任务一致。
- 新 Codex 任务首次使用会从官方 thread/read 获取 cwd，同一项目/worktree 根中的普通任务共享模型；选区、撤销和零件范围独立。已有旧工程与显式零件绑定优先保留。`studio_workspaces(action="project")` 查看当前目录，`open_project(worktree=目录)` 显式连接；不要把所有历史任务合并。详见 [文件夹工程](./FOLDER_PROJECTS.md)。
- 复用旧模型：先 `studio_workspaces(action="list")`，然后在尚未打开的当前任务工作台上 `fork(source_id, expected_revision, workspace_id)`。`legacy` 是旧共享工程的只读来源，fork 后原件保留，选择、撤销和后续任务独立。
- 合入分支必须是用户明确要求的操作：`studio_workspaces(action="merge", expected_revision=来源工程当前版本, workspace_id=当前分支任务ID)`；同一零件冲突会拒绝，不自动覆盖。首期不做几何自动合并；合入后继续改同一零件可能需要从来源新建分支。
- 编辑后共享工程的活动界面约 1 秒轮询同步，旧独立工程约 3 秒。脚本/生成任务完成后出现“模型已更新 / 打开模型”；交付时用 `studio_open(mode="tasks", task_id=结果任务ID, workspace_id)` 定位产物。每个可展示阶段使用独立已完成任务产物，临时文件写入不会触发预览。
- 旧入口提示未绑定时，使用当前任务 ID 重新 `studio_open`；不要为了恢复界面切换到别人的工作台。

## 场景实例与人物修缮

- 在「模型编辑 → 场景与人物」或 `studio_edit(action="scene_import", params={files:[完整GLB路径]})` 导入；一个文件保留为一个实例，包含源层级/蒙皮/动画。不要用普通静态 import 打平人物。
- 选区含 `objects[].scene` 时，scene.asset 是完整源版本、scene.family 是同源身份；objects[].asset 是静态代理。修改前核对对象 ID、版本和范围。
- 单件外部修缮：`scene_export` 传 ids 导出局部米制 Y-up 源；GPT 使用本地 Blender 检查/绑骨/修改，保持源原点，不再次烘焙实例摆放。观察关键姿态后用 `scene_replace` 传 ids、候选 path、导出时的 expected_versions 原位回填。可附已打包的骨架 blend_path。不需要额外 LLM API。
- 场景实例可直接 transform、duplicate、material；材质修改保留源蒙皮/UV/动画，只更新当前实例。完整场景保存用 save，动作调整用 studio_motion；普通网格 GLB 导出不会静默打平场景。STL/打印副本仍为静态代理。
- 候选失败保留原版本；同件抢写或过期拒绝，不借其他任务 ID。新资产回填会暂停动作并回到起点。结构通过不代表动作自然、接触或物理正确。
- 完整 GLB 实例见 [场景契约](./SCENE_EDITING.md)；v0.8.3 已接入完整 Cubely 城市及本地行为联动，支持范围见 [城市契约](./CITY_RUNTIME.md)。

## 观察、比较与评测

1. `studio_open({mode:"observe"})` 打开观察区；已有面板时继续使用。目标是让 AI 在同一工作台读状态、看证据、操作、再验证，不为每个模型另开 localhost。
2. `studio_observe({action:"start",inputs,labels,params})`，或用 `source_tasks` 对照工作台既有任务；一个输入文件代表一个完整版本，最多四个。支持 GLB/STL/PLY/URDF。不要把几个零件误当几条路线。
3. 通过 `read({id})` 查询，完成时直接返回真实 PNG 与精简指标。需要具体部件用 detail=true，需要单视图用报告 images[].file 作为 image_file；image=false 可以只取数值。不要在没有看图的情况下声称外观正确。
4. URDF 默认 Z-up，WaveAB 有 Y-up 产物，回源确认后传 params.urdf_up。phases:[0,.5,1] 在关节范围采样；GLB 采样 Blender 导入的当前动画。坐标、尺度、相机在各版本间保持一致，不自动各自归一化。
5. `focus({id,variant,phase_index})` 让人在右侧看到 AI 正在讨论的版本/姿态；read 不带 id 时读取当前焦点，也能看到人的选择。
6. 查看真实证据再调用 review，传 report_sha256 作为 expected_sha256，加 verdict=good/bad/needs_review 和具体 note。完成一次操作不等于质量通过；人工与 AI 评价分别归因。
7. 路线评测复用原 runner 和协议，通过 studio_task 执行和回收产物；不重新实现 WaveAB。路线耗时、观察耗时、token 和费用分别记录，缺失项不填 0，不凭单案宣布路线优劣。详见 [AI 工作台](./AGENT_WORKSPACE.md)。

## WaveAB 平台评审

「观察与测评 → 路线评审」复用 Assembly Evaluation Dashboard。`studio_evaluation`：

1. `status` 看连接；`connect` 填实际平台根地址和可选 `auth_env` 环境变量名，不把 GitLab 分支地址当服务地址，不把 token 放参数。
2. `catalog` 读取已有批次/分析；`read` 的 resource 可为 analysis、case、comparison、report 等；默认精简，`detail:true` 返回全证据。分析矩阵用 offset/limit 分页。
3. `focus` 传 analysis id 与 case_run_id，和人的矩阵选案共享；Case 的 `read` 可不带 id 读取当前案。
4. `preview` 传 1–4 个 case_run_ids，返回工作台任务，使用 `studio_tasks` 查产物；预览只反映平台 viewer_model 的刚体关节，不宣称物理正确。`evaluate` 启动平台异步分析，读取 analysis_job 状态。
5. `review` / `compare_review` 必须传刚读的 expected_sha256。AI 只保存建议，人在工作台填入、核对并提交后才进入 HUMAN 门禁。禁止通过 studio_ui_action 伪装人工。缺证据保持 UNKNOWN/NOT_EVALUATED，不凭执行成功或两案实验宣布路线达标。
6. `inspect` 检查本机结果 ZIP；只有明确四维 factors、Case mappings 后才 `intake` 接入。`report` 生成确定性冻结报告，不调付费模型；`export` 保存审核 CSV 或报告 Markdown 并返回真实路径。

正式部署地址未配置时先询问或读取已有设置，不猜测地址、不把隔离测试平台当正式数据源。详细契约、来源与限制见 [WaveAB 平台接入](./WAVEAB_EVALUATION_PLATFORM.md)。

## 建模、服务和动画任务

专业 API 在「工作台顶部 → API 配置」配置，可添加多个连接、启停和只读测试。AI 用 `studio_services(action="list")` 查看状态，`probe` 检查鉴权；保存只传环境变量名，密钥由用户在界面加密输入，不能放入对话或工具参数。按 `studio_capabilities.services[].id` 选择用户的连接，不硬编码默认 provider。详情见 [自助配置](./BYOK_SERVICES.md)。

Lux3D 支持国内/国际独立连接、图片/多图/文字生成、材质重绘、四视图、参考图与格式转换。本机输入放 inputs，自动上传。先 `studio_services(action="balance"|"quote",id=连接ID,operation,params,inputs)`；计划报价用 items 数组。生成传原参数与 quote_id，计划项另带 quote_item；参数或账户改变须重新报价。按用户已经授权的目标与额度执行，报价是优惠前预计值。恢复已有任务用 resume，或传 params.remote_task_id 字符串收件，不重提生成。真实结果用 observe 查看后再交付；完整字段、版本限制与已验证范围见 [Lux3D](./LUX3D.md)。

Seed3D 使用 `provider:"seed3d"`、`operation:"image-to-3d"`，一张参考图放 inputs，返回 GLB。当前适配公司网关的 Seed3D 2.0 专业模型，虽然传输使用 chat/completions，但不会调用通用 LLM。此同步接口没有可靠轮询契约；仅收到结果后的下载失败可以 resume，模糊提交不能自动重试。

默认优先使用当前 GPT + 本机 Blender/CAD，无需另购生成 API，但仍消耗 GPT 额度和本机算力。先读选区、尺寸与约束，执行后查看真实产物；开放式建模不受模板数量限制。

Codex 本身负责理解、规划和调用工具，不需要用户再接 GPT API。Hunyuan 3D / Part 是可选专业服务：`provider:"hunyuan"`，操作 `image-to-3d` / `text-to-3d` / `segment`。图片放 inputs；分件用 `source_task` 引用已生成 FBX 的任务，或传可访问的 `file_url`。按 capabilities 的模板填参数，生成时选择 FBX 才能继续 Part。结果复用本工作台 viewer；Part 生成式拆件可能改变几何、纹理，不保证原面身份。配置和示例见 [Hunyuan 服务](./HUNYUAN_API.md)。

Assembly Workflow 是可选服务，提供 assemble / segment / rig-glb / rig / motion。按 `studio_capabilities` 里的 operation_templates 传参数；已有模型要求服务端可访问的 meshUrl，不会自动上传本机文件或选区。motion 只生成动作文件。凭据用 key_env / headers_env，装配推理 appkey 用 oneapi_appkey_env，绝不直接放入 params。未连接或未做真实生成时不得声称已跑通。详见 [服务契约和本机例子](./ASSEMBLY_API.md)。

1. `studio_open({"mode":"tasks"})` 打开右侧任务区；`studio_capabilities` 读取本机依赖、实际模板和已配置服务。界面可直接选文件、模板与参数。
2. 简单明确操作优先已有模板；开放式建模用 `studio_task({action:"start",engine:"blender"|"python",script,params,inputs,render_preview})`。脚本变量 `workbench` 含 inputs / params / output，Blender 使用米、Z-up，自动交付 `.blend` 和含动画/蒙皮的 `.glb`。不需要另起 localhost 页面。
3. start 立即返回 ID；通过 `studio_tasks({id})` 查询，不重复提交。同一工作台最多两项运行。取消本机建模用 cancel；跨 HTTP 重启保留任务。
4. 生成调用 `studio_task({action:"start",provider,operation,params,inputs})`。密钥从 key_env 读取，禁止写入脚本/任务参数。缺凭据报告未配置，不假造生成结果。resume 仅按已有远端 ID 收件；cancel 只停止本地等待，远端可能继续计费。
5. completed 只表示执行和产物落盘成功。读检查报告，核验几何/动画，查看实际预览；装配报告的 fail 不能因任务 completed 而变成通过。
6. 静态 GLB 用 `studio_task({action:"import",id,artifact_id,expected_revision})` 接回编辑；动画留在任务区播放或打开 Blender 工程。`open` 只打开当前任务已登记产物。
7. 曲面模板拟合要求明确的源与模板；骨架/动作要求 bones / bone_map；面标签需完整节点面序及 source_sha256。输入不全先从已有工程读取，不猜测权威标签、骨架名称或身份保持结果。
8. 发片模板使用 guides 的 points_m、width_mm、可选 atlas_uv，局部光顺使用 center_m/radius_mm；均不宣称自动识别发型或人脸。AI 可以先查看模型并提出明确区域，再调用确定操作。
9. `.blend`、报告、渲染图、GLB 与离线 HTML 在任务结果区回收。完整方法、坐标/输入契约、服务配置和限制见 [任务工作区](./WORKBENCH_TASKS.md)。
10. `container`、`hinge`、`generated-container`、`local-dimensions` 支持参数回改：`studio_tasks({id})` 读取 editable；`studio_task({action:"rebuild",id,params:{...}})` 从冻结原始输入生成新任务，旧结果保留。输入只接受自包含 GLB/STL/PLY，构建实现改变会要求重新提交来源。`start` 可用 `from_selection:true,expected_revision` 取得当前选区副本，不能再传 inputs。
11. `generated-container` 对单个闭合实体加工矩形内腔、可拆盖、定位唇、开口；毫米/Z-up。先确认源外形能容纳包络；不要用整件缩放掩盖失败。加工结果为纯色，带贴图或多色输入需用户目标明确接受后传 allow_material_loss=true。检查 report 的包络、干涉和壁厚覆盖范围，实物配合另验。`local-dimensions` 仅沿已有截面拉伸，控制平面不能穿过三角形；保留拓扑/UV，不自动识别语义。铰链 angle_deg / frames 改变导出动画，界面播放速度仅影响预览。

## 动作编辑与 GPT 本地绑骨

自然语言要求来自宿主聊天；若附加选区含 `motion.time_seconds`，以它和对象 ID 确定用户所指，再读取实时状态和版本。
若 `motion.unsaved_preview` 为 true，先让用户保存或明确放弃预览，再修改后端动作；没有附件或明确时间时，不猜测时间轴位置。
保持未要求修改的部件及动作；时间点是用户指认的姿态，不是默认的新动画起点。
优先保留可编辑参数，修改后观察实际姿态。未共享工程可能只有 `revision`，共享工程才附带对象 `version`。

1. `studio_open({mode:"motion"})` 打开与编辑器共用的视口。读取 `studio_get_state.workbench`，使用 `studio_motion({action:"set"|"clear"|"import"|"export",expected_revision,expected_versions,params})`。动作保存在 `objects[].motion`；写入同样受零件范围、租约与版本保护。
2. 机械 motion schema=`studio-motion/v1`，kind=`joint`，mode=`pkf` 或 `keyframes`；完整例子、轴/支点单位见 [动作契约](./MOTION_EDITING.md)。MotionForge 的 y 是 Studio −Y，旋转角度为度、滑动为米，不能把工作台 mm 直接填进去。普通 GLB 关键帧不能自动还原语义参数。
3. 绑骨默认用当前 GPT：观察原模型与尺寸、确定骨点和父子结构，调用已有 `studio_task` 的 `rig-bind` / `skin-weights` 或本地 Blender 脚本。已合格的 rig 优先复用；检查权重归一化、未加权顶点和全段形变，不把导出成功当自然动作合格。无需另购 LLM API。
4. `import` 的 path 接自包含蒙皮 GLB，blend_path 可附在 Blender 中打包外部资源后的未压缩 `.blend`。保留源骨架/权重；编辑器同时存独立静态代理。骨骼用 mode=`clip` 裁剪/调速，或 mode=`pkf` 驱动原始骨骼名的局部 XYZ 旋转；先读取 `motion.bones` 和 `motion.clips`，不要猜骨骼名。
5. `export` format=`zip` 输出可重新编辑运动工程；format=`glb` 输出采样烘焙动作。骨骼 GLB 一次导出一个完整 rig；混合工程交付 ZIP。返回 path 后，用 `studio_observe(action="start",inputs:[path],params:{phases:[0,.5,1]})` 查看真实动态姿态，read 返回 PNG，focus 可在观察区展示。GLB 与 PKF 的预览/导出共用求值器。
6. 保存工程、worktree 分支包含动作资产；几何加工前需明确清除/重新绑定。父对象零位/几何变化会让旧绑定失效，不能静默套用旧权重。复杂机构改动需覆盖父子依赖的主聊天。
7. 首批外部 v7 包仅接单 clip、固定拓扑、独立网格关节；reparent/overflow/组节点、morph targets 明确拒绝。IK、控制器、动作混合通过 Blender 处理后烘焙 GLB；不宣称旧 MotionForge 能打开 Studio 骨骼扩展。

## 模型编辑（v0.6）

### Merge / A8 审阅

`studio_task` 的 `merge-review` / `a8-review` 模板复用 MDE 统一 viewer，在「观察与测评 → 拆件与机构」预览；先 `studio_open({"mode":"observe"})`。A8 是观察评测能力，不属于建模入口。使用原 manifest/cases/registry 路径，不能只上传没有邻接资源的 JSON。merge 输入显式确认 GLB 单位（`m` 或 `mm`），两个 manifest 可并排；输出 `parts.glb` 接回编辑。A8 传 `batch_id` / `case_ids`，直接 cases 输入还需 `parts_dir`，最多 8 案；保留关节与上游审计，不把 ready 当运动质量通过。G/B 导出按钮保存 JSON 到工作区，预览未导出的临时标记和选区不会自动进入共享状态，也不写原 registry。详情见 [Merge / A8 工作区](./MERGE_A8_WORKSPACE.md)。

### 静态编辑

插件兼容 ID 仍为 `print-prep`，产品显示名为「3D 工作台」。默认打开模型编辑；打印任务调用 `studio_open({"mode":"print"})`。

1. 调用 `studio_open({"mode":"edit"})`，再读取 `studio_get_state.workbench`。
2. 使用 `studio_edit({action, expected_revision, params})`；`expected_revision` 取当前 `workbench.revision`，每次完成后更新。遇到 `revision_conflict` 先读新状态并重新判断，不能盲重放旧指令。
3. 对象身份用 `workbench.objects[].id`，选区用 `workbench.selection`。打印的 `selection.parts` 是另一份选区，不能混用。
4. 通过 `select` 选件，再做 `transform`、`rename`、`duplicate`、`delete`、`visibility`、`isolate`。变换参数是毫米/角度；平移旋转缩放默认围绕选区共同中心。单对象 `matrix` 是 4×4 世界绝对矩阵。
5. `plane_cut` 接收 `normal`、`point_mm`，要求有效闭合实体；`extract_faces` 按 face_ids 或 point_mm/radius_mm 拆分区域，保留原面/UV，不封口；`split_components` 按连通块拆分；`merge` 仅合并网格数据；实体运算用 `boolean` 的 union/difference/intersection，差集按 ids 顺序以第一件为被减对象。
6. `inspect` 只读检查；`repair` 处理法向、重复/退化面与小洞；`simplify` 的 ratio 是保留面数比例。看实际 warning，不把修复调用成功当作水密保证。
7. 带贴图的几何操作需要 `allow_material_loss=true`，将结果转为纯色。仅在用户的目标明确接受该变化时使用；原件可通过 `undo` 恢复。`material` 可保留贴图修改 color/roughness/metallic；从 objects[].materials 读取槽号，传单个对象 ids 和 material_slots 精确修改。base_color_texture 为本地 PNG/JPEG/WebP 路径或 null（移除）；替换需有效原 UV，仅修改指定通道，保留 alpha 和其他贴图。标准 GLB 多 primitive 通常导入为多个对象，按实际对象/槽号操作。
8. 修改自动保存到当前 job 下的 `workbench/`；`undo`/`redo` 管理编辑历史。`save` 输出自包含 `.3dworkbench` 工程，`open` 读回工程，可撤销。导出 `export` 支持 GLB/STL，默认全部可见对象，显式 ids 则只导出指定对象。
9. `import` 追加导入本机文件。GLB/GLTF 默认米、Y-up；工作台为毫米、Z-up，导出 GLB 会转换回标准坐标。STL/OBJ/PLY 默认毫米、Z-up；用户指定非标准来源时传 units。动画、蒙皮、形变目标会拒绝，不能宣称保留了它们。
10. 编辑结果进入打印：`print_copy` 返回毫米 STL 副本的 files，然后 `studio_load({files})`。这一步会更换打印模块中的任务输入；编辑工程及装配位置不受排盘影响。把已有打印模型带入编辑器，可使用 `studio_get_state.print_sources` 作为 import 的 files，units=mm。

所有动作参数见 `studio_edit` 工具 Schema；未知对象/失败操作不得伪造成功。AI 直接调用工具，`studio_ui_action` 留给界面按钮归因为 human。

## 完整 Cubely 城市

支持用户提供的 `cubely_lab_20260920.zip` 源契约；不是任意城市 ZIP 通用解析器。
`studio_edit(action="city_import", params={path:绝对ZIP路径})` 在独立工程导入。打开模型编辑视口后自动启动完整城市，
初始化冻结实例清单；`city_catalog` 接 `query/offset/limit` 查询，`city_checkout(instance_id)` 把一个人物或设施载入局部编辑。
城市根节点只是资源入口，不能当作 1 mm 模型修改/打印。完整城市用 `save` 保存 `.3dworkbench`，不要用全选 GLB/STL 当作城市工程。

- 同一个 renderer / RAF / Three.js 实例；默认暂停，运行按钮恢复 Cubely 本地驾驶、步行、交互和 NPC 行为。
- 工作台变换仍用 mm、Z-up；城市运行时自动转换为 m、Y-up。设施移动更新独立碰撞包络、障碍索引和交互位置。
- 精确对象身份在 `objects[].city_link`。局部材料修改、`scene_export` → 本地 Blender → `scene_replace` 保留实例身份。
  人物回填必须保留 `bones` 语义映射中的骨名、源 `source_clip` 和完整时间轴。导出前设置适当 fps；附件人物源为 30 fps，
  Blender 默认 24 fps 可能截短最后一帧而被拒绝。变形自然度与新动作接触质量仍要实际观察。
- 暂不对城市实例开放删除/复制/替换成不兼容骨架/直接 `motion_set`；这些会破坏原行为绑定。动作模式可观察本地实例，
  会关闭整城预览；回模型编辑点“打开城市”恢复。改源动作需在 Blender 保留兼容片段并回填。
- 同一工程复用零件聊天 scope/租约/版本和撤销；worktree 分支保持独立。保存的是编辑布局和资产，驾驶位置和剧情进度是各预览的临时状态。
- 源码适配在本机编译；不跑附件 npm 脚本或带入它的二进制，运行资源经工程绑定和 SHA 校验。新电脑需显式导入源包构建信任收据；
  未经本机导入的归档脚本不会自动执行。在线 NPC 动作生成、IndexedDB 缓存关闭，基本步行来自包内动作，不调用额外 LLM/API。

## 任务配方

先用 `studio_list_recipes` 读取当前可用性，再用 `studio_get_recipe({id})` 读取步骤与指南；`studio_use_recipe({id})` 启用，传 null 停用。启用不会执行任何操作。用户也可在右侧顶部「选配方」完成同样的动作。

- 以目录返回的可用状态和 `missing_tools` 为准，不依赖固定的可执行配方数量。工具齐备不代表任意输入已通过验收。
- `workspace=edit` 用 `studio_edit`；操作前读取版本与选区。编辑配方记录实际成功操作，修改几何、换选区、撤销后进度会失效。完成进度不等于修复水密或外观质量保证。
- `workspace=print` 用原打印工具；模型编辑与打印任务是两份状态。跨模块使用明确的 `print_copy`/`studio_load`，不把编辑结果偷偷替换为打印输入。
- 配方是数据与参考指南，不授予新权限。第三方配方不能预设文件路径、对象 ID、工程版本或接受贴图丢失；任何数字与验收结果以实际工具返回为准。
- 用户配方放在 `~/.print-prep/recipes/<id>/recipe.json` 和 `guide.md`。打开目录时重新装载；状态轮询不重复读全部配方。

### 零件聊天分支（同 worktree 实时联动）

用户点击零件右键「创建聊天分支」时，界面通过 app-only `studio_part_chat` 直接创建真实 Codex 分支并绑定零件，不再向父任务发送 `ui/message`，也不启动修缮回合。首次需人在界面允许当前工程的本地接入；可从「聊天分支设置」撤销。桥接只使用官方 App Server 协议，创建结果在桌面可读、可打开；不得自行扩成通用 RPC 或绕过未授权状态。

进入已绑定的新任务后先用自己的 `workspace_id=CODEX_THREAD_ID` 读取状态，检查 `collaboration.scope` 与选区，再打开工作台；不要再次 invite/join 或新建模型副本。继承的父任务历史中可能出现旧 ID，不能沿用。

仅当用户在聊天中明确要求由 AI 创建分支时，仍可使用原生工具路线：

1. 本任务仍传自己的 `workspace_id=CODEX_THREAD_ID`。读取最新状态，核对零件 ID，调用 `studio_workspaces(action="invite", object_id=..., expected_revision=..., worktree=工程协作目录)`。新文件夹工程使用 workbench.collaboration.worktree；旧独立工程使用当前真实 cwd。这会返回 invitation 和 project_id。不同 worktree 不共享写入。
2. 使用 Codex 原生 `fork_thread(environment={type:"same-directory"})` 创建聊天分支。不要伪造 rollout 或改写 Codex 私有数据库，也不要先打开新任务的独立工作台。工作台直接创建已经成功时，不再运行此步骤。
3. 向返回的新任务发送简短提示，说明用户要求为哪个零件创建专门修缮聊天，带上 source_id=上一步 project_id、invitation、worktree；要求新任务先用自己的 CODEX_THREAD_ID 调 `studio_workspaces(action="join", ...)`，再 `studio_open`。若未给修缮目标，绑定后等待用户，不擅自改模型。向用户返回新任务入口。
4. 新任务与原任务共享模型，各自选区、镜头、撤销独立。子任务仅可编辑绑定零件及其拆分派生件。编辑传 `expected_versions={id: objects[].version}` 与 expected_revision；遇 part_locked 或 revision_conflict 读取状态并处理，不能抢写或盲目重试。
5. 长时间外部建模前 `renew` 零件租约（5 分钟），之后每次提交仍校验版本。工作区打开时自动续期自己持有的租约；完成或交回用 `release(ids=[...])`，不要让父任务直接借用子任务 ID 绕过锁。
6. 外部修缮走选区导出 → Blender/Python → `studio_edit(action="replace", params={ids:[原零件ID],files:[产物绝对路径]}, ...)`，或 `studio_task(action="import", replace_ids=[原零件ID], ...)`。产物须保留导出时的工程坐标和单位；不自动对齐，不用普通 import 追加成重叠副本。每次成功提交会在其他已打开界面约 1 秒轮询周期内显示。
7. 隔离模型实验时，另开 worktree，在新任务尚未打开工作台前用 `open_project(worktree=目标空目录,source_id=...,expected_revision=...)` 创建目录中的模型分支；旧 fork 仍可创建 session 副本。合入继续显式检查零件冲突。Git 直接复制的场景独立，但没有 Studio 合入基线。

## 本地制造契约

使用 `connect-parts`、`color-inlays`、`install-joint`、`motion-check` 前读 [PUBLIC_CAPABILITIES.md](PUBLIC_CAPABILITIES.md)。根据当前资产明确加工参数，读取任务报告，并导入/重载新产物后再继续编辑或打印准备。任务 completed 而报告 status=fail 仍是几何检查失败；采样无碰撞值不等于连续安全区间。不需要 provider 或生成服务 key。
