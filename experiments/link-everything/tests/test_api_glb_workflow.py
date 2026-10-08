"""Exercise the public GLB -> tilted cut -> paired connector HTTP workflow."""

import base64
import json
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from backend import manual, server
from backend.engine import mesh_solid, np


class GLBWorkflowHTTP(unittest.TestCase):
    def test_uploaded_glb_tilted_cut_keep_discard_and_download(self):
        original_paths = manual.OUT, manual.STATE, manual.SOURCE, server.ROOT
        server_instance = None
        thread = None
        with tempfile.TemporaryDirectory(prefix="connection-http-qa-") as temporary:
            root = Path(temporary).resolve()
            self.assertTrue(root.is_relative_to(Path(tempfile.gettempdir()).resolve()))
            manual.OUT = root / "outputs" / "manual"
            manual.STATE = manual.OUT / "project.json"
            manual.SOURCE = manual.OUT / "source.json"
            server.ROOT = root
            try:
                server_instance = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
                thread = threading.Thread(target=server_instance.serve_forever, daemon=True)
                thread.start()
                base = f"http://127.0.0.1:{server_instance.server_port}"

                def post(route, payload):
                    data = json.dumps(payload).encode()
                    request = urllib.request.Request(
                        base + route, data, headers={"Content-Type": "application/json"}, method="POST"
                    )
                    with urllib.request.urlopen(request, timeout=25) as response:
                        self.assertEqual(response.status, 200)
                        return json.load(response)

                def get_bytes(route):
                    with urllib.request.urlopen(base + route, timeout=10) as response:
                        self.assertEqual(response.status, 200)
                        return response.read()

                # Obtain a genuine binary glTF 2.0 GLB, then feed it through
                # the same upload route used by the browser file picker.
                sample = post("/api/manual/cut/sample", {})["source"]
                glb = get_bytes(sample["url"])
                self.assertEqual(glb[:4], b"glTF")
                uploaded = post(
                    "/api/manual/cut/upload",
                    dict(name="tilted-whole.glb", data=base64.b64encode(glb).decode(), units="m", up_axis="Y"),
                )["source"]
                self.assertEqual(uploaded["original_format"], "glb")
                self.assertEqual(get_bytes(uploaded["original_url"]), glb)

                normal = np.array([0.0, 0.2, 0.9797958971132712])
                preview = post(
                    "/api/manual/cut/preview",
                    dict(source_id=uploaded["id"], mode="plane", origin_mm=[0, 0, 14], normal=normal.tolist()),
                )
                self.assertEqual(len(preview["components"]), 3)
                self.assertTrue(all(piece["closed"] for piece in preview["components"]))
                upper = [p for p in preview["components"] if p["side"] == "upper"]
                right = next(p for p in upper if p["center_mm"][0] > 0)
                left = next(p for p in upper if p["center_mm"][0] < 0)
                for piece in preview["components"]:
                    self.assertEqual(get_bytes(piece["url"])[:4], b"glTF")

                committed = post(
                    "/api/manual/cut/commit",
                    dict(
                        preview_id=preview["id"],
                        separate_ids=[right["id"]],
                        discard_ids=[left["id"]],
                        output_mode="objects",
                        print_orientation={"part_a": "keep", "part_b": "cut_face_down"},
                    ),
                )
                self.assertEqual(committed["source"]["cut"]["discarded_ids"], [left["id"]])
                self.assertEqual(
                    committed["source"]["cut"]["merged_ids"],
                    [p["id"] for p in preview["components"] if p["side"] == "lower"],
                )
                self.assertTrue(all(part["closed"] for part in committed["project"]["report"]["parts"]))
                self.assertTrue(np.allclose(committed["source"]["cut"]["part_a_cut_normal"], normal))
                self.assertTrue(np.allclose(committed["source"]["cut"]["part_b_cut_normal"], -normal))

                spec = dict(
                    id="qa-tilted-plug",
                    type="plug",
                    style="prism",
                    shape="circle",
                    center_mm=[11, 0, 14],
                    normal=normal.tolist(),
                    size_mm=4,
                    depth_mm=4,
                    size_tolerance_mm=0.2,
                    depth_tolerance_mm=0.1,
                    rotation_deg=0,
                    bulge_pct=15,
                    space_pct=30,
                    flip=False,
                )
                project = post(
                    "/api/manual/design",
                    dict(
                        source_id=committed["project"]["source_id"],
                        revision=committed["project"]["revision"],
                        connectors=[spec],
                    ),
                )
                self.assertEqual(project["report"]["connector_count"], 1)
                self.assertLess(project["report"]["static_overlap_mm3"], 1e-4)
                self.assertTrue(all(p["closed"] and p["components"] == 1 for p in project["report"]["parts"]))

                originals = [manual._mesh(p["stl"]) for p in committed["source"]["parts"]]
                outputs = [
                    manual._mesh(next(a["absolute_path"] for a in project["artifacts"] if a["id"] == f"part_{key}.stl"))
                    for key in ("a", "b")
                ]
                # One shared world-space click adds the male to A and removes
                # the matching socket from B, with no assembly-space overlap.
                self.assertGreater(outputs[0].volume - originals[0].volume, 5)
                self.assertGreater(originals[1].volume - outputs[1].volume, 5)
                self.assertLess(float((mesh_solid(outputs[0]) ^ mesh_solid(outputs[1])).volume()), 1e-4)

                for name in (
                    "part_a.stl",
                    "part_b.stl",
                    "assembly.glb",
                    "part_a_print.stl",
                    "part_b_print.stl",
                    "report.json",
                ):
                    artifact = next(a for a in project["artifacts"] if a["id"] == name)
                    downloaded = get_bytes(artifact["url"])
                    self.assertEqual(downloaded, Path(artifact["absolute_path"]).read_bytes())
                self.assertEqual(
                    get_bytes(next(a["url"] for a in project["artifacts"] if a["id"] == "assembly.glb"))[:4], b"glTF"
                )
                print_b = manual._mesh(
                    next(a["absolute_path"] for a in project["artifacts"] if a["id"] == "part_b_print.stl")
                )
                self.assertAlmostEqual(print_b.bounds[0][2], 0, places=4)
            finally:
                if server_instance is not None:
                    server_instance.shutdown()
                    server_instance.server_close()
                if thread is not None:
                    thread.join(timeout=2)
                manual.OUT, manual.STATE, manual.SOURCE, server.ROOT = original_paths


if __name__ == "__main__":
    unittest.main()
