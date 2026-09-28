import copy
from pathlib import Path

import numpy as np
import pytest

from studio.core.editor import Workspace, EditorError
from studio.core import collaboration as c
from studio.core.scene_assets import unpack, pack
from tests.helpers import scene_call, session, source


def test_scene_preserves_rig_and_local_placement_when_replaced(tmp_path):
    path = source(tmp_path, rig=True)
    w = Workspace(tmp_path / "w")
    scene_call(w, "scene_import", {"files": [str(path)]})
    a = copy.deepcopy(w.doc["objects"][0])
    scene_call(w, "duplicate")
    b = w.doc["selection"][0]
    scene_call(w, "transform", {"ids": [a["id"]], "translate_mm": [2800, 150, 0], "rotate_deg": [0, 0, 45]})
    placement = copy.deepcopy(w.doc["objects"][0]["transform"])
    before_sibling = copy.deepcopy(next(o for o in w.doc["objects"] if o["id"] == b))
    scene_call(w, "scene_replace", {"ids": [a["id"]], "path": str(path)})
    replaced = next(o for o in w.doc["objects"] if o["id"] == a["id"])
    assert replaced["transform"] == placement and replaced["name"] == a["name"]
    assert next(o for o in w.doc["objects"] if o["id"] == b) == before_sibling
    raw = w.asset_bytes(replaced["scene"]["asset"])
    assert raw == path.read_bytes()
    assert replaced["motion"]["kind"] == "skin"
    out = scene_call(w, "scene_export", {"ids": [a["id"]]})
    assert Path(out["path"]).read_bytes() == raw
    saved = scene_call(w, "save")["path"]
    fresh = Workspace(tmp_path / "fresh")
    scene_call(fresh, "open", {"path": saved})
    assert fresh.doc["objects"] == w.doc["objects"]
    assert fresh.state()["objects"][0]["bounds_mm"] == w.state()["objects"][0]["bounds_mm"]


def test_material_forks_one_instance_without_altering_skin_or_buffers(tmp_path):
    path = source(tmp_path, rig=True)
    w = Workspace(tmp_path / "w")
    scene_call(w, "scene_import", {"files": [str(path)]})
    scene_call(w, "duplicate")
    a, b = w.doc["objects"]
    before = copy.deepcopy(a)
    scene_call(w, "material", {"ids": [b["id"]], "color": "#3366ff", "roughness": 0.25})
    a, b = w.doc["objects"]
    assert a == before and a["scene"]["asset"] != b["scene"]["asset"]
    original, bin0 = unpack(w.asset_bytes(a["scene"]["asset"]))
    edited, bin1 = unpack(w.asset_bytes(b["scene"]["asset"]))
    assert bin0 == bin1 and original["skins"] == edited["skins"] and original["animations"] == edited["animations"]
    assert a["scene"]["family"] == b["scene"]["family"]
    assert edited["materials"][0]["pbrMetallicRoughness"]["baseColorFactor"] == [0.2, 0.4, 1.0, 1.0]
    assert b["motion"]["asset"] == b["scene"]["asset"] and b["motion"]["bound_asset"] == b["asset"]
    scene_call(w, "undo")
    assert w.doc["objects"][1]["scene"]["asset"] == a["scene"]["asset"]


@pytest.mark.parametrize("damage", ["truncated", "weights", "cycle", "external"])
def test_bad_candidate_keeps_current_document(tmp_path, damage):
    path = source(tmp_path, rig=True)
    w = Workspace(tmp_path / "w")
    scene_call(w, "scene_import", {"files": [str(path)]})
    before = w.path.read_bytes()
    doc, binary = unpack(path.read_bytes())
    if damage == "truncated":
        raw = path.read_bytes()[:-12]
    else:
        if damage == "cycle":
            doc["nodes"][0]["children"] = [0]
        if damage == "external":
            doc["images"] = [{"uri": "https://example.invalid/texture.png"}]
        if damage == "weights":
            a = doc["accessors"][doc["meshes"][0]["primitives"][0]["attributes"]["WEIGHTS_0"]]
            view = doc["bufferViews"][a["bufferView"]]
            offset = view["byteOffset"]
            b = bytearray(binary)
            b[offset : offset + 4] = np.array([float("nan")], dtype="<f4").tobytes()
            binary = bytes(b)
        raw = pack(doc, binary)
    candidate = tmp_path / "candidate.glb"
    candidate.write_bytes(raw)
    with pytest.raises(EditorError):
        scene_call(w, "scene_replace", {"path": str(candidate)})
    assert w.path.read_bytes() == before


def test_rigid_animation_and_static_scene_roundtrip(tmp_path):
    w = Workspace(tmp_path / "w")
    a = source(tmp_path, animated=True)
    b = source(tmp_path)
    scene_call(w, "scene_import", {"files": [str(a), str(b)]})
    assert w.doc["objects"][0]["motion"]["kind"] == "gltf"
    assert "motion" not in w.doc["objects"][1]
    packet = scene_call(w, "motion_export", {"format": "zip"})["path"]
    fresh = Workspace(tmp_path / "fresh")
    scene_call(fresh, "motion_import", {"path": packet})
    assert [o["scene"] for o in fresh.doc["objects"]] == [o["scene"] for o in w.doc["objects"]]
    baked = scene_call(w, "motion_export", {"ids": [w.doc["objects"][0]["id"]], "format": "glb"})["path"]
    assert unpack(Path(baked).read_bytes())[0]["animations"]


def test_part_chat_can_replace_only_own_instance_and_undo_preserves_other(tmp_path):
    path = source(tmp_path, rig=True)
    w = Workspace(tmp_path / "w")
    scene_call(w, "scene_import", {"files": [str(path), str(path)]})
    a, b = [o["id"] for o in w.doc["objects"]]
    with session("owner"):
        invite = c.control(
            w, dict(action="invite", object_id=a, worktree=str(tmp_path), expected_revision=w.doc["revision"])
        )
    with session("child"):
        c.control(w, dict(action="join", invitation=invite["invitation"], worktree=str(tmp_path)))
        scene_call(w, "material", {"ids": [a], "color": "#ff4422"})
        with pytest.raises(EditorError, match="绑定零件"):
            scene_call(w, "scene_replace", {"ids": [b], "path": str(path)})
        with pytest.raises(EditorError, match="整体导入"):
            scene_call(w, "scene_import", {"files": [str(path)]})
        scene_call(w, "scene_replace", {"ids": [a], "path": str(path)})
        version = next(o["version"] for o in w.state()["objects"] if o["id"] == a)
    with session("owner"):
        scene_call(w, "rename", {"ids": [b], "name": "另一任务的修改"})
        with pytest.raises(EditorError, match="正由任务"):
            scene_call(w, "scene_replace", {"ids": [a], "path": str(path)})
    with session("child"):
        with pytest.raises(EditorError, match="已改变"):
            scene_call(w, "scene_replace", {"ids": [a], "path": str(path)}, expected_versions={a: version - 1})
        scene_call(w, "undo")
        assert next(o for o in w.state()["objects"] if o["id"] == b)["name"] == "另一任务的修改"
        assert (
            next(o for o in w.doc["objects"] if o["id"] == a)["scene"]["asset"]
            != next(o for o in w.doc["objects"] if o["id"] == b)["scene"]["asset"]
        )


def test_static_editor_cannot_flatten_scene_and_clear_does_not_lose_raw_asset(tmp_path):
    path = source(tmp_path, rig=True)
    w = Workspace(tmp_path / "w")
    scene_call(w, "scene_import", {"files": [str(path)]})
    scene_call(w, "motion_clear")
    with pytest.raises(EditorError, match="绑定"):
        scene_call(w, "simplify", {"ratio": 0.5})
    packet = scene_call(w, "save")["path"]
    fresh = Workspace(tmp_path / "fresh")
    scene_call(fresh, "open", {"path": packet})
    assert fresh.asset_bytes(fresh.doc["objects"][0]["scene"]["asset"]) == path.read_bytes()


def test_static_local_edit_source_roundtrip_does_not_double_placement(tmp_path):
    w = Workspace(tmp_path / "w")
    scene_call(w, "primitive", {"size": [400, 300, 1800]})
    scene_call(w, "transform", {"translate_mm": [3000, 150, 20], "rotate_deg": [0, 0, 40]})
    before = w.state()["objects"][0]
    out = scene_call(w, "scene_export")
    scene_call(w, "scene_replace", {"path": out["path"]})
    after = w.state()["objects"][0]
    np.testing.assert_allclose(before["bounds_mm"], after["bounds_mm"], atol=0.0002)
    assert before["transform"] == after["transform"]
