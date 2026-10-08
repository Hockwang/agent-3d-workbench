"""Independent geometry checks for a printable finite-stroke linear rail."""

import tempfile
import unittest
from pathlib import Path

from backend.engine import box, export_glb, mf, to_trimesh, trimesh
from backend.linear_rail import build_linear_rail


def cut_pair():
    whole = box([-20, -10, -8], [20, 10, 8])
    lower_halfspace = box([-25, -15, -12], [25, 15, 0])
    return whole ^ lower_halfspace, whole - lower_halfspace


def request(**overrides):
    values = dict(
        center_mm=[0, 0, 0],
        travel_axis=[1, 0, 0],
        leaf_normal=[0, 0, 1],
        rail_length_mm=12,
        rail_width_mm=6,
        rail_depth_mm=3.5,
        clearance_mm=0.2,
        travel_mm=6,
        stop_width_mm=1.5,
    )
    values.update(overrides)
    return values


class LinearRailGeometry(unittest.TestCase):
    def test_cut_pair_becomes_three_closed_exportable_parts(self):
        a, b = cut_pair()
        result = build_linear_rail(a, b, **request())
        report = result["report"]
        self.assertEqual(report["type"], "captured_t_rail")
        self.assertEqual(report["allowed_offset_mm"], [-3, 3])
        self.assertTrue(report["stop_removable"])
        self.assertEqual(report["independent_print_parts"], 3)
        self.assertLessEqual(report["stroke_sweep_overlap_mm3"], 0.001)
        self.assertLessEqual(report["insertion_sweep_overlap_mm3"], 0.001)
        self.assertLessEqual(report["stop_insertion_sweep_overlap_mm3"], 0.001)
        self.assertGreater(report["normal_pull_overlap_mm3"], 0.05)
        self.assertGreater(report["beyond_limit_overlap_mm3"]["negative_mm3"], 0.05)
        self.assertGreater(report["beyond_limit_overlap_mm3"]["positive_mm3"], 0.05)
        for label in ("a", "b", "stop"):
            with self.subTest(part=label):
                solid = result[label]
                mesh = to_trimesh(solid)
                self.assertEqual(len(solid.decompose()), 1)
                self.assertTrue(mesh.is_watertight and mesh.is_winding_consistent)
                self.assertGreater(mesh.volume, 0)
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            for label in ("a", "b", "stop"):
                mesh = to_trimesh(result[label])
                stl = folder / f"{label}.stl"
                glb = folder / f"{label}.glb"
                mesh.export(stl)
                export_glb(mesh, glb, [150, 165, 180, 255])
                self.assertTrue(trimesh.load(stl, force="mesh").is_watertight)
                self.assertGreater(glb.stat().st_size, 80)

    def test_stops_truly_bound_motion_and_t_head_cannot_lift_out(self):
        a, b = cut_pair()
        result = build_linear_rail(a, b, **request())
        fixed, slider, stop = result["a"], result["b"], result["stop"]
        for offset in (-3, -1.5, 0, 1.5, 3):
            with self.subTest(offset=offset):
                moved = slider.translate([offset, 0, 0])
                self.assertLessEqual(float((moved ^ fixed).volume()), 0.001)
                self.assertLessEqual(float((moved ^ stop).volume()), 0.001)
        overshot_right = slider.translate([4.5, 0, 0])
        overshot_left = slider.translate([-4.5, 0, 0])
        self.assertLessEqual(float((overshot_right ^ fixed).volume()), 0.001)
        self.assertGreater(float((overshot_right ^ stop).volume()), 0.05)
        self.assertGreater(float((overshot_left ^ fixed).volume()), 0.05)
        self.assertGreater(float((slider.translate([0, 0, 0.7]) ^ fixed).volume()), 0.05)

    def test_curved_part_cross_section_works_when_walls_are_thick(self):
        whole = mf.Manifold.cylinder(20, 12, 12, 96)
        lower_halfspace = box([-20, -20, 0], [20, 20, 10])
        a, b = whole ^ lower_halfspace, whole - lower_halfspace
        result = build_linear_rail(a, b, **request(center_mm=[0, 0, 10], rail_length_mm=10, travel_mm=3))
        self.assertEqual(len(result["a"].decompose()), 1)
        self.assertEqual(len(result["b"].decompose()), 1)
        self.assertTrue(result["report"]["continuous_profile_sweep"])

    def test_rejects_nonplanar_thin_or_unanchored_placement(self):
        a, b = cut_pair()
        with self.assertRaisesRegex(ValueError, "共面切面内"):
            build_linear_rail(a, b, **request(travel_axis=[0, 0, 1]))
        with self.assertRaisesRegex(ValueError, "同一平面"):
            build_linear_rail(a, b, **request(center_mm=[0, 0, 1]))
        with self.assertRaisesRegex(ValueError, "材料太薄"):
            build_linear_rail(box([-20, -10, -3], [20, 10, 0]), b, **request())
        with self.assertRaisesRegex(ValueError, "材料太薄"):
            build_linear_rail(a, b, **request(center_mm=[0, 9, 0]))
        with self.assertRaisesRegex(ValueError, "穿出切面"):
            build_linear_rail(a, b, **request(rail_depth_mm=2.5, stop_width_mm=3.5))


if __name__ == "__main__":
    unittest.main()
