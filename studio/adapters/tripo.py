"""Tripo's public REST API (text/image/multiview-to-3D, retarget/rig, texture).

Like Meshy, Tripo has no dedicated task-params validator or settings-UI catalog
(BaseAdapter's no-op defaults apply); it plugs its own payload shaping (including
its multipart `/upload` step), `data.task_id` submission-id convention and
`data.*`-wrapped result envelope into `services.run_generic_job`'s shared
submit/poll/download loop. Registers itself as the `tripo` adapter.
"""

import mimetypes
import os
from pathlib import Path

from studio.core.editor import EditorError
from studio.adapters.registry import BaseAdapter, register
from studio.adapters.transport import field, request
from studio.i18n import render

OPERATIONS = {
    x: "/task"
    for x in (
        "text_to_model",
        "image_to_model",
        "multiview_to_model",
        "animate_rig",
        "animate_retarget",
        "texture_model",
        "convert_model",
    )
}


def upload(spec, filename):
    path = Path(filename)
    if path.stat().st_size > 20 * 1024 * 1024:
        raise RuntimeError(render("tripo.image_too_large"))
    boundary = "workbench-" + os.urandom(12).hex()
    ext = path.suffix.lower().lstrip(".").replace("jpeg", "jpg")
    if ext not in ("jpg", "png", "webp"):
        raise RuntimeError(render("tripo.unsupported_image_format"))
    raw = (
        (
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="input.{ext}"\r\n'
            f"Content-Type: {mimetypes.guess_type(path.name)[0]}\r\n\r\n"
        ).encode()
        + path.read_bytes()
        + f"\r\n--{boundary}--\r\n".encode()
    )
    result = request(spec, "POST", "/upload", raw=raw, content_type="multipart/form-data; boundary=" + boundary)
    token = field(result, "data.image_token") or field(result, "data.file_token")
    if not token:
        raise RuntimeError(render("tripo.upload_missing_file_token"))
    return {"type": ext, "file_token": token}


def _build_payload(spec, operation, payload, inputs):
    payload["type"] = operation
    if inputs and operation == "image_to_model":
        payload.setdefault("file", upload(spec, inputs[0]))
    if inputs and operation == "multiview_to_model":
        payload.setdefault("files", [upload(spec, name) for name in inputs])
    return payload


def _wrap_result(response):
    return field(response, "data", {})


def _extract_urls(spec, operation, route, result):
    output = result.get("output") or {}
    model = output.get("pbr_model") or output.get("model") or output.get("base_model")
    return {"glb": model} if model else {}


class _TripoAdapter(BaseAdapter):
    def run(self, workbench):
        # Deferred: services.py needs OPERATIONS (above) before it can define
        # run_generic_job, so this cannot be a module-level import (see
        # services.py's own registration-order comment).
        from studio.adapters import services

        services.run_generic_job(
            workbench,
            build_payload=_build_payload,
            id_path_default="data.task_id",
            wrap_result=_wrap_result,
            extract_urls=_extract_urls,
        )

    def probe(self, spec):
        result = request(spec, "GET", "/user/balance", timeout=20)
        if result.get("code") != 0:
            raise EditorError.coded("tripo.balance_rejected")
        return {"models": [], "message": render("tripo.probe_ok"), "generation_tested": False}


register("tripo")(_TripoAdapter())
