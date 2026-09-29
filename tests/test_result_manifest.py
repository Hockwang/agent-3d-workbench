import hashlib
import json

import pytest
import trimesh
from PIL import Image

from studio.core.editor import EditorError
from studio.core.result_manifest import FILENAME, SCHEMA, read_manifest, register_existing, validate
from studio.core.tasks import Tasks
from tests.helpers import wait


def identity(**extra):
    return dict(
        schema=SCHEMA, work_id="cup", work_title="Cup", variant="Local", version="v1", primary="scene.glb", **extra
    )


def test_manifest_references_only_delivered_model_and_image():
    files = [{"name": "scene.glb"}, {"name": "preview.png"}]
    assert validate(identity(thumbnail="preview.png"), files)["thumbnail"] == "preview.png"
    for field, value in [
        ("primary", "../scene.glb"),
        ("thumbnail", "https://elsewhere/p.png"),
        ("work_id", "../other-project"),
        ("work_title", "bad\nname"),
        ("version", ["v1"]),
        ("note", "x" * 281),
    ]:
        data = identity()
        data[field] = value
        with pytest.raises(EditorError):
            validate(data, files)


def test_absent_or_untrusted_manifest(tmp_path):
    assert read_manifest(tmp_path, []) is None
    path = tmp_path / FILENAME
    path.write_text("{not JSON")
    with pytest.raises(EditorError):
        read_manifest(tmp_path, [])
    path.unlink()
    source = tmp_path / "source.json"
    source.write_text(json.dumps(identity()))
    path.symlink_to(source)
    with pytest.raises(EditorError):
        read_manifest(tmp_path, [{"name": "scene.glb"}])


def test_register_existing_keeps_bytes_and_creates_result_in_target_project(tmp_path):
    source = tmp_path / "separate-experiment"
    source.mkdir()
    model = source / "generated.glb"
    model.write_bytes(trimesh.Scene(trimesh.creation.box()).export(file_type="glb"))
    thumb = source / "render.png"
    Image.new("RGB", (8, 8), "green").save(thumb)
    job = tmp_path / "current-project"
    job.mkdir()
    editor = job / "workbench"
    editor.mkdir()
    sentinel = editor / "project.json"
    sentinel.write_text('{"revision":17,"name":"Keep my editing scene"}')
    before = sentinel.read_bytes()
    tasks = Tasks(job / "tasks")
    task = tasks.start(
        {
            "engine": "python",
            "script": "from studio.core.result_manifest import register_existing\nregister_existing(workbench)",
            "params": identity(note="Review required"),
            "inputs": [str(model), str(thumb)],
            "render_preview": False,
        },
        "ai",
    )["task"]
    result = wait(tasks, task["id"])
    assert result["status"] == "completed", result
    assert result["result"]["work_id"] == "cup"
    assert result["result"]["note"] == "Review required"
    assert sentinel.read_bytes() == before
    artifact = next(a for a in result["artifacts"] if a["name"] == "scene.glb")
    assert artifact["sha256"] == hashlib.sha256(model.read_bytes()).hexdigest()
    assert artifact["meshes"] == 1
    assert {a["name"] for a in result["artifacts"]} == {"scene.glb", "preview.png", FILENAME}
    assert Tasks(job / "tasks").state(task["id"])["result"] == result["result"], (
        "identity survives restarting the reader"
    )


def test_registration_rejects_non_model_and_fake_thumbnail(tmp_path):
    model = tmp_path / "model.glb"
    model.write_bytes(b"glTF")
    fake = tmp_path / "private.png"
    fake.write_text("not an image")
    output = tmp_path / "output"
    output.mkdir()
    with pytest.raises(EditorError):
        register_existing({"inputs": [str(model), str(fake)], "params": identity(), "output": str(output)})
    assert not list(output.iterdir())
    with pytest.raises(EditorError):
        register_existing({"inputs": [str(fake)], "params": identity(), "output": str(output)})
