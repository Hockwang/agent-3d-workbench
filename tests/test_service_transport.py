"""Regression: an explicit internal ingress route must not weaken other traffic."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from studio.adapters import services
from studio.core.editor import EditorError
from studio.i18n import render
from studio.adapters import service_diagnostics


def internal_spec(**extra):
    return {
        **services.BUILTINS["assembly"],
        "enabled": True,
        "transport": "assembly-prodtest-http",
        # RFC 5737 TEST-NET-1: never routable, just a syntactically valid placeholder
        # for tests that don't care what internal_origin actually points at.
        "internal_origin": "http://192.0.2.1",
        **extra,
    }


def test_internal_route_is_direct_and_preserves_gateway_host(tmp_path, monkeypatch):
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            seen.append((self.headers["Host"], self.headers.get("Authorization"), self.path))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"c":"-1","m":"appKey missing","d":null}')

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    internal_origin = f"http://127.0.0.1:{server.server_port}"
    monkeypatch.setenv("http_proxy", "http://127.0.0.1:1")
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("no_proxy", "")
    monkeypatch.setenv("NO_PROXY", "")
    try:
        result = services.request(internal_spec(internal_origin=internal_origin), "GET", "/cubely/v1/workflow/history")
        assert result["m"] == "appKey missing"
        monkeypatch.setenv("TEST_TRANSPORT_TOKEN", "test-only-raw-token")
        spec = internal_spec(internal_origin=internal_origin, headers_env={"Authorization": "TEST_TRANSPORT_TOKEN"})
        with pytest.raises(EditorError, match="明文"):
            services.request(spec, "GET", "/cubely/v1/workflow/history")
        assert len(seen) == 1
        spec["allow_insecure_http"] = True
        services.request(spec, "GET", "/cubely/v1/workflow/history")
        assert seen == [
            ("api-beta.aholo3d.cn", None, "/cubely/v1/workflow/history"),
            ("api-beta.aholo3d.cn", "test-only-raw-token", "/cubely/v1/workflow/history"),
        ]
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.parametrize(
    "changes",
    [
        {"adapter": "meshy"},
        {"base_url": "https://api.aholo3d.cn"},
        {"base_url": "https://api-beta.aholo3d.cn@evil.example"},
        {"base_url": "https://api-beta.aholo3d.cn?key=private"},
        {"transport": "unknown"},
        {"allow_insecure_http": "false"},
    ],
)
def test_route_rejects_wrong_scope(changes):
    with pytest.raises(EditorError):
        services.service_transport(internal_spec(**changes))


def test_catalog_isolates_a_misconfigured_provider_and_keeps_listing_the_rest(tmp_path, monkeypatch):
    baseline = {x["id"]: x for x in services.catalog()}

    config = tmp_path / "services.json"
    config.write_text(json.dumps({"broken": internal_spec(internal_origin=None)}))
    monkeypatch.setenv("WORKBENCH_SERVICE_CONFIG", str(config))
    entries = services.catalog()
    ids = {x["id"] for x in entries}
    assert "broken" in ids
    assert "lux3d" in ids  # every other builtin provider is still listed, unaffected

    broken = next(x for x in entries if x["id"] == "broken")
    assert broken["configured"] is False
    assert broken["title"] == render(internal_spec()["title"])  # same rendering as a healthy entry
    assert broken["operations"] == list(internal_spec()["operations"])
    assert "internal_origin" in broken["setup_message"]

    # Every other builtin provider comes out exactly as it would without the
    # broken one present at all — the per-provider try/except is additive, not
    # a change to how well-configured providers are computed.
    lux3d = next(x for x in entries if x["id"] == "lux3d")
    assert lux3d == baseline["lux3d"]

    # prepare()/run() are unaffected by the catalog-level degrade: they still
    # raise strictly for the one misconfigured provider.
    with pytest.raises(EditorError, match="internal_origin"):
        services.prepare("broken", "segment", {"meshUrl": "https://example.com/input.glb"})


def test_plaintext_submission_requires_explicit_opt_in_before_job(tmp_path, monkeypatch):
    config = tmp_path / "services.json"
    config.write_text(json.dumps({"assembly": internal_spec()}))
    monkeypatch.setenv("WORKBENCH_SERVICE_CONFIG", str(config))
    assert not next(x for x in services.catalog() if x["id"] == "assembly")["configured"]
    with pytest.raises(EditorError, match="明文"):
        services.prepare("assembly", "segment", {"meshUrl": "https://example.com/input.glb"})
    spec = internal_spec(allow_insecure_http=True)
    config.write_text(json.dumps({"assembly": spec}))
    assert services.prepare("assembly", "segment", {"meshUrl": "https://example.com/input.glb"})


def test_result_downloads_and_arbitrary_hosts_still_require_https():
    with pytest.raises(EditorError, match="HTTPS"):
        services.validate_url("http://untrusted.example/output.glb")
    with pytest.raises(EditorError):
        services.credential_refs({"headers_env": {"Host": "TEST_HOST"}})
    with pytest.raises(EditorError, match="路径"):
        services.request(internal_spec(), "GET", "/some-other-service")


def test_no_plaintext_post_even_without_credentials():
    with pytest.raises(EditorError, match="明文"):
        services.request(internal_spec(), "POST", "/cubely/v1/workflow", {"prompt": "private"})


def test_default_transport_preserves_tls_and_redirect_policy(monkeypatch):
    seen = []

    class Opener:
        def open(self, req, timeout):
            seen.append(req)
            raise services.urllib.error.URLError("test unavailable")

    def opener(*handlers):
        assert any(isinstance(x, services.NoRedirect) for x in handlers)
        assert not any(isinstance(x, services.urllib.request.ProxyHandler) for x in handlers)
        return Opener()

    monkeypatch.setattr(services.urllib.request, "build_opener", opener)
    with pytest.raises(RuntimeError):
        services.request(services.BUILTINS["assembly"], "GET", "/cubely/v1/workflow/history")
    assert seen[0].full_url.startswith("https://api-beta.aholo3d.cn/")
    assert not seen[0].has_header("Host")


def test_probe_never_sends_existing_credentials_by_default(monkeypatch):
    monkeypatch.setenv("TEST_TRANSPORT_TOKEN", "test-only-secret")

    def fake_request(spec, method, path, **kwargs):
        assert not services.credential_refs(spec)
        assert not spec.get("allow_insecure_http")
        assert method == "GET" and path.startswith("/cubely/v1/workflow/history?promptId=")
        return {"c": "-1", "m": "appKey missing", "d": {"private": "test-only-secret"}}

    monkeypatch.setattr(service_diagnostics, "request", fake_request)
    result = service_diagnostics.probe_assembly(
        internal_spec(headers_env={"Authorization": "TEST_TRANSPORT_TOKEN"}, oneapi_appkey_env="TEST_TRANSPORT_TOKEN")
    )
    assert result["network_reachable"] and result["authentication"] == "required"
    assert not result["credentials_sent"] and result["generation"] == "not_tested"
    assert "test-only-secret" not in json.dumps(result)


@pytest.mark.parametrize(
    "code,auth",
    [
        ("10002", "accepted_read_only"),
        ("0", "accepted_read_only"),
        ("-1", "unverified"),
        ("10001", "accepted_read_only"),
    ],
)
def test_auth_probe_does_not_equate_gateway_access_with_generation(monkeypatch, code, auth):
    monkeypatch.setenv("TEST_TRANSPORT_TOKEN", "test-only-secret")
    monkeypatch.setattr(service_diagnostics, "request", lambda *a, **k: {"c": code, "m": "test-only-secret"})
    result = service_diagnostics.probe_assembly(
        internal_spec(allow_insecure_http=True, headers_env={"Authorization": "TEST_TRANSPORT_TOKEN"}),
        use_credentials=True,
    )
    assert result["authentication"] == auth and result["generation"] == "not_tested"
    assert "test-only-secret" not in json.dumps(result)


def test_oneapi_inference_key_is_not_gateway_auth(monkeypatch):
    monkeypatch.setenv("TEST_LLM_TOKEN", "test-only-inference-token")
    monkeypatch.setattr(service_diagnostics, "request", lambda *a, **k: pytest.fail("must not send"))
    result = service_diagnostics.probe_assembly(internal_spec(oneapi_appkey_env="TEST_LLM_TOKEN"), use_credentials=True)
    assert result["authentication"] == "not_configured" and not result["credentials_sent"]


def test_internal_redirect_does_not_forward_keys(monkeypatch):
    hits = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            hits.append(self.path)
            self.send_response(302)
            self.send_header("Location", f"http://127.0.0.1:{server.server_port}/unexpected")
            self.end_headers()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setenv("TEST_TRANSPORT_TOKEN", "test-only-secret")
    try:
        with pytest.raises(RuntimeError, match="重定向"):
            services.request(
                internal_spec(
                    internal_origin=f"http://127.0.0.1:{server.server_port}",
                    allow_insecure_http=True,
                    headers_env={"Authorization": "TEST_TRANSPORT_TOKEN"},
                ),
                "GET",
                "/cubely/v1/workflow/history",
            )
        assert hits == ["/cubely/v1/workflow/history"]
    finally:
        server.shutdown()
        server.server_close()
