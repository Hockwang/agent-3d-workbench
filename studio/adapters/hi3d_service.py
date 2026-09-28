"""Hi3D public API: AK/SK -> token -> image upload -> async GLB download.

Independently implemented from https://docs.hi3d.ai/en/api/api-reference/overview.
Only single-image geometry / geometry+texture generation is exposed for now.
No vendor desktop code. No credentials or signed URLs are written to artifacts.
"""

import base64
import json
import math
import os
from pathlib import Path
import re
import time
import uuid
from urllib.parse import urlencode

from studio.adapters.registry import BaseAdapter, register
from studio.adapters.transport import credential_refs, download, request
from studio.core.editor import EditorError, _atomic
from studio.i18n import register as register_messages, render

register_messages(
    {
        "hi3d.params": {
            "en": "Unsupported Hi3D parameter or model/resolution combination; see docs/HI3D.md.",
            "zh-CN": "Hi3D 参数或模型/分辨率组合不支持，请参阅 docs/HI3D.zh-CN.md。",
        },
        "hi3d.image": {
            "en": "Hi3D requires one local PNG/JPEG/WebP image, nonempty and at most 20 MB.",
            "zh-CN": "Hi3D 需要一张本地 PNG/JPEG/WebP 图片，非空且不超过 20 MB。",
        },
        "hi3d.credentials": {
            "en": "Set both HI3D_ACCESS_KEY and HI3D_SECRET_KEY in the MCP server environment; never put them in task params.",
            "zh-CN": "请在 MCP 服务进程环境中设置 HI3D_ACCESS_KEY 和 HI3D_SECRET_KEY，不要放进任务参数。",
        },
        "hi3d.response": {
            "en": "Hi3D request failed or returned an invalid response (code: {code}); no generation retry was sent.",
            "zh-CN": "Hi3D 请求失败或响应无效（错误码：{code}）；没有重发生成请求。",
        },
        "hi3d.title": {"en": "Image to 3D · Hi3D", "zh-CN": "图片生成 3D · Hi3D"},
        "hi3d.description": {
            "en": "Paid optional API: upload one image, generate a GLB, then import it for local editing. Model dimensions and part separation need review.",
            "zh-CN": "可选付费 API：上传一张图片，生成 GLB 后导入本地编辑；尺寸与分件仍需检查。",
        },
        "hi3d.probe": {
            "en": "Hi3D authentication and balance query succeeded. No generation submitted.",
            "zh-CN": "Hi3D 鉴权与余额查询成功，未提交生成任务。",
        },
    }
)

RESOLUTIONS = {
    "hitem3dv1.5": ("512", "1024", "1536", "1536pro"),
    "hitem3dv2.0": ("1536", "1536pro"),
    "hitem3dv2.1": ("1536fast", "1536pro"),
    "hi3dv3.0": ("2048quality", "2048master"),
}
DEFAULTS = {
    "model": "hitem3dv2.1",
    "resolution": "1536fast",
    "request_type": 3,
    "face": 100000,
    "format": 2,
    "pbr": 1,
    "rmbg": 1,
    "shading": 0.5,
}


def prepare_payload(operation, payload):
    p = {**DEFAULTS, **payload}
    if (
        operation != "image-to-3d"
        or set(payload) - set(DEFAULTS)
        or not isinstance(p["model"], str)
        or p["model"] not in RESOLUTIONS
        or p["resolution"] not in RESOLUTIONS[p["model"]]
        or any(type(p[k]) is not int for k in ("request_type", "face", "format", "pbr", "rmbg"))
        or p["request_type"] not in (1, 3)
        or p["format"] != 2
        or p["pbr"] not in (0, 1)
        or p["rmbg"] not in (0, 1)
        or not 100000 <= p["face"] <= 2000000
        or type(p["shading"]) not in (int, float)
        or not 0 <= p["shading"] <= 1
        or not math.isclose(p["shading"] * 10, round(p["shading"] * 10))
    ):
        raise EditorError.coded("hi3d.params")
    # v1.5 does not support PBR / de-shading fields.
    if p["model"] == "hitem3dv1.5":
        p.pop("pbr")
        p.pop("shading")
    return p


def response_data(response):
    code = response.get("code")
    if str(code) != "200" or not isinstance(response.get("data"), dict):
        # Do not echo arbitrary provider messages (could contain tokens or URLs).
        safe_code = str(code) if re.fullmatch(r"\d{1,12}", str(code)) else "unknown"
        raise RuntimeError(render("hi3d.response", code=safe_code))
    return response["data"]


def authenticate(spec):
    credential_refs(spec)
    access = os.environ.get(spec.get("key_env") or "", "")
    secret = os.environ.get(spec.get("secret_key_env") or "", "")
    if not access or not secret or ":" in access or any(c.isspace() for c in access + secret):
        raise EditorError.coded("hi3d.credentials")
    basic = base64.b64encode(f"{access}:{secret}".encode()).decode()
    data = response_data(request(spec, "POST", "/open-api/v1/auth/token", authorization="Basic " + basic))
    token = data.get("accessToken")
    if not isinstance(token, str) or not token or any(c.isspace() for c in token):
        raise RuntimeError(render("hi3d.response", code="invalid_token"))
    return "Bearer " + token


def balance(spec):
    data = response_data(request(spec, "GET", "/open-api/v1/balance", authorization=authenticate(spec)))
    value = data.get("totalBalance")
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise RuntimeError(render("hi3d.response", code="invalid_balance"))
    return value


def multipart(payload, inputs):
    if len(inputs) != 1:
        raise EditorError.coded("hi3d.image")
    path = Path(inputs[0])
    if (
        not path.is_file()
        or path.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp")
        or not 0 < path.stat().st_size <= 20 * 1024 * 1024
    ):
        raise EditorError.coded("hi3d.image")
    # Confirm the content, not just the extension, before any billable request.
    from PIL import Image

    try:
        with Image.open(path) as image:
            if image.format not in ("PNG", "JPEG", "WEBP"):
                raise ValueError()
            mime = Image.MIME[image.format]
            image.verify()
    except (OSError, ValueError):
        raise EditorError.coded("hi3d.image") from None
    boundary = "workbench-" + uuid.uuid4().hex
    parts = []
    for key, value in payload.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode())
    parts.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="images"; filename="reference{path.suffix.lower()}"\r\nContent-Type: {mime}\r\n\r\n'.encode()
    )
    parts.extend([path.read_bytes(), f"\r\n--{boundary}--\r\n".encode()])
    return b"".join(parts), "multipart/form-data; boundary=" + boundary


def run(workbench):
    from studio.adapters.services import _input_provenance

    data = workbench["params"]["service"]
    spec, output = data["spec"], Path(workbench["output"])
    receipt = output.parent / "service-receipt.json"
    ledger = json.loads(receipt.read_text()) if receipt.exists() else {}

    def save(**changes):
        ledger.update(changes)
        _atomic(receipt, json.dumps(ledger).encode())

    if not ledger.get("remote_id") and ledger.get("submission_attempted"):
        raise RuntimeError(render("services.previous_submission_ambiguous"))
    # All request authentication remains process-local, not in params/ledger.
    authorization = authenticate(spec)
    if not ledger.get("remote_id"):
        p = prepare_payload(data["operation"], data["payload"])
        body, mime = multipart(p, workbench["inputs"])
        save(
            provider=data["provider"],
            operation=data["operation"],
            adapter="hi3d",
            model=p["model"],
            request_params=p,
            submission_attempted=True,
            submitted_at=time.time(),
        )
        result = response_data(
            request(
                spec,
                "POST",
                "/open-api/v1/submit-task",
                raw=body,
                content_type=mime,
                authorization=authorization,
                timeout=180,
            )
        )
        remote_id = result.get("task_id")
        if not isinstance(remote_id, str) or not re.fullmatch(r"[a-zA-Z0-9_.-]{1,200}", remote_id):
            raise RuntimeError(render("services.missing_remote_id"))
        save(remote_id=remote_id)
    path = "/open-api/v1/query-task?" + urlencode({"task_id": ledger["remote_id"]})
    while True:
        result = response_data(request(spec, "GET", path, authorization=authorization))
        status = result.get("state")
        if status not in ("created", "queueing", "processing", "success", "failed"):
            raise RuntimeError(render("hi3d.response", code="invalid_state"))
        save(status=status, polled_at=time.time())
        print(json.dumps({"status": status}), flush=True)
        if status == "failed":
            raise RuntimeError(render("services.remote_task_failed", status=status))
        if status == "success":
            break
        time.sleep(max(1, min(30, float(spec.get("poll_interval", 10)))))
    url = result.get("url")
    if not isinstance(url, str) or not url:
        raise RuntimeError(render("services.no_downloadable_artifacts"))
    download(url, output / "model.glb")
    # Hi3D's query contract has no task cost field: leave it unknown.
    save(status="completed", received_at=time.time(), output_formats=["GLB"], cost=None, cost_unit="provider credits")
    summary = {
        k: ledger[k]
        for k in (
            "provider",
            "operation",
            "adapter",
            "model",
            "remote_id",
            "status",
            "submitted_at",
            "received_at",
            "request_params",
            "cost",
            "cost_unit",
        )
    }
    summary["input_sha256"] = _input_provenance(workbench["inputs"])
    (output / "service.json").write_text(json.dumps(summary, indent=2))


class Hi3DAdapter(BaseAdapter):
    def prepare_payload(self, spec, operation, payload):
        return prepare_payload(operation, payload)

    def operation_catalog(self, spec, item, *, internal_http):
        return {
            "operation_templates": [
                {
                    "id": "image-to-3d",
                    "title": render("hi3d.title"),
                    "input_mode": "image",
                    "params": dict(DEFAULTS),
                    "description": render("hi3d.description"),
                }
            ],
            "timeout_seconds": spec.get("default_timeout_seconds", 1800),
            "setup_message": render("hi3d.credentials"),
        }

    def probe(self, spec):
        available = balance(spec)
        return {
            "models": list(RESOLUTIONS),
            "message": render("hi3d.probe"),
            "generation_tested": False,
            "positive_balance": available > 0,
        }

    def run(self, workbench):
        run(workbench)


register("hi3d")(Hi3DAdapter())
