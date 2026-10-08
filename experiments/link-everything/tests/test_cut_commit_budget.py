"""Commit accepts tiny preview islands and bounds dense final A/B meshes."""

import base64
import tempfile
import unittest
from pathlib import Path

from backend import cutting, manual
from backend.engine import mesh_solid, np, trimesh


class CutCommitBudget(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.old = manual.OUT, manual.STATE, manual.SOURCE
        manual.OUT = Path(cls.temp.name) / "manual"
        manual.STATE = manual.OUT / "project.json"
        manual.SOURCE = manual.OUT / "source.json"

    @classmethod
    def tearDownClass(cls):
        manual.OUT, manual.STATE, manual.SOURCE = cls.old
        cls.temp.cleanup()

    def test_preview_sub_one_mm3_is_explicitly_discardable_at_commit(self):
        sample = cutting.sample()["source"]
        main = manual._mesh(sample["stl"])
        speck = trimesh.creation.box(extents=[0.95, 0.95, 0.95])
        speck.apply_translation([30, 0, 14.5])
        scene = trimesh.Scene()
        scene.add_geometry(main, node_name="main")
        scene.add_geometry(speck, node_name="stray-speck")
        raw = scene.export(file_type="glb")
        source = cutting.upload(
            dict(data=base64.b64encode(raw).decode(), name="whole-with-speck.glb", units="mm", up_axis="Z")
        )["source"]
        preview = cutting.preview(dict(source_id=source["id"], mode="plane", origin_mm=[0, 0, 14], normal=[0, 0, 1]))
        tiny = [piece for piece in preview["components"] if 0.1 < piece["volume_mm3"] < 1]
        self.assertEqual(len(tiny), 1)
        self.assertTrue(tiny[0]["closed"])
        with self.assertRaisesRegex(ValueError, "体积不足 1 mm³"):
            manual._mesh(tiny[0]["stl"])
        right = next(
            piece for piece in preview["components"] if piece["side"] == "upper" and 0 < piece["center_mm"][0] < 25
        )
        result = cutting.commit(dict(preview_id=preview["id"], separate_ids=[right["id"]], discard_ids=[tiny[0]["id"]]))
        self.assertEqual(result["source"]["cut"]["discarded_ids"], [tiny[0]["id"]])
        self.assertEqual(len(result["source"]["parts"]), 2)
        self.assertTrue(
            all(part["closed"] and part["components"] == 1 for part in result["project"]["report"]["parts"])
        )
        kept = sum(part["volume_mm3"] for part in result["project"]["report"]["parts"])
        self.assertAlmostEqual(source["volume_mm3"] - kept, tiny[0]["volume_mm3"], delta=0.02)

    @staticmethod
    def _dense_box(n=145):
        """252,300 valid triangles over a 20×20×10 mm box."""
        low = np.array([-10.0, -10.0, 0.0])
        high = np.array([10.0, 10.0, 10.0])
        vertices = []
        faces = []
        for axis in range(3):
            b, c = (axis + 1) % 3, (axis + 2) % 3
            for sign in (-1, 1):
                offset = len(vertices)
                for i in range(n + 1):
                    for j in range(n + 1):
                        point = np.zeros(3)
                        point[axis] = low[axis] if sign < 0 else high[axis]
                        point[b] = low[b] + (high[b] - low[b]) * i / n
                        point[c] = low[c] + (high[c] - low[c]) * j / n
                        vertices.append(point)
                for i in range(n):
                    for j in range(n):
                        a = offset + i * (n + 1) + j
                        d = a + n + 1
                        for tri in ((a, d, d + 1), (a, d + 1, a + 1)):
                            faces.append(tri if sign > 0 else tri[::-1])
        result = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
        result.merge_vertices(digits_vertex=6)
        return result

    def test_dense_paired_faces_reduce_with_bounded_geometry_error(self):
        box = self._dense_box()
        self.assertTrue(box.is_watertight and box.is_winding_consistent)
        self.assertGreater(len(box.faces), cutting.MAX_FACES)
        manual.OUT.mkdir(parents=True, exist_ok=True)
        preview_stl = manual.OUT / "dense-preview.stl"
        box.export(preview_stl)
        self.assertEqual(len(cutting._preview_mesh(preview_stl).faces), len(box.faces))
        with self.assertRaisesRegex(ValueError, "超过每件 250000 面"):
            manual._mesh(preview_stl)
        lower = mesh_solid(box)
        upper = lower.translate([0, 0, 10])
        groups, meshes, tolerance = cutting._fit_commit_face_budget([lower, upper])
        self.assertIsNotNone(tolerance)
        self.assertLessEqual(tolerance, 0.1)
        self.assertEqual(len(groups), 2)
        self.assertTrue(
            all(
                mesh.is_watertight and mesh.is_winding_consistent and len(mesh.faces) <= cutting.MAX_FACES
                for mesh in meshes
            )
        )
        self.assertAlmostEqual(sum(mesh.volume for mesh in meshes), 8000, delta=8)
        self.assertLess((groups[0] ^ groups[1]).volume(), 1e-4)
        self.assertTrue(manual._face_at(meshes[0], np.array([0, 0, 10]), np.array([0, 0, 1])))
        self.assertTrue(manual._face_at(meshes[1], np.array([0, 0, 10]), np.array([0, 0, 1]), opposite=True))
        paths = [manual.OUT / "dense-final-a.stl", manual.OUT / "dense-final-b.stl"]
        for path, mesh in zip(paths, meshes):
            mesh.export(path)
        frozen = manual._source_from_files(paths, "dense-pair-budget-qa", "dense pair QA")
        self.assertEqual(len(frozen["parts"]), 2)

    def test_touching_closed_shells_survive_stl_roundtrip_without_false_watertight_claim(self):
        # STL discards vertex/shell identities. Individually closed cubes that
        # meet along an edge create a four-face non-manifold edge on reimport.
        primary = cutting.box([0, 0, 0], [10, 10, 10])
        tangent = cutting.box([10, 10, 0], [15, 15, 10])
        other = cutting.box([0, 0, 10], [10, 10, 15])
        groups = [[primary, tangent], [other]]
        meshes = [cutting._group_mesh(group) for group in groups]
        self.assertTrue(all(cutting._group_valid(group) for group in groups))
        self.assertFalse(cutting._stl_roundtrip(meshes[0])[1])
        adjusted, final, detail = cutting._fit_stl_roundtrip(groups, meshes, np.array([0, 0, 1]))
        self.assertIsNotNone(detail)
        self.assertEqual(detail["method"], "bounded_tangential_shell_separation")
        self.assertLessEqual(detail["max_displacement_mm"], 0.02)
        self.assertTrue(all(cutting._stl_roundtrip(mesh)[1] for mesh in final))
        self.assertEqual(len(cutting._stl_roundtrip(final[0])[0].split()), 2)
        self.assertAlmostEqual(final[0].volume, meshes[0].volume, delta=0.001)
        self.assertLessEqual(
            manual._group_overlap(adjusted[0], adjusted[1]),
            manual._overlap_tolerance(sum(mesh.volume for mesh in final)),
        )


if __name__ == "__main__":
    unittest.main()
