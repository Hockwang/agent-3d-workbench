"""End-to-end cutting, cap and paired-connector regression checks."""

import base64
import hashlib
import json
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from backend import cutting, manual
from backend.server import Handler
from backend.engine import np, trimesh


class CutWorkflow(unittest.TestCase):
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

    def _cut(self, mode, normal=(0, 0, 1)):
        source = cutting.sample()["source"]
        preview = cutting.preview(
            dict(
                source_id=source["id"],
                mode=mode,
                origin_mm=[0, 0, 14],
                normal=list(normal),
                amplitude_mm=1.2,
                wavelength_mm=22,
            )
        )
        self.assertEqual(len(preview["components"]), 3)
        self.assertTrue(all(x["closed"] for x in preview["components"]))
        right = next(x for x in preview["components"] if x["side"] == "upper" and x["center_mm"][0] > 0)
        committed = cutting.commit(dict(preview_id=preview["id"], separate_ids=[right["id"]]))
        self.assertEqual(len(committed["source"]["cut"]["merged_ids"]), 2)
        self.assertEqual(committed["project"]["report"]["connector_count"], 0)
        self.assertTrue(all(x["closed"] and x["components"] == 1 for x in committed["project"]["report"]["parts"]))
        self.assertLess(committed["project"]["report"]["static_overlap_mm3"], 1e-4)
        return committed

    def test_plane_cuts_two_places_but_only_right_separates(self):
        result = self._cut("plane")
        a, b = [manual._mesh(x["stl"]) for x in result["source"]["parts"]]
        self.assertAlmostEqual(a.bounds[1][2], 23, places=3)  # left tower stayed on the body
        self.assertGreater(b.bounds[0][0], 0)  # right cap separated
        connector = dict(
            id="on-right",
            type="plug",
            style="prism",
            shape="circle",
            center_mm=[11, 0, 14],
            normal=[0, 0, 1],
            depth_mm=5.5,
            size_mm=5.5,
            rotation_deg=0,
            clearance_mm=0.2,
            bulge_pct=15,
            space_pct=30,
            flip=False,
        )
        project = result["project"]
        placed = manual.generate(
            dict(source_id=project["source_id"], revision=project["revision"], connectors=[connector])
        )
        self.assertEqual(placed["report"]["connector_count"], 1)
        self.assertLess(placed["report"]["static_overlap_mm3"], 1e-4)

    def test_one_of_two_cut_caps_merges_into_connected_body(self):
        source = cutting.sample()["source"]
        preview = cutting.preview(dict(source_id=source["id"], mode="plane", origin_mm=[0, 0, 14], normal=[0, 0, 1]))
        self.assertEqual(len(preview["components"]), 3)
        (lower,) = (piece for piece in preview["components"] if piece["side"] == "lower")
        upper = [piece for piece in preview["components"] if piece["side"] == "upper"]
        left = next(piece for piece in upper if piece["center_mm"][0] < 0)
        right = next(piece for piece in upper if piece["center_mm"][0] > 0)
        self.assertTrue(all(piece["closed"] for piece in preview["components"]))
        result = cutting.commit(dict(preview_id=preview["id"], separate_ids=[right["id"]]))
        cut = result["source"]["cut"]
        self.assertEqual(cut["selected_ids"], [right["id"]])
        self.assertEqual(cut["merged_ids"], sorted([lower["id"], left["id"]]))
        self.assertEqual(cut["discarded_ids"], [])
        self.assertEqual(len(result["source"]["parts"]), 2)

        body, independent = [manual._mesh(part["stl"]) for part in result["source"]["parts"]]
        self.assertTrue(body.is_watertight and independent.is_watertight)
        self.assertEqual(len(body.split(only_watertight=True)), 1)
        self.assertEqual(len(independent.split(only_watertight=True)), 1)
        self.assertAlmostEqual(body.volume, lower["volume_mm3"] + left["volume_mm3"], delta=0.02)
        self.assertAlmostEqual(independent.volume, right["volume_mm3"], delta=0.02)
        self.assertAlmostEqual(body.volume + independent.volume, source["volume_mm3"], delta=0.02)
        self.assertAlmostEqual(body.bounds[1][2], 23, places=3)
        self.assertGreater(independent.bounds[0][0], 0)
        self.assertLess(result["project"]["report"]["static_overlap_mm3"], 1e-4)

    def test_disconnected_body_shells_remain_one_logical_part_through_connector_and_exports(self):
        # One connected arch is cut exactly at its bridge. The two lower legs
        # belong to part A even though they are no longer physically connected.
        whole = (
            cutting.box([-20, -6, 0], [-5, 6, 10])
            + cutting.box([5, -6, 0], [20, 6, 10])
            + cutting.box([-20, -6, 10], [20, 6, 18])
        )
        source = cutting._set_source(cutting.to_trimesh(whole), "arch", "sample")
        preview = cutting.preview(dict(source_id=source["id"], mode="plane", origin_mm=[0, 0, 10], normal=[0, 0, 1]))
        self.assertEqual([piece["side"] for piece in preview["components"]].count("lower"), 2)
        (upper,) = (piece for piece in preview["components"] if piece["side"] == "upper")
        result = cutting.commit(dict(preview_id=preview["id"], separate_ids=[upper["id"]], output_mode="parts"))
        pair, project = result["source"], result["project"]
        self.assertEqual((pair["cut"]["part_a_shells"], pair["cut"]["part_b_shells"]), (2, 1))
        self.assertEqual([part["components"] for part in project["report"]["parts"]], [2, 1])
        self.assertTrue(project["report"]["logical_grouping_only"])
        self.assertTrue(
            all(
                shell["closed"] and shell["volume_mm3"] > 0
                for part in project["report"]["parts"]
                for shell in part["shells"]
            )
        )
        self.assertLess(project["report"]["static_overlap_mm3"], 1e-4)
        a, b = [manual._mesh(part["stl"]) for part in pair["parts"]]
        self.assertEqual((len(a.split()), len(b.split())), (2, 1))
        self.assertAlmostEqual(a.volume + b.volume, source["volume_mm3"], delta=0.02)
        connector = dict(
            id="left-leg",
            type="plug",
            style="prism",
            shape="circle",
            center_mm=[-12.5, 0, 10],
            normal=[0, 0, 1],
            depth_mm=3,
            size_mm=3,
            rotation_deg=0,
            clearance_mm=0.2,
            bulge_pct=15,
            space_pct=30,
            flip=False,
        )
        placed = manual.generate(
            dict(source_id=project["source_id"], revision=project["revision"], connectors=[connector])
        )
        self.assertEqual([part["components"] for part in placed["report"]["parts"]], [2, 1])
        self.assertLess(placed["report"]["static_overlap_mm3"], 1e-4)
        folder = Path(
            next(item["absolute_path"] for item in placed["artifacts"] if item["id"] == "assembly.glb")
        ).parent
        self.assertEqual(len(trimesh.load(folder / "assembly.glb", force="mesh").split()), 3)
        self.assertEqual(len(manual._mesh(folder / "part_a.stl").split()), 2)

    def test_wave_cut_face_accepts_local_normal_paired_connector(self):
        result = self._cut("wave")
        mesh = manual._mesh(result["source"]["parts"][0]["stl"])
        candidates = np.where(
            (mesh.triangles_center[:, 0] > 7)
            & (mesh.triangles_center[:, 0] < 14)
            & (abs(mesh.triangles_center[:, 1]) < 3)
            & (mesh.face_normals[:, 2] > 0.5)
        )[0]
        self.assertGreater(len(candidates), 0)
        index = candidates[np.argmin(abs(mesh.triangles_center[candidates, 0] - 11))]
        connector = dict(
            id="on-wave",
            type="dowel",
            style="prism",
            shape="circle",
            center_mm=mesh.triangles_center[index].tolist(),
            normal=mesh.face_normals[index].tolist(),
            depth_mm=4,
            size_mm=3,
            rotation_deg=0,
            clearance_mm=0.2,
            bulge_pct=15,
            space_pct=30,
            flip=False,
        )
        project = result["project"]
        placed = manual.generate(
            dict(source_id=project["source_id"], revision=project["revision"], connectors=[connector])
        )
        self.assertEqual(len(placed["parts"]), 3)
        self.assertLess(placed["report"]["static_overlap_mm3"], 1e-4)

    def test_bowl_cut_is_sealed(self):
        self._cut("bowl")

    def test_discard_one_incidental_cut_piece_without_losing_connector_pair(self):
        source = cutting.sample()["source"]
        preview = cutting.preview(dict(source_id=source["id"], mode="plane", origin_mm=[0, 0, 14], normal=[0, 0, 1]))
        upper = [x for x in preview["components"] if x["side"] == "upper"]
        right = next(x for x in upper if x["center_mm"][0] > 0)
        left = next(x for x in upper if x["center_mm"][0] < 0)
        result = cutting.commit(
            dict(
                preview_id=preview["id"],
                separate_ids=[right["id"]],
                discard_ids=[left["id"]],
                output_mode="parts",
                print_orientation={"part_a": "flip", "part_b": "cut_face_down"},
            )
        )
        self.assertEqual(result["source"]["cut"]["discarded_ids"], [left["id"]])
        self.assertEqual(result["source"]["cut"]["output_mode"], "parts")
        self.assertEqual(result["source"]["cut"]["print_orientation"], {"part_a": "flip", "part_b": "cut_face_down"})
        self.assertTrue(np.allclose(result["source"]["cut"]["part_a_cut_normal"], [0, 0, 1]))
        self.assertTrue(np.allclose(result["source"]["cut"]["part_b_cut_normal"], [0, 0, -1]))
        self.assertLess(result["project"]["report"]["static_overlap_mm3"], 1e-4)
        kept_volume = sum(x["volume_mm3"] for x in result["project"]["report"]["parts"])
        self.assertAlmostEqual(source["volume_mm3"] - kept_volume, left["volume_mm3"], delta=0.01)

    def test_whole_stl_upload_and_invalid_source_preservation(self):
        sample = cutting.sample()["source"]
        raw = Path(sample["stl"]).read_bytes()
        uploaded = cutting.upload(dict(data=base64.b64encode(raw).decode(), name="whole.stl"))["source"]
        self.assertEqual(uploaded["kind"], "upload")
        self.assertEqual(uploaded["sha256"], sample["sha256"])
        with self.assertRaisesRegex(ValueError, "base64"):
            cutting.upload(dict(data="not STL base64!", name="bad.stl"))
        self.assertEqual(cutting.current()["source"]["id"], uploaded["id"])

    @staticmethod
    def _scene_glb():
        """A base and two instanced towers in metres/Y-up, with node transforms."""
        scene = trimesh.Scene()
        base = trimesh.creation.box(extents=[0.046, 0.008, 0.028])
        tower = trimesh.creation.box(extents=[0.016, 0.015, 0.020])
        scene.add_geometry(
            base,
            geom_name="base",
            node_name="base-node",
            transform=trimesh.transformations.translation_matrix([0, 0.004, 0]),
        )
        for x, name in [(-0.011, "left-node"), (0.011, "right-node")]:
            scene.add_geometry(
                tower,
                geom_name=name,
                node_name=name,
                transform=trimesh.transformations.translation_matrix([x, 0.0155, 0]),
            )
        return scene.export(file_type="glb")

    def test_multimesh_glb_transforms_units_and_cut_commit(self):
        raw = self._scene_glb()
        source = cutting.upload(dict(data=base64.b64encode(raw).decode(), name="scene.glb", units="m", up_axis="Y"))[
            "source"
        ]
        self.assertEqual(source["mesh_count"], 3)
        self.assertEqual(source["original_format"], "glb")
        self.assertEqual(source["input_units"], "m")
        self.assertEqual(source["input_up_axis"], "Y")
        self.assertEqual(len(source["original_sha256"]), 64)
        self.assertEqual(Path(source["stl"]).parent.joinpath("original.glb").read_bytes(), raw)
        self.assertTrue(np.allclose(source["bounds_mm"], [[-23, -14, 0], [23, 14, 23]], atol=0.001))
        self.assertGreater(source["volume_mm3"], 0)
        preview = cutting.preview(dict(source_id=source["id"], mode="plane", origin_mm=[0, 0, 14], normal=[0, 0, 1]))
        self.assertEqual(len(preview["components"]), 3)
        right = next(x for x in preview["components"] if x["side"] == "upper" and x["center_mm"][0] > 0)
        committed = cutting.commit(dict(preview_id=preview["id"], separate_ids=[right["id"]]))
        self.assertLess(committed["project"]["report"]["static_overlap_mm3"], 1e-4)
        self.assertTrue(all(x["closed"] for x in committed["project"]["report"]["parts"]))

    def test_glb_requires_explicit_units_and_imports_open_mesh_for_viewing(self):
        active = cutting.sample()["source"]
        raw = self._scene_glb()
        with self.assertRaisesRegex(ValueError, "明确选择单位"):
            cutting.upload(dict(data=base64.b64encode(raw).decode(), name="scene.glb"))
        self.assertEqual(cutting.current()["source"]["id"], active["id"])
        open_mesh = trimesh.Trimesh(vertices=[[0, 0, 0], [1, 0, 0], [0, 1, 0]], faces=[[0, 1, 2]], process=False)
        bad = trimesh.Scene(open_mesh).export(file_type="glb")
        source = cutting.upload(dict(data=base64.b64encode(bad).decode(), name="sheet.glb", units="mm"))["source"]
        self.assertFalse(source["cut_ready"])
        self.assertFalse(source["closed"])
        self.assertEqual(source["face_count"], 1)
        self.assertEqual(source["original_sha256"], hashlib.sha256(bad).hexdigest())
        self.assertEqual(Path(source["original_path"]).read_bytes(), bad)
        self.assertEqual(cutting.current()["source"]["id"], source["id"])
        with self.assertRaisesRegex(ValueError, "展示模型|不是可切割"):
            cutting.preview(dict(source_id=source["id"], mode="plane", origin_mm=[0, 0, 0], normal=[0, 0, 1]))

    def test_visual_glb_can_become_separate_approximate_cutting_proxy(self):
        sheet = trimesh.Trimesh(
            vertices=[[-0.01, -0.01, 0], [0.01, -0.01, 0], [0.01, 0.01, 0], [-0.01, 0.01, 0]],
            faces=[[0, 1, 2], [0, 2, 3]],
            process=False,
        )
        raw = trimesh.Scene(sheet).export(file_type="glb")
        visual = cutting.upload(dict(data=base64.b64encode(raw).decode(), name="surface.glb", units="m", up_axis="Z"))[
            "source"
        ]
        self.assertFalse(visual["cut_ready"])
        proxy_mesh = trimesh.creation.box(extents=[20, 20, 20])
        metrics = dict(
            method="test-voxel",
            approximate=True,
            pitch_mm=2.0,
            warning="近似切割代理，仅供测试",
            proxy_faces=len(proxy_mesh.faces),
        )
        with patch("backend.voxel_proxy.make_proxy", return_value=(proxy_mesh, metrics)) as make_proxy:
            proxy = cutting.solidify(dict(source_id=visual["id"]))["source"]
        make_proxy.assert_called_once()
        self.assertEqual(proxy["kind"], "proxy")
        self.assertTrue(proxy["cut_ready"])
        self.assertTrue(proxy["approximate"])
        self.assertEqual(proxy["visual_source_id"], visual["id"])
        self.assertEqual(proxy["original_sha256"], visual["original_sha256"])
        self.assertEqual(Path(proxy["stl"]).with_name("original.glb").read_bytes(), raw)
        self.assertEqual(cutting.current()["source"]["id"], proxy["id"])
        preview = cutting.preview(dict(source_id=proxy["id"], mode="plane", origin_mm=[0, 0, 0], normal=[0, 0, 1]))
        self.assertEqual(len(preview["components"]), 2)
        self.assertTrue(all(piece["closed"] for piece in preview["components"]))

    def test_failed_proxy_keeps_visual_source_active(self):
        sheet = trimesh.Trimesh(
            vertices=[[-0.01, -0.01, 0], [0.01, -0.01, 0], [0.01, 0.01, 0], [-0.01, 0.01, 0]],
            faces=[[0, 1, 2], [0, 2, 3]],
            process=False,
        )
        raw = trimesh.Scene(sheet).export(file_type="glb")
        visual = cutting.upload(dict(data=base64.b64encode(raw).decode(), name="surface.glb", units="m", up_axis="Z"))[
            "source"
        ]
        with patch("backend.voxel_proxy.make_proxy", side_effect=ValueError("代理失败")):
            with self.assertRaisesRegex(ValueError, "代理失败"):
                cutting.solidify(dict(source_id=visual["id"]))
        self.assertEqual(cutting.current()["source"]["id"], visual["id"])
        self.assertFalse(cutting.current()["source"]["cut_ready"])

    def test_glb_small_triangle_hole_is_closed_on_upload(self):
        # A missing triangle reaches Trimesh's NetworkX-backed hole-repair
        # branch. The public upload must produce a valid solid rather than a 500.
        cube = trimesh.creation.box(extents=[0.02, 0.02, 0.02])
        incomplete = trimesh.Trimesh(vertices=cube.vertices.copy(), faces=cube.faces[:-1].copy(), process=False)
        self.assertFalse(incomplete.is_watertight)
        raw = trimesh.Scene(incomplete).export(file_type="glb")
        source = cutting.upload(
            dict(data=base64.b64encode(raw).decode(), name="small-hole.glb", units="m", up_axis="Y")
        )["source"]
        self.assertTrue(source["closed"])
        self.assertTrue(any("filled small boundary holes" in note for note in source["repair_notes"]))
        self.assertAlmostEqual(source["volume_mm3"], 8000, places=1)

    def _cube_with_many_edge_hole(self, both_sides=False):
        """A dense cube with one or two 5 mm square, eight-edge holes."""
        cube = trimesh.creation.box(extents=[0.02, 0.02, 0.02])
        vertices, faces = cube.vertices, cube.faces
        for _ in range(3):
            vertices, faces = trimesh.remesh.subdivide(vertices, faces)
        dense = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
        centers = dense.triangles_center
        top_or_both = np.abs(dense.face_normals[:, 2]) > 0.99 if both_sides else dense.face_normals[:, 2] > 0.99
        missing = top_or_both & (np.abs(centers[:, 0]) < 0.0025) & (np.abs(centers[:, 1]) < 0.0025)
        self.assertEqual(int(missing.sum()), 16 if both_sides else 8)
        punctured = trimesh.Trimesh(vertices=vertices, faces=faces[~missing], process=False)
        self.assertFalse(punctured.is_watertight)
        return punctured

    def test_glb_many_edge_planar_hole_repairs_and_still_cuts(self):
        punctured = self._cube_with_many_edge_hole()
        raw = trimesh.Scene(punctured).export(file_type="glb")
        source = cutting.upload(
            dict(data=base64.b64encode(raw).decode(), name="planar-opening.glb", units="m", up_axis="Z")
        )["source"]
        self.assertEqual(source["original_sha256"], hashlib.sha256(raw).hexdigest())
        self.assertEqual(Path(source["stl"]).with_name("original.glb").read_bytes(), raw)
        self.assertTrue(source["closed"])
        self.assertTrue(source["repair_notes"])
        self.assertAlmostEqual(source["volume_mm3"], 8000, delta=0.1)
        preview = cutting.preview(dict(source_id=source["id"], mode="plane", origin_mm=[0, 0, 0], normal=[0, 0, 1]))
        self.assertEqual(len(preview["components"]), 2)
        self.assertTrue(all(piece["closed"] for piece in preview["components"]))

    def test_glb_two_separate_planar_holes_are_both_capped(self):
        punctured = self._cube_with_many_edge_hole(both_sides=True)
        raw = trimesh.Scene(punctured).export(file_type="glb")
        source = cutting.upload(
            dict(data=base64.b64encode(raw).decode(), name="two-openings.glb", units="m", up_axis="Z")
        )["source"]
        self.assertTrue(any("capped 2 planar boundary opening(s)" in note for note in source["repair_notes"]))
        self.assertTrue(manual._mesh(source["stl"]).is_watertight)
        self.assertAlmostEqual(source["volume_mm3"], 8000, delta=0.1)

    def test_nested_planar_boundary_rings_are_not_filled_as_overlapping_disks(self):
        cube = trimesh.creation.box(extents=[0.02, 0.02, 0.02])
        vertices, faces = cube.vertices, cube.faces
        for _ in range(3):
            vertices, faces = trimesh.remesh.subdivide(vertices, faces)
        dense = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
        centers = dense.triangles_center
        radial = np.maximum(np.abs(centers[:, 0]), np.abs(centers[:, 1]))
        annulus = (dense.face_normals[:, 2] > 0.99) & (radial > 0.0025) & (radial < 0.005)
        self.assertEqual(int(annulus.sum()), 24)
        open_ring = trimesh.Trimesh(vertices=vertices, faces=faces[~annulus], process=False)
        raw = trimesh.Scene(open_ring).export(file_type="glb")
        source = cutting.upload(
            dict(data=base64.b64encode(raw).decode(), name="annular-opening.glb", units="m", up_axis="Z")
        )["source"]
        self.assertFalse(source["cut_ready"])
        self.assertFalse(source["closed"])
        self.assertEqual(Path(source["original_path"]).read_bytes(), raw)
        self.assertIn("无法可靠自动修复", source["import_warning"])

    def test_glb_nonplanar_opening_keeps_original_visual_mesh(self):
        active = cutting.sample()["source"]
        punctured = self._cube_with_many_edge_hole()
        corner = np.where(
            (np.abs(punctured.vertices[:, 0] - 0.0025) < 1e-9)
            & (np.abs(punctured.vertices[:, 1] - 0.0025) < 1e-9)
            & (np.abs(punctured.vertices[:, 2] - 0.01) < 1e-9)
        )[0]
        self.assertEqual(len(corner), 1)
        punctured.vertices[int(corner[0]), 2] -= 0.001
        raw = trimesh.Scene(punctured).export(file_type="glb")
        source = cutting.upload(
            dict(data=base64.b64encode(raw).decode(), name="warped-opening.glb", units="m", up_axis="Z")
        )["source"]
        self.assertFalse(source["cut_ready"])
        self.assertIn("无法可靠自动修复", source["import_warning"])
        self.assertEqual(Path(source["original_path"]).read_bytes(), raw)
        self.assertEqual(cutting.current()["source"]["id"], source["id"])
        self.assertTrue(Path(active["stl"]).is_file())

    def test_glb_material_primitives_with_shared_hole_repair_as_one_shell(self):
        punctured = self._cube_with_many_edge_hole()
        scene = trimesh.Scene()
        for index, indices in enumerate((np.arange(0, len(punctured.faces), 2), np.arange(1, len(punctured.faces), 2))):
            surface = punctured.submesh([indices], append=True, repair=False)
            self.assertFalse(surface.is_watertight)
            scene.add_geometry(surface, node_name=f"material-{index}")
        raw = scene.export(file_type="glb")
        source = cutting.upload(
            dict(data=base64.b64encode(raw).decode(), name="split-material-hole.glb", units="m", up_axis="Z")
        )["source"]
        self.assertEqual(source["mesh_count"], 2)
        self.assertTrue(source["repair_notes"])
        self.assertTrue(manual._mesh(source["stl"]).is_watertight)
        self.assertAlmostEqual(source["volume_mm3"], 8000, delta=0.1)

    def test_open_visual_sheet_is_not_turned_into_an_arbitrary_solid(self):
        active = cutting.sample()["source"]
        sheet = trimesh.Trimesh(
            vertices=[[-0.01, -0.01, 0], [0.01, -0.01, 0], [0.01, 0.01, 0], [-0.01, 0.01, 0]],
            faces=[[0, 1, 2], [0, 2, 3]],
            process=False,
        )
        raw = trimesh.Scene(sheet).export(file_type="glb")
        source = cutting.upload(
            dict(data=base64.b64encode(raw).decode(), name="open-sheet.glb", units="m", up_axis="Z")
        )["source"]
        self.assertFalse(source["cut_ready"])
        self.assertIsNone(source["volume_mm3"])
        self.assertEqual(source["face_count"], 2)
        self.assertTrue(np.allclose(source["bounds_mm"], [[-10, -10, 0], [10, 10, 0]], atol=0.001))
        self.assertTrue(Path(active["stl"]).is_file())

    def test_disconnected_open_and_nonmanifold_glbs_remain_displayable(self):
        # These topologies occur together in exported product and scene GLBs.
        # Each valid file must enter the viewer even when it cannot be cut.
        variants = {}
        disconnected = trimesh.Scene()
        for index, x in enumerate((0.0, 0.03)):
            sheet = trimesh.Trimesh(
                vertices=[[x, 0, 0], [x + 0.01, 0, 0], [x, 0.01, 0]], faces=[[0, 1, 2]], process=False
            )
            disconnected.add_geometry(sheet, node_name=f"sheet-{index}")
        variants["disconnected"] = (disconnected.export(file_type="glb"), 2)
        shared_edge = trimesh.Trimesh(
            vertices=[[0, 0, 0], [0.02, 0, 0], [0, 0.02, 0], [0, 0, 0.02], [0, -0.02, 0]],
            faces=[[0, 1, 2], [1, 0, 3], [0, 1, 4]],
            process=False,
        )
        variants["nonmanifold"] = (trimesh.Scene(shared_edge).export(file_type="glb"), 1)
        for label, (raw, expected_nodes) in variants.items():
            with self.subTest(topology=label):
                source = cutting.upload(
                    dict(data=base64.b64encode(raw).decode(), name=f"{label}.glb", units="m", up_axis="Z")
                )["source"]
                self.assertFalse(source["cut_ready"])
                self.assertEqual(source["mesh_count"], expected_nodes)
                self.assertEqual(source["original_sha256"], hashlib.sha256(raw).hexdigest())
                self.assertEqual(Path(source["original_path"]).read_bytes(), raw)

    def test_valid_glb_survives_unexpected_solid_conversion_failure(self):
        raw = self._scene_glb()
        with patch.object(cutting, "_glb_mesh", side_effect=RuntimeError("Boolean backend unavailable")):
            source = cutting.upload(
                dict(data=base64.b64encode(raw).decode(), name="scene.glb", units="m", up_axis="Y")
            )["source"]
        self.assertFalse(source["cut_ready"])
        self.assertIn("Boolean backend unavailable", source["import_warning"])
        self.assertEqual(source["face_count"], 36)
        self.assertEqual(Path(source["original_path"]).read_bytes(), raw)
        corrupt = bytearray(raw)
        corrupt[0:4] = b"BAD!"
        with patch.object(cutting, "_glb_mesh", side_effect=RuntimeError("Boolean backend unavailable")):
            with self.assertRaisesRegex(ValueError, "文件头无效"):
                cutting.upload(
                    dict(data=base64.b64encode(corrupt).decode(), name="corrupt.glb", units="m", up_axis="Y")
                )
        self.assertEqual(cutting.current()["source"]["id"], source["id"])

    def test_valid_glb_survives_final_solid_gate_failure(self):
        raw = self._scene_glb()
        # Thick in X/Y, very thin in Z: printable-source checks can reject it
        # while the original scene remains perfectly useful for viewing.
        too_thin = trimesh.creation.box(extents=[100, 100, 0.005])
        with patch.object(cutting, "_glb_mesh", return_value=(too_thin, [], [])):
            source = cutting.upload(dict(data=base64.b64encode(raw).decode(), name="thin.glb", units="m", up_axis="Y"))[
                "source"
            ]
        self.assertFalse(source["cut_ready"])
        self.assertEqual(Path(source["original_path"]).read_bytes(), raw)
        self.assertIn("整件尺寸异常", source["import_warning"])

    def test_many_scene_nodes_can_still_import_for_viewing(self):
        raw = self._scene_glb()  # three instances
        with patch.object(cutting, "MAX_MESHES", 1):
            source = cutting.upload(
                dict(data=base64.b64encode(raw).decode(), name="many-nodes.glb", units="m", up_axis="Y")
            )["source"]
        self.assertFalse(source["cut_ready"])
        self.assertEqual(source["mesh_count"], 3)
        self.assertEqual(Path(source["original_path"]).read_bytes(), raw)

    def test_user_badcase_glbs_import_without_changing_original_bytes(self):
        import os

        configured = os.environ.get("CONNECTION_DEMO_BADCASE_DIR")
        if not configured:
            self.skipTest("optional local GLB fixtures are not configured")
        folder = Path(configured)
        paths = sorted(folder.glob("*.glb"))
        if not paths:
            self.skipTest("optional local GLB fixtures are not available")
        for path in paths:
            name = path.name
            with self.subTest(file=name):
                raw = (folder / name).read_bytes()
                source = cutting.upload(dict(data=base64.b64encode(raw).decode(), name=name, units="m", up_axis="Y"))[
                    "source"
                ]
                self.assertEqual(source["original_sha256"], hashlib.sha256(raw).hexdigest())
                self.assertEqual(
                    Path(source["stl"]).with_name("original.glb").read_bytes()
                    if source["cut_ready"]
                    else Path(source["original_path"]).read_bytes(),
                    raw,
                )
                self.assertGreater(source["face_count"], 0)
                self.assertTrue(source["url"])

    def test_face_budget_falls_back_to_visual_without_overwriting_saved_pair(self):
        before = [path.read_bytes() if path.exists() else None for path in (manual.STATE, manual.SOURCE)]
        manual.STATE.parent.mkdir(parents=True, exist_ok=True)
        manual.STATE.write_bytes(b"existing project")
        manual.SOURCE.write_bytes(b"existing paired source")
        raw = self._scene_glb()
        previous = cutting.MAX_FACES
        cutting.MAX_FACES = 10
        try:
            source = cutting.upload(
                dict(data=base64.b64encode(raw).decode(), name="complex.glb", units="m", up_axis="Y")
            )["source"]
            self.assertEqual(
                (manual.STATE.read_bytes(), manual.SOURCE.read_bytes()),
                (b"existing project", b"existing paired source"),
            )
        finally:
            cutting.MAX_FACES = previous
            for path, content in zip((manual.STATE, manual.SOURCE), before):
                if content is None:
                    path.unlink(missing_ok=True)
                else:
                    path.write_bytes(content)
        self.assertFalse(source["cut_ready"])
        self.assertEqual(source["mesh_count"], 3)
        self.assertEqual(source["face_count"], 36)
        self.assertEqual(source["original_url"], source["url"])
        self.assertEqual(Path(source["original_path"]).read_bytes(), raw)

    def test_invalid_glb_still_rejected_without_replacing_visual_source(self):
        sheet = trimesh.Trimesh(vertices=[[0, 0, 0], [1, 0, 0], [0, 1, 0]], faces=[[0, 1, 2]], process=False)
        raw = trimesh.Scene(sheet).export(file_type="glb")
        source = cutting.upload(dict(data=base64.b64encode(raw).decode(), name="valid-open.glb", units="mm"))["source"]
        broken = bytearray(raw)
        broken[0:4] = b"BAD!"
        with self.assertRaisesRegex(ValueError, "文件头无效"):
            cutting.upload(dict(data=base64.b64encode(broken).decode(), name="bad.glb", units="mm"))
        self.assertEqual(cutting.current()["source"]["id"], source["id"])

    def test_glb_upload_cap_is_50_mib_without_allocating_large_fixture(self):
        self.assertEqual(cutting.MAX_BYTES, 50 * 1024 * 1024)

        class OversizedBase64(str):
            def __len__(self):
                return cutting.MAX_BYTES * 4 // 3 + 5

        with self.assertRaisesRegex(ValueError, "50 MB"):
            cutting.upload(dict(data=OversizedBase64("AAAA"), name="over.glb", units="m", up_axis="Y"))

    def test_glb_material_primitives_form_one_closed_shell(self):
        cube = trimesh.creation.box(extents=[0.04, 0.02, 0.02])
        scene = trimesh.Scene()
        for index, indices in enumerate((list(range(6)), list(range(6, 12)))):
            surface = cube.submesh([indices], append=True, repair=False)
            self.assertFalse(surface.is_watertight)
            scene.add_geometry(surface, node_name=f"material-{index}")
        raw = scene.export(file_type="glb")
        source = cutting.upload(
            dict(data=base64.b64encode(raw).decode(), name="split-material.glb", units="m", up_axis="Y")
        )["source"]
        self.assertEqual(source["mesh_count"], 2)
        self.assertAlmostEqual(source["volume_mm3"], 16000, places=1)
        self.assertTrue(source["closed"])

    def test_real_camera_glb_touching_seams_cut_and_commit(self):
        # The bundled camera reference contains two closed shells touching
        # along four non-manifold edges after a 1 µm weld. It is not an open
        # sheet; importing it must preserve both shells without inventing a
        # cap or swallowing its original bytes.
        path = Path(__file__).resolve().parents[1] / "outputs" / "source" / "source_reference.glb"
        if not path.exists():
            self.skipTest("bundled camera reference GLB is unavailable")
        raw = path.read_bytes()
        source = cutting.upload(
            dict(data=base64.b64encode(raw).decode(), name="camera-reference.glb", units="m", up_axis="Y")
        )["source"]
        self.assertEqual(source["original_sha256"], hashlib.sha256(raw).hexdigest())
        self.assertIn("shell 0: separated touching closed seams", source["repair_notes"])
        preview = cutting.preview(
            dict(source_id=source["id"], mode="plane", origin_mm=[0, 0, 20], normal=[0, 0.1, 0.994987])
        )
        self.assertEqual(len(preview["components"]), 4)
        self.assertTrue(all(p["closed"] for p in preview["components"]))
        committed = cutting.commit(
            dict(preview_id=preview["id"], separate_ids=["piece_2"], discard_ids=["piece_1", "piece_3"])
        )
        self.assertEqual(len(committed["project"]["report"]["parts"]), 2)
        self.assertTrue(all(p["closed"] and p["components"] == 1 for p in committed["project"]["report"]["parts"]))
        self.assertLess(committed["project"]["report"]["static_overlap_mm3"], 1e-4)

    def test_glb_legacy_millimetre_z_up_and_mirrored_node(self):
        cube = trimesh.creation.box(extents=[20, 10, 8])
        scene = trimesh.Scene()
        mirror = np.eye(4)
        mirror[0, 0] = -1
        mirror[2, 3] = 4
        scene.add_geometry(cube, node_name="mirrored", transform=mirror)
        source = cutting.upload(
            dict(
                data=base64.b64encode(scene.export(file_type="glb")).decode(),
                name="legacy.glb",
                units="mm",
                up_axis="Z",
            )
        )["source"]
        self.assertTrue(np.allclose(source["bounds_mm"], [[-10, -5, 0], [10, 5, 8]], atol=0.001))
        self.assertAlmostEqual(source["volume_mm3"], 1600, places=1)

    def test_tampered_normalized_source_is_not_cut(self):
        source = cutting.sample()["source"]
        path = Path(source["stl"])
        path.write_bytes(path.read_bytes() + b"tampered")
        with self.assertRaisesRegex(RuntimeError, "不一致"):
            cutting.preview(dict(source_id=source["id"], mode="plane", origin_mm=[0, 0, 14], normal=[0, 0, 1]))

    def test_tampered_original_glb_is_not_cut(self):
        raw = self._scene_glb()
        source = cutting.upload(dict(data=base64.b64encode(raw).decode(), name="original.glb", units="m", up_axis="Y"))[
            "source"
        ]
        original = Path(source["stl"]).with_name("original.glb")
        original.write_bytes(original.read_bytes() + b"tampered")
        with self.assertRaisesRegex(RuntimeError, "上传原件"):
            cutting.preview(dict(source_id=source["id"], mode="plane", origin_mm=[0, 0, 14], normal=[0, 0, 1]))

    def test_http_upload_glb_then_preview(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"

        def post(route, payload):
            body = json.dumps(payload).encode()
            request = urllib.request.Request(
                base + route, body, headers={"Content-Type": "application/json"}, method="POST"
            )
            with urllib.request.urlopen(request, timeout=20) as reply:
                return json.load(reply)

        try:
            source = post(
                "/api/manual/cut/upload",
                dict(data=base64.b64encode(self._scene_glb()).decode(), name="http.glb", units="m", up_axis="Y"),
            )["source"]
            self.assertEqual(source["original_format"], "glb")
            preview = post(
                "/api/manual/cut/preview",
                dict(source_id=source["id"], mode="plane", origin_mm=[0, 0, 14], normal=[0, 0, 1]),
            )
            self.assertEqual(len(preview["components"]), 3)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
