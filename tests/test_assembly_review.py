import base64
import hashlib
import json
import re
from pathlib import Path

import numpy as np
import pytest
import trimesh

from studio.core.assembly_review import run


def glb(path, offset=0):
    mesh = trimesh.creation.box(extents=[0.1, 0.2, 0.3])
    mesh.visual = trimesh.visual.TextureVisuals(
        uv=np.zeros((len(mesh.vertices), 2)),
        material=trimesh.visual.material.PBRMaterial(baseColorFactor=[90, 140, 210, 255]),
    )
    scene = trimesh.Scene()
    transform = np.eye(4)
    transform[0, 3] = offset
    scene.add_geometry(mesh, node_name="mesh", transform=transform)
    path.write_bytes(scene.export(file_type="glb"))
    return scene


def work(tmp_path, paths, params=None):
    out = tmp_path / "out"
    out.mkdir(exist_ok=True)
    return {"inputs": [str(p) for p in paths], "output": str(out), "params": params or {}}


def merge(tmp_path):
    root = tmp_path / "merge"
    root.mkdir()
    glb(root / "a.glb")
    glb(root / "b.glb", 0.2)
    (root / "manifest.json").write_text(json.dumps([{"file": "a.glb"}, {"file": "b.glb"}]))
    return root / "manifest.json"


def a8(tmp_path, joints=None):
    data = tmp_path / "data"
    data.mkdir()
    parts = tmp_path / "parts" / "cabinet"
    parts.mkdir(parents=True)
    glb(parts / "body.glb")
    glb(parts / "door.glb")
    cases = [
        {
            "id": "cabinet",
            "status": "blocked",
            "blocker": "sampled collision",
            "sourceArticulation": {
                "rootLink": "body",
                "links": [{"name": "body", "file": "body.glb"}, {"name": "door", "file": "door.glb"}],
                "joints": joints
                if joints is not None
                else [
                    {
                        "name": "hinge",
                        "parent": "body",
                        "child": "door",
                        "motionType": "revolute",
                        "axis": [0, 1, 0],
                        "origin": [0.1, 0, 0],
                        "poseRange": [0, 1.2],
                    }
                ],
            },
        }
    ]
    path = data / "cases.json"
    path.write_text(json.dumps(cases))
    return path, parts.parent


def payload(out):
    html = (out / "index.html").read_text()
    return json.loads(re.search(r'id="assembly-data">(.*?)</script>', html, re.S)[1])


def test_merge_preserves_faces_materials_transforms_and_safe_embed(tmp_path):
    source = merge(tmp_path)
    w = work(tmp_path, [source], {"title": "</script><script>unsafe</script>", "units": "m"})
    before = {p: p.read_bytes() for p in source.parent.iterdir()}
    run("merge-review", w)
    out = Path(w["output"])
    doc = payload(out)
    assert "</script><script>unsafe" not in (out / "index.html").read_text()
    meshes = trimesh.load(out / "parts.glb", force="scene", process=False)
    assert set(meshes.graph.nodes_geometry) == {"a", "b"}
    assert sum(len(m.faces) for m in meshes.geometry.values()) == 24
    assert np.allclose(meshes.bounds, [[-0.05, -0.1, -0.15], [0.25, 0.1, 0.15]])
    assert all(m.visual.uv is not None for m in meshes.geometry.values())
    for asset, record in doc["assets"].items():
        raw = base64.b64decode(record["data"])
        assert hashlib.sha256(raw).hexdigest() in asset
    assert all(p.read_bytes() == content for p, content in before.items())
    fingerprint = doc["resources"]["scenes/0.json"]["contentSha256"]
    glb(source.parent / "b.glb", 0.25)
    run("merge-review", w)
    assert payload(out)["resources"]["scenes/0.json"]["contentSha256"] != fingerprint


def test_explicit_merge_mm_conversion_and_compare(tmp_path):
    source = merge(tmp_path)
    w = work(tmp_path, [source, source], {"units": "mm"})
    run("merge-review", w)
    out = Path(w["output"])
    result = trimesh.load(out / "parts.glb", force="scene", process=False)
    assert np.allclose(result.bounds, np.array([[-0.05, -0.1, -0.15], [0.25, 0.1, 0.15]]) * 0.001)
    doc = payload(out)
    assert doc["resources"]["scenes/0.json"]["compare"]["sceneUrl"] == "compare.json"


def test_a8_preserves_motion_audit_and_leaves_registry_readonly(tmp_path):
    source, parts = a8(tmp_path)
    registry = tmp_path / "catalog_registry.json"
    registry.write_text(
        json.dumps(
            {
                "schema": "a8_catalog_registry/v1",
                "defaultBatchId": "test",
                "batches": {"test": {"dataDir": str(source.parent), "partsDir": str(parts)}},
            }
        )
    )
    original = registry.read_bytes()
    w = work(tmp_path, [registry], {"case_ids": "cabinet"})
    run("a8-review", w)
    doc = payload(Path(w["output"]))
    scene = doc["resources"]["scenes/0.json"]
    assert scene["joints"][0]["poseRange"] == [0, 1.2]
    assert scene["joints"][0]["origin"] == [0.1, 0, 0]
    assert scene["provenance"]["audit"]["status"] == "blocked"
    assert doc["resources"]["api/index.json"]["catalog"]["writable"] is False
    assert not (Path(w["output"]) / "parts.glb").exists()
    assert registry.read_bytes() == original


@pytest.mark.parametrize("kind", ["cycle", "unknown", "missing", "escape"])
def test_invalid_input_fails_explicitly(tmp_path, kind):
    source, parts = a8(tmp_path)
    cases = json.loads(source.read_text())
    art = cases[0]["sourceArticulation"]
    if kind == "cycle":
        art["joints"].append({"name": "back", "parent": "door", "child": "body", "motionType": "fixed"})
    elif kind == "unknown":
        art["joints"][0]["motionType"] = "ball"
    elif kind == "missing":
        (parts / "cabinet" / "door.glb").unlink()
    else:
        art["links"][0]["file"] = "../../secret.glb"
    source.write_text(json.dumps(cases))
    with pytest.raises(ValueError):
        run("a8-review", work(tmp_path, [source], {"parts_dir": str(parts)}))


def test_catalog_exposes_templates_through_task_runtime():
    from studio.core.task_templates import CATALOG, script_for

    for name in ["merge-review", "a8-review"]:
        assert next(x for x in CATALOG if x["id"] == name)["engine"] == "python"
        assert "studio.core.assembly_review" in script_for(name)
