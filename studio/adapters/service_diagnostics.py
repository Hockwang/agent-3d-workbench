"""Read-only connectivity checks for the optional, key-gated Assembly Workflow
adapter (`assembly_service.py`). Used before a task is ever submitted, to tell
"network unreachable" apart from "gateway needs auth" apart from "auth rejected",
without echoing response bodies or credentials back to the caller."""

from __future__ import annotations
import os
import re
import uuid

from studio.core.editor import EditorError
from studio.adapters.services import credential_refs, request
from studio.i18n import render


def probe_assembly(spec, *, use_credentials=False):
    spec = dict(spec)
    result = {
        "network_reachable": False,
        "authentication": "not_checked",
        "generation": "not_tested",
        "credentials_sent": False,
        "transport": spec.get("transport", "default"),
    }
    if spec.get("adapter") != "assembly":
        raise EditorError.coded("service_diagnostics.assembly_only")
    if use_credentials:
        # oneapiAppKey is a downstream inference key, not gateway authentication.
        spec.pop("oneapi_appkey_env", None)
        refs = credential_refs(spec)
        if spec.get("enabled", True) is False or not refs or any(not os.environ.get(x) for x in refs):
            result.update(authentication="not_configured", detail=render("service_diagnostics.detail_not_configured"))
            return result
    else:
        spec.update(key_env=None, headers_env={}, allow_insecure_http=False)
        spec.pop("oneapi_appkey_env", None)
    endpoint = spec.get("workflow_path", "/cubely/v1/workflow")
    if endpoint not in ("/cubely/v1/workflow", "/cubely/v1/api/workflow"):
        raise EditorError.coded("service_diagnostics.invalid_workflow_path")
    try:
        # A fresh, nonexistent ID tests the history contract without submitting work
        # or reading another user's asset. Some beta deployments lack /assets.
        response = request(
            spec,
            "GET",
            endpoint + "/history?promptId=" + uuid.uuid4().hex + "&nodeName=assembly_agent_cos_upload",
            timeout=15,
        )
    except RuntimeError as exc:
        # request() produces bounded, fixed messages; never include a remote body.
        # Matched on "HTTP {code}" rather than the localized sentence around it,
        # since transport.http_error's rendered text now varies by language
        # (studio.i18n) while this substring stays fixed in every language.
        http = re.search(r"HTTP (\d{3})", str(exc))
        result.update(
            network_reachable=bool(http),
            credentials_sent=use_credentials,
            detail=("HTTP " + http[1]) if http else render("service_diagnostics.detail_connection_or_json_error"),
        )
        if http and http[1] in ("401", "403"):
            result["authentication"] = "rejected" if use_credentials else "required"
        return result
    result.update(network_reachable=True, credentials_sent=use_credentials)
    code = str(response.get("c", ""))
    result["business_code"] = code if re.fullmatch(r"-?\d{1,10}", code) else "unknown"
    message = str(response.get("m", "")).lower()
    if "appkey missing" in message:
        result.update(authentication="required", detail=render("service_diagnostics.detail_gateway_missing_auth"))
    elif code in ("0", "10001", "10002") and use_credentials:
        result.update(
            authentication="accepted_read_only", detail=render("service_diagnostics.detail_accepted_read_only")
        )
    elif code != "0":
        result.update(authentication="unverified", detail=render("service_diagnostics.detail_unverified_error"))
    return result
