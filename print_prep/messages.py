"""Standalone bilingual message catalog for `print_prep.*` raises and UI-facing
strings (report lines, `job.json` `warnings`/`notes`/`error` fields, argparse
help/description text).

`print_prep` is layer A (`tests/test_layering.py` forbids any
`print_prep -> studio` import), so it cannot import `studio.i18n` directly and
instead carries its own tiny, dependency-free copy of the same catalog/render
machinery: a `MESSAGES` dict, `register()`, and `render()` with the same
en -> zh-CN -> bare-code fallback chain. When `studio` is present,
`studio/i18n.py` wires `language_provider` (see its bottom, guarded by
`try/except ImportError` so this module also works standalone, e.g. from a
Blender add-on that never imports `studio`) to `studio.i18n.get_language`, so
the per-request/CLI language chosen at the studio layer flows down into
print_prep's own renders without print_prep ever knowing `studio` exists.
When nothing has set `language_provider` (print_prep used on its own, outside
the plugin), language falls back directly to the `STUDIO_LANG` environment
variable — the same variable and normalization studio.i18n uses — so a bare
`print_prep.cli` invocation still respects it.

One entry per `raise ...Error(...)` call site under `print_prep/` that used
to hardcode Chinese text, plus every UI-facing string (job.json `warnings`,
`notes`, `error` values, and argparse `help`/`description` text) rendered at
the point it is produced. Codes are `<module>.<meaning>`, lower snake_case.
The "zh-CN" text below is the original wording each site used to hardcode,
carried over verbatim; "en" is a faithful translation, not a paraphrase. A
handful of sites (`arrange.py`'s `prepare_item` bed-height check, `cli.py`'s
"missing subcommand") were already English-only — those keep their original
text under "en" and gain a new "zh-CN" translation here.
"""

from __future__ import annotations

import os
from typing import Callable, Optional

SUPPORTED_LANGUAGES: tuple[str, ...] = ("en", "zh-CN")
DEFAULT_LANGUAGE = "en"

# code -> {"en": ..., "zh-CN": ...}
MESSAGES: dict[str, dict[str, str]] = {}

# Set by `studio/i18n.py` (guarded by `try/except ImportError`) to
# `studio.i18n.get_language` when `studio` is importable, so the per-request
# language chosen at the studio layer flows down here. `None` means "no
# studio wiring" (print_prep used standalone) -> fall back to `STUDIO_LANG`.
language_provider: Optional[Callable[[], str]] = None


def register(messages: dict[str, dict[str, str]]) -> None:
    """Merge a mapping of code -> {"en", "zh-CN"} into the module registry.

    A code already registered with *different* text raises immediately
    (codes are meant to be unique within this catalog); re-registering the
    exact same mapping is a no-op, not an error.
    """
    for code, translations in messages.items():
        existing = MESSAGES.get(code)
        if existing is not None and existing != translations:
            raise ValueError(f"message code {code!r} already registered with different text")
        MESSAGES[code] = translations


def normalize(lang: Optional[str]) -> str:
    """Map an arbitrary language tag to one of `SUPPORTED_LANGUAGES`.

    Case-insensitive. "en", "en-US", ... -> "en". "zh", "zh-CN", "zh-Hans",
    any "zh-*"/"zh_*" -> "zh-CN". Anything else, including `None` or an empty
    string, falls back to `DEFAULT_LANGUAGE` ("en").
    """
    if not lang:
        return DEFAULT_LANGUAGE
    tag = lang.strip().lower()
    if tag == "en" or tag.startswith("en-") or tag.startswith("en_"):
        return "en"
    if tag == "zh" or tag.startswith("zh-") or tag.startswith("zh_"):
        return "zh-CN"
    return DEFAULT_LANGUAGE


def get_language() -> str:
    """The language in effect right now: `language_provider()` if set (the
    studio wiring), else `normalize(os.environ["STUDIO_LANG"])`, else "en".
    Never raises: a broken `language_provider` is treated as "unset"."""
    if language_provider is not None:
        try:
            lang = language_provider()
        except Exception:  # noqa: BLE001 -- render() must never raise
            lang = None
        if lang:
            return normalize(lang)
    return normalize(os.environ.get("STUDIO_LANG"))


class _SafeFormatDict(dict):
    """`str.format_map` helper: a missing `{placeholder}` renders back as
    literally `{placeholder}` instead of raising `KeyError`."""

    def __missing__(self, key):  # noqa: D105
        return "{" + str(key) + "}"


def render(code: str, **params) -> str:
    """Render message `code` in the language `get_language()` currently
    reports. Falls back en -> zh-CN -> the bare code itself if `code` is
    unknown or missing a translation for every language. Never raises: a
    malformed format string (or a param that doesn't match `{}` count) just
    yields the unformatted text."""
    translations = MESSAGES.get(code)
    if not translations:
        return code
    lang = get_language()
    text = translations.get(lang) or translations.get("en") or translations.get("zh-CN") or code
    try:
        return text.format_map(_SafeFormatDict(params))
    except (ValueError, IndexError):
        return text


register(
    {
        # --- arrange.py ---
        "arrange.gap_negative": {
            "zh-CN": "gap_mm 必须 >= 0，收到: {gap_mm}",
            "en": "gap_mm must be >= 0; got: {gap_mm}",
        },
        "arrange.part_too_large": {
            "zh-CN": "part {name!r} 尺寸 {dims_mm} 超出可用区 {avail_dims}；建议缩放到 {suggested_scale}",
            "en": "part {name!r} size {dims_mm} exceeds the usable area {avail_dims}; suggest scaling to {suggested_scale}",
        },
        "arrange.parts_dropped": {
            "zh-CN": "零件不能静默丢失: 输入 {input_names} != 摆盘输出 {placed_names}",
            "en": "Parts must not be silently dropped: input {input_names} != plate output {placed_names}",
        },
        "arrange.single_plate_overflow": {
            "zh-CN": "single 模式放不下全部零件；改用 auto 需要 {needed_plates} 盘",
            "en": "single mode cannot fit all parts; switching to auto would need {needed_plates} plate(s)",
        },
        "arrange.unknown_mode": {
            "zh-CN": "未知的 mode: {mode!r}，可选 {valid_modes}",
            "en": "Unknown mode: {mode!r}; choices are {valid_modes}",
        },
        "arrange.zero_vector": {
            "zh-CN": "零向量不能归一化: {v}",
            "en": "Cannot normalize a zero vector: {v}",
        },
        # --- bambu.py ---
        "bambu.result_json_missing": {
            "zh-CN": "result.json 不存在（returncode={returncode}）",
            "en": "result.json does not exist (returncode={returncode})",
        },
        "bambu.result_json_parse_failed": {
            "zh-CN": "result.json 解析失败: {error}",
            "en": "Failed to parse result.json: {error}",
        },
        "bambu.slice_timeout": {
            "zh-CN": "切片超时（{timeout_s}s）",
            "en": "Slicing timed out ({timeout_s}s)",
        },
        "bambu.studio_not_found": {
            "zh-CN": "找不到 Bambu Studio 可执行文件: {binary}",
            "en": "Bambu Studio executable not found: {binary}",
        },
        # --- cli.py ---
        "cli.app_not_found": {
            "zh-CN": "找不到 Bambu Studio 应用: {app}",
            "en": "Bambu Studio application not found: {app}",
        },
        "cli.bad_angle_deg": {
            "zh-CN": "--angle-deg 必须在 {min:g} 到 {max:g} 度之间，收到: {angle_deg}",
            "en": "--angle-deg must be between {min:g} and {max:g} degrees; got: {angle_deg}",
        },
        "cli.bad_gap": {
            "zh-CN": "--gap 必须 >= 0，收到: {gap}",
            "en": "--gap must be >= 0; got: {gap}",
        },
        "cli.bad_scale": {
            "zh-CN": "--scale 必须 > 0，收到: {scale}",
            "en": "--scale must be > 0; got: {scale}",
        },
        "cli.bad_strategy": {
            "zh-CN": "未知的 --strategy: {strategy!r}",
            "en": "Unknown --strategy: {strategy!r}",
        },
        "cli.bad_target_max_mm": {
            "zh-CN": "--target-max-mm 必须 > 0，收到: {target_max_mm}",
            "en": "--target-max-mm must be > 0; got: {target_max_mm}",
        },
        "cli.bambu_export_failed": {
            "zh-CN": "plate {plate} Bambu Studio 导出失败",
            "en": "plate {plate} Bambu Studio export failed",
        },
        "cli.degenerate_extent": {
            "zh-CN": "全体零件合并包围盒的最长边是 0，无法按 --target-max-mm 缩放",
            "en": "The combined bounding box of all parts has a longest edge of 0; cannot scale by --target-max-mm",
        },
        "cli.description": {
            "zh-CN": "把网格做成可打印的 Bambu Studio 工程",
            "en": "Turn a mesh into a printable Bambu Studio project",
        },
        "cli.fallback_process_warning": {
            "zh-CN": "没有找到 compatible_printers 含 {printer!r} 且 layer_height={layer_height_mm} 的系统预设，回退到机器的 default_print_profile",
            "en": (
                "No system preset was found with compatible_printers containing {printer!r} and "
                "layer_height={layer_height_mm}; falling back to the machine's default_print_profile"
            ),
        },
        "cli.file_not_found": {
            "zh-CN": "文件不存在: {file}",
            "en": "File does not exist: {file}",
        },
        "cli.missing_default_filament": {
            "zh-CN": "机器预设没有默认耗材，且未指定 --filament",
            "en": "The machine preset has no default filament, and --filament was not specified",
        },
        "cli.missing_profiles": {
            "zh-CN": "job.json 的 profiles 目录缺文件，无法试切",
            "en": "job.json's profiles directory is missing files; cannot test-slice",
        },
        "cli.missing_project_3mf": {
            "zh-CN": "plate {plate} 没有 project_3mf（export 时用了 --no-project？）",
            "en": "plate {plate} has no project_3mf (was --no-project used during export?)",
        },
        "cli.missing_step_arrange": {
            "zh-CN": "arrange 需要先跑 orient",
            "en": "arrange requires orient to run first",
        },
        "cli.missing_step_check": {
            "zh-CN": "check 需要先跑 export",
            "en": "check requires export to run first",
        },
        "cli.missing_step_export": {
            "zh-CN": "export 需要先跑 arrange",
            "en": "export requires arrange to run first",
        },
        "cli.missing_step_open": {
            "zh-CN": "open 需要先跑 export",
            "en": "open requires export to run first",
        },
        "cli.missing_step_orient": {
            "zh-CN": "orient 需要先跑 inspect",
            "en": "orient requires inspect to run first",
        },
        "cli.missing_subcommand": {
            "zh-CN": "缺少子命令",
            "en": "missing subcommand",
        },
        "cli.no_parts": {
            "zh-CN": "没有载入任何零件",
            "en": "No parts were loaded",
        },
        "cli.plate_not_found": {
            "zh-CN": "没有第 {plate} 盘",
            "en": "There is no plate {plate}",
        },
        "cli.project_geometry_changed": {
            "zh-CN": "plate {plate} Bambu 工程写出后拓扑改变；原始 geometry.3mf 已保留，请勿将该工程视为保真交付",
            "en": (
                "plate {plate}'s topology changed after the Bambu project was written; the original "
                "geometry.3mf was kept — do not treat this project as a faithful deliverable"
            ),
        },
        "cli.readback_failed": {
            "zh-CN": "plate {plate} 几何 3MF 读回校验失败: max_error_mm={max_error_mm}",
            "en": "plate {plate} geometry 3MF readback check failed: max_error_mm={max_error_mm}",
        },
        "cli.scale_and_target_conflict": {
            "zh-CN": "--scale 与 --target-max-mm 互斥",
            "en": "--scale and --target-max-mm are mutually exclusive",
        },
        "cli.set_kv_bad_format": {
            "zh-CN": "--set 参数格式应为 key=value，收到: {entry!r}",
            "en": "--set parameter format must be key=value; got: {entry!r}",
        },
        "cli.set_vec3_bad_format": {
            "zh-CN": "--set 参数格式应为 NAME=x,y,z，收到: {entry!r}",
            "en": "--set parameter format must be NAME=x,y,z; got: {entry!r}",
        },
        "cli.set_vec3_not_number": {
            "zh-CN": "--set 参数的向量不是合法数字: {entry!r}",
            "en": "--set parameter's vector is not a valid number: {entry!r}",
        },
        "cli.set_vec3_wrong_arity": {
            "zh-CN": "--set 参数的向量应为 x,y,z 三个数，收到: {entry!r}",
            "en": "--set parameter's vector must have exactly 3 numbers x,y,z; got: {entry!r}",
        },
        "cli.set_vec3_zero_vector": {
            "zh-CN": "--set 参数不能是零向量: {entry!r}",
            "en": "--set parameter cannot be a zero vector: {entry!r}",
        },
        "cli.slice_failed": {
            "zh-CN": "切片失败",
            "en": "Slicing failed",
        },
        "cli.slice_fallback_note": {
            "zh-CN": "plate {plate}: 不带 --slice 导出被拒绝，已改用 --slice 0",
            "en": "plate {plate}: export without --slice was rejected; fell back to --slice 0",
        },
        "cli.unknown_part_in_set": {
            "zh-CN": "--set 引用了不存在的零件: {unknown}",
            "en": "--set references parts that do not exist: {unknown}",
        },
        "cli.unknown_printer": {
            "zh-CN": "未知的打印机: {printer!r}",
            "en": "Unknown printer: {printer!r}",
        },
        # --- export3mf.py ---
        "export3mf.ambiguous_part_binding": {
            "zh-CN": "无法唯一绑定 Bambu 输出零件与源几何",
            "en": "Cannot uniquely bind the Bambu output part to the source geometry",
        },
        "export3mf.missing_output_part": {
            "zh-CN": "缺少输出零件",
            "en": "Missing output part",
        },
        # --- mesh_io.py ---
        "mesh_io.empty_geometry": {
            "zh-CN": "{path} 是空几何",
            "en": "{path} has empty geometry",
        },
        "mesh_io.file_not_found": {
            "zh-CN": "文件不存在: {path}",
            "en": "File does not exist: {path}",
        },
        "mesh_io.load_failed": {
            "zh-CN": "无法载入 {path}: {error}",
            "en": "Failed to load {path}: {error}",
        },
        "mesh_io.no_usable_geometry": {
            "zh-CN": "{path} 没有可用的几何",
            "en": "{path} has no usable geometry",
        },
        "mesh_io.unrecognized_load_result": {
            "zh-CN": "{path} 载入结果既不是 Trimesh 也不是 Scene: {loaded_type!r}",
            "en": "{path} loaded as neither a Trimesh nor a Scene: {loaded_type!r}",
        },
        "mesh_io.unsupported_file_type": {
            "zh-CN": "不支持的文件类型: {suffix!r} ({path})",
            "en": "Unsupported file type: {suffix!r} ({path})",
        },
        "mesh_io.warning_disconnected_components": {
            "zh-CN": "part {name!r}: {components} disconnected components",
            "en": "part {name!r}: {components} disconnected components",
        },
        "mesh_io.warning_face_count_exceeds": {
            "zh-CN": "part {name!r}: {faces} faces exceeds 2,000,000",
            "en": "part {name!r}: {faces} faces exceeds 2,000,000",
        },
        "mesh_io.warning_not_watertight": {
            "zh-CN": "part {name!r}: not watertight",
            "en": "part {name!r}: not watertight",
        },
        "mesh_io.warning_unit_suspect_high": {
            "zh-CN": "part {name!r}: longest edge {max_extent:.3f}mm > 2000mm (可能单位错误)",
            "en": "part {name!r}: longest edge {max_extent:.3f}mm > 2000mm (possibly a unit mistake)",
        },
        "mesh_io.warning_unit_suspect_low": {
            "zh-CN": "part {name!r}: longest edge {max_extent:.3f}mm < 5mm (可能单位错误)",
            "en": "part {name!r}: longest edge {max_extent:.3f}mm < 5mm (possibly a unit mistake)",
        },
        # --- orient.py ---
        "orient.unknown_strategy": {
            "zh-CN": "未知的朝向策略: {strategy!r}",
            "en": "Unknown orientation strategy: {strategy!r}",
        },
        "orient.upright_rejected_reason": {
            "zh-CN": "+Z 方向贴床面积仅 {contact_area_mm2:.3f} mm^2，低于稳定下限 {stable_contact_mm2:g} mm^2，已改用 support 策略选出的朝向",
            "en": (
                "+Z contact area is only {contact_area_mm2:.3f} mm^2, below the stable minimum of "
                "{stable_contact_mm2:g} mm^2; switched to the orientation chosen by the support strategy"
            ),
        },
        "orient.zero_vector": {
            "zh-CN": "零向量不能归一化: {v}",
            "en": "Cannot normalize a zero vector: {v}",
        },
        # --- profiles.py ---
        "profiles.dir_missing": {
            "zh-CN": "profile 目录不存在: {dir}",
            "en": "Profile directory does not exist: {dir}",
        },
        "profiles.inherits_cycle": {
            "zh-CN": "预设 inherits 成环: {chain}",
            "en": "Preset inherits form a cycle: {chain}",
        },
        "profiles.not_found": {
            "zh-CN": "找不到预设: {name!r}",
            "en": "Preset not found: {name!r}",
        },
        "profiles.parse_failed": {
            "zh-CN": "无法解析预设文件 {path}: {error}",
            "en": "Failed to parse preset file {path}: {error}",
        },
        # --- shape_table.py ---
        "shape_table.unknown_label": {
            "zh-CN": "未知的形态标签 {label!r}，可选 {valid_labels}",
            "en": "Unknown shape label {label!r}; choices are {valid_labels}",
        },
    }
)
