"""SPEC.md §3.3（修订）+ §5 第 9 条：flat 预筛只作用于斐波那契候选、support 的
稳定下限、upright 的退让规则、`stability_warnings`、`manual_result`。"""

from __future__ import annotations

import numpy as np
import trimesh

from print_prep import orient


def _twelve_gon_prism() -> trimesh.Trimesh:
    """外接半径 20、高 20 的正十二棱柱：两端平底各约 1200 mm^2，12 个侧面各约
    207 mm^2；候选总数（大平面片 14 + 六坐标轴 - 2 重复 = 18）> 12，能复现旧的
    "预筛把大平底筛掉"缺陷。"""
    return trimesh.creation.cylinder(radius=20.0, height=20.0, sections=12)


def test_flat_prefilter_regression_prism_picks_flat_base():
    mesh = _twelve_gon_prism()
    candidates, _forced = orient.candidate_directions(mesh, include_fibonacci=False)
    assert len(candidates) > 12, "候选数必须超过 top_k=12 才能复现旧缺陷"

    result = orient.choose_orientation(mesh, "flat")
    assert result["strategy_used"] == "flat"
    assert result["contact_area_mm2"] > 1100.0, "必须选到平底朝下，不是侧面朝下（旧缺陷是 207mm^2）"
    assert abs(result["height_mm"] - 20.0) < 0.5


def test_flat_prefilter_regression_prism_support_strategy():
    mesh = _twelve_gon_prism()
    result = orient.choose_orientation(mesh, "support")
    assert result["contact_area_mm2"] >= orient.STABLE_CONTACT_MM2
    assert result["warnings"] == []


def test_upright_rejects_tip_only_contact_and_falls_back():
    # 圆锥尖朝下：默认 trimesh.creation.cone 底面在 z=0、尖端在 +Z；绕 X 轴翻转
    # 180 度后尖端到 -Z，底面法向翻到 +Z——+Z 方向此时只有尖端触底（面积≈0）。
    cone = trimesh.creation.cone(radius=10.0, height=20.0, sections=32)
    cone.apply_transform(trimesh.transformations.rotation_matrix(np.pi, [1.0, 0.0, 0.0]))

    source_metrics = orient.evaluate_orientation(cone, (0.0, 0.0, 1.0))
    assert source_metrics["contact_area_mm2"] < orient.STABLE_CONTACT_MM2, "测试前提：+Z 朝上应只有尖端触底"

    result = orient.choose_orientation(cone, "upright")
    assert result["upright_rejected"] is True
    assert result["strategy_used"] == "support"
    assert isinstance(result["upright_rejected_reason"], str) and result["upright_rejected_reason"]
    assert result["contact_area_mm2"] >= orient.STABLE_CONTACT_MM2


def test_upright_keeps_plus_z_for_ordinary_box():
    box = trimesh.creation.box(extents=[30.0, 20.0, 10.0])
    result = orient.choose_orientation(box, "upright")
    assert result["print_up"] == [0.0, 0.0, 1.0]
    assert result["upright_rejected"] is False
    assert result["upright_rejected_reason"] is None
    assert result["strategy_used"] == "upright"


def test_stability_warnings_flags_sphere_in_every_orientation():
    sphere = trimesh.creation.icosphere(subdivisions=2, radius=5.0)
    for up in orient.AXES6:
        metrics = orient.evaluate_orientation(sphere, up)
        assert orient.stability_warnings(metrics) == ["unstable_contact"]

    result = orient.choose_orientation(sphere, "support")
    assert result["warnings"] == ["unstable_contact"]
    assert result["contact_area_mm2"] < orient.STABLE_CONTACT_MM2


def test_manual_result_shape_and_content():
    box = trimesh.creation.box(extents=[30.0, 20.0, 5.0])
    result = orient.manual_result(box, (0.0, 0.0, 1.0))

    expected_keys = {
        "print_up",
        "strategy_used",
        "contact_area_mm2",
        "overhang_area_mm2",
        "height_mm",
        "upright_rejected",
        "upright_rejected_reason",
        "warnings",
        "top_candidates",
    }
    assert expected_keys.issubset(result.keys())
    assert result["strategy_used"] == "manual"
    assert result["print_up"] == [0.0, 0.0, 1.0]
    assert result["upright_rejected"] is False
    assert result["upright_rejected_reason"] is None
    assert abs(result["contact_area_mm2"] - 600.0) < 1e-6
    assert len(result["top_candidates"]) == 1
