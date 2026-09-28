# 本地能力验收 — 2026-09-26

[English](../LOCAL_CAPABILITIES_VALIDATION_20260926.md)

四个本地制造任务已补上五条原先缺工具的配方。[对外能力契约](PUBLIC_CAPABILITIES.md)
明确输入范围。保持 26 个 MCP 工具，本地模板增至 33 个；18 条配方中 17 条绑定本地能力，
`image-to-print` 是可选托管扩展。工具绑定可用不代表整条产品流程已经验收。

## 运行证据

在已安装依赖的 macOS 上，使用独立工作区、空服务配置、不传凭据环境变量。
macOS `sandbox-exec` 禁止 MCP、后端和任务子进程访问外网，只放行 loopback。
真实任务中的外部 socket 连接返回 `EPERM`。未运行专用生成模型或托管 3D 服务。

最终 stdio MCP 验收共调用 114 次工具，覆盖任务启动、轮询、产物收集、四个新 URDF
零位检查、三个对象导入编辑器，以及两批 Blender 观察任务、六组生成场景。
独立重算 69 个返回产物的哈希，全部一致。

| 用例 | 实测结果 |
|---|---|
| 定位连接 | 两件盲孔加工件、独立 D 形销；STL 闭合，孔壁包络通过，每个主体检查 21 个拔出位置。 |
| 分色嵌件 | 闭合蓝色主体和红色嵌件；嵌件体积 480 mm³，33 档拔出采样。回归测试另覆盖真实 UV 贴图。 |
| 销铰 | 两个加工主体、M2 五金清单、绑定新 STL 的 URDF；声明范围内 5 个姿态通过。 |
| 回转 | 两主体加端帽，端帽跟随活动件；全圈示例在半圈位置两侧主体相撞。保留失败结果，明确改查 ±1.4 rad 后 17 个采样通过。 |
| 滑轨 | 两主体与 URDF；±10 mm 的 5 个姿态通过。无端挡，不宣称防脱。 |
| 球窝 | 两主体、可拆上盖、锥形杆口；三轴各 ±0.35 rad 的 125 个组合通过。摩擦保持与实物安装未验证。 |
| 混合姿态反例 | 9 个组合中 8 个无碰撞、1 个有碰撞；旧对角线扫描漏检此碰撞。任务完成而几何报告正确返回 `fail`。 |

上述运动结论只适用于这些程序几何样例和报告中的采样点，不代表任意模型或连续轨迹。
已检查真实 Blender 渲染中的几何外观；这不替代原生宿主界面验收。

## 回归与修正

全量 Python：687 passed、2 skipped；JavaScript：125 passed。
制造专项共 14 个测试，覆盖真实实体、薄壁拒绝、后孔破坏前孔壁厚、UV/颜色接缝连通、
调色板不匹配、四种关节、旋转/平移后的 URDF 坐标、组合碰撞反例与计算量上限。
最终配方相关回归 159 项通过。Ruff lint、11 个改动 Python 文件的格式检查、
MCP 工具参考同步检查通过。本轮没有改 UI 源码或生成 bundle。

实现中定位并修复：

- UV/颜色接缝重复顶点导致一个色块被错误拆开。
- 贴图转颜色返回未绑定 mesh 的顶点颜色，需按真实三角面索引求平均。
- 后加销孔可能破坏前一个销孔要求的较厚孔壁，增加最终包络复核。
- 回转端帽在 URDF 中须归活动件。
- 球杆直孔只允许自转、阻挡侧向摆动，改为锥形让位并覆盖完整样例网格。
- 一份 guide 超出已有字节上限，精简文字后通过，不放宽加载限制。

同步纠正配方的错误验收项：实体装配检查不能检测切片中的孔内支撑。安装路径步骤改接
`removal-audit`；支撑可清理性留给切片后单独复核。未测整体最薄壁厚时不宣称达标。

## 复现

```bash
uv run --frozen pytest -q
npm test
uvx ruff@0.14.3 check .
uv run --frozen python scripts/gen_tool_reference.py --check
uv run --frozen python scripts/verify_local_capabilities.py --out /tmp/local-fabrication-proof --deny-external-network
```

输出目录须为新目录。最后一个选项当前需要 macOS；其他系统可去掉该选项运行普通 MCP
验收，但不能据此声称禁外网。脚本自行生成输入，只停止自己启动的后端。
目录保留 `results.json`、`mcp-calls.json`、任务报告和渲染对照图。本轮未做其他平台验收。

## 本轮改动文件

| 文件 | 改动与原因 |
|---|---|
| `studio/core/fabrication.py` | 统一能力发现示例、输入/实体校验、哈希与产物重读。 |
| `studio/core/connect_parts.py` | 圆销/D 形销、盲孔、孔壁包络与拔出检查。 |
| `studio/core/color_inlays.py` | 明确调色板、UV 采样、实体嵌件与凹槽、拔出检查。 |
| `studio/core/install_joint.py` | 四族关节安装进真实主体，并导出绑定新网格的 URDF。 |
| `studio/core/motion_check.py` | 显式姿态与笛卡尔组合采样，保留真实失败结论。 |
| `studio/core/task_templates.py`、`studio/core/task_operations.py` | 注册任务，复用 URDF 实体相交引擎，兼容旧默认扫描。 |
| `tests/test_local_fabrication.py` | 几何与失败反例回归。 |
| `tests/test_recipes.py`、`tests/test_recipe_workbench.py` | 检查实际配方绑定。 |
| `scripts/verify_local_capabilities.py` | 可复现的真实 stdio MCP 验收，可选系统禁外网。 |
| `recipes/{color-split,cut-to-fit,mechanical-joints,poseable-figure,split-glue-kit}/{recipe.json,guide.md}`、`recipes/README.md` | 接通任务，补输入、验收与实物边界说明。 |
| `README.md`、`README.zh-CN.md` | 链接公开承诺。 |
| `docs/{PUBLIC_CAPABILITIES,WORKBENCH_TASKS,AGENT_PLAYBOOK,index,LOCAL_CAPABILITIES_VALIDATION_20260926}.md` 及 `docs/zh-CN/` 镜像 | 承诺清单、调用方法、当前计数与本验收记录。 |

## 剩余边界

没有宣称实物打印、保持力/防脱、连续碰撞、任意语义自动化、干净机器安装和原生 Codex
侧栏验收通过。本轮没有刷新安装缓存、替换现有工作台会话或发布版本；保留用户已有修改，
未 commit、push。
