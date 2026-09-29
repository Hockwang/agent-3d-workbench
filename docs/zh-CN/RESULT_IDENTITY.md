[English](../RESULT_IDENTITY.md)

# 让交付的模型能被找到

「建模与任务」页的 **最新交付**显示当前项目最近完成的作品，同一作品的本地、生成、分件等版本并排展示。
**任务总览**按作品收纳历史，同一路线的旧版折叠。顶部显示正在预览的文件、路线、版本和完成时间。
查看成果会保留编辑场景；只有明确点击**加入编辑场景**才追加对象。

**任务总览**在各工作区均可打开。编辑页围绕当前场景和对象列表展示，最新成果卡片保留在任务页，
项目任务流程默认折叠。该层级不代表导入场景来自某个任务；来源关系必须有真实成果元数据依据。

## Agent 的交付步骤

不要只给磁盘链接，也不要把成果留在临时验收工作区。通过绑定用户当前项目的任务交付。
如果模型来自独立实验，只登记明确选定的模型与缩略图，使用普通 Python 任务即可：

```json
{
  "action": "start",
  "engine": "python",
  "script": "from studio.core.result_manifest import register_existing\nregister_existing(workbench)",
  "inputs": ["/absolute/path/cup.glb", "/absolute/path/render.png"],
  "params": {
    "work_id": "cup-demo",
    "work_title": "杯子",
    "variant": "本地 · 四部件",
    "version": "v1",
    "note": "尺寸为设计假设，未验证实物用途。"
  },
  "title": "杯子 · 本地 · v1",
  "render_preview": false
}
```

按 [Agent 操作手册](AGENT_PLAYBOOK.md) 绑定当前 `workspace_id`。缩略图输入可省略。
登记函数复制指定文件、校验哈希、保存显示信息；不会导入模型、合并工作区、调用生成 API 或复制凭据。
用 `studio_tasks` 等待完成并核对 `result` 与实际 GLB 文件，再调用
`studio_open(mode="tasks", task_id=ID)` 展示。仅预览时，确认编辑场景修订号和对象 ID 不变。

重试前先查当前任务：相同作品、路线、版本和模型 SHA256 已交付时复用，避免重复登记。
同一作品保持 `work_id` 稳定；同一路线／阶段保持 `variant` 稳定；修改后递增 `version`。
改变 `variant` 会产生并列卡片，而不是同一路线的旧版本。

## 建模脚本可直接输出的标识文件

已经在当前任务里生成 GLB 的脚本可以直接写 `workbench-result.json`，不必再运行登记任务：

```json
{
  "schema": "workbench-result/v1",
  "work_id": "cup-demo",
  "work_title": "杯子",
  "variant": "生成版",
  "version": "v1",
  "note": "单网格，尺寸未经实测。",
  "primary": "scene.glb",
  "thumbnail": "preview.png"
}
```

`primary` 必须指向本次实际输出的 GLB；可选的 `thumbnail` 必须指向实际输出的 PNG、JPEG 或 WebP。
两者都是任务文件名，不能填外部 URL。名称与说明只作为文本展示；说明不是系统验证通过的标记。
格式错误或引用不存在的文件会使任务失败。旧任务可以不提供这个文件：有主 GLB 时仍展示，
通过 `source_task` 关联的重建版本会归组。探测、日志和纯报告保留在**全部运行记录**，不会占据模型列表。
