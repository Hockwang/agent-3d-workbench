import zipfile
from contextlib import contextmanager
from pathlib import Path
import pytest
from studio.core.editor import Workspace, EditorError, _glb_document
from studio.core.motion import worker
from studio.core import collaboration as c


def motion(parent=None):
    return dict(
        schema="studio-motion/v1",
        kind="joint",
        duration=2,
        fps=24,
        mode="pkf",
        joint=dict(type="revolute", axis="z", origin=[0, 0, 0], parent=parent, limits=[-180, 180]),
        parameters=[dict(id="angle", default=90)],
        steps=[dict(id="s", t_start=0, t_end=2, value_start="0", value_end="angle", easing="linear")],
        keyframes=[],
    )


def call(w, a, p=None, **kw):
    return w.execute(dict(action=a, params=p or {}, expected_revision=w.doc["revision"], **kw))


@pytest.fixture
def ws(tmp_path):
    w = Workspace(tmp_path / "w")
    call(w, "primitive", {"size": [100, 20, 20]})
    return w


def test_package_reopens_in_clean_workspace_with_parameter_identity(ws, tmp_path):
    call(ws, "motion_set", {"motion": motion()})
    packet = call(ws, "motion_export", {"format": "zip"})["path"]
    fresh = Workspace(tmp_path / "fresh")
    call(fresh, "motion_import", {"path": packet})
    a, b = ws.doc["objects"][0], fresh.doc["objects"][0]
    assert a["id"] != b["id"] and a["asset"] == b["asset"]
    assert a["motion"]["steps"] == b["motion"]["steps"]
    saved = call(fresh, "save")["path"]
    call(fresh, "motion_clear")
    call(fresh, "open", {"path": saved})
    assert fresh.doc["objects"][0]["motion"] == b["motion"]


def test_native_v7_core_imports_without_studio_extension(ws, tmp_path):
    call(ws, "motion_set", {"motion": motion()})
    packet = call(ws, "motion_export", {"format": "zip"})["path"]
    native = tmp_path / "native.zip"
    with zipfile.ZipFile(packet) as source, zipfile.ZipFile(native, "w") as target:
        for name in source.namelist():
            if not name.startswith(("studio-", "assets/", "sources/")):
                target.writestr(name, source.read(name))
    fresh = Workspace(tmp_path / "fresh")
    call(fresh, "motion_import", {"path": str(native)})
    obj = fresh.doc["objects"][0]
    assert obj["motion"]["steps"][0]["value_end"].endswith("_angle")
    assert obj["motion"]["fps"] == 24
    assert obj["motion"]["joint"]["axis"] == "z"
    call(fresh, "motion_export", {"format": "glb"})


def test_baked_glb_contains_sampled_animation_and_geometry(ws):
    call(ws, "motion_set", {"motion": motion()})
    r = call(ws, "motion_export", {"format": "glb"})
    d = _glb_document(Path(r["path"]).read_bytes())
    assert d["animations"] and d["meshes"]
    assert r["motion_report"]["frames"] == 49
    assert all(d["accessors"][s["input"]]["max"] == [2] for s in d["animations"][0]["samplers"])


def test_formula_failure_and_geometry_binding_do_not_corrupt_project(ws):
    m = motion()
    m["steps"][0]["value_end"] = "globalThis.process.exit()"
    before = ws.path.read_bytes()
    with pytest.raises(EditorError):
        call(ws, "motion_set", {"motion": m})
    assert ws.path.read_bytes() == before
    call(ws, "motion_set", {"motion": motion()})
    before = ws.path.read_bytes()
    with pytest.raises(EditorError, match="绑定"):
        call(ws, "simplify", {"ratio": 0.5})
    assert ws.path.read_bytes() == before
    call(ws, "transform", {"translate_mm": [10, 0, 0]})
    with pytest.raises(EditorError, match="零位"):
        call(ws, "motion_export", {"format": "glb"})


@contextmanager
def session(key):
    token = c.SESSION.set(key)
    try:
        yield
    finally:
        c.SESSION.reset(token)


def test_joint_dependency_scope_and_object_undo(ws, tmp_path):
    a = ws.doc["objects"][0]["id"]
    call(ws, "primitive")
    b = ws.doc["objects"][1]["id"]
    with session("owner"):
        invite = c.control(ws, {"action": "invite", "object_id": a, "worktree": str(tmp_path), "expected_revision": 2})
    with session("child"):
        c.control(ws, {"action": "join", "invitation": invite["invitation"], "worktree": str(tmp_path)})
        before = ws.path.read_bytes()
        with pytest.raises(EditorError, match="父子机构"):
            call(ws, "motion_set", {"ids": [a], "motion": motion(b)})
        assert ws.path.read_bytes() == before
        call(ws, "motion_set", {"ids": [a], "motion": motion()})
    with session("owner"):
        call(ws, "rename", {"ids": [b], "name": "other"})
    with session("child"):
        call(ws, "undo")
    assert (
        "motion" not in ws.doc["objects"][0] or next(o for o in ws.doc["objects"] if o["id"] == a).get("motion") is None
    )
    assert next(o for o in ws.doc["objects"] if o["id"] == b)["name"] == "other"


def test_motionforge_parent_chain_roundtrip(ws, tmp_path):
    parent = ws.doc["objects"][0]["id"]
    call(ws, "motion_set", {"motion": motion()})
    call(ws, "primitive")
    call(ws, "transform", {"translate_mm": [200, 0, 0]})
    fixed = motion(parent)
    fixed["joint"]["type"] = "fixed"
    fixed["steps"] = []
    call(ws, "motion_set", {"motion": fixed})
    packet = call(ws, "motion_export", {"format": "zip"})["path"]
    fresh = Workspace(tmp_path / "fresh")
    call(fresh, "motion_import", {"path": packet})
    objects = fresh.doc["objects"]
    assert objects[1]["motion"]["joint"]["parent"] == objects[0]["id"]
    worker(objects)


def test_joint_cannot_inject_unregistered_asset_references(ws):
    m = motion()
    m["asset"] = "../outside"
    before = ws.path.read_bytes()
    with pytest.raises(EditorError, match="独立骨架"):
        call(ws, "motion_set", {"motion": m})
    assert ws.path.read_bytes() == before
    m.pop("asset")
    m["blend_asset"] = "../outside"
    with pytest.raises(EditorError, match="源资产"):
        call(ws, "motion_set", {"motion": m})
    assert ws.path.read_bytes() == before
