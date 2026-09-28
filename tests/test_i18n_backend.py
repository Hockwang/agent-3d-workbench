"""Tests for `studio/i18n.py` (language resolution, message rendering) and
its plumbing into `EditorError.coded()` / the HTTP `Handler`.

Per-module message conversion (server.py/mcp_server.py literal error dicts,
other `studio.core.*` raise sites) is a separate, later piece of work; this
file only exercises the scaffold: the catalog itself, and the one converted
reference module (`studio/core/uploads.py`).
"""

from __future__ import annotations

import json

import pytest

from studio import i18n
from studio.core.editor import EditorError


# --- language normalization ---------------------------------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("en", "en"),
        ("EN", "en"),
        ("en-US", "en"),
        ("en_US", "en"),
        ("zh", "zh-CN"),
        ("zh-CN", "zh-CN"),
        ("ZH-cn", "zh-CN"),
        ("zh-Hans", "zh-CN"),
        ("zh_CN", "zh-CN"),
        ("fr", "en"),
        ("fr-FR", "en"),
        ("", "en"),
        (None, "en"),
        ("   ", "en"),
    ],
)
def test_normalize(raw, expected):
    assert i18n.normalize(raw) == expected


# --- Accept-Language parsing ---------------------------------------------------


@pytest.mark.parametrize(
    "header, expected",
    [
        (None, None),
        ("", None),
        ("fr-FR,de;q=0.8", None),  # nothing we support
        ("*", None),
        ("en", "en"),
        ("zh-CN", "zh-CN"),
        ("en-US,en;q=0.9,zh-CN;q=0.8", "en"),  # first entry (no q = 1.0) wins
        ("zh;q=0.5,en;q=0.9", "en"),  # higher q wins regardless of order
        ("fr;q=1.0,zh;q=0.5", "zh-CN"),  # fr is skipped, not coerced
        ("en;q=abc", "en"),  # unparseable q falls back to 1.0, still matches
    ],
)
def test_parse_accept_language(header, expected):
    assert i18n.parse_accept_language(header) == expected


# --- render() fallback chain + missing-param safety ----------------------------


@pytest.fixture
def temp_message():
    """Register a scratch message code directly (bypassing `register()`'s
    duplicate check, which has its own dedicated test below), guaranteed
    removed again after the test so it can never leak into the
    "every registered code has en+zh-CN" completeness check."""
    added: list[str] = []

    def _add(code: str, translations: dict[str, str]) -> str:
        assert code not in i18n.MESSAGES, f"{code!r} is already registered"
        i18n.MESSAGES[code] = translations
        added.append(code)
        return code

    yield _add
    for code in added:
        i18n.MESSAGES.pop(code, None)


def test_render_unknown_code_falls_back_to_the_code_itself():
    assert i18n.render("test_i18n.does_not_exist") == "test_i18n.does_not_exist"


def test_render_falls_back_en_to_zh_cn_when_current_language_is_en(temp_message):
    code = temp_message("test_i18n.zh_only", {"zh-CN": "只有中文"})
    token = i18n.set_language("en")
    try:
        assert i18n.render(code) == "只有中文"
    finally:
        i18n.reset_language(token)


def test_render_falls_back_zh_cn_to_en_when_current_language_is_zh(temp_message):
    code = temp_message("test_i18n.en_only", {"en": "English only"})
    token = i18n.set_language("zh-CN")
    try:
        assert i18n.render(code) == "English only"
    finally:
        i18n.reset_language(token)


def test_render_substitutes_params(temp_message):
    code = temp_message("test_i18n.with_param", {"en": "hello {name}", "zh-CN": "你好 {name}"})
    token = i18n.set_language("en")
    try:
        assert i18n.render(code, name="world") == "hello world"
    finally:
        i18n.reset_language(token)


def test_render_missing_param_does_not_raise(temp_message):
    code = temp_message("test_i18n.missing_param", {"en": "hello {name}", "zh-CN": "你好 {name}"})
    token = i18n.set_language("en")
    try:
        assert i18n.render(code) == "hello {name}"
    finally:
        i18n.reset_language(token)


# --- registry completeness / duplicate detection -------------------------------


def test_every_registered_code_has_non_empty_en_and_zh_cn():
    assert i18n.MESSAGES, "expected at least the studio.core.uploads.* codes to be registered"
    for code, translations in i18n.MESSAGES.items():
        assert translations.get("en"), f"{code!r} has no English text"
        assert translations.get("zh-CN"), f"{code!r} has no Chinese text"


def test_register_duplicate_code_with_different_text_raises():
    code = "test_i18n.duplicate"
    assert code not in i18n.MESSAGES
    try:
        i18n.register({code: {"en": "one", "zh-CN": "一"}})
        with pytest.raises(ValueError):
            i18n.register({code: {"en": "ONE (different)", "zh-CN": "一"}})
        # Re-registering the exact same mapping is a no-op, not an error.
        i18n.register({code: {"en": "one", "zh-CN": "一"}})
        assert i18n.MESSAGES[code] == {"en": "one", "zh-CN": "一"}
    finally:
        i18n.MESSAGES.pop(code, None)


# --- EditorError.coded() under en vs zh-CN --------------------------------------


def test_editor_error_coded_renders_in_current_language():
    token = i18n.set_language("zh-CN")
    try:
        exc = EditorError.coded("uploads.bad_upload_id")
    finally:
        i18n.reset_language(token)
    assert exc.code == "uploads.bad_upload_id"
    assert exc.params == {}
    assert str(exc) == "无效上传 ID"

    token = i18n.set_language("en")
    try:
        exc = EditorError.coded("uploads.bad_upload_id")
    finally:
        i18n.reset_language(token)
    assert str(exc) == "Invalid upload id"


def test_editor_error_positional_construction_still_works():
    """`EditorError(message, code)` — the pre-i18n call shape used by every
    not-yet-converted raise site — must keep working unchanged."""
    exc = EditorError("legacy message", code="bad_arguments")
    assert str(exc) == "legacy message"
    assert exc.code == "bad_arguments"
    assert exc.params == {}


# --- print_prep.messages bridging (its language_provider hook, wired from this module) ---


def test_print_prep_message_follows_the_studio_language_hook():
    """`print_prep` cannot import `studio` (see `tests/test_layering.py`), so it
    carries its own standalone message catalog/render in `print_prep/messages.py`.
    This module wires that module's `language_provider` hook to `get_language`
    (see the bottom of `studio/i18n.py`), so a language chosen at this (studio)
    layer flows down into print_prep's own renders."""
    import print_prep.messages as print_prep_messages

    token = i18n.set_language("en")
    try:
        assert print_prep_messages.render("cli.no_parts") == "No parts were loaded"
    finally:
        i18n.reset_language(token)

    token = i18n.set_language("zh-CN")
    try:
        assert print_prep_messages.render("cli.no_parts") == "没有载入任何零件"
    finally:
        i18n.reset_language(token)


# --- HTTP layer: Accept-Language drives the rendered language end to end -------


def _upload_task_body():
    return {"action": "upload", "name": "evil.exe", "size": 1, "data_base64": "AA=="}


def test_http_request_with_accept_language_en_gets_english_message(studio_env):
    client = studio_env["client"]
    status, resp = client.post("/api/task", _upload_task_body(), headers={"Accept-Language": "en"})
    assert status == 400
    assert resp["error"]["code"] == "uploads.bad_name_or_type"
    assert resp["error"]["message"] == "Unsupported file name or type"
    assert resp["error"]["params"] == {}


def test_http_request_without_accept_language_gets_chinese_message(studio_env):
    """No `Accept-Language` header -> falls back to the process default, which
    the autouse `_isolate_user_state` fixture in conftest.py pins to
    `STUDIO_LANG=zh-CN` for the whole test suite."""
    client = studio_env["client"]
    status, resp = client.post("/api/task", _upload_task_body())
    assert status == 400
    assert resp["error"]["code"] == "uploads.bad_name_or_type"
    assert resp["error"]["message"] == "不支持的文件名或类型"
    assert "params" in resp["error"]


# --- "params" travels through the JSON error body -------------------------------


def test_error_body_always_carries_a_params_key(studio_env):
    """Additive-JSON-key check for a handler that never touches EditorError
    at all (a literal `{"error": {...}}` dict built directly in server.py) —
    every error body in the codebase gets `"params"`, not just the ones
    raised through the catalog."""
    client = studio_env["client"]
    status, resp = client.get("/api/does-not-exist")
    assert status == 404
    assert resp["error"]["code"] == "not_found"
    assert resp["error"]["params"] == {}


def test_json_error_body_round_trips_through_json(studio_env):
    """Sanity check that `params` survives actual JSON encoding, not just the
    in-memory dict some earlier assertion might have looked at."""
    client = studio_env["client"]
    status, resp = client.post("/api/task", _upload_task_body())
    reencoded = json.loads(json.dumps(resp))
    assert reencoded["error"]["params"] == {}


# ---------------------------------------------------------------------------
# The page servers stamp the process default language into the HTML so the
# panel's own locale (studio/web/i18n.js) follows STUDIO_LANG.


def test_index_page_carries_the_server_default_language(studio_env, monkeypatch):
    import http.client

    monkeypatch.setenv("STUDIO_LANG", "zh-CN")
    conn = http.client.HTTPConnection("127.0.0.1", studio_env["port"], timeout=5)
    conn.request("GET", "/")
    resp = conn.getresponse()
    body = resp.read().decode()
    conn.close()
    assert resp.status == 200
    assert '<meta name="studio-language" content="zh-CN">' in body
    assert '<meta name="studio-language" content="">' not in body


def test_index_page_leaves_the_hint_empty_when_studio_lang_is_unset(studio_env, monkeypatch):
    """No STUDIO_LANG -> the page decides from the browser language, so the
    server must not pretend a choice was made (the suite pins zh-CN; undo it)."""
    import http.client

    monkeypatch.delenv("STUDIO_LANG", raising=False)
    conn = http.client.HTTPConnection("127.0.0.1", studio_env["port"], timeout=5)
    conn.request("GET", "/index.html")
    resp = conn.getresponse()
    body = resp.read().decode()
    conn.close()
    assert resp.status == 200
    assert '<meta name="studio-language" content="">' in body


def test_stamp_language_uses_the_configured_language_not_the_request_language(monkeypatch):
    from studio.shell import app_resources

    monkeypatch.setenv("STUDIO_LANG", "en")
    token = i18n.set_language("zh-CN")  # a request in flight must not leak into the stamp
    try:
        html = b'<head><meta name="studio-language" content=""></head>'
        assert app_resources.stamp_language(html) == b'<head><meta name="studio-language" content="en"></head>'
        assert app_resources.stamp_language(b"<head></head>") == b"<head></head>"
        monkeypatch.setenv("STUDIO_LANG", "  ")
        assert app_resources.stamp_language(html) == html
        monkeypatch.delenv("STUDIO_LANG")
        assert app_resources.stamp_language(html) == html
    finally:
        i18n.reset_language(token)


def test_app_resource_is_stamped_too(tmp_path, monkeypatch):
    from studio.shell import app_resources

    path = tmp_path / "studio.html"
    path.write_text('<head><meta name="studio-language" content=""></head><main data-workspace-id=""></main>')
    monkeypatch.setattr(app_resources, "UI_PATH", path)
    monkeypatch.setenv("STUDIO_LANG", "zh-CN")
    html = app_resources.ui_html(app_resources.LEGACY_UI_URI + "?workspace=stamp-test")
    assert '<meta name="studio-language" content="zh-CN">' in html
    assert 'data-workspace-id="stamp-test"' in html
