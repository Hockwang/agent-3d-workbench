[English](HI3D.md) · [API 演示](API_GENERATION_DEMO.zh-CN.md)

# 可选 Hi3D API

本地建模、编辑仍然不需要生成服务。此适配器增加可选、付费的 **单图 → GLB** 能力，
使用 Hi3D 公开 API，不附带生成模型或账号。Hi3D API 额度与通用 Agent 宿主的订阅分开。

## 在本机配置

给启动 MCP 服务的进程注入 `HI3D_ACCESS_KEY` 和 `HI3D_SECRET_KEY`。
可以使用宿主的环境变量／密钥配置，或由私有启动脚本加载仓库外的环境文件。
不要把实际值写进聊天、任务参数、README 或提交的 MCP 配置。

内置地址是 `https://api.hitem3d.ai`。使用上述变量名时，不必另建配置文件。
高级配置可写在私有 `~/.config/codex-3d/services.json` 中，里面只放**变量名**：

```json
{
  "hi3d": {
    "key_env": "HI3D_ACCESS_KEY",
    "secret_key_env": "HI3D_SECRET_KEY"
  }
}
```

活动任务结束后，重启 MCP 服务及它此前启动的工作台后端。
当前连接设置框只支持单个 key，不支持直接填写 AK/SK 双凭据；请使用上述环境变量，
不要把两者拼进普通 API key 输入框。配置后可在 **「建模与任务」** 中选择 Hi3D。

## 人与 Agent 共用的流程

1. 调用 `studio_capabilities`，确认 `hi3d.configured` 为 true。
2. `studio_services` 传 `{"action":"probe","id":"hi3d"}`，执行令牌鉴权和余额查询，
   不生成模型。`positive_balance:false` 时先补充 API 额度；余额大于零也不等于已获得报价。
3. 在 **「建模与任务」** 中选择 Hi3D、**「图片生成 3D」**，提供一张不超过 20 MB 的
   PNG/JPEG/WebP。也可以让 Agent 调用 `studio_task`：

```json
{
  "action": "start",
  "workspace_id": "CURRENT_WORKSPACE_ID",
  "provider": "hi3d",
  "operation": "image-to-3d",
  "inputs": ["/absolute/reference.png"],
  "params": {
    "model": "hitem3dv2.1",
    "resolution": "1536fast",
    "request_type": 3,
    "face": 100000,
    "format": 2,
    "pbr": 1,
    "rmbg": 1,
    "shading": 0.5
  }
}
```

4. 保存返回的本地任务 ID，用 `studio_tasks` 查询，不能重复 `start`。
   完成后从 **「最近成果 → 查看结果」** 打开模型，点击 **「接回编辑」**。
5. 检查外形、拓扑、材质和尺寸后再修改。生成网格不保证已按语义分件，也不保证真实尺寸。

本版开放几何生成（`request_type:1`）、几何加纹理（`3`），仅输出 GLB（`format:2`），
请求面数范围为 100,000–2,000,000。支持的模型与分辨率如下；这是 API 参数支持范围，
不是所有组合都经过真实账户生成验证的声明。

| 模型 | 分辨率 |
| --- | --- |
| `hitem3dv1.5` | `512`、`1024`、`1536`、`1536pro` |
| `hitem3dv2.0` | `1536`、`1536pro` |
| `hitem3dv2.1` | `1536fast`、`1536pro` |
| `hi3dv3.0` | `2048quality`、`2048master` |

v1.5 请求会省略 PBR／去光照参数。当前适配器尚未开放多视图、重贴图、浮雕、分件或多色接口。

## 恢复与验证边界

生成 POST 只尝试一次，拿到远端任务 ID 后先落盘再轮询。
`studio_task` 的 `action:"resume"` 会重新鉴权，继续查询同一个远端任务，必要时重新下载；
拿不到 ID 的模糊提交不能自动重发。取消只停止本地等待，不代表取消远端计费。
已拿到 ID 时，令牌过期也可用 `resume` 恢复。

AK/SK 和临时令牌不进入任务文件，CDN 下载不带服务密钥。
`service.json` 记录参数、输入哈希、时间和任务身份，不含令牌或签名下载链接。
查询接口未提供单任务费用，所以 `cost` 为 null，不通过余额差额推断收费。

2026-09-28 的真实验证完成了鉴权和余额查询，但测试账户无可用 API 额度，
**没有宣称 Hi3D 已完成真实生成**。本地 HTTP 集成测试覆盖 multipart 上传、GLB 收件、
MCP 导入编辑导出、错误处理和不重提恢复。
公开的 [真实生成演示](API_GENERATION_DEMO.zh-CN.md) 改用已授权 Responses 兼容网关中的 Hunyuan。

公开协议来源：[鉴权](https://docs.hi3d.ai/en/api/api-reference/list/get-token)、
[提交](https://docs.hi3d.ai/en/api/api-reference/list/create-task)、
[查询](https://docs.hi3d.ai/en/api/api-reference/list/query-task)、
[余额](https://docs.hi3d.ai/zh/api/api-reference/list/query-balance)。
适配器根据公开 API 独立编写，不包含 Hi3D 桌面端源码。
