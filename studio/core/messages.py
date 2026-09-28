"""Message catalog for `studio.core.*` raises.

One entry per `EditorError.coded()` call site anywhere under `studio/core/`
(plus a handful of non-error UI strings — default object names, `summary`/
`warning` fields — that go through `studio.i18n.render()` directly at the
point they are produced; see `studio/i18n.py`'s module docstring).
Codes are `<module>.<meaning>`, lower snake_case, and become part of the
public error contract once released: never repurpose or delete one, only add.
The "zh-CN" text below is the original wording each raise/string used to
hardcode, carried over verbatim; "en" is a faithful translation, not a
paraphrase.

A few codes are bare (no module prefix): `stale_asset`, `branch_conflict`,
`part_locked`. These were already specific, externally-visible protocol
codes before this conversion (`EditorError`'s second positional argument,
exposed as `error.code` in JSON responses and, for `revision_conflict`/
`scope_violation`/`worktree_mismatch`/`session_unbound`/`invalid_invitation`/
`bad_arguments`, checked by HTTP-status/behaviour logic elsewhere) and each
maps to exactly one message, so the catalog code and the protocol code are
the same string. Where one protocol code is shared by several distinct
messages (e.g. several different `revision_conflict` situations), each
message gets its own `<module>.<meaning>` catalog code and the raise site
passes the shared protocol code separately via `EditorError.coded(...,
code=...)` / `collaboration.fail(..., "revision_conflict")` — see
`EditorError.coded()`'s docstring in `studio/core/editor.py`.

Imported (for its `register()` side effect) from `studio/core/__init__.py`,
so every code here is registered as soon as anything under `studio.core` is
imported — before any `studio.core.*` function has a chance to call
`EditorError.coded()`.
"""

from studio.i18n import register

register(
    {
        "branch_conflict": {
            "zh-CN": "这些零件已在源工程改变，不能覆盖：{conflicts}",
            "en": "These parts have changed in the source project and cannot be overwritten: {conflicts}",
        },
        "branches.merge_exceeds_object_limit": {
            "zh-CN": "合入后超过工程对象上限",
            "en": "Merging would exceed the project's object limit",
        },
        "branches.stale_source_revision": {
            "zh-CN": "源工程已改变，请读取最新 revision",
            "en": "The source project has changed; please read the latest revision",
        },
        "branches.summary_merged": {
            "zh-CN": "合入分支 {branch_id} 的 {count} 个零件变更",
            "en": "Merged {count} part change(s) from branch {branch_id}",
        },
        "collaboration.backend_worktree_mismatch": {
            "zh-CN": "此后台不属于指定文件夹工程",
            "en": "This backend does not belong to the specified folder project",
        },
        "collaboration.expected_revision_required": {
            "zh-CN": "需要 expected_revision",
            "en": "expected_revision is required",
        },
        "collaboration.ids_must_be_part_list": {
            "zh-CN": "ids 必须是零件 ID 列表",
            "en": "ids must be a list of part IDs",
        },
        "collaboration.invalid_worktree": {
            "zh-CN": "worktree 必须是当前任务的已有绝对工作目录",
            "en": "worktree must be the current task's existing absolute working directory",
        },
        "collaboration.invitation_invalid_or_expired": {
            "zh-CN": "聊天分支邀请无效或已过期",
            "en": "This chat-branch invitation is invalid or has expired",
        },
        "collaboration.invitation_not_owned": {
            "zh-CN": "邀请不属于当前协调任务",
            "en": "This invitation does not belong to the current coordinating task",
        },
        "collaboration.invitation_stale": {
            "zh-CN": "邀请发出后零件已改变，请重新创建邀请",
            "en": "The part has changed since this invitation was created; please create a new invitation",
        },
        "collaboration.no_collaboration_session": {
            "zh-CN": "当前工程尚未开启零件协作",
            "en": "This project has not enabled part collaboration yet",
        },
        "collaboration.nothing_to_undo_redo": {
            "zh-CN": "此聊天没有可撤销/重做的编辑",
            "en": "This chat has no edit to undo/redo",
        },
        "collaboration.params_must_be_object": {
            "zh-CN": "params 必须是对象",
            "en": "params must be an object",
        },
        "collaboration.parts_changed_reread": {
            "zh-CN": "零件已改变，请重新读取后编辑",
            "en": "The parts have changed; please re-read them before editing",
        },
        "collaboration.parts_modified_by_others": {
            "zh-CN": "这些零件已有后续修改，不能覆盖他人的成果",
            "en": "These parts have since been modified; you cannot overwrite someone else's work",
        },
        "collaboration.pick_existing_part": {
            "zh-CN": "请选择当前工程中的零件",
            "en": "Please select a part that exists in the current project",
        },
        "collaboration.project_changed_for_invite": {
            "zh-CN": "工程已改变，请刷新后创建聊天分支",
            "en": "The project has changed; please refresh before creating a chat branch",
        },
        "collaboration.project_changed_reread_or_versions": {
            "zh-CN": "工程已改变，请读取最新状态或提交逐零件 expected_versions",
            "en": "The project has changed; please read the latest state or submit per-part expected_versions",
        },
        "collaboration.scope_already_bound": {
            "zh-CN": "该任务已经绑定此工程，不能覆盖其修缮范围",
            "en": "This task is already bound to this project; its editing scope cannot be overwritten",
        },
        "collaboration.scope_bound_and_derived_only": {
            "zh-CN": "此聊天仅可修缮绑定零件及其派生件；整体导入请回主聊天",
            "en": "This chat may only edit its bound parts and their derivatives; use the main chat for a full import",
        },
        "collaboration.scope_no_full_replace": {
            "zh-CN": "共享工程不能被整体替换；请先创建独立模型分支",
            "en": "A shared project cannot be replaced wholesale; please create an independent model branch first",
        },
        "collaboration.scope_outside_binding": {
            "zh-CN": "不能绑定范围外的零件",
            "en": "Cannot bind a part that is outside the scope",
        },
        "collaboration.scope_outside_operation": {
            "zh-CN": "无法操作修缮范围之外的零件",
            "en": "Cannot operate on a part outside the editing scope",
        },
        "collaboration.scope_own_parts_only": {
            "zh-CN": "此聊天只可为自己的零件创建修缮分支",
            "en": "This chat may only create editing branches for its own parts",
        },
        "collaboration.scope_parent_child_mechanism": {
            "zh-CN": "此动作影响父子机构，请在覆盖这些零件的主聊天中编辑",
            "en": "This action affects a parent/child mechanism; please edit it in the main chat that covers these parts",
        },
        "collaboration.session_not_joined": {
            "zh-CN": "此共享工程尚未绑定当前聊天，请先加入工程",
            "en": "This shared project is not bound to the current chat yet; please join the project first",
        },
        "collaboration.summary_branch_merged": {
            "zh-CN": "合入模型分支",
            "en": "Merged model branch",
        },
        "collaboration.summary_chat_redo": {
            "zh-CN": "重做本聊天编辑",
            "en": "Redid this chat's edit",
        },
        "collaboration.summary_chat_undo": {
            "zh-CN": "撤销本聊天编辑",
            "en": "Undid this chat's edit",
        },
        "collaboration.too_many_objects": {
            "zh-CN": "一个工程最多 {max_objects} 个对象",
            "en": "A project may have at most {max_objects} objects",
        },
        "collaboration.unknown_operation": {
            "zh-CN": "未知协作操作",
            "en": "Unknown collaboration operation",
        },
        "collaboration.worktree_mismatch_branch_hint": {
            "zh-CN": "不同 worktree 不能共享写入，请创建模型分支",
            "en": "Different worktrees cannot share writes; please create a model branch",
        },
        "collaboration.worktree_mismatch_plain": {
            "zh-CN": "不同 worktree 不能共享写入",
            "en": "Different worktrees cannot share writes",
        },
        "editor.animated_mesh_rejected": {
            "zh-CN": "当前编辑器支持静态网格；此文件含骨架、动画或形变目标，已保留原件并停止导入",
            "en": (
                "This editor supports static meshes only; this file has a skeleton, animation, or morph targets — "
                "the original file was kept unchanged and the import was stopped"
            ),
        },
        "editor.archive_duplicate_or_too_large": {
            "zh-CN": "工程包含重复文件或解压后过大",
            "en": "The project archive contains duplicate files or is too large once extracted",
        },
        "editor.cut_volume_check_failed": {
            "zh-CN": "切割后体积校验未通过，原件未修改",
            "en": "The post-cut volume check failed; the original was not modified",
        },
        "editor.degenerate_or_mirrored_transform": {
            "zh-CN": "不支持退化或镜像变换",
            "en": "Degenerate or mirrored transforms are not supported",
        },
        "editor.export_city_requires_project_save": {
            "zh-CN": "完整城市请保存为工程；导出模型/打印时请显式选择已载入的人物或设施",
            "en": (
                "Please save a full city as a project; when exporting a model or print copy, explicitly select "
                "loaded characters or props"
            ),
        },
        "editor.export_format_glb_or_stl": {
            "zh-CN": "导出格式为 glb/stl",
            "en": "The export format must be glb or stl",
        },
        "editor.export_nothing_selected": {
            "zh-CN": "没有可导出的对象",
            "en": "There is nothing selected to export",
        },
        "editor.export_reload_failed": {
            "zh-CN": "导出文件读回失败",
            "en": "Failed to read back the exported file",
        },
        "editor.export_scene_requires_project_save": {
            "zh-CN": (
                "完整场景请保存工程；单个实例用「导出编辑源 GLB」，当前动作用「动作编辑 → 动画 GLB」。"
                "普通网格导出不会打平骨架与层级"
            ),
            "en": (
                'Please save a full scene as a project; for a single instance use "Export editing-source GLB", '
                'for the current motion use "Motion editing → Animation GLB". A plain mesh export does not '
                "flatten the rig or hierarchy"
            ),
        },
        "editor.external_asset_reference": {
            "zh-CN": "请先将外部资源保存为本地文件或自包含 GLB",
            "en": "Please save external resources as local files or a self-contained GLB first",
        },
        "editor.ids_must_be_unique_list": {
            "zh-CN": "ids 必须是不重复的对象 ID 列表",
            "en": "ids must be a list of unique object IDs",
        },
        "editor.invalid_glb": {
            "zh-CN": "无效的 GLB 文件",
            "en": "Invalid GLB file",
        },
        "editor.invalid_boolean_operation": {
            "zh-CN": "布尔类型须为 union/difference/intersection",
            "en": "The boolean operation must be union/difference/intersection",
        },
        "editor.invalid_number": {
            "zh-CN": "请输入有效数值",
            "en": "Please enter a valid number",
        },
        "editor.invalid_object_properties": {
            "zh-CN": "无效的对象属性",
            "en": "Invalid object properties",
        },
        "editor.invalid_or_duplicate_object_identity": {
            "zh-CN": "无效或重复的对象身份",
            "en": "Invalid or duplicate object identity",
        },
        "editor.invalid_selection": {
            "zh-CN": "工程选区无效",
            "en": "Invalid project selection",
        },
        "editor.invalid_triangle_mesh": {
            "zh-CN": "模型必须包含有限坐标的三角网格",
            "en": "The model must be a triangle mesh with finite coordinates",
        },
        "editor.manifold_read_failed": {
            "zh-CN": "Manifold 无法读取该实体",
            "en": "Manifold could not read this solid",
        },
        "editor.material_loss_requires_consent": {
            "zh-CN": "此操作会转换为纯色网格；如接受，请启用几何操作的纯色选项。原件仍可撤销恢复",
            "en": (
                "This operation converts the mesh to a solid color; if that is acceptable, enable the solid-color "
                "option for geometry operations. The original can still be restored with undo"
            ),
        },
        "editor.matrix_must_be_single_object_affine": {
            "zh-CN": "matrix 必须是单个对象的有限 4×4 仿射矩阵",
            "en": "matrix must be a finite 4×4 affine matrix for a single object",
        },
        "editor.merge_boolean_needs_two": {
            "zh-CN": "请选择至少两个对象",
            "en": "Please select at least two objects",
        },
        "editor.mesh_checksum_failed": {
            "zh-CN": "工程网格校验失败",
            "en": "Project mesh checksum verification failed",
        },
        "editor.mesh_must_be_self_contained": {
            "zh-CN": "工程网格必须自包含",
            "en": "Project meshes must be self-contained",
        },
        "editor.motion_asset_checksum_failed": {
            "zh-CN": "动作资产校验失败",
            "en": "Motion asset checksum verification failed",
        },
        "editor.motion_asset_id_invalid": {
            "zh-CN": "无效动作资产 ID",
            "en": "Invalid motion asset ID",
        },
        "editor.motion_scene_binding_blocks_action": {
            "zh-CN": "此对象带动作绑定；请先清除动作，或在 Blender 修改后重新导入骨架，避免旧绑定应用到新几何",
            "en": (
                "This object has a motion binding; please clear the motion first, or modify it in Blender and "
                "re-import the rig, so the old binding is never applied to new geometry"
            ),
        },
        "editor.no_valid_output_mesh": {
            "zh-CN": "没有产生有效网格",
            "en": "No valid mesh was produced",
        },
        "editor.open_path_too_large_or_invalid": {
            "zh-CN": "请选择小于 2 GB 的工程绝对路径",
            "en": "Please choose an absolute project path smaller than 2 GB",
        },
        "editor.operation_produced_no_solid": {
            "zh-CN": "操作没有产生有效实体，请调整参数",
            "en": "The operation did not produce a valid solid; please adjust the parameters",
        },
        "editor.output_path_exists": {
            "zh-CN": "输出文件已存在，请使用新名称",
            "en": "The output file already exists; please use a new name",
        },
        "editor.output_path_invalid": {
            "zh-CN": "输出须为已有目录中的绝对路径，后缀为 {suffix}",
            "en": "The output must be an absolute path in an existing directory, with suffix {suffix}",
        },
        "editor.params_must_be_object": {
            "zh-CN": "params 必须是对象",
            "en": "params must be an object",
        },
        "editor.plane_cut_single_object": {
            "zh-CN": "每次请选择一个实体进行平面切割",
            "en": "Please select one solid at a time for a plane cut",
        },
        "editor.repair_could_not_close_hole": {
            "zh-CN": "自动修复无法补齐此洞，原件未修改",
            "en": "Automatic repair could not close this hole; the original was not modified",
        },
        "editor.scale_out_of_range": {
            "zh-CN": "缩放必须在 (0, 1000] 范围内",
            "en": "Scale must be within (0, 1000]",
        },
        "editor.scene_asset_checksum_failed": {
            "zh-CN": "场景资产校验失败",
            "en": "Scene asset checksum verification failed",
        },
        "editor.scene_asset_id_invalid": {
            "zh-CN": "场景资产 ID 无效",
            "en": "Invalid scene asset ID",
        },
        "editor.select_minimum_objects": {
            "zh-CN": "请选择至少 {minimum} 个当前工程中的对象",
            "en": "Please select at least {minimum} object(s) from the current project",
        },
        "editor.simplify_introduced_opening": {
            "zh-CN": "减面引入开口，原件未修改；请提高保留比例",
            "en": "Simplification introduced an opening; the original was not modified — please raise the keep ratio",
        },
        "editor.simplify_ratio_out_of_range": {
            "zh-CN": "减面保留比例须在 0–1 之间",
            "en": "The simplification keep ratio must be between 0 and 1",
        },
        "editor.solid_requires_closed_consistent_mesh": {
            "zh-CN": "需要封闭且法向一致的实体，请先检查/修复网格",
            "en": "This requires a closed, consistently-wound solid; please inspect/repair the mesh first",
        },
        "editor.stale_project_revision": {
            "zh-CN": "工程已改变，请读取最新状态后重试",
            "en": "The project has changed; please reload the latest state and try again",
        },
        "editor.summary_exported": {
            "zh-CN": "导出 {count} 个对象为 {format}",
            "en": "Exported {count} object(s) as {format}",
        },
        "editor.summary_print_copy_created": {
            "zh-CN": "创建打印副本",
            "en": "Created print copies",
        },
        "editor.too_many_faces": {
            "zh-CN": "单个对象超过 500 万面，请先拆分或减面",
            "en": "A single object exceeds 5,000,000 faces; please split it or reduce the face count first",
        },
        "editor.too_many_objects": {
            "zh-CN": "一个工程最多 {max_objects} 个对象",
            "en": "A project may have at most {max_objects} objects",
        },
        "editor.unknown_action": {
            "zh-CN": "未知编辑操作: {action}",
            "en": "Unknown editor action: {action}",
        },
        "editor.unsupported_project_format": {
            "zh-CN": "不支持的工程格式",
            "en": "Unsupported project format",
        },
        "editor.untitled_project": {
            "zh-CN": "未命名工程",
            "en": "Untitled project",
        },
        "editor.warning_open_outputs": {
            "zh-CN": "{open_count} 个输出仍有开口，可在检查网格中查看",
            "en": "{open_count} output(s) still have an opening; see mesh inspection for details",
        },
        "editor.warning_stl_no_hierarchy": {
            "zh-CN": "STL 不包含材质与对象层级",
            "en": "STL does not include materials or the object hierarchy",
        },
        "editor.wrong_vector_size": {
            "zh-CN": "需要 {size} 个有限数值",
            "en": "Requires {size} finite numbers",
        },
        "editor.zero_cut_normal": {
            "zh-CN": "切面法向不能为零",
            "en": "The cut plane's normal cannot be zero",
        },
        "editor_actions.city_instance_no_shear": {
            "zh-CN": "城市实例不支持剪切变换，请使用移动、旋转或沿本地轴缩放",
            "en": "City instances do not support shear transforms; use translation, rotation, or scaling along local axes",
        },
        "editor_actions.default_box_name": {
            "zh-CN": "立方体",
            "en": "Box",
        },
        "editor_actions.default_sphere_name": {
            "zh-CN": "球体",
            "en": "Sphere",
        },
        "editor_actions.duplicate_suffix": {
            "zh-CN": " 副本",
            "en": " (copy)",
        },
        "editor_actions.extract_faces_needs_one_object": {
            "zh-CN": "请选择一个对象做面区拆分",
            "en": "Please select one object to split by face region",
        },
        "editor_actions.extract_faces_needs_partial_selection": {
            "zh-CN": "所选面区须包含部分三角形，不能为空或覆盖整个对象",
            "en": "The selected face region must be a partial set of triangles; it cannot be empty or the whole object",
        },
        "editor_actions.extract_faces_radius_out_of_range": {
            "zh-CN": "区域半径必须为 0–10000 mm",
            "en": "The region radius must be between 0 and 10000 mm",
        },
        "editor_actions.import_needs_1_to_50_paths": {
            "zh-CN": "请提供 1–50 个模型绝对路径",
            "en": "Please provide 1 to 50 absolute model paths",
        },
        "editor_actions.import_path_must_exist_and_be_small": {
            "zh-CN": "需要存在且小于 500 MB 的本地绝对路径",
            "en": "Requires an existing local absolute path smaller than 500 MB",
        },
        "editor_actions.import_unsupported_extension": {
            "zh-CN": "支持 GLB/GLTF/STL/OBJ/PLY/3MF",
            "en": "Supported formats: GLB/GLTF/STL/OBJ/PLY/3MF",
        },
        "editor_actions.invalid_face_ids": {
            "zh-CN": "face_ids 必须是当前对象的有效三角形索引",
            "en": "face_ids must be valid triangle indices of the current object",
        },
        "editor_actions.invalid_units": {
            "zh-CN": "单位须为 auto/mm/cm/m",
            "en": "units must be auto/mm/cm/m",
        },
        "editor_actions.material_slot_edit_needs_one_object": {
            "zh-CN": "按材质槽编辑时请选择一个对象，避免误改其他对象的同序号材质",
            "en": (
                "When editing by material slot, please select one object, to avoid accidentally changing the "
                "same-numbered slot on other objects"
            ),
        },
        "editor_actions.no_editable_mesh_in_files": {
            "zh-CN": "文件中没有可编辑网格",
            "en": "The file contains no editable mesh",
        },
        "editor_actions.nothing_to_undo_redo": {
            "zh-CN": "没有可撤销/重做的操作",
            "en": "There is nothing to undo/redo",
        },
        "editor_actions.primitive_size_out_of_range": {
            "zh-CN": "尺寸必须大于 0 且不超过 10000 mm",
            "en": "Size must be greater than 0 and at most 10000 mm",
        },
        "editor_actions.primitive_unsupported_kind": {
            "zh-CN": "支持 box/sphere",
            "en": "Supported kinds: box/sphere",
        },
        "editor_actions.rename_needs_one_object_and_name": {
            "zh-CN": "请选择一个对象，名称长度为 1–160 字符",
            "en": "Please select one object; the name must be 1 to 160 characters long",
        },
        "editor_actions.replace_needs_one_part_and_one_file": {
            "zh-CN": "替换需要一个目标零件和一个模型文件；文件坐标须与导出时一致",
            "en": "Replace requires one target part and one model file; the file's coordinates must match the export",
        },
        "editor_actions.suffix_region": {
            "zh-CN": " · 区域",
            "en": " · region",
        },
        "editor_actions.suffix_remainder": {
            "zh-CN": " · 余下",
            "en": " · remainder",
        },
        "editor_actions.summary_boolean": {
            "zh-CN": "布尔运算",
            "en": "Boolean operation",
        },
        "editor_actions.summary_created": {
            "zh-CN": "新建{name}",
            "en": "Created {name}",
        },
        "editor_actions.summary_deleted": {
            "zh-CN": "删除 · {count} 个对象",
            "en": "Deleted · {count} object(s)",
        },
        "editor_actions.summary_duplicated": {
            "zh-CN": "复制 · {count} 个对象",
            "en": "Duplicated · {count} object(s)",
        },
        "editor_actions.summary_extract_faces": {
            "zh-CN": "按面区拆分，保留材质；切口未封盖",
            "en": "Split by face region, materials preserved; the cut was not capped",
        },
        "editor_actions.summary_imported": {
            "zh-CN": "导入 {count} 个对象",
            "en": "Imported {count} object(s)",
        },
        "editor_actions.summary_inspected": {
            "zh-CN": "检查完成",
            "en": "Inspection complete",
        },
        "editor_actions.summary_isolated": {
            "zh-CN": "单独显示 · {count} 个对象",
            "en": "Isolated · {count} object(s)",
        },
        "editor_actions.summary_material_changed": {
            "zh-CN": "修改材质 · {count} 个对象",
            "en": "Changed material · {count} object(s)",
        },
        "editor_actions.summary_merge": {
            "zh-CN": "合并网格",
            "en": "Merged mesh",
        },
        "editor_actions.summary_opened_project": {
            "zh-CN": "打开工程",
            "en": "Opened project",
        },
        "editor_actions.summary_plane_cut": {
            "zh-CN": "平面切割",
            "en": "Plane cut",
        },
        "editor_actions.summary_redo": {
            "zh-CN": "重做",
            "en": "Redo",
        },
        "editor_actions.summary_renamed": {
            "zh-CN": "重命名 · {count} 个对象",
            "en": "Renamed · {count} object(s)",
        },
        "editor_actions.summary_repair": {
            "zh-CN": "执行网格修复",
            "en": "Ran mesh repair",
        },
        "editor_actions.summary_replaced_part": {
            "zh-CN": "更新零件，载入 {count} 个网格",
            "en": "Updated part, loaded {count} mesh(es)",
        },
        "editor_actions.summary_saved_project_copy": {
            "zh-CN": "保存工程副本",
            "en": "Saved a project copy",
        },
        "editor_actions.summary_selection_updated": {
            "zh-CN": "更新选区",
            "en": "Updated selection",
        },
        "editor_actions.summary_show_all": {
            "zh-CN": "显示全部对象",
            "en": "Showed all objects",
        },
        "editor_actions.summary_simplify": {
            "zh-CN": "减面",
            "en": "Simplified",
        },
        "editor_actions.summary_split_components": {
            "zh-CN": "按连通块拆分",
            "en": "Split by connected component",
        },
        "editor_actions.summary_transformed": {
            "zh-CN": "变换 · {count} 个对象",
            "en": "Transformed · {count} object(s)",
        },
        "editor_actions.summary_undo": {
            "zh-CN": "撤销",
            "en": "Undo",
        },
        "editor_actions.summary_visibility_changed": {
            "zh-CN": "调整可见性 · {count} 个对象",
            "en": "Changed visibility · {count} object(s)",
        },
        "editor_actions.visible_must_be_boolean": {
            "zh-CN": "visible 必须是布尔值",
            "en": "visible must be a boolean",
        },
        "history.not_latest": {
            "zh-CN": "id={target_id} 不是最近一条可撤销记录（最近一条是 id={latest_id}）",
            "en": "id={target_id} is not the latest undoable record (the latest is id={latest_id})",
        },
        "history.nothing_to_undo": {
            "zh-CN": "没有可撤销的记录",
            "en": "Nothing to undo",
        },
        "history.readiness_bad_parts": {
            "zh-CN": "{count} 件不水密或放不下",
            "en": "{count} part(s) not watertight or not fitting the bed",
        },
        "history.readiness_export_warn": {
            "zh-CN": "{count} 盘有警告",
            "en": "{count} plate(s) with warnings",
        },
        "history.readiness_model_pass": {
            "zh-CN": "{count} 件，全部水密，放得下",
            "en": "{count} part(s), all watertight and fitting the bed",
        },
        "history.readiness_orient_warn": {
            "zh-CN": "{count} 件有警告",
            "en": "{count} part(s) with warnings",
        },
        "history.readiness_separator": {
            "zh-CN": "，",
            "en": ", ",
        },
        "history.readiness_warnings": {
            "zh-CN": "{count} 条警告",
            "en": "{count} warning(s)",
        },
        "history.undo_snapshot_missing": {
            "zh-CN": "撤销记录缺少可还原的快照",
            "en": "The undo record has no snapshot to restore",
        },
        "materials.default_slot_name": {
            "zh-CN": "材质 {index}",
            "en": "Material {index}",
        },
        "materials.invalid_color_format": {
            "zh-CN": "颜色使用 #rrggbb",
            "en": "Colors must use #rrggbb",
        },
        "materials.invalid_material_slots": {
            "zh-CN": "material_slots 必须是不重复的有效材质槽索引",
            "en": "material_slots must be unique, valid material-slot indices",
        },
        "materials.multicolor_requires_conversion": {
            "zh-CN": "此对象含多色顶点，请先使用保色材质转换，避免覆盖原颜色",
            "en": (
                "This object has multicolor vertices; please use the color-preserving material conversion first, "
                "to avoid overwriting the original colors"
            ),
        },
        "materials.no_material_slots": {
            "zh-CN": "此对象没有材质槽；省略 material_slots 可创建基础材质",
            "en": "This object has no material slots; omit material_slots to create a base material",
        },
        "materials.parameter_out_of_range": {
            "zh-CN": "材质参数范围为 0–1",
            "en": "Material parameters must be between 0 and 1",
        },
        "materials.requires_pbr_material": {
            "zh-CN": "请先转换为 PBR 材质后编辑",
            "en": "Please convert to a PBR material before editing",
        },
        "materials.stale_material_slots": {
            "zh-CN": "材质槽已失效，请刷新对象状态",
            "en": "The material slots are stale; please refresh the object's state",
        },
        "materials.texture_format_or_size": {
            "zh-CN": "纹理支持 PNG/JPEG/WebP，最多 1600 万像素",
            "en": "Textures support PNG/JPEG/WebP, up to 16 million pixels",
        },
        "materials.texture_path_invalid": {
            "zh-CN": "纹理须为不超过 32 MB 的本地图片绝对路径",
            "en": "The texture must be a local absolute image path no larger than 32 MB",
        },
        "materials.texture_requires_uv": {
            "zh-CN": "替换纹理需要有效的原有 UV，请先展 UV",
            "en": "Replacing the texture requires valid existing UVs; please unwrap UVs first",
        },
        "part_locked": {
            "zh-CN": "零件 {part} 正由任务 {session} 修缮；可观察或创建独立模型分支",
            "en": "Part {part} is being edited by task {session}; you may observe it or create an independent model branch",
        },
        "stale_asset": {
            "zh-CN": "网格已不在当前工程，请刷新",
            "en": "This mesh is no longer part of the current project; please refresh",
        },
        "uploads.bad_base64": {
            "zh-CN": "文件数据编码错误",
            "en": "Chunk data is not valid base64",
        },
        "uploads.bad_name_or_type": {
            "zh-CN": "不支持的文件名或类型",
            "en": "Unsupported file name or type",
        },
        "uploads.bad_size_or_offset": {
            "zh-CN": "文件为 1–500 MB 以内，offset 必须合法",
            "en": "File size must be between 1 and 500 MB, and offset must be valid",
        },
        "uploads.bad_upload_id": {
            "zh-CN": "无效上传 ID",
            "en": "Invalid upload id",
        },
        "uploads.chunk_length_mismatch": {
            "zh-CN": "文件块长度不匹配",
            "en": "Chunk length does not match the declared range",
        },
        "uploads.chunk_not_contiguous": {
            "zh-CN": "文件块不连续",
            "en": "Chunk is not contiguous with previously received data",
        },
        "uploads.chunk_too_large": {
            "zh-CN": "每块最多 1 MB",
            "en": "Each chunk is at most 1 MB",
        },
        "uploads.duplicate_chunk_mismatch": {
            "zh-CN": "重复文件块不一致",
            "en": "Duplicate chunk does not match previously received data",
        },
        "uploads.first_chunk_must_start_at_zero": {
            "zh-CN": "首块必须从 0 开始",
            "en": "The first chunk must start at offset 0",
        },
        "uploads.metadata_mismatch": {
            "zh-CN": "上传元数据不匹配",
            "en": "Upload metadata does not match the original request",
        },
    }
)
