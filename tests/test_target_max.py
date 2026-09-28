"""SPEC.md §5 第 14 条：`--target-max-mm` 必须按"全体零件的合并包围盒（各件
保持在源文件里的位置，即装配坐标系）的最长边"来算缩放系数，不是"逐件取各自
最长边里的最大值"。

三个 100mm 的盒子分别摆在 (0,0,0)/(900,0,0)/(0,900,0)：单件的最长边都只有
100mm（如果错误地按"每件最长边的最大值"算，`--target-max-mm 180` 会得到
`180/100=1.8`），但三件合并后的装配包围盒横跨 x: [-50,950]、y: [-50,950]，
最长边是 1000mm——正确答案是 `180/1000=0.18`。
"""

from __future__ import annotations

import numpy as np
import pytest
import trimesh


def _write_three_boxes_glb(path) -> None:
    scene = trimesh.Scene()
    positions = [(0.0, 0.0, 0.0), (900.0, 0.0, 0.0), (0.0, 900.0, 0.0)]
    for i, pos in enumerate(positions):
        box = trimesh.creation.box(extents=[100.0, 100.0, 100.0])
        transform = np.eye(4)
        transform[:3, 3] = pos
        scene.add_geometry(box, node_name=f"box{i}", transform=transform)
    scene.export(path, file_type="glb")


def test_target_max_mm_uses_combined_assembly_bbox_not_per_part_max(tmp_path, run):
    glb_path = tmp_path / "three_boxes.glb"
    _write_three_boxes_glb(glb_path)
    job_dir = tmp_path / "job"

    exit_code, payload, _ = run(["inspect", "--job", str(job_dir), str(glb_path), "--target-max-mm", "180"])
    assert exit_code == 0
    assert payload["ok"] is True
    assert len(payload["parts"]) == 3
    assert payload["scale_applied"] == pytest.approx(0.18, abs=1e-9)

    # 每件缩放后的最长边应该都还是 100 * 0.18 = 18mm（单件尺寸没有被错误地
    # 单独拿去对齐 180mm）。
    for part in payload["parts"]:
        assert max(part["extents_mm"]) == pytest.approx(18.0, abs=1e-6)
