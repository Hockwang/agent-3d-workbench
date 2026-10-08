"""Local handoff validation and the existing HTTP session boundary."""

import json
import threading

import pytest

from studio.adapters import link_everything
from studio.shell.server import create_httpd
from tests.helpers import Client


def make_project(root, source="manual", artifact_url="/outputs/manual/revisions/r0001/assembly.glb"):
    outputs = root / "outputs"
    state = outputs / ("project.json" if source == "legacy" else f"{source}/project.json")
    state.parent.mkdir(parents=True, exist_ok=True)
    artifact = outputs / "manual/revisions/r0001/assembly.glb"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_bytes(b"glTF")
    state.write_text(
        json.dumps({"revision": 1, "artifacts": [{"id": "assembly.glb", "url": artifact_url}]}),
        encoding="utf-8",
    )
    return artifact


def test_project_reads_only_valid_generated_artifacts(tmp_path, monkeypatch):
    monkeypatch.setenv("LINK_EVERYTHING_ROOT", str(tmp_path))
    artifact = make_project(tmp_path)
    result = link_everything.project("manual")
    assert result["units"] == "m"
    assert result["revision"] == 1
    assert result["import_file"] == str(artifact.resolve())
    assert set(result) == {"revision", "preset_id", "source", "import_file", "units"}


@pytest.mark.parametrize(
    "url",
    [
        "/outputs/manual/../../outside.glb",
        "/outputs/manual/revisions/r0001/assembly.glb?token=secret",
        "https://provider.example/model.glb",
        "/outputs/manual/revisions/r0001/private.json",
    ],
)
def test_handoff_rejects_external_and_out_of_scope_artifacts(tmp_path, monkeypatch, url):
    monkeypatch.setenv("LINK_EVERYTHING_ROOT", str(tmp_path))
    make_project(tmp_path, artifact_url=url)
    with pytest.raises(link_everything.AssemblyProjectError) as caught:
        link_everything.project("manual")
    assert caught.value.code == "assembly_not_ready"
    assert str(tmp_path) not in str(caught.value)


def test_handoff_http_keeps_token_and_fetch_site_protection(tmp_path, monkeypatch):
    monkeypatch.setenv("LINK_EVERYTHING_ROOT", str(tmp_path / "connections"))
    make_project(tmp_path / "connections")
    httpd, port, backend = create_httpd(tmp_path / "workbench", port=0)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    client = Client(f"http://127.0.0.1:{port}", backend.token)
    try:
        assert client.get("/api/assembly/project?source=manual", token=None)[0] == 403
        assert client.get("/api/assembly/project?source=manual", headers={"Sec-Fetch-Site": "cross-site"})[0] == 403
        status, data = client.get("/api/assembly/project?source=manual")
        assert status == 200 and data["revision"] == 1
        assert client.get("/api/assembly/project?source=other")[0] == 400
        assert client.get("/api/assembly/project?source=presets")[0] == 409
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=3)
