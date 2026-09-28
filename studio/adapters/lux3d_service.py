"""Lux3D public OpenAPI adapter, independently implemented from its contracts.

API baseline: manycore-research/Aholo-Lux3D @ 71779ccd8290e999d980621439c728524830f422.
Raw-key auth, region separation, one create attempt, numeric task identity and
ordered output slots are protocol requirements (not generic provider behavior).
Registers itself as the `lux3d` adapter (shared by the cn/global BUILTINS entries).
"""

from __future__ import annotations
import hashlib
import json
import math
from pathlib import Path
import re
import time
from urllib.parse import urlencode, urlsplit

from studio.core.editor import EditorError, _atomic
from studio.adapters.registry import BaseAdapter, register
from studio.adapters.transport import request as _api_request, validate_url
from studio.i18n import render

ROUTES = {
    op: "/lux3d/v1/generate/" + route + "/task/create"
    for op, route in {
        "image-to-3d": "img-to-3d",
        "multi-image-to-3d": "img-to-3d",
        "text-to-3d": "text-to-3d",
        "material-transfer": "material-transfer",
        "four-view": "image-to-four-view",
        "multimodal-image": "multimodal-to-image",
    }.items()
}
ROUTES["multi-format-export"] = "/lux3d/v1/multi-format-export/task/create"
SLOTS = ["zip", "glb", "usdz", "obj_zip", "fbx_zip", "stl", "3mf"]
TITLE_CODES = {
    "image-to-3d": "lux3d_service.title_image_to_3d",
    "multi-image-to-3d": "lux3d_service.title_multi_image_to_3d",
    "text-to-3d": "lux3d_service.title_text_to_3d",
    "material-transfer": "lux3d_service.title_material_transfer",
    "four-view": "lux3d_service.title_four_view",
    "multimodal-image": "lux3d_service.title_multimodal_image",
    "multi-format-export": "lux3d_service.title_multi_format_export",
}


def operation_catalog():
    result = []
    for op in ROUTES:
        params = {"prompt": ""} if op in ("text-to-3d", "four-view", "multimodal-image") else {}
        choices = {}
        if op in ("image-to-3d", "multi-image-to-3d", "text-to-3d"):
            params.update(version="G1-Turbo", faceCount=100000, outputFormat="glb")
            choices = {
                "version": {"G1-Turbo": "G1-Turbo", "G1": "G1"},
                "outputFormat": {
                    "glb": "GLB",
                    "zip": render("lux3d_service.output_format_zip_label"),
                    "ply": render("lux3d_service.output_format_ply_label"),
                },
            }
        elif op == "material-transfer":
            params.update(version="v3.0-standard", outputFormat="glb")
        elif op == "multi-format-export":
            params.update(outputFormat="stl")
            choices = {"outputFormat": {x: x.upper() for x in SLOTS[2:]}}
        result.append(
            {
                "id": op,
                "title": render(TITLE_CODES[op]),
                "params": params,
                "choices": choices,
                "optional_params": ["prompt"] if op in ("four-view", "multimodal-image") else [],
                "input_mode": "image"
                if op in ("image-to-3d", "multi-image-to-3d", "four-view", "multimodal-image")
                else "files",
                "description": render("lux3d_service.operation_description"),
            }
        )
    return result


def check_region(spec):
    region = spec.get("region")
    base = spec.get("base_url", "").rstrip("/")
    if region not in ("cn", "international"):
        raise EditorError.coded("lux3d_service.region_required")
    known = {"api.aholo3d.cn": "cn", "api.aholo3d.com": "international"}
    host = urlsplit(base).hostname
    if host in known and known[host] != region:
        raise EditorError.coded("lux3d_service.region_mismatch")
    if host == "api.aholo3d.com" and urlsplit(base).path != "/global":
        raise EditorError.coded("lux3d_service.global_path_required")


def unwrap(response):
    if response.get("c") != "0":
        code = response.get("c")
        safe = str(code) if re.fullmatch(r"[A-Z0-9_-]{1,80}", str(code), re.I) else "INVALID_RESPONSE"
        raise EditorError.coded("lux3d_service.request_failed", code=safe)
    if "d" not in response:
        raise EditorError.coded("lux3d_service.response_missing_data")
    return response["d"]


def request(spec, method, path, payload=None):
    check_region(spec)
    return unwrap(_api_request(spec, method, path, payload))


def task_id(value):
    if isinstance(value, str) and re.fullmatch(r"[1-9][0-9]{0,19}", value):
        value = int(value)
    if type(value) is not int or not 0 < value < 2**63:
        raise EditorError.coded("lux3d_service.task_id_invalid")
    return value


def prepare_payload(operation, payload, *, complete=False):
    if operation not in ROUTES:
        raise EditorError.coded("lux3d_service.unknown_operation")
    p = {k: v for k, v in payload.items() if v is not None and v != ""}
    common = {"remote_task_id", "quote_id", "quote_item"}
    fields = {
        "image-to-3d": {
            "img",
            "imgs",
            "version",
            "faceCount",
            "outputFormat",
            "enablePbr",
            "aiPredictSize",
            "customSize",
        },
        "multi-image-to-3d": {
            "img",
            "imgs",
            "version",
            "faceCount",
            "outputFormat",
            "enablePbr",
            "aiPredictSize",
            "customSize",
        },
        "text-to-3d": {
            "prompt",
            "style",
            "img",
            "version",
            "faceCount",
            "outputFormat",
            "enablePbr",
            "aiPredictSize",
            "customSize",
        },
        "material-transfer": {"img", "meshUrl", "version", "outputFormat", "aiPredictSize", "customSize"},
        "four-view": {"img", "prompt"},
        "multimodal-image": {"img", "prompt"},
        "multi-format-export": {"modelUrl", "outputFormat"},
    }[operation]
    if set(p) - fields - common:
        raise EditorError.coded("lux3d_service.unsupported_fields", fields=", ".join(sorted(set(p) - fields - common)))
    if "quote_item" in p and (
        not isinstance(p["quote_item"], str) or not re.fullmatch(r"[1-9][0-9]?", p["quote_item"])
    ):
        raise EditorError.coded("lux3d_service.quote_item_invalid")
    if "remote_task_id" in p:
        p["remote_task_id"] = task_id(p["remote_task_id"])
        return p
    if operation in ("image-to-3d", "multi-image-to-3d", "text-to-3d"):
        p.setdefault("version", "G1-Turbo")
        p.setdefault("outputFormat", ["glb"])
        if p["version"] not in ("G1", "G1-Turbo"):
            raise EditorError.coded("lux3d_service.version_invalid")
        if p["version"] == "G1" and "enablePbr" in p:
            raise EditorError.coded("lux3d_service.g1_no_enable_pbr")
        if p["version"] == "G1-Turbo" and "customSize" in p:
            raise EditorError.coded("lux3d_service.g1turbo_no_custom_size")
        allowed = {"zip", "glb", "ply"}
    elif operation == "material-transfer":
        p.setdefault("version", "v3.0-standard")
        if p["version"] != "v3.0-standard":
            raise EditorError.coded("lux3d_service.material_version_invalid")
        allowed = set(SLOTS[:5])
    else:
        allowed = set(SLOTS[2:])
    if "outputFormat" in p:
        f = p["outputFormat"]
        f = [f] if isinstance(f, str) else f
        if (
            not isinstance(f, list)
            or not f
            or any(not isinstance(x, str) or x not in allowed for x in f)
            or len(f) != len(set(f))
        ):
            raise EditorError.coded("lux3d_service.output_format_invalid")
        p["outputFormat"] = f
        if p.get("version") == "G1-Turbo" and f == ["ply"] and "enablePbr" in p:
            raise EditorError.coded("lux3d_service.ply_only_no_enable_pbr")
    if "faceCount" in p and (type(p["faceCount"]) is not int or not 10000 <= p["faceCount"] <= 300000):
        raise EditorError.coded("lux3d_service.face_count_range")
    for name in ("enablePbr", "aiPredictSize"):
        if name in p and type(p[name]) is not bool:
            raise EditorError.coded("lux3d_service.field_must_be_bool", field=name)
    if "customSize" in p and (
        type(p["customSize"]) not in (int, float) or not math.isfinite(p["customSize"]) or p["customSize"] <= 0
    ):
        raise EditorError.coded("lux3d_service.custom_size_invalid")
    if operation == "material-transfer" and p.get("aiPredictSize") and "customSize" in p:
        raise EditorError.coded("lux3d_service.auto_size_conflicts_custom_size")
    if "prompt" in p and (not isinstance(p["prompt"], str) or not p["prompt"].strip()):
        raise EditorError.coded("lux3d_service.prompt_empty")
    if "style" in p and p["style"] not in (
        "photorealistic",
        "cartoon",
        "anime",
        "hand_painted",
        "cyberpunk",
        "fantasy",
        "glass",
    ):
        raise EditorError.coded("lux3d_service.style_invalid")
    if "img" in p and "imgs" in p:
        raise EditorError.coded("lux3d_service.img_imgs_conflict")
    if "imgs" in p and (not isinstance(p["imgs"], list) or not 1 <= len(p["imgs"]) <= 32):
        raise EditorError.coded("lux3d_service.imgs_count_range")
    for url in [p[k] for k in ("img", "meshUrl", "modelUrl") if k in p] + p.get("imgs", []):
        if not isinstance(url, str):
            raise EditorError.coded("lux3d_service.asset_must_be_url")
        validate_url(url)
    if "meshUrl" in p and not urlsplit(p["meshUrl"]).path.lower().endswith(".glb"):
        raise EditorError.coded("lux3d_service.mesh_url_must_be_glb")
    if "modelUrl" in p:
        suffix = Path(urlsplit(p["modelUrl"]).path).suffix.lower()
        if suffix not in (".glb", ".zip"):
            raise EditorError.coded("lux3d_service.model_url_invalid_format")
        if suffix == ".glb" and not p.get("outputFormat"):
            raise EditorError.coded("lux3d_service.glb_conversion_needs_output_format")
    if complete:
        required = {
            "text-to-3d": ["prompt"],
            "material-transfer": ["img", "meshUrl"],
            "multi-format-export": ["modelUrl"],
        }.get(operation, [])
        if any(k not in p for k in required):
            raise EditorError.coded("lux3d_service.missing_inputs", fields=", ".join(required))
        if operation in ("image-to-3d", "multi-image-to-3d") and not (p.get("img") or p.get("imgs")):
            raise EditorError.coded("lux3d_service.image_input_required")
        if operation in ("four-view", "multimodal-image") and not (p.get("img") or p.get("prompt")):
            raise EditorError.coded("lux3d_service.image_or_prompt_required")
    return p


def input_payload(spec, operation, payload, inputs):
    from studio.adapters.lux3d_upload import upload

    p = prepare_payload(operation, payload)
    images = [f for f in inputs if Path(f).suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")]
    models = [f for f in inputs if Path(f).suffix.lower() in (".glb", ".zip")]
    if inputs:
        if len(images) + len(models) != len(inputs):
            raise EditorError.coded("lux3d_service.unsupported_input_types")
        if (
            operation
            in ("image-to-3d", "multi-image-to-3d", "four-view", "multimodal-image", "text-to-3d", "material-transfer")
            and images
        ):
            if "img" in p or "imgs" in p:
                raise EditorError.coded("lux3d_service.image_file_or_url_only")
            if operation != "multi-image-to-3d" and len(images) != 1:
                raise EditorError.coded("lux3d_service.single_reference_image_required")
            if len(images) > 32:
                raise EditorError.coded("lux3d_service.max_reference_images")
            urls = [upload(spec, f) for f in images]
            p["imgs" if operation == "multi-image-to-3d" else "img"] = (
                urls if operation == "multi-image-to-3d" else urls[0]
            )
        if models:
            field = {"material-transfer": "meshUrl", "multi-format-export": "modelUrl"}.get(operation)
            if not field or len(models) != 1 or field in p:
                raise EditorError.coded("lux3d_service.model_input_mismatch")
            p[field] = upload(spec, models[0])
    return prepare_payload(operation, p, complete=True)


def get_task(spec, remote_id):
    remote_id = task_id(remote_id)
    d = request(spec, "GET", "/lux3d/v1/generate/task/get?" + urlencode({"taskid": remote_id}))
    if (
        not isinstance(d, dict)
        or d.get("bizId") != "LUX_3D"
        or type(d.get("taskId")) is not int
        or d["taskId"] != remote_id
        or type(d.get("status")) is not int
        or d["status"] not in (0, 1, 3, 4, 6)
    ):
        raise EditorError.coded("lux3d_service.task_identity_invalid")
    return d


def output_urls(operation, payload, task):
    outputs = task.get("outputs")
    if not isinstance(outputs, list):
        raise EditorError.coded("lux3d_service.outputs_missing")
    values = []
    for item in outputs:
        if not isinstance(item, dict):
            raise EditorError.coded("lux3d_service.output_item_invalid")
        value = item.get("content", "")
        if not isinstance(value, str):
            raise EditorError.coded("lux3d_service.output_content_not_string")
        values.append(None if value.strip().lower() in ("", "not_requested", "null") else value.strip())
    if operation in ("four-view", "multimodal-image"):
        if len(values) != 1 or values[0] is None:
            raise EditorError.coded("lux3d_service.image_output_incomplete")
        urls = json.loads(values[0]) if operation == "four-view" else [values[0]]
        if not isinstance(urls, list) or len(urls) != (4 if operation == "four-view" else 1):
            raise EditorError.coded("lux3d_service.four_view_count_invalid")
        formats = ["view-" + str(i) + ".png" for i in range(len(urls))]
        values = urls
    elif operation == "material-transfer":
        formats = SLOTS[:5]
    elif operation == "multi-format-export":
        formats = SLOTS
    elif payload.get("version", "G1-Turbo") == "G1":
        formats = ["zip", "glb"] + (["ply"] if "ply" in payload.get("outputFormat", []) else [])
    else:
        formats = payload.get("outputFormat") or ["zip"]
    if len(formats) != len(values):
        raise EditorError.coded("lux3d_service.output_slots_mismatch")
    result = {fmt: url for fmt, url in zip(formats, values) if url}
    expected = (
        (["zip", "glb"] + [x for x in SLOTS[2:5] if x in payload.get("outputFormat", [])])
        if operation == "material-transfer"
        else (
            [x for x in SLOTS[2:] if x in payload.get("outputFormat", [])]
            + (["glb"] if urlsplit(payload.get("modelUrl", "")).path.endswith(".zip") else [])
        )
        if operation == "multi-format-export"
        else formats
    )
    if not result or not set(expected) <= result.keys():
        raise EditorError.coded("lux3d_service.missing_requested_outputs")
    for url in result.values():
        if not isinstance(url, str):
            raise EditorError.coded("lux3d_service.output_url_invalid")
        validate_url(url)
    return result


def inspect_file(path, fmt):
    if fmt == "glb":
        from studio.core.task_operations import glb_data

        glb_data(path)
    elif fmt in ("zip", "obj_zip", "fbx_zip", "usdz"):
        import zipfile

        with zipfile.ZipFile(path) as archive:
            if not archive.namelist() or sum(x.file_size for x in archive.infolist()) > 2 * 1024**3:
                raise EditorError.coded("lux3d_service.zip_empty_or_too_large")
            if archive.testzip():
                raise EditorError.coded("lux3d_service.zip_checksum_failed")
    elif fmt.endswith(".png"):
        from PIL import Image

        with Image.open(path) as image:
            suffix = {"PNG": ".png", "JPEG": ".jpg", "WEBP": ".webp"}.get(image.format)
            if not suffix:
                raise EditorError.coded("lux3d_service.image_format_invalid")
            image.verify()
        return suffix
    elif fmt == "ply":
        if not path.read_bytes()[:4].startswith(b"ply"):
            raise EditorError.coded("lux3d_service.ply_header_invalid")
    elif fmt == "stl":
        import trimesh

        if not len(trimesh.load(path, force="mesh").faces):
            raise EditorError.coded("lux3d_service.stl_no_mesh")
    elif fmt == "3mf":
        import zipfile

        with zipfile.ZipFile(path) as archive:
            if not any(n.endswith(".model") for n in archive.namelist()):
                raise EditorError.coded("lux3d_service.3mf_missing_model")


def run(w):
    from studio.adapters.services import download, _input_provenance, _sanitize_request_params

    service = w["params"]["service"]
    spec = service["spec"]
    op = service["operation"]
    root = Path(w["output"]).parent
    receipt = root / "service-receipt.json"
    ledger = json.loads(receipt.read_text()) if receipt.exists() else {}

    def save(**changes):
        ledger.update(changes)
        _atomic(receipt, json.dumps(ledger, ensure_ascii=False, allow_nan=False).encode())

    p = service["payload"]
    if not ledger.get("remote_id"):
        if ledger.get("submission_attempted"):
            raise EditorError.coded("lux3d_service.previous_submission_ambiguous")
        if p.get("remote_task_id"):
            save(
                remote_id=str(task_id(p["remote_task_id"])),
                provider=service["provider"],
                operation=op,
                resumed_external=True,
                adapter=spec.get("adapter"),
                model=p.get("version"),
                request_params=_sanitize_request_params(service["payload"]),
            )
            p = {k: v for k, v in p.items() if k != "remote_task_id"}
            save(request_payload=p)
        else:
            if p.get("quote_id"):
                from studio.adapters.lux3d_commerce import quoted_payload

                p = quoted_payload(spec, op, p, w["inputs"])
            else:
                p = input_payload(spec, op, p, w["inputs"])
            save(
                provider=service["provider"],
                operation=op,
                submission_attempted=True,
                request_payload=p,
                output_formats=p.get("outputFormat"),
                submitted_at=time.time(),
                adapter=spec.get("adapter"),
                model=p.get("version"),
                request_params=_sanitize_request_params(service["payload"]),
            )
            remote = request(spec, "POST", ROUTES[op], p)
            save(remote_id=str(task_id(remote)))
    p = ledger["request_payload"]
    remote_id = ledger["remote_id"]
    while True:
        task = get_task(spec, remote_id)
        status = task["status"]
        save(status=status, polled_at=time.time())
        print(json.dumps({"remote_id": remote_id, "status": status}), flush=True)
        if status in (4, 6):
            raise EditorError.coded("lux3d_service.remote_task_failed", status=status)
        if status == 3:
            break
        time.sleep(max(1, min(30, float(spec.get("poll_interval", 10)))))
    urls = output_urls(op, p, task)
    out = Path(w["output"])
    artifacts = []
    for fmt, url in urls.items():
        name = fmt if fmt.endswith(".png") else "model." + fmt.replace("_zip", ".zip")
        path = out / name
        download(url, path)
        suffix = inspect_file(path, fmt)
        if suffix and path.suffix != suffix:
            target = path.with_suffix(suffix)
            path.replace(target)
            path = target
            name = path.name
        artifacts.append(
            {
                "file": name,
                "format": fmt,
                "bytes": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    report = {
        "provider": service["provider"],
        "region": spec["region"],
        "operation": op,
        "remote_id": remote_id,
        "status": 3,
        "artifacts": artifacts,
        "completed_at": time.time(),
        "visual_review": "pending",
        "adapter": ledger.get("adapter"),
        "model": ledger.get("model"),
        "request_params": ledger.get("request_params"),
        "input_sha256": _input_provenance(w["inputs"]),
        "submitted_at": ledger.get("submitted_at"),
    }
    _atomic(out / "service.json", json.dumps(report, ensure_ascii=False, indent=2).encode())
    save(received_at=time.time())


class _Lux3DAdapter(BaseAdapter):
    def operation_catalog(self, spec, item, *, internal_http):
        check_region(spec)
        return {
            "region": spec["region"],
            "operation_templates": operation_catalog(),
            "timeout_seconds": 1800,
            "setup_message": render("lux3d_service.setup_message"),
        }

    def prepare_payload(self, spec, operation, payload):
        check_region(spec)
        p = prepare_payload(operation, payload)
        # Every ROUTES operation spends Lux3D credits (image/multi-image/text-to-3d,
        # material-transfer, four-view, multimodal-image, multi-format-export all hit
        # a billed .../task/create route quotable via lux3d_commerce.quote_plan) — so
        # the "quote before you pay" rule below applies uniformly, with no free op.
        # This is the server-side half of that rule: studio/web/tasks.js's `luxQuote`
        # check only gates the UI, so an MCP/API caller going straight to
        # studio_task must be blocked here too, unless it is recovering an already
        # -submitted remote task (remote_task_id, never a new spend) or the spec
        # opts out via the declarative `allow_unquoted` flag a user can only set in
        # their own services.json entry (BUILTINS never sets it, so the gate is on
        # by default).
        if "remote_task_id" not in p and not p.get("quote_id") and not spec.get("allow_unquoted"):
            raise EditorError.coded("lux3d_service.quote_required")
        return p

    def run(self, workbench):
        run(workbench)

    def probe(self, spec):
        from studio.adapters.lux3d_commerce import balance

        account = balance(spec)
        return {
            "account": account,
            "generation_tested": False,
            "message": render("lux3d_service.probe_ok", credits=account["availableCredits"]),
        }

    def on_save(self, spec, template_spec, old):
        # A region change (cn <-> international) must not silently reuse the
        # other region's credential; users add a new connection instead.
        if old.get("region") and old["region"] != template_spec["region"]:
            raise EditorError.coded("lux3d_service.region_change_requires_new_connection")
        check_region(spec)


register("lux3d")(_Lux3DAdapter())
