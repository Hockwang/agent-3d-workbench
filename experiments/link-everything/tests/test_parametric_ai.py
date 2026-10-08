"""Isolated AI planning contract and real A/B CAD generation tests.

No paid provider call is made by this suite; the transport is injected while
all placement and Boolean validation still uses the real local geometry.
"""

import json
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from backend import manual, parametric_ai
from backend.engine import sha
from backend.server import Handler


class AIParametricWorkflow(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old = manual.OUT, manual.STATE, manual.SOURCE
        manual.OUT = Path(self.temp.name) / "manual"
        manual.STATE = manual.OUT / "project.json"
        manual.SOURCE = manual.OUT / "source.json"
        self.project = manual.current_project()
        self.hashes = [sha(Path(x["stl"])) for x in self.project["source"]["parts"]]

    def tearDown(self):
        manual.OUT, manual.STATE, manual.SOURCE = self.old
        self.temp.cleanup()

    def request(self, motion="fixed"):
        return dict(
            source_id=self.project["source_id"],
            revision=self.project["revision"],
            design_intent=dict(
                motion=motion,
                frequency="medium",
                removable=True,
                material="PETG",
                process="FDM",
                notes="camera shell lid",
            ),
        )

    @staticmethod
    def answer(families=("cantilever", "hinge")):
        return dict(
            analysis="小外壳需可拆连接，先试悬臂卡扣；强度与打印偏差仍需验证。",
            options=[
                dict(
                    family_id=family,
                    placement_index=0,
                    parameters=dict(
                        size_mm=6,
                        depth_mm=7,
                        beam_thickness_mm=1,
                        hook_mm=0.65,
                        size_tolerance_mm=0.25,
                        depth_tolerance_mm=0.15,
                    )
                    if family == "cantilever"
                    else {},
                    reason="根据使用方式与切面可用位置选择。",
                    risks=["材料应变与尺寸偏差需样件试印。"],
                )
                for family in families
            ],
        )

    def make_proposal(self, request=None, families=("cantilever", "hinge")):
        frozen = parametric_ai.snapshot(request or self.request())
        with patch.object(
            parametric_ai,
            "_model_response",
            return_value=(
                self.answer(families),
                dict(requested="gpt-6-sol", actual="gpt-6-sol", status="completed", usage=dict(total_tokens=123)),
            ),
        ):
            return parametric_ai.propose(frozen)

    def test_cantilever_writes_actual_distinct_watertight_pair(self):
        proposal = self.make_proposal()
        self.assertEqual(proposal["schema"], "parametric-ai.proposal/v1")
        self.assertEqual(proposal["source_id"], self.project["source_id"])
        self.assertEqual(proposal["revision"], self.project["revision"])
        self.assertTrue(proposal["analysis"]["geometry_summary"]["placements"])
        self.assertEqual(proposal["model"]["actual"], "gpt-6-sol")
        first = proposal["candidates"][0]
        self.assertEqual(first["family_id"], "cantilever")
        self.assertTrue(first["geometry_supported"])
        self.assertFalse(first["manufacturable"])
        self.assertEqual(proposal["candidates"][1]["family_id"], "hinge")
        self.assertFalse(proposal["candidates"][1]["geometry_supported"])
        with self.assertRaisesRegex(ValueError, "结构构想"):
            parametric_ai.generate(
                dict(
                    source_id=self.project["source_id"],
                    revision=self.project["revision"],
                    proposal_id=proposal["proposal_id"],
                    candidate_id=proposal["candidates"][1]["id"],
                )
            )
        response = parametric_ai.generate(
            dict(
                source_id=self.project["source_id"],
                revision=self.project["revision"],
                proposal_id=proposal["proposal_id"],
                candidate_id=first["id"],
            )
        )
        result = response["project"]
        self.assertEqual(response["schema"], "parametric-ai.generation/v1")
        self.assertEqual(result["connectors"][0]["type"], "cantilever")
        self.assertTrue(all(x["closed"] and x["components"] == 1 for x in result["report"]["parts"]))
        self.assertLess(result["report"]["static_overlap_mm3"], 1e-4)
        self.assertEqual([sha(Path(x["stl"])) for x in self.project["source"]["parts"]], self.hashes)
        artifacts = {x["id"]: Path(x["absolute_path"]) for x in result["artifacts"]}
        for name in ("part_a.stl", "part_b.stl", "assembly.glb", "parameters.json", "report.json"):
            self.assertTrue(artifacts[name].is_file(), name)
        with self.assertRaisesRegex(RuntimeError, "revision"):
            parametric_ai.generate(
                dict(
                    source_id=self.project["source_id"],
                    revision=self.project["revision"],
                    proposal_id=proposal["proposal_id"],
                    candidate_id=first["id"],
                )
            )
        # The Formlabs-inspired cantilever is not the old split axial pin with
        # a different display label: its distinct Boolean output is testable.
        snap = dict(
            type="snap",
            center_mm=first["placement"]["center_mm"],
            normal=first["placement"]["normal"],
            size_mm=6,
            depth_mm=7,
            size_tolerance_mm=0.25,
            depth_tolerance_mm=0.15,
            bulge_pct=15,
            space_pct=30,
        )
        old = manual.generate(dict(source_id=result["source_id"], revision=result["revision"], connectors=[snap]))
        old_artifacts = {x["id"]: x["sha256"] for x in old["artifacts"]}
        ai_artifacts = {x["id"]: x["sha256"] for x in result["artifacts"]}
        self.assertNotEqual(ai_artifacts["part_a.stl"], old_artifacts["part_a.stl"])
        self.assertNotEqual(ai_artifacts["part_b.stl"], old_artifacts["part_b.stl"])

    def test_motion_capability_and_bounds_are_hard_gates(self):
        rotate = self.make_proposal(self.request("rotate"), ("cantilever", "hinge"))
        self.assertFalse(rotate["candidates"][0]["geometry_supported"])
        self.assertTrue(rotate["candidates"][1]["geometry_supported"])
        slide = self.make_proposal(self.request("slide"), ("dovetail", "linear_rail"))
        self.assertFalse(slide["candidates"][0]["geometry_supported"])
        self.assertTrue(slide["candidates"][1]["geometry_supported"])
        proposal = self.make_proposal()
        with self.assertRaisesRegex(ValueError, "within"):
            parametric_ai.generate(
                dict(
                    source_id=self.project["source_id"],
                    revision=self.project["revision"],
                    proposal_id=proposal["proposal_id"],
                    candidate_id=proposal["candidates"][0]["id"],
                    overrides=dict(parameters=dict(hook_mm=900)),
                )
            )
        with self.assertRaisesRegex(ValueError, "共同切面"):
            parametric_ai.generate(
                dict(
                    source_id=self.project["source_id"],
                    revision=self.project["revision"],
                    proposal_id=proposal["proposal_id"],
                    candidate_id=proposal["candidates"][0]["id"],
                    overrides=dict(placement=dict(center_mm=[999, 999, 999])),
                )
            )

    def test_clicked_face_pins_static_location_and_nearest_hinge_side(self):
        source = self.project["source"]
        bounds = source["parts"][0]["bounds_mm"]
        for point, axis, sign in (
            ([0, 13, 10], 1, 1),
            ([0, -13, 10], 1, -1),
            ([16, 0, 10], 0, 1),
            ([-16, 0, 10], 0, -1),
        ):
            with self.subTest(point=point):
                request = self.request("rotate")
                request["anchor"] = dict(center_mm=point, normal=[0, 0, 1])
                frozen = parametric_ai.snapshot(request)
                descriptor = frozen["descriptor"]
                self.assertEqual(len(descriptor["placements"]), 1)
                self.assertEqual(descriptor["placements"][0]["center_mm"], point)
                hinges = descriptor["mechanism_placements"]["hinge"]
                self.assertEqual(len(hinges), 1)
                self.assertEqual(hinges[0]["origin"], "computed_nearest_clicked_edge")
                edge = hinges[0]["hinge_axis_center_mm"][axis]
                self.assertGreater(edge, bounds[1][axis]) if sign > 0 else self.assertLess(edge, bounds[0][axis])

        off_center = self.request("rotate")
        off_center["anchor"] = dict(center_mm=[4, 13, 10], normal=[0, 0, 1])
        placed = parametric_ai.snapshot(off_center)["descriptor"]["mechanism_placements"]["hinge"][0]
        self.assertAlmostEqual(placed["hinge_axis_center_mm"][0], 4, places=3)
        self.assertGreater(placed["hinge_axis_center_mm"][1], bounds[1][1])

        request = self.request("fixed")
        request["anchor"] = dict(center_mm=[0, 0, 10], normal=[0, 0, 1])
        frozen = parametric_ai.snapshot(request)
        self.assertEqual(len(frozen["descriptor"]["placements"]), 1)
        # The model may suggest another index, but a click may never be
        # silently replaced by a different computed face location.
        option = parametric_ai._option(
            dict(family_id="plug", placement_index=1, parameters=dict(size_mm=5, depth_mm=5)), 1, frozen
        )
        self.assertFalse(option["geometry_supported"])
        self.assertIsNone(option["placement"])

    def test_clicked_hinge_stays_on_side_when_ai_or_user_changes_radius(self):
        request = self.request("rotate")
        request["anchor"] = dict(center_mm=[0, 13, 10], normal=[0, 0, 1])
        frozen = parametric_ai.snapshot(request)
        proposed = self.answer(("hinge",))
        proposed["options"][0]["parameters"] = dict(knuckle_radius_mm=3.5)
        with patch.object(
            parametric_ai, "_model_response", return_value=(proposed, dict(actual="gpt-6-sol", status="completed"))
        ):
            proposal = parametric_ai.propose(frozen)
        candidate = proposal["candidates"][0]
        self.assertTrue(candidate["geometry_supported"], candidate["validation"])
        self.assertEqual(candidate["placement"]["hinge_axis_center_mm"][1], 19)
        self.assertEqual(candidate["placement_reference"]["hinge_edge_point_mm"][1], 15)
        command = dict(
            source_id=self.project["source_id"],
            revision=self.project["revision"],
            proposal_id=proposal["proposal_id"],
            candidate_id=candidate["id"],
        )
        with self.assertRaisesRegex(ValueError, "另一侧"):
            parametric_ai.generate({**command, "overrides": dict(placement=dict(hinge_axis_center_mm=[0, -19, 10]))})
        result = parametric_ai.generate({**command, "overrides": dict(parameters=dict(knuckle_radius_mm=4))})
        self.assertEqual(result["applied_candidate"]["placement"]["hinge_axis_center_mm"][1], 19.5)
        self.assertEqual(result["project"]["connectors"][0]["hinge_axis_center_mm"][1], 19.5)

    def test_saved_pre_fix_hinge_on_opposite_side_requires_reanalysis(self):
        proposal = self.make_proposal(self.request("rotate"), ("hinge",))
        selected = proposal["candidates"][0]
        self.assertTrue(selected["geometry_supported"])
        path = parametric_ai._proposal_path(proposal["proposal_id"])
        saved = json.loads(path.read_text(encoding="utf-8"))
        saved["requested_anchor"] = None
        saved["candidates"][0].pop("placement_reference", None)
        saved["candidates"][0]["placement"]["center_mm"] = [0, 13, 10]
        saved["analysis"]["geometry_summary"]["placements"].insert(
            0, dict(origin="user_anchor", center_mm=[0, 13, 10], normal=[0, 0, 1])
        )
        path.write_text(json.dumps(saved), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "旧方案将铰链布置在点选位置的另一侧"):
            parametric_ai.generate(
                dict(
                    source_id=self.project["source_id"],
                    revision=self.project["revision"],
                    proposal_id=proposal["proposal_id"],
                    candidate_id=selected["id"],
                )
            )

    def test_hinge_generates_real_pin_and_rotation_report(self):
        proposal = self.make_proposal(self.request("rotate"), ("hinge",))
        candidate = proposal["candidates"][0]
        self.assertTrue(candidate["engine_supported"] and candidate["geometry_supported"])
        self.assertEqual(candidate["precheck"], "full_motion_kernel")
        result = parametric_ai.generate(
            dict(
                source_id=self.project["source_id"],
                revision=self.project["revision"],
                proposal_id=proposal["proposal_id"],
                candidate_id=candidate["id"],
            )
        )
        report = result["project"]["report"]
        self.assertEqual(report["mechanisms"][0]["type"], "three_knuckle_hinge")
        self.assertTrue(report["mechanisms"][0]["rotation"]["opens_to_90_deg"])
        self.assertFalse(report["mechanisms"][0]["rotation"]["continuous_proof"])
        self.assertEqual(report["motion_preview"]["kind"], "rotation")
        self.assertEqual(report["motion_preview"]["pivot_mm"], report["mechanisms"][0]["axis_center_mm"])
        self.assertEqual(report["motion_preview"]["axis"], report["mechanisms"][0]["axis"])
        self.assertFalse(report["motion_preview"]["validation"]["continuous_proof"])
        self.assertTrue(report["mechanisms"][0]["pin_removal"]["removable"])
        self.assertEqual(len(report["pins"]), 1)
        self.assertTrue(all(part["closed"] for part in report["parts"]))
        self.assertEqual([sha(Path(x["stl"])) for x in self.project["source"]["parts"]], self.hashes)

    def test_finite_rail_generates_stop_and_travel_report(self):
        proposal = self.make_proposal(self.request("slide"), ("linear_rail",))
        candidate = proposal["candidates"][0]
        self.assertTrue(candidate["geometry_supported"])
        result = parametric_ai.generate(
            dict(
                source_id=self.project["source_id"],
                revision=self.project["revision"],
                proposal_id=proposal["proposal_id"],
                candidate_id=candidate["id"],
            )
        )
        report = result["project"]["report"]
        rail = report["mechanisms"][0]
        self.assertEqual(rail["type"], "captured_t_rail")
        self.assertTrue(rail["stop_removable"])
        self.assertEqual(rail["independent_print_parts"], 3)
        self.assertLessEqual(rail["stroke_sweep_overlap_mm3"], 0.001)
        self.assertLessEqual(rail["stop_insertion_sweep_overlap_mm3"], 0.001)
        self.assertFalse(rail["whole_part_continuous_proof"])
        self.assertEqual(report["motion_preview"]["kind"], "translation")
        self.assertEqual(report["motion_preview"]["range"], rail["allowed_offset_mm"])
        self.assertEqual(report["motion_preview"]["axis"], rail["travel_axis"])
        self.assertEqual(len(report["pins"]), 1)
        self.assertTrue(all(part["closed"] for part in report["parts"]))
        self.assertEqual([sha(Path(x["stl"])) for x in self.project["source"]["parts"]], self.hashes)

    def test_ai_replaces_manual_plug_without_changing_prior_revisions(self):
        for motion, family in (
            ("snap", "cantilever"),
            ("rotate", "hinge"),
            ("slide", "linear_rail"),
            ("fixed", "dowel"),
        ):
            with self.subTest(family=family):
                plug_option = self.make_proposal(self.request("fixed"), ("plug",))["candidates"][0]
                self.assertTrue(plug_option["geometry_supported"])
                self.project = manual.generate(
                    dict(
                        source_id=self.project["source_id"],
                        revision=self.project["revision"],
                        connectors=[
                            dict(id="manual-plug", type="plug", **plug_option["parameters"], **plug_option["placement"])
                        ],
                    )
                )
                previous = self.project
                prior_path = manual.OUT / "revisions" / f"r{previous['revision']:04d}" / "project.json"
                prior_hash = sha(prior_path)
                prior_artifacts = {item["id"]: sha(Path(item["absolute_path"])) for item in previous["artifacts"]}
                proposal = self.make_proposal(self.request(motion), (family,))
                candidate = proposal["candidates"][0]
                self.assertTrue(candidate["geometry_supported"], candidate["validation"])
                request = dict(
                    source_id=previous["source_id"],
                    revision=previous["revision"],
                    proposal_id=proposal["proposal_id"],
                    candidate_id=candidate["id"],
                )
                # Static candidates must use the same one-candidate geometry
                # path, rather than bridge.design appending a second connector.
                with patch.object(
                    parametric_ai.parametric_bridge, "design", side_effect=AssertionError("bridge must not append")
                ):
                    response = parametric_ai.generate(request)
                self.assertEqual(response["mode"], "replace_connectors")
                self.assertEqual(response["replaced_connector_count"], 1)
                self.assertEqual(response["base_revision"], previous["revision"])
                self.assertEqual(response["new_revision"], response["project"]["revision"])
                self.assertGreater(response["new_revision"], response["base_revision"])
                self.assertEqual(len(response["project"]["connectors"]), 1)
                self.assertEqual(response["project"]["connectors"][0]["type"], family)
                self.assertNotEqual(response["project"]["connectors"][0]["id"], "manual-plug")
                self.assertEqual(sha(prior_path), prior_hash)
                self.assertEqual(
                    {item["id"]: sha(Path(item["absolute_path"])) for item in previous["artifacts"]}, prior_artifacts
                )
                self.assertEqual(json.loads(prior_path.read_text(encoding="utf-8"))["connectors"][0]["type"], "plug")
                self.assertEqual([sha(Path(x["stl"])) for x in previous["source"]["parts"]], self.hashes)
                self.project = response["project"]

    def test_approximate_proxy_warning(self):
        frozen = parametric_ai.snapshot(self.request())
        frozen["descriptor"]["source_quality"]["approximate"] = True
        with patch.object(
            parametric_ai,
            "_model_response",
            return_value=(self.answer(("cantilever",)), dict(actual="gpt-6-sol", status="completed")),
        ):
            proposal = parametric_ai.propose(frozen)
        self.assertTrue(any("近似代理体" in x for x in proposal["candidates"][0]["risks"]))

    def test_source_bytes_changed_after_proposal_are_rejected(self):
        proposal = self.make_proposal()
        source_file = Path(self.project["source"]["parts"][0]["stl"])
        original = source_file.read_bytes()
        source_file.write_bytes(original[:-1] + bytes([original[-1] ^ 1]))
        with self.assertRaisesRegex(RuntimeError, "SHA-256"):
            parametric_ai.generate(
                dict(
                    source_id=self.project["source_id"],
                    revision=self.project["revision"],
                    proposal_id=proposal["proposal_id"],
                    candidate_id=proposal["recommended_id"],
                )
            )

    def test_http_propose_and_generate_contract(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        def post(path, payload):
            request = urllib.request.Request(
                f"http://127.0.0.1:{server.server_port}" + path,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=20) as response:
                return json.load(response)

        try:
            with patch.object(
                parametric_ai,
                "_model_response",
                return_value=(
                    self.answer(("cantilever",)),
                    dict(requested="gpt-6-sol", actual="gpt-6-sol", status="completed", usage=dict(total_tokens=123)),
                ),
            ):
                proposal = post("/api/parametric/ai/propose", self.request())
            self.assertEqual(proposal["model"]["actual"], "gpt-6-sol")
            self.assertNotIn("source_hashes", proposal)
            result = post(
                "/api/parametric/ai/generate",
                dict(
                    source_id=self.project["source_id"],
                    revision=self.project["revision"],
                    proposal_id=proposal["proposal_id"],
                    candidate_id=proposal["recommended_id"],
                ),
            )
            self.assertTrue(result["validation"]["static_watertight"])
            self.assertEqual(result["applied_candidate"]["family_id"], "cantilever")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
