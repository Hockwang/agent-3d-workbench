# v0.8.2 场景实例编辑验收

日期：2026-09-23。实现用户确认的 [第一阶段提案](SCENE_EDITING_PROPOSAL.md)：
在既有 Studio 视口选中完整人物/设施，编辑实例、检查动作，经本地 Blender 修缮或绑骨后
原位回填；复用工程与任务协作。使用方法见 [场景编辑](../SCENE_EDITING.md)。

## 改动与原因

| 文件 | 行为与原因 |
| --- | --- |
| `studio/scene_assets.py` | 将完整 GLB 与静态代理分开存储；导出局部编辑源，验证候选后按原 ID 和摆放回填。材质修改只分叉选中实例，保留原始蒙皮和动画 buffer。 |
| `studio/editor.py`、`editor_schema.py`、`collaboration.py` | 接入 scene_import/export/replace、完整工程归档和版本/范围/租约检查；拒绝会静默打平骨架的操作。 |
| `studio/motion.py`、`motion-cli.mjs`、`web/motion-engine.js` | 保留 skin，增加原生刚体节点动画；编辑源与场景摆放分开，动作导出复用既有采样引擎。 |
| `studio/web/editor-viewport.js`、`motion-player.js` | 编辑和动作模式共用真实 GLB 与 renderer；显示骨架，修正 raw GLB 的 gizmo 单位转换，替换后暂停并重启动作。 |
| `studio/web/scene-panel.js`、`motion-panel.js`、`editor.js`、`workspace.js` | 在现有模型浏览器/属性面板加入场景入口、完整资产导入、修缮/绑骨与原位回填；沿用全局 UI。 |
| `studio/app/selection-context.js`、`skills/print-prep/SKILL.md` | 将选中实例身份、源版本、变换、骨架/片段摘要交给当前 Codex；说明本地 Blender 工作与冲突处理契约。 |
| `tests/test_scene_assets.py`、`test_editor_loading.mjs`、`test_editor_pivot.mjs`、`test_selection_context.mjs` | 覆盖完整资产往返、单实例分叉、坏候选拒绝、并行任务保护、单位换算和上下文。 |

没有复制附件游戏代码，也没有将附件素材打进插件发行包。

## 自动化回归

- 发布仓完整 Python 回归：**456 passed / 2 skipped**，156.83 秒。
- 发布仓 Node 回归：**91 passed**，0 failed。
- 安装源合并后定向 Python 回归：**76 passed**，42.73 秒；Node：**92 passed**，0 failed。
- 发布仓和安装源 `npm run build:app` 均成功。安装源保留其他任务的增量，以三方合并处理重叠文件，没有整树覆盖。
- 新增场景测试覆盖：保留骨架和摆放、同源实例独立材质、截断/坏权重/循环层级/外部贴图拒绝、静态及节点动画归档往返、任务 scope/租约/过期版本与撤销、清除动作不丢源资产、普通网格局部导出回填不重复施加摆放。

## 真实资产与本地 Blender

只读取用户附件 ZIP 中指定资产，没有执行附件脚本或调用附件服务：

| 资产 | 实际载入 |
| --- | --- |
| `person_01_adult_man.glb` | 52 骨骼，1 个源片段 |
| `person_06_adult_woman.glb` | 46 骨骼，1 个源片段 |
| `treasure-chest.glb` | 无 skin，2 个节点动画片段 |

三件在同一 Studio 场景中载入。男性 GLB 经本地 Blender 修改并导出后，通过绑定该实例的子任务
执行 scene_replace；**实例 ID、摆放与其他对象不变**，新资产仍含 52 骨及源片段。

另以简单无骨架长椭球验证本地路线：导出局部编辑源 → Blender 创建两骨及权重 → 添加弯曲动作 →
原位回填 → 动画 GLB 导出。对 61 帧、每帧 1488 顶点比较源动作加场景摆放与导出动作，
最大误差 **5.2197e-8 m**，最大顶点位移 **0.56561 m**。

实际查看了 front/iso 两视角、0/0.5/1 三相位观察图。首次测试动作轴造成扭转，改为弯曲轴后
重新导出和核验；最终弯曲可见，中段仍有 LBS 压缩。这个简单样本证明本地工具到工作台的闭环，
**不证明任意人体或动物的自动绑骨自然度**。

## 界面、同步与资源读取

测试使用真实 Studio HTTP 后台与构建后的 MCP App 页面，宿主 RPC 桥在 Chromium 测试环境模拟。
发布仓 bundle 与实际安装缓存 `print-prep/0.8.2/studio/app/dist/studio.html` 分别跑通：

- 人物选区上下文带有 46 骨摘要，骨架辅助线可见，源动画播放。
- 「修缮 / 绑骨」将包含当前对象 ID 的任务发送到宿主接口。
- UI 修改材质只重新读取受影响资产；同场景其他资产不重读，最大并发读取为 1。
- 子任务修改同步到主视口：发布版约 **1219 ms**，安装版约 **1251 ms**（单次样本）。
- 编辑/动作切换新增模型读取 **0**；连续 12 个宽度变化新增模型读取 **0**。
- 两轮页面异常均为 **0**。

这验证了浏览器内的更新行为，没有测量原生 Codex 窗口合成或系统级拖窗延迟。
不能据此声称此前 Codex 拖动卡顿已全面解决。测试记录的 resizeMs 包含后续点击与截图，
不能用作纯 resize 延迟或 FPS 指标。

## 安装与现有数据

经正式 `codex plugin add print-prep@personal --json` 安装 **0.8.2**，实际安装 bundle 已通过上述界面验证。
仅在确认当前任务后台空闲后升级该后台；升级前后原工程保持 **34 个对象**，project.json SHA256 均为：

`864336b97ae74ee21236a01021c8228e92cb643f00595762fdbb399801723865`

测试场景使用独立目录，没有混入用户工程。官方 studio_open 已成功请求当前任务右侧工作台，
这个回执不替代原生 UI 的视觉验收。

## 边界与证据

完整城市运行时远控、NPC 行为、驾驶、碰撞/导航重建、流式加载和人物设施接触规划尚未实现。
内部任意场景树重挂父级、一键更新全部同源实例也不在本阶段范围。Morph、压缩 GLB 和超过四个
骨骼影响的蒙皮须先经 Blender 整理；完整资产结构通过不等于运动质量通过。

本机原始证据目录：`~/test/studio-scene-20260923`，不提交大模型及测试素材：

- `full-pytest.log`、`node-tests-final.log`、`installed-pytest.log`、`installed-node.log`
- `sources.json`、`replacement-check.json`、`bind-vertex-check.json`
- `bind-observation-bend/contact-sheet.png`：最终弯曲观察图
- `ui-check.json`、`installed-ui-check.json`、`scene-selected.png`、`scene-motion.png`、`scene-final.png`
- `install-receipt.json`、`fix-upgrades.json`、`install-backup/files.json`
- `job/workbench/exports/ff599982bd07.3dworkbench`：含两个真实人物、宝箱及本地两骨样本的示例工程

浏览器复现脚本为 `check-ui.mjs` / `check-installed-ui.mjs`，本地绑定脚本为 `local_bind.py`，
导出动作逐顶点核验脚本为 `check-bind.mjs`。资产 SHA 和具体输出路径以本机 JSON 收据为准。
