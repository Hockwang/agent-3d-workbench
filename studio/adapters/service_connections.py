"""Local BYOK connection management shared by every optional, key-gated hosted
adapter (Lux3D, Hunyuan, Seed3D, Assembly, Meshy, Tripo). Public configuration
never contains credential values: the private store lives beside services.json,
outside projects, with 0600 permissions (not OS keychain encryption). UI secrets
cross the MCP bridge encrypted with a process-local RSA key and AES-GCM, never
as plaintext tool arguments.
"""

from contextlib import contextmanager
import base64
import json
import os
from pathlib import Path
import re
import tempfile
import threading
import uuid

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from studio.core import filelock
from studio.core.editor import EditorError
from studio.i18n import render

_LOCK = threading.RLock()
_KEY = None
_KEY_ID = uuid.uuid4().hex
# Values are message-catalog codes (see `services.BUILTINS`'s own `title` codes
# for the same pattern), rendered by `render()` where they are displayed
# (`listing()`), never at module-import time.
TEMPLATES = {
    "lux3d": "service_connections.title_lux3d",
    "lux3d-global": "service_connections.title_lux3d_global",
    "hunyuan": "service_connections.title_hunyuan",
    "seed3d": "service_connections.title_seed3d",
    "meshy": "service_connections.title_meshy",
    "tripo": "service_connections.title_tripo",
}


def store_path():
    config = Path(os.environ.get("WORKBENCH_SERVICE_CONFIG", "~/.config/codex-3d/services.json")).expanduser()
    return config.with_name("connections.private.json")


def read_store():
    path = store_path()
    if not path.exists():
        return {"revision": "0", "profiles": {}, "secrets": {}}
    try:
        data = json.loads(path.read_text())
        if not isinstance(data.get("profiles"), dict) or not isinstance(data.get("secrets"), dict):
            raise ValueError()
        return data
    except (OSError, ValueError, AttributeError):
        raise EditorError.coded("service_connections.local_config_unreadable") from None


@contextmanager
def locked_store():
    path = store_path()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with _LOCK:
        fd = os.open(path.with_suffix(".lock"), os.O_CREAT | os.O_RDWR, 0o600)
        try:
            filelock.lock(fd)
            yield read_store()
        finally:
            os.close(fd)


def write_store(data):
    path = store_path()
    fd, name = tempfile.mkstemp(prefix=".connections-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(data, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def public_key():
    global _KEY
    with _LOCK:
        if _KEY is None:
            _KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        raw = _KEY.public_key().public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
        )
    return {"key_id": _KEY_ID, "spki": base64.b64encode(raw).decode()}


def unseal(envelope, base_url):
    try:
        if not isinstance(envelope, dict) or envelope.get("key_id") != _KEY_ID or _KEY is None:
            raise ValueError()

        def decode(name, limit):
            value = envelope[name]
            if not isinstance(value, str) or len(value) > limit:
                raise ValueError()
            return base64.b64decode(value, validate=True)

        key = _KEY.decrypt(
            decode("wrapped_key", 512),
            padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None),
        )
        secret = (
            AESGCM(key)
            .decrypt(decode("iv", 32), decode("ciphertext", 24000), (_KEY_ID + "\n" + base_url).encode())
            .decode()
        )
        if not secret or len(secret) > 16000 or any(c.isspace() for c in secret):
            raise ValueError()
        return secret
    except Exception:
        raise EditorError.coded("service_connections.key_unseal_failed") from None


def credential(spec):
    ref = spec.get("credential_ref")
    if not ref:
        return os.environ.get(spec.get("key_env") or "", "")
    item = read_store()["secrets"].get(ref, {})
    if item.get("base_url") != spec.get("base_url", "").rstrip("/"):
        raise EditorError.coded("service_connections.credential_base_url_mismatch")
    return item.get("value", "")


def ready(spec):
    try:
        return bool(credential(spec)) if spec.get("credential_ref") else True
    except EditorError:
        return False


def listing():
    from studio.adapters.services import BUILTINS, catalog, config

    data, specs = read_store(), config()
    legacy = config(include_connections=False)
    states = {x["id"]: x for x in catalog()}
    profiles = []
    for name, spec in specs.items():
        template = spec.get("connection_template") or next(
            (
                k
                for k in TEMPLATES
                if BUILTINS[k]["adapter"] == spec.get("adapter") and BUILTINS[k].get("region") == spec.get("region")
            ),
            None,
        )
        profiles.append(
            {
                "id": name,
                "title": render(spec.get("title", name)),
                "base_url": spec.get("base_url", ""),
                "template": template,
                "enabled": spec.get("enabled", True),
                "configured": states[name]["configured"],
                "key_env": spec.get("key_env"),
                "credential_stored": bool(spec.get("credential_ref")),
                "editable": template is not None and not spec.get("headers_env") and not spec.get("oneapi_appkey_env"),
                "removable": name in data["profiles"] and name not in legacy,
            }
        )
    return {
        "ok": True,
        "revision": data["revision"],
        "profiles": profiles,
        "encryption": public_key(),
        "templates": [{"id": k, "title": render(v), "base_url": BUILTINS[k]["base_url"]} for k, v in TEMPLATES.items()],
    }


def save(body):
    from studio.adapters.services import BUILTINS, config, validate_url

    allowed = {
        "action",
        "id",
        "template",
        "title",
        "base_url",
        "enabled",
        "key_env",
        "sealed_key",
        "clear_key",
        "expected_revision",
    }
    if set(body) - allowed:
        raise EditorError.coded("service_connections.unknown_connection_field")
    name = body.get("id") or "service-" + uuid.uuid4().hex[:12]
    if not isinstance(name, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", name):
        raise EditorError.coded("service_connections.invalid_service_id")
    template = body.get("template")
    if template not in TEMPLATES:
        raise EditorError.coded("service_connections.unsupported_protocol")
    title = body.get("title", "")
    if not isinstance(title, str) or not 1 <= len(title.strip()) <= 100:
        raise EditorError.coded("service_connections.title_length_range")
    base = body.get("base_url")
    if not isinstance(base, str) or len(base) > 2000:
        raise EditorError.coded("service_connections.invalid_base_url")
    base = validate_url(base.strip()).rstrip("/")
    from urllib.parse import urlsplit

    if urlsplit(base).query or urlsplit(base).fragment:
        raise EditorError.coded("service_connections.base_url_no_query_or_fragment")
    if type(body.get("enabled", True)) is not bool or type(body.get("clear_key", False)) is not bool:
        raise EditorError.coded("service_connections.enabled_and_clear_key_must_be_bool")
    env = body.get("key_env") or None
    if env is not None and (not isinstance(env, str) or not re.fullmatch(r"[A-Z_][A-Z0-9_]*", env)):
        raise EditorError.coded("service_connections.key_env_must_be_name_not_value")
    secret = unseal(body["sealed_key"], base) if body.get("sealed_key") is not None else None
    if secret and env:
        raise EditorError.coded("service_connections.key_and_env_conflict")
    with locked_store() as data:
        if body.get("expected_revision") != data["revision"]:
            raise EditorError.coded("service_connections.revision_conflict_on_save")
        old = config().get(name, {})
        if old and old.get("adapter") != BUILTINS[template]["adapter"]:
            raise EditorError.coded("service_connections.protocol_change_not_allowed")
        if old.get("headers_env") or old.get("oneapi_appkey_env"):
            raise EditorError.coded("service_connections.custom_headers_not_editable")
        spec = {
            **BUILTINS[template],
            **old,
            "connection_template": template,
            "title": title.strip(),
            "base_url": base,
            "enabled": body.get("enabled", True),
        }
        from studio.adapters.registry import adapter_for

        adapter_for(spec).on_save(spec, BUILTINS[template], old)
        # A changed endpoint must never inherit a saved credential or environment reference.
        same_base = base == old.get("base_url", "").rstrip("/")
        ref = old.get("credential_ref") if same_base and not body.get("clear_key") and not env else None
        if secret:
            ref = uuid.uuid4().hex
            data["secrets"][ref] = {"base_url": base, "value": secret}
        spec["key_env"] = env or (old.get("key_env") if same_base and not body.get("clear_key") and not ref else None)
        spec.pop("credential_ref", None)
        if ref:
            spec["credential_ref"] = ref
        # Missing credential is distinct from an intentionally unauthenticated generic API.
        spec["requires_key"] = True
        data["profiles"][name] = spec
        data["revision"] = uuid.uuid4().hex
        write_store(data)
    return {"ok": True, "id": name, **listing()}


def delete(body):
    from studio.adapters.services import config

    with locked_store() as data:
        if body.get("expected_revision") != data["revision"]:
            raise EditorError.coded("service_connections.revision_conflict_on_delete")
        name = body.get("id")
        if name in config(include_connections=False) or name not in data["profiles"]:
            raise EditorError.coded("service_connections.builtin_or_file_configured_not_removable")
        del data["profiles"][name]
        # Keep old references for in-flight tasks, whose requests freeze the old endpoint.
        data["revision"] = uuid.uuid4().hex
        write_store(data)
    return listing()


def probe(name):
    from studio.adapters.services import config, catalog
    from studio.adapters.registry import adapter_for

    spec = config().get(name)
    if not spec:
        raise EditorError.coded("service_connections.service_not_found")
    if not next(x for x in catalog() if x["id"] == name)["configured"]:
        raise EditorError.coded("service_connections.enable_and_configure_key_first")
    return {"ok": True, "id": name, **adapter_for(spec).probe(spec)}


def execute(body):
    action = body.get("action", "list")
    if action == "list":
        return listing()
    if action == "save":
        return save(body)
    if action == "delete":
        return delete(body)
    if action == "probe":
        return probe(body.get("id"))
    if action in ("balance", "quote", "remote_task", "remote_tasks"):
        from studio.adapters.lux3d_commerce import execute as lux3d_execute

        return lux3d_execute(body)
    raise EditorError.coded("service_connections.unknown_action")
