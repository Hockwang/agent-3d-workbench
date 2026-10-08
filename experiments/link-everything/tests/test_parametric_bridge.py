"""GLB cutting and parameter-driven connectors share one frozen A/B project."""

import base64
import hashlib
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from backend import cutting, manual, parametric_bridge
from backend.engine import sha, trimesh
from backend.server import Handler


class ParametricBridgeWorkflow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.old = manual.OUT, manual.STATE, manual.SOURCE
        manual.OUT = Path(cls.temp.name) / "manual"
        manual.STATE = manual.OUT / "project.json"
        manual.SOURCE = manual.OUT / "source.json"
        cls.http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.http.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.http.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown()
        cls.http.server_close()
        cls.thread.join(timeout=2)
        manual.OUT, manual.STATE, manual.SOURCE = cls.old
        cls.temp.cleanup()

    def request(self, route, payload=None):
        raw = json.dumps(payload).encode() if payload is not None else None
        request = urllib.request.Request(self.base + route, raw, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)

    def test_glb_cut_manual_and_parametric_share_pair_revisions_and_exports(self):
        sample = cutting.sample()["source"]
        raw = Path(sample["stl"]).with_name("whole.glb").read_bytes()
        uploaded = self.request(
            "/api/manual/cut/upload",
            dict(data=base64.b64encode(raw).decode(), name="imported-whole.glb", units="m", up_axis="Y"),
        )["source"]
        self.assertEqual(uploaded["original_sha256"], hashlib.sha256(raw).hexdigest())
        self.assertTrue(uploaded["cut_ready"])
        preview = self.request(
            "/api/manual/cut/preview",
            dict(source_id=uploaded["id"], mode="plane", origin_mm=[0, 0, 14], normal=[0, 0, 1]),
        )
        right = next(piece for piece in preview["components"] if piece["side"] == "upper" and piece["center_mm"][0] > 0)
        committed = self.request("/api/manual/cut/commit", dict(preview_id=preview["id"], separate_ids=[right["id"]]))
        source = committed["source"]
        baseline = committed["project"]
        original_pair_hashes = [sha(part["stl"]) for part in source["parts"]]
        self.assertEqual(source["cut"]["selected_ids"], [right["id"]])

        manually_placed = dict(
            id="manual-plug",
            type="plug",
            style="prism",
            shape="circle",
            center_mm=[11, 7, 14],
            normal=[0, 0, 1],
            depth_mm=3,
            size_mm=2.5,
            clearance_mm=0.2,
        )
        manual_project = self.request(
            "/api/manual/design",
            dict(source_id=source["id"], revision=baseline["revision"], connectors=[manually_placed]),
        )
        context = self.request("/api/parametric/context")
        self.assertEqual(context["schema"], "parametric-bridge.context/v1")
        self.assertEqual(context["alignment"]["status"], "aligned")
        self.assertEqual(context["source_id"], source["id"])
        self.assertEqual(context["revision"], manual_project["revision"])
        self.assertEqual(context["source"]["parts"], source["parts"])
        self.assertEqual([part["id"] for part in context["parts"]], ["part_a", "part_b"])
        self.assertEqual([item["id"] for item in context["connectors"]], ["manual-plug"])
        self.assertFalse(context["reference_presets"]["applies_to_current_parts"])
        self.assertEqual({item["id"] for item in context["families"]}, {"plug", "dowel", "snap", "dovetail"})

        state_hash = sha(manual.STATE)
        valid = self.request(
            "/api/parametric/placement/check",
            dict(source_id=source["id"], revision=context["revision"], center_mm=[11, 0, 14], normal=[0, 0, 1]),
        )
        self.assertEqual(valid["schema"], "paired-placement.check/v1")
        self.assertTrue(valid["valid"])
        self.assertIsNone(valid["reason"])
        from_b = self.request(
            "/api/manual/placement/check",
            dict(
                source_id=source["id"],
                revision=context["revision"],
                center_mm=[11, 0, 14],
                normal=[0, 0, -1],
                part_id="part_b",
            ),
        )
        self.assertTrue(from_b["valid"])
        self.assertEqual(from_b["normal_a_to_b"], [0.0, 0.0, 1.0])
        exterior = self.request(
            "/api/parametric/placement/check",
            dict(
                source_id=source["id"],
                revision=context["revision"],
                center_mm=[0, -14, 4],
                normal=[0, -1, 0],
                part_id="part_a",
            ),
        )
        self.assertFalse(exterior["valid"])
        self.assertIn("共同切面", exterior["reason"])
        self.assertEqual(sha(manual.STATE), state_hash)

        meshes = [manual._mesh(part["stl"]) for part in source["parts"]]
        with self.assertRaisesRegex(ValueError, "共同切面"):
            manual._validate_connector(dict(center_mm=[0, -14, 4], normal=[0, -1, 0]), meshes, source)
        with self.assertRaisesRegex(ValueError, "足迹超出"):
            manual._validate_connector(dict(center_mm=[11, 9, 14], normal=[0, 0, 1], size_mm=5.5), meshes, source)

        parameters = dict(
            size_mm=5.5, depth_mm=5.5, bulge_pct=15, space_pct=30, size_tolerance_mm=0.2, depth_tolerance_mm=0.1
        )
        request = dict(
            source_id=source["id"],
            revision=context["revision"],
            family_id="snap",
            placement=dict(center_mm=[11, 0, 14], normal=[0, 0, 1]),
            parameters=parameters,
        )
        project = self.request("/api/parametric/design", request)
        self.assertEqual(project["schema"], "manual-connectors.project/v1")
        self.assertEqual(project["source_id"], source["id"])
        self.assertEqual(project["report"]["connector_count"], 2)
        self.assertEqual(project["connectors"][0]["id"], "manual-plug")
        self.assertEqual(project["connectors"][1]["type"], "snap")
        self.assertLess(project["report"]["static_overlap_mm3"], 1e-4)
        self.assertTrue(all(part["closed"] and part["components"] == 1 for part in project["report"]["parts"]))
        self.assertEqual([sha(part["stl"]) for part in source["parts"]], original_pair_hashes)
        files = {entry["id"]: Path(entry["absolute_path"]) for entry in project["artifacts"]}
        for name in (
            "part_a.stl",
            "part_b.stl",
            "part_a.glb",
            "part_b.glb",
            "assembly.glb",
            "parameters.json",
            "report.json",
        ):
            self.assertTrue(files[name].is_file(), name)
            self.assertEqual(
                sha(files[name]), next(item["sha256"] for item in project["artifacts"] if item["id"] == name)
            )
        self.assertTrue(trimesh.load(files["part_a.stl"], force="mesh").is_watertight)
        self.assertTrue(trimesh.load(files["part_b.stl"], force="mesh").is_watertight)

        snap_id = project["connectors"][1]["id"]
        changed = self.request(
            "/api/parametric/design",
            {
                **request,
                "revision": project["revision"],
                "replace_id": snap_id,
                "parameters": {**parameters, "depth_mm": 4.5},
            },
        )
        self.assertGreater(changed["revision"], project["revision"])
        self.assertEqual([item["id"] for item in changed["connectors"]], ["manual-plug", snap_id])
        self.assertEqual(changed["report"]["connector_count"], 2)
        old_files = {item["id"]: item for item in project["artifacts"]}
        new_files = {item["id"]: item for item in changed["artifacts"]}
        self.assertNotEqual(old_files["part_a.stl"]["sha256"], new_files["part_a.stl"]["sha256"])
        self.assertEqual([sha(part["stl"]) for part in source["parts"]], original_pair_hashes)

        # Uploading a different whole GLB must expose a stale A/B pair and
        # block parameter edits before they can overwrite its saved revision.
        other = trimesh.Scene(trimesh.creation.box(extents=[0.02, 0.02, 0.02]))
        other_raw = other.export(file_type="glb")
        self.request(
            "/api/manual/cut/upload",
            dict(data=base64.b64encode(other_raw).decode(), name="another-whole.glb", units="m", up_axis="Y"),
        )
        stale = self.request("/api/parametric/context")
        self.assertEqual(stale["source_id"], source["id"])
        self.assertEqual(stale["alignment"]["status"], "stale_pair")
        self.assertFalse(stale["alignment"]["aligned"])
        self.assertTrue(stale["alignment"]["warning"])
        stale_pick = self.request(
            "/api/parametric/placement/check",
            dict(source_id=source["id"], revision=changed["revision"], center_mm=[11, 0, 14], normal=[0, 0, 1]),
        )
        self.assertFalse(stale_pick["valid"])
        self.assertTrue(stale_pick["reason"])
        project_hash = sha(manual.STATE)
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.request("/api/parametric/design", {**request, "revision": changed["revision"], "replace_id": snap_id})
        self.assertEqual(error.exception.code, 409)
        self.assertEqual(sha(manual.STATE), project_hash)

    def test_standalone_teaching_preset_cannot_masquerade_as_pair_connector(self):
        context = parametric_bridge.current()
        with self.assertRaisesRegex(ValueError, "standalone teaching presets"):
            parametric_bridge.design(
                dict(
                    source_id=context["source_id"],
                    revision=context["revision"],
                    family_id="cantilever",
                    placement=dict(center_mm=[11, 0, 14], normal=[0, 0, 1]),
                    parameters={},
                )
            )


if __name__ == "__main__":
    unittest.main()
