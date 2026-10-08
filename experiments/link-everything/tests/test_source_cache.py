"""Source-cache safety and byte-identical manual geometry regression."""

import json
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from backend import manual
from backend.engine import box, sha, to_trimesh
from backend.source_cache import SourceGeometryCache


def source_pair(folder):
    folder.mkdir(parents=True, exist_ok=True)
    paths = [folder / "part_a.stl", folder / "part_b.stl"]
    for path, bounds in zip(paths, (([-18, -15, 0], [18, 15, 10]), ([-18, -15, 10], [18, 15, 19]))):
        to_trimesh(box(*bounds)).export(path)
    return {
        "id": "cache-fixture",
        "label": "cache-fixture",
        "note": "test",
        "parts": [{"id": f"part_{label}", "stl": str(path), "sha256": sha(path)} for label, path in zip("ab", paths)],
    }


def build_direct(source):
    meshes = [manual._mesh(part["stl"]) for part in source["parts"]]
    return meshes, [mesh.split(only_watertight=False) for mesh in meshes]


class SourceCache(unittest.TestCase):
    def test_hit_returns_detached_geometry_and_switches_source(self):
        with tempfile.TemporaryDirectory() as temp:
            source = source_pair(Path(temp) / "inputs")
            cache = SourceGeometryCache()
            calls = []

            def builder():
                calls.append(1)
                return build_direct(source)

            first_meshes, first_shells = cache.load(source, builder)
            first_meshes[0].apply_translation([100, 0, 0])
            first_shells[0][0].apply_translation([100, 0, 0])
            second_meshes, second_shells = cache.load(source, builder)
            self.assertEqual(len(calls), 1)
            self.assertAlmostEqual(second_meshes[0].bounds[0][0], -18)
            self.assertAlmostEqual(second_shells[0][0].bounds[0][0], -18)
            self.assertEqual(cache.stats()["hits"], 1)

            changed = {**source, "id": "different-source"}
            cache.load(changed, builder)
            self.assertEqual(len(calls), 2)
            self.assertEqual(cache.stats()["source_id"], "different-source")
            # Same source ID but changed STL bytes must never hit stale data.
            to_trimesh(box([-19, -15, 0], [18, 15, 10])).export(source["parts"][0]["stl"])
            with self.assertRaisesRegex(RuntimeError, "内容已改变"):
                cache.load(source, builder)

    def test_budget_bypass_and_concurrent_single_build(self):
        with tempfile.TemporaryDirectory() as temp:
            source = source_pair(Path(temp) / "inputs")
            tiny = SourceGeometryCache(max_bytes=1)
            calls = []

            def builder():
                calls.append(1)
                return build_direct(source)

            tiny.load(source, builder)
            tiny.load(source, builder)
            self.assertEqual(len(calls), 2)
            self.assertEqual(tiny.stats()["cached_bytes_estimate"], 0)

            cache = SourceGeometryCache()
            count = [0]
            count_lock = threading.Lock()

            def slow_builder():
                with count_lock:
                    count[0] += 1
                time.sleep(0.03)
                return build_direct(source)

            with ThreadPoolExecutor(max_workers=6) as executor:
                results = list(executor.map(lambda _: cache.load(source, slow_builder), range(6)))
            self.assertEqual(count[0], 1)
            self.assertEqual(cache.stats()["hits"], 5)
            self.assertTrue(all(len(result[1][0]) == 1 for result in results))

    def test_manual_export_geometry_is_identical_with_and_without_cache(self):
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
            outputs = {}
            for mode, budget in (("uncached", 1), ("cached", 160 * 1024 * 1024)):
                out = root / mode
                out.mkdir()
                (out / "source.json").write_text(json.dumps(source), encoding="utf-8")
                cache = SourceGeometryCache(max_bytes=budget)
                with (
                    patch.object(manual, "OUT", out),
                    patch.object(manual, "STATE", out / "project.json"),
                    patch.object(manual, "SOURCE", out / "source.json"),
                    patch.object(manual, "CURRENT_SOURCE", cache),
                ):
                    empty = manual.generate({"source_id": source["id"], "connectors": []})
                    placed = manual.generate(
                        {"source_id": source["id"], "connectors": [connector], "revision": empty["revision"]}
                    )
                    outputs[mode] = [
                        (
                            project["report"],
                            [
                                sha(out / "revisions" / f"r{project['revision']:04d}" / f"part_{letter}.stl")
                                for letter in "ab"
                            ],
                        )
                        for project in (empty, placed)
                    ]
                if mode == "cached":
                    self.assertEqual(cache.stats()["misses"], 1)
                    self.assertEqual(cache.stats()["hits"], 1)
                else:
                    self.assertEqual(cache.stats()["misses"], 2)
            for revision_index in (0, 1):
                baseline, optimized = (outputs[mode][revision_index] for mode in ("uncached", "cached"))
                self.assertEqual(baseline[1], optimized[1], "STL export bytes changed")
                self.assertEqual(baseline[0]["parts"], optimized[0]["parts"])
                self.assertEqual(baseline[0]["static_overlap_mm3"], optimized[0]["static_overlap_mm3"])


if __name__ == "__main__":
    unittest.main()
