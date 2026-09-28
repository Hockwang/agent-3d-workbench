"""Generic HTTP transport shared by every hosted-service adapter.

This module has no knowledge of any specific provider's wire protocol (payload
shapes, polling conventions, ...): it only validates URLs/credentials, builds the
one HTTP request primitive every adapter submits through, and downloads results.
The one deliberate exception is the `assembly-prodtest-http` transport mode in
`service_transport`/`request`, which is a fixed, opt-in internal-network route for
a single documented deployment, not a general provider hook.

POST is attempted once. An ambiguous submission remains ambiguous; recovery only
polls a persisted remote ID. Credentials and signed result URLs are not artifacts.
"""

from __future__ import annotations
import base64
import json
import mimetypes
import os
from pathlib import Path
import re
import urllib.error
import urllib.parse
import urllib.request

from studio.core.editor import EditorError
from studio.i18n import render


def validate_internal_origin(url):
    """Like `validate_url`, but allows plain HTTP to a non-local host: this only ever
    replaces the origin for the fixed, opt-in `assembly-prodtest-http` transport below,
    which already pins the Host header, forbids redirects, and requires an explicit
    `allow_insecure_http` before sending credentials or task parameters."""
    parsed = urllib.parse.urlsplit(url)
    if parsed.username or parsed.password or parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise EditorError.coded("transport.internal_origin_requires_no_credentials")
    if parsed.query or parsed.fragment or parsed.path not in ("", "/"):
        raise EditorError.coded("transport.internal_origin_scheme_host_only")
    return url.rstrip("/")


def validate_url(url):
    parsed = urllib.parse.urlsplit(url)
    if parsed.username or parsed.password or parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise EditorError.coded("transport.service_url_requires_no_credentials")
    if parsed.scheme == "http" and parsed.hostname not in ("127.0.0.1", "localhost", "::1"):
        raise EditorError.coded("transport.remote_requires_https")
    return url


def validate_payload(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if re.sub("[^a-z]", "", key.lower()) in (
                "apikey",
                "authorization",
                "accesskey",
                "secretkey",
                "password",
                "secret",
                "oneapiappkey",
                "appkey",
            ):
                raise EditorError.coded("transport.credentials_must_use_key_env")
            validate_payload(item)
    elif isinstance(value, list):
        for item in value:
            validate_payload(item)


def credential_refs(spec):
    if type(spec.get("enabled", True)) is not bool:
        raise EditorError.coded("transport.enabled_must_be_bool")
    direct = [spec.get(name) for name in ("key_env", "secret_key_env", "oneapi_appkey_env") if spec.get(name) is not None]
    if any(not isinstance(ref, str) or not re.fullmatch(r"[A-Z_][A-Z0-9_]*", ref) for ref in direct):
        raise EditorError.coded("transport.credential_ref_must_be_env_name")
    refs = spec.get("headers_env", {})
    if not isinstance(refs, dict):
        raise EditorError.coded("transport.headers_env_must_be_mapping")
    for header, env in refs.items():
        if (
            not re.fullmatch(r"[A-Za-z][A-Za-z0-9-]*", header)
            or header.lower() in ("host", "content-length", "connection", "transfer-encoding")
            or not isinstance(env, str)
            or not re.fullmatch(r"[A-Z_][A-Z0-9_]*", env)
        ):
            raise EditorError.coded("transport.headers_env_invalid_entry")
    return direct + list(refs.values())


def service_transport(spec, *, submitting=False):
    if not spec.get("base_url"):
        raise EditorError.coded("transport.missing_base_url")
    base_url = validate_url(spec["base_url"]).rstrip("/")
    mode = spec.get("transport", "default")
    if type(spec.get("allow_insecure_http", False)) is not bool:
        raise EditorError.coded("transport.allow_insecure_http_must_be_bool")
    if mode == "default":
        return base_url, {}, False
    if (
        mode != "assembly-prodtest-http"
        or spec.get("adapter") != "assembly"
        or base_url != "https://api-beta.aholo3d.cn"
    ):
        raise EditorError.coded("transport.internal_transport_scope_restricted")
    internal_origin = spec.get("internal_origin")
    if not isinstance(internal_origin, str) or not internal_origin:
        raise EditorError.coded("transport.internal_origin_required")
    internal_origin = validate_internal_origin(internal_origin)
    if (submitting or credential_refs(spec)) and not spec.get("allow_insecure_http", False):
        raise EditorError.coded("transport.internal_http_requires_opt_in")
    return internal_origin, {"Host": "api-beta.aholo3d.cn"}, True


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeError(render("transport.redirect_rejected"))


def request(spec, method, path, payload=None, *, raw=None, content_type="application/json", timeout=90, authorization=None):
    if not isinstance(path, str) or not path.startswith("/") or path.startswith("//"):
        raise RuntimeError(render("transport.path_must_start_with_slash"))
    origin, route_headers, internal_http = service_transport(
        spec, submitting=method != "GET" or payload is not None or raw is not None
    )
    if internal_http and urllib.parse.urlsplit(path).path not in (
        "/cubely/v1/workflow",
        "/cubely/v1/workflow/history",
        "/cubely/v1/workflow/assets",
    ):
        raise EditorError.coded("transport.internal_path_restricted")
    url = origin + path
    from studio.adapters.service_connections import credential

    key = credential(spec)
    if key and any(c.isspace() for c in key):
        raise EditorError.coded("transport.credential_contains_invalid_whitespace")
    headers = {"Content-Type": content_type, **route_headers}
    if key:
        headers["Authorization"] = key if spec.get("adapter") == "lux3d" else "Bearer " + key
    # Short-lived provider tokens stay in memory, never in a persisted spec or env.
    if authorization is not None:
        if not isinstance(authorization, str) or not authorization or "\r" in authorization or "\n" in authorization:
            raise EditorError.coded("transport.credential_contains_invalid_whitespace")
        headers["Authorization"] = authorization
    credential_refs(spec)
    for name, env in spec.get("headers_env", {}).items():
        value = os.environ.get(env, "")
        if not value or "\r" in value or "\n" in value:
            raise RuntimeError(render("transport.header_env_missing_or_invalid_newline"))
        headers[name] = value
    data = raw if raw is not None else json.dumps(payload).encode() if payload is not None else None
    handlers = [NoRedirect()]
    if internal_http:
        # Scoped to this request: do not change process/system proxy or DNS settings.
        handlers.append(urllib.request.ProxyHandler({}))
    try:
        with urllib.request.build_opener(*handlers).open(
            urllib.request.Request(url, data=data, headers=headers, method=method), timeout=timeout
        ) as response:
            result = response.read(16 * 1024 * 1024 + 1)
            if len(result) > 16 * 1024 * 1024:
                raise RuntimeError(render("transport.response_too_large"))
            decoded = json.loads(result)
            if not isinstance(decoded, dict):
                raise RuntimeError(render("transport.response_not_json_object"))
            return decoded
    except urllib.error.HTTPError as exc:
        raise RuntimeError(render("transport.http_error", status=exc.code)) from None
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        raise RuntimeError(render("transport.connection_or_json_error_no_resubmit")) from None


def field(data, path, default=None):
    for part in path.split(".") if path else []:
        if isinstance(data, list) and part.isdigit():
            data = data[int(part)] if int(part) < len(data) else None
        elif isinstance(data, dict):
            data = data.get(part)
        else:
            return default
    return default if data is None else data


def file_data(path):
    path = Path(path).expanduser()
    if not path.is_absolute() or not path.is_file() or path.stat().st_size > 100 * 1024 * 1024:
        raise RuntimeError(render("transport.file_ref_invalid"))
    return (
        "data:"
        + (mimetypes.guess_type(path.name)[0] or "application/octet-stream")
        + ";base64,"
        + base64.b64encode(path.read_bytes()).decode()
    )


def files(value):
    if isinstance(value, dict):
        if set(value) == {"$file"}:
            return file_data(value["$file"])
        return {key: files(item) for key, item in value.items()}
    if isinstance(value, list):
        return [files(item) for item in value]
    return value


def download(url, target):
    validate_url(url)
    # Result CDN never receives the provider API key.
    temp = target.with_suffix(target.suffix + ".partial")
    try:
        with urllib.request.urlopen(url, timeout=120) as response, temp.open("wb") as output:
            size = 0
            while chunk := response.read(1024 * 1024):
                size += len(chunk)
                if size > 1024**3:
                    raise RuntimeError(render("transport.artifact_too_large"))
                output.write(chunk)
        if not size:
            raise RuntimeError(render("transport.artifact_empty"))
        temp.replace(target)
    except (urllib.error.URLError, TimeoutError):
        raise RuntimeError(render("transport.download_failed_resume_with_task_id")) from None
    finally:
        temp.unlink(missing_ok=True)
