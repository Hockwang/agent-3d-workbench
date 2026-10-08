"""A motion preview must follow measured generation reports, never proposal guesses."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import manual
from backend.motion_preview import build_motion_preview


def valid_report():
    return dict(
        parts=[dict(closed=True), dict(closed=True)],
        static_overlap_mm3=0,
        static_overlap_tolerance_mm3=0.001,
        mechanisms=[],
        pins=[],
    )


def hinge_report():
    report = valid_report()
    report["pins"] = [dict(id="pin_1", closed=True)]
    report["mechanisms"] = [
        dict(
            type="three_knuckle_hinge",
            axis=[0, 1, 0],
            axis_center_mm=[12, 425.6426, 380],
            pin_removable=True,
            rotation=dict(
                opens_to_90_deg=True,
                continuous_proof=False,
                sampled_paths=[
                    dict(
                        direction="negative",
                        collision_free=False,
                        samples=[dict(angle_deg=0, overlap_mm3=0), dict(angle_deg=-15, overlap_mm3=3)],
                    ),
                    dict(
                        direction="positive",
                        collision_free=True,
                        samples=[dict(angle_deg=angle, overlap_mm3=0) for angle in range(0, 91, 15)],
                    ),
                ],
            ),
        )
    ]
    return report


class MotionPreviewContract(unittest.TestCase):
    def test_hinge_uses_actual_report_axis_and_only_collision_free_side(self):
        preview = build_motion_preview([dict(type="hinge")], hinge_report(), revision=54)
        self.assertEqual(preview["kind"], "rotation")
        self.assertEqual(preview["status"], "ready")
        self.assertEqual(preview["coordinate_space"], "engineering_mm_z_up")
        self.assertEqual(preview["pivot_mm"], [12, 425.6426, 380])
        self.assertEqual(preview["axis"], [0, 1, 0])
        self.assertEqual(preview["range"], [0, 90])
        self.assertEqual(preview["stationary_parts"], ["part_a", "pin_1"])
        self.assertFalse(preview["validation"]["continuous_proof"])
        report = hinge_report()
        report["mechanisms"][0]["rotation"]["sampled_paths"][0] = dict(
            direction="negative",
            collision_free=True,
            samples=[dict(angle_deg=angle, overlap_mm3=0) for angle in range(0, -91, -15)],
        )
        negative = build_motion_preview([dict(type="hinge")], report)
        self.assertEqual(negative["range"], [-90, 90])

    def test_hinge_rejects_falsely_labelled_colliding_path(self):
        report = hinge_report()
        report["mechanisms"][0]["rotation"]["sampled_paths"][1]["samples"][2]["overlap_mm3"] = 2
        preview = build_motion_preview([dict(type="hinge", normal=[0, 0, 1])], report)
        self.assertEqual(preview["kind"], "inspection_explode")
        self.assertEqual(preview["validation"]["method"], "visualization_only")

    def test_rail_uses_validated_signed_offsets_and_stationary_stop(self):
        report = valid_report()
        report["pins"] = [dict(id="pin_1", closed=True)]
        report["mechanisms"] = [
            dict(
                type="captured_t_rail",
                travel_axis=[1, 0, 0],
                allowed_offset_mm=[-12, 12],
                continuous_profile_sweep=True,
                whole_part_continuous_proof=False,
                stroke_sweep_overlap_mm3=0,
                sampled_whole_part_poses=[dict(offset_mm=offset, overlap_mm3=0) for offset in range(-12, 13, 3)],
            )
        ]
        preview = build_motion_preview([dict(type="linear_rail")], report)
        self.assertEqual(preview["kind"], "translation")
        self.assertEqual(preview["range"], [-12, 12])
        self.assertEqual(preview["axis"], [1, 0, 0])
        self.assertEqual(preview["stationary_parts"], ["part_a", "pin_1"])
        self.assertFalse(preview["validation"]["continuous_proof"])

    def test_only_recorded_single_dovetail_path_is_animated(self):
        report = valid_report()
        item = dict(id="dovetail-1", type="dovetail", normal=[0, 0, 1])
        self.assertEqual(build_motion_preview([item], report)["kind"], "inspection_explode")
        report["dovetail_assembly_paths"] = [
            dict(
                connector_id=item["id"],
                moving_part="part_b",
                axis=[0, 1, 0],
                poses=[
                    dict(offset_mm=-25, overlap_mm3=0),
                    dict(offset_mm=-12.5, overlap_mm3=0),
                    dict(offset_mm=0, overlap_mm3=0),
                ],
                overlap_tolerance_mm3=0.001,
                collision_free=True,
            )
        ]
        preview = build_motion_preview([item], report)
        self.assertEqual(preview["kind"], "assembly_translation")
        self.assertEqual(preview["assembly_start_value"], -25)
        self.assertEqual(preview["range"], [-25, 0])
        self.assertEqual(
            build_motion_preview([item, dict(type="plug", normal=[0, 0, 1])], report)["kind"], "inspection_explode"
        )

    def test_static_connector_gets_case_scaled_visual_inspection_only(self):
        for kind in ("plug", "dowel", "snap", "cantilever"):
            with self.subTest(kind=kind):
                preview = build_motion_preview(
                    [dict(type=kind, normal=[0, 0, 1], size_mm=8, depth_mm=6)], valid_report()
                )
                self.assertEqual(preview["kind"], "inspection_explode")
                self.assertEqual(preview["status"], "ready")
                self.assertTrue(preview["visualization_only"])
                self.assertEqual(preview["validation"]["method"], "visualization_only")
                self.assertFalse(preview["validation"]["physical_assembly_path_tested"])
                self.assertEqual(preview["axis"], [0, 0, 1])
                self.assertGreater(preview["range"][1], 0)

    def test_multi_connector_explode_distance_adapts_to_part_bounds(self):
        items = [dict(type="plug", normal=[0, 0, 1], size_mm=8), dict(type="dowel", normal=[0, 0, 1], size_mm=8)]
        small, large = valid_report(), valid_report()
        small["pins"] = [dict(id="pin_1", closed=True)]
        for report, size in ((small, 20), (large, 1000)):
            report["parts"][0]["shells"] = [dict(bounds_mm=[[0, 0, 0], [size, size, size / 2]])]
            report["parts"][1]["shells"] = [dict(bounds_mm=[[0, 0, size / 2], [size, size, size]])]
        small_preview = build_motion_preview(items, small)
        large_preview = build_motion_preview(items, large)
        self.assertEqual(small_preview["kind"], "inspection_explode")
        self.assertGreater(large_preview["range"][1], small_preview["range"][1] * 10)
        self.assertIn("pin_1", small_preview["stationary_parts"])

    def test_historical_tiny_overlap_and_missing_tolerance_still_preview(self):
        old = hinge_report()
        old.pop("static_overlap_tolerance_mm3")
        old["static_overlap_mm3"] = 1e-13
        hinge = build_motion_preview([dict(type="hinge", normal=[0, 0, 1])], old)
        self.assertEqual(hinge["kind"], "rotation")
        static = build_motion_preview([dict(type="plug", normal=[0, 0, 1])], old)
        self.assertEqual(static["kind"], "inspection_explode")
        old["static_overlap_mm3"] = 1e-4
        blocked = build_motion_preview([dict(type="hinge", normal=[0, 0, 1])], old)
        self.assertEqual(blocked["kind"], "inspection_explode")
        self.assertEqual(blocked["validation"]["method"], "visualization_only")

    def test_failed_physical_report_remains_display_only(self):
        failed = hinge_report()
        failed["parts"][1]["closed"] = False
        preview = build_motion_preview([dict(type="hinge", normal=[0, 0, 1])], failed)
        self.assertEqual(preview["status"], "ready")
        self.assertEqual(preview["kind"], "inspection_explode")
        self.assertFalse(preview["validation"]["physical_assembly_path_tested"])

    def test_existing_hinge_revision_backfills_without_touching_saved_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "project.json"
            project = dict(source_id="test-source", revision=54, connectors=[dict(type="hinge")], report=hinge_report())
            path.write_text(json.dumps(project), encoding="utf-8")
            original = path.read_bytes()
            with (
                patch.object(manual, "STATE", path),
                patch.object(manual, "initialize", return_value=dict(id="test-source")),
            ):
                loaded = manual.current_project()
            self.assertEqual(path.read_bytes(), original)
            self.assertNotIn("motion_preview", project["report"])
            self.assertEqual(loaded["report"]["motion_preview"]["kind"], "rotation")

    def test_old_static_revision_replaces_stale_unavailable_preview_on_read(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "project.json"
            project = dict(
                source_id="test-source",
                revision=8,
                connectors=[dict(type="plug", normal=[0, 0, 1], size_mm=8)],
                report={**valid_report(), "motion_preview": dict(status="unavailable")},
            )
            path.write_text(json.dumps(project), encoding="utf-8")
            original = path.read_bytes()
            with (
                patch.object(manual, "STATE", path),
                patch.object(manual, "initialize", return_value=dict(id="test-source")),
            ):
                loaded = manual.current_project()
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(loaded["report"]["motion_preview"]["kind"], "inspection_explode")


if __name__ == "__main__":
    unittest.main()
