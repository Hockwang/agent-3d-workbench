"""Physical geometry checks for the planar, edge-open sliding dovetail."""

import unittest

from backend.dovetail import _basis, build_dovetail, required_entry_run_mm, slide_path_report
from backend.engine import box, np, to_trimesh


def sample_parts():
    return box([-18, -15, 0], [18, 15, 10]), box([-18, -15, 10], [18, 15, 19])


def request(flip=False, degrees=0):
    return dict(
        center_mm=[0, 0, 10],
        normal=[0, 0, 1],
        size_mm=6,
        depth_mm=3,
        rotation_deg=degrees,
        size_tolerance_mm=0.2,
        depth_tolerance_mm=0.1,
        slide_length_mm=9,
        flip=flip,
    )


class DovetailGeometry(unittest.TestCase):
    def test_open_groove_and_under_cut_are_real_closed_solids(self):
        a, b = sample_parts()
        item = request()
        item["entry_run_mm"] = required_entry_run_mm(to_trimesh(b), item)
        cut_a, groove, male, pin = build_dovetail(item)
        self.assertIsNone(cut_a)
        self.assertIsNone(pin)
        self.assertTrue(to_trimesh(groove).is_watertight)
        self.assertTrue(to_trimesh(male).is_watertight)
        u, v, n = _basis(np.array(item["normal"]), item["rotation_deg"])
        # A genuine undercut widens *away from* the cut plane. The head cannot
        # be inserted straight down through the narrower channel mouth.
        male_vertices = to_trimesh(male).vertices - np.array(item["center_mm"])
        local_x, local_z = male_vertices @ u, male_vertices @ n
        neck = np.ptp(local_x[np.isclose(local_z, -0.3)])
        head = np.ptp(local_x[np.isclose(local_z, item["depth_mm"])])
        self.assertLess(neck, head * 0.7)
        self.assertGreater(item["entry_run_mm"], 18)  # +V reaches past the box edge.
        result_a, result_b = a + male, b - groove
        for solid in (result_a, result_b):
            mesh = to_trimesh(solid)
            self.assertTrue(mesh.is_watertight and mesh.is_winding_consistent)
            self.assertEqual(len(solid.decompose()), 1)
        self.assertLessEqual(float((result_a ^ result_b).volume()), 1e-5)

    def test_41_sliding_poses_are_collision_free(self):
        a, b = sample_parts()
        item = request()
        item["entry_run_mm"] = required_entry_run_mm(to_trimesh(b), item)
        _, groove, male, _ = build_dovetail(item)
        part_a, part_b = a + male, b - groove
        report = slide_path_report(part_a, part_b, item)
        self.assertEqual(len(report["poses"]), 41)
        self.assertTrue(report["collision_free"])
        self.assertFalse(report["continuous_proof"])
        _, direction, _ = _basis(np.array(item["normal"]), item["rotation_deg"])
        start = -item["entry_run_mm"] - item["slide_length_mm"] / 2 - 0.5
        for offset in np.linspace(start, 0, 41):
            with self.subTest(offset=offset):
                overlap = float((part_a ^ part_b.translate(direction * float(offset))).volume())
                self.assertLessEqual(overlap, 1e-5)

    def test_flipped_male_and_rotated_insertion(self):
        a, b = sample_parts()
        item = request(flip=True, degrees=47)
        item["entry_run_mm"] = required_entry_run_mm(to_trimesh(a), item)
        _, groove, male, _ = build_dovetail(item)
        receiver, moving_male = a - groove, b + male
        self.assertEqual(len(receiver.decompose()), 1)
        self.assertEqual(len(moving_male.decompose()), 1)
        self.assertLessEqual(float((receiver ^ moving_male).volume()), 1e-5)
        self.assertTrue(slide_path_report(receiver, moving_male, item, samples=11)["collision_free"])
        _, direction, _ = _basis(-np.array(item["normal"]), item["rotation_deg"])
        start = item["entry_run_mm"] + item["slide_length_mm"] / 2 + 0.5
        for offset in np.linspace(start, 0, 11):
            with self.subTest(offset=offset):
                overlap = float((receiver ^ moving_male.translate(direction * float(offset))).volume())
                self.assertLessEqual(overlap, 1e-5)

    def test_rejects_a_captive_groove_or_unavailable_planar_face(self):
        _, b = sample_parts()
        item = request()
        item["entry_run_mm"] = 3
        with self.assertRaisesRegex(ValueError, "open cut-face edge"):
            build_dovetail(item)
        shifted = to_trimesh(box([-18, -15, 11], [18, 15, 19]))
        with self.assertRaisesRegex(ValueError, "planar receiver cut face"):
            required_entry_run_mm(shifted, item)


if __name__ == "__main__":
    unittest.main()
