"""Printing checks must not mistake missing evidence for passing evidence."""

import pytest
import trimesh

from studio.core import manufacturing as m
from studio.core.kernels import mechanical_geometry as g
from studio.core.editor import EditorError


def dense_box(extents):
    mesh = trimesh.creation.box(extents)
    for _ in range(6):
        mesh = mesh.subdivide()
    assert len(mesh.faces) > 30000
    return mesh


def test_dense_thin_wall_is_measured_and_blocks_sampled_acceptance():
    mesh = dense_box([40, 40, 0.8])
    result = m.thickness_samples(mesh, 1.6)
    assert result["status"] == "sampled"
    assert len(result["samples"]) == 96
    assert result["min_sample_mm"] == pytest.approx(0.8)
    assert result["thin_samples"]
    report = m.assembly_audit({"thin_plate": mesh}, {"requirements": m.validate_requirements({}), "defects": []})
    assert report["status"] == "needs_review"
    assert report["thin_sample_parts"] == ["thin_plate"]


@pytest.mark.parametrize("result", [
    {"status": "not_checked", "reason": "face_budget"},
    {"status": "sampled", "samples": [], "thin_samples": []},
    {"status": "incomplete", "samples": [{"face": 0, "thickness_mm": 4}], "thin_samples": []},
])
def test_unmeasured_wall_cannot_pass_audit(monkeypatch, result):
    monkeypatch.setattr(m, "thickness_samples", lambda *args: result)
    report = m.assembly_audit({"body": trimesh.creation.box([10, 10, 10])},
                            {"requirements": m.validate_requirements({}), "defects": []})
    assert report["status"] == "needs_review"
    assert report["unchecked_thickness_parts"] == ["body"]


def test_withdrawal_stops_failed_directions_but_keeps_all_passing_samples(monkeypatch):
    host = g.box([-10, -10, -10], [10, 10, 0]) - g.cyl(2.2, -6, 0.01)
    meshes = {"pin_001": g.mesh(g.cyl(2, -5, 5)), "socket": g.mesh(host)}
    original = g.overlap
    calls = []

    def overlap(a, b):
        calls.append(1)
        return original(a, b)

    monkeypatch.setattr(g, "overlap", overlap)
    result = m.assembly_audit(meshes, {"requirements": m.validate_requirements({}), "defects": []})
    assert len(calls) < 100
    assert len(result["disassembly_steps"]) == 2
    first = result["disassembly_steps"][0]
    assert first["part"] == "pin_001"
    assert first["direction"] == [0, 0, 1]
    assert all(row["samples"] == 41 and row["max_overlap_mm3"] < 1e-5 for row in result["disassembly_steps"])


def test_dense_ray_samples_match_box_geometry_after_rotation():
    mesh = dense_box([40, 30, 4])
    mesh.apply_transform(trimesh.transformations.rotation_matrix(0.41, [1, 2, 3]))
    mesh.apply_translation([350, -120, 50])
    result = m.thickness_samples(mesh, 1.6)
    assert result["status"] == "sampled"
    assert len(result["samples"]) == 96
    for sample in result["samples"]:
        assert min(abs(sample["thickness_mm"] - size) for size in (40, 30, 4)) < 1e-6
    assert not result["thin_samples"]
    assert result["whole_wall_verified"] is False


def test_legacy_audit_remains_readable_but_new_delivery_requires_coverage(tmp_path):
    source = tmp_path / "source.stl"
    trimesh.creation.box([10, 10, 10]).export(source)
    store = m.Manufacturing(tmp_path / "manufacturing")
    doc = store.create([str(source)], {"split_mode": "keep"})
    geometry = tmp_path / "geometry.npz"
    geometry.write_bytes(b"fixture hash only")
    doc["stages"] = {
        "split": {"status": "completed", "scene": str(source), "sha256": m.sha(source),
                  "geometry": str(geometry), "geometry_sha256": m.sha(geometry),
                  "report": {"closed_outputs": True}},
        "prepare": {"status": "completed"},
        "audit": {"status": "completed", "report": {"status": "pass_sampled"}},
    }
    m.dump(store.folder(doc["id"]) / "workflow.json", doc)
    assert store.read(doc["id"])["stages"]["audit"]["report"]["status"] == "pass_sampled"
    with pytest.raises(EditorError, match="重跑|Rerun"):
        store.check_stage(doc, "deliver", {})
    doc["stages"]["audit"]["report"]["unchecked_thickness_parts"] = ["body"]
    with pytest.raises(EditorError):
        store.check_stage(doc, "deliver", {})
    doc["stages"]["audit"]["report"]["unchecked_thickness_parts"] = []
    store.check_stage(doc, "deliver", {})


def test_ray_without_exit_is_incomplete_evidence():
    mesh = trimesh.creation.box([10, 10, 10])
    mesh.update_faces([0])
    result = m.thickness_samples(mesh, 1.6)
    assert result["status"] == "incomplete"
    assert result["samples"] == []
    assert result["min_sample_mm"] is None
