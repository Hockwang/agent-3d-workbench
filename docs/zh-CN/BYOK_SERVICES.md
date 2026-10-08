> English: [../BYOK_SERVICES.md](../BYOK_SERVICES.md)

# 专业 3D API 自助接入

工作台里的 Codex 负责规划、调用工具和验收；本机 Blender/CAD 继续承担可直接完成的建模和编辑。用户可以自备专业 3D API，用于生成、分件、纹理或绑骨，不增加 GPT 等通用模型的 API 配置。

## 使用

建议先看 [真实 API 生成演示](../API_GENERATION_DEMO.zh-CN.md)。
Hi3D 使用 AK/SK 双凭据，配置见 [Hi3D 接入](../HI3D.zh-CN.md)；下述单 key 设置框不支持直接填写双凭据。

1. 打开「工作台顶部 → API 配置」。
2. 选择内置连接或添加一个同协议的新连接，填写名称、API 地址和 API key；高级设置也可引用已注入后端环境的变量名。
3. 保存，再点「测试连接」。测试读取模型清单或余额，不生成模型；Hi3D 会先用 AK/SK 换取令牌。连接成功不代表已验收生成质量。
4. 回到「执行方式」选择该连接、选择任务并提供输入。后台收件后的模型复用当前 viewer，可导入工程继续编辑或送入观察评测。

多个连接可对应同一供应商的不同账户或兼容网关。保存不重置工程和视口。空密钥保留旧凭据；更换地址自动清除继承的凭据，需要重新填写。停用/删除只影响新任务，旧任务保留提交时的配置用于继续收件。

| 模板 | 当前协议与能力 | 只读测试 |
| --- | --- | --- |
| Hunyuan 3D / Part | Responses 兼容网关；文字/图片生成、FBX 分件 | GET /models，过滤已适配模型 |
| Seed3D | OpenAI 兼容网关 chat/completions；固定 doubao-seed3d-2.0 图片生成 | GET /models，检查 Seed3D |
| Meshy | 官方 Bearer API；沿用已有生成、纹理、减面、绑骨、动画适配 | GET /openapi/v1/balance |
| Tripo | 官方 V2 OpenAPI Bearer API；沿用已有适配 | GET /user/balance |
| Hi3D（环境变量配置） | 官方 AK/SK API；单图几何或带纹理 GLB | POST auth/token 后 GET balance，不生成模型 |

Hunyuan 的腾讯云 SecretId / SecretKey（TC3 签名）不是 Responses 网关协议；Seed3D 的直连火山接口也不能仅换 base URL 就当作兼容。Assembly 自定义鉴权仍通过 `services.json` 配置。没有供应商真凭据的适配器不能标成已做真实服务验收。

`studio_task` 的 `inputs`（本机文件）能不能挂到某个 provider 上、任务超时多久才算超时，都由该 provider 自己声明（`services.json` 里的 `local_inputs_allowed`/`default_timeout_seconds`，见[配置](CONFIGURATION.md)），不是写死在某个适配器名字上。Assembly 出厂就关闭本机输入——它只接受服务端可访问的远程 URL；Assembly、Hunyuan、Seed3D、Lux3D 出厂的默认超时都比 Meshy/Tripo 更长，因为它们的托管任务通常跑得更久。Lux3D 还有自己的 `allow_unquoted`，可以退出生成前必须报价的要求——见 [Lux3D](LUX3D.md)。

## 密钥和恢复

- 旧 `~/.config/codex-3d/services.json` 继续有效。界面连接存在同目录 `connections.private.json`，原子写入、权限 0600，包含私有凭据；这是本机文件权限保护，**不是系统钥匙串加密**。`WORKBENCH_SERVICE_CONFIG` 指定配置文件时，私有存储也位于其旁边。不要把配置目录设在 Git 仓内。
- 明文 key 只在本机设置页面和后端使用。页面用 WebCrypto AES-GCM 加密，并用后端临时 RSA-OAEP 公钥封装 AES key；MCP 工具参数中只有密文。密文绑定服务地址，后端重启后旧加密信封失效。服务端返回值、任务参数和工程中仅存凭据引用。
- API 请求禁止自动重定向，CDN 下载不携带服务 key。换地址不能继承旧凭据；旧引用只为已创建任务续收保留。要撤销供应商密钥，应在供应商侧撤销。
- Hunyuan 按持久化 response ID 继续 GET，不再次 POST。Seed3D 的同步提交没有已适配的查询接口：只提交一次；收到产物地址后私有缓存，再按缓存恢复下载。提交超时或响应无法解析时，先核对上游记录，禁止自动重复生成。
- `studio_services` 的 list/save/delete/probe 与 UI 走同一本机接口；写配置有版本校验和进程间文件锁。密钥不能通过普通 params 或明文配置字段提交。

## 为什么不搭建 sub2api 平台

[aigccat 的服务管理实现](https://github.com/RainNameless/aigccat/blob/94bdaa3d9af4345d0eb88da9a2f35434997d249a/web/src/services.rs) 提供了多连接、启停与配置状态的参考。本插件借鉴这部分交互思路，复用现有任务执行、收件、viewer 和标准密码库，没有复制其供应商/订阅代码。

当前用户需求是自带专业 API，直接供 Codex 调用；不需要额外的通用模型代理、订阅会话转换、自动账号轮换或集中计费服务器。后续销售自有 3D API 套餐可以作为一个标准专业服务连接接入，再独立建设服务端鉴权、限额和计费。

## 验证

自动测试覆盖加密信封跨 JS/Python 解密、长密钥、篡改/过期/改地址拒绝、权限、无明文返回、旧任务凭据绑定、启停/删除、并发版本冲突、只读鉴权与重定向拒绝。Seed3D 测试使用真实本机 HTTP 服务，验证 ZIP 收件、继续下载不重提、模糊提交不重试以及 API key 不流入产物/CDN。

浏览器测试覆盖新增、保存、测试、切换、改地址、删除和不同宽度；不等于已经测过原生 Codex 拖窗性能。真实供应商测试记录在本轮验证报告中。
