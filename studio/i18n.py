"""Backend message catalog and per-request language resolution.

Every user-facing error message the backend can raise lives in a small
per-package catalog (`studio/core/messages.py`, `studio/shell/messages.py`,
`studio/adapters/messages.py`, ...), each registering its codes here via
`register()` at import time. `EditorError.coded()` (`studio/core/editor.py`)
renders a message from this catalog at the moment an error is raised; the
HTTP and MCP layers (`studio/shell/server.py`, `studio/shell/mcp_server.py`)
arrange for `get_language()` to already reflect the caller's preference
before any handler code runs, so the render is in the right language without
every raise site needing to know about requests or transports.

This module is intentionally dependency-free (stdlib only) and sits above
all three layers (core/adapters/shell) so any of them can import it without
tripping the layer-boundary rule in `docs/ARCHITECTURE.md`.
"""

from __future__ import annotations

import os
import re
from contextvars import ContextVar, Token
from typing import Optional

SUPPORTED_LANGUAGES: tuple[str, ...] = ("en", "zh-CN")
DEFAULT_LANGUAGE = "en"

# code -> {"en": ..., "zh-CN": ...}
MESSAGES: dict[str, dict[str, str]] = {}


def register(messages: dict[str, dict[str, str]]) -> None:
    """Merge a package-local catalog into the global registry.

    Called once at import time by each `studio/<layer>/messages.py`. A code
    that is already registered with *different* text raises immediately —
    codes are meant to be globally unique across the whole plugin, and a
    silent overwrite would make one of the two callers wrong without anyone
    noticing. Re-registering the exact same mapping (e.g. a module imported
    twice under different names in tests) is a no-op, not an error.
    """
    for code, translations in messages.items():
        existing = MESSAGES.get(code)
        if existing is not None and existing != translations:
            raise ValueError(f"message code {code!r} already registered with different text")
        MESSAGES[code] = translations


def normalize(lang: Optional[str]) -> str:
    """Map an arbitrary language tag to one of `SUPPORTED_LANGUAGES`.

    Case-insensitive. "en", "en-US", ... -> "en". "zh", "zh-CN", "zh-Hans",
    any "zh-*"/"zh_*" -> "zh-CN". Anything else, including `None` or an empty
    string, falls back to `DEFAULT_LANGUAGE` ("en").
    """
    if not lang:
        return DEFAULT_LANGUAGE
    tag = lang.strip().lower()
    if tag == "en" or tag.startswith("en-") or tag.startswith("en_"):
        return "en"
    if tag == "zh" or tag.startswith("zh-") or tag.startswith("zh_"):
        return "zh-CN"
    return DEFAULT_LANGUAGE


def _env_default() -> str:
    return normalize(os.environ.get("STUDIO_LANG"))


def configured_language() -> Optional[str]:
    """`STUDIO_LANG` normalized when it is set to something, else `None`.

    Unlike the env default used by `get_language()`, this tells "nobody chose"
    apart from an explicit "en", so the page servers can leave the language
    hint empty and let the browser language decide (see `stamp_language` in
    studio/shell/app_resources.py). Never reflects a per-request
    `set_language()`.
    """
    raw = os.environ.get("STUDIO_LANG")
    return normalize(raw) if raw and raw.strip() else None


# `None` (the sentinel default) means "nobody called set_language() in this
# context yet" — distinct from an explicit `"en"`/`"zh-CN"` — so get_language()
# can tell "not set" apart from "set to en" and fall back to the env default.
current_language: ContextVar[Optional[str]] = ContextVar("current_language", default=None)


def get_language() -> str:
    """The language in effect right now: whatever `set_language()` last set
    in this context, else `normalize(os.environ["STUDIO_LANG"])`, else "en".
    """
    value = current_language.get()
    return value if value is not None else _env_default()


def set_language(lang: Optional[str]) -> Token:
    """Set the current-context language (normalized) and return a token for
    `reset_language()`. Passing `None` explicitly sets the language to the
    normalized env default rather than leaving the previous value in place —
    callers that have "no preference" (e.g. a missing Accept-Language header)
    should call this with `None` so the context is deterministic.
    """
    return current_language.set(normalize(lang) if lang is not None else _env_default())


def reset_language(token: Token) -> None:
    current_language.reset(token)


# The q-value group is intentionally loose (`\S*`, not `[0-9.]+`): a malformed
# `q=` value (e.g. a client bug) should fall back to q=1.0 in `parse_accept_language`
# below rather than making the whole header entry fail to match and get silently
# dropped.
_ACCEPT_LANGUAGE_ITEM = re.compile(r"^\s*([^;,\s]+)\s*(?:;\s*q\s*=\s*(\S*))?\s*$")


def parse_accept_language(header: Optional[str]) -> Optional[str]:
    """Pick the best-supported language out of an `Accept-Language` header.

    Returns the normalized tag ("en" or "zh-CN") of the first entry — by
    descending q-value, ties broken by order of appearance — whose raw tag
    actually looks like an en/zh tag; entries for other languages (or `*`)
    are skipped rather than coerced. Returns `None` if the header is absent,
    empty, or names nothing we support, so the caller can fall back to the
    process-wide default instead of silently assuming English.
    """
    if not header:
        return None
    best_tag: Optional[str] = None
    best_q = -1.0
    for part in header.split(","):
        match = _ACCEPT_LANGUAGE_ITEM.match(part)
        if not match:
            continue
        raw_tag, q_str = match.group(1), match.group(2)
        if raw_tag == "*":
            continue
        lowered = raw_tag.lower()
        looks_supported = (
            lowered == "en"
            or lowered.startswith("en-")
            or lowered.startswith("en_")
            or lowered == "zh"
            or lowered.startswith("zh-")
            or lowered.startswith("zh_")
        )
        if not looks_supported:
            continue
        try:
            q = float(q_str) if q_str is not None else 1.0
        except ValueError:
            q = 1.0
        if q > best_q:
            best_q = q
            best_tag = normalize(raw_tag)
    return best_tag


class _SafeFormatDict(dict):
    """`str.format_map` helper: a missing `{placeholder}` renders back as
    literally `{placeholder}` instead of raising `KeyError`. Used by
    `render()`, which must never raise — it runs at exception-construction
    time and a formatting bug there must not shadow the real error."""

    def __missing__(self, key):  # noqa: D105
        return "{" + str(key) + "}"


def render(code: str, **params) -> str:
    """Render message `code` in the language `get_language()` currently
    reports. Falls back en -> zh-CN -> the bare code itself if `code` is
    unknown or missing a translation for every language. Never raises:
    a malformed format string (or a param that doesn't match `{}` count)
    just yields the unformatted text.
    """
    translations = MESSAGES.get(code)
    if not translations:
        return code
    lang = get_language()
    text = translations.get(lang) or translations.get("en") or translations.get("zh-CN") or code
    try:
        return text.format_map(_SafeFormatDict(params))
    except (ValueError, IndexError):
        return text


# `print_prep` is layer A (see `docs/ARCHITECTURE.md`'s "Package layout") and
# `tests/test_layering.py` forbids it from importing anything under `studio`,
# so it cannot call into this module directly and instead carries its own
# tiny, standalone copy of this catalog/render machinery in
# `print_prep/messages.py` (MESSAGES/register/render, same fallback chain).
# Wiring its `language_provider` hook to `get_language` here — the one place
# that already knows both modules exist — lets the per-request/CLI language
# chosen at this (studio) layer flow down into print_prep's own renders,
# without print_prep ever importing or knowing about `studio`. Guarded by
# `try/except ImportError` so this module keeps working standalone (e.g. a
# fresh checkout where `print_prep` has been removed, or import order during
# partial test collection).
try:
    import print_prep.messages as _print_prep_messages
except ImportError:
    pass
else:
    _print_prep_messages.language_provider = get_language
