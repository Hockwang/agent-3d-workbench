# 万物连接件 · Link Everything

在已有 3D 模型上设计双方对应的连接结构，帮助设计者决定部件如何装配，并继续修改、检查和交付。

本分支把连接设计研究原型接入当前 Agent 3D Workbench 的 **HTTP 浏览器工作台**。复用本仓的视口与模型导入接口，连接几何在独立 Python 环境执行；没有复制另一份旧工作台。

## 两条工作流

| 入口 | 任务与交互 |
| --- | --- |
| AI 参数化方案 | 确认当前 A/B → 描述固定、卡合、转动或平移需求 → 点选连接区域 → 查看结构与尺寸候选 → 选择并修改 → 配对生成、检查和预览 |
| 手动分件与配对连接 | 上传 GLB/STL → 移动/旋转切面 → 将切块指定为主体、独立件或丢弃 → 封闭断面 → 自选位置与连接件 → 双方同步生成 |

可以先手动分件，再用当前 A/B 进行 AI 设计。AI 从冻结 A/B 重建并替换当前连接件集合，保留旧修订；当前不支持任意多机构混合编排。

产品重点是连接方案的选择、持续修改与验证：例如相机壳体与盖子如何拆装，盒盖应该固定还是转动，以及尺寸变化后双方结构如何保持对应。完整方案比较、保护区域、参数依赖与实物反馈管理仍是后续目标。

## 当前能力

- 整件上传上限 50 MiB；平面、波浪和碗形切面预设，坐标轴平移/旋转，切面 Ctrl+Z / Ctrl+Y。
- 切块归组与封口，输出一对 A/B；每件可包含多个独立闭合壳体，归组不保证熔接。
- 自由放置 Plug、Dowel、Snap 和局部 Dovetail；共同坐标下生成公件/母槽，销钉另存，尺寸按模型与局部可用空间推荐。
- AI 使用可配置的 Responses 服务与 `gpt-6-sol`，输入需求和几何摘要，返回有限结构/参数候选，由确定性内核生成。
- 可执行 AI 类型为 plug、dowel、cantilever、dovetail、hinge、linear_rail。铰链和有限行程导轨只适用于当前支持的单壳、共面且空间足够的 A/B 子集。
- 闭合、正体积、静态交叠及适用的离散路径检查；生成 STL/GLB、参数、报告和不可覆盖修订。
- 预览可播放、拖动和复位。检查通过的机构使用实际轴线与范围；其他结果标注为 `visualization_only` 结构分开展示。
- 工作台的“导回模型编辑”读取已保存的 `assembly.glb`，通过原生导入接口成为当前项目中的新资产。

手动 Snap 是开槽卡扣柱，AI cantilever 是悬臂梁/倒扣窗。独立教学页面另有悬臂、U 形、扭转和环形卡扣试件；后三类尚不能自动安装到任意 A/B。几何动画不模拟弹性或证明连续无干涉。

## 安装与运行

Windows PowerShell，在仓库根目录执行：

```powershell
# 当前工作台的锁定依赖
uv sync --locked --python 3.12

# 连接几何需要另一套 Trimesh/Manifold 版本
uv venv --python 3.12 experiments/link-everything/.venv
uv pip install --python experiments/link-everything/.venv/Scripts/python.exe -r experiments/link-everything/backend/requirements.txt

./experiments/link-everything/Start-Demo.ps1
```

打开 [工作台装配入口](http://127.0.0.1:8767/?mode=assembly) 或 [独立连接页面](http://127.0.0.1:8766/manual.html)。默认样件不需要私人模型或 AI 密钥。

如默认端口已占用，启动脚本不会终止占用进程；使用其他端口：

```powershell
./experiments/link-everything/Start-Demo.ps1 -BackendPort 18766 -WorkbenchPort 18767
```

对应入口为 `http://127.0.0.1:18767/?mode=assembly&assemblyBackendPort=18766`。启动器打印实际入口，并把工作台状态隔离在实验的 `outputs/` 内。

macOS/Linux 可分别运行两个终端；后端用独立环境的 Python，工作台用仓库根环境：

```bash
uv sync --locked --python 3.12
uv venv --python 3.12 experiments/link-everything/.venv
uv pip install --python experiments/link-everything/.venv/bin/python -r experiments/link-everything/backend/requirements.txt
experiments/link-everything/.venv/bin/python experiments/link-everything/backend/server.py --port 8766
# 另一个终端
.venv/bin/python experiments/link-everything/integration/serve_workbench.py --port 8767
```

本次验证使用 Windows；其他平台的上述启动方式尚未实跑。

## AI 与本地配置

AI 提案需要在启动后端的环境中配置：

| 变量 | 内容 |
| --- | --- |
| `CONNECTION_DESIGN_ONEAPI_BASE_URL` | 自己的 Responses 兼容服务基础地址，包含 API 前缀；例如 `https://provider.example/v1` |
| `CONNECTION_DESIGN_ONEAPI_KEY` | 自己的服务密钥，仅保存在本机环境中 |
| `CONNECTION_DEMO_BLENDER` | 可选 Blender 可执行文件，供非水密模型生成近似代理体 |
| `CONNECTION_DEMO_BADCASE_DIR` | 可选本地 GLB 回归目录，不随仓库发布 |

未配置服务地址或密钥时，AI 提案明确报未配置，手动连接与教学试件仍可使用。健康接口的 `llm: true` 仅表示配置存在，真实调用以提案记录为准。本仓没有预置密钥或私有服务地址，也不自动读取 `.env` 文件。

调用会向所配置的服务发送需求与几何摘要；当前不发送模型截图或网格文件。生成物、原始上传文件、绝对路径记录和模型调用记录仅在本机 `outputs/` 中保存。

## 能力边界

有效开放 GLB 可保留原件查看，并尝试另存近似水密代理体；无效、异常或超限文件仍可能拒绝，代理生成也可能失败。代理体可能改变薄壁、开口、空隙与细节，只能证明对应近似几何的切割流程。

计算/STL 为 mm/Z-up，生成 GLB 为 m/Y-up。布尔输出尚不保留原材质与 UV。当前没有材料强度、疲劳寿命、真实打印公差、切片或完整实物试装验收。

HTTP 装配入口与本地后端集成已实现。Codex **MCP App** 的现有 CSP 不允许该 localhost iframe，本分支会隐藏这一入口并保留原有 MCP 编辑功能；没有宣称完成 MCP 原生连接设计工具。

## 检查与继续开发

```powershell
# 当前工作台的 HTTP 交接边界
.venv/Scripts/python.exe -m pytest tests/test_link_everything.py -q
# 独立连接几何回归
cd experiments/link-everything
.venv/Scripts/python.exe -m unittest discover -s tests -p 'test_*.py' -q
.venv/Scripts/python.exe verify_snapshot.py
```

新增前端测试在根目录 `tests/test_assembly_panel.mjs`、`tests/test_assembly_workspace.mjs`；本次接入记录见 [validation.md](validation.md)。

`backend/` 放几何与 AI 提案，`frontend/` 放独立工具和教学页面，`tests/` 放连接回归，`integration/` 启动本仓 HTTP 工作台。新增工作台面板位于根目录 `studio/web/assembly-panel.js`，文件交接适配位于 `studio/adapters/link_everything.py`。

只发布源码、公开静态依赖与合成测试；`outputs/`、`.venv/`、密钥文件、本机运行状态和用户模型均排除。修改本模块后运行 `scripts/build_snapshot_manifest.py` 刷新源码清单，再执行 `verify_snapshot.py`。
