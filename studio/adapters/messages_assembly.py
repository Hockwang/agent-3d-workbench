"""Message catalog for `studio.adapters.{hunyuan_service,assembly_service,
evaluation,platform_preview,transport,registry,service_diagnostics}`.

One entry per `EditorError.coded()` call site in those modules, plus every
UI-facing string those modules return in an API payload (operation catalog
`title`/`labels`/`description`/`setup_message`, probe `message`, diagnostic
`detail`, preview `eyebrow`/`label`/`limitations`, ...) that the workbench
panel renders directly. Codes are `<module>.<meaning>`, lower snake_case, and
become part of the public error/response contract once released: never
repurpose or delete one, only add.

The "zh-CN" text below is the original wording each call site used to
hardcode, carried over verbatim (params become `{placeholder}`); "en" is a
faithful translation, not a paraphrase. A handful of messages (some in
`transport.py`, plus `hunyuan_service.cost_unit_gateway_reported` and two
`platform_preview.py` validation errors) were originally English-only (no
Chinese ever shipped for them) — those keep their original text under "en"
and gain a new "zh-CN" translation here.

Imported (for its `register()` side effect) from `studio/adapters/__init__.py`.
"""

from studio.i18n import register

register(
    {
        # -- hunyuan_service.py --------------------------------------------
        "hunyuan_service.unknown_operation_or_params": {
            "zh-CN": "未知 Hunyuan 操作或参数",
            "en": "Unknown Hunyuan operation or parameters",
        },
        "hunyuan_service.segment_needs_single_source": {
            "zh-CN": "Part 需要 source_task 或 file_url，且只能选一种",
            "en": "Part needs either source_task or file_url, and only one of them",
        },
        "hunyuan_service.invalid_source_task_id": {
            "zh-CN": "无效的来源任务 ID",
            "en": "Invalid source task id",
        },
        "hunyuan_service.unsupported_model": {
            "zh-CN": "仅接受已支持的 Hunyuan 3D 模型；不调用 GPT API",
            "en": "Only supported Hunyuan 3D models are accepted; no GPT API is called",
        },
        "hunyuan_service.invalid_output_format": {
            "zh-CN": "输出格式使用 GLB / FBX / OBJ",
            "en": "Output format must be GLB / FBX / OBJ",
        },
        "hunyuan_service.invalid_face_count": {
            "zh-CN": "face_count 必须为 3000–1500000 的整数",
            "en": "face_count must be an integer between 3000 and 1500000",
        },
        "hunyuan_service.pbr_must_be_bool": {
            "zh-CN": "pbr 必须为布尔值",
            "en": "pbr must be a boolean",
        },
        "hunyuan_service.invalid_generate_type": {
            "zh-CN": "无效 generate_type",
            "en": "Invalid generate_type",
        },
        "hunyuan_service.invalid_prompt_length": {
            "zh-CN": "prompt 需要 1–200 个字符",
            "en": "prompt must be 1-200 characters",
        },
        "hunyuan_service.text_to_3d_no_image": {
            "zh-CN": "文字生成需要 prompt，不接受图片",
            "en": "Text-to-3D needs a prompt and does not accept an image",
        },
        "hunyuan_service.source_task_no_result": {
            "zh-CN": "来源任务尚未收到 Hunyuan 结果",
            "en": "The source task has not received a Hunyuan result yet",
        },
        "hunyuan_service.source_task_wrong_provider": {
            "zh-CN": "来源必须为同一 Hunyuan 服务的生成任务",
            "en": "The source must be a generation task from the same Hunyuan service",
        },
        "hunyuan_service.source_task_missing_fbx": {
            "zh-CN": "来源任务没有 FBX；生成时请选择 FBX 输出",
            "en": "The source task has no FBX; choose FBX output when generating",
        },
        "hunyuan_service.segment_no_local_upload": {
            "zh-CN": "Part 接受 FBX 链接或来源任务，不会自动上传本机模型",
            "en": "Part accepts an FBX link or a source task; it never auto-uploads a local model",
        },
        "hunyuan_service.image_to_3d_needs_single_image": {
            "zh-CN": "图片生成需要且只接受一张本机图片或 image_url",
            "en": "Image-to-3D needs exactly one local image or image_url",
        },
        "hunyuan_service.invalid_reference_image": {
            "zh-CN": "参考图须为不超过 4 MB 的 PNG / JPG / WebP",
            "en": "The reference image must be PNG / JPG / WebP no larger than 4 MB",
        },
        "hunyuan_service.text_to_3d_no_files": {
            "zh-CN": "文字生成不接受输入文件",
            "en": "Text-to-3D does not accept input files",
        },
        "hunyuan_service.result_missing_or_too_many": {
            "zh-CN": "Hunyuan 结果缺少模型，或产物数量超过限制",
            "en": "The Hunyuan result is missing a model, or the artifact count exceeds the limit",
        },
        "hunyuan_service.part_missing_preview_glb": {
            "zh-CN": "Part 未返回可预览的 GLB",
            "en": "Part did not return a previewable GLB",
        },
        "hunyuan_service.part_empty_geometry": {
            "zh-CN": "Part 返回空几何",
            "en": "Part returned empty geometry",
        },
        "hunyuan_service.previous_submission_ambiguous": {
            "zh-CN": "上次 Hunyuan 提交结果不明确，不能自动重提；请先核对服务端记录",
            "en": (
                "The previous Hunyuan submission's result is ambiguous and cannot be "
                "auto-resubmitted; verify the server record first"
            ),
        },
        "hunyuan_service.missing_valid_task_id": {
            "zh-CN": "Hunyuan 未返回有效任务 ID，不能自动重提",
            "en": "Hunyuan did not return a valid task id; it cannot be auto-resubmitted",
        },
        "hunyuan_service.unknown_status": {
            "zh-CN": "Hunyuan 返回未知状态；可按原任务 ID 再查",
            "en": "Hunyuan returned an unknown status; you can query again with the original task id",
        },
        "hunyuan_service.task_ended": {
            "zh-CN": "Hunyuan 任务结束：{status}",
            "en": "Hunyuan task ended: {status}",
        },
        "hunyuan_service.cost_unit_gateway_reported": {
            "zh-CN": "网关返回金额",
            "en": "gateway reported amount",
        },
        "hunyuan_service.probe_invalid_model_list": {
            "zh-CN": "服务未返回有效模型清单",
            "en": "The service did not return a valid model list",
        },
        "hunyuan_service.op_segment_title": {
            "zh-CN": "Hunyuan Part · 语义分件",
            "en": "Hunyuan Part · Semantic segmentation",
        },
        "hunyuan_service.op_image_to_3d_title": {
            "zh-CN": "Hunyuan · 图片生成模型",
            "en": "Hunyuan · Image-to-3D model",
        },
        "hunyuan_service.op_text_to_3d_title": {
            "zh-CN": "Hunyuan · 文字生成模型",
            "en": "Hunyuan · Text-to-3D model",
        },
        "hunyuan_service.label_source_task": {
            "zh-CN": "已生成的 FBX 任务",
            "en": "An existing FBX task",
        },
        "hunyuan_service.label_file_url": {
            "zh-CN": "或填可访问的 FBX 链接",
            "en": "Or an accessible FBX link",
        },
        "hunyuan_service.label_model": {
            "zh-CN": "生成模型",
            "en": "Generation model",
        },
        "hunyuan_service.label_output_format": {
            "zh-CN": "输出格式",
            "en": "Output format",
        },
        "hunyuan_service.label_face_count": {
            "zh-CN": "目标面数",
            "en": "Target face count",
        },
        "hunyuan_service.op_segment_description": {
            "zh-CN": "选择之前生成 FBX 的任务，或填 FBX 链接。生成式分件可能改变原始几何和纹理，需要观察验收。",
            "en": (
                "Choose a previous FBX generation task, or fill in an FBX link. Generative "
                "segmentation can alter the original geometry and texture; verify by inspection."
            ),
        },
        "hunyuan_service.op_image_to_3d_description": {
            "zh-CN": "直接调用 Hunyuan 3D。需要继续 Part 分件时选择 FBX。本机图片会发送到所配置的服务。",
            "en": (
                "Calls Hunyuan 3D directly. Choose FBX if you plan to continue with Part "
                "segmentation. The local image is sent to the configured service."
            ),
        },
        "hunyuan_service.op_text_to_3d_description": {
            "zh-CN": "直接调用 Hunyuan 3D。需要继续 Part 分件时选择 FBX。",
            "en": "Calls Hunyuan 3D directly. Choose FBX if you plan to continue with Part segmentation.",
        },
        "hunyuan_service.setup_message_needs_base_url": {
            "zh-CN": "在 services.json 配置 base_url（任意兼容 Hunyuan Responses 协议的 OpenAI 兼容网关）和 HUNYUAN_API_KEY；无需额外 GPT API。",
            "en": (
                "Configure base_url in services.json (any OpenAI-compatible gateway that speaks "
                "the Hunyuan Responses protocol) and HUNYUAN_API_KEY; no separate GPT API is needed."
            ),
        },
        "hunyuan_service.setup_message_configured": {
            "zh-CN": "配置兼容 Hunyuan Responses 的服务地址和 HUNYUAN_API_KEY；无需额外 GPT API。",
            "en": (
                "Configure a service address compatible with Hunyuan Responses and "
                "HUNYUAN_API_KEY; no separate GPT API is needed."
            ),
        },
        "hunyuan_service.probe_message_with_models": {
            "zh-CN": "连接和鉴权有效；可用模型：{models}",
            "en": "Connection and authentication succeeded; available models: {models}",
        },
        "hunyuan_service.probe_message_no_models": {
            "zh-CN": "连接和鉴权有效，但清单中未发现已适配的模型",
            "en": "Connection and authentication succeeded, but no adapted model was found in the list",
        },
        # -- assembly_service.py --------------------------------------------
        "assembly_service.remote_url_required": {
            "zh-CN": "输入需要服务端可访问的 HTTP(S) URL",
            "en": "The input needs an HTTP(S) URL reachable from the server",
        },
        "assembly_service.remote_url_no_credentials": {
            "zh-CN": "输入需要无内嵌凭据的 HTTP(S) URL，不能传本机路径或 data URI",
            "en": "The input needs an HTTP(S) URL with no embedded credentials; a local path or data URI is not accepted",
        },
        "assembly_service.remote_url_no_localhost": {
            "zh-CN": "远端服务不能读取本机 localhost",
            "en": "The remote service cannot read this machine's localhost",
        },
        "assembly_service.remote_url_no_link_local": {
            "zh-CN": "远端服务不能读取本机或链路本地地址",
            "en": "The remote service cannot read a loopback or link-local address",
        },
        "assembly_service.unknown_operation": {
            "zh-CN": "未知 Assembly Workflow 操作",
            "en": "Unknown Assembly Workflow operation",
        },
        "assembly_service.duplicate_field_conflict": {
            "zh-CN": "重复字段使用了不同值：{field}",
            "en": "Duplicate field with conflicting values: {field}",
        },
        "assembly_service.unsupported_params": {
            "zh-CN": "未支持的 Assembly 参数：{fields}",
            "en": "Unsupported Assembly parameters: {fields}",
        },
        "assembly_service.workflow_template_mismatch": {
            "zh-CN": "工作流模板与所选操作不一致",
            "en": "The workflow template does not match the selected operation",
        },
        "assembly_service.motion_requires_prompt": {
            "zh-CN": "动作生成需要 prompt",
            "en": "Motion generation needs a prompt",
        },
        "assembly_service.invalid_cfg_type_or_weight": {
            "zh-CN": "cfgType 使用 regular/separated，并提供 cfgWeight",
            "en": "cfgType must be regular/separated, and cfgWeight must be provided",
        },
        "assembly_service.field_must_be_positive_finite": {
            "zh-CN": "{field} 必须是有限正数",
            "en": "{field} must be a finite positive number",
        },
        "assembly_service.field_must_be_positive_integer": {
            "zh-CN": "{field} 必须是正整数",
            "en": "{field} must be a positive integer",
        },
        "assembly_service.field_must_be_bool": {
            "zh-CN": "{field} 必须为布尔值",
            "en": "{field} must be a boolean",
        },
        "assembly_service.motion_input_url_not_glb": {
            "zh-CN": "动作 inputUrl 是 JSON 输入，不能传 GLB；模型动捕请选择绑骨与动作资产包",
            "en": (
                "Motion's inputUrl is a JSON input and cannot be a GLB; for model motion "
                "capture choose the rigging and motion asset package"
            ),
        },
        "assembly_service.mesh_url_required": {
            "zh-CN": "需要 meshUrl：远端可访问的 GLB 链接，不会自动上传本机模型",
            "en": "meshUrl is required: a remotely accessible GLB link; a local model is never auto-uploaded",
        },
        "assembly_service.from_node_type_unsupported": {
            "zh-CN": "from 仅支持文档中的 AssemblyAgentSegmentedGLBExport 输入",
            "en": "from only supports the documented AssemblyAgentSegmentedGLBExport input",
        },
        "assembly_service.from_node_input_invalid": {
            "zh-CN": "fromNodeInput 字段无效",
            "en": "Invalid fromNodeInput fields",
        },
        "assembly_service.assemble_requires_prompt": {
            "zh-CN": "完整装配需要 prompt",
            "en": "Full assembly needs a prompt",
        },
        "assembly_service.image_urls_must_be_mapping": {
            "zh-CN": "imageUrls 必须为视角到 URL 的对象",
            "en": "imageUrls must be an object mapping view name to URL",
        },
        "assembly_service.invalid_choice_field": {
            "zh-CN": "无效参数：{field}",
            "en": "Invalid parameter: {field}",
        },
        "assembly_service.cube_parts_invalid": {
            "zh-CN": "cubeParts 为 1–8 个非空部件名称",
            "en": "cubeParts must be 1-8 non-empty part names",
        },
        "assembly_service.zip_extract_too_large": {
            "zh-CN": "资产包解压规模超过限制",
            "en": "The asset package's extracted size exceeds the limit",
        },
        "assembly_service.zip_unsafe_entry": {
            "zh-CN": "资产包含不安全路径、链接或加密条目",
            "en": "The asset package contains an unsafe path, link, or encrypted entry",
        },
        "assembly_service.zip_name_conflict": {
            "zh-CN": "资产包文件名冲突",
            "en": "The asset package has a file name conflict",
        },
        "assembly_service.output_dir_symlink_forbidden": {
            "zh-CN": "资产输出目录不能为符号链接",
            "en": "The asset output directory cannot be a symlink",
        },
        "assembly_service.output_must_be_object": {
            "zh-CN": "Assembly output 必须为对象",
            "en": "Assembly output must be an object",
        },
        "assembly_service.workflow_path_invalid": {
            "zh-CN": "workflow_path 必须使用文档中的 OpenAPI 或 Web workflow 路径",
            "en": "workflow_path must use the documented OpenAPI or web workflow path",
        },
        "assembly_service.submission_ambiguous_no_resubmit": {
            "zh-CN": "上次提交结果不明确，不能自动重提；请向服务端核对任务",
            "en": (
                "The previous submission's result is ambiguous and cannot be auto-resubmitted; "
                "verify the task with the server"
            ),
        },
        "assembly_service.oneapi_appkey_env_not_configured": {
            "zh-CN": "OneAPI appkey 环境变量未配置",
            "en": "The OneAPI appkey environment variable is not configured",
        },
        "assembly_service.submit_missing_prompt_id": {
            "zh-CN": "Assembly 提交未返回有效 promptId；不得自动重提",
            "en": "The Assembly submission did not return a valid promptId; it must not be auto-resubmitted",
        },
        "assembly_service.submit_node_errors": {
            "zh-CN": "Assembly 提交包含节点错误；保留任务 ID，请核对服务端日志",
            "en": "The Assembly submission contains node errors; the task id is retained — check the server logs",
        },
        "assembly_service.query_failed_or_unknown_status": {
            "zh-CN": "Assembly 查询失败或返回未知状态；保留任务 ID，请核对服务端日志",
            "en": (
                "The Assembly query failed or returned an unknown status; the task id is "
                "retained — check the server logs"
            ),
        },
        "assembly_service.repeated_not_found": {
            "zh-CN": "Assembly 连续返回 not_found；保留任务 ID，可稍后继续收件",
            "en": "Assembly repeatedly returned not_found; the task id is retained — you can resume receiving later",
        },
        "assembly_service.wait_timeout": {
            "zh-CN": "Assembly 等待超时；不代表远端失败，可按原任务 ID 继续收件",
            "en": (
                "Assembly wait timed out; this does not mean the remote side failed — you can "
                "continue receiving with the original task id"
            ),
        },
        "assembly_service.success_missing_result_object": {
            "zh-CN": "Assembly 成功响应缺少结果对象",
            "en": "The Assembly success response is missing the result object",
        },
        "assembly_service.success_no_downloadable_artifact": {
            "zh-CN": "Assembly 成功但未返回可下载产物",
            "en": "Assembly succeeded but returned no downloadable artifact",
        },
        "assembly_service.result_not_valid_zip": {
            "zh-CN": "Assembly 结果不是有效 ZIP",
            "en": "The Assembly result is not a valid ZIP",
        },
        "assembly_service.cost_note_billing_unknown": {
            "zh-CN": "接口未返回计费信息，不能据此认定免费",
            "en": "The API did not return billing information; this must not be taken to mean it is free",
        },
        "assembly_service.op_assemble_title": {
            "zh-CN": "生成可动装配",
            "en": "Generate an articulated assembly",
        },
        "assembly_service.op_segment_title": {
            "zh-CN": "模型语义拆件",
            "en": "Semantic model segmentation",
        },
        "assembly_service.op_rig_glb_title": {
            "zh-CN": "自动绑骨 · GLB",
            "en": "Auto-rig · GLB",
        },
        "assembly_service.op_rig_title": {
            "zh-CN": "绑骨与动作资产包",
            "en": "Rigging and motion asset package",
        },
        "assembly_service.op_motion_title": {
            "zh-CN": "文字生成动作 · BVH",
            "en": "Text-to-motion · BVH",
        },
        "assembly_service.op_motion_description": {
            "zh-CN": "只生成动作文件；不生成模型，也不自动给模型绑定动作。",
            "en": "Generates only a motion file; it does not generate a model or auto-bind motion to one.",
        },
        "assembly_service.op_default_description": {
            "zh-CN": "使用服务端可访问的模型链接。模型完成后可预览，静态结果可接回编辑。",
            "en": (
                "Uses a model link reachable from the server. Once the model finishes it can be "
                "previewed, and the static result can be brought back into editing."
            ),
        },
        "assembly_service.label_mesh_url": {
            "zh-CN": "模型 GLB 链接",
            "en": "Model GLB link",
        },
        "assembly_service.label_prompt": {
            "zh-CN": "任务描述",
            "en": "Task description",
        },
        "assembly_service.label_mesh_up_axis": {
            "zh-CN": "模型向上轴",
            "en": "Model up axis",
        },
        "assembly_service.label_cut_backend": {
            "zh-CN": "拆件路线",
            "en": "Segmentation route",
        },
        "assembly_service.label_rig_backend": {
            "zh-CN": "绑骨路线",
            "en": "Rigging route",
        },
        "assembly_service.label_cfg_type": {
            "zh-CN": "动作引导模式",
            "en": "Motion guidance mode",
        },
        "assembly_service.label_cfg_weight": {
            "zh-CN": "动作引导强度",
            "en": "Motion guidance strength",
        },
        "assembly_service.label_duration": {
            "zh-CN": "动作时长 · 秒",
            "en": "Motion duration · seconds",
        },
        "assembly_service.label_num_samples": {
            "zh-CN": "候选动作数",
            "en": "Number of candidate motions",
        },
        "assembly_service.label_export_bvh": {
            "zh-CN": "导出 BVH 动作",
            "en": "Export BVH motion",
        },
        "assembly_service.label_return_cos_url": {
            "zh-CN": "返回可下载结果",
            "en": "Return a downloadable result",
        },
        "assembly_service.choice_mesh_up_axis_y_up": {
            "zh-CN": "Y 向上（标准 GLB）",
            "en": "Y up (standard GLB)",
        },
        "assembly_service.choice_mesh_up_axis_z_up": {
            "zh-CN": "Z 向上",
            "en": "Z up",
        },
        "assembly_service.choice_cut_backend_default": {
            "zh-CN": "默认路线",
            "en": "Default route",
        },
        "assembly_service.choice_cut_backend_cube": {
            "zh-CN": "Cubepart",
            "en": "Cubepart",
        },
        "assembly_service.choice_rig_backend_auto": {
            "zh-CN": "自动选择",
            "en": "Automatic",
        },
        "assembly_service.choice_rig_backend_puppeteer": {
            "zh-CN": "Puppeteer",
            "en": "Puppeteer",
        },
        "assembly_service.choice_rig_backend_skintokens": {
            "zh-CN": "SkinTokens",
            "en": "SkinTokens",
        },
        "assembly_service.choice_cfg_type_regular": {
            "zh-CN": "Regular",
            "en": "Regular",
        },
        "assembly_service.choice_cfg_type_separated": {
            "zh-CN": "Separated",
            "en": "Separated",
        },
        "assembly_service.setup_message_default": {
            "zh-CN": "在本机 services.json 配置可达地址、启用服务和鉴权环境变量引用。",
            "en": "Configure a reachable address in the local services.json, enable the service, and reference an auth env var.",
        },
        "assembly_service.setup_message_internal_http_insecure": {
            "zh-CN": "内网 HTTP 目前仅允许无凭据诊断；发送任务前需明确允许明文传输。",
            "en": (
                "Internal-network HTTP currently only allows credential-free diagnostics; "
                "plaintext transmission must be explicitly allowed before sending a task."
            ),
        },
        # -- evaluation.py ----------------------------------------------
        "evaluation.invalid_record_id": {
            "zh-CN": "无效的平台记录 ID",
            "en": "Invalid platform record id",
        },
        "evaluation.connection_url_invalid": {
            "zh-CN": "请填写平台网页或 API 根地址，不含账号、密码、查询参数",
            "en": "Enter the platform's web or API root address, with no account, password, or query parameters",
        },
        "evaluation.connection_path_invalid": {
            "zh-CN": "平台地址含非法路径",
            "en": "The platform address contains an invalid path",
        },
        "evaluation.auth_env_invalid": {
            "zh-CN": "认证只填写 Bearer token 的环境变量名称",
            "en": "Authentication must be the environment variable name holding the Bearer token",
        },
        "evaluation.client_path_invalid": {
            "zh-CN": "非法平台接口路径",
            "en": "Invalid platform API path",
        },
        "evaluation.missing_env_var": {
            "zh-CN": "当前服务进程缺少环境变量 {name}",
            "en": "The current service process is missing the environment variable {name}",
        },
        "evaluation.response_too_large": {
            "zh-CN": "平台响应超过本次读取上限，请缩小数据范围",
            "en": "The platform response exceeds this read's size limit; narrow the data range",
        },
        "evaluation.platform_http_error": {
            "zh-CN": "平台接口返回 HTTP {status}；请检查地址、权限或平台日志",
            "en": "The platform API returned HTTP {status}; check the address, permissions, or platform logs",
        },
        "evaluation.connection_failed": {
            "zh-CN": "无法连接评审平台；请检查服务地址和网络，写请求不会自动重试",
            "en": "Could not connect to the review platform; check the service address and network — write requests are not auto-retried",
        },
        "evaluation.invalid_json_response": {
            "zh-CN": "平台未返回有效 JSON；请填写提供 /api 接口的服务根地址",
            "en": "The platform did not return valid JSON; enter the service root address that serves the /api endpoints",
        },
        "evaluation.unsupported_resource": {
            "zh-CN": "不支持的平台资源",
            "en": "Unsupported platform resource",
        },
        "evaluation.zip_count_invalid": {
            "zh-CN": "一次接入 1–8 个本机 ZIP",
            "en": "Attach 1-8 local ZIP files at a time",
        },
        "evaluation.zip_path_invalid": {
            "zh-CN": "结果包须为存在的绝对 ZIP 路径",
            "en": "Result packages must be existing, absolute ZIP paths",
        },
        "evaluation.zip_total_too_large": {
            "zh-CN": "本次结果包总量超过 90 MB，请在原平台接入后读取批次",
            "en": "The total size of these result packages exceeds 90 MB; connect the original platform and read the batch instead",
        },
        "evaluation.health_check_failed": {
            "zh-CN": "平台健康检查未通过",
            "en": "The platform health check failed",
        },
        "evaluation.not_connected": {
            "zh-CN": "请先连接评审平台",
            "en": "Connect to the review platform first",
        },
        "evaluation.invalid_offset_or_limit": {
            "zh-CN": "offset >= 0；limit 为 1–100",
            "en": "offset must be >= 0; limit must be between 1 and 100",
        },
        "evaluation.case_run_not_in_analysis": {
            "zh-CN": "CaseRun 不属于当前分析",
            "en": "The CaseRun does not belong to the current analysis",
        },
        "evaluation.intake_incomplete": {
            "zh-CN": "先检查结果包，再明确四个分析维度和 Case 对应关系",
            "en": "Inspect the result package first, then specify the four analysis dimensions and case mapping",
        },
        "evaluation.batch_count_invalid": {
            "zh-CN": "选择 1–8 个批次",
            "en": "Select 1-8 batches",
        },
        "stale_evidence": {
            "zh-CN": "评审依据已变化；请刷新证据后再提交",
            "en": "The review evidence has changed; refresh the evidence before submitting",
        },
        "evaluation.review_note_required": {
            "zh-CN": "请填写具体评价依据",
            "en": "Enter the specific reasoning for this review",
        },
        "evaluation.preview_count_invalid": {
            "zh-CN": "一次预览 1–4 个不同的 CaseRun",
            "en": "Preview 1-4 distinct CaseRuns at a time",
        },
        "evaluation.case_not_materialized": {
            "zh-CN": "该结果尚未物化；先执行平台自动评测以准备 Viewer",
            "en": "This result has not been materialized yet; run the platform's automatic evaluation first to prepare the viewer",
        },
        "evaluation.export_resource_invalid": {
            "zh-CN": "导出支持 review_data（CSV）或 report（Markdown）",
            "en": "Export supports review_data (CSV) or report (Markdown)",
        },
        "evaluation.unsupported_action": {
            "zh-CN": "不支持的评审操作",
            "en": "Unsupported review action",
        },
        "evaluation.ai_suggestion_saved": {
            "zh-CN": "已保存 AI 建议；人在工作台查看并提交后才进入平台人工门禁",
            "en": (
                "AI suggestion saved; it only reaches the platform's human review gate after a "
                "person reviews and submits it in the workbench"
            ),
        },
        "evaluation.preview_title": {
            "zh-CN": "平台评审预览 · {id}",
            "en": "Platform review preview · {id}",
        },
        "evaluation.default_comparison_name": {
            "zh-CN": "路线对比",
            "en": "Route comparison",
        },
        # -- platform_preview.py -----------------------------------------
        "platform_preview.eyebrow_raw_result": {
            "zh-CN": "平台评审 · 原始结果",
            "en": "Platform review · Raw result",
        },
        "platform_preview.label_current_version": {
            "zh-CN": "当前版本",
            "en": "Current version",
        },
        "platform_preview.index_title": {
            "zh-CN": "路线评审预览",
            "en": "Route review preview",
        },
        "platform_preview.limitation_rigid_joints_only": {
            "zh-CN": "仅展示平台 viewer_model 声明的刚体关节；不是物理仿真或新增质量结论。",
            "en": (
                "Only shows the rigid-body joints declared by the platform's viewer_model; this "
                "is not a physics simulation or a new quality conclusion."
            ),
        },
        "platform_preview.limitation_review_saved_upstream": {
            "zh-CN": "评价通过工作台保存到原平台。",
            "en": "Reviews are saved to the original platform through the workbench.",
        },
        "platform_preview.viewer_asset_path_not_string": {
            "zh-CN": "预览资源路径必须为字符串",
            "en": "Viewer asset path must be a string",
        },
        "platform_preview.asset_path_scoped_glb_only": {
            "zh-CN": "平台预览只接受本案目录内的自包含 GLB",
            "en": "Platform preview only accepts a self-contained GLB inside this case's directory",
        },
        "platform_preview.unsupported_model_or_no_coordinate_system": {
            "zh-CN": "不支持的 Viewer model 或未声明坐标系",
            "en": "Unsupported viewer model, or no coordinate system declared",
        },
        "platform_preview.link_count_range": {
            "zh-CN": "预览每案需要 1–512 个 Link",
            "en": "Each preview case needs 1-512 links",
        },
        "platform_preview.invalid_visual_field": {
            "zh-CN": "视觉字段无效：{field}",
            "en": "Invalid visual {field}",
        },
        "platform_preview.unsupported_joint_type_no_silent_fixed": {
            "zh-CN": "不支持的关节类型，不会静默改成 fixed",
            "en": "Unsupported joint type; it will not be silently changed to fixed",
        },
        "platform_preview.case_run_count_range": {
            "zh-CN": "一次最多四个 CaseRun",
            "en": "At most four CaseRuns at a time",
        },
        "platform_preview.case_run_changed_regenerate": {
            "zh-CN": "CaseRun 已变化，请重新生成预览",
            "en": "The CaseRun has changed; please regenerate the preview",
        },
        "platform_preview.evidence_changed_during_fetch": {
            "zh-CN": "取件期间评审依据变化，请重试",
            "en": "The review evidence changed while fetching; please retry",
        },
        # -- transport.py -----------------------------------------------
        "transport.internal_origin_requires_no_credentials": {
            "zh-CN": "internal_origin 必须为不含凭据的 HTTP(S) 地址",
            "en": "internal_origin must be an HTTP(S) address with no embedded credentials",
        },
        "transport.internal_origin_scheme_host_only": {
            "zh-CN": "internal_origin 只能是协议加主机，不带路径、查询参数或片段",
            "en": "internal_origin must be scheme + host only, with no path, query string, or fragment",
        },
        "transport.service_url_requires_no_credentials": {
            "zh-CN": "服务 URL 必须为不含凭据的 HTTP(S) 地址",
            "en": "The service URL must be an HTTP(S) address with no embedded credentials",
        },
        "transport.remote_requires_https": {
            "zh-CN": "远程服务须使用 HTTPS；HTTP 仅用于本机服务",
            "en": "Remote services must use HTTPS; HTTP is only for local services",
        },
        "transport.credentials_must_use_key_env": {
            "zh-CN": "凭据必须通过服务 key_env 注入，不能放在任务参数里",
            "en": "Credentials must be injected through the service's key_env, not placed in task parameters",
        },
        "transport.enabled_must_be_bool": {
            "zh-CN": "enabled 必须为布尔值",
            "en": "enabled must be a boolean",
        },
        "transport.credential_ref_must_be_env_name": {
            "zh-CN": "凭据配置只接受环境变量名",
            "en": "Credential configuration only accepts environment variable names",
        },
        "transport.headers_env_must_be_mapping": {
            "zh-CN": "headers_env 必须是请求头名到环境变量名的映射",
            "en": "headers_env must map header names to environment variable names",
        },
        "transport.headers_env_invalid_entry": {
            "zh-CN": "headers_env 只接受合法请求头和环境变量引用，不能填凭据值",
            "en": "headers_env only accepts valid header names and environment variable references, never a raw credential value",
        },
        "transport.missing_base_url": {
            "zh-CN": "services.json 未配置该服务的 base_url",
            "en": "service has no base_url configured in services.json",
        },
        "transport.allow_insecure_http_must_be_bool": {
            "zh-CN": "allow_insecure_http 必须为布尔值",
            "en": "allow_insecure_http must be a boolean",
        },
        "transport.internal_transport_scope_restricted": {
            "zh-CN": "内网连接配置仅支持 Assembly prod-test OpenAPI 地址",
            "en": "The internal-network transport configuration only supports the Assembly prod-test OpenAPI address",
        },
        "transport.internal_origin_required": {
            "zh-CN": "transport 为 assembly-prodtest-http 时，services.json 需配置 internal_origin",
            "en": "transport assembly-prodtest-http requires internal_origin in services.json",
        },
        "transport.internal_http_requires_opt_in": {
            "zh-CN": "内网 HTTP 会明文发送凭据与任务参数；须显式设置 allow_insecure_http=true，或仅运行无凭据诊断",
            "en": (
                "Internal-network HTTP sends credentials and task parameters in plaintext; "
                "allow_insecure_http=true must be set explicitly, or only run credential-free diagnostics"
            ),
        },
        "transport.internal_path_restricted": {
            "zh-CN": "内网连接仅支持文档中的 Assembly OpenAPI 路径",
            "en": "The internal-network connection only supports the documented Assembly OpenAPI paths",
        },
        "transport.credential_contains_invalid_whitespace": {
            "zh-CN": "服务密钥含无效空白字符",
            "en": "The service credential contains invalid whitespace characters",
        },
        "transport.redirect_rejected": {
            "zh-CN": "服务 API 重定向被拒绝；请配置最终 API 地址",
            "en": "The service API redirect was rejected; configure the final API address",
        },
        "transport.path_must_start_with_slash": {
            "zh-CN": "服务接口路径必须以单个 / 开始",
            "en": "The service API path must start with a single /",
        },
        "transport.header_env_missing_or_invalid_newline": {
            "zh-CN": "鉴权环境变量缺失或含无效换行",
            "en": "The auth environment variable is missing or contains an invalid newline",
        },
        "transport.response_too_large": {
            "zh-CN": "服务响应超过 16 MB",
            "en": "The service response exceeds 16 MB",
        },
        "transport.response_not_json_object": {
            "zh-CN": "服务响应必须为 JSON 对象",
            "en": "The service response must be a JSON object",
        },
        "transport.http_error": {
            "zh-CN": "服务 HTTP {status}；请检查配置、额度与参数",
            "en": "Service HTTP {status}; check the configuration, quota, and parameters",
        },
        "transport.connection_or_json_error_no_resubmit": {
            "zh-CN": "服务连接中断或返回无效 JSON；未自动重提任务",
            "en": "The service connection was interrupted, or invalid JSON was returned; the task was not auto-resubmitted",
        },
        "transport.file_ref_invalid": {
            "zh-CN": "$file 须为存在且不超过 100 MB 的绝对路径",
            "en": "$file must be an absolute path to an existing file no larger than 100 MB",
        },
        "transport.artifact_too_large": {
            "zh-CN": "服务产物超过 1 GB",
            "en": "The service artifact exceeds 1 GB",
        },
        "transport.artifact_empty": {
            "zh-CN": "服务返回空产物",
            "en": "The service returned an empty artifact",
        },
        "transport.download_failed_resume_with_task_id": {
            "zh-CN": "产物下载失败；可用原任务 ID 继续收件",
            "en": "Artifact download failed; you can continue receiving with the original task id",
        },
        # -- registry.py --------------------------------------------------
        "registry.no_probe_available": {
            "zh-CN": "该协议暂无只读连接测试",
            "en": "This protocol has no read-only connection test yet",
        },
        "registry.unknown_adapter": {
            "zh-CN": "未知服务协议：{adapter_id}",
            "en": "Unknown service protocol: {adapter_id}",
        },
        # -- service_diagnostics.py ---------------------------------------
        "service_diagnostics.assembly_only": {
            "zh-CN": "此诊断只支持 Assembly 服务",
            "en": "This diagnostic only supports the Assembly service",
        },
        "service_diagnostics.invalid_workflow_path": {
            "zh-CN": "workflow_path 必须使用文档中的 OpenAPI 或 Web workflow 路径",
            "en": "workflow_path must use the documented OpenAPI or web workflow path",
        },
        "service_diagnostics.detail_not_configured": {
            "zh-CN": "需要启用服务并配置网关鉴权环境变量引用",
            "en": "The service must be enabled and a gateway-auth environment variable reference configured",
        },
        "service_diagnostics.detail_connection_or_json_error": {
            "zh-CN": "连接失败或响应不是有效 JSON",
            "en": "Connection failed, or the response was not valid JSON",
        },
        "service_diagnostics.detail_gateway_missing_auth": {
            "zh-CN": "已到达网关，缺少网关鉴权；不是 OneAPI 推理 key",
            "en": "Reached the gateway, but gateway authentication is missing; this is not the OneAPI inference key",
        },
        "service_diagnostics.detail_accepted_read_only": {
            "zh-CN": "只读 history 查询已到业务层；未验证提交、余额或生成质量",
            "en": "The read-only history query reached the business layer; submission, balance, and generation quality are unverified",
        },
        "service_diagnostics.detail_unverified_error": {
            "zh-CN": "网关或业务返回错误；未输出可能含敏感信息的响应正文",
            "en": "The gateway or business layer returned an error; the response body was withheld as it may contain sensitive information",
        },
    }
)
