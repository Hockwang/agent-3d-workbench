"""Message catalog for `studio.core.observation*` and `studio.core.print_state`.

One entry per `EditorError.coded()` / `render()` call site in
`studio/core/observation.py`, `studio/core/observation_run.py`, and
`studio/core/print_state.py` (plus the `model-observe` task-template display
fields in `observation.py`'s `CATALOG`, which `task_templates.localized_catalog()`
renders — see the CATALOG convention in `studio/core/task_templates.py`).
Codes are `<module>.<meaning>`, lower snake_case. The "zh-CN" text below is the
original wording each raise/string used to hardcode, carried over verbatim;
"en" is a faithful translation, not a paraphrase.

`studio/core/observation_render.py` (executed inside Blender's own bundled
Python via a standalone `--python` invocation, with no `sys.path` setup for
the `studio` package) is NOT covered here — see that module's docstring.

Imported (for its `register()` side effect) from `studio/core/__init__.py`.
"""

from studio.i18n import register

register(
    {
        # --- observation.py ---
        "observation.action_invalid": {
            "zh-CN": "观察 action 为 start/read/review/focus",
            "en": "The observation action must be start/read/review/focus",
        },
        "observation.default_title": {
            "zh-CN": "观察 · {labels}",
            "en": "Observation · {labels}",
        },
        "observation.file_not_found": {
            "zh-CN": "文件不存在：{path}",
            "en": "File not found: {path}",
        },
        "observation.glb_json_too_large": {
            "zh-CN": "GLB JSON 过大",
            "en": "GLB JSON is too large",
        },
        "observation.glb_must_be_self_contained": {
            "zh-CN": "观察 GLB 须内嵌全部几何和贴图",
            "en": "GLBs used for observation must embed all geometry and textures",
        },
        "observation.inputs_must_be_absolute": {
            "zh-CN": "输入须为绝对路径",
            "en": "Inputs must be absolute paths",
        },
        "observation.inputs_or_source_tasks_only": {
            "zh-CN": "inputs 与 source_tasks 只能传一种",
            "en": "Pass either inputs or source_tasks, not both",
        },
        "observation.invalid_glb": {
            "zh-CN": "无效 GLB",
            "en": "Invalid GLB",
        },
        "observation.labels_invalid": {
            "zh-CN": "labels 须与输入一一对应，每项 1–100 字",
            "en": "labels must correspond one-to-one with inputs, each 1 to 100 characters",
        },
        "observation.model_observe.description": {
            "zh-CN": "同一尺度、相机和光照观察 GLB/STL/PLY/URDF，交付真实多视图、几何指标和来源指纹",
            "en": (
                "Observe GLB/STL/PLY/URDF under the same scale, camera, and lighting; delivers real multi-view "
                "renders, geometry metrics, and a provenance fingerprint"
            ),
        },
        "observation.model_observe.title": {
            "zh-CN": "观察与版本对比",
            "en": "Observation and version comparison",
        },
        "observation.not_an_observation_task": {
            "zh-CN": "这不是观察任务",
            "en": "This is not an observation task",
        },
        "observation.phases_invalid": {
            "zh-CN": "phases 为 0–1 的采样位置，最多 5 个",
            "en": "phases are sample positions between 0 and 1, at most 5",
        },
        "observation.remote_urdf_resource_unsupported": {
            "zh-CN": "观察只读取本机模型，不获取远端 URDF 资源",
            "en": "Observation only reads local models; it does not fetch remote URDF resources",
        },
        "observation.resolution_invalid": {
            "zh-CN": "resolution 为 256–1024 整数",
            "en": "resolution must be an integer between 256 and 1024",
        },
        "observation.review_requires_verdict_and_note": {
            "zh-CN": "评价需要 verdict 和 1–4000 字理由",
            "en": "A review needs a verdict and a 1 to 4000 character note",
        },
        "observation.review_stale_report": {
            "zh-CN": "观察版本不匹配，请重新 read 后评价",
            "en": "The observation version does not match; please read again before reviewing",
        },
        "observation.source_task_missing_glb": {
            "zh-CN": "来源任务没有 GLB 产物",
            "en": "The source task has no GLB artifact",
        },
        "observation.source_tasks_max": {
            "zh-CN": "source_tasks 至多 4 个",
            "en": "source_tasks accepts at most 4 items",
        },
        "observation.unsupported_format": {
            "zh-CN": "观察支持 GLB/STL/PLY/URDF",
            "en": "Observation supports GLB/STL/PLY/URDF",
        },
        "observation.urdf_external_entities_forbidden": {
            "zh-CN": "URDF 不允许外部实体",
            "en": "URDF does not allow external entities",
        },
        "observation.urdf_joint_cycle": {
            "zh-CN": "URDF joint 存在环",
            "en": "The URDF joints contain a cycle",
        },
        "observation.urdf_joint_references_missing_link": {
            "zh-CN": "URDF joint 引用了不存在的 link",
            "en": "A URDF joint references a link that does not exist",
        },
        "observation.urdf_link_multiple_parents": {
            "zh-CN": "URDF link 具有多个父关节",
            "en": "A URDF link has more than one parent joint",
        },
        "observation.urdf_link_name_invalid": {
            "zh-CN": "URDF link 名称为空或重复",
            "en": "URDF link names are empty or duplicated",
        },
        "observation.urdf_link_tree_invalid": {
            "zh-CN": "URDF 需要一棵完整且无环的 link 树",
            "en": "URDF requires one complete, acyclic tree of links",
        },
        "observation.urdf_texture_must_be_packed": {
            "zh-CN": "请将 URDF 纹理打包到各 visual GLB 中",
            "en": "Please pack URDF textures into each visual GLB",
        },
        "observation.urdf_unreachable_link": {
            "zh-CN": "URDF 有不可达 link，不能作为完整模型观察",
            "en": "URDF has an unreachable link; it cannot be observed as a complete model",
        },
        "observation.urdf_up_invalid": {
            "zh-CN": "urdf_up 需要明确为 y 或 z",
            "en": "urdf_up must be explicitly y or z",
        },
        "observation.urdf_visual_mesh_missing": {
            "zh-CN": "URDF visual 需要存在的 GLB/STL/PLY：{filename}",
            "en": "URDF visual requires an existing GLB/STL/PLY: {filename}",
        },
        "observation.variant_count_invalid": {
            "zh-CN": "每次观察 1–4 个版本；每个 GLB/URDF 代表一个完整版本",
            "en": "Each observation takes 1 to 4 versions; each GLB/URDF represents one complete version",
        },
        "observation.variant_phase_out_of_range": {
            "zh-CN": "variant / phase_index 超出观察范围",
            "en": "variant / phase_index is out of the observation's range",
        },
        "observation.views_invalid": {
            "zh-CN": "views 为 front/right/back/left/top/iso，最多 6 个",
            "en": "views must be from front/right/back/left/top/iso, at most 6",
        },
        # --- observation_run.py ---
        "observation_run.actuated_joint_missing_range": {
            "zh-CN": "可动关节缺少范围：{name}",
            "en": "Actuated joint is missing its range: {name}",
        },
        "observation_run.blender_required": {
            "zh-CN": "多视图观察需要本机 Blender",
            "en": "Multi-view observation requires a local Blender installation",
        },
        "observation_run.input_changed": {
            "zh-CN": "观察期间输入已变化，请重新观察",
            "en": "An input changed during observation; please observe again",
        },
        "observation_run.joint_range_invalid": {
            "zh-CN": "关节范围无效：{name}",
            "en": "Invalid joint range: {name}",
        },
        "observation_run.limitation_geometry_not_semantic": {
            "zh-CN": "几何指标不代表语义/外观/运动正确；没有 GT 时不产生质量分数",
            "en": (
                "Geometry metrics do not imply semantic/appearance/motion correctness; without ground truth, no "
                "quality score is produced"
            ),
        },
        "observation_run.limitation_no_auto_registration": {
            "zh-CN": "相同相机和尺度；没有自动配准、居中或归一化每个版本",
            "en": "Same camera and scale; no automatic registration, centering, or normalization per version",
        },
        "observation_run.limitation_unit_convention": {
            "zh-CN": "STL/PLY 按毫米/Z-up；GLB 按米/Y-up；URDF 坐标系由调用者声明",
            "en": "STL/PLY use mm/Z-up; GLB uses meters/Y-up; the URDF coordinate system is declared by the caller",
        },
        "observation_run.limitation_urdf_phase_sampling": {
            "zh-CN": "URDF 相位在线性范围内采样，不等于连续碰撞检测；GLB 采样 Blender 导入的当前动画",
            "en": (
                "URDF phases are sampled linearly within range and are not continuous collision checking; GLB "
                "samples the animation currently imported by Blender"
            ),
        },
        "observation_run.metrics_pose_bind": {
            "zh-CN": "已存网格 / 绑定姿态",
            "en": "stored mesh / bind pose",
        },
        "observation_run.metrics_pose_urdf_zero": {
            "zh-CN": "URDF 零位配置",
            "en": "URDF zero configuration",
        },
        "observation_run.no_observable_mesh": {
            "zh-CN": "输入没有可观察的三角网格",
            "en": "The input has no observable triangle mesh",
        },
        "observation_run.non_finite_coordinates": {
            "zh-CN": "模型含非有限坐标",
            "en": "The model contains non-finite coordinates",
        },
        "observation_run.render_failed": {
            "zh-CN": "观察图渲染失败，详见任务日志",
            "en": "Observation rendering failed; see the task log for details",
        },
        "observation_run.snapshot_incomplete": {
            "zh-CN": "观察姿态快照没有完整交付",
            "en": "The observation pose snapshot was not fully delivered",
        },
        "observation_run.unsupported_joint_type": {
            "zh-CN": "暂不支持 {type} joint：{name}",
            "en": "{type} joints are not yet supported: {name}",
        },
        "observation_run.variant_count_mismatch": {
            "zh-CN": "需要 1–4 个版本与对应 labels",
            "en": "Requires 1 to 4 versions with matching labels",
        },
        # --- print_state.py ---
        "print_state.not_a_number": {
            "zh-CN": "{field_name} 不是合法数字: {value}",
            "en": "{field_name} is not a valid number: {value}",
        },
        "print_state.not_an_integer": {
            "zh-CN": "{field_name} 不是合法整数: {value}",
            "en": "{field_name} is not a valid integer: {value}",
        },
        "print_state.orient_set_vector_length": {
            "zh-CN": "orient 的 set 向量必须是长度为 3 的数组: {entry}",
            "en": "orient's set vector must be an array of length 3: {entry}",
        },
        "print_state.orient_set_vector_not_numeric": {
            "zh-CN": "orient 的 set 向量分量不是合法数字: {entry}",
            "en": "orient's set vector has a component that is not a valid number: {entry}",
        },
        "print_state.unknown_choice": {
            "zh-CN": "未知的 {field_name}: {value}",
            "en": "Unknown {field_name}: {value}",
        },
    }
)
