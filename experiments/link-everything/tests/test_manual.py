"""Real geometry/API-contract checks for manual placement on planar split faces."""

import base64
import copy
import tempfile
import unittest
from pathlib import Path

from backend import manual
from backend.engine import to_trimesh


def connector(kind="plug", shape="circle", style="prism", flip=False, x=0, y=0):
    return dict(
        id=f"{kind}-{shape}-{style}-{flip}-{x}-{y}",
        type=kind,
        style=style,
        shape=shape,
        center_mm=[x, y, 10],
        normal=[0, 0, 1],
        depth_mm=5.5,
        size_mm=5.5,
        rotation_deg=15,
        clearance_mm=0.2,
        bulge_pct=15,
        space_pct=30,
        flip=flip,
    )


class ManualGeometry(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.globals = (manual.OUT, manual.STATE, manual.SOURCE)
        manual.OUT = Path(cls.temp.name) / "manual"
        manual.STATE = manual.OUT / "project.json"
        manual.SOURCE = manual.OUT / "source.json"
        cls.initial = manual.current_project()

    @classmethod
    def tearDownClass(cls):
        manual.OUT, manual.STATE, manual.SOURCE = cls.globals
        cls.temp.cleanup()

    def make(self, items):
        previous = manual.current_project()
        return manual.generate(dict(source_id=previous["source_id"], revision=previous["revision"], connectors=items))

    def test_blank_pair_is_two_closed_solids(self):
        self.assertEqual(self.initial["report"]["connector_count"], 0)
        self.assertEqual(len(self.initial["report"]["parts"]), 2)

    def test_three_mechanisms_and_extra_pin(self):
        for kind in ("plug", "dowel", "snap"):
            with self.subTest(kind=kind):
                result = self.make([connector(kind)])
                self.assertEqual(result["report"]["connector_count"], 1)
                self.assertEqual(result["report"]["motion_preview"]["kind"], "inspection_explode")
                self.assertTrue(result["report"]["motion_preview"]["visualization_only"])
                self.assertLess(abs(result["report"]["static_overlap_mm3"]), 1e-4)
                self.assertTrue(all(p["closed"] and p["components"] == 1 for p in result["report"]["parts"]))
                self.assertEqual(len(result["parts"]), 3 if kind == "dowel" else 2)

    def test_all_type_style_shape_flip_combinations(self):
        for kind in ("plug", "dowel", "snap"):
            for style in ("prism", "tapered"):
                for shape in ("circle", "triangle", "square", "hexagon"):
                    for flip in (False, True):
                        with self.subTest(kind=kind, style=style, shape=shape, flip=flip):
                            result = self.make([connector(kind, shape, style, flip)])
                            self.assertLess(abs(result["report"]["static_overlap_mm3"]), 1e-4)
                            self.assertTrue(all(x["closed"] for x in result["report"]["parts"]))

    def test_style_shape_flip_and_rotation_change_real_mesh(self):
        hashes = []
        for shape, style, flip in [
            ("circle", "prism", False),
            ("square", "prism", False),
            ("hexagon", "tapered", False),
            ("circle", "prism", True),
        ]:
            result = self.make([connector("plug", shape, style, flip)])
            file = next(a for a in result["artifacts"] if a["id"] == "assembly.glb")
            hashes.append(file["sha256"])
        self.assertEqual(len(set(hashes)), len(hashes))

    def test_square_size_is_actual_side_length(self):
        mesh = to_trimesh(manual._profile(2.75, 0, 5.5, "square", "prism"))
        self.assertAlmostEqual(mesh.extents[0], 5.5, places=3)
        self.assertAlmostEqual(mesh.extents[1], 5.5, places=3)

    def test_depth_and_size_tolerances_change_receiver_independently(self):
        base = connector()
        base.update(depth_tolerance_mm=0.1, size_tolerance_mm=0.2)
        deeper = copy.deepcopy(base)
        deeper["depth_tolerance_mm"] = 0.5
        wider = copy.deepcopy(base)
        wider["size_tolerance_mm"] = 0.5
        results = [self.make([item]) for item in (base, deeper, wider)]

        def artifact(project, name):
            return next(x["sha256"] for x in project["artifacts"] if x["id"] == name)

        self.assertEqual(len({artifact(x, "part_a.stl") for x in results}), 1)
        self.assertEqual(len({artifact(x, "part_b.stl") for x in results}), 3)
        self.assertEqual(results[1]["connectors"][0]["size_tolerance_mm"], 0.2)
        self.assertEqual(results[2]["connectors"][0]["depth_tolerance_mm"], 0.1)

    def test_planar_dovetail_has_open_entry_and_collision_free_slide(self):
        manual.restore_sample()
        item = connector(kind="dovetail")
        item.update(
            depth_mm=3, size_mm=6, slide_length_mm=9, neck_ratio=0.62, depth_tolerance_mm=0.1, size_tolerance_mm=0.2
        )
        result = self.make([item])
        self.assertEqual(result["report"]["connector_count"], 1)
        self.assertGreater(result["connectors"][0]["entry_run_mm"], 15)
        preview = result["report"]["motion_preview"]
        self.assertEqual(preview["kind"], "assembly_translation")
        self.assertEqual(preview["moving_part"], "part_b")
        self.assertLess(preview["assembly_start_value"], 0)
        self.assertEqual(preview["range"][1], 0)
        self.assertFalse(preview["validation"]["continuous_proof"])
        self.assertLess(result["report"]["static_overlap_mm3"], 1e-4)
        self.assertTrue(all(x["closed"] and x["components"] == 1 for x in result["report"]["parts"]))

    def test_multiple_locations_and_remove(self):
        a, b = connector(x=-8), connector(kind="dowel", x=8)
        result = self.make([a, b])
        self.assertEqual(result["report"]["connector_count"], 2)
        self.assertEqual(len(result["parts"]), 3)
        removed = self.make([a])
        self.assertEqual(removed["report"]["connector_count"], 1)

    def test_overlapping_connector_footprints_are_rejected(self):
        before = manual.current_project()["revision"]
        with self.assertRaisesRegex(ValueError, "overlap"):
            self.make([connector(x=0), connector(kind="dowel", x=2)])
        self.assertEqual(manual.current_project()["revision"], before)

    def test_invalid_point_preserves_project(self):
        before = manual.current_project()["revision"]
        with self.assertRaisesRegex(ValueError, "共同切面"):
            self.make([connector(x=25)])
        self.assertEqual(manual.current_project()["revision"], before)

    def test_edge_crossing_is_rejected_before_boolean(self):
        before = manual.current_project()["revision"]
        with self.assertRaisesRegex(ValueError, "共同切面"):
            self.make([connector(x=17)])
        self.assertEqual(manual.current_project()["revision"], before)

    def test_revision_conflict_preserves_project(self):
        before = manual.current_project()
        with self.assertRaisesRegex(RuntimeError, "revision conflict"):
            manual.generate(dict(source_id=before["source_id"], revision=0, connectors=[]))
        self.assertEqual(manual.current_project()["revision"], before["revision"])

    def test_upload_freezes_two_stls_and_resets_connectors(self):
        before = manual.current_project()
        raw = [Path(part["stl"]).read_bytes() for part in before["source"]["parts"]]
        payload = dict(
            part_a=base64.b64encode(raw[0]).decode(), part_b=base64.b64encode(raw[1]).decode(), names=["A.stl", "B.stl"]
        )
        uploaded = manual.upload(payload)
        self.assertNotEqual(uploaded["source"]["id"], before["source_id"])
        self.assertEqual(uploaded["project"]["connectors"], [])
        self.assertEqual(
            [p["sha256"] for p in uploaded["source"]["parts"]], [p["sha256"] for p in before["source"]["parts"]]
        )
        restored = manual.restore_sample()
        self.assertEqual(restored["source"]["id"], "sample-pair")

    def test_invalid_upload_keeps_previous_source_and_version(self):
        previous = manual.current_project()
        raw = Path(previous["source"]["parts"][0]["stl"]).read_bytes()
        data = base64.b64encode(raw).decode()
        with self.assertRaisesRegex(ValueError, "overlap"):
            manual.upload(dict(part_a=data, part_b=data, names=["same-a.stl", "same-b.stl"]))
        current = manual.current_project()
        self.assertEqual(current["source_id"], previous["source_id"])
        self.assertEqual(current["revision"], previous["revision"])


if __name__ == "__main__":
    unittest.main()
