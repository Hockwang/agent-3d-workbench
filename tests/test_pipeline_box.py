"""SPEC.md §5 第 2 条：合成盒子走 inspect -> orient -> arrange -> export --no-project；
读回误差 < 0.01mm；flat 把 30x20x5 的盒子最大面朝下。"""

from __future__ import annotations

from .conftest import write_box_stl


def test_box_pipeline_flat_orientation_and_export_readback(tmp_path, run):
    box_path = write_box_stl(tmp_path, "box1", (30, 20, 5))
    job_dir = tmp_path / "job"

    exit_code, payload, _ = run(["inspect", "--job", str(job_dir), str(box_path)])
    assert exit_code == 0
    assert payload["ok"] is True
    assert len(payload["parts"]) == 1
    part = payload["parts"][0]
    assert part["name"] == "box1"
    assert part["watertight"] is True
    assert part["components"] == 1
    assert part["fits_bed"] is True
    assert part["extents_mm"] == [30.0, 20.0, 5.0]

    exit_code, payload, _ = run(["orient", "--job", str(job_dir), "--strategy", "flat"])
    assert exit_code == 0
    ori = payload["parts"]["box1"]
    assert ori["strategy_used"] == "flat"
    # 最大面（30x20=600mm^2）必须贴床：贴床接触面积应该等于这个最大面的面积，
    # 高度（沿 print_up 方向的跨度）应该等于盒子最短的那条边（5mm）。
    assert abs(ori["contact_area_mm2"] - 600.0) < 1e-6
    assert abs(ori["height_mm"] - 5.0) < 1e-6
    assert ori["upright_rejected"] is False

    exit_code, payload, _ = run(["arrange", "--job", str(job_dir)])
    assert exit_code == 0
    assert len(payload["plates"]) == 1
    assert payload["plates"][0]["parts"] == ["box1"]

    exit_code, payload, _ = run(["export", "--job", str(job_dir), "--no-project"])
    assert exit_code == 0
    assert len(payload["plates"]) == 1
    plate = payload["plates"][0]
    assert plate["readback"]["pass"] is True
    assert plate["readback"]["max_error_mm"] < 0.01
    assert "project_3mf" not in plate  # --no-project 只做几何 3MF 那一步

    from pathlib import Path

    assert Path(plate["geometry_3mf"]).exists()
