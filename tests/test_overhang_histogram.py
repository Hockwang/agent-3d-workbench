"""SPEC.md §5 第 7 条：悬空面积的直方图近似与逐面精确值在一个球体加一个悬臂盒的
合成件上相差 < 2%。"""

from __future__ import annotations

import numpy as np
import trimesh

from print_prep import orient


def _sphere_plus_cantilever_box() -> trimesh.Trimesh:
    sphere = trimesh.creation.icosphere(subdivisions=3, radius=10.0)
    box = trimesh.creation.box(extents=[6.0, 6.0, 20.0])
    box.apply_translation([16.0, 0.0, 5.0])  # 悬在球体侧面，下方没有支撑
    return trimesh.util.concatenate([sphere, box])


def test_histogram_overhang_matches_exact_within_two_percent():
    mesh = _sphere_plus_cantilever_box()
    hist = orient.direction_histogram(mesh, angle_tol_deg=1.0)

    test_ups = [
        np.array([0.0, 0.0, 1.0]),
        np.array([1.0, 0.0, 0.0]),
        np.array([0.3, 0.1, 0.95]),
        np.array([0.5, 0.5, 0.7]),
    ]
    for raw_up in test_ups:
        up = raw_up / np.linalg.norm(raw_up)
        approx = orient.overhang_area_histogram(hist, up, angle_deg=30.0)
        exact = orient.overhang_area_exact(mesh, up, angle_deg=30.0, exclude_base=False)
        assert exact > 0.0, "这个合成件在测试方向上应该本来就有悬空面积，不然测试没有意义"
        rel_err = abs(approx - exact) / exact
        assert rel_err < 0.02, f"up={up}: approx={approx} exact={exact} rel_err={rel_err}"
