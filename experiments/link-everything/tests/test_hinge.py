"""Real printable hinge geometry from an isolated, Boolean-cut A/B pair."""

import tempfile
import unittest
from pathlib import Path

from backend.engine import box, export_glb, mf, to_trimesh, trimesh
from backend.hinge import _cylinder, _frame, build_hinge


def cut_pair():
    whole = box([-15, -10, -5], [15, 10, 5])
    lower_halfspace = box([-20, -20, -10], [20, 20, 0])
    return whole ^ lower_halfspace, whole - lower_halfspace


def request(**overrides):
    values = dict(
        center_mm=[0, 13, 0],
        axis=[1, 0, 0],
        leaf_normal=[0, 0, 1],
        pin_radius_mm=1,
        knuckle_radius_mm=2.5,
        clearance_mm=0.25,
        segment_length_mm=24,
        gap_mm=0.3,
    )
    values.update(overrides)
    return values


class HingeGeometry(unittest.TestCase):
    def test_boolean_cut_pair_becomes_three_closed_exportable_parts(self):
        a, b = cut_pair()
        self.assertEqual(len(a.decompose()), 1)
        self.assertEqual(len(b.decompose()), 1)
        solids = build_hinge(a, b, **request())
        report = solids["report"]
        for key in ("a", "b", "pin"):
            with self.subTest(part=key):
                solid = solids[key]
                mesh = to_trimesh(solid)
                self.assertEqual(len(solid.decompose()), 1)
                self.assertTrue(mesh.is_watertight and mesh.is_winding_consistent)
                self.assertGreater(mesh.volume, 0)
        self.assertEqual(report["type"], "three_knuckle_hinge")
        self.assertTrue(report["pin_removable"])
        self.assertAlmostEqual(report["minimum_radial_pin_clearance_mm"], 0.25)
        self.assertTrue(report["rotation"]["opens_to_90_deg"])
        self.assertTrue(report["pin_removal"]["removable"])
        self.assertFalse(report["rotation"]["continuous_proof"])
        self.assertTrue(all(volume <= 0.001 for volume in report["assembled_overlap_mm3"].values()))
        for owner, roots in report["web_root_engagement"].items():
            with self.subTest(owner=owner):
                self.assertEqual(len(roots), 2 if owner == "a" else 1)
                for root in roots:
                    self.assertGreaterEqual(root["embedded_volume_mm3"], root["minimum_embedded_volume_mm3"])
        # Previously the first non-zero Boolean overlap was accepted at 3.5 mm,
        # leaving a printable but only point-sized root on this simple box.
        self.assertGreaterEqual(report["web_reach_mm"]["b"][0], 4.5)
        self.assertGreater(float((solids["a"] ^ a).volume()), 0)
        self.assertGreater(float((solids["b"] ^ b).volume()), 0)

        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            for key in ("a", "b", "pin"):
                mesh = to_trimesh(solids[key])
                stl = folder / f"{key}.stl"
                glb = folder / f"{key}.glb"
                mesh.export(stl)
                export_glb(mesh, glb, [150, 165, 180, 255])
                self.assertGreater(stl.stat().st_size, 80)
                self.assertGreater(glb.stat().st_size, 80)
                loaded = trimesh.load(stl, force="mesh")
                self.assertTrue(loaded.is_watertight)
                self.assertAlmostEqual(loaded.volume, mesh.volume, places=3)

    def test_three_alternating_knuckles_have_a_real_common_bore(self):
        a, b = cut_pair()
        result = build_hinge(a, b, **request())
        frame = _frame([1, 0, 0], [0, 0, 1])
        for axial_mm, owner, other in ((-8, "a", "b"), (0, "b", "a"), (8, "a", "b")):
            with self.subTest(axial_mm=axial_mm):
                central_bore = _cylinder(1.1, axial_mm - 0.4, axial_mm + 0.4, [0, 13, 0], frame)
                outer_ring = _cylinder(2.4, axial_mm - 0.4, axial_mm + 0.4, [0, 13, 0], frame)
                self.assertLessEqual(float((result[owner] ^ central_bore).volume()), 0.001)
                self.assertGreater(float((result[owner] ^ outer_ring).volume()), 1)
                self.assertLessEqual(float((result[other] ^ outer_ring).volume()), 0.001)
        self.assertGreater(to_trimesh(result["pin"]).volume, 0)

    def test_rejects_axis_through_body_wrong_direction_and_remote_axis(self):
        a, b = cut_pair()
        with self.assertRaisesRegex(ValueError, "铰轴穿过"):
            build_hinge(a, b, **request(center_mm=[0, 0, 0]))
        with self.assertRaisesRegex(ValueError, "垂直"):
            build_hinge(a, b, **request(axis=[0, 0, 1]))
        with self.assertRaisesRegex(ValueError, "距离部件过远"):
            build_hinge(a, b, **request(center_mm=[0, 80, 0]))
        with self.assertRaisesRegex(ValueError, "壁厚"):
            build_hinge(a, b, **request(knuckle_radius_mm=1.8))

    def test_rejects_disconnected_or_intersecting_source_parts(self):
        a, b = cut_pair()
        disconnected = a + box([25, 25, -4], [28, 28, -1])
        with self.assertRaisesRegex(ValueError, "单个封闭连通实体"):
            build_hinge(disconnected, b, **request())
        with self.assertRaisesRegex(ValueError, "实体相交"):
            build_hinge(a, b.translate([0, 0, -0.5]), **request())

    def test_pin_extraction_uses_a_continuous_swept_volume(self):
        a, b = cut_pair()
        right_bar = box([14, 9, -1], [19, 13.5, -0.3])
        left_bar = box([-19, 9, -1], [-14, 13.5, -0.3])
        one_blocked = build_hinge(a + right_bar, b, **request())
        paths = {path["direction"]: path for path in one_blocked["report"]["pin_removal"]["paths"]}
        self.assertTrue(one_blocked["report"]["pin_removal"]["continuous_axis_sweep"])
        self.assertTrue(paths["negative"]["collision_free"])
        self.assertFalse(paths["positive"]["collision_free"])
        self.assertGreater(paths["positive"]["sweep_overlap_mm3"], 1)
        with self.assertRaisesRegex(ValueError, "销轴向两端抽出"):
            build_hinge(a + right_bar + left_bar, b, **request())

    def test_curved_body_cut_still_gets_connected_mounting_webs(self):
        whole = mf.Manifold.cylinder(20, 10, 10, 96)
        lower_halfspace = box([-20, -20, 0], [20, 20, 10])
        a, b = whole ^ lower_halfspace, whole - lower_halfspace
        result = build_hinge(a, b, **request(center_mm=[0, 13, 10]))
        self.assertEqual(len(result["a"].decompose()), 1)
        self.assertEqual(len(result["b"].decompose()), 1)
        self.assertTrue(result["report"]["rotation"]["opens_to_90_deg"])
        self.assertTrue(all(volume <= 0.001 for volume in result["report"]["assembled_overlap_mm3"].values()))


if __name__ == "__main__":
    unittest.main()
