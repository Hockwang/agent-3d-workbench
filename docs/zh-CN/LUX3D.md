> English: [../LUX3D.md](../LUX3D.md)

# Lux3D 接入与 Aholo 能力对照

依据 [Aholo-Lux3D](https://github.com/manycore-research/Aholo-Lux3D) commit `71779ccd8290e999d980621439c728524830f422` 的公开接口契约独立实现，版本基线为 2026-09-23。没有复制其 skill、客户端或业务实现。

## 配置与操作

在「建模与任务 → 管理 3D 服务」选择 Lux3D 国内/国际模板，可加密填写 key，或绑定环境变量。默认国内 `LUX3D_CN_API_KEY`，国际 `LUX3D_GLOBAL_API_KEY`；也可绑定已有 `AHOLO_KEY` 等变量名。MCP 保存只接受变量名，不接受密钥值。无需配置 GPT API。

| 区域 | API 根地址 | 鉴权 |
| --- | --- | --- |
| 国内 | `https://api.aholo3d.cn` | `Authorization: <raw key>` |
| 国际 | `https://api.aholo3d.com/global` | 同上，账户/key 不通用 |

AI 先 `studio_services(action="list")` 找实际连接 ID，然后 `balance`、`quote`。单项报价传 operation、params、inputs；多项报价传 items 数组（1–50 项）。生成用 `studio_task(action="start", provider=连接ID, operation=..., params={...原参数, quote_id, quote_item}, inputs=[...])`。单项 quote_item 默认 `"1"`，计划中的项使用返回的序号字符串。

UI 提供余额、报价、开始任务、远端记录和按任务 ID 恢复收件。开始前显示报价；参数/输入/账户变化或报价过期会拒绝复用。报价是账户优惠前预计积分，不是最终扣费。用户已授权的生成目标可按其额度执行，报价本身不代替授权；取消本地等待不代表远端退款。

报价要求在服务端强制，不只是 UI 一层：适配器的 `prepare_payload` 会拒绝既无 `quote_id` 又无 `remote_task_id`（恢复已提交的远端任务不会二次扣费）的付费操作，绕过 UI 直接调 `studio_task` 也无法跳过报价。`services.json` 条目可用声明式 `allow_unquoted: true` 选择退出；内置的 `lux3d`/`lux3d-global` 模板从不设置它，默认强制报价。

## 能力对照

| Aholo 的能力 | Studio 入口 | 验证与边界 |
| --- | --- | --- |
| 国内/国际 key、余额、会员与试用信息 | `studio_services` / 服务面板 | 契约与模拟服务；真实账户待验 |
| 单项与整计划报价 | `quote` 单项或 items | 请求、账户、文件 SHA、有效期绑定；不伪造未知价格 |
| 单图、多图生成 | image-to-3d、multi-image-to-3d | G1/G1-Turbo；本机上传或 img/imgs；最多 32 图 |
| 文生 3D、风格、面数、尺寸参数 | text-to-3d | 按版本校验；G1 与 Turbo 参数不能混用 |
| 材质重绘 | material-transfer | GLB + 参考图；版本 v3.0-standard |
| 四视图、参考图辅助 | four-view、multimodal-image | 固定四图顺序/数量；后者是上游内部辅助端点 |
| 多格式转换 | multi-format-export | GLB 或 Lux3D 原始 ZIP → USDZ/OBJ ZIP/FBX ZIP/STL/3MF |
| 素材上传 | 自动使用区域 Asset API | 单文件/分片；存储端只带短期 OUS token，不发送账户 key |
| 查询、任务历史、恢复收件 | remote_task、remote_tasks、task resume | ID 按字符串传递；历史支持分页、状态和毫秒时间范围 |
| 失败恢复与防重复提交 | 任务 receipt | POST 只尝试一次；响应未知时保留记录，不盲重提；下载失败可续收 |
| GLB 检视、压缩资源、动画 | 工作台预览与离线网页 | 共用 Three.js loader；实测 Draco、Meshopt、KTX2，零外部请求 |
| 生成后编辑、布置、材质与参数化处理 | `studio_edit`、本机 Blender/CAD、`studio_motion` | 复用既有工具；原始产物保留，编辑生成新资产/版本 |
| 场景拼装、动作、渲染与流程编排 | 当前 Codex + `studio_task` | 使用已安装本机工具；不需要再配通用模型 API |
| 离线模型交付、模型切换、动作播放 | viewer-page / interactive-scene | 自包含 HTML；多模型可切换，WASD 与热点；复用既有任务模板 |
| 交互体验/游戏目标 | 当前 GPT 编写本地脚本与网页 | 通用脚本能力可用；不宣称覆盖所有玩法或已逐场景达到质量对等 |

正常 Lux3D GLB 收件后可「接回编辑」，再改材质、变换、切割、保存。压缩 GLB 的**预览/离线交付**已补齐；静态编辑与绑骨仍受 Trimesh/Blender 导入能力约束，KTX2 等复杂源应先转换为可编辑、自包含 GLB，不能把预览成功说成编辑无损。

PLY 是完整保存的输出文件，当前没有 Gaussian splat 渲染器；上游 Aholo viewer 同样以 GLB 展示为主。ZIP 按原文件保存与完整性校验，不猜测压缩包内部文件名。格式转换不是网格修复或打印有效性保证。

## 恢复

- 已有本地任务：`studio_task(action="resume", id=...)`，继续轮询/下载原 task ID。
- 只有远端 ID：保持原 operation/version/outputFormat，传 `params.remote_task_id="..."` 开始收件；不会创建新远端生成。UI 的「恢复收件」走此路线。
- 提交超时且没有可靠 ID：先 remote_tasks 对账，找到任务再恢复。不能因为本地失败就再提交收费生成。
- 成功产物附 `service.json`，记录提供方、区域、task ID、SHA256；仍需要真实观察图进行外观验收。签名结果 URL 不进入交付清单。

## 验证状态

本轮使用本地 HTTP fixture 验证请求/响应契约、上传、报价、收件、身份检查、恢复、错误与 key 隔离；浏览器用真实 Studio 后台跑报价到导入编辑全链路。压缩模型用 Khronos Draco Box、Three.js KTX2 样本与生成的 Meshopt 三角形验证，并检查离线画布实际有图像。

本机已查阅的公司/个人环境配置和 Studio 连接中未发现 Lux3D 专用凭据，因此**尚未完成国内或国际站真实账户的余额、扣费与模型生成验收，不能宣称已达到全部能力和质量对等**。接入后应跑至少一件实际图生/文生模型，保留 task ID、报价、原产物、编辑后产物和观察报告。

### 未关闭缺口：LUX3D-LIVE-001

- 状态：缺少 Lux3D 专用 key，等待可用的国内或国际站账户配置。2026-09-23 用户要求记录此缺口，并用公司 OneAPI Hunyuan 进行替代链路测试。
- 可替代验证：专业 3D 服务提交、轮询、收件、统一预览、接回编辑、导出，以及 Hunyuan Part 分件。
- 不能替代验证：Lux3D 区域鉴权、余额与计划报价、素材上传、实际扣费、七类操作的服务端兼容性。Hunyuan 成功不关闭本缺口。
- 关闭条件：合法区域 key 配置完成，至少一件 Lux3D 真实生成走完报价到收件、观察和编辑；其余操作逐项记录真实成功或明确限制，不从一个样例推断全能力对等。

公司 OneAPI 替代链路已实测通过，详见 [Hunyuan 真实验证与法线修复](../history/VALIDATION_20260923_ONEAPI_HUNYUAN.md)；本缺口仍未关闭。

测试入口 `tests/test_lux3d.py`、`tests/test_projects.py`，运行 `uv run pytest -q` 与 `node --test tests/*.mjs`；前端 `npm run build:app`。
