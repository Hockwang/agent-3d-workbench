"""Geometric invariants and HTTP boundary checks; no physical-fit claims."""

import json
import sys
import unittest
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.engine import (
    OUTPUTS,
    build_geometry,
    validate_parameters,
    geometry_report,
    init_source,
    to_trimesh,
    box,
    sha,
)
import numpy as np
import trimesh


class GeometryTests(unittest.TestCase):
    def test_tongue_pair_and_assembly_path(self):
        p = validate_parameters({"type": "tongue_slot"})
        g = build_geometry(p)
        report = geometry_report(p, g, init_source())
        self.assertFalse(report["assembly"]["rigid_collision"])
        self.assertEqual(len(report["assembly"]["samples"]), 41)
        self.assertLess(report["final_overlap_mm3"], 1e-7)
        self.assertLess(report["outside_roi_change_mm3"], 1e-7)
        self.assertLess(report["cavity_intrusion_mm3"], 1e-7)
        self.assertTrue(all(m["watertight"] and m["components"] == 1 for m in report["parts"]))

    def test_snap_rigid_path_is_not_misreported_as_pass(self):
        p = validate_parameters({"type": "snap_fit"})
        report = geometry_report(p, build_geometry(p), init_source())
        self.assertTrue(report["assembly"]["rigid_collision"])
        self.assertGreater(report["assembly"]["max_overlap_mm3"], 0.1)
        self.assertEqual(next(c["status"] for c in report["checks"] if c["id"] == "path"), "review")
        self.assertLess(report["final_overlap_mm3"], 1e-7)
        self.assertFalse(report["fea_performed"])
        self.assertFalse(report["physical_print_performed"])

    def test_clearance_changes_receiver_but_preserves_male(self):
        a = build_geometry(validate_parameters({"clearance_mm": 0.2}))
        b = build_geometry(validate_parameters({"clearance_mm": 0.5}))
        self.assertLess(abs(a["lid"].volume() - b["lid"].volume()), 1e-7)
        self.assertLess((a["lid"] - b["lid"]).volume(), 1e-7)
        self.assertGreater(a["base"].volume() - b["base"].volume(), 5)
        self.assertLess(((a["base"] - b["base"]) - a["roi"]).volume(), 1e-7)
        # Probe material where the tight wall existed; it is removed by larger clearance.
        x0 = a["half"] + 1.2
        probe = box([x0 - 0.45, -1, a["H"] - 3], [x0 - 0.25, 1, a["H"] - 2])
        self.assertGreater((a["base"] ^ probe).volume(), 0.1)
        self.assertLess((b["base"] ^ probe).volume(), 1e-7)

    def test_depth_change_keeps_connector_attached_to_upper_rim(self):
        p = validate_parameters({})
        q = {**p, "cavity_depth_mm": p["cavity_depth_mm"] + 4.3}
        a, b = build_geometry(p), build_geometry(q)
        # Entire cap and connection must follow the +4.3 mm upper-rim movement.
        self.assertLess((a["lid"].translate([0, 0, 4.3]) - b["lid"]).volume(), 1e-6)
        self.assertLess((b["lid"] - a["lid"].translate([0, 0, 4.3])).volume(), 1e-6)
        self.assertLess((a["protected"] - b["protected"]).volume(), 1e-7)

    def test_position_edit_moves_only_connector_region(self):
        p = validate_parameters({"position_mm": -4.0})
        q = validate_parameters({"position_mm": 4.0})
        a, b = build_geometry(p), build_geometry(q)
        self.assertLess(((a["base"] - b["base"]) - (a["roi"] + b["roi"])).volume(), 1e-7)
        self.assertGreater((a["base"] - b["base"]).volume(), 10)

    def test_boundary_parameter_combinations(self):
        for mode in ["tongue_slot", "snap_fit"]:
            for offset in [-5, 5]:
                for clearance in [0.1, 0.65]:
                    p = validate_parameters(
                        dict(
                            type=mode,
                            position_mm=offset,
                            clearance_mm=clearance,
                            engagement_mm=10,
                            wall_mm=2,
                            cavity_depth_mm=28,
                        )
                    )
                    g = build_geometry(p)
                    for key in ["base", "lid"]:
                        mesh = to_trimesh(g[key])
                        self.assertTrue(mesh.is_watertight, (mode, offset, clearance, key))
                        self.assertEqual(len(g[key].decompose()), 1)
                    self.assertLess((g["base"] ^ g["lid"]).volume(), 1e-7)

    def test_reject_nonfinite_and_outside_parameters(self):
        for data in [
            {"clearance_mm": float("nan")},
            {"clearance_mm": float("inf")},
            {"position_mm": 9},
            {"cavity_depth_mm": -1},
            {"type": "arbitrary_llm_mesh"},
        ]:
            with self.assertRaises(ValueError):
                validate_parameters(data)

    def test_snap_without_retention_is_rejected(self):
        for hook, clearance in [(0.45, 0.65), (0.5, 0.5)]:
            with self.assertRaisesRegex(ValueError, "retention"):
                validate_parameters(dict(type="snap_fit", hook_mm=hook, clearance_mm=clearance))

    def test_fit_report_measures_result_and_detects_wrong_receiver(self):
        from backend.engine import measure_fit

        p = validate_parameters(dict(clearance_mm=0.3))
        g = build_geometry(p)
        measured = measure_fit(g, p)
        self.assertAlmostEqual(measured["receiver_width_mm"], 6.6, 6)
        self.assertAlmostEqual(measured["male_width_mm"], 6.0, 6)
        self.assertTrue(measured["matches_requested_clearance"])
        bad = build_geometry(validate_parameters(dict(clearance_mm=0.5)))
        g["base"] = bad["base"]
        self.assertFalse(measure_fit(g, p)["matches_requested_clearance"])

    def test_exported_stl_and_gltf_scale(self):
        project = json.loads((OUTPUTS / "project.json").read_text(encoding="utf-8"))
        for part in project["parts"]:
            glb = ROOT / part["url"].lstrip("/")
            stl = glb.with_suffix(".stl")
            mm = trimesh.load(stl, force="mesh")
            meters = trimesh.load(glb, force="mesh")
            self.assertTrue(mm.is_watertight)
            np.testing.assert_allclose(np.sort(mm.extents) * 0.001, np.sort(meters.extents), atol=1e-7)
            self.assertGreater(mm.volume, 100)

    def test_source_originals_and_frozen_bytes_match(self):
        source = init_source()
        if not source.get("reference_required", True):
            self.assertEqual(source["records"], [])
            self.assertIsNone(source["url"])
            return
        self.assertEqual(len(source["records"]), 2)
        for r in source["records"]:
            self.assertEqual(sha(Path(r["original_path"])), r["sha256"])
            self.assertEqual(sha(OUTPUTS / "source" / r["file"]), r["sha256"])

    def test_configured_historical_source_is_hash_checked(self):
        import tempfile
        from unittest.mock import patch
        import backend.engine as engine

        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            parts = temporary / "historical" / "PARTS"
            parts.mkdir(parents=True)
            for name, offset in [("A_00.stl", 0), ("A_01_NORMAL.stl", 8)]:
                mesh = to_trimesh(box([offset, 0, 0], [offset + 4, 4, 4]))
                mesh.export(parts / name)
            output = temporary / "outputs"
            with patch.object(engine, "SOURCE_DIR", parts.parent), patch.object(engine, "OUTPUTS", output):
                source = engine.init_source()
                self.assertTrue(source["reference_required"])
                self.assertEqual(len(source["records"]), 2)
                params = validate_parameters({})
                geometry = build_geometry(params)
                good = geometry_report(params, geometry, source)
                self.assertEqual(next(c["status"] for c in good["checks"] if c["id"] == "source"), "pass")
                (output / "source" / "A_00.stl").write_bytes(b"changed")
                bad = geometry_report(params, geometry, source)
                self.assertEqual(next(c["status"] for c in bad["checks"] if c["id"] == "source"), "fail")

    def test_coupon_preserves_original_wall_thickness_after_stl_roundtrip(self):
        from backend.engine import section_crossings, mesh_solid
        import tempfile

        for wall in [2.0, 2.4, 3.2]:
            p = validate_parameters(dict(wall_mm=wall))
            g = build_geometry(p)
            coupon = to_trimesh(g["base"] ^ g["coupon_roi"])
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "coupon.stl"
                coupon.export(path)
                loaded = trimesh.load(path, force="mesh")
                self.assertTrue(loaded.is_watertight)
                points = section_crossings(mesh_solid(loaded), g["H"] - 3, 1, p["position_mm"] + 5.5)
                self.assertAlmostEqual(max(points) - min(points), wall, 5)

    def test_missing_sources_fail_report_instead_of_vacuous_pass(self):
        p = validate_parameters({})
        g = build_geometry(p)
        for source in [dict(records=[]), dict(records=init_source()["records"][:1])]:
            report = geometry_report(p, g, source)
            self.assertEqual(report["status"], "geometry_failed")
            self.assertEqual(next(c["status"] for c in report["checks"] if c["id"] == "source"), "fail")


class HTTPTests(unittest.TestCase):
    base = "http://127.0.0.1:8766"

    def request(self, path, payload=None, headers=None):
        raw = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(
            self.base + path, data=raw, headers=headers or {"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.load(r)

    def test_health_and_artifact(self):
        _, health = self.request("/api/health")
        self.assertTrue(health["ok"])
        _, project = self.request("/api/project")
        with urllib.request.urlopen(self.base + project["parts"][0]["url"]) as r:
            self.assertEqual(r.read(4), b"glTF")

    def test_invalid_revision_and_cross_origin_do_not_mutate(self):
        _, before = self.request("/api/project")
        for payload, headers, expected in [
            ({"revision": -1}, None, 409),
            ({"clearance_mm": 5}, None, 400),
            ({"type": "snap_fit", "clearance_mm": 0.65, "hook_mm": 0.45}, None, 400),
            ({}, {"Content-Type": "application/json", "Origin": "https://example.invalid"}, 403),
        ]:
            with self.assertRaises(urllib.error.HTTPError) as context:
                self.request("/api/design", payload, headers)
            self.assertEqual(context.exception.code, expected)
        _, after = self.request("/api/project")
        self.assertEqual(before["revision"], after["revision"])

    def test_media_traversal_is_rejected(self):
        req = urllib.request.Request(
            self.base + "/api/media?filename=../../bad.webm",
            data=bytes.fromhex("1a45dfa3"),
            headers={"Content-Type": "video/webm"},
        )
        with self.assertRaises(urllib.error.HTTPError) as context:
            urllib.request.urlopen(req)
        self.assertEqual(context.exception.code, 400)


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    summary = dict(
        tests_run=result.testsRun,
        failures=len(result.failures),
        errors=len(result.errors),
        success=result.wasSuccessful(),
        physical_validation=False,
        details=[str(x[0]) + ": " + x[1] for x in result.failures + result.errors],
    )
    (OUTPUTS / "backend_test_report.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    sys.exit(not result.wasSuccessful())
