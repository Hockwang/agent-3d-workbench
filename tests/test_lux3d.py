import hashlib
import io
import json
import re
import zipfile
from pathlib import Path
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
import trimesh
from PIL import Image

from studio.adapters import services, lux3d_service as lux, lux3d_commerce as commerce, lux3d_upload as upload
from studio.core.editor import EditorError


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKBENCH_SERVICE_CONFIG", str(tmp_path / "services.json"))
    monkeypatch.setenv("LUX3D_CN_API_KEY", "fixture-private-lux-key")
    state = {
        "calls": [],
        "posts": 0,
        "outputs": [],
        "task_status": 3,
        "task_id": 1234567890,
        "files": {},
        "upload_name": "input.png",
    }
    stream = io.BytesIO()
    Image.new("RGB", (8, 8), "red").save(stream, format="PNG")
    glb = trimesh.Scene(trimesh.creation.box()).export(file_type="glb")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            self.handle_request()

        def do_POST(self):
            self.handle_request()

        def handle_request(self):
            raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            data = (
                json.loads(raw) if raw and self.headers.get("Content-Type", "").startswith("application/json") else None
            )
            state["calls"].append(
                {
                    "path": self.path,
                    "method": self.command,
                    "auth": self.headers.get("Authorization"),
                    "ous": self.headers.get("ous-token-v2"),
                    "body": data,
                    "raw": raw,
                }
            )
            if self.path.startswith("/files/"):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(state["files"].get(self.path, stream.getvalue() if ".png" in self.path else glb))
                return
            if self.path == "/asset/v1/token":
                result = {"ousToken": "fixture-upload-token", "globalDomain": state["origin"], "blockSize": 16}
            elif self.path.endswith("/block/upload/init"):
                result = {"lackBlocks": "1-5"}
            elif self.path.endswith("/upload/status"):
                result = {"status": 5, "url": state["origin"] + "/files/" + state["upload_name"]}
            elif self.path.startswith("/ous/"):
                name = re.search(rb'filename="([^"]+)"', raw)
                if name:
                    state["upload_name"] = name[1].decode()
                result = {}
            elif self.path == "/lux3d/v1/account/balance?source=1":
                now = datetime.now(timezone.utc)
                result = {
                    "availableCredits": 200,
                    "trialCountMap": {},
                    "member": False,
                    "memberType": 0,
                    "snapshotAt": now.isoformat(),
                    "uniqueId": "ctx_" + "1" * 32,
                    "uniqueIdExpiresAt": (now + timedelta(minutes=10)).isoformat(),
                }
            elif self.path == "/lux3d/v1/pricing/openapi-quotes":
                now = datetime.now(timezone.utc)
                result = {
                    "source": 1,
                    "uniqueId": data["uniqueId"],
                    "quoteId": "quote_" + "2" * 32,
                    "pricingScope": "BEFORE_ACCOUNT_BENEFITS",
                    "estimatedCreditsTotal": 10 * len(data["items"]),
                    "details": {k: 10 for k in data["items"]},
                    "quotedAt": now.isoformat(),
                    "expiresAt": (now + timedelta(minutes=5)).isoformat(),
                }
            elif self.path.endswith("/task/create"):
                state["posts"] += 1
                result = state["task_id"]
            elif "/task/get?" in self.path:
                result = {
                    "bizId": "LUX_3D",
                    "taskId": state["task_id"],
                    "status": state["task_status"],
                    "outputs": state["outputs"],
                }
            elif "/task/list?" in self.path:
                result = {
                    "total": 1,
                    "list": [
                        {"taskId": state["task_id"], "status": 3, "prompt": "private", "outputs": state["outputs"]}
                    ],
                }
            else:
                self.send_response(404)
                self.end_headers()
                return
            encoded = json.dumps({"f": None, "c": "0", "m": "", "d": result}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(encoded)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    state["origin"] = f"http://127.0.0.1:{server.server_port}"
    spec = {**services.BUILTINS["lux3d"], "base_url": state["origin"]}
    (tmp_path / "services.json").write_text(json.dumps({"lux3d": spec}))
    state.update(spec=spec, root=tmp_path, image=stream.getvalue(), glb=glb)
    try:
        yield state
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def work(api, operation="text-to-3d", payload=None, inputs=()):
    out = api["root"] / ("run-" + str(api.get("run", 0))) / "output"
    api["run"] = api.get("run", 0) + 1
    out.mkdir(parents=True)
    return {
        "output": str(out),
        "inputs": list(inputs),
        "params": {"service": services.prepare("lux3d", operation, payload or {"prompt": "chair"})},
    }


def allow_unquoted(api):
    """Opt this test's spec out of the server-side quote gate (studio_adapters.
    lux3d_service._Lux3DAdapter.prepare_payload) for tests whose purpose is
    submission/upload/output-slot mechanics, not the quote requirement itself."""
    api["spec"]["allow_unquoted"] = True
    (api["root"] / "services.json").write_text(json.dumps({"lux3d": api["spec"]}))


def test_account_quote_and_generation_bind_exact_request_without_leaking_key(api):
    params = {"prompt": "small chair"}
    quoted = commerce.execute({"action": "quote", "id": "lux3d", "operation": "text-to-3d", "params": params})
    assert quoted["account"]["availableCredits"] == 200 and quoted["quote"]["estimatedCreditsTotal"] == 10
    sent = next(x for x in api["calls"] if x["path"].endswith("openapi-quotes"))["body"]
    assert sent["source"] == 1 and sent["items"]["1"]["endpoint"]["path"] == lux.ROUTES["text-to-3d"]
    assert isinstance(sent["items"]["1"]["parameters"]["body"], str)
    body = {**params, "quote_id": quoted["quote_id"]}
    w = work(api, payload=body)
    api["outputs"] = [{"content": api["origin"] + "/files/chair.glb"}]
    lux.run(w)
    assert api["posts"] == 1
    artifact = Path(w["output"]) / "model.glb"
    assert artifact.read_bytes() == api["glb"]
    report = json.loads((Path(w["output"]) / "service.json").read_text())
    assert report["artifacts"][0]["sha256"] == hashlib.sha256(api["glb"]).hexdigest()
    assert all(c["auth"] == "fixture-private-lux-key" for c in api["calls"] if c["path"].startswith("/lux3d/"))
    assert all(c["auth"] is None for c in api["calls"] if c["path"].startswith("/files/"))
    assert "fixture-private-lux-key" not in json.dumps(w) + json.dumps(report)
    changed = work(api, payload={**body, "prompt": "different"})
    with pytest.raises(EditorError, match="已改变"):
        lux.run(changed)
    assert api["posts"] == 1
    record = commerce.quote_path(quoted["quote_id"])
    data = json.loads(record.read_text())
    data["quote"]["expiresAt"] = "2000-01-01T00:00:00Z"
    record.write_text(json.dumps(data))
    with pytest.raises(EditorError, match="过期"):
        commerce.quoted_payload(api["spec"], "text-to-3d", body, [])


def test_one_submission_then_resume_download_and_external_recovery(api, monkeypatch):
    allow_unquoted(api)
    api["outputs"] = [{"content": api["origin"] + "/files/chair.glb"}]
    w = work(api)
    original = services.download
    monkeypatch.setattr(services, "download", lambda *a: (_ for _ in ()).throw(RuntimeError("offline")))
    with pytest.raises(RuntimeError):
        lux.run(w)
    assert api["posts"] == 1
    monkeypatch.setattr(services, "download", original)
    lux.run(w)
    assert api["posts"] == 1
    external = work(api, payload={"remote_task_id": api["task_id"], "version": "G1-Turbo", "outputFormat": ["glb"]})
    lux.run(external)
    assert api["posts"] == 1
    history = commerce.execute({"action": "remote_tasks", "id": "lux3d"})
    assert "private" not in json.dumps(history) and "/files/" not in json.dumps(history)


def _credential_shaped_keys(value):
    if isinstance(value, dict):
        return [k for k in value if re.search("key|token|secret|authorization", k, re.I)] + [
            k for v in value.values() for k in _credential_shaped_keys(v)
        ]
    if isinstance(value, list):
        return [k for item in value for k in _credential_shaped_keys(item)]
    return []


def test_service_json_carries_adapter_model_and_sanitized_provenance(api):
    allow_unquoted(api)
    image = api["root"] / "ref.png"
    image.write_bytes(api["image"])
    api["outputs"] = [{"content": api["origin"] + "/files/chair.glb"}]
    w = work(
        api, operation="image-to-3d", payload={"version": "G1-Turbo", "outputFormat": ["glb"]}, inputs=[str(image)]
    )
    lux.run(w)
    report = json.loads((Path(w["output"]) / "service.json").read_text())
    assert report["adapter"] == "lux3d"
    assert report["model"] == "G1-Turbo"
    assert report["request_params"] == {"version": "G1-Turbo", "outputFormat": ["glb"]}
    assert report["input_sha256"] == [{"name": "ref.png", "sha256": hashlib.sha256(image.read_bytes()).hexdigest()}]
    assert isinstance(report["submitted_at"], float)
    assert "base_url" not in json.dumps(report)
    assert "fixture-private-lux-key" not in json.dumps(report)
    assert not _credential_shaped_keys(report)


def test_plan_quote_uses_each_items_own_payload_and_rejects_mismatch(api):
    result = commerce.execute(
        {
            "action": "quote",
            "id": "lux3d",
            "items": [
                {"operation": "text-to-3d", "params": {"prompt": "chair"}},
                {"operation": "text-to-3d", "params": {"prompt": "table"}},
            ],
        }
    )
    assert result["quote"]["estimatedCreditsTotal"] == 20
    assert result["items"]["2"]["quote_item"] == "2"
    second = {"prompt": "table", "quote_id": result["quote_id"], "quote_item": "2"}
    assert commerce.quoted_payload(api["spec"], "text-to-3d", second, [])["prompt"] == "table"
    with pytest.raises(EditorError, match="已改变"):
        commerce.quoted_payload(api["spec"], "text-to-3d", {**second, "quote_item": "1"}, [])
    assert api["posts"] == 0


@pytest.mark.parametrize("operation", ["image-to-3d", "multi-image-to-3d"])
def test_image_create_uses_published_img_route(api, operation):
    image = api["root"] / "sample.png"
    image.write_bytes(api["image"])
    quoted = commerce.quote(api["spec"], operation, {}, [str(image)])
    request = next(c for c in api["calls"] if c["path"].endswith("openapi-quotes"))["body"]
    assert request["items"]["1"]["endpoint"]["path"] == "/lux3d/v1/generate/img-to-3d/task/create"
    api["outputs"] = [{"content": api["origin"] + "/files/model.glb"}]
    lux.run(work(api, operation, {"quote_id": quoted["quote_id"]}, [str(image)]))
    assert any(c["path"] == "/lux3d/v1/generate/img-to-3d/task/create" for c in api["calls"])


def test_long_task_ids_stay_strings_in_public_metadata(api):
    api["task_id"] = 9223372036854775806
    result = commerce.execute({"action": "remote_task", "id": "lux3d", "remote_task_id": str(api["task_id"])})
    assert result["task"]["taskId"] == "9223372036854775806"


def test_material_format_reference_and_g1_artifacts(api):
    allow_unquoted(api)
    image = api["root"] / "image.png"
    image.write_bytes(api["image"])
    model = api["root"] / "input.glb"
    model.write_bytes(api["glb"])
    zipped = io.BytesIO()
    with zipfile.ZipFile(zipped, "w") as archive:
        archive.writestr("model.glb", api["glb"])
    api["files"]["/files/model.zip"] = zipped.getvalue()
    api["files"]["/files/model.stl"] = trimesh.creation.box().export(file_type="stl")
    cases = [
        (
            "material-transfer",
            {"version": "v3.0-standard"},
            [str(image), str(model)],
            ["model.zip", "model.glb", None, None, None],
            {"model.zip", "model.glb"},
        ),
        (
            "multi-format-export",
            {"outputFormat": ["stl"]},
            [str(model)],
            [None, None, None, None, None, "model.stl", None],
            {"model.stl"},
        ),
        ("multimodal-image", {"prompt": "glass chair"}, [], ["input.png"], {"view-0.png"}),
        (
            "text-to-3d",
            {"prompt": "glass chair", "style": "glass", "version": "G1"},
            [],
            ["model.zip", "model.glb"],
            {"model.zip", "model.glb"},
        ),
    ]
    for operation, params, inputs, slots, expected in cases:
        api["outputs"] = [
            {"content": api["origin"] + "/files/" + f} if f else {"content": "NOT_REQUESTED"} for f in slots
        ]
        w = work(api, operation, params, inputs)
        lux.run(w)
        assert expected <= {p.name for p in Path(w["output"]).iterdir()}


def test_ambiguous_submission_never_retries(api, monkeypatch):
    allow_unquoted(api)
    w = work(api)
    original = lux.request

    def unreliable(spec, method, path, payload=None):
        if path.endswith("/create"):
            original(spec, method, path, payload)
            raise RuntimeError("lost response")
        return original(spec, method, path, payload)

    monkeypatch.setattr(lux, "request", unreliable)
    with pytest.raises(RuntimeError):
        lux.run(w)
    monkeypatch.setattr(lux, "request", original)
    with pytest.raises(EditorError, match="不明确"):
        lux.run(w)
    assert api["posts"] == 1


def test_upload_blocks_uses_only_storage_token_and_downloads_four_views(api):
    allow_unquoted(api)
    image = api["root"] / "image.png"
    image.write_bytes(api["image"])
    assert upload.upload(api["spec"], str(image)) == api["origin"] + "/files/input.png"
    storage = [x for x in api["calls"] if x["path"].startswith("/ous/")]
    assert all(x["auth"] is None and x["ous"] == "fixture-upload-token" for x in storage)
    blocks = [x for x in storage if x["path"].endswith("/part")]
    assert len(blocks) == 5
    w = work(api, "four-view", {"prompt": "chair"})
    api["outputs"] = [{"content": json.dumps([api["origin"] + f"/files/view{i}.png" for i in range(4)])}]
    lux.run(w)
    assert len(list(Path(w["output"]).glob("view-*.png"))) == 4


@pytest.mark.parametrize(
    "operation,payload,slots,expected",
    [
        ("text-to-3d", {"version": "G1"}, ["zip", "glb"], {"zip", "glb"}),
        ("image-to-3d", {"version": "G1-Turbo", "outputFormat": ["ply", "glb"]}, ["ply", "glb"], {"ply", "glb"}),
        ("material-transfer", {"outputFormat": ["usdz"]}, ["zip", "glb", "usdz", None, None], {"zip", "glb", "usdz"}),
        (
            "multi-format-export",
            {"outputFormat": ["stl", "3mf"], "modelUrl": "https://x.test/model.glb"},
            [None, None, None, None, None, "stl", "3mf"],
            {"stl", "3mf"},
        ),
    ],
)
def test_outputs_follow_exact_slots_and_preserve_formats(operation, payload, slots, expected):
    d = {
        "outputs": [
            {"content": "https://cdn.test/opaque?signature=x"} if x else {"content": "NOT_REQUESTED"} for x in slots
        ]
    }
    assert set(lux.output_urls(operation, payload, d)) == expected
    d["outputs"].pop()
    with pytest.raises(EditorError):
        lux.output_urls(operation, payload, d)


@pytest.mark.parametrize(
    "op,params",
    [
        ("text-to-3d", {"prompt": "x", "version": "G1", "enablePbr": True}),
        ("text-to-3d", {"prompt": "x", "version": "G1-Turbo", "customSize": 12}),
        ("image-to-3d", {"img": "https://x.test/a.png", "imgs": ["https://x.test/b.png"]}),
        ("image-to-3d", {"faceCount": True}),
        ("image-to-3d", {"faceCount": 9999}),
        ("material-transfer", {"aiPredictSize": True, "customSize": 50}),
        ("multi-format-export", {"modelUrl": "https://x.test/a.glb"}),
    ],
)
def test_bad_parameters_rejected_before_network(op, params):
    with pytest.raises(EditorError):
        lux.prepare_payload(op, params, complete=True)


def test_region_task_identity_and_wrong_success_envelope(api):
    with pytest.raises(EditorError):
        lux.check_region({**api["spec"], "base_url": "https://api.aholo3d.com/global"})
    with pytest.raises(EditorError):
        lux.unwrap({"c": 0, "d": {}})
    for value in (True, 0, -1, "not-an-id"):
        with pytest.raises(EditorError):
            lux.task_id(value)
    with pytest.raises(EditorError):
        lux.get_task(api["spec"], 123)
    api["task_status"] = 2
    with pytest.raises(EditorError):
        lux.get_task(api["spec"], api["task_id"])
    assert upload.missing_blocks("1-2,4", 4) == [1, 2, 4]
    with pytest.raises(EditorError):
        upload.missing_blocks("0-100", 4)


def test_missing_quote_is_rejected_before_any_network_call(api):
    calls_before = len(api["calls"])
    with pytest.raises(EditorError, match="报价"):
        work(api)
    assert len(api["calls"]) == calls_before


def test_quote_present_lets_prepare_pass(api):
    quoted = commerce.quote(api["spec"], "text-to-3d", {"prompt": "chair"}, [])
    w = work(api, payload={"prompt": "chair", "quote_id": quoted["quote_id"]})
    assert w["params"]["service"]["payload"]["prompt"] == "chair"


def test_remote_task_id_recovery_needs_no_quote(api):
    w = work(api, payload={"remote_task_id": api["task_id"], "version": "G1-Turbo", "outputFormat": ["glb"]})
    assert w["params"]["service"]["payload"]["remote_task_id"] == api["task_id"]


def test_allow_unquoted_opt_out_bypasses_the_gate(api):
    allow_unquoted(api)
    w = work(api)
    assert w["params"]["service"]["payload"]["prompt"] == "chair"


def test_default_builtins_lux3d_specs_do_not_allow_unquoted():
    assert "allow_unquoted" not in services.BUILTINS["lux3d"]
    assert "allow_unquoted" not in services.BUILTINS["lux3d-global"]
