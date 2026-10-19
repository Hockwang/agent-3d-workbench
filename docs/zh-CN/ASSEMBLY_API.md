> English: [../ASSEMBLY_API.md](../ASSEMBLY_API.md)

# 可选 Assembly Workflow 服务与本机建模

工作台默认使用当前 Codex 中的 GPT 编写脚本，调用本机 Blender / CadQuery/OCP，交付模型、工程、图像及检查报告。它不要求购买生成 API，仍消耗用户当前 GPT 额度与本机算力。明确操作也可以直接点选模板、参数和选区。

Assembly 是可选的远端处理服务。适配器实现可配置的装配、绑定和动作工作流协议。它处理已有 GLB 或生成动作，不是文/图生几何接口。

| operation | 服务模板 | 交付 |
|---|---|---|
| assemble | workflow_assembly_prod | 可动装配资产包 |
| segment | workflow_assembly_seg_prod | 拆件 GLB / 面标签 |
| rig-glb | workflow_rig_glb_prod | 带骨架 GLB |
| rig | workflow_rig_prod | 骨架与动作资产包 |
| motion | workflow_motion_generate_prod | 动作 ZIP / BVH；不自动绑定模型 |

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


可选 `oneapi_appkey_env` 引用后端装配推理使用的 OneAPI appkey（例如用户已配置的 `ONEAPI_API_KEY`）；发送时才注入 `oneapiAppKey`，不会进入任务参数或收据。该 appkey 不等同于 Assembly 接口登录凭据。`model` 可按部署权限覆盖装配主链模型；不代表覆盖全部分支。不要在 `params` 放明文 appkey。

环境变量需要进入实际插件后端进程，配置后重启/重新连接后端。UI 的“已配置”只代表启用且引用存在，不代表网络、鉴权、余额或服务质量已经验证。

### 连接诊断

使用服务运营方提供的地址和鉴权方式。运行
`uv run python scripts/diagnose_assembly.py` 可对已配置服务做只读诊断；
默认不发送凭据、不提交任务，`--with-auth` 才显式使用已配置的凭据引用。
网络可达、鉴权和生成分别报告；连接成功不代表计费、服务质量或真实生成已通过。

本预览版不分发私人部署地址、会话标识或内部网络诊断记录。
旧传输配置必须显式指定目标，不会在 HTTPS 失败后自动启用。

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
- 未把混合材质、URDF 渲染、SVInput 或 Lux3D 文/图生模型算作已集成；它们需要各自契约和真实验证。本次也未实现 API 套餐销售、充值或计费系统。

复现不依赖生成 API 的例子：

```bash
uv run --frozen python scripts/verify_local_first.py --out /absolute/new/directory
```

它运行一段 GPT 编写的 CadQuery 脚本，制作 80×40×50 mm、壁厚 4 mm、两处直径 6 mm 孔的 L 形支架；读回 STEP 验证体积，检查 STL 尺寸、水密性和孔洞拓扑，再经 Blender 渲染、保存工程与 GLB，最后导入隔离编辑工程。不会调用生成服务或更改当前用户工程。本机实测 CAD 4.33 秒、Blender 渲染与交付 1.79 秒，接回编辑成功；不包含 GPT 思考及工具往返时间。
