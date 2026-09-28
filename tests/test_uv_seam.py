"""SPEC.md §5 第 4 条：带 UV 缝的网格（人为把一个立方体的顶点按面拆开）
components == 1、watertight == true。

`trimesh.Trimesh.unmerge_vertices()` 就是"把顶点按面拆开"本身（每个三角形拿到
自己独立的一份顶点，跟 UV 展开在缝上把同位置顶点拆成多份是同一种连通性破坏）。
"""

from __future__ import annotations

import trimesh

from print_prep import mesh_io


def _unmerged_cube() -> trimesh.Trimesh:
    box = trimesh.creation.box(extents=[10.0, 10.0, 10.0])
    box.unmerge_vertices()
    return box


def test_unmerge_vertices_actually_breaks_naive_connectivity():
    """先确认合成手法本身有效：不做任何修复的话，raw 网格看起来是碎的。"""
    box = _unmerged_cube()
    assert box.is_watertight is False
    assert len(box.split(only_watertight=False)) == 12  # 12 个三角形，互不相连


def test_position_merged_copy_fixes_seam_and_reports_single_component():
    box = _unmerged_cube()
    measured = mesh_io.measure_part(box)
    assert measured["watertight"] is True
    assert measured["components"] == 1
    assert measured["faces"] == 12
    assert measured["vertices"] == 36  # 原始（未焊接）网格的顶点数原样报告
    assert abs(measured["volume_cm3"] - 1.0) < 1e-6  # 10x10x10mm = 1cm^3


def test_uv_seam_glb_round_trip_via_inspect_command(tmp_path, run):
    """走完整文件 I/O：导出成 GLB（保留按面拆开的顶点索引），再走 inspect 子命令。"""
    box = _unmerged_cube()
    glb_path = tmp_path / "seamy_cube.glb"
    box.export(glb_path, file_type="glb")

    job_dir = tmp_path / "job"
    exit_code, payload, _ = run(["inspect", "--job", str(job_dir), str(glb_path)])
    assert exit_code == 0
    assert len(payload["parts"]) == 1
    part = payload["parts"][0]
    assert part["watertight"] is True
    assert part["components"] == 1
    # 焊接前的"假碎裂"不应该冒充成真警告
    assert not any("watertight" in w or "components" in w for w in payload["warnings"])
