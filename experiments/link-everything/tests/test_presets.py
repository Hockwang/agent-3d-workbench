"""Independent geometric controls, exported file checks and actual HTTP routes."""

import json
import sys
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend import presets
from backend.engine import box, sha
from backend.server import Handler, ThreadingHTTPServer
import trimesh
import numpy as np

DELIVERY_OUTPUTS = presets.OUTPUTS


class PresetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.old_project_hash = sha(ROOT / "outputs" / "project.json")
        cls.old_engine_hash = sha(ROOT / "backend" / "engine.py")
        cls.qa = DELIVERY_OUTPUTS / "qa_runs" / time.strftime("%Y%m%d-%H%M%S")
        cls.qa.mkdir(parents=True, exist_ok=False)
        cls.output_patch = patch.object(presets, "OUTPUTS", cls.qa)
        cls.output_patch.start()
        cls.defaults = {}
        for spec in presets.catalog()["presets"]:
            cls.defaults[spec["id"]] = presets.generate({"preset_id": spec["id"], **spec["defaults"]})
        cls.http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.http.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.http.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown()
        cls.http.server_close()
        cls.thread.join(timeout=2)
        cls.output_patch.stop()

    def call(self, path, payload=None, headers=None):
        raw = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(
            self.base + path, data=raw, headers=headers or {"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=20) as response:
            return response.status, json.load(response)

    def test_four_defaults_are_real_closed_two_part_assemblies(self):
        self.assertEqual(set(self.defaults), {"cantilever", "u_shaped", "torsion", "annular"})
        for id, project in self.defaults.items():
            self.assertEqual(len(project["parts"]), 2, id)
            self.assertNotEqual(project["report"]["status"], "geometry_failed", id)
            self.assertLess(project["report"]["static_overlap_mm3"], 1e-5, id)
            self.assertTrue(all(x["watertight"] and x["components"] == 1 for x in project["report"]["parts"]), id)
            self.assertFalse(project["report"]["elastic_simulation_performed"])
            self.assertFalse(project["report"]["fea_performed"])
            self.assertTrue(any(x["id"] == "assembly.glb" for x in project["artifacts"]))

    def test_exported_stl_roundtrip_and_gltf_dimensions(self):
        for id, project in self.defaults.items():
            files = {a["id"]: Path(a["absolute_path"]) for a in project["artifacts"]}
            for part in ["part_a", "part_b"]:
                mm = trimesh.load(files[part + ".stl"], force="mesh")
                meters = trimesh.load(files[part + ".glb"], force="mesh")
                self.assertTrue(mm.is_watertight, (id, part))
                np.testing.assert_allclose(np.sort(mm.extents) * 0.001, np.sort(meters.extents), atol=1e-7)
                self.assertGreater(mm.volume, 1)
            scene = trimesh.load(files["assembly.glb"], force="scene")
            self.assertEqual(set(scene.graph.nodes_geometry), {"part_a", "part_b"})
            pair = trimesh.load(files["coupon_pair_print_layout.stl"], force="mesh")
            self.assertTrue(pair.is_watertight)
            self.assertAlmostEqual(pair.bounds[0, 2], 0, 5)
            self.assertTrue(
                np.isclose(pair.volume, sum(x["volume_mm3"] for x in project["report"]["parts"]), rtol=1e-5)
            )

    def test_all_exposed_parameters_change_geometry(self):
        for id, baseline in self.defaults.items():
            baseline_volumes = [x["volume_mm3"] for x in baseline["report"]["parts"]]
            for key, delta in [("clearance_mm", 0.1), ("beam_thickness_mm", 0.2), ("hook_mm", 0.15)]:
                values = {**baseline["parameters"], key: baseline["parameters"][key] + delta}
                project = presets.generate({"preset_id": id, **values})
                new_volumes = [x["volume_mm3"] for x in project["report"]["parts"]]
                self.assertGreater(max(abs(a - b) for a, b in zip(new_volumes, baseline_volumes)), 0.01, (id, key))
                self.assertLess(project["report"]["static_overlap_mm3"], 1e-5)

    def test_u_shape_opening_is_through_and_bridge_connected(self):
        p = self.defaults["u_shaped"]["parameters"]
        g = presets.build("u_shaped", p)
        opening = box([-2, -2, 7], [2, 2, 13])
        self.assertLess((g["solids"][1] ^ opening).volume(), 1e-7)
        bridge = box([-2, -2, 3.7], [2, 2, 4.1])
        self.assertGreater((g["solids"][1] ^ bridge).volume(), 1)
        self.assertEqual(len(g["solids"][1].decompose()), 1)

    def test_retention_comes_from_hooks_not_trapped_u_bridge(self):
        for id, project in self.defaults.items():
            p = project["parameters"]
            normal = presets.build(id, p)
            # Deliberate engineering control bypasses API validation: remove the net undercut.
            control = presets.build(id, {**p, "hook_mm": p["clearance_mm"]})
            normal_overlaps = []
            for dz in np.linspace(0.3, normal["travel_mm"], 31):
                normal_overlaps.append(
                    (normal["solids"][0] ^ normal["solids"][1].translate([0, 0, float(dz)])).volume()
                )
                overlap = (control["solids"][0] ^ control["solids"][1].translate([0, 0, float(dz)])).volume()
                self.assertLess(overlap, 1e-5, (id, float(dz), overlap))
            self.assertGreater(max(normal_overlaps), 0.05, id)

    def test_torsion_is_monolithic_rod_not_free_pin(self):
        p = self.defaults["torsion"]["parameters"]
        g = presets.build("torsion", p)
        fixed = g["solids"][0]
        self.assertEqual(len(fixed.decompose()), 1)
        # Both unsupported rod spans contain material and join the central lever to the supports.
        for x in [-5, 5]:
            self.assertGreater((fixed ^ box([x - 0.1, -0.1, 9.9], [x + 0.1, 0.1, 10.1])).volume(), 0.007)
        thick = presets.build("torsion", {**p, "beam_thickness_mm": p["beam_thickness_mm"] + 0.2})
        self.assertGreater(thick["solids"][0].volume() - fixed.volume(), 1)

    def test_annular_ring_is_continuous_and_clearance_is_radial(self):
        p = self.defaults["annular"]["parameters"]
        g = presets.build("annular", p)
        radius = 10 - p["clearance_mm"]
        t = p["beam_thickness_mm"]
        band = presets.cylinder(radius - 0.1, 0.2, 12) - presets.cylinder(radius - t + 0.1, 0.4, 11.9)
        self.assertLess((band - g["solids"][1]).volume(), 1e-5)
        self.assertAlmostEqual(20 - 2 * radius, 2 * p["clearance_mm"])
        spec = next(x for x in presets.catalog()["presets"] if x["id"] == "annular")
        self.assertIn("2 ×", spec["clearance_semantics"])

    def test_invalid_values_rejected_without_modifying_current(self):
        before = sha(presets.state_path())
        invalid = [
            {"preset_id": "unknown"},
            {"clearance_mm": float("nan")},
            {"hook_mm": float("inf")},
            {"beam_thickness_mm": False},
            {"clearance_mm": 0.55, "hook_mm": 0.45},
            {"beam_thickness_mm": 50},
            {"made_up_parameter": 1},
            {"revision": 1.1},
            {"revision": True},
        ]
        for data in invalid:
            with self.assertRaises(ValueError):
                presets.generate(data)
        with self.assertRaises(RuntimeError):
            presets.generate({"revision": -1})
        self.assertEqual(before, sha(presets.state_path()))

    def test_geometry_failure_keeps_previous_project(self):
        before = sha(presets.state_path())
        failed = {"status": "geometry_failed", "checks": [{"id": "static", "status": "fail"}]}
        with patch.object(presets, "check_geometry", return_value=failed):
            with self.assertRaises(ValueError):
                presets.generate({"preset_id": "cantilever"})
        self.assertEqual(before, sha(presets.state_path()))
        self.assertTrue(list((self.qa / "revisions").glob("r*/failed_report.json")))

    def test_catalog_and_real_http_design_routes(self):
        _, cat = self.call("/api/presets")
        self.assertEqual(len(cat["presets"]), 4)
        for spec in cat["presets"]:
            self.assertEqual({p["key"] for p in spec["parameters"]}, set(spec["limits"]))
        _, before = self.call("/api/presets/project")
        _, after = self.call(
            "/api/presets/design",
            dict(
                preset_id="cantilever",
                revision=before["revision"],
                clearance_mm=0.35,
                beam_thickness_mm=1.25,
                hook_mm=0.8,
            ),
        )
        self.assertGreater(after["revision"], before["revision"])
        self.assertEqual(after["preset_id"], "cantilever")
        for payload, status in [({"preset_id": "missing"}, 400), ({"revision": before["revision"]}, 409)]:
            with self.assertRaises(urllib.error.HTTPError) as error:
                self.call("/api/presets/design", payload)
            self.assertEqual(error.exception.code, status)
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.call(
                "/api/presets/design",
                {},
                headers={"Content-Type": "application/json", "Origin": "https://example.invalid"},
            )
        self.assertEqual(error.exception.code, 403)

    def test_original_project_and_engine_untouched(self):
        self.assertEqual(self.old_project_hash, sha(ROOT / "outputs" / "project.json"))
        self.assertEqual(self.old_engine_hash, sha(ROOT / "backend" / "engine.py"))

    def test_actual_first_contact_samples_are_not_reported_as_elastic_pass(self):
        for id, project in self.defaults.items():
            connection = project["connection"]
            report = project["report"]
            samples = connection["rigid_path_samples"]
            self.assertEqual(len(samples), 41)
            self.assertIsNotNone(connection["first_contact_offset_m"], id)
            clear_offset = connection["previous_clear_offset_m"]
            self.assertGreater(clear_offset, connection["first_contact_offset_m"])
            self.assertLess(next(x["overlap_mm3"] for x in samples if x["offset_m"] == clear_offset), 1e-5)
            self.assertTrue(any(x["overlap_mm3"] > 1e-5 for x in samples), id)
            elastic = next(x for x in report["checks"] if x["id"] == "elastic")
            self.assertEqual(elastic["status"], "pending")


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(PresetTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    summary = dict(
        tests_run=result.testsRun,
        failures=len(result.failures),
        errors=len(result.errors),
        success=result.wasSuccessful(),
        source_url=presets.SOURCE_URL,
        tested_default_presets=list(getattr(PresetTests, "defaults", {})),
        qa_directory=str(getattr(PresetTests, "qa", "")),
        elastic_simulation=False,
        physical_validation=False,
        details=[str(x[0]) + ": " + x[1] for x in result.failures + result.errors],
    )
    save = DELIVERY_OUTPUTS / "presets_test_report.json"
    save.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    sys.exit(not result.wasSuccessful())
