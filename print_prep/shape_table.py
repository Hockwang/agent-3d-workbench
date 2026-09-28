"""print_prep.shape_table —— 形态标签 -> 朝向策略 + 工艺选择（自有经验数值，SPEC.md §4）。

每一档的取值理由是常识性的切片经验，不引用任何厂商专有数据表：
- generic：不知道是什么形状时先假设它需要的支撑最省——`support` 策略专门去找
  悬空面积最小的摆法；层高用最通用的 0.20mm，不加任何专用工艺项。
- figurine：手办类倾向摆正身位（`upright`，保住造型识别度，不会为了省支撑把
  人物摆成大字躺平），0.16mm 出细节；手办常见悬空的手臂/发梢，所以支撑要能
  从半空里长出来（`support_on_build_plate_only=0`），`tree(auto)` 比 `normal`
  更省料也更好剥离；细长直立件容易在打印中途被风吹/被喷头蹭倒，`brim_type=
  outer_only` + `brim_width=3` 只在外轮廓加一圈裙边增加附着力。
- relief：浮雕/贴脸这类背面本来就是平的，`flat` 摆放天然贴床，正面细节朝上
  不需要任何支撑（`enable_support=0`）。
- mechanical：功能件要结构强度而不是细节，0.20mm 配 4 圈墙（默认 2-3 圈）+
  20% 填充（默认 15%）更抗受力；`flat` 通常能让功能面朝上/朝下贴床减少支撑；
  `support_on_build_plate_only=1` 是因为功能件的支撑面一般在底部，不希望支撑
  长在侧面破坏配合面的表面质量。
"""

from __future__ import annotations

from typing import Any

from .messages import render

VALID_LABELS = ("generic", "figurine", "relief", "mechanical")

_TABLE: dict[str, dict[str, Any]] = {
    "generic": {
        "orient_strategy": "support",
        "layer_height_mm": 0.20,
        "process_overrides": {},
    },
    "figurine": {
        "orient_strategy": "upright",
        "layer_height_mm": 0.16,
        "process_overrides": {
            "enable_support": "1",
            "support_type": "tree(auto)",
            "support_on_build_plate_only": "0",
            "brim_type": "outer_only",
            "brim_width": "3",
        },
    },
    "relief": {
        "orient_strategy": "flat",
        "layer_height_mm": 0.16,
        "process_overrides": {"enable_support": "0"},
    },
    "mechanical": {
        "orient_strategy": "flat",
        "layer_height_mm": 0.20,
        "process_overrides": {
            "wall_loops": "4",
            "sparse_infill_density": "20%",
            "enable_support": "1",
            "support_type": "normal(auto)",
            "support_on_build_plate_only": "1",
        },
    },
}


def normalize_label(label: str | None) -> str:
    """校验并归一化形态标签（缺省 `generic`）；非法值抛 ValueError（用户侧错误）。"""
    label = label or "generic"
    if label not in VALID_LABELS:
        raise ValueError(render("shape_table.unknown_label", label=label, valid_labels=VALID_LABELS))
    return label


def lookup(label: str | None) -> dict[str, Any]:
    """返回该标签的朝向策略 + 层高档位 + 工艺增量（返回拷贝，调用方可放心修改）。"""
    label = normalize_label(label)
    entry = _TABLE[label]
    return {
        "label": label,
        "orient_strategy": entry["orient_strategy"],
        "layer_height_mm": entry["layer_height_mm"],
        "process_overrides": dict(entry["process_overrides"]),
    }
