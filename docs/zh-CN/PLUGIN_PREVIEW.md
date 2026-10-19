[English](../PLUGIN_PREVIEW.md)

# Plugin 开发者预览版 · 0.9.0

本版更新现有 `print-prep` MCP plugin 与浏览器工作台，通过 Codex 或已配置的其他
MCP 宿主使用。不包含独立 Agent 聊天应用、app-server 运行时、Electron 或桌面安装包。

## 更新内容

- 新起始页、模型/成果直接选择、动画当前姿态的静态打印副本、热床参考，以及保尺寸的超床拆分。
- 持久化制造步骤：诊断、有限本地修复、拆件、连接结构、公差试片、装配采样复检、摆盘/切片、
  对比、交付和补件。每阶段记录源文件指纹、修订号和任务回执。
- 高面数网格壁厚采样及缺失证据处理。缺失、空样本、不完整测量不能判为通过；旧审查需重跑才能
  新建交付。采样不证明全局壁厚。
- 明确的单色部件颜色在编辑器打印副本中保留，并回读 Bambu 实际工程验证颜色与料槽映射。
  见[打印颜色](PRINT_COLOR_INTENT.md)。
- 发现 Bambu Studio、OrcaSlicer、ElegooSlicer、Snapmaker Orca、Creality Print 及其配置目录。
  配置存在不代表设备已验收。Creality 交付几何，需手动配置；其他导出依赖已安装的软件/版本。
  跨切片器交付须明确选择仅几何模式。
- 可选的源绑定分区适配器、Lux3D 上传/报价兼容修复、聊天与工程绑定校验、宿主兼容下载。
- 实验性板件设计/排版及本地 LightBurn 导入。只准备/导入文件，不移动或点火激光设备。

新增 `studio_list_slicers`、`studio_send_to_slicer`、`studio_manufacture`、`studio_laser`；
总计 30 个 MCP 工具，[工具参考](../TOOLS.md)由真实运行时 Schema 生成。

## 安装或更新

已有本地源码改动时，请使用独立 checkout 试用：

```bash
git clone https://github.com/Hockwang/agent-3d-workbench.git
cd agent-3d-workbench
uv sync --locked
STUDIO_LANG=zh-CN ./install.sh --add
```

更新后重新连接 plugin 或重启宿主，使 Python 后端加载新代码。兼容插件 ID 仍为 `print-prep`，
项目格式保持。`studio_open` 的 `manufacture` 模式进入制造准备，`print` 进入打印流程，
`home` 进入起始页。试用新制造操作前备份重要工程，明确使用源模型副本。

Blender 和切片器需按任务另行安装。仓库预构建资产已含动画姿态导出所需的 STL exporter，
plugin 用户无需重建前端；开发者使用 `npm ci`、`npm run build:app` 重建。

## 可选模型分区

在「API 配置」选择「模型分区」，填写自己的兼容服务地址。仓库不附服务器地址或凭据。
远端必须使用 HTTPS；HTTP 仅允许本机回环地址（`localhost`、`127.0.0.1`、`::1`）。
适配器向 `POST /segment` 提交单个模型，核验返回网格的有序三角几何和参数回显，
将面标签绑定到输入 SHA256。提交状态不明时不自动重发。本协议没有 API key 字段，
不要将未鉴权部署直接暴露到公网。

分区结果只是候选，不等于闭合打印实体或语义归属正确。消费源绑定标签前需要检查边界。
普通本地编辑与打印准备不依赖该服务。

## 限制和验证

远端自动修补尚未实现；本地修补仅覆盖有限网格缺陷。拔出和壁厚检查是采样；切片、颜色映射、
文件导入成功不代表实物配合、强度、已装耗材、设备就绪或打印成功。工具不提交打印任务。
LightBurn 配对信息保存在 `$PRINT_PREP_HOME/connections/lightburn.json`（默认 `~/.print-prep`），
不进入项目产物。

本预览在 macOS 验证；其他操作系统与切片器版本需独立验收，不是便携桌面发行版。
2026-10-19（macOS Apple Silicon）的验证结果：

| 检查 | 结果 |
| --- | --- |
| Python 全量 | 859 通过；2 项依赖仓外样本而跳过 |
| JavaScript | 198 通过 |
| Ruff / 工具参考生成一致性 / diff 空白检查 | 通过，保持现有 lint 规则 |
| 浏览器资产 | 四份 bundle 重建，补齐 STL exporter 与制造入口图标 |
| 真实 Bambu 颜色导出 | 分盘、同盘用例通过，未提交打印 |
| README stdio MCP 教程 | 五部件导入、变换、撤销、保存、导出、重开通过 |
| 新工具真实 stdio MCP | 30 个工具、版本 0.9.0；制造诊断及激光设计/板件/排版通过 |
| 浏览器检查 | 首页、五部件上传、七工作区、分区配置、语言切换通过；页面异常和失败 HTTP 请求均为 0 |
| 浏览器/MCP 绑定 | 同一工程、双向选区同步、错误工作区拒绝；几何保持 |

界面检查使用隔离状态和 headless Chromium。本轮未操作 LightBurn 配对/导入、实物设备或
在线生成服务。发布文件已扫描私人部署域名/IP、个人绝对路径、密钥模式及排除的独立应用模块。

以下检查无需生成服务账号：

```bash
uv run pytest -q
npm test
uvx ruff@0.14.3 check .
npm run build:app
uv run python scripts/gen_tool_reference.py --check
uv run python examples/demo/verify_tutorial.py
uv run pytest tests/test_print_colors.py -m bambu -v
```

最后一项依赖本机 Bambu，自动生成蓝/红徽章，核验分盘与同盘导出，不提交打印。
依赖仓外真实零件的测试在未设置 `PRINT_PREP_E2E_PARTS` 时跳过。
私人部署配置、本机运行日志与独立应用验收资料不进入 plugin 发布包；没有放宽 lint 规则。
