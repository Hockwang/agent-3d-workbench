> English: [../WORKBENCH_TASKS.md](../WORKBENCH_TASKS.md)

# 2026-09-22：建模、服务与产物工作区

本轮把插件从静态编辑/打印扩展为三种工作区：模型编辑、建模与任务、打印准备。
兼容插件 ID `print-prep`，显示名「3D 工作台」。默认仍由 MCP App 在 Codex 右侧展开。

## 已接通的功能

- 33 个本地任务模板，另可执行 AI 编写的可信 Blender/Python 脚本。Blender 负责工程、网格、UV、烘焙、骨架与动画；CadQuery/OCP 负责精确实体及 STEP；Trimesh/Manifold 负责拆件、截面和实体检查。
- 参数化容器、铰链、CAD 外壳/拉伸/回转、作者研究仓库中的销铰和薄回转试片；来源记在 `studio/core/kernels/SOURCES.json`。
- 光顺/减面/实体化/体素重建/展 UV、高低模底色与法线烘焙、固定拓扑表面拟合、局部有界 Taubin 光顺、显式引导生成发片。
- 保原面和 UV 的面标签拆分；编辑器增加点击模型定位球形区域并拆件，结果不自动封盖。
- 显式骨架自动权重、权重归一与影响数限制、显式骨名映射的动作重定向、动画合并与预览、场景陈列和离线渲染。
- 灰度图片闭合浮雕、毫米 SVG 分层、静态和显式采样运动的实体干涉检查；`assembly-audit` 新增 URDF 模式，按单个 URDF 自身的关节范围（或 `joint_ranges` 覆盖值），沿关节空间对角线同时、线性地联动扫掠每个可动非 mimic 关节——一条直线，不是遍历所有组合，只在混合姿态下才出现的碰撞不在覆盖范围内。mimic 关节仍会跟着动（由 `yourdfpy` 从其主关节解出，不算进这次扫掠本身），仅通过 `fixed` 关节相连的连杆会先合并成每个刚性组一个实体再测试，重叠按组以毫米为单位检查。`removal-audit` 对任意一组水密 STL 部件复用角色头壳任务的同一套离散拆卸/装配顺序采样。
- 离线交互 HTML：原始 GLB 嵌入、动画、观察/漫游和点击热点；不包含物理引擎或通用游戏逻辑。
- 右侧可查看 GLB/动画、渲染图、JSON 报告和隔离的交互网页；可取回静态结果继续编辑、打开 Blender/STEP 工程、保存文件。动画不强行降为静态编辑工程。
- MCP 与 HTTP 共用分块上传（唯一目录、连续偏移、重传校验），文件可由人选择，无须全部输入路径。

## 任务契约

`studio_capabilities` 返回实际模板、执行环境和服务配置状态；`studio_task` 启动后立即返回 ID；`studio_tasks` 查询状态、尾部日志与产物。
任务位于 `<job>/tasks/<id>`，含 request、脚本摘要、输入 SHA256、运行记录、状态、产物 SHA256。
独立 worker 可跨 HTTP 重启继续执行，同时至多两项；超时和取消终止其自身进程组，不按可能被复用的 PID 杀进程。

脚本使用 `workbench = {inputs, params, output}`。Blender 单位米/Z-up，自动保存 `.blend`、动画 `.glb` 和可选渲染图；其他输出写到 output。
`completed` 代表进程成功且有产物，不代表审美、身份、制造或运动自然度验收通过。必须继续读报告、检查真实模型。
脚本与用户 shell 同权，是可信代码执行入口，不是隔离运行不可信代码的沙箱。
静态编辑操作和产物 import 都保留工程版本检查，失败不会覆盖当前几何。

## 自备 API

内置 Meshy / Tripo，分别引用 `MESHY_API_KEY` / `TRIPO_API_KEY`。密钥只从服务进程环境读取，不写进任务参数、产物或前端。
本次没有配置真实账户，因此只完成实际 HTTP 模拟服务的契约/恢复/凭据隔离验证，未声称云端生成质量通过。
配置 `WORKBENCH_SERVICE_CONFIG` 或 `~/.config/codex-3d/services.json` 可以接入其他已知契约的异步服务：

```json
{
  "my-service": {
    "title": "我的模型服务",
    "adapter": "generic",
    "base_url": "https://api.example.com",
    "key_env": "MY_3D_API_KEY",
    "operations": {
      "generate": {
        "submit": "/jobs",
        "poll": "/jobs/{id}",
        "id_path": "id",
        "status_path": "status",
        "success": ["completed"],
        "failure": ["failed"],
        "artifacts_path": "artifacts"
      }
    }
  }
}
```

具体字段以 `studio/adapters/services.py` 为准；下载项为已确认的文件 URL。`$file` 在本机转换为 data URI，支持服务的既定契约，不会推测私有接口。
提交前持久化意图，只尝试一次 POST。已有远端 ID 时可以 `resume` 继续轮询/收件；未知是否提交成功时保留不确定状态，不自动重提。
已完成的托管服务任务，其 `output/service.json` 记录 `provider`、`operation`、`adapter`、`model`（该 adapter 若有可选模型/版本，就是请求里选的那个——例如 Hunyuan 的 `model`、Lux3D 的 `version`、Assembly 的 `workflowTemplateId`；若像 Seed3D 那样只有单一固定模型，就是那个固定值）、`remote_id`、`status`、`cost`/`cost_unit`、`request_params`（提交的 payload，落盘前经过清洗：任何名字含 key/token/secret/authorization 的字段整体移除、看起来像 URL 的字符串值会被去掉查询串和片段、`$file` 标记会被压缩成引用文件本身的文件名——凭据本来就到不了这里，因为 `validate_payload` 已经拒绝它们）、`input_sha256`（每个本机输入文件的名字 + SHA256）以及 `submitted_at`/`received_at`。它永远不含 `base_url`、签名下载地址或原始供应商响应。这对通用 REST 任务 adapter 和每个专用供应商 adapter（Lux3D、Assembly、Hunyuan、Seed3D）都一样。任务运行期间，`studio_tasks` 返回的 `service` 对象也会同步回显 `cost`/`cost_unit`/`model`/`adapter`/`submitted_at`/`polled_at`/`received_at` 这几个字段。
“停止等待”仅取消本机轮询，不等于供应商停止计算或停止计费。服务配置存在也不等于该服务实时健康。
Meshy 对照公开文档：[文字生成](https://docs.meshy.ai/en/api/text-to-3d)、[绑骨](https://docs.meshy.ai/en/api/rigging)、[动作](https://docs.meshy.ai/en/api/animation)。

## 精度与性能

编辑资产在标准 float32 GLB 显示数据之外保留 float64 权威几何，用于工程重开和继续处理；当 float32 STL 会合并不同顶点时用 ASCII STL。
GLB 向外部软件导出仍受格式 float32 精度约束，不把显示精度说成制造精度。
3MF 顶点按 17 位有效数字写出；Bambu 工程读回比较源/结果的顶点、面和拓扑特征。损伤时拒绝交付该工程，保留原始几何 3MF；这不是修复 Bambu 本身的序列化。

静态视图按需渲染，隐藏视图停止渲染；缩放/改变面板尺寸时绘制合并并限到 30 Hz，暂用 1× 像素比，稳定 150 ms 后恢复清晰度。
宽侧栏的表单和结果独立滚动，窄侧栏优先展示结果。动画按播放状态运行；隐藏交互网页时卸载 iframe，避免后台继续播放。
CadQuery 首次冷加载在本机实测约 237 秒，后续约 2.3 秒；不能把热启动耗时当首次使用时间。

## 验收与尚未覆盖的部分

证据见[历史验证记录](../history/VALIDATION_20260922.md)。本轮不是与任何特定第三方产品的全面能力对等声明。
人像的自动关键点、鼻部 donor 过渡缝合、身份保持的自动头模拟合，完整通用动作接地/自然度评估，以及 41 个具体产品工作流的逐一成品验收仍未完成。
通用 Blender 执行、模板表面拟合和发片生成分别提供底层入口，不冒充上述专用链已经通过。
云端真实账号验收需要可用 API 环境；人像固定拓扑链需要来源明确的目标模板及关键点契约。新增 `connect-parts`、`color-inlays`、`install-joint`、`motion-check` 后，五条原缺工具配方已有本地绑定；输入范围、调用参数和数字验收见[对外能力契约](PUBLIC_CAPABILITIES.md)。配方 ready 只表示工具契约可用，不等于自动运行全流程或任意模型/实物通过。`image-to-print` 仍是托管扩展，不属于本地承诺。
没有复用任何第三方产品的私有代码，没有部署外部服务、发布网站或向真实打印机发送任务。
