import base64
import json
import os
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from studio.adapters import service_connections as connections, services
from studio.core.editor import EditorError


@pytest.fixture(autouse=True)
def private_config(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKBENCH_SERVICE_CONFIG", str(tmp_path / "services.json"))


def envelope(secret, base_url="https://example.test/v1"):
    # Exercise the actual browser implementation against the Python decryptor.
    source = """
      import { sealCredential } from './studio/web/service-settings.js';
      let text=''; for await (const chunk of process.stdin) text+=chunk;
      const {secret,encryption,base_url}=JSON.parse(text);
      process.stdout.write(JSON.stringify(await sealCredential(secret,encryption,base_url)));
    """
    return json.loads(
        subprocess.run(
            ["node", "--input-type=module", "-e", source],
            input=json.dumps({"secret": secret, "encryption": connections.public_key(), "base_url": base_url}),
            text=True,
            capture_output=True,
            check=True,
        ).stdout
    )


def save(**changes):
    return connections.save(
        {
            "action": "save",
            "template": "hunyuan",
            "title": "My 3D",
            "base_url": "https://example.test/v1",
            "expected_revision": connections.read_store()["revision"],
            **changes,
        }
    )


def test_sealed_key_persists_without_public_or_task_leak():
    secret = "private-" + "long-token-" * 80  # Longer than an RSA-OAEP plaintext block.
    sealed = envelope(secret)
    result = save(sealed_key=sealed)
    spec = services.config()[result["id"]]
    assert connections.credential(spec) == secret
    assert connections.store_path().stat().st_mode & 0o777 == 0o600
    task_spec = services.prepare(result["id"], "text-to-3d", {"prompt": "chair"})
    for public in (result, services.catalog(), task_spec, sealed):
        assert secret not in json.dumps(public)
    assert next(x for x in services.catalog() if x["id"] == result["id"])["configured"]
    # The worker can resolve a persisted reference in a new process, without the UI keypair.
    check = subprocess.run(
        [
            "uv",
            "run",
            "--frozen",
            "python",
            "-c",
            "from studio.adapters.service_connections import credential; import json,sys; print(bool(credential(json.loads(sys.stdin.read()))))",
        ],
        input=json.dumps(spec),
        text=True,
        capture_output=True,
        check=True,
    )
    assert check.stdout.strip() == "True"


def test_address_change_drops_saved_and_environment_credentials(monkeypatch):
    first = save(sealed_key=envelope("private-test-key"))
    old = services.config()[first["id"]]
    changed = save(id=first["id"], base_url="https://different.test/v1")
    new = services.config()[first["id"]]
    assert (
        not connections.credential(new)
        and not next(x for x in changed["profiles"] if x["id"] == first["id"])["configured"]
    )
    assert connections.credential(old) == "private-test-key"  # In-flight snapshot still owns its old endpoint.
    with pytest.raises(EditorError):
        connections.credential({**old, "base_url": new["base_url"]})
    monkeypatch.setenv("CONNECTION_TEST_KEY", "env-test-key")
    env = save(key_env="CONNECTION_TEST_KEY")
    save(id=env["id"], base_url="https://new.test/v1")
    assert services.config()[env["id"]]["key_env"] is None


def test_blank_preserves_clear_disables_delete_and_stale_revision():
    first = save(sealed_key=envelope("private-test-key"))
    save(id=first["id"], title="Renamed")
    assert connections.credential(services.config()[first["id"]]) == "private-test-key"
    with pytest.raises(EditorError, match="已更新"):
        save(id=first["id"], expected_revision=first["revision"])
    save(id=first["id"], enabled=False)
    with pytest.raises(EditorError, match="尚未启用"):
        services.prepare(first["id"], "text-to-3d", {"prompt": "chair"})
    save(id=first["id"], clear_key=True)
    with pytest.raises(EditorError, match="填写 API key"):
        services.prepare(first["id"], "text-to-3d", {"prompt": "chair"})
    connections.delete({"id": first["id"], "expected_revision": connections.read_store()["revision"]})
    assert first["id"] not in services.config()


def test_envelope_failures_never_echo_input():
    sealed = envelope("sensitive-private-value")
    for changes in (
        {"key_id": "stale"},
        {"ciphertext": "sensitive-private-value"},
        {"iv": base64.b64encode(os.urandom(12)).decode()},
    ):
        with pytest.raises(EditorError) as error:
            save(sealed_key={**sealed, **changes})
        assert "sensitive-private-value" not in str(error.value)
    with pytest.raises(EditorError):
        save(api_key="sensitive-private-value")
    with pytest.raises(EditorError):
        save(sealed_key=sealed, base_url="https://attacker.test")
    assert not connections.store_path().exists()


def test_readonly_probe_authentication_and_redirect_isolation():
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            calls.append((self.path, self.headers.get("Authorization")))
            if self.path == "/redirect/models":
                self.send_response(302)
                self.send_header("Location", "/stolen")
                self.end_headers()
                return
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps({"data": [{"id": "hunyuan-3d-rapid"}, {"id": "general-llm"}]}).encode())

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        profile = save(base_url=base, sealed_key=envelope("probe-private-key", base))
        result = connections.probe(profile["id"])
        assert result["models"] == ["hunyuan-3d-rapid"] and not result["generation_tested"]
        assert calls == [("/models", "Bearer probe-private-key")]
        redirected = save(base_url=base + "/redirect", sealed_key=envelope("probe-private-key", base + "/redirect"))
        with pytest.raises(RuntimeError, match="重定向"):
            connections.probe(redirected["id"])
        assert all(path != "/stolen" for path, _ in calls)
    finally:
        server.shutdown()
        server.server_close()


def test_concurrent_stale_writes_cannot_overwrite():
    revision = connections.read_store()["revision"]
    outcomes = []

    def run():
        try:
            save(expected_revision=revision)
            outcomes.append("saved")
        except EditorError:
            outcomes.append("conflict")

    threads = [threading.Thread(target=run) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(outcomes) == ["conflict", "saved"]


def test_legacy_tuning_is_preserved_and_delete_cannot_resurrect_it(tmp_path):
    (tmp_path / "services.json").write_text(
        json.dumps(
            {
                "legacy": {
                    **services.BUILTINS["hunyuan"],
                    "base_url": "https://example.test/v1",
                    "poll_interval": 12,
                    "operations": {"segment": "/responses"},
                }
            }
        )
    )
    result = save(id="legacy", enabled=False)
    spec = services.config()["legacy"]
    assert spec["poll_interval"] == 12 and spec["operations"] == {"segment": "/responses"}
    assert not next(p for p in result["profiles"] if p["id"] == "legacy")["removable"]
    with pytest.raises(EditorError):
        connections.delete({"id": "legacy", "expected_revision": result["revision"]})


def _write_raw_profile(profile):
    # Bypasses `save()` on purpose: `save()` always re-merges the current
    # `BUILTINS[template]`, so it can never reproduce a profile frozen on disk
    # before `local_inputs_allowed`/`default_timeout_seconds` existed there.
    with connections.locked_store() as data:
        data["profiles"]["old"] = profile
        data["revision"] = "irrelevant-for-this-test"
        connections.write_store(data)


def test_old_saved_connection_without_policy_keys_still_gets_1800s_timeout():
    _write_raw_profile(
        {
            "connection_template": "hunyuan",
            "adapter": "hunyuan-responses",
            "title": "Old Hunyuan",
            "base_url": "https://example.test/v1",
            "key_env": "HUNYUAN_API_KEY",
            "enabled": True,
            "operations": {"image-to-3d": "/responses"},
        }
    )
    spec = services.config()["old"]
    assert spec["default_timeout_seconds"] == 1800


def test_old_saved_assembly_shaped_connection_still_rejects_local_inputs():
    _write_raw_profile(
        {
            "adapter": "assembly",
            "title": "Old Assembly",
            "base_url": "https://api-beta.aholo3d.cn",
            "enabled": True,
            "operations": {"assemble": "assemble"},
        }
    )
    spec = services.config()["old"]
    assert spec["local_inputs_allowed"] is False
    assert spec["default_timeout_seconds"] == 1800


def test_saved_connections_explicit_policy_keys_win_over_backfill():
    _write_raw_profile(
        {
            "connection_template": "hunyuan",
            "adapter": "hunyuan-responses",
            "title": "Custom",
            "base_url": "https://example.test/v1",
            "key_env": "HUNYUAN_API_KEY",
            "enabled": True,
            "operations": {"image-to-3d": "/responses"},
            "default_timeout_seconds": 90,
            "local_inputs_allowed": False,
        }
    )
    spec = services.config()["old"]
    assert spec["default_timeout_seconds"] == 90
    assert spec["local_inputs_allowed"] is False
