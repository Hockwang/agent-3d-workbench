from __future__ import annotations

import hashlib
import json
import zipfile

import numpy as np
import pytest
import trimesh
from PIL import Image

from studio.core.editor import Workspace, EditorError
from tests.helpers import act


def test_nearby_vertices_survive_storage_archive_and_stl_export(w, tmp_path):
    mesh = trimesh.creation.box([0.000002, 20, 30])
    mesh.apply_translation([100, 0, 0])
    source = tmp_path / "precision.stl"
    source.write_text(mesh.export(file_type="stl_ascii"))
    act(w, "import", files=[str(source)])
    assert act(w, "inspect")["reports"][0]["watertight"]
    obj = w.state()["objects"][0]
    np.testing.assert_array_equal(w.mesh(obj).triangles, mesh.triangles)
    archive = act(w, "save")["path"]
    other = Workspace(tmp_path / "restored")
    act(other, "open", path=archive)
    np.testing.assert_array_equal(other.mesh(other.state()["objects"][0]).triangles, mesh.triangles)
    exported = act(other, "export", format="stl")["path"]
    result = trimesh.load_mesh(exported, process=True)
    assert result.is_watertight and result.is_volume
    assert result.volume == pytest.approx(mesh.volume, rel=1e-6)


def test_inspect_welds_uv_seams_without_splitting_or_copying_textures(w, tmp_path, monkeypatch):
    box = trimesh.creation.box([20, 30, 40])
    # One UV island per face: closed geometry with deliberately disconnected UVs.
    mesh = trimesh.Trimesh(box.triangles.reshape(-1, 3), np.arange(36).reshape(-1, 3), process=False)
    mesh.visual = trimesh.visual.TextureVisuals(
        uv=np.arange(72).reshape(36, 2) / 72,
        material=trimesh.visual.material.PBRMaterial(baseColorTexture=Image.new("RGB", (16, 16), "red")),
    )
    path = tmp_path / "seamed.glb"
    trimesh.Scene(mesh).export(path)
    act(w, "import", files=[str(path)], units="mm")
    before = w.path.read_bytes()

    def no_materialized_components(*args, **kwargs):
        raise AssertionError("inspection must count face components without constructing textured submeshes")

    monkeypatch.setattr(trimesh.Trimesh, "split", no_materialized_components)
    report = act(w, "inspect")["reports"][0]
    assert report["watertight"] and report["components"] == 1
    assert report["boundary_edges"] == 0
    assert report["volume_mm3"] == pytest.approx(24000)
    assert w.path.read_bytes() == before
    assert w.mesh(w.state()["objects"][0]).visual.uv.shape == (36, 2)


@pytest.fixture
def w(tmp_path):
    return Workspace(tmp_path / "workspace")


def test_print_geometry_3mf_import_preserves_units_and_build_transform(w, tmp_path):
    from print_prep.export3mf import write_geometry_3mf

    path = tmp_path / "placed.3mf"
    placement = trimesh.transformations.translation_matrix([70, 50, 20])
    write_geometry_3mf(path, {"box": trimesh.creation.box([20, 30, 40])}, [{"part": "box", "T": placement}])
    act(w, "import", files=[str(path)])
    obj = w.state()["objects"][0]
    assert obj["extents_mm"] == pytest.approx([20, 30, 40])
    assert np.mean(obj["bounds_mm"], axis=0) == pytest.approx([70, 50, 20])
    report = act(w, "inspect")["reports"][0]
    assert report["watertight"] and report["components"] == 1


def test_cut_preserves_volume_and_original_then_undo_redo(w):
    act(w, "primitive", size=[20, 30, 40])
    original = w.state()["objects"][0]
    raw = w.asset_bytes(original["asset"])
    act(w, "plane_cut", point_mm=[0, 0, 7])
    objects = w.state()["objects"]
    assert len(objects) == 2
    assert all(w.mesh(o).is_volume for o in objects)
    assert sum(w.mesh(o).volume for o in objects) == pytest.approx(24000)
    assert [o["extents_mm"][2] for o in objects] == pytest.approx([13, 27])
    act(w, "undo")
    assert w.state()["objects"][0]["id"] == original["id"]
    assert w.asset_bytes(original["asset"]) == raw
    act(w, "redo")
    assert len(w.state()["objects"]) == 2
    act(w, "undo")
    act(w, "rename", name="New branch")
    assert not w.state()["can_redo"]


def test_stale_write_and_failed_cut_leave_project_unchanged(w):
    act(w, "primitive")
    before = w.path.read_bytes()
    with pytest.raises(EditorError, match="工程已改变"):
        w.execute({"action": "delete", "expected_revision": 0})
    with pytest.raises(EditorError, match="有效实体"):
        act(w, "plane_cut", point_mm=[0, 0, 100])
    assert w.path.read_bytes() == before


def test_gltf_world_transforms_texture_and_units_roundtrip(w, tmp_path):
    mesh = trimesh.creation.box([0.02, 0.04, 0.06])
    mesh.visual = trimesh.visual.TextureVisuals(
        uv=np.zeros((len(mesh.vertices), 2)),
        material=trimesh.visual.material.PBRMaterial(
            baseColorTexture=Image.new("RGB", (4, 4), "red"), roughnessFactor=0.3, metallicFactor=0.2
        ),
    )
    scene = trimesh.Scene()
    matrix = trimesh.transformations.translation_matrix([0.1, 0.2, 0.3])
    scene.add_geometry(mesh, node_name="textured", transform=matrix)
    source = tmp_path / "source.glb"
    scene.export(source)
    sha = hashlib.sha256(source.read_bytes()).hexdigest()
    act(w, "import", files=[str(source)])
    obj = w.state()["objects"][0]
    assert obj["extents_mm"] == pytest.approx([20, 60, 40], abs=1e-4)
    assert np.mean(obj["bounds_mm"], axis=0) == pytest.approx([100, -300, 200], abs=1e-4)
    assert obj["textured"]
    with pytest.raises(EditorError, match="纯色"):
        act(w, "plane_cut")
    act(w, "transform", translate_mm=[10, 0, 0])
    act(w, "material", roughness=0.8, metallic=0.1, color="#ffffff")
    act(w, "rename", name="保留材质和名字")
    exported = act(w, "export", format="glb")["path"]
    new = Workspace(tmp_path / "reimport")
    act(new, "import", files=[exported])
    final = new.state()["objects"][0]
    assert final["textured"]
    assert final["name"] == "保留材质和名字"
    assert np.mean(final["bounds_mm"], axis=0) == pytest.approx([110, -300, 200], abs=1e-3)
    assert new.mesh(final).visual.material.roughnessFactor == pytest.approx(0.8)
    assert hashlib.sha256(source.read_bytes()).hexdigest() == sha


def test_multi_selection_transform_duplicate_visibility_and_export(w, tmp_path):
    act(w, "primitive")
    act(w, "duplicate")
    act(w, "transform", translate_mm=[40, 0, 0])
    all_ids = [o["id"] for o in w.state()["objects"]]
    act(w, "select", ids=all_ids)
    act(w, "transform", scale=[2, 2, 2])
    assert np.diff(np.array(w.state()["bounds_mm"]), axis=0)[0] == pytest.approx([120, 40, 40])
    act(w, "visibility", ids=[all_ids[0]], visible=False)
    output = act(w, "export", format="stl")["path"]
    assert trimesh.load_mesh(output).extents == pytest.approx([40, 40, 40])
    with pytest.raises(EditorError, match="已存在"):
        act(w, "export", path=output, format="stl")
    act(w, "delete", ids=[all_ids[1]])
    act(w, "undo")
    assert len(w.state()["objects"]) == 2
    restored = Workspace(w.root)
    assert restored.state() == w.state()


def test_archive_is_self_contained_and_can_be_undone(w, tmp_path):
    act(w, "primitive")
    act(w, "rename", name="小立方")
    saved = act(w, "save")["path"]
    new = Workspace(tmp_path / "new")
    act(new, "open", path=saved)
    assert new.state()["objects"][0]["name"] == "小立方"
    assert new.mesh(new.state()["objects"][0]).volume == pytest.approx(8000)
    act(new, "undo")
    assert not new.state()["objects"]
    with zipfile.ZipFile(saved) as z:
        manifest = json.loads(z.read("manifest.json"))
        asset = manifest["objects"][0]["asset"]
        raw = z.read(f"assets/{asset}.glb")
    corrupt = tmp_path / "corrupt.3dworkbench"
    with zipfile.ZipFile(corrupt, "w") as z:
        z.writestr("manifest.json", json.dumps(manifest))
        z.writestr(f"assets/{asset}.glb", raw + b"bad")
    before = new.path.read_bytes()
    with pytest.raises(EditorError, match="校验失败"):
        act(new, "open", path=str(corrupt))
    assert new.path.read_bytes() == before


def test_boolean_and_components_use_real_geometry(w):
    act(w, "primitive")
    act(w, "duplicate")
    act(w, "transform", translate_mm=[10, 0, 0])
    ids = [o["id"] for o in w.state()["objects"]]
    act(w, "select", ids=ids)
    act(w, "boolean", operation="union")
    obj = w.state()["objects"][0]
    assert w.mesh(obj).volume == pytest.approx(12000)
    act(w, "undo")
    act(w, "transform", ids=[ids[1]], translate_mm=[50, 0, 0])
    act(w, "merge", ids=ids)
    act(w, "split_components")
    assert len(w.state()["objects"]) == 2


def test_repair_and_simplify_report_actual_output(w, tmp_path):
    mesh = trimesh.creation.box()
    mesh.update_faces(np.arange(len(mesh.faces)) != 0)
    path = tmp_path / "open.stl"
    mesh.export(path)
    act(w, "import", files=[str(path)])
    assert act(w, "inspect")["reports"][0]["boundary_edges"] == 3
    act(w, "repair", require_watertight=True)
    assert act(w, "inspect")["reports"][0]["watertight"]
    act(w, "primitive", kind="sphere")
    before = len(w.mesh(w.state()["objects"][-1]).faces)
    act(w, "simplify", ratio=0.5)
    result = w.mesh(w.state()["objects"][-1])
    assert result.is_watertight
    assert len(result.faces) <= before * 0.6


def test_rejects_animated_glb_without_losing_previous_state(w, tmp_path):
    act(w, "primitive")
    raw = trimesh.Scene(trimesh.creation.box()).export(file_type="gltf")
    data = json.loads(raw["model.gltf"])
    data["animations"] = [{"channels": []}]
    path = tmp_path / "animated.gltf"
    path.write_text(json.dumps(data))
    before = w.state()
    with pytest.raises(EditorError, match="骨架"):
        act(w, "import", files=[str(path)])
    assert w.state() == before


def test_rotated_dimensions_measure_mesh_and_print_copies_keep_names(w):
    act(w, "primitive", kind="sphere")
    act(w, "transform", rotate_deg=[23, 41, 17])
    obj = w.state()["objects"][0]
    assert obj["extents_mm"] == pytest.approx(w.mesh(obj, world=True).extents)
    assert max(obj["extents_mm"]) < 20.1
    act(w, "rename", name="球体检查件")
    exported = act(w, "print_copy")["files"][0]
    assert "球体检查件_" in exported
    assert trimesh.load_mesh(exported).extents == pytest.approx(obj["extents_mm"], abs=1e-5)


def test_multicolor_requires_explicit_consent_for_topology_changes(w, tmp_path):
    mesh = trimesh.creation.box()
    colors = np.tile([255, 0, 0, 255], (len(mesh.vertices), 1))
    colors[0] = [0, 0, 255, 255]
    mesh.visual.vertex_colors = colors
    path = tmp_path / "colors.ply"
    mesh.export(path)
    act(w, "import", files=[str(path)])
    before = w.path.read_bytes()
    with pytest.raises(EditorError, match="纯色"):
        act(w, "plane_cut")
    assert w.path.read_bytes() == before
    act(w, "plane_cut", allow_material_loss=True)
    assert len(w.state()["objects"]) == 2


def test_http_editor_auth_conflicts_and_human_ai_history(studio_env):
    client = studio_env["client"]
    body = {"action": "primitive", "expected_revision": 0}
    assert client.post("/api/edit", body, token=None)[0] == 403
    assert client.post("/api/edit", body, headers={"Origin": "https://untrusted.example"})[0] == 403
    assert client.post("/api/edit", body, headers={"X-Studio-Actor": "human"})[0] == 200
    assert client.post("/api/edit", body)[0] == 409
    _, state = client.get("/api/state")
    obj = state["workbench"]["objects"][0]
    assert client.get(obj["asset_url"], token=None)[0] == 403
    assert client.get(obj["asset_url"])[1][:4] == b"glTF"
    assert (
        client.post(
            "/api/edit", {"action": "transform", "expected_revision": 1, "params": {"translate_mm": [3, 0, 0]}}
        )[0]
        == 200
    )
    _, state = client.get("/api/state")
    assert [h["actor"] for h in state["workbench"]["history"]] == ["human", "ai"]
    assert not state["parts"]  # editing does not implicitly overwrite a print job
    assert not state["history"]  # editor history is not a printing operation


def test_extract_faces_preserves_original_triangles_and_material(w, tmp_path):
    mesh = trimesh.creation.icosphere(subdivisions=1, radius=10)
    mesh.visual = trimesh.visual.TextureVisuals(
        uv=np.zeros((len(mesh.vertices), 2)),
        material=trimesh.visual.material.PBRMaterial(baseColorFactor=[50, 100, 150, 255]),
    )
    source = tmp_path / "textured.glb"
    source.write_bytes(trimesh.Scene(mesh).export(file_type="glb"))
    act(w, "import", files=[str(source)])
    original = w.mesh(w.doc["objects"][0], world=True)
    result = act(w, "extract_faces", face_ids=list(range(20)))
    assert result["capped"] is False and result["faces_extracted"] == 20
    actual = [w.mesh(o, world=True) for o in w.doc["objects"]]
    assert sum(len(m.faces) for m in actual) == len(original.faces)
    assert all(m.visual.uv is not None for m in actual)
    points = np.concatenate([m.triangles.reshape(-1, 3) for m in actual])
    assert np.allclose(np.sort(points, axis=0), np.sort(original.triangles.reshape(-1, 3), axis=0))
    act(w, "undo")
    assert len(w.doc["objects"]) == 1
