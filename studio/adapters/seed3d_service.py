"""Seed3D's company gateway contract; chat envelope carries only a 3D request.

This synchronous API has no supported polling endpoint. Submit once, persist the
result privately, and resume only its downloads. An ambiguous POST is never
retried. Registers itself as the `seed3d-chat` adapter.
"""

import json
from pathlib import Path
import time

from studio.core.editor import EditorError, _atomic
from studio.adapters.hunyuan_service import result_files, save_private, receive
from studio.adapters.assembly_service import remote_url
from studio.adapters.registry import BaseAdapter, register
from studio.adapters.transport import file_data, request
from studio.i18n import render

MODEL = "doubao-seed3d-2.0"


def operation_catalog():
    return [
        {
            "id": "image-to-3d",
            "title": render("seed3d_service.title_image_to_3d"),
            "input_mode": "image",
            "params": {"prompt": "Generate a 3D model from this image."},
            "labels": {"prompt": render("seed3d_service.label_prompt")},
            "description": render("seed3d_service.operation_description"),
        }
    ]


def prepare_payload(operation, payload):
    if operation != "image-to-3d" or set(payload) - {"prompt", "image_url"}:
        raise EditorError.coded("seed3d_service.unsupported_operation")
    p = {"prompt": "Generate a 3D model from this image.", **payload}
    if not isinstance(p["prompt"], str) or not 1 <= len(p["prompt"].strip()) <= 2000:
        raise EditorError.coded("seed3d_service.prompt_length_range")
    if "image_url" in p:
        remote_url(p["image_url"])
    return p


def build_request(p, inputs):
    if len(inputs) + bool(p.get("image_url")) != 1:
        raise EditorError.coded("seed3d_service.single_image_required")
    if inputs:
        path = Path(inputs[0])
        if path.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp") or path.stat().st_size > 4 * 1024 * 1024:
            raise EditorError.coded("seed3d_service.reference_image_invalid")
        url = file_data(path)
    else:
        url = p["image_url"]
    return {
        "model": MODEL,
        "messages": [
            {
                "role": "user",
                "content": [{"type": "text", "text": p["prompt"]}, {"type": "image_url", "image_url": {"url": url}}],
            }
        ],
    }


def run(workbench):
    from studio.adapters.services import _input_provenance, _sanitize_request_params

    data = workbench["params"]["service"]
    output = Path(workbench["output"])
    root = output.parent
    receipt, cache = root / "service-receipt.json", root / "seed3d-result.json"
    ledger = json.loads(receipt.read_text()) if receipt.exists() else {}

    def save(**changes):
        ledger.update(changes)
        _atomic(receipt, json.dumps(ledger).encode())

    if not cache.exists():
        if ledger.get("submission_attempted"):
            raise RuntimeError(render("seed3d_service.previous_submission_ambiguous"))
        p = prepare_payload(data["operation"], data["payload"])
        body = build_request(p, workbench["inputs"])
        save(
            provider=data["provider"],
            operation=data["operation"],
            model=MODEL,
            submission_attempted=True,
            submitted_at=time.time(),
            status="generating",
            adapter=data["spec"].get("adapter"),
            request_params=_sanitize_request_params(p),
        )
        response = request(data["spec"], "POST", "/chat/completions", body, timeout=900)
        try:
            content = response["choices"][0]["message"]["content"]
            if isinstance(content, str):
                content = json.loads(content)
            if isinstance(content, dict):
                content = [content]
            if not isinstance(content, list):
                raise ValueError()
            files = result_files({"output": content})
        except (KeyError, IndexError, TypeError, ValueError, RuntimeError):
            raise RuntimeError(render("seed3d_service.result_files_unrecognized")) from None
        save_private(cache, {"files": files})
    files = json.loads(cache.read_text())["files"]
    save(response_received=True, status="receiving")
    receive(files, output, "image-to-3d")
    glbs = sorted(output.rglob("*.glb"))
    if not glbs:
        raise RuntimeError(render("seed3d_service.no_previewable_glb"))
    summary = {
        "provider": data["provider"],
        "operation": data["operation"],
        "model": MODEL,
        "status": "completed",
        "files": len(files),
        "received_at": time.time(),
        "adapter": ledger.get("adapter"),
        "request_params": ledger.get("request_params"),
        "input_sha256": _input_provenance(workbench["inputs"]),
        "submitted_at": ledger.get("submitted_at"),
    }
    (output / "service.json").write_text(json.dumps(summary, indent=2))
    save(status="completed", output_formats=["GLB"], received_at=summary["received_at"])


class _Seed3DAdapter(BaseAdapter):
    def operation_catalog(self, spec, item, *, internal_http):
        return {
            "operation_templates": operation_catalog(),
            "timeout_seconds": 1800,
            "setup_message": render(
                "seed3d_service.setup_message_with_base_url"
                if item["needs_base_url"]
                else "seed3d_service.setup_message_without_base_url"
            ),
        }

    def prepare_payload(self, spec, operation, payload):
        return prepare_payload(operation, payload)

    def run(self, workbench):
        run(workbench)

    def probe(self, spec):
        result = request(spec, "GET", "/models", timeout=20)
        if not isinstance(result.get("data"), list):
            raise EditorError.coded("seed3d_service.model_list_invalid")
        allowed = {MODEL}
        models = sorted({x["id"] for x in result["data"] if isinstance(x, dict) and x.get("id") in allowed})
        return {
            "models": models,
            "message": (
                render("seed3d_service.probe_ok_with_models", models="、".join(models))
                if models
                else render("seed3d_service.probe_ok_no_models")
            ),
            "generation_tested": False,
        }


register("seed3d-chat")(_Seed3DAdapter())
