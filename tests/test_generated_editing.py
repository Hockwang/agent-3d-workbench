import json

import numpy as np
import pytest
import trimesh
from PIL import Image

from studio.core.editor import Workspace, EditorError
from studio.core.generated_editing import generated_container, local_dimensions
from studio.core.materials import edit, describe
from studio.core.tasks import Tasks
from tests.helpers import act, container_input, wait


def test_material_and_export_preserve_authored_normals(tmp_path):
    # UV seams can disconnect vertices that intentionally share smooth normals.
    # Recomputing from this topology would turn the surface into flat triangles.
    sphere = trimesh.creation.icosphere(subdivisions=1)
    vertices = sphere.triangles.reshape(-1, 3)
    mesh = trimesh.Trimesh(
        vertices,
        np.arange(len(vertices)).reshape(-1, 3),
        vertex_normals=vertices / np.linalg.norm(vertices, axis=1)[:, None],
        process=False,
    )
    mesh.visual = trimesh.visual.TextureVisuals(
        uv=np.zeros((len(vertices), 2)),
        material=trimesh.visual.material.PBRMaterial(baseColorFactor=[90, 150, 220, 255]),
    )
    source = tmp_path / "smooth-seams.glb"
    mesh.export(source)
    original = next(iter(trimesh.load_scene(source, process=False).geometry.values()))
    w = Workspace(tmp_path / "normals")
    act(w, "import", files=[str(source)])
    act(w, "material", roughness=0.28, metallic=0.35)
    exported = act(w, "export", format="glb")["path"]
    result = next(iter(trimesh.load_scene(exported, process=False).geometry.values()))
    assert "vertex_normals" in result._cache
    np.testing.assert_allclose(result.vertex_normals, original.vertex_normals, atol=1e-6)
    np.testing.assert_allclose(result.vertices, original.vertices, atol=1e-6)
    np.testing.assert_array_equal(result.faces, original.faces)


def test_exact_geometry_restore_preserves_authored_normals(tmp_path):
    from studio.core.geometry_store import encode, restore

    mesh = trimesh.creation.icosphere(subdivisions=1)
    mesh.vertices = np.asarray(mesh.vertices) + [0.000000012345, 0, 0]
    normals = np.tile([0.0, 0.0, 1.0], (len(mesh.vertices), 1))
    mesh.vertex_normals = normals
    raw = encode(mesh)
    path = tmp_path / "exact-normals.glb"
    path.write_bytes(raw)
    decoded = next(iter(trimesh.load_scene(path, process=False).geometry.values()))
    restored = restore(raw, decoded)
    np.testing.assert_array_equal(restored.vertices, mesh.vertices)
    np.testing.assert_array_equal(restored.vertex_normals, normals)


def textured_mesh():
    m = trimesh.creation.box([20, 30, 40])
    m.visual = trimesh.visual.TextureVisuals(
        uv=np.arange(16).reshape(8, 2) / 16,
        material=trimesh.visual.material.PBRMaterial(
            name="耳垫",
            baseColorFactor=[30, 60, 90, 128],
            baseColorTexture=Image.new("RGB", (4, 4), "red"),
            roughnessFactor=0.2,
            metallicFactor=0.7,
            normalTexture=Image.new("RGB", (4, 4), (128, 128, 255)),
            alphaMode="BLEND",
        ),
    )
    return m


def test_material_slot_preserves_other_slots_alpha_uv_and_normal():
    m = textured_mesh()
    first = m.visual.material
    second = first.copy()
    second.name = "外壳"
    m.visual.material = trimesh.visual.material.MultiMaterial([first, second])
    m.visual.face_materials = np.array([0] * 6 + [1] * 6)
    uv = m.visual.uv.copy()
    vertices = m.vertices.copy()
    result = edit(m.copy(), {"material_slots": [1], "color": "#ffffff", "roughness": 0.8})
    info = describe(result)
    assert info[0]["color"] == "#1e3c5a" and info[1]["color"] == "#ffffff"
    assert info[1]["alpha"] == pytest.approx(128 / 255)
    assert info[1]["metallic"] == 0.7 and info[1]["roughness"] == 0.8
    assert first.baseColorFactor.tolist() == [30, 60, 90, 128]
    np.testing.assert_array_equal(result.visual.uv, uv)
    np.testing.assert_array_equal(result.vertices, vertices)
    np.testing.assert_array_equal(result.visual.material.materials[1].normalTexture, first.normalTexture)


def test_texture_edit_archive_undo_and_invalid_slot(tmp_path):
    source = tmp_path / "source.glb"
    trimesh.Scene(textured_mesh()).export(source)
    w = Workspace(tmp_path / "workspace")
    act(w, "import", files=[str(source)])
    original = w.state()["objects"][0]
    assert original["materials"][0]["name"] == "耳垫"
    image = tmp_path / "blue.png"
    Image.new("RGB", (4, 4), "blue").save(image)
    act(w, "material", material_slots=[0], base_color_texture=str(image), color="#ffffff")
    new = w.state()["objects"][0]
    assert new["asset"] != original["asset"]
    assert w.mesh(new).visual.material.baseColorTexture.getpixel((0, 0))[:3] == (0, 0, 255)
    unchanged = w.path.read_bytes()
    with pytest.raises(EditorError):
        act(w, "material", material_slots=[4], metallic=0)
    assert w.path.read_bytes() == unchanged
    saved = act(w, "save")["path"]
    other = Workspace(tmp_path / "other")
    act(other, "open", path=saved)
    assert other.state()["objects"][0]["materials"][0]["alpha"] == pytest.approx(128 / 255)
    act(w, "undo")
    assert w.state()["objects"][0]["asset"] == original["asset"]
    act(w, "redo")
    assert w.state()["objects"][0]["asset"] == new["asset"]
    act(w, "material", material_slots=[0], base_color_texture=None)
    assert not w.state()["objects"][0]["materials"][0]["base_color_texture"]


def test_generated_container_validates_package_clearance_and_original(tmp_path):
    path = container_input(tmp_path)
    original = path.read_bytes()
    out = tmp_path / "output"
    out.mkdir()
    generated_container({"inputs": [str(path)], "params": {}, "output": str(out)})
    report = json.loads((out / "report.json").read_text())
    assert report["cut_z_mm"] == 47 and max(report["checks"].values()) < 1e-5
    assert path.read_bytes() == original
    for part in ("body", "lid"):
        mesh = trimesh.load_mesh(out / (part + ".stl"), process=True)
        assert mesh.is_volume and len(mesh.split()) == 1
    assert len(trimesh.load_scene(out / "scene.glb").geometry) == 2
    with pytest.raises(ValueError, match="放不进"):
        generated_container({"inputs": [str(path)], "params": {"inner_width_mm": 120}, "output": str(out)})


def test_parametric_rebuild_uses_frozen_input_and_keeps_old_result(tmp_path):
    path = container_input(tmp_path)
    tasks = Tasks(tmp_path / "tasks")
    task = tasks.start({"template": "generated-container", "inputs": [str(path)], "params": {}}, "human")["task"]
    first = wait(tasks, task["id"])
    assert first["status"] == "completed", first
    frozen = first["editable"]["inputs"][0]
    assert frozen != str(path)
    saved = {x["name"]: x["sha256"] for x in first["artifacts"]}
    path.write_bytes(b"Changed outside the task")
    second = tasks.rebuild({"id": task["id"], "params": {"inner_width_mm": 64, "clearance_mm": 0.5}}, "ai")["task"]
    second = wait(tasks, second["id"])
    assert second["status"] == "completed", second
    assert second["source_task"] == first["id"] and second["actor"] == "ai"
    assert second["editable"]["params"]["inner_width_mm"] == 64
    assert {x["name"]: x["sha256"] for x in tasks.state(first["id"])["artifacts"]} == saved
    bad = tasks.rebuild({"id": second["id"], "params": {"inner_width_mm": 200}}, "human")["task"]
    assert wait(tasks, bad["id"])["status"] == "failed"
    assert tasks.state(second["id"])["status"] == "completed"
    from pathlib import Path

    Path(frozen).write_bytes(b"tampered")
    with pytest.raises(EditorError, match="已改变"):
        tasks.rebuild({"id": first["id"]}, "ai")


def test_local_dimensions_preserves_uv_and_moves_only_specified_axis(tmp_path):
    from studio.core.task_operations import deliver
    from studio.core.generated_editing import source

    # Four rings let the middle stretch while both ends retain their shape.
    vertices = [[x, y, z] for z in (0, 10, 30, 40) for x, y in ((-10, -10), (10, -10), (10, 10), (-10, 10))]
    faces = [[0, 2, 1], [0, 3, 2], [12, 13, 14], [12, 14, 15]]
    for ring in range(3):
        for i in range(4):
            a, b = ring * 4 + i, ring * 4 + (i + 1) % 4
            faces.extend([[a, b, b + 4], [a, b + 4, a + 4]])
    m = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
    m.visual = trimesh.visual.TextureVisuals(
        uv=np.arange(32).reshape(16, 2) / 32, material=textured_mesh().visual.material
    )
    src = tmp_path / "input"
    src.mkdir()
    deliver({"model": m}, src, {}, stl=False)
    path = src / "scene.glb"
    out = tmp_path / "output"
    out.mkdir()
    before, _ = source({"inputs": [str(path)]})
    local_dimensions(
        {"inputs": [str(path)], "params": {"start_mm": 10, "end_mm": 30, "delta_mm": 10}, "output": str(out)}
    )
    after, _ = source({"inputs": [str(out / "scene.glb")]})
    report = json.loads((out / "report.json").read_text())
    assert report["topology_preserved"] and report["after_extents_mm"][2] == pytest.approx(50)
    np.testing.assert_allclose(before.vertices[:, :2], after.vertices[:, :2], atol=1e-5)
    fixed = before.vertices[:, 2] <= 10 + 1e-5
    np.testing.assert_allclose(before.vertices[fixed], after.vertices[fixed], atol=1e-5)
    moved = before.vertices[:, 2] >= 30 - 1e-5
    np.testing.assert_allclose(
        after.vertices[moved] - before.vertices[moved], [0, 0, 10] + np.zeros((moved.sum(), 3)), atol=1e-5
    )
    np.testing.assert_array_equal(before.faces, after.faces)
    np.testing.assert_array_equal(before.visual.uv, after.visual.uv)
    np.testing.assert_array_equal(before.visual.material.baseColorTexture, after.visual.material.baseColorTexture)
    np.testing.assert_array_equal(before.visual.material.normalTexture, after.visual.material.normalTexture)
    with pytest.raises(ValueError, match="折叠"):
        local_dimensions(
            {"inputs": [str(path)], "params": {"start_mm": 0, "end_mm": 40, "delta_mm": -50}, "output": str(out)}
        )
    with pytest.raises(ValueError, match="穿过"):
        local_dimensions(
            {"inputs": [str(path)], "params": {"start_mm": 5, "end_mm": 30, "delta_mm": 10}, "output": str(out)}
        )
