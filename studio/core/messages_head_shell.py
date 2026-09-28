"""Message catalog for `studio.core.head_shell`, `head_shell_audit`,
`head_shell_vision`, `head_shell_sight` and `task_recipe_progress`.

One entry per `raise ValueError(...)`/`raise RuntimeError(...)` call site,
per CATALOG `title`/`description`/`labels` display field of `head_shell.py`
(see the CATALOG-convention note in `studio/core/messages_tasks.py`), and —
for `task_recipe_progress.py` specifically — per `detail`/`scope_note`
string it returns, because those flow straight into the `/api/state`
response's `recipe.steps[].detail`, live per-request UI text exactly like an
error message. The same live-language rule applies to the handful of
`report.json["workflow_checks"][*]["detail"]`/`["head_fit"]["note"]` strings
`head_shell.py` writes that `task_recipe_progress.view()` reads straight back
and surfaces the same way (`head_shell.check_*` codes below): those are
rendered with `render()` at write time, using the worker process's
`STUDIO_LANG`. Every other `report.json`/`assembly-verification.json`/
`sight-verification.json` artifact field these modules write is frozen
task-output data, not per-request UI text, and — matching the existing
precedent in `generated_editing.py`'s own `report` dict — is left as literal
Chinese.

Codes are `<module>.<meaning>`, lower snake_case, one prefix per producing
module (`head_shell.*`, `head_shell_audit.*`, `head_shell_vision.*`,
`head_shell_sight.*`, `task_recipe_progress.*`), matching the file each code
comes from rather than the shared "head shell" feature name, which is the
convention every other multi-module catalog in this package follows. The
"zh-CN" text below is the original wording each site used to hardcode,
carried over verbatim; "en" is a faithful translation, not a paraphrase.

A few raise sites take a human-readable "name" describing which value failed
(e.g. `finite_vector`'s `name` parameter, `main_component`'s `name`
parameter). Where that name is itself a natural-language phrase (not a
technical field/part identifier), the call site renders its own
`head_shell.name_*` code first and passes the *already-rendered* text in,
so the outer message is fully localized end to end; where the name is a
technical identifier already chosen by the user/recipe (a component name, an
STL part name), it is passed through unrendered, the same way
`generated_editing.coordinate()` passes its `key` parameter through.

Imported (for its `register()` side effect) from `studio/core/__init__.py`.
"""

from studio.i18n import register

register(
    {
        # --- head_shell.py (CATALOG) ---
        "head_shell.check_head_fit_note_measured": {
            "zh-CN": "几何包络不能替代真人试戴、衬垫和视线验证",
            "en": "A geometric envelope does not replace a real fitting, padding and sight verification",
        },
        "head_shell.check_physical_fit_detail_todo": {
            "zh-CN": "未真人试戴、未打印配合试片、未验证通风量",
            "en": "Not fitted on a person, no fit coupon printed, ventilation not verified",
        },
        "head_shell.shell_kit_description": {
            "zh-CN": (
                "保留源外形，内缩掏空、前后分片、颈口与成对磁铁座。可保留已明确的独立分色部件；尺寸可回改。"
                "佩戴适配、视线及实物配合须另验。"
            ),
            "en": (
                "Keeps the original shape and hollows it inward, splits it into a front and back shell, and "
                "adds a neck opening and paired magnet sockets. Already-declared independent colour "
                "components can be kept; dimensions can be rebuilt. Wearer fit, sightline, and physical fit "
                "still need separate verification."
            ),
        },
        "head_shell.shell_kit_label_head_circumference_mm": {
            "zh-CN": "头围 mm",
            "en": "Head circumference (mm)",
        },
        "head_shell.shell_kit_label_head_height_mm": {
            "zh-CN": "暂定头高 mm",
            "en": "Provisional head height (mm)",
        },
        "head_shell.shell_kit_label_insert_clearance_mm": {
            "zh-CN": "分色安装余量 mm",
            "en": "Colour-insert fitting clearance (mm)",
        },
        "head_shell.shell_kit_label_magnet_clearance_mm": {
            "zh-CN": "磁铁孔直径余量 mm",
            "en": "Magnet hole diameter clearance (mm)",
        },
        "head_shell.shell_kit_label_magnet_diameter_mm": {
            "zh-CN": "磁铁直径 mm",
            "en": "Magnet diameter (mm)",
        },
        "head_shell.shell_kit_label_magnet_pairs": {
            "zh-CN": "磁铁对数",
            "en": "Magnet pairs",
        },
        "head_shell.shell_kit_label_magnet_thickness_mm": {
            "zh-CN": "磁铁厚度 mm",
            "en": "Magnet thickness (mm)",
        },
        "head_shell.shell_kit_label_neck_depth_mm": {
            "zh-CN": "颈口前后长 mm",
            "en": "Neck opening depth (mm)",
        },
        "head_shell.shell_kit_label_neck_top_mm": {
            "zh-CN": "颈口通道高度 mm",
            "en": "Neck channel height (mm)",
        },
        "head_shell.shell_kit_label_neck_width_mm": {
            "zh-CN": "颈口左右宽 mm",
            "en": "Neck opening width (mm)",
        },
        "head_shell.shell_kit_label_padding_mm": {
            "zh-CN": "单侧衬垫余量 mm",
            "en": "Per-side padding allowance (mm)",
        },
        "head_shell.shell_kit_label_preserve_components": {
            "zh-CN": "保留来源独立部件",
            "en": "Keep independent source components",
        },
        "head_shell.shell_kit_label_preserve_eye_outline": {
            "zh-CN": "保护原眼轮廓（默认）",
            "en": "Protect the original eye outline (default)",
        },
        "head_shell.shell_kit_label_seam_gap_mm": {
            "zh-CN": "合壳间隙 mm",
            "en": "Shell seam gap (mm)",
        },
        "head_shell.shell_kit_label_split_y_mm": {
            "zh-CN": "前后分界 Y · mm",
            "en": "Front/back split Y (mm)",
        },
        "head_shell.shell_kit_label_target_width_mm": {
            "zh-CN": "总宽度（含耳）mm",
            "en": "Total width including ears (mm)",
        },
        "head_shell.shell_kit_label_voxel_mm": {
            "zh-CN": "内壁采样间距 mm",
            "en": "Interior wall sampling pitch (mm)",
        },
        "head_shell.shell_kit_title": {
            "zh-CN": "角色头壳 · 掏空与磁吸分壳",
            "en": "Character head shell - hollowing and magnetic split shells",
        },
        # --- head_shell.py (raises) ---
        "head_shell.cavity_grid_too_large": {
            "zh-CN": "内壁网格超过 8000 万格，请增加 voxel_mm 或减小尺寸",
            "en": "The interior wall grid exceeds 80 million cells; increase voxel_mm or reduce the size",
        },
        "head_shell.cavity_removes_component": {
            "zh-CN": "内腔/开孔将部件 {i} 完全移除",
            "en": "The cavity/opening removes component {i} entirely",
        },
        # --- head_shell.py (report.workflow_checks[*].detail / head_fit.note: read back and
        # displayed live by studio.core.task_recipe_progress.view(), so — unlike the rest of
        # this module's report.json fields — these follow the request/process language) ---
        "head_shell.check_geometry_detail_needs_review": {
            "zh-CN": "{count} 件水密；装配路径离散检查仍有待复核项",
            "en": "{count} watertight parts; the discrete assembly-path check still has items to review",
        },
        "head_shell.check_geometry_detail_pass": {
            "zh-CN": "{count} 件水密；装配路径离散检查通过，实物配合待验",
            "en": "{count} watertight parts; the discrete assembly-path check passed, physical fit still needs verification",
        },
        "head_shell.check_head_fit_detail_clear": {
            "zh-CN": "声明的头部包络无干涉；不等于真人适配",
            "en": "The declared head envelope has no interference; this is not the same as an actual wearer fit",
        },
        "head_shell.check_head_fit_detail_unclear": {
            "zh-CN": "头部包络干涉或尺寸尚未声明",
            "en": "The head envelope interferes, or its dimensions have not been declared",
        },
        "head_shell.check_head_fit_note_not_measured": {
            "zh-CN": "没有佩戴者尺寸，不能确认适配",
            "en": "No wearer dimensions were supplied; fit cannot be confirmed",
        },
        "head_shell.check_sight_detail_blocked": {
            "zh-CN": "视线被遮挡或未检查，不能作为可佩戴终稿",
            "en": "The sightline is blocked or was not checked; this cannot be treated as a final wearable draft",
        },
        "head_shell.check_sight_detail_clear": {
            "zh-CN": "暂定眼点正前方射线通达；实际视野待试戴",
            "en": "The forward ray from the provisional eye point is clear; actual field of view still needs a real try-on",
        },
        "head_shell.color_must_be_hex": {
            "zh-CN": "颜色须为 #RRGGBB",
            "en": "Colour must be #RRGGBB",
        },
        "head_shell.component_name_must_be_ascii_unique": {
            "zh-CN": "部件名称须唯一且为 ASCII 字母、数字、横线",
            "en": "Component names must be unique and use only ASCII letters, digits, and hyphens",
        },
        "head_shell.component_names_require_source_sha": {
            "zh-CN": "自定义部件名称和颜色必须绑定 source_sha256",
            "en": "Custom component names and colours must be bound to source_sha256",
        },
        "head_shell.convex_socket_expansion_exceeds_limit": {
            "zh-CN": "凸形安装槽扩张超过源部件体积的 5%，需要另设计接口",
            "en": "The convex mounting socket expands more than 5% of the source component's volume; design a different interface",
        },
        "head_shell.decorative_clearance_insufficient": {
            "zh-CN": "分色件 {name} 实际间隙不足：{distance} mm",
            "en": "Colour component {name} has insufficient actual clearance: {distance} mm",
        },
        "head_shell.eye_outline_protected_no_extension": {
            "zh-CN": "原眼轮廓受保护：不能扩展内眼角；先核对佩戴位置或明确允许改变外观",
            "en": (
                "The original eye outline is protected: the inner eye corner cannot be extended; check the "
                "wearing position first or explicitly allow changing the appearance"
            ),
        },
        "head_shell.finite_vector_required": {
            "zh-CN": "{name} 必须为有限数值向量",
            "en": "{name} must be a finite numeric vector",
        },
        "head_shell.head_envelope_dims_must_be_positive": {
            "zh-CN": "头部包络尺寸须为正",
            "en": "Head envelope dimensions must be positive",
        },
        "head_shell.highlight_protected_component_invalid": {
            "zh-CN": "高光保护部件索引无效",
            "en": "Highlight-protected component index is invalid",
        },
        "head_shell.insertion_axis_cannot_be_zero": {
            "zh-CN": "分色件装入轴不能为零",
            "en": "The colour insert's insertion axis cannot be zero",
        },
        "head_shell.insufficient_hidden_magnet_sites": {
            "zh-CN": "找不到足够且不露出外表面的磁铁座，请调整分界",
            "en": "Could not find enough magnet sites that stay hidden under the exterior surface; adjust the split",
        },
        "head_shell.invalid_body_index": {
            "zh-CN": "无效主体索引",
            "en": "Invalid body component index",
        },
        "head_shell.magnet_pairs_range": {
            "zh-CN": "magnet_pairs 须为 2–8 整数",
            "en": "magnet_pairs must be an integer from 2 to 8",
        },
        "head_shell.magnet_site_count_mismatch": {
            "zh-CN": "磁铁座坐标数量不匹配",
            "en": "The number of magnet site coordinates does not match",
        },
        "head_shell.magnet_site_exposed": {
            "zh-CN": "磁铁座露出源外表面",
            "en": "A magnet site is exposed on the source exterior surface",
        },
        "head_shell.magnet_site_spacing_insufficient": {
            "zh-CN": "磁铁座间距不足",
            "en": "Magnet site spacing is insufficient",
        },
        "head_shell.main_component_fragment_count": {
            "zh-CN": "{name} 产生 {count} 个实体，体积 {volumes}，边界 {bounds}",
            "en": "{name} produced {count} solids, volumes {volumes}, bounds {bounds}",
        },
        "head_shell.mesh_eyes_invalid_component_index": {
            "zh-CN": "眼网部件索引无效",
            "en": "Eye-mesh component index is invalid",
        },
        "head_shell.mesh_eyes_params_must_be_object": {
            "zh-CN": "眼网参数必须为对象",
            "en": "Eye-mesh parameters must be an object",
        },
        "head_shell.mesh_eyes_require_preserve_and_sha": {
            "zh-CN": "眼网需要保留分件并绑定 source_sha256",
            "en": "The eye mesh requires preserving split components and binding source_sha256",
        },
        "head_shell.mouth_slit_not_connected_to_cavity": {
            "zh-CN": "嘴缝没有连接内腔",
            "en": "The mouth slit is not connected to the interior cavity",
        },
        "head_shell.name_back_shell": {
            "zh-CN": "后壳",
            "en": "back shell",
        },
        "head_shell.name_decorative_part": {
            "zh-CN": "分色件 {i}",
            "en": "colour component {i}",
        },
        "head_shell.name_front_shell": {
            "zh-CN": "前壳",
            "en": "front shell",
        },
        "head_shell.name_head_envelope_center": {
            "zh-CN": "头部包络中心",
            "en": "head envelope center",
        },
        "head_shell.name_head_envelope_dims": {
            "zh-CN": "头部包络尺寸",
            "en": "head envelope dimensions",
        },
        "head_shell.name_insertion_direction": {
            "zh-CN": "分色件装入轴",
            "en": "colour insert insertion axis",
        },
        "head_shell.name_port_center": {
            "zh-CN": "通孔中心",
            "en": "port center",
        },
        "head_shell.name_port_size": {
            "zh-CN": "通孔宽高",
            "en": "port width/height",
        },
        "head_shell.neck_not_connected_to_cavity": {
            "zh-CN": "颈口通道没有连通内腔，请增加 neck_top_mm",
            "en": "The neck channel is not connected to the interior cavity; increase neck_top_mm",
        },
        "head_shell.normal_offset_does_not_enclose_source": {
            "zh-CN": "分色件法向偏移不能完整包住原实体，需要显式安装槽",
            "en": "The colour component's normal offset does not fully enclose the original solid; an explicit mounting socket is needed",
        },
        "head_shell.parts_intersect": {
            "zh-CN": "零件静态相交 {collisions}",
            "en": "Parts statically intersect {collisions}",
        },
        "head_shell.port_size_must_be_positive": {
            "zh-CN": "通孔尺寸必须为正",
            "en": "Port size must be positive",
        },
        "head_shell.preserve_components_must_be_bool": {
            "zh-CN": "preserve_components 必须为布尔值",
            "en": "preserve_components must be a boolean",
        },
        "head_shell.preserve_eye_outline_must_be_bool": {
            "zh-CN": "preserve_eye_outline 必须为布尔值",
            "en": "preserve_eye_outline must be a boolean",
        },
        "head_shell.seam_insufficient_magnet_space": {
            "zh-CN": "接缝没有足够磁铁安装空间",
            "en": "The seam does not have enough room to mount magnets",
        },
        "head_shell.shell_insertion_path_interferes": {
            "zh-CN": "前后壳装入路径干涉",
            "en": "The front/back shell insertion path interferes",
        },
        "head_shell.shell_material_loss_opt_in_required": {
            "zh-CN": "壳体加工不保留贴图，需要明确 allow_material_loss",
            "en": "Shell machining does not preserve textures; allow_material_loss must be explicitly enabled",
        },
        "head_shell.source_component_count_range": {
            "zh-CN": "源连通部件须为 1–64 件",
            "en": "Source connected components must number from 1 to 64",
        },
        "head_shell.source_component_must_be_closed_solid": {
            "zh-CN": "源部件必须为闭合且法向一致的正体积；不隐式修复",
            "en": "Source components must be closed, consistently-oriented, positive-volume solids; no implicit repair",
        },
        "head_shell.source_file_required": {
            "zh-CN": "需要一个静态 GLB/STL/PLY 源文件",
            "en": "One static GLB/STL/PLY source file is required",
        },
        "head_shell.source_sha_mismatch": {
            "zh-CN": "来源 SHA256 与部件计划不匹配",
            "en": "The source SHA256 does not match the component plan",
        },
        "head_shell.split_coordinate_must_be_finite": {
            "zh-CN": "分界坐标必须有限",
            "en": "The split coordinate must be finite",
        },
        "head_shell.split_must_cross_body": {
            "zh-CN": "分界必须穿过主体",
            "en": "The split must cross the body component",
        },
        "head_shell.split_outline_not_closed_loop": {
            "zh-CN": "分界轮廓不是有效闭环",
            "en": "The split outline is not a valid closed loop",
        },
        "head_shell.split_plane_does_not_cross_body": {
            "zh-CN": "前后分界没有穿过主体",
            "en": "The front/back split plane does not cross the body component",
        },
        "head_shell.stl_readback_not_single_watertight": {
            "zh-CN": "STL 导出读回不是单体水密 {name}",
            "en": "STL export read-back is not a single watertight solid: {name}",
        },
        "head_shell.stl_readback_volume_changed": {
            "zh-CN": "STL 读回体积变化 {name}",
            "en": "STL read-back volume changed: {name}",
        },
        "head_shell.voxel_mm_exceeds_half_wall": {
            "zh-CN": "voxel_mm 不得大于壁厚的一半",
            "en": "voxel_mm must not exceed half the wall thickness",
        },
        "head_shell.wall_too_thick_no_cavity": {
            "zh-CN": "壁厚过大，没有内腔",
            "en": "The wall is too thick; there is no interior cavity",
        },
        # --- head_shell_audit.py ---
        "head_shell_audit.stl_not_single_watertight": {
            "zh-CN": "STL 未通过单体水密读回 {name}",
            "en": "STL failed the single watertight read-back: {name}",
        },
        "head_shell_audit.ungrouped_parts_need_two_groups": {
            "zh-CN": "部件 {name} 未归入任何分组，且声明的分组少于两个，无法按位置自动分派",
            "en": "Part {name} is not in any declared group, and fewer than two groups were declared, so it cannot be auto-assigned by position",
        },
        # --- head_shell_vision.py ---
        "head_shell_vision.eye_extension_outline_invalid": {
            "zh-CN": "内眼角轮廓必须简单闭合且面积足够",
            "en": "The inner-eye-corner outline must be a simple closed shape with sufficient area",
        },
        "head_shell_vision.eye_extension_outline_needs_points": {
            "zh-CN": "内眼角轮廓需要至少三个有限 XZ 点",
            "en": "The inner-eye-corner outline needs at least three finite XZ points",
        },
        "head_shell_vision.eye_screen_export_not_watertight": {
            "zh-CN": "眼片在 GLB 精度下不能保持单体水密",
            "en": "The eye screen cannot stay a single watertight solid at GLB precision",
        },
        "head_shell_vision.eye_screen_export_volume_changed": {
            "zh-CN": "眼片导出稳定化导致体积变化过大",
            "en": "Eye screen export stabilization caused too large a volume change",
        },
        "head_shell_vision.eye_screen_insufficient_area": {
            "zh-CN": "眼网没有足够观察面积",
            "en": "The eye mesh does not have enough viewing area",
        },
        "head_shell_vision.eye_screen_no_valid_holes": {
            "zh-CN": "眼网没有有效网孔",
            "en": "The eye mesh has no valid holes",
        },
        "head_shell_vision.eye_screen_params_must_be_positive": {
            "zh-CN": "眼网参数必须为有限正数",
            "en": "Eye-mesh parameters must be finite positive numbers",
        },
        "head_shell_vision.eye_screen_params_out_of_range": {
            "zh-CN": "眼网筋宽/厚度或间距超出样稿范围",
            "en": "The eye mesh's bar width, thickness, or pitch is outside the draft's supported range",
        },
        "head_shell_vision.smile_vent_needs_points": {
            "zh-CN": "嘴缝必须为至少两个有限 XZ 点",
            "en": "A smile vent must have at least two finite XZ points",
        },
        "head_shell_vision.smile_vent_width_range": {
            "zh-CN": "嘴缝宽度须为 0.5–4 mm",
            "en": "Smile vent width must be 0.5-4 mm",
        },
        # --- head_shell_sight.py ---
        "head_shell_sight.eye_points_required": {
            "zh-CN": "需要两个明确且有限的人眼坐标",
            "en": "Two explicit, finite human eye coordinates are required",
        },
        # --- task_recipe_progress.py (raises) ---
        "task_recipe_progress.generation_task_recipe_mismatch": {
            "zh-CN": "生成任务与配方不匹配",
            "en": "The generation task does not match the recipe",
        },
        "task_recipe_progress.report_schema_mismatch": {
            "zh-CN": "检查报告类型不匹配",
            "en": "The check report's type does not match",
        },
        "task_recipe_progress.report_too_large": {
            "zh-CN": "检查报告超出大小限制",
            "en": "The check report exceeds the size limit",
        },
        # --- task_recipe_progress.py (detail / scope_note text) ---
        "task_recipe_progress.appearance_detail_awaiting_human": {
            "zh-CN": "已有版本对照；等待人工确认外观，AI 评价单独保留",
            "en": "A version comparison already exists; awaiting human confirmation of appearance, the AI review is kept separate",
        },
        "task_recipe_progress.appearance_detail_human_review": {
            "zh-CN": "人工外观复核：{note}",
            "en": "Human appearance review: {note}",
        },
        "task_recipe_progress.check_detail_missing_evidence": {
            "zh-CN": "此版本缺少检查证据",
            "en": "This version is missing check evidence",
        },
        "task_recipe_progress.evidence_unavailable": {
            "zh-CN": "证据不可用：{error}",
            "en": "Evidence unavailable: {error}",
        },
        "task_recipe_progress.generate_detail_incomplete": {
            "zh-CN": "生成未完成，请查看运行记录",
            "en": "Generation did not complete; check the run log",
        },
        "task_recipe_progress.generate_detail_pass": {
            "zh-CN": "已生成可调样稿；不等于可佩戴验收",
            "en": "An adjustable draft has been generated; this is not a wearable acceptance",
        },
        "task_recipe_progress.generate_detail_running": {
            "zh-CN": "正在生成；检查结果尚未产生",
            "en": "Generating; check results are not available yet",
        },
        "task_recipe_progress.prepare_detail_recorded": {
            "zh-CN": "输入与参数已记录到此生成版本",
            "en": "The input and parameters have been recorded for this generation version",
        },
        "task_recipe_progress.scope_note": {
            "zh-CN": "检查绑定此生成版本。真人试戴、配合试片和通风量另验。",
            "en": (
                "These checks are bound to this generation version. Actual wearer fit, fit-test coupons, and "
                "ventilation still need separate verification."
            ),
        },
    }
)
