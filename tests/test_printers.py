"""SPEC.md §5 第 1 条：printers 能列出 Bambu Lab P1S 0.4 nozzle，床 256x256x250，避让区 [0,0,18,28]。"""

from __future__ import annotations


def test_printers_lists_p1s_with_correct_bed(run):
    exit_code, payload, _ = run(["printers"])
    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["job"] is None

    by_name = {p["name"]: p for p in payload["printers"]}
    assert "Bambu Lab P1S 0.4 nozzle" in by_name
    p1s = by_name["Bambu Lab P1S 0.4 nozzle"]
    assert p1s["bed_mm"] == [256.0, 256.0, 250.0]
    assert p1s["exclude_areas"] == [[0.0, 0.0, 18.0, 28.0]]
    assert p1s["nozzle_mm"] == 0.4
    assert p1s["printer_model"] == "Bambu Lab P1S"
    assert p1s["default_process"] == "0.20mm Standard @BBL X1C"
    assert p1s["default_filament"] == "Bambu PLA Basic @BBL P1S 0.4 nozzle"
    # Our own conservative default (not a Bambu Studio preset field); see
    # print_prep/profiles.py DEFAULT_OVERHANG_ANGLE_DEG.
    assert p1s["overhang_angle_deg"] == 30.0


def test_printers_filter(run):
    exit_code, payload, _ = run(["printers", "--filter", "P1S"])
    assert exit_code == 0
    names = [p["name"] for p in payload["printers"]]
    assert names, "过滤后至少应该还剩下 P1S 系列"
    assert all("p1s" in n.lower() for n in names)
