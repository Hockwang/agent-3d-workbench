"""Per-placement manual defaults preserve small parts and scale up large ones."""

import tempfile
import unittest
from pathlib import Path

from backend import manual
from backend.engine import trimesh


def pair(scale=1):
    a = trimesh.creation.box(extents=[36 * scale, 30 * scale, 10 * scale])
    b = trimesh.creation.box(extents=[36 * scale, 30 * scale, 9 * scale])
    a.apply_translation([0, 0, 5 * scale])
    b.apply_translation([0, 0, 14.5 * scale])
    return a, b


def picked(x=0, z=10, **dimensions):
    return dict(
        id="adaptive-plug",
        type="plug",
        shape="circle",
        style="prism",
        center_mm=[x, 0, z],
        normal=[0, 0, 1],
        size_tolerance_mm=0.2,
        depth_tolerance_mm=0.1,
        **dimensions,
    )


class ManualAdaptiveSizing(unittest.TestCase):
    def test_small_and_large_pairs_get_different_widths(self):
        small = manual._suggested_dimensions(picked(), pair(), {})
        large = manual._suggested_dimensions(picked(z=200), pair(20), {})
        self.assertAlmostEqual(small["size_mm"], 5.5)
        self.assertGreaterEqual(large["size_mm"], 30)
        self.assertGreater(large["depth_mm"], small["depth_mm"])
        self.assertLessEqual(large["size_mm"], manual.MAX_MANUAL_SIZE_MM)

    def test_edge_point_shrinks_footprint_and_bad_point_is_rejected(self):
        meshes = pair(20)
        middle = manual._suggested_dimensions(picked(z=200), meshes, {})
        near_edge = manual._suggested_dimensions(picked(x=348, z=200), meshes, {})
        self.assertLess(near_edge["size_mm"], middle["size_mm"])
        with self.assertRaisesRegex(ValueError, "共同切面"):
            manual._suggested_dimensions(picked(x=500, z=200), meshes, {})

    def test_explicit_width_is_not_overwritten(self):
        result = manual._suggested_dimensions(picked(z=200, size_mm=9), pair(20), {})
        self.assertEqual(result["size_mm"], 9)

    def test_blank_fields_create_real_scaled_connector_without_live_state(self):
        with tempfile.TemporaryDirectory() as directory:
            old = (manual.OUT, manual.STATE, manual.SOURCE)
            root = Path(directory)
            manual.OUT = root / "manual"
            manual.STATE = manual.OUT / "project.json"
            manual.SOURCE = manual.OUT / "source.json"
            try:
                meshes = pair(10)
                paths = []
                for name, mesh in zip(("a", "b"), meshes):
                    path = root / f"{name}.stl"
                    mesh.export(path)
                    paths.append(path)
                source = manual._source_from_files(paths, "scaled-pair", "scaled test pair")
                project = manual.generate(dict(source_id=source["id"], connectors=[picked(z=100)]))
                self.assertGreater(project["connectors"][0]["size_mm"], 5.5)
                self.assertEqual(project["report"]["connector_count"], 1)
                self.assertTrue(all(part["closed"] for part in project["report"]["parts"]))
            finally:
                manual.OUT, manual.STATE, manual.SOURCE = old


if __name__ == "__main__":
    unittest.main()
