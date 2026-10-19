import hashlib
import json
from pathlib import Path
import uuid
import zipfile

import numpy as np
import pytest
import trimesh

from studio.core.editor import EditorError
from studio.core.manufacturing import Manufacturing, clearance_candidates, diagnostic, run, sha, validate_requirements


class Queue:
    def __init__(self, root):
        self.root = root
        self.requests = {}
        self.states = {}

    def start(self, body, actor):
        identity = uuid.uuid4().hex
        folder = self.root / identity / "output"
        folder.mkdir(parents=True)
        self.requests[identity] = {**body, "output": str(folder)}
        self.states[identity] = dict(id=identity, status="running", actor=actor)
        return dict(task=self.states[identity])

    def state(self, identity):
        return self.states[identity]

    def cancel(self, identity):
        self.states[identity]["status"] = "cancelled"
        return dict(ok=True)


def fixture(tmp_path, mesh=None, **requirements):
    path = tmp_path / "source.ply"
    (mesh if mesh is not None else trimesh.creation.box([80, 40, 40])).export(path)
    tasks = Queue(tmp_path / "tasks")
    store = Manufacturing(tmp_path / "manufacturing", tasks)
    doc = store.create([str(path)], requirements)
    return store, tasks, doc, path


def call(store, doc, **body):
    latest = store.read(doc["id"])
    return store.execute(dict(id=doc["id"], expected_revision=latest["revision"], **body), "human")


def stage(store, tasks, doc, name, **body):
    result = call(store, doc, action="run", stage=name, **body)
    identity = result["task"]["id"]
    request = tasks.requests[identity]
    run(dict(params=request["params"], inputs=request["inputs"], output=request["output"]))
    tasks.states[identity]["status"] = "completed"
    return store.read(doc["id"])["stages"][name]


@pytest.mark.parametrize("clearance", [0.0001, 0.05, 0.1, 0.2, 1.9999, 2.0])
def test_coupon_candidates_keep_three_positive_recordable_fits(clearance):
    candidates = clearance_candidates(clearance)
    assert len(set(candidates)) == 3
    assert candidates == sorted(candidates)
    assert clearance in candidates
    assert all(0 < value <= 2 for value in candidates)


def test_small_clearance_coupon_delivers_three_real_socket_pin_pairs(tmp_path):
    store, tasks, doc, _ = fixture(tmp_path, clearance_mm=0.1)
    coupon = stage(store, tasks, doc, "coupon")
    assert coupon["report"]["clearance_candidates_mm"] == [0.05, 0.1, 0.2]
    outputs = list(Path(coupon["output"]).glob("*.stl"))
    assert len(outputs) == 6
    assert all(trimesh.load_mesh(path).is_volume for path in outputs)
    assert coupon["report"]["physical_calibration"] == "pending"
    assert store.read(doc["id"])["requirements"]["clearance_mm"] == 0.1


def test_frozen_source_revisions_and_invalidation_are_persistent(tmp_path):
    store, tasks, doc, path = fixture(tmp_path, split_mode="keep")
    original = path.read_bytes()
    inspected = stage(store, tasks, doc, "inspect")
    assert inspected["report"]["closed_outputs"]
    assert inspected["report"]["diagnostics"][0]["open_edges"] == 0
    assert inspected["report"]["self_intersections"] == "not_exhaustively_checked"
    split = stage(store, tasks, doc, "split")
    assert split["report"]["parts"][0]["id"] == "P001"
    other = Manufacturing(store.root, tasks)
    assert other.read(doc["id"])["stages"]["split"]["sha256"] == split["sha256"]
    with pytest.raises(EditorError, match="变化|changed"):
        store.execute(dict(action="update", id=doc["id"], expected_revision=0, requirements={"material": "PETG"}))
    updated = call(store, doc, action="update", requirements={"material": "PETG"})["workflow"]
    assert updated["stages"]["split"]["status"] == "completed"
    updated = call(store, doc, action="update", requirements={"target_max_mm": 100})["workflow"]
    assert updated["stages"]["inspect"]["status"] == "stale"
    assert path.read_bytes() == original
    assert Path(split["scene"]).exists()


def test_wall_requirement_invalidates_diagnostics_and_guided_split(tmp_path):
    store, tasks, doc, _ = fixture(tmp_path, split_mode="keep")
    stage(store, tasks, doc, "inspect")
    stage(store, tasks, doc, "split")
    updated = call(store, doc, action="update", requirements={"min_wall_mm": 3.2})["workflow"]
    assert updated["stages"]["inspect"]["status"] == "stale"
    assert updated["stages"]["split"]["status"] == "stale"
    with pytest.raises(EditorError, match="诊断|Inspect"):
        call(store, doc, action="run", stage="split")


def test_guided_split_rejects_unlabelled_extra_sources_before_queueing(tmp_path):
    store, tasks, _, first = fixture(tmp_path)
    second = tmp_path / "second.ply"
    trimesh.creation.box([10, 10, 10]).export(second)
    doc = store.create([str(first), str(second)], {"split_mode": "guided"})
    stage(store, tasks, doc, "inspect")
    pending = len(tasks.requests)
    with pytest.raises(EditorError, match="单个源模型|single source"):
        call(store, doc, action="run", stage="split")
    assert len(tasks.requests) == pending


def test_bad_mesh_is_diagnosed_and_cannot_proceed_before_repair(tmp_path):
    mesh = trimesh.creation.box([40, 40, 40])
    mesh.update_faces(np.arange(len(mesh.faces) - 1))
    store, tasks, doc, _ = fixture(tmp_path, mesh, split_mode="keep")
    result = stage(store, tasks, doc, "inspect")
    assert not result["report"]["closed_outputs"]
    assert result["report"]["diagnostics"][0]["open_edges"] == 3
    with pytest.raises(EditorError, match="孔洞|Repair"):
        stage(store, tasks, doc, "split")
    result = stage(store, tasks, doc, "local_repair")
    assert result["report"]["closed_outputs"] and result["report"]["repair_api_used"] is False
    assert stage(store, tasks, doc, "split")["report"]["closed_outputs"]
    assert call(store, doc, action="repair_status")["repair_api"]["available"] is False


def test_oversize_split_pins_audit_coupon_real_geometry(tmp_path):
    store, tasks, doc, source = fixture(tmp_path, trimesh.creation.box([500, 60, 60]))
    stage(store, tasks, doc, "inspect")
    split = stage(store, tasks, doc, "split")
    assert len(split["report"]["parts"]) > 1
    assert sum(p["volume_mm3"] for p in split["report"]["parts"]) == pytest.approx(500 * 60 * 60, rel=1e-5)
    connected = stage(store, tasks, doc, "connect")
    assert connected["report"]["seams"]
    assert any(p["id"].startswith("pin_") for p in connected["report"]["parts"])
    assert not connected["report"]["holding_strength_verified"]
    audit = stage(store, tasks, doc, "audit")
    assert audit["report"]["status"] == "pass_sampled", audit["report"]
    assert not audit["report"]["continuous_motion_checked"]
    assert len(audit["report"]["assembly_order"]) == len(connected["report"]["parts"])
    coupon = stage(store, tasks, doc, "coupon")
    assert coupon["report"]["clearance_candidates_mm"] == [0.1, 0.2, 0.3]
    assert all(trimesh.load_mesh(f).is_volume for f in Path(coupon["output"]).glob("*.stl"))
    calibrated = call(
        store, doc, action="calibration", clearance_mm=0.2, note="QA physical record, not actual fit assertion"
    )["workflow"]
    assert calibrated["calibration"][0]["coupon_sha256"] == coupon["sha256"]
    assert sha(source) == doc["sources"][0]["source_sha256"]


def test_guided_source_hash_bound_caps_and_merge(tmp_path):
    mesh = trimesh.creation.box([80, 40, 40]).subdivide()
    store, tasks, doc, path = fixture(tmp_path, mesh, split_mode="guided")
    stage(store, tasks, doc, "inspect")
    from studio.core.manufacturing import load_meshes

    original = load_meshes([path], safe_names=False)
    labels = dict(
        source_sha256=sha(path),
        nodes={n: ["left" if x < 0 else "right" for x in m.triangles_center[:, 0]] for n, m in original.items()},
    )
    call(store, doc, action="labels", labels=labels)
    split = stage(store, tasks, doc, "split")
    assert split["report"]["capped"]
    assert len(split["report"]["parts"]) == 2
    assert sum(p["volume_mm3"] for p in split["report"]["parts"]) == pytest.approx(mesh.volume, rel=1e-5)
    before = store.read(doc["id"])
    repeated = call(store, doc, action="labels", labels=labels)["workflow"]
    assert repeated["revision"] == before["revision"]
    assert repeated["stages"]["split"]["status"] == "completed"
    assert stage(store, tasks, doc, "connect")["report"]["seams"]
    call(store, doc, action="update", requirements={"label_map": {"left": "whole", "right": "whole"}})
    assert len(stage(store, tasks, doc, "split")["report"]["parts"]) == 1
    with pytest.raises(EditorError, match="SHA256"):
        call(store, doc, action="labels", labels={**labels, "source_sha256": "0" * 64})


def test_color_inlays_are_closed_and_wrong_pull_is_rejected(tmp_path):
    mesh = trimesh.creation.box([40, 40, 20])
    mesh.unmerge_vertices()
    mesh.visual.face_colors = [255, 255, 255, 255]
    mesh.visual.face_colors[mesh.face_normals[:, 2] > 0.9] = [255, 0, 0, 255]
    store, tasks, doc, _ = fixture(tmp_path, mesh, split_mode="color")
    stage(store, tasks, doc, "inspect")
    stage(store, tasks, doc, "local_repair")
    result = stage(store, tasks, doc, "split")["report"]
    assert len(result["parts"]) == 2
    assert {tuple(p["color_rgb"]) for p in result["parts"]} == {(255, 255, 255), (255, 0, 0)}
    assert all(p["name"] != p["id"] for p in result["parts"])
    call(store, doc, action="update", requirements={"clearance_mm": 0.25})
    assert store.read(doc["id"])["stages"]["split"]["status"] == "stale"
    stage(store, tasks, doc, "split")
    call(store, doc, action="update", requirements={"pull_direction": [0, 0, -1]})
    with pytest.raises(EditorError, match="outward_facing"):
        stage(store, tasks, doc, "split")
    assert store.read(doc["id"])["stages"]["split"]["status"] == "failed"


def test_guided_plane_fit_is_bounded_preserves_source_and_rejects_wrong_regions():
    from studio.core.manufacturing import fitted_guided_regions, cap_planar
    from studio.core.kernels import mechanical_geometry as g

    # A closed cylinder with fine side triangles and a slightly wavy P3 seam.
    angles = np.arange(32) * 2 * np.pi / 32
    vertices = [[10 * np.cos(a), 10 * np.sin(a), z] for z in np.linspace(-20, 20, 161) for a in angles]
    faces = []
    for ring in range(160):
        for j in range(32):
            a, b = ring * 32 + j, ring * 32 + (j + 1) % 32
            faces.extend([[a, b, b + 32], [a, b + 32, a + 32]])
    vertices.extend([[0, 0, -20], [0, 0, 20]])
    for j in range(32):
        faces.extend([[len(vertices) - 2, (j + 1) % 32, j],
                      [len(vertices) - 1, 160 * 32 + j, 160 * 32 + (j + 1) % 32]])
    mesh = trimesh.Trimesh(vertices, faces, process=False)
    center = mesh.triangles_center
    seam = .35 * np.sin(3 * np.arctan2(center[:, 1], center[:, 0]))
    values = np.where(center[:, 2] < seam, "bottom", "top")
    original = mesh.vertices.copy()
    with pytest.raises(EditorError, match="Nonplanar"):
        cap_planar(mesh.submesh([np.flatnonzero(values == "bottom")], append=True))
    parts, receipt = fitted_guided_regions(mesh, values, .6, [], 1.6)
    assert len(parts) == 2 and all(p.is_volume for _, p in parts)
    assert all(len(g.solid(p).decompose()) == 1 for _, p in parts)
    assert sum(p.volume for _, p in parts) == pytest.approx(mesh.volume, rel=1e-6)
    assert g.overlap(*(g.solid(p) for _, p in parts)) < 1e-6
    assert np.array_equal(mesh.vertices, original)
    assert receipt["cuts"][0]["max_boundary_error_mm"] <= .6
    assert max(r["worst_surface_reassignment_fraction"] for r in receipt["surface_agreement"]) < .05
    assert all(row["min_sample_mm"] >= 1.6 for row in receipt["thickness_samples"].values())
    with pytest.raises(EditorError, match="rejected"):
        fitted_guided_regions(mesh, values, .1, [])
    with pytest.raises(EditorError, match="rejected"):
        fitted_guided_regions(mesh, values, .6, [[[-20, -20, -1], [20, 20, 1]]])
    with pytest.raises(EditorError, match="rejected"):
        fitted_guided_regions(mesh, np.where(center[:, 0] * center[:, 2] < 0, "a", "b"), 20, [])
    with pytest.raises(EditorError):
        validate_requirements({"guided_seam_tolerance_mm": -.0001})


def test_old_workflow_without_seam_tolerance_updates_without_losing_checkpoints(tmp_path):
    store, tasks, doc, _ = fixture(tmp_path, split_mode="keep")
    stage(store, tasks, doc, "inspect")
    path = store.folder(doc["id"]) / "workflow.json"
    old = json.loads(path.read_text())
    del old["requirements"]["guided_seam_tolerance_mm"]
    path.write_text(json.dumps(old))
    new = call(store, doc, action="update", requirements={"material": "PETG"})["workflow"]
    assert new["requirements"]["guided_seam_tolerance_mm"] == 0
    assert new["stages"]["inspect"]["status"] == "completed"


def test_physical_defect_and_scope_cannot_be_cleared_by_ai(tmp_path):
    store, tasks, doc, _ = fixture(tmp_path, split_mode="keep")
    stage(store, tasks, doc, "inspect")
    stage(store, tasks, doc, "split")
    result = call(store, doc, action="defect", note="腿根有孔洞")["workflow"]
    assert stage(store, tasks, doc, "audit")["report"]["status"] == "needs_review"
    with pytest.raises(EditorError, match="本人|human"):
        store.execute(
            dict(
                action="defect",
                id=doc["id"],
                expected_revision=store.read(doc["id"])["revision"],
                defect_id=result["defects"][0]["id"],
                resolved=True,
                note="AI says fine",
            ),
            "ai",
        )
    assert store.read(doc["id"])["defects"][0]["resolved"] is False
    call(store, doc, action="defect", defect_id=result["defects"][0]["id"], resolved=True, note="Human fixture record")
    assert stage(store, tasks, doc, "audit")["report"]["status"] == "pass_sampled"
    with pytest.raises(EditorError, match="scope|会话"):
        store.read(doc["id"], scope=["other"])
    assert store.execute({"action": "list"}, scope=["other"])["workflows"] == []


def test_interrupted_worker_recovers_and_old_claim_cannot_publish(tmp_path):
    store, tasks, doc, _ = fixture(tmp_path)
    result = call(store, doc, action="run", stage="inspect")
    identity = result["task"]["id"]
    tasks.states[identity]["status"] = "interrupted"
    assert store.read(doc["id"])["active"] is None
    assert store.read(doc["id"])["stages"]["inspect"]["status"] == "interrupted"
    stage(store, tasks, doc, "inspect")
    digest = store.read(doc["id"])["stages"]["inspect"]["sha256"]
    old = tasks.requests[identity]
    with pytest.raises(EditorError, match="旧结果|Obsolete"):
        run(dict(params=old["params"], inputs=old["inputs"], output=old["output"]))
    assert store.read(doc["id"])["stages"]["inspect"]["sha256"] == digest


def test_api_workspace_route_and_immutable_source(studio_env, tmp_path):
    client, backend = studio_env["client"], studio_env["backend"]
    path = tmp_path / "fixture.stl"
    trimesh.creation.box([40, 40, 40]).export(path)
    code, result = client.post("/api/manufacture", dict(action="create", files=[str(path)]))
    assert code == 200, result
    doc = result["workflow"]
    code, result = client.post("/api/manufacture", dict(action="repair_status", id=doc["id"]))
    assert code == 200 and result["repair_api"]["status"] == "not_connected"
    assert backend.editor.state()["objects"] == []
    assert (
        client.post(
            "/api/manufacture", dict(action="update", id=doc["id"], expected_revision=99, requirements={"scale": 2})
        )[0]
        == 409
    )


def test_collaborative_backend_uses_member_scope_and_rejects_raw_scoped_sources(tmp_path):
    from studio.shell.server import StudioBackend
    from studio.core import collaboration as c
    from tests.helpers import session

    backend = StudioBackend(tmp_path / "job", "test")
    w = backend.editor
    for n in range(2):
        w.execute({"action": "primitive", "expected_revision": n})
    a, b = [o["id"] for o in w.doc["objects"]]
    with session("owner"):
        invite = c.control(w, {"action": "invite", "object_id": a, "worktree": str(tmp_path), "expected_revision": 2})
        assert backend.api_manufacture({"action": "list"}, "human")["workflows"] == []
        w.execute({"action": "select", "expected_revision": 2, "params": {"ids": [b]}})
        owner = backend.api_manufacture(
            {"action": "create", "from_selection": True, "expected_editor_revision": 2}, "human"
        )["workflow"]
    with session("child"):
        c.control(w, {"action": "join", "worktree": str(tmp_path), "invitation": invite["invitation"]})
        assert backend.api_manufacture({"action": "list"}, "human")["workflows"] == []
        with pytest.raises(EditorError, match="Scoped|会话"):
            backend.api_manufacture(
                {"action": "create", "files": [owner["sources"][0]["path"]], "source_ids": [a]}, "human"
            )
        child = backend.api_manufacture(
            {"action": "create", "from_selection": True, "expected_editor_revision": 2}, "human"
        )["workflow"]
        assert child["source_ids"] == [a]
        with pytest.raises(EditorError, match="scope|会话"):
            backend.api_manufacture({"action": "read", "id": owner["id"]}, "human")


def test_package_manifest_reprint_and_real_slice_receipts(tmp_path, monkeypatch):
    from studio.core import manufacturing as m
    from studio.core import task_operations

    calls = []

    def plates(meshes, requirements, out, strategy=None, check=False):
        calls.append((list(meshes), strategy, check))
        f = out / f"{strategy or 'plates'}.3mf"
        with zipfile.ZipFile(f, "w") as z:
            z.writestr("3D/3dmodel.model", "fixture only")
        return dict(
            plates=[dict(index=1, geometry_3mf=str(f))],
            check={"fixture": True} if check else None,
            print_submitted=False,
        )

    monkeypatch.setattr(m, "plate_job", plates)
    store, tasks, doc, _ = fixture(tmp_path, split_mode="keep")
    stage(store, tasks, doc, "inspect")
    stage(store, tasks, doc, "split")
    stage(store, tasks, doc, "audit")
    prepared = stage(store, tasks, doc, "prepare")
    stage(store, tasks, doc, "compare")
    exports = []
    original_deliver = task_operations.deliver

    def record_export(*args, **kwargs):
        exports.append(args[1])
        return original_deliver(*args, **kwargs)

    monkeypatch.setattr(task_operations, "deliver", record_export)
    package = stage(store, tasks, doc, "deliver")
    assert len(exports) == 1, "The complete mesh set must only be serialized once per delivery"
    archive = Path(package["output"]) / "manufacturing-package.zip"
    with zipfile.ZipFile(archive) as z:
        manifest = json.loads(z.read("manifest.json"))
        assert "BOM.csv" in manifest and "ASSEMBLY.txt" in manifest and "plate_01_geometry_3mf.3mf" in manifest
        assert all(hashlib.sha256(z.read(name)).hexdigest() == digest for name, digest in manifest.items())
    reprint = stage(store, tasks, doc, "reprint", part_ids=["P001"])
    assert reprint["report"]["selected_part_ids"] == ["P001"]
    assert store.read(doc["id"])["stages"]["prepare"]["sha256"] == prepared["sha256"]
    assert calls[1][1:] == ("flat", True) and calls[2][1:] == ("support", True)
    with pytest.raises(EditorError, match="有效零件|valid"):
        call(store, doc, action="run", stage="reprint", part_ids=["escape"])


def test_thin_walls_and_invalid_requirements_fail_explicitly(tmp_path):
    p = validate_requirements({})
    report = diagnostic({"plate": trimesh.creation.box([40, 40, 0.8])}, p)
    assert report["diagnostics"][0]["thickness"]["thin_samples"]
    assert report["diagnostics"][0]["thickness"]["whole_wall_verified"] is False
    for invalid in (
        {"scale": float("nan")},
        {"clearance_mm": 0},
        {"target_max_mm": 40, "scale": 2},
        {"palette_rgb": [[255, 0, 0], [255, 0, 0]]},
    ):
        with pytest.raises(Exception):
            validate_requirements(invalid)


def test_physical_photo_receipt_is_hashed_scoped_and_noop_settings_keep_results(tmp_path):
    import base64
    from PIL import Image

    store, tasks, doc, _ = fixture(tmp_path, split_mode="keep")
    photo = tmp_path / "defect.jpg"
    Image.new("RGB", (60, 40), "white").save(photo)
    stage(store, tasks, doc, "inspect")
    stage(store, tasks, doc, "split")
    before = store.read(doc["id"])
    same = call(store, doc, action="update", requirements={"material": "PLA"})["workflow"]
    assert same["revision"] == before["revision"]
    assert same["stages"]["split"]["status"] == "completed"
    record = call(store, doc, action="defect", note="fixture only", photos=[str(photo)])["workflow"]["defects"][0]
    result = store.execute({"action": "photo", "id": doc["id"], "defect_id": record["id"], "photo_index": 0})
    assert result["source_sha256"] == sha(photo) and base64.b64decode(result["data_base64"])[:2] == b"\xff\xd8"
    with pytest.raises(EditorError, match="scope|会话"):
        store.execute(
            {"action": "photo", "id": doc["id"], "defect_id": record["id"], "photo_index": 0}, scope=["outside"]
        )
    stage(store, tasks, doc, "coupon")
    changed = call(store, doc, action="update", requirements={"material": "PETG"})["workflow"]
    assert changed["stages"]["coupon"]["status"] == "stale"


def test_protected_region_refuses_unavoidable_geometric_cut(tmp_path):
    store, tasks, doc, source = fixture(
        tmp_path, trimesh.creation.box([500, 60, 60]), protected_boxes_mm=[[[-300, -40, -40], [300, 40, 40]]]
    )
    stage(store, tasks, doc, "inspect")
    with pytest.raises(Exception, match="找到|plan"):
        stage(store, tasks, doc, "split")
    assert store.read(doc["id"])["stages"]["split"]["status"] == "failed"
    assert sha(source) == doc["sources"][0]["source_sha256"]
