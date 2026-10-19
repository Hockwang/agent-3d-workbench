import hashlib
import json

import numpy as np
import pytest
import trimesh

from studio.core.editor import EditorError
from studio.shell.server import StudioBackend


def saved_task(backend, *, animated=False):
    task_id = "a" * 32
    folder = backend.tasks.root / task_id
    output = folder / "output"
    output.mkdir(parents=True)
    scene = trimesh.Scene(trimesh.creation.box([0.02, 0.04, 0.03]))
    raw = scene.export(file_type="glb")
    if animated:
        import struct

        length = struct.unpack_from("<I", raw, 12)[0]
        doc = json.loads(raw[20:20 + length])
        doc["animations"] = [{"channels": [], "samplers": []}]
        encoded = json.dumps(doc).encode()
        encoded += b" " * (-len(encoded) % 4)
        tail = raw[20 + length:]
        raw = struct.pack("<5I", 0x46546C67, 2, 20 + len(encoded) + len(tail), len(encoded), 0x4E4F534A) + encoded + tail
    path = output / "scene.glb"
    path.write_bytes(raw)
    item = {"id": "model", "name": "scene.glb", "path": str(path), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
    (folder / "state.json").write_text(json.dumps({"id": task_id, "status": "completed", "created": 1, "artifacts": [item]}))
    return {"task_id": task_id, "artifact_id": "model"}, path


def test_task_model_goes_straight_to_print_in_mm_z_up_without_editing_scene(tmp_path):
    backend = StudioBackend(tmp_path / "job", "test")
    backend.editor.execute({"action": "primitive", "expected_revision": 0, "params": {"kind": "box"}})
    request, source = saved_task(backend)
    scene_before = backend.editor.path.read_bytes()
    source_before = source.read_bytes()
    result = backend.api_load(request)
    assert result["ok"] and not result["print_submitted"]
    assert len(result["parts"]) == 1
    np.testing.assert_allclose(result["parts"][0]["extents_mm"], [20, 30, 40], atol=1e-5)
    assert backend.editor.path.read_bytes() == scene_before
    assert source.read_bytes() == source_before
    assert str(source) != result["parts"][0]["source"]
    assert (tmp_path / "job" / "job.json").is_file()


@pytest.mark.parametrize("failure", ["checksum", "animated", "missing", "mixed"])
def test_invalid_task_model_does_not_replace_print_state(tmp_path, failure):
    backend = StudioBackend(tmp_path / "job", "test")
    request, source = saved_task(backend, animated=failure == "animated")
    old_job = backend.job_dir / "job.json"
    old_job.write_text('{"marker": "keep"}')
    if failure == "checksum":
        raw = bytearray(source.read_bytes())
        raw[-1] ^= 1
        source.write_bytes(raw)
    elif failure == "missing":
        request["artifact_id"] = "absent"
    elif failure == "mixed":
        request["files"] = [str(source)]
    with pytest.raises((EditorError, ValueError)):
        backend.api_load(request)
    assert old_job.read_text() == '{"marker": "keep"}'


def test_task_print_load_http_route_records_the_model_and_keeps_editor_revision(studio_env):
    backend, client = studio_env["backend"], studio_env["client"]
    request, _ = saved_task(backend)
    revision = backend.editor.doc["revision"]
    status, result = client.post("/api/load", request)
    assert status == 200 and result["ok"]
    _, state = client.get("/api/state")
    assert state["parts"] and state["history"][0]["op"] == "load"
    assert state["workbench"]["revision"] == revision
