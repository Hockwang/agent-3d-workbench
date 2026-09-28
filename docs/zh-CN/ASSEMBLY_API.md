> English: [../ASSEMBLY_API.md](../ASSEMBLY_API.md)

# 可选 Assembly Workflow 服务与本机建模

工作台默认使用当前 Codex 中的 GPT 编写脚本，调用本机 Blender / CadQuery/OCP，交付模型、工程、图像及检查报告。它不要求购买生成 API，仍消耗用户当前 GPT 额度与本机算力。明确操作也可以直接点选模板、参数和选区。

Assembly 是可选的远端处理服务。本次依据公司内部的接口文档（API 链路、Web 关节动画、Web 骨骼动作）实现。它处理已有 GLB 或生成动作，不是文/图生几何接口。

| operation | 服务模板 | 收件 nodeName | 交付 |
|---|---|---|---|
| assemble | workflow_assembly_prod | assembly_agent_cos_upload | 可动装配资产包 |
| segment | workflow_assembly_seg_prod | AssemblyAgentSegmentedGLBExport | 拆件 GLB / 面标签 |
| rig-glb | workflow_rig_glb_prod | AssemblyAgentRiggedGLBOutput | 带骨架 GLB |
| rig | workflow_rig_prod | rig_package_zip | 骨架与动作资产包 |
| motion | workflow_motion_generate_prod | AssemblyAgentKimodoMotionGenerate | 动作 ZIP / BVH；不自动绑定模型 |

## 配置

默认未启用。配置文件在仓库外的 `~/.config/codex-3d/services.json`，或通过 `WORKBENCH_SERVICE_CONFIG` 指向另一个文件。仅填写部署地址和环境变量引用：

```json
{
  "assembly": {
    "enabled": true,
    "base_url": "https://api-beta.aholo3d.cn",
    "workflow_path": "/cubely/v1/workflow",
    "key_env": null,
    "headers_env": {}
  }
}
```

此示例不是完整鉴权配置。OpenAPI 的鉴权应按实际部署提供的规范配置，不能从 Web 登录方式推导。若部署要求 Authorization 请求头，可用 `"headers_env":{"Authorization":"ASSEMBLY_AUTHORIZATION"}`；对应环境变量是完整请求头值。若已明确使用 Bearer API key，也可配置 `key_env`，由适配器添加 `Bearer `。不要同时给同一个请求头配置两种来源。

Web 测试入口是 `https://beta.aholo3d.cn`，路径为 `/cubely/v1/api/workflow`，需要公司登录态；其凭据也必须通过已配置的环境变量引用提供。不能填写、猜测或冒用 `x-qh-id`，请求体不接受用户 ID。

可选 `oneapi_appkey_env` 引用后端装配推理使用的 OneAPI appkey（例如用户已配置的 `ONEAPI_API_KEY`）；发送时才注入 `oneapiAppKey`，不会进入任务参数或收据。该 appkey 不等同于 Assembly 接口登录凭据。`model` 可按部署权限覆盖装配主链模型；不代表覆盖全部分支。不要在 `params` 放明文 appkey。

环境变量需要进入实际插件后端进程，配置后重启/重新连接后端。UI 的“已配置”只代表启用且引用存在，不代表网络、鉴权、余额或服务质量已经验证。

### prod-test 内网路由（方案 0，2026-09-22 补充）

Claude 会话 `bfc7ec9a-9cf8-41b0-b2c8-0dde1058ed5e` 提供了不修改系统网络的入口。本轮独立复测：

- 连接 `<your-assembly-endpoint>`，仅该请求设置 `Host: api-beta.aholo3d.cn` 且不使用 HTTP 代理，`/cubely/v1/workflow/history` 返回 HTTP 200、`c=-1`、`appKey missing`。
- 同一入口不设置 Host 返回 HTTP 401。通过这个入口连接 HTTPS，即使保留原域名的 SNI，也收到 `Kubernetes Ingress Controller Fake Certificate`，不是有效的 api-beta 证书。
- `/assets` 在本次 prod-test 返回 HTTP 404；诊断使用已部署的 `/history` 和随机不存在的 promptId，不提交任务、不读取已有资产。
- 安装缓存首测曾收到一次 HTTP 502；随后源码、curl 和安装版复测均恢复为 `appKey missing`。入口可达不代表上游服务稳定，502 不会被识别为鉴权或生成通过。

“0 成本”在这里指不修改 `/etc/resolver`、代理、Shell 或 VPN 配置，**不代表免费生成或加密传输**。默认地址、TLS 校验及其他服务行为保留。无凭据复测：

```bash
uv run --frozen python scripts/diagnose_assembly.py --internal-prodtest
```

即使环境中已有凭据，默认也不会读取它们发送请求。输出分别标明网络、鉴权与生成状态；HTTP 200 不会被当成生成成功。该命令不写配置或更改工作区。

需要实际运行内网服务时，在仓库外的 `services.json` 对 Assembly 增加：

```json
{
  "assembly": {
    "enabled": true,
    "base_url": "https://api-beta.aholo3d.cn",
    "transport": "assembly-prodtest-http",
    "internal_origin": "http://<your-internal-ingress>",
    "allow_insecure_http": true,
    "key_env": null,
    "headers_env": {"Authorization": "ASSEMBLY_AUTHORIZATION"}
  }
}
```

`internal_origin` 是这条内网路由实际连接的地址（替换 `base_url` 但保留其 `Host` 头，见上一节）；它必须是不含凭据、路径、查询参数的纯 HTTP(S) 协议加主机，且只在 `transport: "assembly-prodtest-http"` 下生效——不填会在发请求前直接拒绝。`ASSEMBLY_AUTHORIZATION` 需要是该测试环境真实接受的网关凭据完整请求头值；上述引用名不代表凭据已存在或可用。`allow_insecure_http=true` 明确允许在内网以 HTTP 明文发送凭据与任务参数。缺少此设置时仅允许无凭据只读诊断，任务创建前即拒绝。该选项只适用于固定的 Assembly prod-test OpenAPI 域名、`internal_origin` 指向的内网目标及三个文档路径，不能给任意域名覆盖 Host、放开 HTTP，或影响下载请求。

已配置后可用 `--with-auth` 只读检查，成功也只表示 history 已到业务层，不代表生成、余额或质量通过。API 重定向仍拒绝，HTTP 入口不会在 HTTPS 失败后自动启用。

鉴权依据：Aholo OpenAPI 开发指南（指向独立网关和测试权限流程）与测试 OpenAPI 文档（说明测试账号、appkey/appsecret 和签名方式）。Aholo token 模式与公司旧签名模式不能仅凭 `appKey missing` 推断；当前适配器支持完整 Authorization 请求头，尚未实现旧 appkey/appsecret 动态签名。不要填入 OneAPI 推理 key，也不要模拟用户身份。本轮检查到服务配置文件及 Aholo 网关环境变量均未配置，未从历史 transcript 恢复旧 token。

## 调用和收件

读取 `studio_capabilities` 后，调用：

```json
{
  "action": "start",
  "provider": "assembly",
  "operation": "segment",
  "params": {
    "meshUrl": "https://your-storage.example/model.glb",
    "meshUpAxis": "y_up"
  }
}
```

输入必须是服务端可访问的链接，保留 GLB 实际向上轴。当前不会上传用户本机文件或选区；这类输入会明确拒绝。输入链接会保留在本机任务参数中。拆件可配置 `cutBackend:"cube"` 和 1–8 个 `cubeParts`；完整装配需要 `prompt`。高级参数支持文档规定的 `from` 已分割输入。动作需要 `prompt`，`inputUrl` 指 JSON，而非 GLB。

1. 创建只提交一次，立刻持久化 `promptId`。无法确定是否受理时不自动重提。
2. 首次等待 30 秒，随后每 10 秒查询，最多 70 次；按外层 `c` 解析状态，不读取不存在的 `d.status`。
3. `10001` 等待；`10002` 短重试，连续三次后保留 ID；`-1` 或未知状态结束本轮等待。网络/下载失败或超时后可通过 `resume` 按同一 ID 继续收件。
4. 停止等待只停止本机进程，不取消远端计算或收费。服务未给费用时记录 null，不能标成免费。
5. 下载 URL 不进入收据/运行日志；下载不携带 API 鉴权头。原 ZIP 保留，限制规模后解压几何与数据文件，拒绝越界路径、链接、冲突和加密条目，排除脚本/HTML。
6. `glbUrl` 也可能指向 ZIP，不能改后缀冒充 GLB。静态 GLB 可预览并接回编辑；骨架/动画 GLB 留在任务预览或 Blender。BVH 是动作数据，本次不实现自动匹配未知角色骨架。

## 验证与边界（2026-09-22）

- 新增 29 项 Assembly 测试，连同既有服务测试共 33 项通过。使用真实本机 HTTP + 独立任务子进程验证五种模板、状态轮询、失败恢复、单次提交、产物解包和凭据隔离。模拟服务不证明真实后端模型质量。
- 全量：339 项 Python 测试通过，2 项真实 Bambu 测试排除；62 项 Node 测试通过；`npm run build:app` 通过。
- 首轮 CF 指定的两个测试域名在本机 Python/curl 中均发生 TLS EOF；浏览器访问 Web 测试站报 `ERR_CONNECTION_CLOSED`。后续通过上述方案 0 收到了真实网关鉴权响应，修正了“没有可达入口”的判断。仍未提交真实计费任务，真实端到端尚未通过；未关闭 TLS 校验、未模拟身份、未改系统网络设置。
- 未把混合材质、URDF 渲染、SVInput 或 Lux3D 文/图生模型算作已集成；它们需要各自契约和真实验证。本次也未实现 API 套餐销售、充值或计费系统。

复现不依赖生成 API 的例子：

```bash
uv run --frozen python scripts/verify_local_first.py --out /absolute/new/directory
```

它运行一段 GPT 编写的 CadQuery 脚本，制作 80×40×50 mm、壁厚 4 mm、两处直径 6 mm 孔的 L 形支架；读回 STEP 验证体积，检查 STL 尺寸、水密性和孔洞拓扑，再经 Blender 渲染、保存工程与 GLB，最后导入隔离编辑工程。不会调用生成服务或更改当前用户工程。本机实测 CAD 4.33 秒、Blender 渲染与交付 1.79 秒，接回编辑成功；不包含 GPT 思考及工具往返时间。
