"""Message catalog for `studio.core.{tasks,task_templates,task_operations,
blender_catalog,task_worker}` raises, plus the CATALOG display fields of
those modules and of `generated_editing.py` / `assembly_review.py` (their
non-CATALOG raise sites are converted by other catalogs).

One entry per `EditorError.coded()` call site, per `render()`-wrapped
`RuntimeError`/`ValueError` raise, and per CATALOG `title`/`description`/
`labels` value/`choices` display label in the modules above. `CATALOG` is a
module-level list built once at import time, so it cannot itself follow the
per-request language; producer modules store message codes in those display
fields instead, and `task_templates.localized_catalog()` renders them at the
point a request actually needs them (see that module's docstring).

Codes are `<module>.<meaning>`, lower snake_case, and become part of the
public error/response contract once released: never repurpose or delete one,
only add. The "zh-CN" text below is the original wording each site used to
hardcode, carried over verbatim; "en" is a faithful translation, not a
paraphrase. A few call sites were English-only before this conversion (e.g.
most of `task_operations.py`'s `ValueError`s, and `tasks.blender_not_found`);
those get a new Chinese translation here.

One raise site is deliberately left unconverted: `task_operations.py`'s
`Hotspot position requires finite XYZ metre coordinates` (in
`interactive_scene()`). `tests/test_task_operations.py` asserts
`pytest.raises(ValueError, match="finite XYZ")` under the suite's pinned
`STUDIO_LANG=zh-CN`, and a faithful Chinese translation would not contain
that English phrase; converting it would either break the test or force an
unnatural "zh-CN" string that fakes an English fragment just to pass. Every
other raise site in this module's scope is converted.

Imported (for its `register()` side effect) from `studio/core/__init__.py`,
so every code here is registered as soon as anything under `studio.core` is
imported -- before any of these modules' functions can call
`EditorError.coded()` / `studio.i18n.render()`.
"""

from studio.i18n import register

register(
    {
        # --- assembly_review.py (CATALOG only; the rest of the module is
        # converted by another catalog) ---
        "assembly_review.a8_review_description": {
            "zh-CN": (
                "输入原 cases.json / cases.js 或 catalog_registry.json 路径。保留关节与审计事实，支持开合、"
                "逐关节、轴向、炸开、原材质。一次最多 8 案；G/B 标记需导出保存。"
            ),
            "en": (
                "Provide the original cases.json / cases.js or catalog_registry.json path. Preserves joints "
                "and audit facts; supports open/close, per-joint, axis, explode, and original materials views. "
                "At most 8 cases at a time; G/B marks must be exported to be saved."
            ),
        },
        "assembly_review.a8_review_label_batch_id": {
            "zh-CN": "批次 ID（registry 默认批次可留空）",
            "en": "Batch ID (leave empty for the registry's default batch)",
        },
        "assembly_review.a8_review_label_case_ids": {
            "zh-CN": "案 ID（逗号分隔，空为前 8 案）",
            "en": "Case IDs (comma-separated; empty means the first 8 cases)",
        },
        "assembly_review.a8_review_label_compare_case_id": {
            "zh-CN": "对照案 ID（须包含在选定案中，可留空）",
            "en": "Comparison case ID (must be one of the selected cases; may be left empty)",
        },
        "assembly_review.a8_review_label_parts_dir": {
            "zh-CN": "parts 目录（registry 输入可留空）",
            "en": "parts directory (leave empty for a registry input)",
        },
        "assembly_review.a8_review_title": {
            "zh-CN": "A8 机构审阅",
            "en": "A8 mechanism review",
        },
        "assembly_review.merge_review_choice_units_m": {
            "zh-CN": "米（glTF 标准）",
            "en": "Metres (glTF standard)",
        },
        "assembly_review.merge_review_choice_units_mm": {
            "zh-CN": "毫米（旧 merge 数据）",
            "en": "Millimetres (legacy merge data)",
        },
        "assembly_review.merge_review_description": {
            "zh-CN": (
                "输入 merge_ui 的 manifest.json 原路径。炸开、编号、材质、X-ray；输出 parts.glb 可接回编辑，"
                "继续合并、拆分和撤销。两个 manifest 可并排对照。"
            ),
            "en": (
                "Provide merge_ui's original manifest.json path. Explode, number, material, and X-ray views; "
                "the output parts.glb can be imported back into the editor to keep merging, splitting, and "
                "undoing. Two manifests can be compared side by side."
            ),
        },
        "assembly_review.merge_review_label_title": {
            "zh-CN": "标题",
            "en": "Title",
        },
        "assembly_review.merge_review_label_units": {
            "zh-CN": "源 GLB 坐标单位",
            "en": "Source GLB coordinate unit",
        },
        "assembly_review.merge_review_title": {
            "zh-CN": "Merge 拆件工作区",
            "en": "Merge part-splitting workspace",
        },
        # --- blender_catalog.py ---
        "blender_catalog.hair_cards_description": {
            "zh-CN": (
                "高级参数 guides 指定米制引导点、width_mm 和可选 atlas_uv；可输入纹理图集，交付可编辑发片和引导 JSON"
            ),
            "en": (
                "The advanced guides parameter specifies metre-scale guide points, width_mm, and an optional "
                "atlas_uv; a texture atlas may be provided as input. Delivers editable hair cards plus a guide "
                "JSON"
            ),
        },
        "blender_catalog.hair_cards_title": {
            "zh-CN": "引导线生成发片",
            "en": "Generate hair cards from guide curves",
        },
        "blender_catalog.local_sculpt_description": {
            "zh-CN": ("仅处理显式球形区域，保留外部顶点、拓扑与 UV；高级参数 center_m 为世界米坐标，适合局部瑕疵清理"),
            "en": (
                "Only processes an explicit spherical region, preserving vertices, topology, and UVs outside "
                "it; the advanced center_m parameter is a world-space metre coordinate, suited to local defect "
                "cleanup"
            ),
        },
        "blender_catalog.local_sculpt_title": {
            "zh-CN": "局部保形光顺",
            "en": "Local shape-preserving smoothing",
        },
        "blender_catalog.motion_retarget_description": {
            "zh-CN": (
                "先输入动作源，再输入目标角色；高级参数 bone_map 显式映射骨名。按 rest pose 补偿旋转并烘焙目标动作"
            ),
            "en": (
                "Provide the motion source first, then the target character; the advanced bone_map parameter "
                "explicitly maps bone names. Compensates rotation against the rest pose and bakes the "
                "retargeted motion"
            ),
        },
        "blender_catalog.motion_retarget_title": {
            "zh-CN": "动作重定向",
            "en": "Motion retargeting",
        },
        "blender_catalog.rig_bind_description": {
            "zh-CN": ("使用 Blender 自动权重；高级参数 bones 指定骨名、父骨、head/tail 米坐标，绑定后检查漏绑顶点"),
            "en": (
                "Uses Blender's automatic weights; the advanced bones parameter specifies bone names, parent "
                "bones, and head/tail metre coordinates. Checks for unweighted vertices after binding"
            ),
        },
        "blender_catalog.rig_bind_title": {
            "zh-CN": "按骨架绑定网格",
            "en": "Bind mesh to a skeleton",
        },
        "blender_catalog.scene_render_description": {
            "zh-CN": "载入 Blender / GLB 场景，保留相机、灯光与材质，输出可编辑工程和预览",
            "en": (
                "Loads a Blender / GLB scene, preserving cameras, lights, and materials; outputs an editable "
                "project and a preview"
            ),
        },
        "blender_catalog.scene_render_title": {
            "zh-CN": "渲染已有工程",
            "en": "Render an existing project",
        },
        "blender_catalog.skin_weights_description": {
            "zh-CN": "保留骨架和动画，限制影响骨骼数并归一化；无骨骼或漏绑顶点会明确报错",
            "en": (
                "Preserves the skeleton and animation, caps and normalizes the number of influencing bones; "
                "raises a clear error for missing bones or unweighted vertices"
            ),
        },
        "blender_catalog.skin_weights_title": {
            "zh-CN": "修复蒙皮权重",
            "en": "Repair skin weights",
        },
        "blender_catalog.surface_fit_description": {
            "zh-CN": "以第二个输入作为模板，通过 Blender Shrinkwrap 拟合到第一个输入；保持模板拓扑和 UV",
            "en": (
                "Uses the second input as a template and fits it onto the first input via Blender's "
                "Shrinkwrap; preserves the template's topology and UVs"
            ),
        },
        "blender_catalog.surface_fit_title": {
            "zh-CN": "模板表面拟合",
            "en": "Template surface fitting",
        },
        "blender_catalog.texture_bake_description": {
            "zh-CN": "从原高模烘焙低模底色和切线法线，生成新的 UV 和可编辑工程，原输入文件不变",
            "en": (
                "Bakes base color and tangent-space normals from the original high-poly mesh onto a decimated "
                "low-poly mesh, generating new UVs and an editable project; the original input files are "
                "unchanged"
            ),
        },
        "blender_catalog.texture_bake_title": {
            "zh-CN": "减面并烘焙贴图",
            "en": "Decimate and bake textures",
        },
        "blender_catalog.turntable_description": {
            "zh-CN": "为场景添加独立的旋转父级，不改网格与材质；交付动画 GLB 与 Blender 工程",
            "en": (
                "Adds an independent rotating parent to the scene without changing meshes or materials; "
                "delivers an animated GLB and a Blender project"
            ),
        },
        "blender_catalog.turntable_title": {
            "zh-CN": "模型旋转展示",
            "en": "Turntable display",
        },
        # --- generated_editing.py (CATALOG only) ---
        "generated_editing.axis_must_be_xyz": {
            "zh-CN": "axis 为 x/y/z",
            "en": "axis must be x, y or z",
        },
        "generated_editing.cavity_does_not_fit_source": {
            "zh-CN": "要求的内腔与壁厚放不进源外形（缺少 {loss} mm³），请调整尺寸或位置",
            "en": "The requested cavity and wall thickness do not fit inside the source shape ({loss} mm³ short); adjust the size or position",
        },
        "generated_editing.cavity_requires_connected_solid": {
            "zh-CN": "内腔加工需要一个连通实体",
            "en": "Cavity machining needs one connected solid",
        },
        "generated_editing.control_plane_cuts_triangle": {
            "zh-CN": "控制平面穿过三角形内部；请在已有截面顶点位置设平面，或先细分网格",
            "en": "The control plane cuts through a triangle; place it at an existing section vertex or subdivide the mesh first",
        },
        "generated_editing.control_plane_outside_model": {
            "zh-CN": "控制平面必须位于模型范围内",
            "en": "The control plane must lie inside the model bounds",
        },
        "generated_editing.disconnected_fragments": {
            "zh-CN": "{name} 出现断开的碎片，请调整加工参数",
            "en": "{name} has disconnected fragments; adjust the machining parameters",
        },
        "generated_editing.finite_mm_coordinate_required": {
            "zh-CN": "{key} 必须是有限毫米坐标，绝对值不超过 100000",
            "en": "{key} must be a finite millimetre coordinate with absolute value at most 100000",
        },
        "generated_editing.generated_container_description": {
            "zh-CN": (
                "保留原外形，在闭合实体内加工矩形内腔、可拆盖、定位唇与抽取开口。毫米/Z-up；原始输入冻结，可修改"
                "参数重建。输出加工件为纯色；带贴图时须明确允许。"
            ),
            "en": (
                "Keeps the original shape and machines a rectangular cavity, a removable lid, a locating lip, "
                "and a draw opening into the closed solid. Millimetres/Z-up; the original input is frozen and "
                "can be rebuilt by changing parameters. Machined output is flat-colored; a textured source "
                "requires explicit opt-in."
            ),
        },
        "generated_editing.generated_container_title": {
            "zh-CN": "生成模型 → 可调内腔与盖子",
            "en": "Generated model -> adjustable cavity and lid",
        },
        "generated_editing.lip_or_opening_outside_cavity": {
            "zh-CN": "定位唇或开口超出内腔范围，请减小壁厚、间隙或开口",
            "en": "The locating lip or opening exceeds the cavity; reduce the wall thickness, clearance or opening",
        },
        "generated_editing.local_dimensions_choice_axis_x": {
            "zh-CN": "X",
            "en": "X",
        },
        "generated_editing.local_dimensions_choice_axis_y": {
            "zh-CN": "Y",
            "en": "Y",
        },
        "generated_editing.local_dimensions_choice_axis_z": {
            "zh-CN": "Z",
            "en": "Z",
        },
        "generated_editing.local_dimensions_description": {
            "zh-CN": (
                "沿指定轴拉长两个已有网格截面之间的区域：起始侧固定，终止侧刚性平移，中间线性伸缩。保留拓扑、"
                "UV、材质；控制平面不能穿过三角形内部，不自动识别语义。"
            ),
            "en": (
                "Stretches the region between two existing mesh cross-sections along the given axis: the "
                "start side stays fixed, the end side translates rigidly, and the region in between scales "
                "linearly. Preserves topology, UVs, and materials; a control plane must not pass through a "
                "triangle's interior, and no semantics are inferred automatically."
            ),
        },
        "generated_editing.local_dimensions_title": {
            "zh-CN": "局部尺寸 · 保形拉长",
            "en": "Local dimensions - shape-preserving stretch",
        },
        # --- task_operations.py ---
        "generated_editing.material_loss_opt_in_required": {
            "zh-CN": "加工会转为纯色网格；请明确启用 allow_material_loss，原模型保留",
            "en": "Machining converts the model to a plain-colour mesh; enable allow_material_loss explicitly (the original is kept)",
        },
        "generated_editing.region_needs_positive_length": {
            "zh-CN": "区域必须有正长度，修改后不能折叠或反转",
            "en": "The region must have a positive length and must not fold or invert after the edit",
        },
        "generated_editing.single_object_required": {
            "zh-CN": "需要恰好一个模型对象；请从编辑器选中一件作为输入",
            "en": "Exactly one model object is required; select one in the editor as the input",
        },
        "generated_editing.static_model_required": {
            "zh-CN": "请选择一个静态 GLB/STL/PLY 模型；多件先明确需要加工的对象",
            "en": "Select one static GLB/STL/PLY model; with several parts, first specify which object to machine",
        },
        "generated_editing.stl_readback_failed": {
            "zh-CN": "STL 导出读回未通过：{name}",
            "en": "STL export read-back failed: {name}",
        },
        "generated_editing.structure_intersects_envelope": {
            "zh-CN": "生成结构与内装包络或配合件相交：{checks}",
            "en": "The generated structure intersects the interior envelope or a mating part: {checks}",
        },
        "generated_editing.unexpected_topology_change": {
            "zh-CN": "拓扑发生意外变化",
            "en": "Unexpected topology change",
        },
        "task_operations.asset_preview_description": {
            "zh-CN": "保留原文件与动画，加入工作台任务预览",
            "en": "Keeps the original file and animation, adding it to the workbench task preview",
        },
        "task_operations.asset_preview_requires_glb": {
            "zh-CN": "至少需要一个 GLB",
            "en": "At least one GLB is required",
        },
        "task_operations.asset_preview_title": {
            "zh-CN": "打开动画或静态 GLB",
            "en": "Open an animated or static GLB",
        },
        "task_operations.assembly_audit_description": {
            "zh-CN": (
                "对闭合部件做实体相交检查；高级参数 motions 指定轴、轴心和范围。单个输入为 URDF 时改为按其自身关节"
                "定义联动扫掠：所有可动关节沿关节空间对角线同时、线性地从下限走到上限（一条直线，不是遍历所有"
                "组合），只在混合姿态下才出现的碰撞不在覆盖范围内；joint_ranges 覆盖值须用各关节自身的原生单位"
                "（转动/连续关节为弧度，移动关节为米）。报告列出每个采样姿态的碰撞"
            ),
            "en": (
                "Runs solid-intersection checks on closed parts; the advanced motions parameter specifies "
                "axis, pivot, and range. When the single input is a URDF, it instead sweeps that URDF's own "
                "joint definitions together: every actuated joint moves simultaneously and linearly from its "
                "lower to upper limit along the diagonal of joint-configuration space (one straight line, not "
                "every combination), so a collision that only happens at a mixed configuration is not covered; "
                "joint_ranges overrides must be given in each joint's own native unit (radians for "
                "revolute/continuous, metres for prismatic). The report lists collisions at every sampled pose"
            ),
        },
        "task_operations.assembly_audit_title": {
            "zh-CN": "装配与运动干涉检查",
            "en": "Assembly and motion interference check",
        },
        "task_operations.audit_invalid_motion_plan": {
            "zh-CN": "无效的运动计划",
            "en": "Invalid motion plan",
        },
        "task_operations.audit_invalid_motion_transform": {
            "zh-CN": "无效的运动变换",
            "en": "Invalid motion transform",
        },
        "task_operations.audit_motion_type_invalid": {
            "zh-CN": "运动类型须为 revolute/prismatic",
            "en": "Motion type must be revolute/prismatic",
        },
        "task_operations.audit_object_names_must_be_unique": {
            "zh-CN": "各输入间的对象名必须唯一",
            "en": "Object names must be unique across inputs",
        },
        "task_operations.audit_requires_2_to_40_solids": {
            "zh-CN": "检查需要 2–40 个闭合实体",
            "en": "The audit requires 2-40 closed solids",
        },
        "task_operations.audit_requires_single_urdf_input": {
            "zh-CN": "URDF 模式只能有一个输入文件",
            "en": "URDF mode takes exactly one input file",
        },
        "task_operations.audit_urdf_continuous_needs_range": {
            "zh-CN": "连续关节 {name} 须通过 joint_ranges 指定扫掠范围",
            "en": "Continuous joint {name} needs a swept range from joint_ranges",
        },
        "task_operations.audit_urdf_invalid_joint_ranges": {
            "zh-CN": "joint_ranges 须为 {关节名: [下限, 上限]}，且关节须为可动关节、下限小于上限",
            "en": "joint_ranges must be {joint_name: [lower, upper]}, naming an actuated joint with lower < upper",
        },
        "task_operations.cad_invalid_solid": {
            "zh-CN": "CAD 内核报告实体无效",
            "en": "CAD kernel reports an invalid solid",
        },
        "task_operations.cad_model_choice_operation_enclosure": {
            "zh-CN": "开口外壳",
            "en": "Open-top enclosure",
        },
        "task_operations.cad_model_choice_operation_extrude": {
            "zh-CN": "截面拉伸",
            "en": "Profile extrusion",
        },
        "task_operations.cad_model_choice_operation_revolve": {
            "zh-CN": "截面回转",
            "en": "Profile revolution",
        },
        "task_operations.cad_model_description": {
            "zh-CN": "以毫米参数构建实体，交付 STEP、STL 和 GLB；支持外壳、拉伸、回转",
            "en": "Builds a solid from millimetre parameters, delivering STEP, STL, and GLB; supports "
            "enclosure, extrude, and revolve",
        },
        "task_operations.cad_model_title": {
            "zh-CN": "精确 CAD 建模",
            "en": "Precise CAD modelling",
        },
        "task_operations.cad_profile_requires_finite_points": {
            "zh-CN": "profile_mm 须为有限的二维点",
            "en": "profile_mm must be finite 2D points",
        },
        "task_operations.cad_stl_readback_not_closed": {
            "zh-CN": "STL 读回不是闭合正体积网格",
            "en": "The STL readback is not a closed positive-volume mesh",
        },
        "task_operations.cad_unsupported_operation": {
            "zh-CN": "不支持的 CAD 操作",
            "en": "Unsupported CAD operation",
        },
        "task_operations.cad_wall_no_cavity": {
            "zh-CN": "壁厚导致内腔无可用空间",
            "en": "The wall thickness leaves no usable cavity",
        },
        "task_operations.face_split_description": {
            "zh-CN": "输入静态 GLB/STL 与标签 JSON，保留原三角形、UV、材质并验证面覆盖；不会推测语义标签",
            "en": (
                "Takes a static GLB/STL and a label JSON, preserving the original triangles, UVs, and "
                "materials while verifying face coverage; never guesses a semantic label"
            ),
        },
        "task_operations.face_split_every_face_needs_label": {
            "zh-CN": "每个源面都必须有一个非空标签",
            "en": "Every source face must have exactly one nonempty label",
        },
        "task_operations.face_split_labels_not_bound_to_source": {
            "zh-CN": "面标签未绑定到这份源文件精确的 SHA256",
            "en": "Face labels are not bound to this exact source's SHA256",
        },
        "task_operations.face_split_node_set_mismatch": {
            "zh-CN": "标签节点集合必须与场景完全一致",
            "en": "The label node set must exactly match the scene",
        },
        "task_operations.face_split_subset_changed_topology": {
            "zh-CN": "面子集改变了拓扑",
            "en": "The face subset changed topology",
        },
        "task_operations.face_split_title": {
            "zh-CN": "按面标签拆件",
            "en": "Split parts by face label",
        },
        "task_operations.glb_clips_conflicting_channels": {
            "zh-CN": "多个通道指向同一节点属性，产生冲突；请选择可同时播放的兼容片段",
            "en": (
                "Conflicting channels target the same node property; select compatible clips that can play "
                "simultaneously"
            ),
        },
        "task_operations.glb_clips_description": {
            "zh-CN": "合并同一 GLB 的动画通道；拒绝对同一节点同一属性的冲突写入",
            "en": "Merges animation channels within one GLB; rejects conflicting writes to the same node property",
        },
        "task_operations.glb_clips_no_animations": {
            "zh-CN": "输入没有动画",
            "en": "The input has no animations",
        },
        "task_operations.glb_clips_title": {
            "zh-CN": "合并同时播放的动画",
            "en": "Merge simultaneously-playing animations",
        },
        "task_operations.glb_invalid": {
            "zh-CN": "无效的 GLB",
            "en": "Invalid GLB",
        },
        "task_operations.glb_must_embed_resources": {
            "zh-CN": "GLB 必须内嵌全部 buffer 和图片",
            "en": "The GLB must embed all buffers and images",
        },
        "task_operations.image_relief_description": {
            "zh-CN": "将灰度高度图转换为带底板的闭合实体，交付 STL / GLB",
            "en": "Converts a grayscale height map into a closed solid with a base plate, delivering STL / GLB",
        },
        "task_operations.image_relief_title": {
            "zh-CN": "图片转几何浮雕",
            "en": "Image to geometric relief",
        },
        "task_operations.interactive_asset_over_100mb": {
            "zh-CN": "内嵌交付页面的素材须小于 100 MB",
            "en": "Assets for an embedded delivery page must be under 100 MB",
        },
        "task_operations.interactive_hotspot_needs_label": {
            "zh-CN": "每个热点都需要 label",
            "en": "Each hotspot needs a label",
        },
        "task_operations.interactive_hotspots_max_100": {
            "zh-CN": "hotspots 最多包含 100 个标记",
            "en": "hotspots must contain at most 100 markers",
        },
        "task_operations.interactive_requires_glb_files": {
            "zh-CN": "请提供一个或多个自包含 GLB 文件",
            "en": "Supply one or more self-contained GLB files",
        },
        "task_operations.interactive_scene_description": {
            "zh-CN": ("交付可离线打开的 3D 页面，支持模型观察、动画、WASD 漫游与热点探索；高级参数 hotspots 定义标记"),
            "en": (
                "Delivers an offline-capable 3D page supporting model inspection, animation, WASD navigation, "
                "and hotspot exploration; the advanced hotspots parameter defines the markers"
            ),
        },
        "task_operations.interactive_scene_over_180mb": {
            "zh-CN": "内嵌场景超过 180 MB 交付上限",
            "en": "The embedded scene exceeds the 180 MB delivery limit",
        },
        "task_operations.interactive_scene_title": {
            "zh-CN": "交互成果网页",
            "en": "Interactive result webpage",
        },
        "task_operations.joint_coupon_choice_family_compact_pivot": {
            "zh-CN": "M2 销铰",
            "en": "M2 pin hinge",
        },
        "task_operations.joint_coupon_choice_family_thin_slew": {
            "zh-CN": "薄回转接口",
            "en": "Thin slew interface",
        },
        "task_operations.joint_coupon_description": {
            "zh-CN": "复用 MDE 关节库，生成销铰或薄回转关节及毫米 STL，记录数字间隙和待实打项目",
            "en": (
                "Reuses the MDE joint library to generate a pin-hinge or thin-slew joint plus millimetre STL, "
                "recording the digital clearance and items still pending a physical print"
            ),
        },
        "task_operations.joint_coupon_title": {
            "zh-CN": "机械接口与试片",
            "en": "Mechanical interface and coupon",
        },
        "task_operations.joint_invalid_or_disconnected_coupon": {
            "zh-CN": "试片 {name} 无效或不连通",
            "en": "Coupon {name} is invalid or disconnected",
        },
        "task_operations.joint_rest_pose_intersecting": {
            "zh-CN": "静止姿态下实体相交",
            "en": "Solids intersect at the rest pose",
        },
        "task_operations.joint_unsupported_family": {
            "zh-CN": "不支持的关节族",
            "en": "Unsupported joint family",
        },
        "task_operations.laser_layer_count_range": {
            "zh-CN": "层数须为 1–500",
            "en": "The layer count must be 1-500",
        },
        "task_operations.laser_open_section": {
            "zh-CN": "开放截面不能用于激光切割",
            "en": "An open section cannot be sent for laser cutting",
        },
        "task_operations.laser_requires_closed_mesh": {
            "zh-CN": "激光切片需要闭合正体积网格",
            "en": "Laser slicing requires a closed positive-volume mesh",
        },
        "task_operations.laser_slices_description": {
            "zh-CN": "对闭合模型按层厚求截面，交付毫米 SVG、每层边界及层位记录",
            "en": (
                "Sections a closed model at the given layer thickness, delivering millimetre SVGs, each "
                "layer's boundary, and layer position records"
            ),
        },
        "task_operations.laser_slices_title": {
            "zh-CN": "分层激光切割",
            "en": "Layered laser cutting",
        },
        "task_operations.number_out_of_range": {
            "zh-CN": "{key} 须在 ({lower}, {upper}] 范围内",
            "en": "{key} must be in ({lower}, {upper}]",
        },
        "task_operations.relief_image_too_narrow": {
            "zh-CN": "输入图片过窄",
            "en": "The input image is too narrow",
        },
        "task_operations.relief_not_closed_solid": {
            "zh-CN": "浮雕未形成闭合实体",
            "en": "The relief did not form a closed solid",
        },
        "task_operations.relief_samples_range": {
            "zh-CN": "samples 须为 8–256",
            "en": "samples must be 8-256",
        },
        "task_operations.removal_audit_description": {
            "zh-CN": (
                "对任意一组水密 STL 部件做离散拆卸顺序检查，复用角色头壳的同一几何内核。groups 可声明分组"
                "（同名部件即该组固定主体），insertion_directions 声明优先尝试的拔出方向，"
                "radial_center_mm/split_axis/split_value_mm 控制未声明部件的自动分组"
            ),
            "en": (
                "Runs the discrete removal-order check on any set of watertight STL parts, reusing the head "
                "shell's own geometric core. groups declares membership (a part named the same as its group "
                "is that group's fixed host); insertion_directions declares a preferred pull-out direction per "
                "part; radial_center_mm/split_axis/split_value_mm control auto-assignment of undeclared parts"
            ),
        },
        "task_operations.removal_audit_invalid_groups": {
            "zh-CN": "groups 须为 {分组名: [已知部件名列表]}，且部件名须属于本次输入",
            "en": "groups must be {group_name: [known part names]}, naming only parts from this input",
        },
        "task_operations.removal_audit_invalid_insertion_directions": {
            "zh-CN": "insertion_directions 须为 {部件名: [x, y, z]}，部件名须属于本次输入且坐标有限",
            "en": "insertion_directions must be {part_name: [x, y, z]}, naming a part from this input with finite coordinates",
        },
        "task_operations.removal_audit_invalid_radial_center": {
            "zh-CN": "radial_center_mm 须为 3 个有限数",
            "en": "radial_center_mm must be 3 finite numbers",
        },
        "task_operations.removal_audit_invalid_split_axis": {
            "zh-CN": "split_axis 须为 0/1/2",
            "en": "split_axis must be 0/1/2",
        },
        "task_operations.removal_audit_invalid_split_value": {
            "zh-CN": "split_value_mm 须为有限数",
            "en": "split_value_mm must be a finite number",
        },
        "task_operations.removal_audit_limitations_groups": {
            "zh-CN": "先在各分组内部逐件安装/移除，最后再把两大分组整体分开",
            "en": "Install/remove parts within each group first, then separate the two whole groups last",
        },
        "task_operations.removal_audit_limitations_sampling": {
            "zh-CN": "离散采样，不是连续碰撞或实物装配证明",
            "en": "Discrete sampling only; not a continuous collision or physical assembly proof",
        },
        "task_operations.removal_audit_part_not_single_watertight": {
            "zh-CN": "部件未通过单体水密读回 {name}",
            "en": "Part failed the single watertight read-back: {name}",
        },
        "task_operations.removal_audit_requires_stl": {
            "zh-CN": "removal-audit 只接受 STL 输入",
            "en": "removal-audit only accepts STL inputs",
        },
        "task_operations.removal_audit_title": {
            "zh-CN": "拆卸与安装顺序检查",
            "en": "Removal and assembly-order check",
        },
        "task_operations.scene_input_no_mesh_geometry": {
            "zh-CN": "输入不含网格几何",
            "en": "The input contains no mesh geometry",
        },
        # --- task_templates.py ---
        "task_templates.container_description": {
            "zh-CN": "按尺寸创建带底壁的开口容器和独立盖子",
            "en": "Creates an open container with a base wall and a separate lid, sized by parameters",
        },
        "task_templates.container_title": {
            "zh-CN": "参数化容器",
            "en": "Parametric container",
        },
        "task_templates.hinge_description": {
            "zh-CN": "两片交错销轴铰链，带可播放的开合动画",
            "en": "An interleaved two-leaf pin hinge with a playable open/close animation",
        },
        "task_templates.hinge_title": {
            "zh-CN": "铰链运动样件",
            "en": "Hinge motion sample",
        },
        "task_templates.mesh_process_description": {
            "zh-CN": "导入已有模型，执行平滑、减面、实体化、体素重网格或 UV 展开",
            "en": "Imports an existing model and applies smoothing, decimation, solidify, voxel remesh, or UV unwrap",
        },
        "task_templates.mesh_process_title": {
            "zh-CN": "Blender 网格处理",
            "en": "Blender mesh processing",
        },
        "task_templates.scene_layout_description": {
            "zh-CN": "把多个模型放入同一场景，生成 Blender 工程和预览",
            "en": "Lays out multiple models in one scene, producing a Blender project and a preview",
        },
        "task_templates.scene_layout_title": {
            "zh-CN": "模型陈列与渲染",
            "en": "Model layout and rendering",
        },
        "task_templates.unknown_template": {
            "zh-CN": "未知建模模板",
            "en": "Unknown modelling template",
        },
        # --- task_worker.py ---
        "task_worker.artifact_over_1gb": {
            "zh-CN": "单个产物超过 1 GB",
            "en": "A single artifact exceeds 1 GB",
        },
        "task_worker.cancelled": {
            "zh-CN": "用户取消",
            "en": "Cancelled by the user",
        },
        "task_worker.frozen_source_changed_during_build": {
            "zh-CN": "构建期间冻结源模型发生改变",
            "en": "The frozen source model changed during the build",
        },
        "task_worker.frozen_source_checksum_failed": {
            "zh-CN": "冻结源模型校验失败",
            "en": "The frozen source model failed its checksum",
        },
        "task_worker.glb_json_over_limit": {
            "zh-CN": "GLB JSON 超过限制",
            "en": "The GLB JSON exceeds the limit",
        },
        "task_worker.glb_readback_failed": {
            "zh-CN": "产物 GLB 读回失败",
            "en": "Reading the artifact GLB back failed",
        },
        "task_worker.implementation_changed": {
            "zh-CN": "任务构建实现已改变，请重新提交",
            "en": "The task's build implementation has changed; please resubmit",
        },
        "task_worker.no_artifacts_delivered": {
            "zh-CN": "脚本没有交付任何产物",
            "en": "The script did not deliver any artifacts",
        },
        "task_worker.process_did_not_complete": {
            "zh-CN": "建模进程未成功完成（exit {returncode}），详见运行日志",
            "en": "The modelling process did not complete successfully (exit {returncode}); see the run log",
        },
        "task_worker.timed_out": {
            "zh-CN": "任务超时",
            "en": "Task timed out",
        },
        # --- tasks.py ---
        "tasks.acceptance": {
            "zh-CN": "检查实际产物和约束，再把结果接回工作台；仅脚本成功不代表质量通过",
            "en": (
                "Inspect the actual artifacts and constraints before feeding the result back into the "
                "workbench; a script merely succeeding does not mean quality has been verified"
            ),
        },
        "tasks.artifact_changed_or_outside_task_dir": {
            "zh-CN": "产物已改变或不在任务目录内",
            "en": "The artifact has changed, or is outside the task directory",
        },
        "tasks.artifact_checksum_failed": {
            "zh-CN": "产物校验失败",
            "en": "The artifact failed its checksum",
        },
        "tasks.artifact_not_found": {
            "zh-CN": "产物不存在",
            "en": "The artifact does not exist",
        },
        "tasks.assembly_workflow_no_local_inputs": {
            "zh-CN": (
                "这个托管服务只接受服务端可访问的模型 URL（services.json 里 local_inputs_allowed 为 false）；"
                "不会自动上传本机文件或选区"
            ),
            "en": (
                "This hosted service only accepts a model URL the server can reach (local_inputs_allowed is "
                "false in services.json); it will not automatically upload a local file or selection"
            ),
        },
        "tasks.blender_not_found": {
            "zh-CN": "未找到 Blender；请安装 Blender 或将 WORKBENCH_BLENDER 设为其可执行文件路径",
            "en": "Blender not found; install it or set WORKBENCH_BLENDER to its executable path",
        },
        "tasks.busy_resume": {
            "zh-CN": "已有两个任务在执行",
            "en": "Two tasks are already running",
        },
        "tasks.busy_start": {
            "zh-CN": "已有两个任务在执行，请等待或取消其中一个",
            "en": "Two tasks are already running; wait for one to finish or cancel it",
        },
        "tasks.default_title": {
            "zh-CN": "建模任务",
            "en": "Modelling task",
        },
        "tasks.engine_must_be_blender_or_python": {
            "zh-CN": "执行环境为 blender/python",
            "en": "The execution engine must be blender or python",
        },
        "tasks.example_animation": {
            "zh-CN": "读取已有模型/骨架/明确运动轴，用本机工具制作动画并观察验证",
            "en": (
                "Read an existing model/skeleton/explicit motion axis, animate it with local tools, and "
                "verify it by observation"
            ),
        },
        "tasks.example_cad_script": {
            "zh-CN": "按尺寸编写 CAD/Blender 建模脚本，交付工程、STEP/STL/GLB 和实测尺寸",
            "en": (
                "Write a CAD/Blender modelling script from dimensions, delivering the project, STEP/STL/GLB, "
                "and measured dimensions"
            ),
        },
        "tasks.example_selection_edit": {
            "zh-CN": "基于选区执行确定编辑或冻结源参数重建，保留可撤销的原件",
            "en": (
                "Perform a deterministic edit on a selection, or a frozen-source parametric rebuild, keeping "
                "an undoable original"
            ),
        },
        "tasks.execution": {
            "zh-CN": "本机执行可信建模脚本；与 Codex shell 相同，不是安全沙箱",
            "en": "Trusted modelling scripts run locally; like the Codex shell, this is not a security sandbox",
        },
        "tasks.frozen_source_changed": {
            "zh-CN": "冻结的源模型已改变，停止重建",
            "en": "The frozen source model has changed; the rebuild is stopped",
        },
        "tasks.frozen_source_changed_during_copy": {
            "zh-CN": "复制期间冻结源模型发生改变，停止重建",
            "en": "The frozen source model changed during copying; the rebuild is stopped",
        },
        "tasks.guidance": {
            "zh-CN": (
                "优先用当前 GPT + 本机 Blender/CAD 完成尺寸建模、编辑、动画和渲染。服务是可选能力；本机执行仍"
                "使用 GPT 额度和本机算力。"
            ),
            "en": (
                "Prefer the current GPT plus local Blender/CAD for dimensioned modelling, editing, animation, "
                "and rendering. Hosted services are an optional capability; local execution still uses GPT "
                "quota and local compute."
            ),
        },
        "tasks.heartbeat_interrupted": {
            "zh-CN": "任务心跳中断；保留已生成文件，可重新运行",
            "en": "The task's heartbeat was interrupted; generated files are kept and it can be re-run",
        },
        "tasks.implementation_changed": {
            "zh-CN": "构建实现版本已改变，请重新提交任务；不将新实现冒充原版本重建",
            "en": (
                "The build implementation version has changed; please resubmit the task instead of rebuilding "
                "under the new implementation while claiming it is the original"
            ),
        },
        "tasks.input_must_be_absolute_local_path": {
            "zh-CN": "输入须为存在的本机绝对路径",
            "en": "Each input must be an existing local absolute path",
        },
        "tasks.inputs_max_50": {
            "zh-CN": "inputs 必须为至多 50 个文件路径",
            "en": "inputs must be at most 50 file paths",
        },
        "tasks.invalid_task_id": {
            "zh-CN": "无效任务 ID",
            "en": "Invalid task ID",
        },
        "tasks.old_task_not_frozen": {
            "zh-CN": "旧任务未冻结源模型，请重新提交一次作为参数化来源",
            "en": "The old task did not freeze a source model; resubmit once to serve as a parametric source",
        },
        "tasks.parametric_source_glb_must_embed_resources": {
            "zh-CN": "参数化源 GLB 必须内嵌全部资源",
            "en": "A parametric source GLB must embed all of its resources",
        },
        "tasks.params_must_be_json_finite": {
            "zh-CN": "params 必须为有限数值和 JSON 数据",
            "en": "params must contain only finite numbers and JSON-safe data",
        },
        "tasks.params_must_be_object": {
            "zh-CN": "params 必须为对象",
            "en": "params must be an object",
        },
        "tasks.rebuild_needs_finished_editable_task": {
            "zh-CN": "请选择已结束的可调参数任务",
            "en": "Please select a finished, parameter-editable task",
        },
        "tasks.rebuildable_task_needs_self_contained_format": {
            "zh-CN": "可重建任务使用自包含 GLB/STL/PLY，其他格式请先导入并导出 GLB",
            "en": (
                "A rebuildable task uses a self-contained GLB/STL/PLY; for other formats, import and export a GLB first"
            ),
        },
        "tasks.render_preview_must_be_bool": {
            "zh-CN": "render_preview 必须为布尔值",
            "en": "render_preview must be a boolean",
        },
        "tasks.resume_requires_remote_task_id": {
            "zh-CN": "只有已保存远端任务 ID 的失败或已停止服务任务可以继续收件",
            "en": (
                "Only a failed or stopped service task with a saved remote task ID can resume collecting its result"
            ),
        },
        "tasks.script_contract": {
            "zh-CN": (
                "脚本全局变量 workbench 是字典：inputs 为绝对路径列表，params 为参数字典，output 为产物目录。"
                "Blender 使用米/Z-up；自动保存 scene.blend 并导出 scene.glb（含骨架/动画）。其他产物写到 "
                "output；任务成功后从 artifacts 取产物 ID。静态 GLB 可 import 回编辑器；动画在任务预览中播放。"
            ),
            "en": (
                "The script's global workbench variable is a dict: inputs is a list of absolute paths, params "
                "is the parameter dict, and output is the artifact directory. Blender uses metres/Z-up; it "
                "auto-saves scene.blend and exports scene.glb (including skeleton/animation). Other artifacts "
                "are written to output; once the task succeeds, take artifact IDs from artifacts. A static "
                "GLB can be imported back into the editor; an animation plays in the task preview."
            ),
        },
        "tasks.script_required": {
            "zh-CN": "需要非空建模脚本（不超过 200 KB）或内置模板",
            "en": "A nonempty modelling script (at most 200 KB) or a built-in template is required",
        },
        "tasks.script_syntax_error": {
            "zh-CN": "脚本语法错误：第 {lineno} 行 {msg}",
            "en": "Script syntax error: line {lineno} {msg}",
        },
        "tasks.service_task_conflicts_script_or_template": {
            "zh-CN": "服务任务不能同时指定脚本或模板",
            "en": "A service task cannot also specify a script or a template",
        },
        "tasks.single_input_over_500mb": {
            "zh-CN": "单个输入超过 500 MB",
            "en": "A single input exceeds 500 MB",
        },
        "tasks.source_script_changed": {
            "zh-CN": "原任务构建脚本已改变，不能作为参数重建来源",
            "en": "The original task's build script has changed and cannot serve as a parametric-rebuild source",
        },
        "tasks.task_not_completed": {
            "zh-CN": "任务尚未成功完成",
            "en": "The task has not completed successfully yet",
        },
        "tasks.task_not_found": {
            "zh-CN": "任务不存在",
            "en": "The task does not exist",
        },
        "tasks.template_and_script_conflict": {
            "zh-CN": "template 与 script 只能选择一个",
            "en": "Choose either template or script, not both",
        },
        "tasks.template_requires_engine": {
            "zh-CN": "该模板需要 {engine}",
            "en": "This template requires {engine}",
        },
        "tasks.timeout_range": {
            "zh-CN": "任务时限为 1–3600 秒",
            "en": "The task time limit must be 1-3600 seconds",
        },
    }
)
