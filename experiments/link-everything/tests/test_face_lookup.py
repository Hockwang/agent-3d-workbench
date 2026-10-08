"""Indexed face lookup must keep the original point/normal acceptance rule."""

import json
import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import manual
from backend.engine import box, np, sha, to_trimesh
from backend.face_lookup import full_scan
from backend.source_cache import SourceGeometryCache
from tests.test_source_cache import source_pair


def reference(mesh, point, normal, opposite=False):
    return full_scan(mesh, np.asarray(point), np.asarray(normal), opposite, manual._point_in_triangle)


class FaceLookupEquivalence(unittest.TestCase):
    def test_box_face_points_edges_and_invalid_points_match_reference(self):
        mesh = to_trimesh(box([-18, -15, 0], [18, 15, 10]))
        rng = np.random.default_rng(8)
        points = [[0, 0, 10], [18, 0, 5], [0, 0, 9.85], [18.001, 0, 5], [0, 0, 12], [0, 0, 0]]
        points += [[float(x), float(y), 10] for x, y in rng.uniform([-20, -17], [20, 17], size=(40, 2))]
        for point in points:
            for normal in ([0, 0, 1], [1, 0, 0]):
                for opposite in (False, True):
                    with self.subTest(point=point, normal=normal, opposite=opposite):
                        self.assertEqual(
                            manual._face_at(mesh, np.asarray(point), np.asarray(normal), opposite),
                            reference(mesh, point, normal, opposite),
                        )

    def test_archived_car_shared_face_matches_reference_if_available(self):
        root = Path(__file__).resolve().parents[1]
        cases = ((35, [-171.15738423665366, -233.8148447672526, 178.3576202392578]), (41, [-230.377, 141.753, 8.99]))
        for revision, center in cases:
            project_path = root / "outputs" / "manual" / "revisions" / f"r{revision:04d}" / "project.json"
            if not project_path.is_file():
                continue
            source = json.loads(project_path.read_text(encoding="utf-8"))["source"]
            a, b = [manual._mesh(part["stl"]) for part in source["parts"]]
            normal = np.asarray(source["cut"]["part_a_cut_normal"])
            for radius, angle in ((0, 0), (0.8, 0), (0.8, math.pi / 2), (2, math.pi), (50, 0)):
                point = np.asarray(center) + np.asarray([radius * math.cos(angle), radius * math.sin(angle), 0])
                for mesh, opposite in ((a, False), (b, True)):
                    with self.subTest(revision=revision, point=point.tolist(), opposite=opposite):
                        self.assertEqual(
                            manual._face_at(mesh, point, normal, opposite), reference(mesh, point, normal, opposite)
                        )

    def test_manual_no_connector_and_one_connector_exports_match_reference(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = source_pair(root / "inputs")
            connector = dict(
                id="same-plug",
                type="plug",
                style="prism",
                shape="circle",
                center_mm=[0, 0, 10],
                normal=[0, 0, 1],
                depth_mm=5.5,
                size_mm=5.5,
                clearance_mm=0.2,
            )
            results = {}
            original_lookup = manual._face_at
            for mode in ("reference", "indexed"):
                out = root / mode
                out.mkdir()
                (out / "source.json").write_text(json.dumps(source), encoding="utf-8")
                lookup = reference if mode == "reference" else original_lookup
                with (
                    patch.object(manual, "OUT", out),
                    patch.object(manual, "STATE", out / "project.json"),
                    patch.object(manual, "SOURCE", out / "source.json"),
                    patch.object(manual, "CURRENT_SOURCE", SourceGeometryCache()),
                    patch.object(manual, "_face_at", lookup),
                ):
                    empty = manual.generate({"source_id": source["id"], "connectors": []})
                    placed = manual.generate(
                        {"source_id": source["id"], "connectors": [connector], "revision": empty["revision"]}
                    )
                    results[mode] = [
                        [
                            sha(out / "revisions" / f"r{project['revision']:04d}" / f"part_{letter}.stl")
                            for letter in "ab"
                        ]
                        for project in (empty, placed)
                    ]
            self.assertEqual(results["reference"], results["indexed"])


if __name__ == "__main__":
    unittest.main()
