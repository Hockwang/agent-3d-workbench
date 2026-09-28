"""Message catalog for `studio.core.{scene_assets,city,motion}` raises and
the UI-facing action-result strings they return.

One entry per `EditorError.coded()` call site plus every `studio.i18n.render()`
call in those three modules. Codes are `<module>.<meaning>`, lower snake_case,
and become part of the public error/response contract once released: never
repurpose or delete one, only add. The "zh-CN" text below is the original
wording each site used to hardcode, carried over verbatim; "en" is a faithful
translation, not a paraphrase.

Imported (for its `register()` side effect) from `studio/core/__init__.py`, so
every code here is registered as soon as anything under `studio.core` is
imported -- before any of these three modules' functions can call
`EditorError.coded()` or `studio.i18n.render()`.
"""

from studio.i18n import register

register(
    {
        "city.archive_catalog_mismatch": {
            "zh-CN": "归档城市清单与已有冻结版本不同",
            "en": "The archived city catalog differs from an existing frozen version",
        },
        "city.archive_missing_package": {
            "zh-CN": "归档缺少城市源包",
            "en": "The archive is missing the city source package",
        },
        "city.archive_package_too_large_or_duplicate": {
            "zh-CN": "城市包过大或有重复资源",
            "en": "City package is too large or has duplicate resources",
        },
        "city.archive_resource_checksum_mismatch": {
            "zh-CN": "城市归档资源校验失败",
            "en": "City archive resource checksum failed",
        },
        "city.catalog_frozen_mismatch": {
            "zh-CN": "城市生成清单与冻结版本不一致，请重开同一源版本",
            "en": "The generated city catalog does not match the frozen version; please reopen the same source version",
        },
        "city.catalog_summary": {
            "zh-CN": "读取城市实例",
            "en": "Read city instances",
        },
        "city.catalog_too_large": {
            "zh-CN": "城市实例清单过大",
            "en": "City instance catalog is too large",
        },
        "city.checkout_existing_summary": {
            "zh-CN": "选中已编辑城市实例",
            "en": "Selected the already-edited city instance",
        },
        "city.checkout_summary": {
            "zh-CN": "城市实例已进入局部编辑，提交后原位联动",
            "en": "The city instance is now in local editing; submitting links it back in place",
        },
        "city.duplicate_or_symlink_entry": {
            "zh-CN": "城市包存在重复文件或软链接",
            "en": "City package has a duplicate file or a symlink",
        },
        "city.import_summary": {
            "zh-CN": "已导入完整城市包，打开城市以初始化实例清单",
            "en": "Full city package imported; open the city to initialize the instance catalog",
        },
        "city.instance_action_unsupported": {
            "zh-CN": "城市实例目前支持原位变换、材质和完整模型回填；动作与行为修改请回填兼容源片段",
            "en": "City instances currently support in-place transform, material and full-model replace-in-place; edit motion/behavior by replacing with a compatible source clip",
        },
        "city.instance_binding_mismatch": {
            "zh-CN": "城市实例绑定与冻结清单不同",
            "en": "The city instance binding differs from the frozen catalog",
        },
        "city.instance_has_two_edit_branches": {
            "zh-CN": "同一城市实例存在两个编辑分支，请先解决零件冲突",
            "en": "The same city instance has two edit branches; please resolve the part conflict first",
        },
        "city.instance_not_found": {
            "zh-CN": "城市实例不存在，请先打开城市视口完成清单初始化",
            "en": "City instance does not exist; please open the city viewport first to initialize the catalog",
        },
        "city.instance_references_missing_model": {
            "zh-CN": "城市实例引用了源包中不存在的模型",
            "en": "City instance references a model that does not exist in the source package",
        },
        "city.instance_source_project_missing": {
            "zh-CN": "城市实例的源工程已丢失",
            "en": "The city instance's source project is gone",
        },
        "city.instances_empty_or_too_large": {
            "zh-CN": "城市清单为空或过大",
            "en": "City instance list is empty or too large",
        },
        "city.invalid_bone_binding": {
            "zh-CN": "城市骨骼绑定无效",
            "en": "Invalid city bone binding",
        },
        "city.invalid_catalog": {
            "zh-CN": "城市实例清单无效",
            "en": "Invalid city instance catalog",
        },
        "city.invalid_clip_binding": {
            "zh-CN": "城市动画绑定无效",
            "en": "Invalid city animation binding",
        },
        "city.invalid_instance_id": {
            "zh-CN": "城市实例身份无效",
            "en": "Invalid city instance identity",
        },
        "city.invalid_instance_name": {
            "zh-CN": "城市实例名称无效",
            "en": "Invalid city instance name",
        },
        "city.invalid_instance_transform": {
            "zh-CN": "城市实例变换无效",
            "en": "Invalid city instance transform",
        },
        "city.invalid_instance_url": {
            "zh-CN": "城市实例源路径无效",
            "en": "Invalid city instance source path",
        },
        "city.invalid_local_zip_path": {
            "zh-CN": "请选择本地 Cubely ZIP 绝对路径",
            "en": "Please choose a local Cubely ZIP absolute path",
        },
        "city.invalid_manifest_entry": {
            "zh-CN": "城市资源条目无效",
            "en": "Invalid city resource entry",
        },
        "city.invalid_package_digest": {
            "zh-CN": "城市包身份无效",
            "en": "Invalid city package identity",
        },
        "city.invalid_package_manifest": {
            "zh-CN": "城市包格式无效",
            "en": "Invalid city package format",
        },
        "city.invalid_package_path": {
            "zh-CN": "城市包包含无效路径",
            "en": "City package contains an invalid path",
        },
        "city.invalid_schema": {
            "zh-CN": "城市格式无效",
            "en": "Invalid city format",
        },
        "city.manifest_hash_mismatch": {
            "zh-CN": "城市包清单哈希不符",
            "en": "City package manifest hash does not match",
        },
        "city.manifest_too_large": {
            "zh-CN": "城市资源清单过大",
            "en": "City resource manifest is too large",
        },
        "city.missing_cubely_source": {
            "zh-CN": "此 ZIP 不含可接入的 Cubely 城市源码",
            "en": "This ZIP does not contain adaptable Cubely city source",
        },
        "city.missing_pedestrian_manifest": {
            "zh-CN": "城市人物清单缺失",
            "en": "City pedestrian manifest is missing",
        },
        "city.missing_source_package": {
            "zh-CN": "城市源包缺失",
            "en": "City source package is missing",
        },
        "city.only_one_city_per_project": {
            "zh-CN": "每个工程目前只挂载一个城市",
            "en": "Each project currently mounts only one city",
        },
        "city.package_not_in_project": {
            "zh-CN": "城市包不属于当前工程",
            "en": "The city package does not belong to the current project",
        },
        "city.package_too_large": {
            "zh-CN": "城市包超过容量限制",
            "en": "City package exceeds the size limit",
        },
        "city.project_already_has_city": {
            "zh-CN": "工程已有城市；请在独立工程导入另一城市",
            "en": "The project already has a city; please import another city in a separate project",
        },
        "city.register_summary": {
            "zh-CN": "城市已初始化：{count} 个人物与设施",
            "en": "City initialized: {count} people and facilities",
        },
        "city.replacement_clip_too_short": {
            "zh-CN": "候选截短了城市行为依赖的动画时间轴",
            "en": "The candidate shortened the animation timeline the city behavior depends on",
        },
        "city.replacement_missing_bones": {
            "zh-CN": "新人物缺少城市行为所需骨骼，请保留原骨名和语义映射",
            "en": "The new person is missing the bones the city behavior needs; keep the original bone names and semantic mapping",
        },
        "city.replacement_missing_clip": {
            "zh-CN": "候选缺少城市行为绑定的源动画片段",
            "en": "The candidate is missing the source animation clip the city behavior is bound to",
        },
        "city.requires_city_import": {
            "zh-CN": "请先导入城市",
            "en": "Please import a city first",
        },
        "city.resource_checksum_mismatch": {
            "zh-CN": "城市源资源校验失败",
            "en": "City source resource checksum failed",
        },
        "city.resource_missing_or_too_large": {
            "zh-CN": "城市资源不存在或过大",
            "en": "The city resource does not exist or is too large",
        },
        "city.root_managed_by_runtime": {
            "zh-CN": "城市根节点由运行时管理，请选择具体人物或设施编辑",
            "en": "The city root node is managed by the runtime; please select a specific person or facility to edit",
        },
        "city.root_transform_not_allowed": {
            "zh-CN": "城市根节点不能整体变换",
            "en": "The city root node cannot be transformed as a whole",
        },
        "city.runtime_build_failed": {
            "zh-CN": "城市适配构建失败：{stderr}",
            "en": "City adapter build failed: {stderr}",
        },
        "city.runtime_not_built_locally": {
            "zh-CN": "此城市运行模块尚未在本机从源包构建，请先显式导入原 Cubely ZIP",
            "en": "This city runtime module has not been built locally from the source package; please explicitly import the original Cubely ZIP first",
        },
        "city.unknown_action": {
            "zh-CN": "未知城市操作",
            "en": "Unknown city action",
        },
        "city.zip_too_large": {
            "zh-CN": "城市 ZIP 超过 2 GB",
            "en": "City ZIP exceeds 2 GB",
        },
        "motion.asset_kind_changed": {
            "zh-CN": "不能更改源资产的动作类型",
            "en": "The source asset's motion kind cannot be changed",
        },
        "motion.blend_not_uncompressed": {
            "zh-CN": "请保存为未压缩的 .blend，并在 Blender 中打包外部资源",
            "en": "Please save as an uncompressed .blend, with external resources packed in Blender",
        },
        "motion.clear_summary": {
            "zh-CN": "清除选中对象的动作，保留静态模型",
            "en": "Cleared motion on the selected objects, keeping the static model",
        },
        "motion.clip_duration_out_of_range": {
            "zh-CN": "源片段长度须为 0–120 秒，请先在 Blender 裁剪",
            "en": "Source clip length must be 0-120 seconds; please trim it in Blender first",
        },
        "motion.clip_range_exceeds_source": {
            "zh-CN": "动作时间范围超过源 GLB clip",
            "en": "Motion time range exceeds the source GLB clip",
        },
        "motion.export_glb_summary": {
            "zh-CN": "导出烘焙动画 GLB",
            "en": "Exported a baked-animation GLB",
        },
        "motion.export_zip_summary": {
            "zh-CN": "导出可编辑运动包",
            "en": "Exported an editable motion package",
        },
        "motion.exported_glb_missing_geometry": {
            "zh-CN": "动画 GLB 读回缺少几何",
            "en": "The exported animation GLB is missing geometry on read-back",
        },
        "motion.geometry_changed": {
            "zh-CN": "{name} 的几何已变化，请清除旧绑定后重新绑定",
            "en": "{name}'s geometry has changed; clear the old binding and rebind",
        },
        "motion.glb_export_requires_single_rig": {
            "zh-CN": "骨骼 GLB 导出请选择一个完整 rig；多对象请导出运动工程",
            "en": "Select a single complete rig to export a rig GLB; export a motion project for multiple objects",
        },
        "motion.has_morph_targets": {
            "zh-CN": "当前动作编辑支持骨骼和刚体；含 morph targets 的文件请在 Blender 烘焙后导入",
            "en": "Motion editing currently supports bones and rigid bodies; files with morph targets should be baked in Blender before importing",
        },
        "motion.import_package_summary": {
            "zh-CN": "导入运动工程 · {count} 个对象",
            "en": "Imported motion project - {count} objects",
        },
        "motion.invalid_blend_path": {
            "zh-CN": "源 .blend 需要小于 500 MB 的本地绝对路径",
            "en": "The source .blend needs a local absolute path under 500 MB",
        },
        "motion.invalid_bone_names": {
            "zh-CN": "骨骼需要非空且唯一的名称",
            "en": "Bones need nonempty, unique names",
        },
        "motion.invalid_export_format": {
            "zh-CN": "动作导出支持 zip/glb",
            "en": "Motion export supports zip/glb",
        },
        "motion.invalid_motion_payload": {
            "zh-CN": "motion 必须为动作对象",
            "en": "motion must be a motion object",
        },
        "motion.invalid_package_path": {
            "zh-CN": "需要小于 500 MB 的运动包绝对路径",
            "en": "Needs a motion package absolute path under 500 MB",
        },
        "motion.invalid_rig_path": {
            "zh-CN": "请提供小于 500 MB 的本地骨骼 GLB 绝对路径",
            "en": "Please provide a local rig GLB absolute path under 500 MB",
        },
        "motion.joint_not_allowed_on_scene": {
            "zh-CN": "完整场景实例保留内部动画；机械关节编辑请使用独立网格对象，或在 Blender 修改后原位回填",
            "en": "Full scene instances keep their internal animation; edit mechanical joints on an independent mesh object, or replace in place after editing in Blender",
        },
        "motion.missing_motionforge_manifest": {
            "zh-CN": "缺少唯一 MotionForge manifest",
            "en": "Missing a unique MotionForge manifest",
        },
        "motion.missing_skin": {
            "zh-CN": "GLB 没有蒙皮骨架，请通过本地 Blender 绑骨后导入",
            "en": "The GLB has no skinned rig; please rig it locally in Blender before importing",
        },
        "motion.motionforge_joint_not_zeroed": {
            "zh-CN": "请先在 MotionForge 将关节恢复零位，再导出工程",
            "en": "Please reset the joint to zero in MotionForge first, then export the project",
        },
        "motion.motionforge_joint_parent_unresolved": {
            "zh-CN": "关节父节点无法绑定到对象",
            "en": "The joint's parent node could not be resolved to an object",
        },
        "motion.motionforge_joint_requires_mesh_node": {
            "zh-CN": "v7 包的关节需绑定到独立网格节点，组节点请先展开",
            "en": "A v7 package's joint must bind to an independent mesh node; please unpack group nodes first",
        },
        "motion.motionforge_multi_clip_unsupported": {
            "zh-CN": "当前支持单片段、固定拓扑的 v7 包；动态换父级请在 MotionForge 中编辑",
            "en": "Currently only single-clip, fixed-topology v7 packages are supported; edit dynamic re-parenting in MotionForge",
        },
        "motion.motionforge_overflow_unsupported": {
            "zh-CN": "当前导入不支持双段门架 overflow；请先烘焙为关键帧",
            "en": "This import does not support two-stage gantry overflow; please bake to keyframes first",
        },
        "motion.motionforge_scene_markers_unsupported": {
            "zh-CN": "含场景标记的运动包请先在 MotionForge 整理后导入",
            "en": "Motion packages with scene markers must be cleaned up in MotionForge before importing",
        },
        "motion.motionforge_units_mismatch": {
            "zh-CN": "MotionForge 包需要原生米制/Z-up 约定",
            "en": "MotionForge packages need the native metres/Z-up convention",
        },
        "motion.package_glb_requires_self_contained": {
            "zh-CN": "运动包 GLB 必须自包含，不能引用本地或远程外部文件",
            "en": "The motion package GLB must be self-contained; it cannot reference local or remote external files",
        },
        "motion.package_too_large_or_duplicate": {
            "zh-CN": "运动包过大或文件重复",
            "en": "Motion package is too large or has duplicate files",
        },
        "motion.pkf_step_missing_bone": {
            "zh-CN": "PKF 步骤引用不存在的骨骼",
            "en": "A PKF step references a bone that does not exist",
        },
        "motion.requires_decompression": {
            "zh-CN": "请先解压 Draco/Meshopt/KTX2，再导入动作编辑",
            "en": "Please decompress Draco/Meshopt/KTX2 first, then import for motion editing",
        },
        "motion.requires_motion": {
            "zh-CN": "请先为模型添加动作",
            "en": "Please add motion to the model first",
        },
        "motion.requires_self_contained": {
            "zh-CN": "动作模型必须是自包含 GLB",
            "en": "Motion model must be a self-contained GLB",
        },
        "motion.requires_single_embedded_buffer": {
            "zh-CN": "动作 GLB 需要单一内嵌二进制 buffer，请从 Blender 重新导出 GLB",
            "en": "Motion GLB needs a single embedded binary buffer; please re-export the GLB from Blender",
        },
        "motion.requires_single_selection": {
            "zh-CN": "每次编辑一个对象的动作；多对象操作分别检查版本",
            "en": "Edit one object's motion at a time; check versions separately for multi-object operations",
        },
        "motion.rig_asset_checksum_mismatch": {
            "zh-CN": "骨架资产校验失败",
            "en": "Rig asset checksum failed",
        },
        "motion.rig_asset_must_use_import": {
            "zh-CN": "骨架必须通过 motion_import 导入，不能借参数切换资产",
            "en": "A rig must be imported via motion_import; its asset cannot be swapped through parameters",
        },
        "motion.rig_asset_too_large": {
            "zh-CN": "骨骼资产超过 500 MB",
            "en": "Rig asset exceeds 500 MB",
        },
        "motion.rig_import_summary": {
            "zh-CN": "导入骨架 · {bones} 骨 / {clips} 片段",
            "en": "Imported rig - {bones} bones / {clips} clips",
        },
        "motion.set_summary": {
            "zh-CN": "更新 {name} 的动作",
            "en": "Updated {name}'s motion",
        },
        "motion.unknown_action": {
            "zh-CN": "未知动作操作",
            "en": "Unknown motion action",
        },
        "motion.unsupported_animation_channel": {
            "zh-CN": "动作编辑支持节点 TRS 通道；材质动画或其他通道请在 Blender 烘焙后导入",
            "en": "Motion editing supports node TRS channels; material animation or other channels should be baked in Blender before importing",
        },
        "motion.unsupported_motionforge_schema": {
            "zh-CN": "仅支持 MotionForge schema v7",
            "en": "Only MotionForge schema v7 is supported",
        },
        "motion.worker_evaluation_failed": {
            "zh-CN": "动作求值失败",
            "en": "Motion evaluation failed",
        },
        "motion.worker_process_unavailable": {
            "zh-CN": "动作求值进程不可用：{error}",
            "en": "Motion evaluation process unavailable: {error}",
        },
        "scene_assets.animation_keyframe_count_mismatch": {
            "zh-CN": "动画关键帧数量不符",
            "en": "Animation keyframe count does not match",
        },
        "scene_assets.animation_non_finite_or_unordered_time": {
            "zh-CN": "动画包含非有限数值或无序时间",
            "en": "Animation contains non-finite values or unordered time",
        },
        "scene_assets.animation_time_bound_mismatch": {
            "zh-CN": "动画时间上界与数据不符",
            "en": "Animation time upper bound does not match the data",
        },
        "scene_assets.asset_hash_mismatch": {
            "zh-CN": "场景源资产哈希不符",
            "en": "Scene source asset hash does not match",
        },
        "scene_assets.asset_summary_mismatch": {
            "zh-CN": "场景资产摘要不符",
            "en": "Scene asset summary does not match",
        },
        "scene_assets.blend_path_requires_skin": {
            "zh-CN": "blend_path 目前只用于完整骨架替换",
            "en": "blend_path is currently only used for full-rig replacement",
        },
        "scene_assets.buffer_view_out_of_range": {
            "zh-CN": "GLB bufferView 超出资产范围",
            "en": "GLB bufferView is out of range of the asset",
        },
        "scene_assets.clip_duration_out_of_range": {
            "zh-CN": "片段长度须为 0–120 秒，请先裁剪",
            "en": "Clip length must be 0-120 seconds; please trim it first",
        },
        "scene_assets.export_summary": {
            "zh-CN": "导出实例编辑源 GLB（局部米制 Y-up，保留全部源动画）",
            "en": "Exported the instance's editable source GLB (local metres/Y-up, all source animation kept)",
        },
        "scene_assets.external_textures": {
            "zh-CN": "请先打包外部贴图",
            "en": "Please pack external textures first",
        },
        "scene_assets.has_morph_targets": {
            "zh-CN": "含 morph 的资产请先在 Blender 整理，不会静默丢失形变",
            "en": "Assets with morph targets must be flattened in Blender first, or their deformation would be silently lost",
        },
        "scene_assets.hierarchy_cycle": {
            "zh-CN": "场景层级成环",
            "en": "Cyclic scene hierarchy",
        },
        "scene_assets.import_summary": {
            "zh-CN": "导入 {count} 个场景实例，保留层级、骨架与动画",
            "en": "Imported {count} scene instance(s), keeping hierarchy, rig and animation",
        },
        "scene_assets.invalid_accessor_index": {
            "zh-CN": "GLB accessor 索引无效",
            "en": "Invalid GLB accessor index",
        },
        "scene_assets.invalid_accessor_type": {
            "zh-CN": "蒙皮 accessor 类型无效",
            "en": "Invalid skin accessor type",
        },
        "scene_assets.invalid_animation_interpolation": {
            "zh-CN": "动画插值无效",
            "en": "Invalid animation interpolation",
        },
        "scene_assets.invalid_animation_or_skin_structure": {
            "zh-CN": "动画或蒙皮数据结构无效",
            "en": "Invalid animation or skin data structure",
        },
        "scene_assets.invalid_animation_sampler_index": {
            "zh-CN": "动画采样器索引无效",
            "en": "Invalid animation sampler index",
        },
        "scene_assets.invalid_binary_chunk": {
            "zh-CN": "GLB 二进制分块无效",
            "en": "Invalid GLB binary chunk",
        },
        "scene_assets.invalid_color": {
            "zh-CN": "颜色无效",
            "en": "Invalid color",
        },
        "scene_assets.invalid_glb_header": {
            "zh-CN": "需要完整的 GLB 2.0 文件，且小于 500 MB",
            "en": "A complete GLB 2.0 file under 500 MB is required",
        },
        "scene_assets.invalid_hierarchy_or_multi_parent": {
            "zh-CN": "场景层级节点无效或有多个父级",
            "en": "Invalid scene hierarchy node, or a node has more than one parent",
        },
        "scene_assets.invalid_import_file_count": {
            "zh-CN": "请提供 1–50 个 GLB 路径，每个文件导入为一个完整场景实例",
            "en": "Please provide 1-50 GLB paths; each file is imported as one full scene instance",
        },
        "scene_assets.invalid_json": {
            "zh-CN": "GLB JSON 无效",
            "en": "Invalid GLB JSON",
        },
        "scene_assets.invalid_json_chunk": {
            "zh-CN": "GLB JSON 分块无效",
            "en": "Invalid GLB JSON chunk",
        },
        "scene_assets.invalid_local_path": {
            "zh-CN": "请选择小于 500 MB 的本地 GLB 绝对路径",
            "en": "Please choose a local GLB absolute path under 500 MB",
        },
        "scene_assets.invalid_or_duplicate_animation_target": {
            "zh-CN": "动画目标无效或重复",
            "en": "Invalid or duplicate animation target",
        },
        "scene_assets.invalid_scene_reference": {
            "zh-CN": "场景实例引用无效",
            "en": "Invalid scene instance reference",
        },
        "scene_assets.invalid_scene_root": {
            "zh-CN": "场景根节点无效",
            "en": "Invalid scene root node",
        },
        "scene_assets.invalid_skin_joint_index": {
            "zh-CN": "蒙皮骨骼索引无效",
            "en": "Invalid skin joint index",
        },
        "scene_assets.invalid_transform_values": {
            "zh-CN": "场景变换包含无效数值",
            "en": "Scene transform contains invalid values",
        },
        "scene_assets.material_slots_changed": {
            "zh-CN": "材质槽已改变，请重新读取",
            "en": "Material slots have changed; please reload",
        },
        "scene_assets.material_value_out_of_range": {
            "zh-CN": "材质数值须为 0–1",
            "en": "Material values must be between 0 and 1",
        },
        "scene_assets.missing_default_scene": {
            "zh-CN": "缺少有效的默认场景",
            "en": "Missing a valid default scene",
        },
        "scene_assets.motion_asset_version_mismatch": {
            "zh-CN": "场景与动作源版本不一致",
            "en": "Scene and motion source versions do not match",
        },
        "scene_assets.node_count_out_of_range": {
            "zh-CN": "场景节点为空或超过 20000",
            "en": "The scene has no nodes, or more than 20000",
        },
        "scene_assets.replace_summary": {
            "zh-CN": "已原位更新选中实例；保留身份与摆放，新骨架/片段重新载入",
            "en": "Updated the selected instance in place; identity and placement are kept, the new rig/clips are reloaded",
        },
        "scene_assets.replace_validation_note": {
            "zh-CN": "GLB、层级、有限几何及蒙皮结构已检查；形变自然度需观察验收",
            "en": "GLB, hierarchy, finite geometry and skin structure were checked; natural-looking deformation still needs visual review",
        },
        "scene_assets.requires_decompression": {
            "zh-CN": "场景编辑请先在 Blender 解压 Draco/Meshopt/KTX2",
            "en": "Please decompress Draco/Meshopt/KTX2 in Blender before scene editing",
        },
        "scene_assets.requires_self_contained": {
            "zh-CN": "场景资产需要自包含 GLB",
            "en": "Scene assets must be a self-contained GLB",
        },
        "scene_assets.requires_single_selection": {
            "zh-CN": "请选择一个场景实例",
            "en": "Please select one scene instance",
        },
        "scene_assets.scene_animation_trs_only": {
            "zh-CN": "场景动画仅支持节点 TRS",
            "en": "Scene animation only supports node TRS",
        },
        "scene_assets.skin_data_out_of_range": {
            "zh-CN": "蒙皮数据超出二进制范围",
            "en": "Skin data is out of range of the binary chunk",
        },
        "scene_assets.skin_vertex_count_mismatch": {
            "zh-CN": "蒙皮顶点数量不一致",
            "en": "Skin vertex count is inconsistent",
        },
        "scene_assets.skin_weights_invalid": {
            "zh-CN": "蒙皮权重非有限或未归一化",
            "en": "Skin weights are non-finite or not normalized",
        },
        "scene_assets.sparse_accessor_unsupported": {
            "zh-CN": "蒙皮稀疏 accessor 请先在 Blender 转为普通数据",
            "en": "Sparse skin accessors must be converted to regular data in Blender first",
        },
        "scene_assets.texture_replacement_unsupported": {
            "zh-CN": "完整场景资产替换贴图请在 Blender 修改后原位回填；颜色/粗糙度/金属度可直接编辑",
            "en": "To replace textures on a full scene asset, edit it in Blender and re-import in place; color/roughness/metallic can be edited directly",
        },
        "scene_assets.too_many_skin_weight_sets": {
            "zh-CN": "超过四组蒙皮权重请先在 Blender 整理",
            "en": "More than four skin weight sets must be consolidated in Blender first",
        },
        "scene_assets.unknown_action": {
            "zh-CN": "未知场景操作",
            "en": "Unknown scene action",
        },
        "scene_assets.vertex_references_missing_joint": {
            "zh-CN": "顶点引用不存在的骨骼",
            "en": "A vertex references a joint that does not exist",
        },
    }
)
