import copy
import hashlib
import json
import zipfile
from pathlib import Path

import numpy as np
import pytest
from studio.core import city, collaboration as c
from studio.core.editor import Workspace, EditorError
from studio.core.workspaces import copy_assets
from tests.helpers import scene_call, session, source


def prepared(w, tmp_path):
    raw = source(tmp_path, rig=True).read_bytes()
    files = {"runtime.js": b"/* test runtime */", "public/models/person.glb": raw}
    manifest = {
        "schema": city.SCHEMA,
        "files": {k: {"sha256": hashlib.sha256(v).hexdigest(), "bytes": len(v)} for k, v in files.items()},
    }
    doc = json.dumps(manifest, sort_keys=True).encode()
    digest = hashlib.sha256(doc).hexdigest()
    p = w.root / "cities"
    p.mkdir(exist_ok=True)
    with zipfile.ZipFile(p / f"{digest}.zip", "w") as z:
        z.writestr("package.json", doc)
        for k, v in files.items():
            z.writestr(k, v)
    return digest, manifest


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("PRINT_PREP_HOME", str(tmp_path / "home"))
    w = Workspace(tmp_path / "workbench")
    digest, manifest = prepared(w, tmp_path)
    monkeypatch.setattr(city, "prepare", lambda *_: (digest, {**manifest, "source_sha256": "a" * 64}))
    scene_call(w, "city_import", {"path": "/source.zip"})
    row = {
        "id": "person_1",
        "name": "人物",
        "kind": "person",
        "url": "/models/person.glb",
        "matrix": [[1, 0, 0, 10], [0, 1, 0, 0], [0, 0, 1, 20], [0, 0, 0, 1]],
        "bones": {"RootBone": "Hips"},
        "source_clip": "Move",
    }
    scene_call(w, "city_register", {"instances": [row]})
    return w, row, digest


def test_city_lazy_checkout_and_unit_conversion(project):
    w, row, digest = project
    assert len(w.doc["objects"]) == 1
    r = scene_call(w, "city_catalog")
    assert r["total"] == 1 and r["items"] == [row]
    scene_call(w, "city_checkout", {"instance_id": row["id"]})
    assert len(w.doc["objects"]) == 2
    obj = w.doc["objects"][1]
    assert obj["city_link"]["root"] == w.doc["objects"][0]["id"]
    np.testing.assert_allclose(np.array(obj["transform"])[:3, 3], [10000, -20000, 0], atol=1e-6)
    scene_call(w, "city_checkout", {"instance_id": row["id"]})
    assert len(w.doc["objects"]) == 2
    assert w.doc["selection"] == [obj["id"]]


def test_city_resource_auth_hash_and_runtime_trust(project):
    w, row, digest = project
    assert city.resource(w, digest, "public/models/person.glb")[:4] == b"glTF"
    with pytest.raises(EditorError, match="不属于"):
        city.resource(w, "b" * 64, "runtime.js")
    with pytest.raises(EditorError, match="无效路径"):
        city.resource(w, digest, "../project.json")
    with pytest.raises(EditorError, match="尚未"):
        city.resource(w, digest, "runtime.js")
    with zipfile.ZipFile(city.package_path(w, digest)) as z:
        m = city.package_manifest(z, digest)
    from studio import print_prep_home

    p = print_prep_home() / "city-trust"
    p.mkdir(parents=True)
    (p / f"{digest}.json").write_text(json.dumps({"runtime_sha256": m["files"]["runtime.js"]["sha256"]}))
    assert city.resource(w, digest, "runtime.js").startswith(b"/*")


def test_city_root_and_link_protection(project, tmp_path):
    w, row, digest = project
    for action in ["delete", "duplicate", "transform"]:
        with pytest.raises(EditorError, match="根节点"):
            scene_call(w, action)
    scene_call(w, "city_checkout", {"instance_id": row["id"]})
    old = copy.deepcopy(w.doc)
    with pytest.raises(EditorError, match="骨骼"):
        scene_call(w, "scene_replace", {"path": str(source(tmp_path))})
    assert w.doc == old
    scene_call(w, "scene_replace", {"path": str(source(tmp_path, rig=True))})
    assert w.doc["objects"][1]["city_link"] == old["objects"][1]["city_link"]
    with pytest.raises(EditorError, match="完整城市"):
        scene_call(w, "export")
    duplicate = copy.deepcopy(w.doc["objects"][1])
    duplicate["id"] = "a" * 32
    with pytest.raises(EditorError, match="两个编辑分支"):
        city.validate(w, w.doc["objects"] + [duplicate])


def test_city_runtime_trust_survives_task_home_change(project, tmp_path, monkeypatch):
    w, _, digest = project
    machine = tmp_path / "machine"
    monkeypatch.setenv("PRINT_PREP_WORKSPACES_HOME", str(machine))
    monkeypatch.setenv("PRINT_PREP_HOME", str(machine / "workspaces" / "task-a"))
    trust = city.trust_directory()
    trust.mkdir(parents=True)
    with zipfile.ZipFile(city.package_path(w, digest)) as z:
        m = city.package_manifest(z, digest)
    (trust / f"{digest}.json").write_text(json.dumps({"runtime_sha256": m["files"]["runtime.js"]["sha256"]}))
    assert city.resource(w, digest, "runtime.js").startswith(b"/*")
    monkeypatch.setenv("PRINT_PREP_HOME", str(machine / "workspaces" / "task-b"))
    assert city.resource(w, digest, "runtime.js").startswith(b"/*")
    with pytest.raises(EditorError, match="不属于"):
        city.resource(Workspace(tmp_path / "empty"), digest, "runtime.js")
    monkeypatch.setenv("PRINT_PREP_WORKSPACES_HOME", str(tmp_path / "different-machine"))
    with pytest.raises(EditorError, match="尚未"):
        city.resource(w, digest, "runtime.js")


def test_city_roundtrip_and_branch_assets(project, tmp_path):
    w, row, digest = project
    scene_call(w, "city_checkout", {"instance_id": row["id"]})
    scene_call(w, "transform", {"translate_mm": [100, 200, 0]})
    archive = scene_call(w, "save")["path"]
    fresh = Workspace(tmp_path / "fresh")
    scene_call(fresh, "open", {"path": archive})
    assert fresh.doc["objects"] == w.doc["objects"]
    assert city.catalog(fresh, fresh.doc["objects"][0]) == [row]
    target = tmp_path / "branch/assets"
    copy_assets(w.doc["objects"], w.root / "assets", target)
    assert (target.parent / "cities" / f"{digest}.zip").read_bytes() == city.package_path(w, digest).read_bytes()


def test_frozen_catalog_rejects_drift(project):
    w, row, digest = project
    changed = copy.deepcopy(row)
    changed["matrix"][0][3] += 2
    with pytest.raises(EditorError, match="冻结版本"):
        scene_call(w, "city_register", {"instances": [changed]})
    assert scene_call(w, "city_catalog")["items"] == [row]


def test_city_child_scope_and_undo(project, tmp_path):
    w, row, digest = project
    scene_call(w, "city_checkout", {"instance_id": row["id"]})
    obj = w.doc["objects"][1]
    with session("owner"):
        invite = c.control(
            w, dict(action="invite", object_id=obj["id"], worktree=str(tmp_path), expected_revision=w.doc["revision"])
        )
    with session("child"):
        c.control(w, dict(action="join", invitation=invite["invitation"], worktree=str(tmp_path)))
        with pytest.raises(EditorError, match="整体导入"):
            scene_call(w, "city_checkout", {"instance_id": "person_2"})
        scene_call(w, "transform", {"translate_mm": [100, 0, 0]})
        scene_call(w, "undo")
        assert next(o for o in w.doc["objects"] if o["id"] == obj["id"])["transform"] == obj["transform"]


def test_city_archive_rejects_corrupt_resource_without_replacing_package(project, tmp_path):
    w, row, digest = project
    archive = Path(scene_call(w, "save")["path"])
    bad = tmp_path / "bad.3dworkbench"
    import io

    original = city.package_path(w, digest).read_bytes()
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(original)) as src, zipfile.ZipFile(out, "w") as z:
        for name in src.namelist():
            z.writestr(name, b"corrupt" if name == "runtime.js" else src.read(name))
    with zipfile.ZipFile(archive) as src, zipfile.ZipFile(bad, "w") as z:
        for name in src.namelist():
            z.writestr(name, out.getvalue() if name.endswith(digest + ".zip") else src.read(name))
    before = copy.deepcopy(w.doc)
    with pytest.raises(EditorError, match="校验失败"):
        scene_call(w, "open", {"path": str(bad)})
    assert w.doc == before and city.package_path(w, digest).read_bytes() == original


def test_city_worktree_merge_keeps_instance_binding(project, tmp_path):
    from studio.core import branches

    w, row, digest = project
    scene_call(w, "city_checkout", {"instance_id": row["id"]})
    base = copy.deepcopy(w.doc["objects"])
    branch = Workspace(tmp_path / "fork")
    scene_call(branch, "open", {"path": scene_call(w, "save")["path"]})
    scene_call(branch, "transform", {"translate_mm": [700, 0, 0]})
    result = branches.merge(
        w,
        dict(
            expected_revision=w.doc["revision"],
            base_objects=base,
            objects=branch.doc["objects"],
            asset_root=str(branch.root / "assets"),
            branch_id="city-fork",
        ),
        "ai",
    )
    assert result["merged_ids"] == [base[1]["id"]]
    assert w.doc["objects"][1]["city_link"] == base[1]["city_link"]
    np.testing.assert_allclose(np.array(w.doc["objects"][1]["transform"])[:3, 3], [10700, -20000, 0], atol=1e-6)


@pytest.mark.anyio
async def test_city_mcp_resource_is_workspace_scoped(project, tmp_path, monkeypatch):
    from studio.shell import mcp_server
    from mcp import types
    import base64

    w, row, digest = project
    monkeypatch.setattr(
        mcp_server,
        "_ensure_running",
        lambda key: ({"job": str(w.root.parent) if key == "city-test" else str(tmp_path / "other")}, False),
    )
    uri = f"print-prep://city/{digest}/public%2Fmodels%2Fperson.glb?workspace=city-test"
    result = await mcp_server.on_read_resource(None, types.ReadResourceRequestParams(uri=uri))
    assert base64.b64decode(result.contents[0].blob) == city.resource(w, digest, "public/models/person.glb")
    with pytest.raises(EditorError, match="不属于"):
        await mcp_server.on_read_resource(
            None, types.ReadResourceRequestParams(uri=uri.replace("city-test", "other-test"))
        )
