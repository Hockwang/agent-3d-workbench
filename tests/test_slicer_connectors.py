"""Connector isolation, no-print semantics and fresh Orca statistics."""
from __future__ import annotations

import argparse
import json
import subprocess
import zipfile
from pathlib import Path

import pytest

from print_prep import arrange, bambu, cli, printer_catalog, profiles, slicers


def exported_job(root: Path, source="orca"):
    root.mkdir(parents=True, exist_ok=True)
    files = {}
    for kind in ("geometry", "project"):
        path = root / f"plate.{kind}.3mf"
        path.write_bytes(b"test file; opening is mocked")
        files[f"{kind}_3mf"] = str(path)
    data = {"export": {"slicer": source, "plates": [{"index": 1, **files}]}}
    (root / "job.json").write_text(json.dumps(data))
    return data


@pytest.mark.parametrize("slicer", list(slicers.SLICERS))
def test_all_connectors_dry_run_never_launch(tmp_path, monkeypatch, slicer):
    path = tmp_path / "part with spaces.3mf"
    path.write_bytes(b"fixture")
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("launched"))
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: pytest.fail("launched"))
    result = slicers.open_file(slicer, path, dry_run=True)
    assert result["executed"] is False
    assert result["command"][-1] == str(path.resolve())


def test_missing_app_does_not_fall_back_to_default(tmp_path, monkeypatch):
    path = tmp_path / "part.3mf"
    path.touch()
    monkeypatch.setenv("ORCA_SLICER_APP", str(tmp_path / "not-installed.app"))
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("launched"))
    with pytest.raises(slicers.SlicerError):
        slicers.open_file("orca", path)


def test_open_failure_is_not_success(tmp_path, monkeypatch):
    path = tmp_path / "part.3mf"
    path.touch()
    app = tmp_path / "OrcaSlicer.app"
    app.mkdir()
    monkeypatch.setattr(slicers.sys, "platform", "darwin")
    monkeypatch.setenv("ORCA_SLICER_APP", str(app))
    def fail(*a, **k):
        raise subprocess.CalledProcessError(1, ["open"])
    monkeypatch.setattr(subprocess, "run", fail)
    with pytest.raises(slicers.SlicerError):
        slicers.open_file("orca", path)


def test_other_slicer_requires_explicit_geometry_only(tmp_path):
    data = exported_job(tmp_path)
    args = argparse.Namespace(job=str(tmp_path), slicer="bambu", geometry_only=False, all=True, plate=None, dry_run=True)
    with pytest.raises(cli.UserError) as exc:
        cli.cmd_open_slicer(args, data)
    assert exc.value.code == "slicer_mismatch"
    args.geometry_only = True
    result = cli.cmd_open_slicer(args, data)
    assert result["print_submitted"] is False
    assert result["manual_setup_required"] is True
    assert result["opened"][0]["path"].endswith("geometry.3mf")


def test_generic_http_tool_and_legacy_target(studio_env):
    exported_job(studio_env["job_dir"])
    client = studio_env["client"]
    status, result = client.post("/api/send_to_slicer", {"dry_run": True})
    assert status == 200 and result["slicer"] == "orca"
    assert result["loaded"] == "unverified"
    assert result["print_submitted"] is False
    assert studio_env["backend"]._delivered is False
    status, result = client.post("/api/send", {"dry_run": True})
    assert status != 200 and result["error"]["code"] == "slicer_mismatch"
    status, result = client.get("/api/slicers")
    assert status == 200 and len(result["slicers"]) == 5


def test_orca_fresh_statistics_and_no_stale_success(tmp_path, monkeypatch):
    binary = tmp_path / "orca"
    binary.touch()
    out = tmp_path / "out"
    out.mkdir()
    sliced = out / "part.sliced.3mf"
    def run(command, log_path, timeout_s):
        with zipfile.ZipFile(sliced, "w") as z:
            z.writestr("Metadata/plate_1.gcode", "G1 X1 E1")
            z.writestr("Metadata/slice_info.config", '<config><plate><metadata key="weight" value="3.62"/><metadata key="prediction" value="997"/><warning msg="review_temperature"/></plate></config>')
        return {"returncode": 0, "timed_out": False, "wall_seconds": 0.1}
    monkeypatch.setattr(bambu, "_run", run)
    args = (tmp_path / "g.3mf", out, tmp_path / "m.json", tmp_path / "p.json", [], "part")
    result = bambu.check_slice(*args, binary=binary, statistics_format="orca")
    assert result["ok"] and result["grams"] == 3.62 and result["seconds"] == 997
    assert result["warnings"] == ["review_temperature"]
    monkeypatch.setattr(bambu, "_run", lambda *a: {"returncode": 0, "timed_out": False, "wall_seconds": 0.1})
    result = bambu.check_slice(*args, binary=binary, statistics_format="orca")
    assert not result["ok"] and result["grams"] is None


@pytest.mark.parametrize("source", printer_catalog.SOURCES)
def test_catalog_isolated_ids_and_unsupported_beds(tmp_path, monkeypatch, source):
    for other in printer_catalog.SOURCES:
        monkeypatch.setenv(f"MFG_{other.upper()}_PROFILE_ROOT", str(tmp_path / other))
    root = tmp_path / source
    printer_catalog._cache.clear()
    for vendor in ("Creality", "New vendor"):
        for kind in ("machine", "process", "filament"):
            (root / vendor / kind).mkdir(parents=True)
        for kind, name in (("process", "process"), ("filament", "material")):
            (root / vendor / kind / f"{name}.json").write_text(json.dumps({"name": name, "instantiation": "true"}))
        machine = {"name": "Same model", "instantiation": "true", "printable_area": ["0x0", "200x0", "200x200", "0x200"], "printable_height": "200", "nozzle_diameter": ["0.4"], "default_print_profile": "process", "default_filament_profile": ["material"], "bed_exclude_area": "0x0"}
        (root / vendor / "machine/model.json").write_text(json.dumps(machine))
        machine = {**machine, "name": "Offset bed", "printable_area": ["-100x-100", "100x-100", "100x100", "-100x100"]}
        (root / vendor / "machine/offset.json").write_text(json.dumps(machine))
        machine = {**machine, "name": "Triangle", "printable_area": ["0x0", "200x0", "100x200"]}
        (root / vendor / "machine/triangle.json").write_text(json.dumps(machine))
        machine = {**machine, "name": "Broken default", "printable_area": ["0x0", "200x0", "200x200", "0x200"], "default_print_profile": "missing"}
        (root / vendor / "machine/broken.json").write_text(json.dumps(machine))
    catalog = printer_catalog.catalog()
    assert len(catalog["printers"]) == 4 and len(catalog["excluded"]) == 2
    assert len(catalog["errors"]) == 2
    assert {p["name"] for p in catalog["printers"]} == {f"{source}::{v}::{n}" for v in ("Creality", "New vendor") for n in ("Same model", "Offset bed")}
    assert next(p for p in catalog["printers"] if p["display_name"] == "Offset bed")["bed_origin_mm"] == [-100, -100]
    _, vendor_root, idx, native = printer_catalog.context(f"{source}::New vendor::Same model")
    assert vendor_root == root / "New vendor"
    assert profiles.resolve(native, idx)["name"] == "Same model"
    for invalid in [f"{source}::../../escape::Same model", "unknown::Creality::Same model", f"{source}::New vendor::"]:
        with pytest.raises(profiles.ProfileError):
            printer_catalog.context(invalid)


def test_mac_bundle_executable_is_not_assumed_from_app_name(tmp_path, monkeypatch):
    import plistlib
    app = tmp_path / "Friendly name.app"
    (app / "Contents").mkdir(parents=True)
    (app / "Contents/Info.plist").write_bytes(plistlib.dumps({"CFBundleExecutable": "Actual_Binary"}))
    monkeypatch.setenv("SNAPMAKER_ORCA_APP", str(app))
    monkeypatch.delenv("SNAPMAKER_ORCA_PATH", raising=False)
    assert slicers.binary_path("snapmaker") == app / "Contents/MacOS/Actual_Binary"


@pytest.mark.parametrize("origin", [(0.5, 1.0), (-100.0, -100.0)])
def test_offset_bed_coordinates_and_exclusions(origin):
    import numpy as np
    import trimesh
    ox, oy = origin
    mesh = trimesh.creation.box((20, 20, 20))
    parts = [{"name": "cube", "mesh": mesh, "print_up": [0, 0, 1]}]
    # Native-coordinate exclusion blocks the first slot.
    exclusion = [ox, oy, ox + 40, oy + 40]
    plates = arrange.arrange(parts, [200, 200, 200], 5, [exclusion], bed_origin_mm=origin)
    placement = plates[0]["placements"][0]
    placed = mesh.copy()
    placed.apply_transform(np.array(placement["T"]))
    lo, hi = placed.bounds
    assert lo[0] >= ox + 5 and lo[1] >= oy + 5
    assert hi[0] <= ox + 195 and hi[1] <= oy + 195
    assert lo[2] == pytest.approx(0)
    assert not (lo[0] < exclusion[2] and lo[1] < exclusion[3])


def test_creality_geometry_route_and_explicit_slice_limit(tmp_path, monkeypatch):
    data = exported_job(tmp_path, source="creality")
    data["export"]["manual_setup_required"] = True
    (tmp_path / "job.json").write_text(json.dumps(data))
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("unexpected process"))
    args = argparse.Namespace(job=str(tmp_path), slicer=None, geometry_only=False, all=True, plate=None, dry_run=True)
    result = cli.cmd_open_slicer(args, data)
    assert result["geometry_only"] and result["manual_setup_required"]
    assert result["opened"][0]["path"].endswith("geometry.3mf")
    with pytest.raises(cli.UserError) as exc:
        cli.cmd_check(argparse.Namespace(job=str(tmp_path), plate=None))
    assert exc.value.code == "slicer_manual_required"
