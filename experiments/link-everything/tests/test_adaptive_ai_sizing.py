"""Scale guidance must survive the AI/model-to-kernel boundary."""

import unittest

from backend import manual, parametric_ai
from backend.engine import box, to_trimesh


class AdaptiveAISizing(unittest.TestCase):
    def guidance(self, side, pitch=0):
        a = to_trimesh(box([-side / 2, -side * 0.42, -side * 0.5], [side / 2, side * 0.42, 0]))
        b = to_trimesh(box([-side / 2, -side * 0.42, 0], [side / 2, side * 0.42, side * 0.45]))
        interface = dict(projected_size_mm=[side, side * 0.84])
        quality = dict(proxy_pitch_mm=pitch or None)
        placements = [dict(center_mm=[0, 0, 0], normal=[0, 0, 1])]
        return parametric_ai._dimension_guidance({}, [a, b], interface, quality, placements)

    def test_metres_scale_proxy_suggests_visible_connectors(self):
        guidance = self.guidance(1000, 6.7)
        self.assertTrue(guidance["local_static_footprint_verified"])
        self.assertGreaterEqual(guidance["preferred"]["plug"]["size_mm"], 45)
        self.assertGreaterEqual(guidance["preferred"]["hinge"]["pin_radius_mm"], 7)
        self.assertGreaterEqual(guidance["preferred"]["hinge"]["knuckle_radius_mm"], 14)
        self.assertGreaterEqual(guidance["preferred"]["hinge"]["segment_length_mm"], 150)
        self.assertGreaterEqual(guidance["preferred"]["linear_rail"]["rail_width_mm"], 40)
        old = dict(pin_radius_mm=1.5, knuckle_radius_mm=3.5, segment_length_mm=40)
        fixed = parametric_ai._parameters("hinge", old, guidance)
        self.assertGreater(fixed["pin_radius_mm"], old["pin_radius_mm"])
        self.assertGreater(fixed["knuckle_radius_mm"], old["knuckle_radius_mm"])
        self.assertGreater(fixed["segment_length_mm"], old["segment_length_mm"])
        with self.assertRaisesRegex(ValueError, "最小建议尺寸"):
            parametric_ai._parameters("hinge", old, guidance, strict_floor=True)
        self.assertGreaterEqual(manual.MAX_MANUAL_SIZE_MM, guidance["preferred"]["plug"]["size_mm"])

    def test_small_part_stays_small_and_process_clearance_is_not_scaled(self):
        small = self.guidance(35)
        large = self.guidance(1000, 6.7)
        self.assertLess(small["preferred"]["plug"]["size_mm"], large["preferred"]["plug"]["size_mm"] / 3)
        hinge = parametric_ai._parameters("hinge", {}, large)
        self.assertEqual(hinge["size_tolerance_mm"], parametric_ai.HINGE_DEFAULTS["size_tolerance_mm"])
        self.assertIsNone(small["proxy_pitch_mm"])


if __name__ == "__main__":
    unittest.main()
