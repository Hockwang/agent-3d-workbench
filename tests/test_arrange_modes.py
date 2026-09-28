"""SPEC.md §5 第 3/9/13 条：arrange 三种模式——20 个 60x60x10 盒子，single 退出码 2
且报所需盘数；auto 给出多盘且零件恰好各出现一次；per_part 给 20 盘；任意通过的
排盘结果逐件验证在可用区内、互不重叠、不压避让区。另外覆盖两个具体缺陷的回归：
绕 Z 转 0/90 度必须优先让长边落在 X 上（不是按占地面积挑——面积恒等，那样挑
是死代码）；避让区把件堵死时必须是退出码 2 + part_too_large + suggested_scale，
不是裸异常。
"""

from __future__ import annotations

import pytest

from .conftest import write_box_stl

# P1S 默认打印机的床参数（与 test_printers.py 断言的值一致），供下面的物理校验
# 与"件会被避让区堵死"的回归用例使用。
_BED_MM = (256.0, 256.0, 250.0)
_MARGIN_MM = 5.0
_EXCLUDE_AREAS = ((0.0, 0.0, 18.0, 28.0),)


def _rects_intersect(ax0, ay0, ax1, ay1, bx0, by0, bx1, by1) -> bool:
    if ax1 <= bx0 or bx1 <= ax0:
        return False
    if ay1 <= by0 or by1 <= ay0:
        return False
    return True


def assert_arrangement_is_physically_valid(
    plates, bed_mm=_BED_MM, margin_mm=_MARGIN_MM, exclude_areas=_EXCLUDE_AREAS
) -> None:
    """SPEC.md §3.4「放置后置校验」的独立回归：不信任 `arrange` 自己声称成功，
    这里用一份跟生产代码（`arrange.py::_placement_fits`）完全独立的实现重新核
    一遍每一盘的每一件——整体落在可用区内、不压任何避让区、跟本盘其它已放置的
    零件不重叠。任何一种模式产出的「通过」的排盘结果都应该能过这个函数。
    """
    x0, y0 = margin_mm, margin_mm
    x1, y1 = bed_mm[0] - margin_mm, bed_mm[1] - margin_mm
    eps = 1e-6
    for plate in plates:
        placed_rects: list[tuple[float, float, float, float, str]] = []
        for pl in plate["placements"]:
            px0, py0 = pl["x_mm"], pl["y_mm"]
            w, h = pl["footprint_mm"]
            px1, py1 = px0 + w, py0 + h
            assert px0 >= x0 - eps and py0 >= y0 - eps and px1 <= x1 + eps and py1 <= y1 + eps, (
                f"plate {plate['index']} part {pl['part']!r} 超出可用区: {pl}"
            )
            for ex0, ey0, ex1, ey1 in exclude_areas:
                assert not _rects_intersect(px0, py0, px1, py1, ex0, ey0, ex1, ey1), (
                    f"plate {plate['index']} part {pl['part']!r} 压在避让区 {(ex0, ey0, ex1, ey1)} 上: {pl}"
                )
            for ox0, oy0, ox1, oy1, other_name in placed_rects:
                assert not _rects_intersect(px0, py0, px1, py1, ox0, oy0, ox1, oy1), (
                    f"plate {plate['index']} part {pl['part']!r} 与 {other_name!r} 重叠"
                )
            placed_rects.append((px0, py0, px1, py1, pl["part"]))


def _make_20_boxes(tmp_path):
    return [str(write_box_stl(tmp_path, f"blk{i:02d}", (60, 60, 10))) for i in range(20)]


def _inspect_and_orient(job_dir, files, run):
    exit_code, payload, _ = run(["inspect", "--job", str(job_dir), *files])
    assert exit_code == 0
    exit_code, payload, _ = run(["orient", "--job", str(job_dir)])
    assert exit_code == 0


def test_single_mode_overflows_with_needed_plate_count(tmp_path, run):
    files = _make_20_boxes(tmp_path)
    job_dir = tmp_path / "job_single"
    _inspect_and_orient(job_dir, files, run)

    exit_code, payload, _ = run(["arrange", "--job", str(job_dir), "--mode", "single"])
    assert exit_code == 2
    assert payload["ok"] is False
    assert payload["error"]["code"] == "single_plate_overflow"
    assert "needed_plates_with_auto" in payload
    assert payload["needed_plates_with_auto"] > 1
    assert str(payload["needed_plates_with_auto"]) in payload["error"]["message"]


def test_auto_mode_uses_multiple_plates_without_dropping_parts(tmp_path, run):
    files = _make_20_boxes(tmp_path)
    job_dir = tmp_path / "job_auto"
    _inspect_and_orient(job_dir, files, run)

    exit_code, payload, _ = run(["arrange", "--job", str(job_dir), "--mode", "auto"])
    assert exit_code == 0
    plates = payload["plates"]
    assert len(plates) > 1
    all_names = sorted(name for plate in plates for name in plate["parts"])
    expected = sorted(f"blk{i:02d}" for i in range(20))
    assert all_names == expected
    assert_arrangement_is_physically_valid(plates)


def test_per_part_mode_gives_twenty_plates(tmp_path, run):
    files = _make_20_boxes(tmp_path)
    job_dir = tmp_path / "job_per_part"
    _inspect_and_orient(job_dir, files, run)

    exit_code, payload, _ = run(["arrange", "--job", str(job_dir), "--mode", "per_part"])
    assert exit_code == 0
    assert len(payload["plates"]) == 20
    for plate in payload["plates"]:
        assert len(plate["parts"]) == 1
    assert_arrangement_is_physically_valid(payload["plates"])


def test_prepare_item_prefers_long_edge_along_x(tmp_path, run):
    """回归：`prepare_item` 绕 Z 转 0/90 度必须优先让长边落在 X 上。修复前的
    实现按占地面积挑（两个候选面积恒等，`<=` 让 0 度候选永远胜出）——这个
    20x60x10 的盒子在 print_up=[0,0,1]（R0 恒等变换）下 0 度候选恰好是
    w=20,h=60（长边在 Y 上），修复前会原样选中它；修复后必须转 90 度换成
    w=60,h=20（长边在 X 上，货架法行高更小）。"""
    box_path = write_box_stl(tmp_path, "long_box", (20, 60, 10))
    job_dir = tmp_path / "job_long_edge"

    exit_code, payload, _ = run(["inspect", "--job", str(job_dir), str(box_path)])
    assert exit_code == 0

    exit_code, payload, _ = run(["orient", "--job", str(job_dir), "--set", "long_box=0,0,1"])
    assert exit_code == 0

    exit_code, payload, _ = run(["arrange", "--job", str(job_dir)])
    assert exit_code == 0
    plate = payload["plates"][0]
    assert plate["parts"] == ["long_box"]
    w, h = plate["placements"][0]["footprint_mm"]
    assert w == pytest.approx(60.0, abs=1e-3), f"长边应该落在 X 上: footprint={(w, h)}"
    assert h == pytest.approx(20.0, abs=1e-3), f"长边应该落在 X 上: footprint={(w, h)}"
    assert_arrangement_is_physically_valid(payload["plates"])


def test_long_bar_steps_over_the_exclude_area(tmp_path, run):
    """P1S 上 240x40x10 的长条件：贴着左前角放会压到避让区 [0,0,18,28]，往右躲又超宽；
    但往上挪过避让区上沿就放得下。排盘器必须找到这个位置，而不是报「放不下」。"""
    box_path = write_box_stl(tmp_path, "bar", (240, 40, 10))
    job_dir = tmp_path / "job_bar"
    assert run(["inspect", "--job", str(job_dir), str(box_path)])[0] == 0
    assert run(["orient", "--job", str(job_dir), "--set", "bar=0,0,1"])[0] == 0

    exit_code, payload, _ = run(["arrange", "--job", str(job_dir)])
    assert exit_code == 0, payload
    placement = payload["plates"][0]["placements"][0]
    assert placement["y_mm"] >= 28.0, placement
    assert_arrangement_is_physically_valid(payload["plates"])


def test_arrange_reports_part_too_large_when_blocked_by_exclude_area(tmp_path, run):
    """SPEC.md 第 5 节第 13 条：240x225x10 的板尺寸没超可用区（246x246），但不管往右
    还是往上都躲不开避让区。必须是退出码 2 + part_too_large，且建议缩放系数是一个
    真能放下的值（小于 1），不是裸异常，也不是大于 1 的空话。"""
    box_path = write_box_stl(tmp_path, "slab", (240, 225, 10))
    job_dir = tmp_path / "job_blocked"
    assert run(["inspect", "--job", str(job_dir), str(box_path)])[0] == 0
    assert run(["orient", "--job", str(job_dir), "--set", "slab=0,0,1"])[0] == 0

    exit_code, payload, _ = run(["arrange", "--job", str(job_dir)])
    assert exit_code == 2
    assert payload["ok"] is False
    assert payload["error"]["code"] == "part_too_large"
    assert payload["suggested_scale"] is not None
    assert 0.5 < payload["suggested_scale"] < 1.0, payload["suggested_scale"]
