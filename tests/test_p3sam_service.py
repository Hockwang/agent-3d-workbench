import io
import json
from pathlib import Path
import zipfile

import numpy as np
import pytest
import trimesh

from studio.adapters import p3sam_service as p3, service_connections as connections, services, transport
from studio.core.editor import EditorError


def result_zip(source, *, wrong_order=False, wrong_params=False):
    mesh = trimesh.load(source, force="mesh", process=False)
    returned = mesh.copy()
    returned.apply_scale(0.25)
    returned.apply_translation([1, 2, 3])
    if wrong_order:
        returned.faces = np.roll(returned.faces, 1, axis=0)
    meta = {k: v for k, v in p3.DEFAULTS.items() if k not in ("return_glb", "return_cos_url", "prompt_bs")}
    if wrong_params:
        meta["face_label_solver"] = "legacy"
    labels = io.BytesIO()
    np.save(labels, np.arange(len(mesh.faces)) % 2)
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("segment.glb", returned.export(file_type="glb"))
        archive.writestr("face_ids.npy", labels.getvalue())
        archive.writestr("meta.json", json.dumps(meta))
    return output.getvalue()


def setup_job(tmp_path):
    source = tmp_path / "source.glb"
    trimesh.creation.box().export(source)
    output = tmp_path / "task" / "output"
    output.mkdir(parents=True)
    spec = dict(adapter="p3sam", base_url="http://localhost:8000", requires_key=False)
    return source, dict(inputs=[str(source)], output=str(output), params={"service": dict(
        provider="segmentation", spec=spec, operation="segment", payload={})})


def test_actual_zip_binding_and_no_second_post_on_resume(tmp_path, monkeypatch):
    source, work = setup_job(tmp_path)
    calls = []
    def request(spec, method, path, *args, **kwargs):
        calls.append(method)
        if method == "GET":
            return dict(status="ok", model_loaded=True)
        assert kwargs["binary"] and source.read_bytes() in kwargs["raw"]
        return result_zip(source)
    monkeypatch.setattr(p3, "request", request)
    adapter = p3.P3Adapter()
    adapter.run(work)
    output = Path(work["output"]) / "segmentation"
    labels = json.loads((output / "source-bound-labels.json").read_text())
    assert labels["source_sha256"] == p3.sha(source)
    assert sum(map(len, labels["nodes"].values())) == 12
    report = json.loads((output / "report.json").read_text())
    assert report["status"] == "proposal" and not report["printable_solids"]
    assert report["ordered_binding"]["corners_checked"] == 36
    adapter.run(work)
    assert calls.count("POST") == 1
    source.write_bytes(b"changed")
    with pytest.raises(RuntimeError, match="Resume differs"):
        adapter.run(work)


@pytest.mark.parametrize("problem", ["wrong_order", "wrong_params"])
def test_wrong_order_or_echo_is_rejected(tmp_path, monkeypatch, problem):
    source, work = setup_job(tmp_path)
    monkeypatch.setattr(p3, "request", lambda spec, method, *a, **kw: dict(status="ok", model_loaded=True)
                        if method == "GET" else result_zip(source, **{problem: True}))
    with pytest.raises(RuntimeError):
        p3.P3Adapter().run(work)
    assert not (Path(work["output"]) / "segmentation/source-bound-labels.json").exists()


def test_ambiguous_submission_never_retries(tmp_path, monkeypatch):
    _, work = setup_job(tmp_path)
    calls = []
    def request(spec, method, *a, **kw):
        calls.append(method)
        if method == "GET":
            return dict(status="ok", model_loaded=True)
        raise TimeoutError()
    monkeypatch.setattr(p3, "request", request)
    with pytest.raises(TimeoutError):
        p3.P3Adapter().run(work)
    with pytest.raises(RuntimeError, match="Ambiguous"):
        p3.P3Adapter().run(work)
    assert calls.count("POST") == 1


def test_segmentation_requires_https_or_loopback_and_no_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKBENCH_SERVICE_CONFIG", str(tmp_path / "services.json"))
    for url in ("http://segmentation.example", "https://user:password@segmentation.example"):
        with pytest.raises(EditorError):
            transport.service_transport(dict(adapter="p3sam", base_url=url, allow_insecure_http=True), submitting=True)
        with pytest.raises(EditorError):
            connections.save(dict(template="p3sam", title="Segmentation", base_url=url, expected_revision="0"))
    for url in ("https://segmentation.example", "http://127.0.0.1:8000"):
        assert transport.service_transport(dict(adapter="p3sam", base_url=url), submitting=True) == (url, {}, False)
    saved = connections.save(dict(template="p3sam", title="Segmentation", base_url="https://segmentation.example",
                                  expected_revision="0"))
    assert next(p for p in saved["profiles"] if p["id"] == saved["id"])["configured"]
    assert not services.config()[saved["id"]]["requires_key"]
    with pytest.raises(EditorError):
        connections.save(dict(template="p3sam", title="Bad", base_url="https://segmentation.example",
                              sealed_key={"fake": "credential"}, expected_revision=saved["revision"]))


def test_invalid_labels_and_sampling_rejected(tmp_path):
    _, work = setup_job(tmp_path)
    source = work["inputs"][0]
    from studio.adapters.assembly_service import safe_extract
    archive = tmp_path / "result.zip"
    archive.write_bytes(result_zip(source))
    output = Path(work["output"])
    safe_extract(archive, output / "segmentation")
    np.save(output / "segmentation/face_ids.npy", np.full(12, -1))
    with pytest.raises(RuntimeError, match="valid region label"):
        p3.validate_result(source, output / "segmentation", p3.DEFAULTS)
    for bad in ({"point_num": 1000000}, {"post_process": "false"}, {"face_label_solver": "legacy"}, {"mesh_url": "http://a"}):
        with pytest.raises(EditorError):
            p3.P3Adapter().prepare_payload({}, "segment", bad)


def test_live_documented_multimask_choices_and_probability_bounds():
    adapter=p3.P3Adapter()
    params=adapter.prepare_payload({},"segment",dict(mask_branch_strategy="all",mask_clustering_method="complete_linkage",
                                                   cluster_probability_aggregation="representative",cluster_similarity_threshold=.98))
    assert params["mask_branch_strategy"]=="all" and params["cluster_similarity_threshold"]==.98
    for bad in ({"mask_branch_strategy":"invented"},{"cluster_similarity_threshold":1.1},{"mask_threshold":2}):
        with pytest.raises(EditorError):
            adapter.prepare_payload({},"segment",bad)
