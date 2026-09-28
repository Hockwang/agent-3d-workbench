"""BYOK asynchronous services: the public façade over every hosted-service adapter.

This module owns `services.json`/BUILTINS configuration, credential-safety checks,
and the generic "submit once, poll by id, download named artifacts" REST-job loop
(`run_generic_job`, used by Meshy, Tripo, and any custom provider-agnostic entry).
Provider-specific wire protocols live in their own adapter modules and register
themselves in `studio.adapters.registry`; this module dispatches to them through
`registry.adapter_for(spec)` instead of branching on the adapter string itself.

Contracts are public APIs, never vendor desktop code. POST is attempted once. An
ambiguous submission remains ambiguous; recovery only polls a persisted remote ID.
Credentials and signed result URLs are not artifacts.
"""

from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import re
import time

# Re-exported so `services.urllib.request.build_opener` etc. remain patchable:
# transport.request() calls through the same shared `urllib` package object.
import urllib.error
import urllib.parse
import urllib.request  # noqa: F401 - re-exported: tests patch services.urllib.request

from studio.core.editor import EditorError, _atomic
from studio.i18n import render
from studio.adapters.registry import BaseAdapter, adapter_for, register
from studio.adapters.transport import (
    NoRedirect,  # noqa: F401 - re-exported facade API
    credential_refs,
    download,
    field,
    file_data,  # noqa: F401 - re-exported facade API
    files,
    request,
    service_transport,
    validate_internal_origin,  # noqa: F401 - re-exported facade API
    validate_payload,
    validate_url,  # noqa: F401 - re-exported facade API
)
from studio.adapters.lux3d_service import ROUTES as LUX3D_OPERATIONS
from studio.adapters.meshy import OPERATIONS as MESHY_OPERATIONS
from studio.adapters.tripo import OPERATIONS as TRIPO_OPERATIONS
from studio.adapters.tripo import upload as tripo_upload  # noqa: F401 - re-exported facade API

# `title` values below are message-catalog codes, not literal display text (the
# `lux3d_service.TITLE_CODES` pattern): a spec's title is only ever turned into
# display text by `render()` at the point `_catalog_entry()`/`catalog()` build
# the payload, never here at BUILTINS-definition time, since the language in
# effect is a per-request thing `render()` reads from context. A custom title
# a user typed into services.json/a connection is plain text, not a code, and
# `render()` on an unregistered code just returns it unchanged (see i18n.py).
BUILTINS = {
    "lux3d": {
        "title": "services.title_lux3d",
        "base_url": "https://api.aholo3d.cn",
        "adapter": "lux3d",
        "region": "cn",
        "key_env": "LUX3D_CN_API_KEY",
        "requires_key": True,
        "operations": LUX3D_OPERATIONS,
        "poll_interval": 10,
        "default_timeout_seconds": 1800,
    },
    "lux3d-global": {
        "title": "services.title_lux3d_global",
        "base_url": "https://api.aholo3d.com/global",
        "adapter": "lux3d",
        "region": "international",
        "key_env": "LUX3D_GLOBAL_API_KEY",
        "requires_key": True,
        "operations": LUX3D_OPERATIONS,
        "poll_interval": 10,
        "default_timeout_seconds": 1800,
    },
    "seed3d": {
        "title": "services.title_seed3d",
        "base_url": "",
        "requires_base_url": True,
        "adapter": "seed3d-chat",
        "key_env": "SEED3D_API_KEY",
        "operations": {"image-to-3d": "/chat/completions"},
        "default_timeout_seconds": 1800,
    },
    "hunyuan": {
        "title": "services.title_hunyuan",
        "base_url": "",
        "requires_base_url": True,
        "adapter": "hunyuan-responses",
        "key_env": "HUNYUAN_API_KEY",
        "operations": {key: "/responses" for key in ("image-to-3d", "text-to-3d", "segment")},
        "poll_interval": 5,
        "default_timeout_seconds": 1800,
    },
    "assembly": {
        "title": "services.title_assembly",
        "base_url": "https://api-beta.aholo3d.cn",
        "adapter": "assembly",
        "enabled": False,
        "key_env": None,
        "headers_env": {},
        "operations": {key: key for key in ("assemble", "segment", "rig-glb", "rig", "motion")},
        "poll_interval": 10,
        "initial_poll_delay": 30,
        "max_polls": 70,
        # Assembly only accepts remotely reachable URLs (see `assembly_service.py`'s
        # `remote_url()`); nothing is auto-uploaded, so a local `inputs` path can
        # never be honored for this adapter, not just "for this deployment".
        "local_inputs_allowed": False,
        "default_timeout_seconds": 1800,
    },
    "meshy": {
        "title": "services.title_meshy",
        "base_url": "https://api.meshy.ai",
        "key_env": "MESHY_API_KEY",
        "adapter": "meshy",
        "operations": MESHY_OPERATIONS,
    },
    "tripo": {
        "title": "services.title_tripo",
        "base_url": "https://api.tripo3d.ai/v2/openapi",
        "key_env": "TRIPO_API_KEY",
        "adapter": "tripo",
        "operations": TRIPO_OPERATIONS,
    },
}

# Hints shown when a `requires_base_url` provider (below) has none configured yet.
_BASE_URL_HINTS = {
    "hunyuan-responses": "any OpenAI-compatible gateway that serves the Hunyuan 3D models",
    "seed3d-chat": "any OpenAI-compatible gateway that serves the Seed3D image-to-3D model",
}


def require_base_url(provider, spec):
    """`hunyuan`/`seed3d` ship with no default endpoint (see BUILTINS): they speak an
    OpenAI-compatible gateway protocol, not a specific vendor's API, so there is no
    single correct default to hard-code. Raise a specific, actionable message before
    falling through to `service_transport`'s generic "no base_url" rejection."""
    if spec.get("requires_base_url") and not spec.get("base_url"):
        hint = _BASE_URL_HINTS.get(spec.get("adapter"), "an OpenAI-compatible gateway")
        raise EditorError.coded("services.base_url_required", provider=provider, hint=hint)


_POLICY_DEFAULT_KEYS = ("local_inputs_allowed", "default_timeout_seconds")


def _backfill_policy_defaults(spec):
    """A BYOK connection profile frozen by `service_connections.save()` (or a bare
    `services.json` entry with a custom name) before `local_inputs_allowed`/
    `default_timeout_seconds` existed in `BUILTINS` carries neither key on disk, and
    never gets a fresh copy of them just by this module gaining new BUILTINS fields --
    `save()` only re-merges `BUILTINS[template]` in the next time that particular
    profile is edited. Backfill both here, at read time, from the BUILTINS entry the
    profile names (`connection_template`) or, absent one, the first BUILTINS entry
    sharing the same `adapter` id (e.g. any custom-named `adapter: "assembly"` entry
    gets `assembly`'s `local_inputs_allowed: False`/`1800`). A key already present on
    `spec` — including one explicitly set to the same value as a BUILTINS default --
    is never overwritten."""
    if all(key in spec for key in _POLICY_DEFAULT_KEYS):
        return spec
    template = spec.get("connection_template")
    source = (
        BUILTINS.get(template)
        if template
        else next((b for b in BUILTINS.values() if b.get("adapter") == spec.get("adapter")), None)
    )
    if not source:
        return spec
    return {**{k: source[k] for k in _POLICY_DEFAULT_KEYS if k in source}, **spec}


def config(*, include_connections=True):
    providers = json.loads(json.dumps(BUILTINS))
    path = Path(os.environ.get("WORKBENCH_SERVICE_CONFIG", "~/.config/codex-3d/services.json")).expanduser()
    if path.is_file():
        data = json.loads(path.read_text())
        if not isinstance(data, dict):
            raise EditorError.coded("services.config_must_be_object")
        for name, spec in data.items():
            if not isinstance(spec, dict):
                raise EditorError.coded("services.each_provider_config_must_be_object")
            providers[name] = {**providers.get(name, {}), **spec}
    if include_connections:
        from studio.adapters.service_connections import read_store

        providers.update(read_store()["profiles"])
    return {name: _backfill_policy_defaults(spec) for name, spec in providers.items()}


def _catalog_entry(key, spec, credential, ready):
    needs_base_url = bool(spec.get("requires_base_url")) and not spec.get("base_url")
    if needs_base_url:
        # No route to validate yet; never call service_transport() with an empty
        # base_url from inside a loop over every other provider too.
        internal_http = False
    else:
        # Validate the route independently of credential/transport opt-in readiness.
        probe_spec = {**spec, "key_env": None, "headers_env": {}}
        probe_spec.pop("oneapi_appkey_env", None)
        _, _, internal_http = service_transport(probe_spec)
    item = {
        "id": key,
        "title": render(spec.get("title", key)),
        "operations": list(spec.get("operations", {})),
        "configured": (
            not needs_base_url
            and spec.get("enabled", True) is not False
            and all(os.environ.get(x) for x in credential_refs(spec))
            and ready(spec)
            and (not spec.get("requires_key") or bool(credential(spec)))
            and (not internal_http or spec.get("allow_insecure_http", False))
        ),
        "key_env": spec.get("key_env"),
        "adapter": spec.get("adapter", "generic"),
        "needs_base_url": needs_base_url,
    }
    item.update(adapter_for(spec).operation_catalog(spec, item, internal_http=internal_http))
    return item


def catalog():
    from studio.adapters.service_connections import credential, ready

    result = []
    for key, spec in config().items():
        try:
            result.append(_catalog_entry(key, spec, credential, ready))
        except EditorError as exc:
            # One misconfigured provider (e.g. transport=assembly-prodtest-http
            # without internal_origin) must not take down the whole catalog —
            # /api/capabilities and the service settings panel both need to keep
            # listing every other provider. Degrade to a minimal, additive entry
            # instead; prepare()/run() still call service_transport() directly
            # and stay strict for that one provider.
            result.append(
                {
                    "id": key,
                    # Same rendering as `_catalog_entry`: BUILTINS titles are catalog
                    # codes, a services.json title is plain text (render() returns
                    # unknown codes unchanged).
                    "title": render(spec.get("title", key)),
                    "operations": list(spec.get("operations", {})),
                    "configured": False,
                    "key_env": spec.get("key_env"),
                    "adapter": spec.get("adapter", "generic"),
                    "needs_base_url": bool(spec.get("requires_base_url")) and not spec.get("base_url"),
                    "setup_message": str(exc),
                }
            )
    return result


def prepare(provider, operation, payload):
    spec = config().get(provider)
    if not spec or operation not in spec.get("operations", {}):
        raise EditorError.coded("services.unknown_service_or_operation")
    require_base_url(provider, spec)
    service_transport(spec, submitting=True)
    validate_payload({k: v for k, v in spec.items() if k != "headers_env"})
    if spec.get("enabled", True) is False:
        raise EditorError.coded("services.provider_not_enabled")
    missing = [x for x in credential_refs(spec) if not os.environ.get(x)]
    if missing:
        raise EditorError.coded("services.missing_env_vars", missing=", ".join(missing))
    from studio.adapters.service_connections import credential

    if (spec.get("requires_key") or spec.get("credential_ref")) and not credential(spec):
        raise EditorError.coded("services.credential_required")
    if not isinstance(payload, dict):
        raise EditorError.coded("services.payload_must_be_object")
    validate_payload(payload)
    payload = adapter_for(spec).prepare_payload(spec, operation, payload)
    return {"provider": provider, "operation": operation, "spec": spec, "payload": payload}


def run(workbench):
    data = workbench["params"]["service"]
    require_base_url(data["provider"], data["spec"])
    adapter_for(data["spec"]).run(workbench)


def _generic_artifact_urls(spec, operation, route, result):
    urls = field(result, route.get("artifacts_path", "artifacts"), {})
    if isinstance(urls, list):
        urls = {item["name"]: item["url"] for item in urls}
    return urls


_FILE_LIKE_KEY = re.compile("file|path|inputs", re.IGNORECASE)


def _sanitize_url(value):
    parts = urllib.parse.urlsplit(value)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return value
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def _sanitize_request_params(value, _key=None):
    """Redact/trim a payload before it becomes `service.json`/ledger provenance.
    Kept as-is: everything that isn't one of the shapes below (operation names,
    booleans, numbers, plain text). Changed:
    - a key matching `key|token|secret|authorization` -> its value becomes
      `"<redacted>"` (`validate_payload`, called from `prepare()`, already rejects a
      credential-shaped key before a payload is accepted, so a provenance record
      built from `data["payload"]` should never actually contain one -- see
      `test_credentials_are_references_not_job_parameters` -- this redaction is
      defense in depth against a payload shape that slips past that check, not the
      primary guarantee);
    - a string that parses as an `http`/`https` URL -> only scheme, host, and path
      survive; its query string and fragment (where a signed upload/download URL's
      access token lives) are dropped;
    - a `{"$file": path}` marker (see `transport.files()`), or a plain string value
      under a key whose name contains `file`/`path`/`inputs` that looks like an
      absolute local filesystem path -> only the basename survives, never the full
      local path;
    applied recursively through nested dicts and lists, `_key` threading the
    enclosing dict key down to each leaf so the path-like-key check above can see
    it."""
    if isinstance(value, dict):
        if set(value) == {"$file"} and isinstance(value.get("$file"), str):
            return Path(value["$file"]).name
        return {
            k: "<redacted>"
            if re.search("key|token|secret|authorization", k, re.IGNORECASE)
            else _sanitize_request_params(v, k)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_sanitize_request_params(v, _key) for v in value]
    if not isinstance(value, str):
        return value
    sanitized_url = _sanitize_url(value)
    if sanitized_url != value:
        return sanitized_url
    if _key and _FILE_LIKE_KEY.search(_key) and value.startswith("/"):
        return Path(value).name
    return value


def _input_provenance(paths):
    """Recorded from `workbench["inputs"]` (local paths), not `data["payload"]`'s
    `{"$file": path}` markers -- `build_payload`/`files()` only inflates those into
    full base64 data URIs at submit time, and a delivered artifact must never carry
    that much inline file content."""
    result = []
    for item in paths:
        path = Path(item)
        if path.is_file():
            with path.open("rb") as stream:
                result.append({"name": path.name, "sha256": hashlib.file_digest(stream, "sha256").hexdigest()})
    return result


def run_generic_job(workbench, *, build_payload=None, id_path_default="result", wrap_result=None, extract_urls=None):
    """Shared "submit once, poll by remote id, download named artifacts" loop for
    hosted services that follow the generic REST-job conventions configurable per
    operation in `route` (`id_path`, `poll`, `status_path`, `progress_path`,
    `success`/`failure`, `artifacts_path`). Used by the built-in Meshy and Tripo
    adapters, and by any custom `services.json` entry whose `adapter` id has no
    dedicated adapter module (see `registry.adapter_for`).

    `build_payload(spec, operation, payload, inputs)`, `wrap_result(response)` and
    `extract_urls(spec, operation, route, result)` let a caller override the few
    provider-specific steps (payload shaping/uploads, response envelope, artifact
    URL extraction) without duplicating the ledger/poll/download plumbing."""
    build_payload = build_payload or (lambda spec, operation, payload, inputs: files(payload))
    wrap_result = wrap_result or (lambda response: response)
    extract_urls = extract_urls or _generic_artifact_urls
    data = workbench["params"]["service"]
    spec, operation, provider = data["spec"], data["operation"], data["provider"]
    root = Path(workbench["output"]).parent
    receipt = root / "service-receipt.json"
    route = spec["operations"][operation]
    if isinstance(route, str):
        route = {"submit": route}
    ledger = json.loads(receipt.read_text()) if receipt.is_file() else {}

    def save(**updates):
        ledger.update(updates)
        _atomic(receipt, json.dumps(ledger).encode())

    if not ledger.get("remote_id"):
        if ledger.get("submission_attempted"):
            raise RuntimeError(render("services.previous_submission_ambiguous"))
        payload = build_payload(spec, operation, dict(data["payload"]), workbench["inputs"])
        save(
            provider=provider,
            operation=operation,
            submission_attempted=True,
            submitted_at=time.time(),
            adapter=spec.get("adapter"),
            model=data["payload"].get("model") or data["payload"].get("version") or spec.get("model"),
            # `data["payload"]`, not the just-built `payload`: the latter has already
            # had any `{"$file": path}` marker inflated into a full base64 data URI
            # (see `_input_provenance`'s docstring) and must never be persisted.
            request_params=_sanitize_request_params(data["payload"]),
        )
        response = request(spec, "POST", route["submit"], payload)
        remote_id = field(response, route.get("id_path", id_path_default))
        if not isinstance(remote_id, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,200}", remote_id):
            raise RuntimeError(render("services.missing_remote_id"))
        save(remote_id=remote_id)
    remote_id = ledger["remote_id"]
    poll_path = route.get("poll", route["submit"] + "/{id}").replace("{id}", remote_id)
    while True:
        response = request(spec, "GET", poll_path)
        result = wrap_result(response)
        status = str(field(result, route.get("status_path", "status"), "unknown")).lower()
        progress = field(result, route.get("progress_path", "progress"))
        save(status=status, progress=progress, polled_at=time.time())
        print(json.dumps({"remote_id": remote_id, "status": status, "progress": progress}), flush=True)
        if status in [
            x.lower() for x in route.get("failure", ["failed", "canceled", "cancelled", "banned", "error", "expired"])
        ]:
            raise RuntimeError(render("services.remote_task_failed", status=status))
        if status in [x.lower() for x in route.get("success", ["succeeded", "success", "completed"])]:
            break
        time.sleep(max(1, min(30, float(spec.get("poll_interval", 5)))))
    urls = extract_urls(spec, operation, route, result)
    if not isinstance(urls, dict) or not urls:
        raise RuntimeError(render("services.no_downloadable_artifacts"))
    output = Path(workbench["output"])
    for name, url in urls.items():
        if not isinstance(url, str):
            continue
        suffix = ".glb" if "glb" in name else ".fbx" if "fbx" in name else ""
        filename = (
            "model." + name if name in ("glb", "fbx", "stl", "3mf") else name if Path(name).suffix else name + suffix
        )
        if not re.fullmatch(r"[a-zA-Z0-9_.-]+", filename) or filename in (".", ".."):
            raise RuntimeError(render("services.invalid_artifact_name"))
        download(url, output / filename)
    # Sanitized provenance only: no signed URLs, raw response, or base_url in
    # delivered files. `cost`/`cost_unit`/`received_at` are also persisted to the
    # ledger so `Tasks.state()` can surface them while `output/service.json` is
    # not yet readable through `artifact()` (task not `completed` yet).
    cost, cost_unit, received_at = result.get("consumed_credits"), "provider credits", time.time()
    save(cost=cost, cost_unit=cost_unit, received_at=received_at)
    (output / "service.json").write_text(
        json.dumps(
            {
                "provider": provider,
                "operation": operation,
                "remote_id": remote_id,
                "status": status,
                "cost": cost,
                "cost_unit": cost_unit,
                "adapter": ledger.get("adapter"),
                "model": ledger.get("model"),
                "request_params": ledger.get("request_params"),
                "input_sha256": _input_provenance(workbench["inputs"]),
                "submitted_at": ledger.get("submitted_at"),
                "received_at": received_at,
            },
            indent=2,
        )
    )


class _GenericAdapter(BaseAdapter):
    """Fallback for any `services.json` entry whose `adapter` id has no dedicated
    module: an arbitrary REST job run through `run_generic_job` with no provider
    overrides. `operation_catalog` and `prepare_payload` keep BaseAdapter's no-op
    defaults, matching this façade's historical "unknown adapter is left alone"
    behavior."""

    def run(self, workbench):
        run_generic_job(workbench)


register("generic")(_GenericAdapter())

# lux3d_service/meshy/tripo already registered themselves as a side effect of the
# BUILTINS-time imports above (their operation tables live in their own module).
# assembly_service/hunyuan_service/seed3d_service have no constant this module
# needs, so import them here for that same registration side effect. Provider
# modules only reach back into this module lazily (inside function bodies, e.g.
# to observe test monkeypatches on `services.download`), never at their own
# import time, so this dispatcher never has to import them earlier than this.
from studio.adapters import assembly_service  # noqa: F401,E402
from studio.adapters import hunyuan_service  # noqa: F401,E402
from studio.adapters import seed3d_service  # noqa: F401,E402
