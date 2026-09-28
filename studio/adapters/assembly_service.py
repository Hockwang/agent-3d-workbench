"""Assembly Workflow OpenAPI adapter; CF 81502019948 version 39.

The API processes existing remote models, or generates motion. It is not a
text/image-to-mesh API. Auth is deployment-specific and configured by reference.
Registers itself as the `assembly` adapter.
"""

from pathlib import Path, PurePosixPath
import ipaddress
import json
import os
import re
import shutil
import stat
import tempfile
import time
import urllib.parse
import zipfile

from studio.core.editor import EditorError, _atomic
from studio.adapters.registry import BaseAdapter, register
from studio.i18n import render


OPERATIONS = {
    "assemble": (
        "workflow_assembly_prod",
        "assembly_agent_cos_upload",
        "assembly_service.op_assemble_title",
        {"meshUrl": "", "prompt": "", "meshUpAxis": "y_up", "cutBackend": ""},
    ),
    "segment": (
        "workflow_assembly_seg_prod",
        "AssemblyAgentSegmentedGLBExport",
        "assembly_service.op_segment_title",
        {"meshUrl": "", "meshUpAxis": "y_up", "cutBackend": ""},
    ),
    "rig-glb": (
        "workflow_rig_glb_prod",
        "AssemblyAgentRiggedGLBOutput",
        "assembly_service.op_rig_glb_title",
        {"meshUrl": "", "meshUpAxis": "y_up", "rigBackend": "auto"},
    ),
    "rig": (
        "workflow_rig_prod",
        "rig_package_zip",
        "assembly_service.op_rig_title",
        {"meshUrl": "", "meshUpAxis": "y_up", "rigBackend": "auto"},
    ),
    "motion": (
        "workflow_motion_generate_prod",
        "AssemblyAgentKimodoMotionGenerate",
        "assembly_service.op_motion_title",
        {
            "prompt": "",
            "cfgType": "regular",
            "cfgWeight": "5.0",
            "duration": "5.0",
            "numSamples": 1,
            "exportBvh": True,
            "returnCosUrl": True,
        },
    ),
}
# Title (OPERATIONS[key][2]) and these label values are message-catalog codes,
# rendered at catalog-build time in `operation_catalog()` below — not literal text.
LABEL_CODES = {
    "meshUrl": "assembly_service.label_mesh_url",
    "prompt": "assembly_service.label_prompt",
    "meshUpAxis": "assembly_service.label_mesh_up_axis",
    "cutBackend": "assembly_service.label_cut_backend",
    "rigBackend": "assembly_service.label_rig_backend",
    "cfgType": "assembly_service.label_cfg_type",
    "cfgWeight": "assembly_service.label_cfg_weight",
    "duration": "assembly_service.label_duration",
    "numSamples": "assembly_service.label_num_samples",
    "exportBvh": "assembly_service.label_export_bvh",
    "returnCosUrl": "assembly_service.label_return_cos_url",
}
# Values are message-catalog codes for the display label, rendered at
# catalog-build time in `operation_catalog()` below; the dict keys are the
# literal values the UI submits and stay verbatim (see `prepare_payload()`'s
# `CHOICES[key]` membership checks).
CHOICES = {
    "meshUpAxis": {
        "y_up": "assembly_service.choice_mesh_up_axis_y_up",
        "z_up": "assembly_service.choice_mesh_up_axis_z_up",
    },
    "cutBackend": {
        "": "assembly_service.choice_cut_backend_default",
        "cube": "assembly_service.choice_cut_backend_cube",
    },
    "rigBackend": {
        "auto": "assembly_service.choice_rig_backend_auto",
        "puppeteer": "assembly_service.choice_rig_backend_puppeteer",
        "skintokens": "assembly_service.choice_rig_backend_skintokens",
    },
    "cfgType": {
        "regular": "assembly_service.choice_cfg_type_regular",
        "separated": "assembly_service.choice_cfg_type_separated",
    },
}
ALIASES = {
    "workflow_template_id": "workflowTemplateId",
    "mesh_url": "meshUrl",
    "glburl": "meshUrl",
    "glb": "meshUrl",
    "glb_url": "meshUrl",
    "meshurl": "meshUrl",
    "imageurl": "imageUrl",
    "image_url": "imageUrl",
    "image_urls": "imageUrls",
    "mesh_up_axis": "meshUpAxis",
    "cut_backend": "cutBackend",
    "cube_parts": "cubeParts",
    "rig_backend": "rigBackend",
    "source_channel": "sourceChannel",
    "source_type": "sourceType",
}
COMMON = {"workflowTemplateId", "sourceChannel", "sourceType"}
MODEL_FIELDS = {
    "meshUrl",
    "imageUrl",
    "imageUrls",
    "meshUpAxis",
    "prompt",
    "model",
    "cutBackend",
    "cubeParts",
    "rigBackend",
    "from",
}
MOTION_FIELDS = {
    "prompt",
    "cfgType",
    "cfgWeight",
    "model",
    "duration",
    "numSamples",
    "diffusionSteps",
    "numTransitionFrames",
    "seed",
    "postprocess",
    "exportBvh",
    "returnCosUrl",
    "outputFilename",
    "inputUrl",
    "inputCosUrl",
    "requestUrl",
    "constraintsJson",
    "constraintsUrl",
    "constraintsCosUrl",
    "outputUrl",
    "outputCosUrl",
    "outputKey",
    "timeoutSeconds",
    "filenamePrefix",
}
SUFFIXES = {
    ".glb",
    ".gltf",
    ".bin",
    ".stl",
    ".obj",
    ".mtl",
    ".urdf",
    ".bvh",
    ".fbx",
    ".blend",
    ".json",
    ".npy",
    ".npz",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".usd",
    ".usda",
    ".usdz",
    ".zip",
}
OUTPUT_KEYS = {
    "url",
    "usdurl",
    "gltfurl",
    "glburl",
    "riggedglburl",
    "motionurl",
    "cosurl",
    "motionresultjson",
    "segmentedglb",
    "faceidsnpy",
    "rigpackagezip",
    "assemblysvinput",
    "urdfpackagezip",
    "metadatajson",
}


def operation_catalog(operations):
    labels = {key: render(code) for key, code in LABEL_CODES.items()}
    choices = {field: {value: render(code) for value, code in mapping.items()} for field, mapping in CHOICES.items()}
    return [
        {
            "id": key,
            "title": render(OPERATIONS[key][2]),
            "params": dict(OPERATIONS[key][3]),
            "labels": labels,
            "choices": choices,
            "optional_params": ["cutBackend"],
            "description": render(
                "assembly_service.op_motion_description"
                if key == "motion"
                else "assembly_service.op_default_description"
            ),
        }
        for key in operations
        if key in OPERATIONS
    ]


def remote_url(value):
    if not isinstance(value, str) or len(value) > 16384:
        raise EditorError.coded("assembly_service.remote_url_required")
    p = urllib.parse.urlsplit(value)
    if p.scheme not in ("http", "https") or not p.hostname or p.username or p.password or p.fragment:
        raise EditorError.coded("assembly_service.remote_url_no_credentials")
    if p.hostname.lower() in ("localhost", "localhost.localdomain"):
        raise EditorError.coded("assembly_service.remote_url_no_localhost")
    try:
        address = ipaddress.ip_address(p.hostname)
    except ValueError:
        address = None
    if address and (address.is_loopback or address.is_unspecified or address.is_link_local):
        raise EditorError.coded("assembly_service.remote_url_no_link_local")
    return value


def prepare_payload(operation, payload):
    if operation not in OPERATIONS:
        raise EditorError.coded("assembly_service.unknown_operation")
    p = {}
    for key, value in payload.items():
        normalized = ALIASES.get(key, key)
        if normalized in p and p[normalized] != value:
            raise EditorError.coded("assembly_service.duplicate_field_conflict", field=normalized)
        p[normalized] = value
    allowed = COMMON | (MOTION_FIELDS if operation == "motion" else MODEL_FIELDS)
    unknown = set(p) - allowed
    if unknown:
        raise EditorError.coded("assembly_service.unsupported_params", fields=", ".join(sorted(unknown)))
    expected = OPERATIONS[operation][0]
    if p.get("workflowTemplateId", expected) != expected:
        raise EditorError.coded("assembly_service.workflow_template_mismatch")
    p["workflowTemplateId"] = expected
    p.setdefault("sourceType", "codex-3d-studio")
    if operation == "motion":
        if not isinstance(p.get("prompt"), str) or not p["prompt"].strip():
            raise EditorError.coded("assembly_service.motion_requires_prompt")
        p.setdefault("cfgType", "regular")
        p.setdefault("cfgWeight", "5.0")
        p.setdefault("exportBvh", True)
        p.setdefault("returnCosUrl", True)
        if p["cfgType"] not in ("regular", "separated") or not str(p["cfgWeight"]).strip():
            raise EditorError.coded("assembly_service.invalid_cfg_type_or_weight")
        for key in ("duration", "cfgWeight"):
            if key in p:
                try:
                    if isinstance(p[key], bool):
                        raise ValueError()
                    value = float(p[key])
                    if not 0 < value < 1e6:
                        raise ValueError()
                except (ValueError, TypeError):
                    raise EditorError.coded("assembly_service.field_must_be_positive_finite", field=key) from None
                p[key] = str(p[key])
        for key in ("numSamples", "diffusionSteps", "timeoutSeconds"):
            if key in p and (type(p[key]) is not int or p[key] < 1):
                raise EditorError.coded("assembly_service.field_must_be_positive_integer", field=key)
        for key in ("postprocess", "exportBvh", "returnCosUrl"):
            if key in p and type(p[key]) is not bool:
                raise EditorError.coded("assembly_service.field_must_be_bool", field=key)
        for key in (
            "inputUrl",
            "inputCosUrl",
            "requestUrl",
            "constraintsUrl",
            "constraintsCosUrl",
            "outputUrl",
            "outputCosUrl",
        ):
            if p.get(key):
                remote_url(p[key])
                if key in ("inputUrl", "inputCosUrl") and urllib.parse.urlsplit(p[key]).path.lower().endswith(".glb"):
                    raise EditorError.coded("assembly_service.motion_input_url_not_glb")
    else:
        if p.get("meshUrl"):
            remote_url(p["meshUrl"])
        elif operation not in ("assemble", "segment") or not p.get("from"):
            raise EditorError.coded("assembly_service.mesh_url_required")
        if "from" in p:
            start = p["from"]
            if (
                not isinstance(start, dict)
                or set(start) != {"fromNodeType", "fromNodeInput"}
                or start["fromNodeType"] != "AssemblyAgentSegmentedGLBExport"
            ):
                raise EditorError.coded("assembly_service.from_node_type_unsupported")
            fields = start["fromNodeInput"]
            if not isinstance(fields, dict) or set(fields) - {"segmentedGlb", "faceIdsNpy", "filenamePrefix"}:
                raise EditorError.coded("assembly_service.from_node_input_invalid")
            remote_url(fields.get("segmentedGlb"))
            if fields.get("faceIdsNpy"):
                remote_url(fields["faceIdsNpy"])
        if operation == "assemble" and (not isinstance(p.get("prompt"), str) or not p["prompt"].strip()):
            raise EditorError.coded("assembly_service.assemble_requires_prompt")
        if p.get("imageUrl"):
            remote_url(p["imageUrl"])
        if "imageUrls" in p:
            if not isinstance(p["imageUrls"], dict):
                raise EditorError.coded("assembly_service.image_urls_must_be_mapping")
            for url in p["imageUrls"].values():
                remote_url(url)
        p.setdefault("meshUpAxis", "y_up")
        for key in ("meshUpAxis", "cutBackend", "rigBackend"):
            if key in p and p[key] not in CHOICES[key]:
                raise EditorError.coded("assembly_service.invalid_choice_field", field=key)
        if not p.get("cutBackend"):
            p.pop("cutBackend", None)
        if "cubeParts" in p:
            parts = p["cubeParts"]
            if isinstance(parts, str):
                parts = [x.strip() for x in re.split(r"[,\n]", parts) if x.strip()]
            if (
                not isinstance(parts, list)
                or not 1 <= len(parts) <= 8
                or any(not isinstance(x, str) or not x.strip() for x in parts)
            ):
                raise EditorError.coded("assembly_service.cube_parts_invalid")
            p["cubeParts"] = parts
    return p


def safe_extract(path, destination):
    """Keep the original ZIP; extract only bounded model data, never scripts/HTML."""
    with zipfile.ZipFile(path) as package:
        entries = package.infolist()
        if len(entries) > 4096 or sum(x.file_size for x in entries) > 1024**3:
            raise RuntimeError(render("assembly_service.zip_extract_too_large"))
        seen = set()
        accepted = []
        for info in entries:
            p = PurePosixPath(info.filename)
            if (
                not info.filename
                or "\\" in info.filename
                or ":" in info.filename
                or p.is_absolute()
                or ".." in p.parts
                or stat.S_ISLNK(info.external_attr >> 16)
                or info.flag_bits & 1
            ):
                raise RuntimeError(render("assembly_service.zip_unsafe_entry"))
            if info.is_dir():
                continue
            identity = p.as_posix().casefold()
            if identity in seen:
                raise RuntimeError(render("assembly_service.zip_name_conflict"))
            seen.add(identity)
            if p.suffix.lower() not in SUFFIXES or p.suffix.lower() == ".zip":
                continue
            accepted.append((info, p))
        # A corrupt or malicious later entry must not leave half an asset tree.
        with tempfile.TemporaryDirectory(prefix=".assembly-extract-", dir=destination.parent) as temporary:
            staged = Path(temporary) / "files"
            staged.mkdir()
            for info, p in accepted:
                target = staged.joinpath(*p.parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                with package.open(info) as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output, length=1024 * 1024)
            if destination.is_symlink():
                raise RuntimeError(render("assembly_service.output_dir_symlink_forbidden"))
            if destination.exists():
                shutil.rmtree(destination)
            staged.replace(destination)


def artifact_urls(data, operation):
    found = []

    def collect(value, label):
        if isinstance(value, str) and value.startswith(("https://", "http://")):
            if value not in [url for _, url in found]:
                found.append((label, value))
        elif isinstance(value, dict):
            for key, item in value.items():
                collect(item, str(key))
        elif isinstance(value, list):
            for i, item in enumerate(value):
                collect(item, f"{label}-{i}")

    collect(data.get("value"), "primary")
    output = data.get("output") or {}
    if not isinstance(output, dict):
        raise RuntimeError(render("assembly_service.output_must_be_object"))
    for key, value in output.items():
        if re.sub("[^a-z]", "", key.lower()) in OUTPUT_KEYS:
            if key == "motionResultJson" and isinstance(value, str) and value.startswith("{"):
                try:
                    value = json.loads(value)
                except ValueError:
                    continue
            collect(value, key)
    result = []
    for index, (label, url) in enumerate(found):
        suffix = Path(urllib.parse.urlsplit(url).path).suffix.lower()
        if not suffix:
            suffix = ".glb" if operation in ("segment", "rig-glb") else ".zip"
        if suffix not in SUFFIXES:
            continue
        role = re.sub("[^A-Za-z0-9_-]", "-", label)[:60] or "asset"
        result.append((f"{index:02d}-{role}{suffix}", url))
    return result


def run(workbench):
    from studio.adapters.services import request, download, _input_provenance, _sanitize_request_params

    data = workbench["params"]["service"]
    spec = data["spec"]
    operation = data["operation"]
    output = Path(workbench["output"])
    receipt = output.parent / "service-receipt.json"
    ledger = json.loads(receipt.read_text()) if receipt.exists() else {}
    endpoint = spec.get("workflow_path", "/cubely/v1/workflow")
    if endpoint not in ("/cubely/v1/workflow", "/cubely/v1/api/workflow"):
        raise RuntimeError(render("assembly_service.workflow_path_invalid"))

    def save(**updates):
        ledger.update(updates)
        _atomic(receipt, json.dumps(ledger).encode())

    if not ledger.get("remote_id"):
        if ledger.get("submission_attempted"):
            raise RuntimeError(render("assembly_service.submission_ambiguous_no_resubmit"))
        payload = prepare_payload(operation, data["payload"])
        model = payload.get("workflowTemplateId")
        request_params = _sanitize_request_params(payload)
        if spec.get("oneapi_appkey_env"):
            key = os.environ.get(spec["oneapi_appkey_env"])
            if not key:
                raise RuntimeError(render("assembly_service.oneapi_appkey_env_not_configured"))
            # Inject only at send time. Neither task params nor receipts contain it.
            payload["oneapiAppKey"] = key
        save(
            provider=data["provider"],
            operation=operation,
            submission_attempted=True,
            submitted_at=time.time(),
            adapter=spec.get("adapter"),
            model=model,
            request_params=request_params,
        )
        response = request(spec, "POST", endpoint, payload)
        d = response.get("d") or {}
        remote_id = d.get("promptId") if isinstance(d, dict) else None
        if (
            str(response.get("c")) != "0"
            or not isinstance(remote_id, str)
            or not re.fullmatch(r"[A-Za-z0-9_.-]{1,200}", remote_id)
        ):
            raise RuntimeError(render("assembly_service.submit_missing_prompt_id"))
        save(remote_id=remote_id)
        if d.get("nodeErrors") or d.get("error"):
            raise RuntimeError(render("assembly_service.submit_node_errors"))
    remote_id = ledger["remote_id"]
    query = urllib.parse.urlencode({"promptId": remote_id, "nodeName": OPERATIONS[operation][1]})
    delay = max(0, min(30, float(spec.get("initial_poll_delay", 30))))
    time.sleep(max(0, delay - (time.time() - ledger.get("submitted_at", 0))))
    missing = 0
    for _ in range(max(1, min(70, int(spec.get("max_polls", 70))))):
        response = request(spec, "GET", endpoint + "/history?" + query)
        code = str(response.get("c"))
        status = {"0": "succeeded", "10001": "running", "10002": "not_found", "-1": "failed"}.get(code, "unknown")
        save(status=status, code=code, polled_at=time.time())
        print(json.dumps({"remote_id": remote_id, "status": status, "code": code}), flush=True)
        if code == "0":
            break
        if code not in ("10001", "10002"):
            raise RuntimeError(render("assembly_service.query_failed_or_unknown_status"))
        missing = missing + 1 if code == "10002" else 0
        if missing >= 3:
            raise RuntimeError(render("assembly_service.repeated_not_found"))
        time.sleep(max(1, min(15, float(spec.get("poll_interval", 10)))))
    else:
        raise RuntimeError(render("assembly_service.wait_timeout"))
    d = response.get("d")
    if not isinstance(d, dict):
        raise RuntimeError(render("assembly_service.success_missing_result_object"))
    urls = artifact_urls(d, operation)
    if not urls:
        raise RuntimeError(render("assembly_service.success_no_downloadable_artifact"))
    received = []
    for name, url in urls:
        target = output / name
        download(url, target)
        if target.suffix == ".zip":
            if not zipfile.is_zipfile(target):
                raise RuntimeError(render("assembly_service.result_not_valid_zip"))
            safe_extract(target, output / (target.stem + "-files"))
        received.append(name)
    (output / "service.json").write_text(
        json.dumps(
            {
                "provider": data["provider"],
                "operation": operation,
                "remote_id": remote_id,
                "status": "succeeded",
                "cost": None,
                "cost_unit": None,
                "cost_note": render("assembly_service.cost_note_billing_unknown"),
                "received_at": time.time(),
                "files": received,
                "contract": "CF 81502019948 v39",
                "adapter": ledger.get("adapter"),
                "model": ledger.get("model"),
                "request_params": ledger.get("request_params"),
                "input_sha256": _input_provenance(workbench["inputs"]),
                "submitted_at": ledger.get("submitted_at"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


class _AssemblyAdapter(BaseAdapter):
    def operation_catalog(self, spec, item, *, internal_http):
        extra = {
            "input_mode": "remote_urls",
            "operation_templates": operation_catalog(item["operations"]),
            "timeout_seconds": 1800,
            "setup_message": render("assembly_service.setup_message_default"),
        }
        if internal_http and not spec.get("allow_insecure_http", False):
            extra["setup_message"] = render("assembly_service.setup_message_internal_http_insecure")
        return extra

    def prepare_payload(self, spec, operation, payload):
        return prepare_payload(operation, payload)

    def run(self, workbench):
        run(workbench)

    # `probe` and `on_save` keep BaseAdapter's defaults: Assembly has no read-only
    # connection test today (see service_diagnostics.probe_assembly instead), and
    # no extra save-time validation.


register("assembly")(_AssemblyAdapter())
