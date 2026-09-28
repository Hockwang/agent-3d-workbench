> English: [../HUNYUAN_API.md](../HUNYUAN_API.md)

# Hunyuan 3D / Part

2026-09-23：再次用公司 OneAPI 完成真实生成 → Part → 编辑 → 导出 → 统一预览，并修复材质编辑丢失顶点法线的问题，见 [0.8.1 验证记录](../history/VALIDATION_20260923_ONEAPI_HUNYUAN.md)。该链路不代替 Lux3D 专属账户接口验收。

Codex 是已有的推理和工具调用入口。工作台只把专业任务发到 Hunyuan 3D / Part，不增加 GPT API、对话模型账号或另一套 viewer。本机 Blender/CAD 路线仍可独立使用。

## 接口与复用

适配 `hunyuan-responses` 协议：POST `/responses`，`background:true`，GET `/responses/{id}`；仅从 `3d_generation_call` 接收模型。
契约来自公司内部的批量拆件验证与接口参数文档，与作者研究仓库中已验证的 Hunyuan 模型一致。

这是公司兼容 Responses 的 3D 服务接口，**不是腾讯云 TC3 原生接口**。其他部署必须兼容此契约；不能只把 base_url 换成腾讯云域名。

复用已有 HTTP 鉴权/重定向限制、任务生命周期、ZIP 安全收件和共享 viewer。没有引入 aigccat 的 OpenCode、LLM 路由或渲染器；也没有复制其源码。

## 配置

在仓库外设置环境变量 `HUNYUAN_API_KEY`，让启动工作台的进程继承。也可在 `~/.config/codex-3d/services.json` 指向已有环境变量名：

```json
{
  "hunyuan": {
    "base_url": "<your-openai-compatible-gateway>/v1",
    "key_env": "HUNYUAN_API_KEY"
  }
}
```

配置只存引用，不存密钥。不要把 key 文件复制进仓库。这个适配器不带任何默认 `base_url`——它说的是一种协议（兼容 Responses 的 3D 生成接口），不是某一家具体服务；`base_url` 必须指向你自己有权访问的网关，不能把某份文档或示例里的地址、key 当作公共配置直接使用。

升级安装会清理旧插件缓存。若后台服务仍来自旧缓存，在确认无活动任务后从新版本重启；否则旧服务可能尝试从已删除目录启动 worker。升级验证应同时检查服务端、MCP 和前端版本，不能只刷新 UI。

## 人与 AI 共用的操作

在右侧「建模与任务」选择 **Hunyuan 3D / Part**。图片生成选择一张 PNG/JPG/WebP（≤4 MB）；文字生成填描述。准备继续分件时，输出格式选 FBX。

```json
{"action":"start","provider":"hunyuan","operation":"text-to-3d","params":{"prompt":"A simple wooden chair with four legs and a slatted backrest.","model":"hunyuan-3d-3.1-pro","output_format":"FBX","face_count":3000}}
```

图生操作用 `image-to-3d`，图片绝对路径放 `inputs`；也可使用 `params.image_url`，二选一。不会把当前 GLB 选区冒充图片。

生成任务完成后，在 Part 界面下拉选择该任务；AI 可直接引用任务 ID：

```json
{"action":"start","provider":"hunyuan","operation":"segment","params":{"source_task":"已完成生成任务的32位ID"}}
```

已有远端 FBX 用 `file_url` 替代 `source_task`，不要把本机文件路径当 URL。当前不自动上传本机 FBX。服务端下载链接过期后可能需要重新提供来源；不会为了续期自动重跑生成。

每次提交只发送一次 POST；拿到远端 ID 立即落盘。中断后 `resume` 按原 ID 查询、收件，不重新生成。停止等待不保证停止远端计费。未取得 ID 的模糊提交禁止自动重试。

多个 Part GLB 保留原文件，并按各自节点世界变换组合成 `combined.glb`，可在任务区旋转查看或导入编辑。密钥不进入任务文件或下载请求；签名链接仅放权限 0600 的任务私有缓存，不进入输出包。

## 验收边界

`completed` 表示任务执行和文件落盘成功，不代表拆件质量通过。Part 属于生成式拆件，可能改变原几何、纹理、尺度或部件数量；应通过观察、几何指标和原模型对照判断。公司套餐是否计费以服务账单为准，不能从旧实验的“$0”推断永久免费。

协议测试覆盖：真实本地 HTTP、一次提交、按 ID 继续收件、来源任务引用、图片请求、模型白名单、ZIP 包装、目录穿越拒绝、凭据和产物隔离。

## 2026-09-22 真实公司接口验收

三个任务均使用自有的 OpenAI 兼容网关的 `/v1/responses` 端点，各提交一次，凭据从本机仓库外已有配置引用。未调用 GPT API。耗时包含轮询和收件，不等于纯模型推理时间。

| 操作 | 模型 | 耗时 | 实际产物 |
| --- | --- | ---: | --- |
| 文生木椅 | hunyuan-3d-3.1-pro | 187.1 秒 | OBJ + GLB + FBX；3,000 面 |
| FBX 分件 | hunyuan-3d-1.5-part | 71.9 秒 | 5 个 GLB + combined.glb；1,340,205 面 |
| 参考图生成 | hunyuan-3d-rapid | 85.1 秒 | GLB；50,000 面 |

参考图是本次生成木椅经本机 Blender 渲染的图片。三个产物都重新读取几何，并通过工作台实际观察渲染。分件结果与生成原件做了正面、斜视、俯视的同尺度比较；外形和位置接近，但零件分组未必符合装配语义，检测到 27 条边界边，结论保留为 `needs_review`。特别注意 Part 面数从 3,000 增加至约 134 万，不能称为原网格保持拆件或可直接制造。

网关返回的 actual_amount 分别为 1.68、0、0.72；这里只记录回执数值，不推断账单币种或长期价格。

验证：`uv run --frozen pytest -q -m 'not bambu'`：372 passed、2 deselected；`node --test tests/*.mjs`：62 passed。App 构建成功；隔离浏览器实测三种表单、来源任务下拉、输入类型切换，无 pageerror。真实用例任务 ID、SHA 与截图保留在本机 `workbench-hunyuan-20260922` 证据目录，不把私有签名下载链接或密钥纳入 Git。
