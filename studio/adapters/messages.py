"""Message catalog for the Lux3D / Seed3D / Meshy / Tripo adapter modules plus
the `services`/`service_connections` BYOK façade.

One entry per `EditorError.coded()`/`RuntimeError` call site plus every
UI-facing string (operation-catalog titles/descriptions/labels/choices, setup
messages, probe messages, BUILTINS/TEMPLATES connection titles) in
`studio/adapters/{lux3d_service,lux3d_commerce,lux3d_upload,seed3d_service,
meshy,tripo,services,service_connections}.py`. Codes are `<module>.<meaning>`,
lower snake case. The "zh-CN" text below is the original wording each site
used to hardcode, carried over verbatim; "en" is a faithful translation, not a
paraphrase.

Imported (for its `register()` side effect) from `studio/adapters/__init__.py`.
"""

from studio.i18n import register

register(
    {
        # --- lux3d_commerce.py ---
        "lux3d_commerce.account_context_expired": {
            "zh-CN": "Lux3D 账户上下文已过期",
            "en": "Lux3D account context has expired",
        },
        "lux3d_commerce.account_context_invalid": {
            "zh-CN": "Lux3D 未返回有效账户上下文",
            "en": "Lux3D did not return a valid account context",
        },
        "lux3d_commerce.account_response_incomplete": {
            "zh-CN": "Lux3D 账户响应不完整，未将未知余额当作零",
            "en": "Lux3D account response is incomplete; an unknown balance is not treated as zero",
        },
        "lux3d_commerce.connection_required": {
            "zh-CN": "请选择 Lux3D 连接",
            "en": "Please select a Lux3D connection",
        },
        "lux3d_commerce.credits_invalid": {
            "zh-CN": "Lux3D 余额/报价数值无效",
            "en": "Lux3D balance/quote value is invalid",
        },
        "lux3d_commerce.items_and_single_operation_conflict": {
            "zh-CN": "计划 items 与单项 operation 不能混用",
            "en": "Plan items and a single operation cannot be mixed",
        },
        "lux3d_commerce.key_not_configured": {
            "zh-CN": "请先配置并启用 Lux3D 密钥",
            "en": "Please configure and enable a Lux3D key first",
        },
        "lux3d_commerce.member_status_invalid": {
            "zh-CN": "Lux3D 会员状态无效",
            "en": "Lux3D membership status is invalid",
        },
        "lux3d_commerce.page_must_be_positive_int": {
            "zh-CN": "page 必须为正整数",
            "en": "page must be a positive integer",
        },
        "lux3d_commerce.pagesize_range": {
            "zh-CN": "pagesize 范围为 1–100",
            "en": "pagesize must be between 1 and 100",
        },
        "lux3d_commerce.plan_size_range": {
            "zh-CN": "Lux3D 计划报价需要 1–50 项操作",
            "en": "A Lux3D plan quote needs between 1 and 50 operations",
        },
        "lux3d_commerce.quote_account_mismatch": {
            "zh-CN": "Lux3D 报价账户或计价范围不一致",
            "en": "Lux3D quote account or pricing scope does not match",
        },
        "lux3d_commerce.quote_expired": {
            "zh-CN": "Lux3D 报价已过期",
            "en": "Lux3D quote has expired",
        },
        "lux3d_commerce.quote_expired_refetch": {
            "zh-CN": "Lux3D 报价已过期，请重新获取",
            "en": "Lux3D quote has expired; please fetch a new one",
        },
        "lux3d_commerce.quote_id_invalid": {
            "zh-CN": "无效 Lux3D quote_id",
            "en": "Invalid Lux3D quote_id",
        },
        "lux3d_commerce.quote_input_must_be_local_file": {
            "zh-CN": "报价输入须为本机文件",
            "en": "Quote inputs must be local files",
        },
        "lux3d_commerce.quote_item_fields_required": {
            "zh-CN": "报价明细需要 operation、params、inputs",
            "en": "Each quote line item needs operation, params, and inputs",
        },
        "lux3d_commerce.quote_not_found": {
            "zh-CN": "Lux3D 报价不存在，请重新获取",
            "en": "Lux3D quote not found; please fetch a new one",
        },
        "lux3d_commerce.quote_response_incomplete": {
            "zh-CN": "Lux3D 报价响应不完整",
            "en": "Lux3D quote response is incomplete",
        },
        "lux3d_commerce.quote_stale": {
            "zh-CN": "参数、输入或账户已改变，请重新获取 Lux3D 报价",
            "en": "Parameters, inputs, or the account have changed; please fetch a new Lux3D quote",
        },
        "lux3d_commerce.quote_totals_mismatch": {
            "zh-CN": "Lux3D 报价明细与总额不一致",
            "en": "Lux3D quote line items do not sum to the total",
        },
        "lux3d_commerce.resume_task_no_requote": {
            "zh-CN": "恢复任务无需重新报价或提交",
            "en": "A resumed task does not need to be requoted or resubmitted",
        },
        "lux3d_commerce.task_query_invalid": {
            "zh-CN": "Lux3D 任务查询条件无效",
            "en": "Lux3D task query condition is invalid",
        },
        "lux3d_commerce.task_query_time_range_invalid": {
            "zh-CN": "任务查询时间范围无效",
            "en": "Task query time range is invalid",
        },
        "lux3d_commerce.timestamp_invalid": {
            "zh-CN": "Lux3D 账户/报价时间无效",
            "en": "Lux3D account/quote timestamp is invalid",
        },
        "lux3d_commerce.trial_credits_invalid": {
            "zh-CN": "Lux3D 试用额度无效",
            "en": "Lux3D trial credits are invalid",
        },
        "lux3d_commerce.unknown_action": {
            "zh-CN": "未知 Lux3D 服务操作",
            "en": "Unknown Lux3D service action",
        },
        # --- lux3d_service.py ---
        "lux3d_service.3mf_missing_model": {
            "zh-CN": "Lux3D 3MF 缺少模型",
            "en": "Lux3D 3MF is missing its model",
        },
        "lux3d_service.asset_must_be_url": {
            "zh-CN": "素材须为已上传的 HTTP(S) URL",
            "en": "Assets must be an already-uploaded HTTP(S) URL",
        },
        "lux3d_service.auto_size_conflicts_custom_size": {
            "zh-CN": "自动尺寸与 customSize 不能同时使用",
            "en": "aiPredictSize and customSize cannot be used together",
        },
        "lux3d_service.custom_size_invalid": {
            "zh-CN": "customSize 须为正毫米数",
            "en": "customSize must be a positive number of millimeters",
        },
        "lux3d_service.face_count_range": {
            "zh-CN": "faceCount 须为 10000–300000 的整数",
            "en": "faceCount must be an integer between 10000 and 300000",
        },
        "lux3d_service.field_must_be_bool": {
            "zh-CN": "{field} 须为布尔值",
            "en": "{field} must be a boolean",
        },
        "lux3d_service.four_view_count_invalid": {
            "zh-CN": "Lux3D 四视图数量不正确",
            "en": "Lux3D four-view output count is incorrect",
        },
        "lux3d_service.g1_no_enable_pbr": {
            "zh-CN": "G1 不接受 enablePbr",
            "en": "G1 does not accept enablePbr",
        },
        "lux3d_service.g1turbo_no_custom_size": {
            "zh-CN": "G1-Turbo 不接受 customSize",
            "en": "G1-Turbo does not accept customSize",
        },
        "lux3d_service.glb_conversion_needs_output_format": {
            "zh-CN": "GLB 转换须指定 outputFormat",
            "en": "GLB conversion requires an outputFormat",
        },
        "lux3d_service.global_path_required": {
            "zh-CN": "Lux3D 国际站地址必须包含 /global",
            "en": "The Lux3D international site address must include /global",
        },
        "lux3d_service.image_file_or_url_only": {
            "zh-CN": "图片文件与图片 URL 只能选择一种",
            "en": "Choose either an image file or an image URL, not both",
        },
        "lux3d_service.image_format_invalid": {
            "zh-CN": "Lux3D 图片格式无效",
            "en": "Lux3D image format is invalid",
        },
        "lux3d_service.image_input_required": {
            "zh-CN": "请提供图片文件或 img/imgs URL",
            "en": "Please provide an image file or an img/imgs URL",
        },
        "lux3d_service.image_or_prompt_required": {
            "zh-CN": "请提供图片或 prompt",
            "en": "Please provide an image or a prompt",
        },
        "lux3d_service.image_output_incomplete": {
            "zh-CN": "Lux3D 图片产物不完整",
            "en": "Lux3D image output is incomplete",
        },
        "lux3d_service.img_imgs_conflict": {
            "zh-CN": "img 与 imgs 不能同时使用",
            "en": "img and imgs cannot be used together",
        },
        "lux3d_service.imgs_count_range": {
            "zh-CN": "imgs 需要 1–32 张图片",
            "en": "imgs requires between 1 and 32 images",
        },
        "lux3d_service.material_version_invalid": {
            "zh-CN": "材质重绘 version 须为 v3.0-standard",
            "en": "material-transfer version must be v3.0-standard",
        },
        "lux3d_service.max_reference_images": {
            "zh-CN": "最多 32 张参考图",
            "en": "At most 32 reference images",
        },
        "lux3d_service.mesh_url_must_be_glb": {
            "zh-CN": "材质重绘 meshUrl 须为 GLB",
            "en": "material-transfer meshUrl must be a GLB",
        },
        "lux3d_service.missing_inputs": {
            "zh-CN": "缺少 Lux3D 输入：{fields}",
            "en": "Missing Lux3D input: {fields}",
        },
        "lux3d_service.missing_requested_outputs": {
            "zh-CN": "Lux3D 成功但缺少请求的产物，保留远端任务 ID 供恢复",
            "en": "Lux3D succeeded but is missing requested outputs; the remote task ID is kept for recovery",
        },
        "lux3d_service.model_input_mismatch": {
            "zh-CN": "模型输入与当前操作不匹配或重复",
            "en": "Model input does not match the current operation, or is duplicated",
        },
        "lux3d_service.model_url_invalid_format": {
            "zh-CN": "格式转换输入须为 GLB 或 Lux3D ZIP",
            "en": "Format-conversion input must be a GLB or a Lux3D ZIP",
        },
        "lux3d_service.operation_description": {
            "zh-CN": "Lux3D 官方服务。可上传本机文件，或在高级参数填写 img/imgs/meshUrl/modelUrl；材质重绘需要模型和参考图。",
            "en": (
                "Official Lux3D service. Upload a local file, or fill in img/imgs/meshUrl/modelUrl under "
                "advanced parameters; material transfer needs both a model and a reference image."
            ),
        },
        "lux3d_service.output_content_not_string": {
            "zh-CN": "Lux3D 产物 content 须为字符串",
            "en": "Lux3D output content must be a string",
        },
        "lux3d_service.output_format_invalid": {
            "zh-CN": "Lux3D 输出格式无效或重复",
            "en": "Lux3D outputFormat is invalid or contains duplicates",
        },
        "lux3d_service.output_format_ply_label": {
            "zh-CN": "高斯 PLY",
            "en": "Gaussian PLY",
        },
        "lux3d_service.output_format_zip_label": {
            "zh-CN": "原始 ZIP",
            "en": "Raw ZIP",
        },
        "lux3d_service.output_item_invalid": {
            "zh-CN": "Lux3D 产物格式无效",
            "en": "Lux3D output item format is invalid",
        },
        "lux3d_service.output_slots_mismatch": {
            "zh-CN": "Lux3D 产物槽位与请求不一致，拒绝猜测格式",
            "en": "Lux3D output slots do not match the request; refusing to guess the format",
        },
        "lux3d_service.output_url_invalid": {
            "zh-CN": "Lux3D 产物 URL 无效",
            "en": "Lux3D output URL is invalid",
        },
        "lux3d_service.outputs_missing": {
            "zh-CN": "Lux3D 成功任务缺少产物列表",
            "en": "Successful Lux3D task is missing its outputs list",
        },
        "lux3d_service.ply_header_invalid": {
            "zh-CN": "Lux3D PLY 文件头无效",
            "en": "Lux3D PLY file header is invalid",
        },
        "lux3d_service.ply_only_no_enable_pbr": {
            "zh-CN": "仅 PLY 输出时不能设置 enablePbr",
            "en": "enablePbr cannot be set when the only output is PLY",
        },
        "lux3d_service.previous_submission_ambiguous": {
            "zh-CN": "上次 Lux3D 提交结果不明确；请查询远端任务记录，不能自动重提",
            "en": (
                "The previous Lux3D submission's result is unknown; check the remote task record — it cannot "
                "be resubmitted automatically"
            ),
        },
        "lux3d_service.probe_ok": {
            "zh-CN": "Lux3D 连接和鉴权有效，可用积分 {credits}",
            "en": "Lux3D connection and credentials are valid; available credits: {credits}",
        },
        "lux3d_service.prompt_empty": {
            "zh-CN": "prompt 不能为空",
            "en": "prompt cannot be empty",
        },
        "lux3d_service.quote_item_invalid": {
            "zh-CN": "quote_item 须为报价明细序号字符串",
            "en": "quote_item must be a quote line-item index string",
        },
        "lux3d_service.quote_required": {
            "zh-CN": "Lux3D 付费生成前须先获取报价（quote_id）；先用 studio_services 的 quote 操作取得报价再提交",
            "en": (
                "A Lux3D paid generation requires a quote (quote_id) first; "
                "fetch one via studio_services' quote action before submitting"
            ),
        },
        "lux3d_service.region_change_requires_new_connection": {
            "zh-CN": "区域变更请添加新连接，避免沿用其他区域密钥",
            "en": "Add a new connection for a region change instead of reusing another region's key",
        },
        "lux3d_service.region_mismatch": {
            "zh-CN": "Lux3D API 地址与密钥区域不一致",
            "en": "The Lux3D API address does not match the key's region",
        },
        "lux3d_service.region_required": {
            "zh-CN": "Lux3D 连接须明确国内 cn 或国际 international 区域",
            "en": "Lux3D connections must explicitly declare the cn (mainland) or international region",
        },
        "lux3d_service.remote_task_failed": {
            "zh-CN": "Lux3D 远端任务失败或已取消：{status}",
            "en": "Lux3D remote task failed or was cancelled: {status}",
        },
        "lux3d_service.request_failed": {
            "zh-CN": "Lux3D 请求未成功：{code}",
            "en": "Lux3D request did not succeed: {code}",
        },
        "lux3d_service.response_missing_data": {
            "zh-CN": "Lux3D 响应缺少数据",
            "en": "Lux3D response is missing data",
        },
        "lux3d_service.setup_message": {
            "zh-CN": "配置 Lux3D 专用 API key；国内和国际站密钥分别保存，支持余额、报价和远端任务恢复。",
            "en": (
                "Configure a dedicated Lux3D API key; mainland and international keys are stored separately, "
                "with balance, quoting, and remote task recovery."
            ),
        },
        "lux3d_service.single_reference_image_required": {
            "zh-CN": "该操作需要一张参考图",
            "en": "This operation requires exactly one reference image",
        },
        "lux3d_service.stl_no_mesh": {
            "zh-CN": "Lux3D STL 没有网格",
            "en": "Lux3D STL has no mesh",
        },
        "lux3d_service.style_invalid": {
            "zh-CN": "未知 Lux3D style",
            "en": "Unknown Lux3D style",
        },
        "lux3d_service.task_id_invalid": {
            "zh-CN": "Lux3D task ID 必须是正整数",
            "en": "Lux3D task ID must be a positive integer",
        },
        "lux3d_service.task_identity_invalid": {
            "zh-CN": "Lux3D 任务响应身份或状态无效",
            "en": "Lux3D task response identity or status is invalid",
        },
        "lux3d_service.title_four_view": {
            "zh-CN": "生成四视图",
            "en": "Generate four views",
        },
        "lux3d_service.title_image_to_3d": {
            "zh-CN": "图片生成模型",
            "en": "Image-to-3D model",
        },
        "lux3d_service.title_material_transfer": {
            "zh-CN": "材质重绘",
            "en": "Material transfer",
        },
        "lux3d_service.title_multi_format_export": {
            "zh-CN": "多格式转换",
            "en": "Multi-format export",
        },
        "lux3d_service.title_multi_image_to_3d": {
            "zh-CN": "多视图生成模型",
            "en": "Multi-image-to-3D model",
        },
        "lux3d_service.title_multimodal_image": {
            "zh-CN": "生成参考图",
            "en": "Generate reference image",
        },
        "lux3d_service.title_text_to_3d": {
            "zh-CN": "文字生成模型",
            "en": "Text-to-3D model",
        },
        "lux3d_service.unknown_operation": {
            "zh-CN": "未知 Lux3D 操作",
            "en": "Unknown Lux3D operation",
        },
        "lux3d_service.unsupported_fields": {
            "zh-CN": "Lux3D 参数包含未支持的字段：{fields}",
            "en": "Lux3D parameters contain unsupported fields: {fields}",
        },
        "lux3d_service.unsupported_input_types": {
            "zh-CN": "Lux3D 输入只接受 PNG/JPEG/WebP、GLB、ZIP",
            "en": "Lux3D input only accepts PNG/JPEG/WebP, GLB, or ZIP",
        },
        "lux3d_service.version_invalid": {
            "zh-CN": "version 为 G1 / G1-Turbo",
            "en": "version must be G1 / G1-Turbo",
        },
        "lux3d_service.zip_checksum_failed": {
            "zh-CN": "Lux3D ZIP 校验失败",
            "en": "Lux3D ZIP failed its integrity check",
        },
        "lux3d_service.zip_empty_or_too_large": {
            "zh-CN": "Lux3D ZIP 为空或展开体积过大",
            "en": "Lux3D ZIP is empty or too large when expanded",
        },
        # --- lux3d_upload.py ---
        "lux3d_upload.block_number_invalid": {
            "zh-CN": "Lux3D 分片编号无效",
            "en": "Lux3D block number is invalid",
        },
        "lux3d_upload.block_number_out_of_range": {
            "zh-CN": "Lux3D 分片编号越界",
            "en": "Lux3D block number is out of range",
        },
        "lux3d_upload.checksum_mismatch": {
            "zh-CN": "Lux3D 上传校验和不一致",
            "en": "Lux3D upload checksum does not match",
        },
        "lux3d_upload.connection_failed_or_invalid": {
            "zh-CN": "Lux3D 素材上传连接失败或响应无效",
            "en": "Lux3D asset upload connection failed or the response is invalid",
        },
        "lux3d_upload.file_must_exist_and_fit": {
            "zh-CN": "Lux3D 素材须为存在且不超过 1 GB 的本机文件",
            "en": "Lux3D assets must be an existing local file no larger than 1 GB",
        },
        "lux3d_upload.missing_blocks_invalid": {
            "zh-CN": "Lux3D 缺失分片清单无效",
            "en": "Lux3D missing-blocks list is invalid",
        },
        "lux3d_upload.response_invalid": {
            "zh-CN": "Lux3D 素材上传响应无效",
            "en": "Lux3D asset upload response is invalid",
        },
        "lux3d_upload.response_missing_data": {
            "zh-CN": "Lux3D 素材上传缺少数据",
            "en": "Lux3D asset upload response is missing data",
        },
        "lux3d_upload.response_too_large": {
            "zh-CN": "Lux3D 上传响应过大",
            "en": "Lux3D upload response is too large",
        },
        "lux3d_upload.token_invalid": {
            "zh-CN": "Lux3D 上传令牌无效",
            "en": "Lux3D upload token is invalid",
        },
        "lux3d_upload.upload_failed": {
            "zh-CN": "Lux3D 素材上传失败",
            "en": "Lux3D asset upload failed",
        },
        "lux3d_upload.upload_rejected": {
            "zh-CN": "Lux3D 素材上传被拒绝",
            "en": "Lux3D asset upload was rejected",
        },
        "lux3d_upload.upload_timeout": {
            "zh-CN": "Lux3D 素材上传未在限定时间内完成",
            "en": "Lux3D asset upload did not complete within the time limit",
        },
        # --- meshy.py ---
        "meshy.balance_invalid": {
            "zh-CN": "Meshy 未返回有效余额",
            "en": "Meshy did not return a valid balance",
        },
        "meshy.probe_ok": {
            "zh-CN": "连接和鉴权有效",
            "en": "Connection and credentials are valid",
        },
        # --- seed3d_service.py ---
        "seed3d_service.label_prompt": {
            "zh-CN": "生成要求",
            "en": "Generation prompt",
        },
        "seed3d_service.model_list_invalid": {
            "zh-CN": "服务未返回有效模型清单",
            "en": "The service did not return a valid model list",
        },
        "seed3d_service.no_previewable_glb": {
            "zh-CN": "Seed3D 结果中没有可预览的 GLB",
            "en": "There is no previewable GLB in the Seed3D result",
        },
        "seed3d_service.operation_description": {
            "zh-CN": "调用 Seed3D 2.0 生成带纹理模型。本机参考图会发送至所配置服务，通常需数分钟。",
            "en": (
                "Calls Seed3D 2.0 to generate a textured model. The local reference image is sent to the "
                "configured service; this usually takes a few minutes."
            ),
        },
        "seed3d_service.previous_submission_ambiguous": {
            "zh-CN": "上次 Seed3D 提交结果不明确，该接口不支持按 ID 查询；请先核对账单，不会自动重提",
            "en": (
                "The previous Seed3D submission's result is unknown and this API has no query-by-ID endpoint; "
                "check the billing record first — it will not be resubmitted automatically"
            ),
        },
        "seed3d_service.probe_ok_no_models": {
            "zh-CN": "连接和鉴权有效，但清单中未发现已适配的模型",
            "en": "Connection and credentials are valid, but no supported model was found in the list",
        },
        "seed3d_service.probe_ok_with_models": {
            "zh-CN": "连接和鉴权有效；可用模型：{models}",
            "en": "Connection and credentials are valid; available models: {models}",
        },
        "seed3d_service.prompt_length_range": {
            "zh-CN": "生成要求需要 1–2000 个字符",
            "en": "The generation prompt must be between 1 and 2000 characters",
        },
        "seed3d_service.reference_image_invalid": {
            "zh-CN": "参考图须为不超过 4 MB 的 PNG / JPG / WebP",
            "en": "The reference image must be a PNG / JPG / WebP no larger than 4 MB",
        },
        "seed3d_service.result_files_unrecognized": {
            "zh-CN": "Seed3D 未返回可识别的模型产物；不会自动重提生成",
            "en": "Seed3D did not return a recognizable model output; generation will not be resubmitted automatically",
        },
        "seed3d_service.setup_message_with_base_url": {
            "zh-CN": "在 services.json 配置 base_url（任意兼容 OpenAI chat/completions 协议的网关）和 SEED3D_API_KEY；无需额外 GPT API。",
            "en": (
                "Configure base_url (any gateway compatible with the OpenAI chat/completions protocol) and "
                "SEED3D_API_KEY in services.json; no separate GPT API is needed."
            ),
        },
        "seed3d_service.setup_message_without_base_url": {
            "zh-CN": "在 3D 服务中配置 Seed3D 网关；直接生成模型，无需 GPT API。",
            "en": "Configure the Seed3D gateway in 3D services; it generates models directly, no GPT API needed.",
        },
        "seed3d_service.single_image_required": {
            "zh-CN": "Seed3D 需要且只接受一张本机图片或 image_url",
            "en": "Seed3D requires exactly one local image or an image_url",
        },
        "seed3d_service.title_image_to_3d": {
            "zh-CN": "Seed3D · 图片生成模型",
            "en": "Seed3D · Image-to-3D model",
        },
        "seed3d_service.unsupported_operation": {
            "zh-CN": "Seed3D 仅支持图片生成，参数为 prompt / image_url",
            "en": "Seed3D only supports image-to-3D; parameters are prompt / image_url",
        },
        # --- service_connections.py ---
        "service_connections.base_url_no_query_or_fragment": {
            "zh-CN": "服务地址不能带查询参数或片段",
            "en": "The service address cannot include a query string or fragment",
        },
        "service_connections.builtin_or_file_configured_not_removable": {
            "zh-CN": "内置或文件配置的服务可停用；仅界面新建的连接可删除",
            "en": "A built-in or file-configured service can be disabled; only a connection created in the UI can be deleted",
        },
        "service_connections.credential_base_url_mismatch": {
            "zh-CN": "密钥与服务地址不匹配；请为当前地址重新配置密钥",
            "en": "The key does not match the service address; reconfigure the key for the current address",
        },
        "service_connections.custom_headers_not_editable": {
            "zh-CN": "该连接使用自定义请求头，请继续通过 services.json 管理，或新建 Bearer 连接",
            "en": (
                "This connection uses custom request headers; keep managing it through services.json, or "
                "create a new Bearer connection"
            ),
        },
        "service_connections.enable_and_configure_key_first": {
            "zh-CN": "请先启用服务并配置密钥",
            "en": "Please enable the service and configure a key first",
        },
        "service_connections.enabled_and_clear_key_must_be_bool": {
            "zh-CN": "启停与清除密钥必须为布尔值",
            "en": "enabled and clear_key must be booleans",
        },
        "service_connections.invalid_base_url": {
            "zh-CN": "无效服务地址",
            "en": "Invalid service address",
        },
        "service_connections.invalid_service_id": {
            "zh-CN": "无效服务 ID",
            "en": "Invalid service ID",
        },
        "service_connections.key_and_env_conflict": {
            "zh-CN": "API key 与环境变量只能选一种",
            "en": "Choose either an API key or an environment variable, not both",
        },
        "service_connections.key_env_must_be_name_not_value": {
            "zh-CN": "只能填写环境变量名，不能填写密钥值",
            "en": "Only an environment variable name can be entered here, not a key value",
        },
        "service_connections.key_unseal_failed": {
            "zh-CN": "密钥无法解密或格式无效；请重新打开服务设置并填写密钥",
            "en": "The key could not be decrypted or is malformed; reopen service settings and fill in the key again",
        },
        "service_connections.local_config_unreadable": {
            "zh-CN": "本机 3D 服务配置无法读取；未覆盖原文件",
            "en": "The local 3D service configuration could not be read; the original file was not overwritten",
        },
        "service_connections.protocol_change_not_allowed": {
            "zh-CN": "已有连接不能更换协议；请添加新连接",
            "en": "An existing connection cannot change protocol; add a new connection instead",
        },
        "service_connections.revision_conflict_on_delete": {
            "zh-CN": "服务配置已更新，请重新打开设置",
            "en": "The service configuration has been updated; reopen settings",
        },
        "service_connections.revision_conflict_on_save": {
            "zh-CN": "服务配置已更新，请重新打开设置后再保存",
            "en": "The service configuration has been updated; reopen settings and save again",
        },
        "service_connections.service_not_found": {
            "zh-CN": "服务不存在",
            "en": "Service not found",
        },
        "service_connections.title_hunyuan": {
            "zh-CN": "Hunyuan 3D / Part · Responses 兼容网关",
            "en": "Hunyuan 3D / Part · Responses-compatible gateway",
        },
        "service_connections.title_length_range": {
            "zh-CN": "连接名称需要 1–100 个字符",
            "en": "The connection name must be between 1 and 100 characters",
        },
        "service_connections.title_lux3d": {
            "zh-CN": "Lux3D · 国内站",
            "en": "Lux3D · Mainland",
        },
        "service_connections.title_lux3d_global": {
            "zh-CN": "Lux3D · 国际站",
            "en": "Lux3D · International",
        },
        "service_connections.title_meshy": {
            "zh-CN": "Meshy · 官方 API",
            "en": "Meshy · Official API",
        },
        "service_connections.title_seed3d": {
            "zh-CN": "Seed3D · Chat Completions 兼容网关",
            "en": "Seed3D · Chat Completions-compatible gateway",
        },
        "service_connections.title_tripo": {
            "zh-CN": "Tripo · 官方 API",
            "en": "Tripo · Official API",
        },
        "service_connections.unknown_action": {
            "zh-CN": "服务操作为 list/save/delete/probe",
            "en": "Service action must be one of list/save/delete/probe",
        },
        "service_connections.unknown_connection_field": {
            "zh-CN": "未知连接字段；API key 只能由界面加密提交或引用环境变量",
            "en": "Unknown connection field; the API key can only be submitted encrypted from the UI or referenced via an environment variable",
        },
        "service_connections.unsupported_protocol": {
            "zh-CN": "请选择已支持的 3D 服务协议",
            "en": "Please choose a supported 3D service protocol",
        },
        # --- services.py ---
        "services.base_url_required": {
            "zh-CN": "{provider}：请在 services.json 中设置 base_url（{hint}）",
            "en": "{provider}: set base_url in services.json ({hint})",
        },
        "services.config_must_be_object": {
            "zh-CN": "服务配置必须为对象",
            "en": "The service configuration must be an object",
        },
        "services.credential_required": {
            "zh-CN": "请先在 3D 服务设置中填写 API key 或环境变量引用",
            "en": "Please fill in an API key or environment variable reference in the 3D service settings first",
        },
        "services.each_provider_config_must_be_object": {
            "zh-CN": "每个服务配置必须为对象",
            "en": "Each service configuration must be an object",
        },
        "services.invalid_artifact_name": {
            "zh-CN": "服务产物名称无效",
            "en": "The service artifact name is invalid",
        },
        "services.missing_env_vars": {
            "zh-CN": "服务尚未配置环境变量 {missing}",
            "en": "The service has not configured the environment variable(s) {missing}",
        },
        "services.missing_remote_id": {
            "zh-CN": "服务未返回有效任务 ID；请在提供商处核对，不能自动重提",
            "en": "The service did not return a valid task ID; check with the provider — it cannot be resubmitted automatically",
        },
        "services.no_downloadable_artifacts": {
            "zh-CN": "远端成功但没有可下载产物；请核对服务契约",
            "en": "The remote task succeeded but produced no downloadable artifacts; check the service contract",
        },
        "services.payload_must_be_object": {
            "zh-CN": "服务 params 为请求 JSON 对象",
            "en": "The service params must be a request JSON object",
        },
        "services.previous_submission_ambiguous": {
            "zh-CN": "上次提交结果不明确；须在提供商处核对远端任务 ID，不能自动重提",
            "en": (
                "The previous submission's result is unknown; check the remote task ID with the provider — "
                "it cannot be resubmitted automatically"
            ),
        },
        "services.provider_not_enabled": {
            "zh-CN": "服务尚未启用；请先配置可达地址和鉴权方式",
            "en": "The service is not enabled yet; configure a reachable address and an authentication method first",
        },
        "services.remote_task_failed": {
            "zh-CN": "远端任务失败：{status}",
            "en": "Remote task failed: {status}",
        },
        "services.title_assembly": {
            "zh-CN": "Assembly Workflow",
            "en": "Assembly Workflow",
        },
        "services.title_hunyuan": {
            "zh-CN": "Hunyuan 3D / Part",
            "en": "Hunyuan 3D / Part",
        },
        "services.title_lux3d": {
            "zh-CN": "Lux3D · 国内站",
            "en": "Lux3D · Mainland",
        },
        "services.title_lux3d_global": {
            "zh-CN": "Lux3D · 国际站",
            "en": "Lux3D · International",
        },
        "services.title_meshy": {
            "zh-CN": "Meshy",
            "en": "Meshy",
        },
        "services.title_seed3d": {
            "zh-CN": "Seed3D",
            "en": "Seed3D",
        },
        "services.title_tripo": {
            "zh-CN": "Tripo",
            "en": "Tripo",
        },
        "services.unknown_service_or_operation": {
            "zh-CN": "未知服务或操作，请先读取 studio_capabilities",
            "en": "Unknown service or operation; read studio_capabilities first",
        },
        # --- tripo.py ---
        "tripo.balance_rejected": {
            "zh-CN": "Tripo 拒绝余额查询；请检查凭据和地址",
            "en": "Tripo rejected the balance query; check the credentials and address",
        },
        "tripo.image_too_large": {
            "zh-CN": "Tripo 输入图片不能超过 20 MB",
            "en": "Tripo input image must not exceed 20 MB",
        },
        "tripo.probe_ok": {
            "zh-CN": "连接和鉴权有效",
            "en": "Connection and credentials are valid",
        },
        "tripo.unsupported_image_format": {
            "zh-CN": "Tripo 输入须为 JPG/PNG/WebP 图片",
            "en": "Tripo input must be a JPG/PNG/WebP image",
        },
        "tripo.upload_missing_file_token": {
            "zh-CN": "Tripo 上传未返回文件标识",
            "en": "Tripo upload did not return a file token",
        },
    }
)
