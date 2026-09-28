"""Hunyuan 3D/Part through the company's Responses gateway, without an LLM call.

Protocol: CF 81467106899 qunhe-image3d-pipeline and CF 81494192346.
Reuse the task runner, HTTP transport, bounded ZIP extraction and shared viewer.
Only one paid POST; every recovery polls the persisted response ID. Registers
itself as the `hunyuan-responses` adapter.
"""

from pathlib import Path
import json
import math
import os
import re
import tempfile
import time
import zipfile

from studio.core.editor import EditorError, _atomic
from studio.adapters.assembly_service import remote_url, safe_extract
from studio.adapters.registry import BaseAdapter, register
from studio.adapters.transport import file_data, request, validate_url
from studio.i18n import render

GEN_MODELS = ("hunyuan-3d-3.1-pro", "hunyuan-3d-3.0-pro", "hunyuan-3d-pro", "hunyuan-3d-rapid")
PART_MODEL = "hunyuan-3d-1.5-part"
FORMATS = ("GLB", "FBX", "OBJ")


def operation_catalog(operations):
    result = []
    for key in operations:
        if key == "segment":
            result.append(
                {
                    "id": key,
                    "title": render("hunyuan_service.op_segment_title"),
                    "input_mode": "remote_urls",
                    "params": {"source_task": "", "file_url": ""},
                    "optional_params": ["source_task", "file_url"],
                    "labels": {
                        "source_task": render("hunyuan_service.label_source_task"),
                        "file_url": render("hunyuan_service.label_file_url"),
                    },
                    "description": render("hunyuan_service.op_segment_description"),
                }
            )
        elif key in ("image-to-3d", "text-to-3d"):
            result.append(
                {
                    "id": key,
                    "title": render(
                        "hunyuan_service.op_image_to_3d_title"
                        if key == "image-to-3d"
                        else "hunyuan_service.op_text_to_3d_title"
                    ),
                    "input_mode": "image" if key == "image-to-3d" else "remote_urls",
                    "params": {
                        "model": GEN_MODELS[0],
                        "output_format": "FBX",
                        "face_count": 60000,
                        **({"prompt": ""} if key == "text-to-3d" else {}),
                    },
                    "choices": {
                        "model": {x: x.removeprefix("hunyuan-3d-") for x in GEN_MODELS},
                        "output_format": {x: x for x in FORMATS},
                    },
                    "labels": {
                        "model": render("hunyuan_service.label_model"),
                        "output_format": render("hunyuan_service.label_output_format"),
                        "face_count": render("hunyuan_service.label_face_count"),
                    },
                    "description": render(
                        "hunyuan_service.op_image_to_3d_description"
                        if key == "image-to-3d"
                        else "hunyuan_service.op_text_to_3d_description"
                    ),
                }
            )
    return result


def prepare_payload(operation, payload):
    p = dict(payload)
    allowed = (
        {"source_task", "file_url"}
        if operation == "segment"
        else {"model", "output_format", "face_count", "generate_type", "pbr", "prompt", "image_url"}
    )
    if operation not in ("segment", "image-to-3d", "text-to-3d") or set(p) - allowed:
        raise EditorError.coded("hunyuan_service.unknown_operation_or_params")
    if operation == "segment":
        p = {k: v for k, v in p.items() if v != ""}
        if len(p) != 1:
            raise EditorError.coded("hunyuan_service.segment_needs_single_source")
        if "source_task" in p and (
            not isinstance(p["source_task"], str) or not re.fullmatch(r"[a-f0-9]{32}", p["source_task"])
        ):
            raise EditorError.coded("hunyuan_service.invalid_source_task_id")
        if "file_url" in p:
            remote_url(p["file_url"])
        return p
    p.setdefault("model", GEN_MODELS[0])
    p.setdefault("output_format", "FBX")
    if p["model"] not in GEN_MODELS:
        raise EditorError.coded("hunyuan_service.unsupported_model")
    if p["output_format"] not in FORMATS:
        raise EditorError.coded("hunyuan_service.invalid_output_format")
    if "face_count" in p and (type(p["face_count"]) is not int or not 3000 <= p["face_count"] <= 1500000):
        raise EditorError.coded("hunyuan_service.invalid_face_count")
    if "pbr" in p and type(p["pbr"]) is not bool:
        raise EditorError.coded("hunyuan_service.pbr_must_be_bool")
    if "generate_type" in p and p["generate_type"] not in ("Normal", "LowPoly", "Geometry", "Sketch"):
        raise EditorError.coded("hunyuan_service.invalid_generate_type")
    if "prompt" in p and (not isinstance(p["prompt"], str) or not 1 <= len(p["prompt"].strip()) <= 200):
        raise EditorError.coded("hunyuan_service.invalid_prompt_length")
    if operation == "text-to-3d" and (not p.get("prompt") or "image_url" in p):
        raise EditorError.coded("hunyuan_service.text_to_3d_no_image")
    if "image_url" in p:
        remote_url(p["image_url"])
    return p


def source_file(root, task_id, provider):
    source = root.parent / task_id
    try:
        receipt = json.loads((source / "service-receipt.json").read_text())
        result = json.loads((source / "hunyuan-result.json").read_text())
    except (OSError, ValueError):
        raise EditorError.coded("hunyuan_service.source_task_no_result") from None
    if receipt.get("provider") != provider or receipt.get("operation") not in ("image-to-3d", "text-to-3d"):
        raise EditorError.coded("hunyuan_service.source_task_wrong_provider")
    urls = [item["url"] for item in result["files"] if item["type"] == "FBX"]
    if not urls:
        raise EditorError.coded("hunyuan_service.source_task_missing_fbx")
    return remote_url(urls[0])


def build_request(operation, p, inputs, root, provider):
    content, tool = [], {"type": "3d_generation"}
    if operation == "segment":
        if inputs:
            raise EditorError.coded("hunyuan_service.segment_no_local_upload")
        url = source_file(root, p["source_task"], provider) if p.get("source_task") else p["file_url"]
        content.append({"type": "input_file", "file_url": url})
        model = PART_MODEL
    else:
        model = p["model"]
        tool.update({key: p[key] for key in ("output_format", "face_count", "generate_type", "pbr") if key in p})
        if operation == "image-to-3d":
            if len(inputs) + bool(p.get("image_url")) != 1:
                raise EditorError.coded("hunyuan_service.image_to_3d_needs_single_image")
            if inputs:
                path = Path(inputs[0])
                if (
                    path.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp")
                    or path.stat().st_size > 4 * 1024 * 1024
                ):
                    raise EditorError.coded("hunyuan_service.invalid_reference_image")
                url = file_data(path)
            else:
                url = p["image_url"]
            content.append({"type": "input_image", "image_url": url})
        elif inputs:
            raise EditorError.coded("hunyuan_service.text_to_3d_no_files")
        if p.get("prompt"):
            content.append({"type": "input_text", "text": p["prompt"]})
    return {
        "model": model,
        "background": True,
        "input": [{"role": "user", "type": "message", "content": content}],
        "tools": [tool],
    }


def result_files(response):
    files, seen = [], set()
    for call in response.get("output") or []:
        if not isinstance(call, dict) or call.get("type") != "3d_generation_call":
            continue
        for item in call.get("content") or []:
            if not isinstance(item, dict):
                continue
            kind, url = str(item.get("type", "")).upper(), item.get("url")
            if kind not in ("GLB", "FBX", "OBJ", "STL", "ZIP") or not isinstance(url, str):
                continue
            validate_url(url)
            if url not in seen:
                files.append({"type": kind, "url": url})
                seen.add(url)
    if not files or len(files) > 128:
        raise RuntimeError(render("hunyuan_service.result_missing_or_too_many"))
    return files


def save_private(path, value):
    # Signed CDN URLs are only a local continuation cache, never delivered artifacts.
    fd, temporary = tempfile.mkstemp(prefix=".hunyuan-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def receive(files, output, operation):
    from studio.adapters.services import download

    for i, item in enumerate(files):
        target = output / f"model-{i:03d}.{item['type'].lower()}"
        download(item["url"], target)
        if zipfile.is_zipfile(target):
            archive = target.with_suffix(".zip")
            target.replace(archive)
            safe_extract(archive, output / f"model-{i:03d}")
    glbs = [p for p in sorted(output.rglob("*.glb")) if p.name != "combined.glb"]
    if operation == "segment":
        if not glbs:
            raise RuntimeError(render("hunyuan_service.part_missing_preview_glb"))
        import trimesh

        combined = trimesh.Scene()
        for index, path in enumerate(glbs):
            scene = trimesh.load(path, force="scene", process=False)
            for node in scene.graph.nodes_geometry:
                matrix, name = scene.graph[node]
                combined.add_geometry(
                    scene.geometry[name],
                    transform=matrix,
                    geom_name=f"part-{index:03d}-{name}",
                    node_name=f"part-{index:03d}-{node}",
                )
        if not combined.geometry:
            raise RuntimeError(render("hunyuan_service.part_empty_geometry"))
        combined.export(output / "combined.glb")


def run(workbench):
    from studio.adapters.services import _input_provenance, _sanitize_request_params

    data = workbench["params"]["service"]
    spec, operation, provider = data["spec"], data["operation"], data["provider"]
    p = prepare_payload(operation, data["payload"])
    output = Path(workbench["output"])
    root = output.parent
    receipt = root / "service-receipt.json"
    ledger = json.loads(receipt.read_text()) if receipt.exists() else {}

    def save(**changes):
        ledger.update(changes)
        _atomic(receipt, json.dumps(ledger).encode())

    if not ledger.get("remote_id"):
        if ledger.get("submission_attempted"):
            raise RuntimeError(render("hunyuan_service.previous_submission_ambiguous"))
        body = build_request(operation, p, workbench["inputs"], root, provider)
        save(
            provider=provider,
            operation=operation,
            model=body["model"],
            submission_attempted=True,
            submitted_at=time.time(),
            status="submitting",
            adapter=spec.get("adapter"),
            request_params=_sanitize_request_params(p),
        )
        response = request(spec, "POST", "/responses", body, timeout=120)
        remote_id = response.get("id")
        if not isinstance(remote_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", remote_id):
            raise RuntimeError(render("hunyuan_service.missing_valid_task_id"))
        save(remote_id=remote_id)
    while True:
        response = request(spec, "GET", "/responses/" + ledger["remote_id"])
        status = response.get("status")
        if status not in ("queued", "in_progress", "completed", "failed", "cancelled", "expired", "incomplete"):
            raise RuntimeError(render("hunyuan_service.unknown_status"))
        save(status=status, polled_at=time.time())
        print(json.dumps({"remote_id": ledger["remote_id"], "status": status}), flush=True)
        if status == "completed":
            break
        if status not in ("queued", "in_progress"):
            raise RuntimeError(render("hunyuan_service.task_ended", status=status))
        time.sleep(max(1, min(30, float(spec.get("poll_interval", 5)))))
    files = result_files(response)
    save_private(root / "hunyuan-result.json", {"files": files})
    receive(files, output, operation)
    # Only scalar billing fields, never the raw response: `usage`/other response
    # fields can otherwise re-embed the request's own `image_url`/`file_url`
    # verbatim, including their query string. `request_params` above already went
    # through `_sanitize_request_params`, which keeps only scheme+host+path of any
    # URL; copying the raw response here would bypass that.
    cost = (response.get("usage") or {}).get("price") or {}
    cost = (
        {
            k: v
            for k, v in cost.items()
            if k in ("actual_amount", "payable_amount", "discount") and type(v) in (int, float) and math.isfinite(v)
        }
        if isinstance(cost, dict)
        else {}
    )
    summary = {
        "provider": provider,
        "operation": operation,
        "model": ledger["model"],
        "remote_id": ledger["remote_id"],
        "status": "completed",
        "files": len(files),
        "cost": cost or None,
        "cost_unit": render("hunyuan_service.cost_unit_gateway_reported"),
        "received_at": time.time(),
        "adapter": ledger.get("adapter"),
        "request_params": ledger.get("request_params"),
        "input_sha256": _input_provenance(workbench["inputs"]),
        "submitted_at": ledger.get("submitted_at"),
    }
    (output / "service.json").write_text(json.dumps(summary, indent=2))
    save(output_formats=sorted({x["type"] for x in files}), received_at=summary["received_at"])


class _HunyuanAdapter(BaseAdapter):
    def operation_catalog(self, spec, item, *, internal_http):
        return {
            "operation_templates": operation_catalog(item["operations"]),
            "timeout_seconds": 1800,
            "setup_message": render(
                "hunyuan_service.setup_message_needs_base_url"
                if item["needs_base_url"]
                else "hunyuan_service.setup_message_configured"
            ),
        }

    def prepare_payload(self, spec, operation, payload):
        return prepare_payload(operation, payload)

    def run(self, workbench):
        run(workbench)

    def probe(self, spec):
        result = request(spec, "GET", "/models", timeout=20)
        if not isinstance(result.get("data"), list):
            raise EditorError.coded("hunyuan_service.probe_invalid_model_list")
        allowed = {*GEN_MODELS, PART_MODEL}
        models = sorted({x["id"] for x in result["data"] if isinstance(x, dict) and x.get("id") in allowed})
        return {
            "models": models,
            "message": (
                render("hunyuan_service.probe_message_with_models", models="、".join(models))
                if models
                else render("hunyuan_service.probe_message_no_models")
            ),
            "generation_tested": False,
        }


register("hunyuan-responses")(_HunyuanAdapter())
