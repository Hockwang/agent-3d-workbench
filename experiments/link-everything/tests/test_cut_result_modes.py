"""Verify cut result grouping and bed-ready exports preserve assembly geometry."""

import tempfile
import unittest
from pathlib import Path

from backend import cutting, manual
from backend.engine import trimesh


class CutResultModes(unittest.TestCase):
    def test_parts_group_and_print_orientations_are_real_exports(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = manual.OUT, manual.STATE, manual.SOURCE
            manual.OUT = Path(tmp) / "manual"
            manual.STATE = manual.OUT / "project.json"
            manual.SOURCE = manual.OUT / "source.json"
            try:
                source = cutting.sample()["source"]
                preview = cutting.preview(
                    dict(
                        source_id=source["id"],
                        mode="plane",
                        origin_mm=[0, 0, 14],
                        normal=[0, 0, 1],
                        amplitude_mm=1.2,
                        wavelength_mm=22,
                    )
                )
                selected = next(
                    x["id"] for x in preview["components"] if x["side"] == "upper" and x["center_mm"][0] > 0
                )
                project = cutting.commit(
                    dict(
                        preview_id=preview["id"],
                        separate_ids=[selected],
                        output_mode="parts",
                        print_orientation=dict(part_a="cut_face_down", part_b="flip"),
                    )
                )["project"]
                folder = Path(
                    next(x["absolute_path"] for x in project["artifacts"] if x["id"] == "assembly.glb")
                ).parent
                assembled = trimesh.load(folder / "assembly.glb", force="scene")
                self.assertEqual(len(assembled.geometry), 1)
                self.assertEqual(project["report"]["output_mode"], "parts")
                self.assertEqual(len(project["report"]["print_exports"]), 2)
                for key in ("part_a", "part_b"):
                    source_mesh = manual._mesh(folder / f"{key}.stl")
                    print_mesh = manual._mesh(folder / f"{key}_print.stl")
                    self.assertAlmostEqual(source_mesh.volume, print_mesh.volume, delta=0.01)
                    self.assertAlmostEqual(print_mesh.bounds[0][2], 0, places=4)
                    self.assertTrue((folder / f"{key}_print.glb").is_file())
                self.assertLess(project["report"]["static_overlap_mm3"], 1e-4)
            finally:
                manual.OUT, manual.STATE, manual.SOURCE = old


if __name__ == "__main__":
    unittest.main()
