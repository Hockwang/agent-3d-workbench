"""Display frozen assembly data with today's Studio viewer; never rewrite evidence."""

from __future__ import annotations

import json
from html.parser import HTMLParser

from studio.paths import APP_DIST_DIR


class _BundleParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.contract = False
        self.in_bundle = False
        self.count = 0
        self.chunks = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "html":
            self.contract = attrs.get("data-viewer-contract") == "scene-viewer-a8-skin-v1"
        if tag == "script" and attrs.get("id") == "assembly-data" and attrs.get("type") == "application/json":
            self.count += 1
            self.in_bundle = True

    def handle_endtag(self, tag):
        if tag == "script":
            self.in_bundle = False

    def handle_data(self, data):
        if self.in_bundle:
            self.chunks.append(data)


def studio_presentation(raw: bytes) -> bytes:
    """Only a recognised offline assembly bundle opts into the current template.

    Original HTML remains the default download/resource. Executable code and CSS
    from an old report are not carried into this derived presentation. The entire
    JSON bundle (including curationEnabled, provenance and assets) is preserved.
    """
    if b"data-viewer-contract" not in raw[:1024]:
        return raw
    try:
        parser = _BundleParser()
        parser.feed(raw.decode("utf-8"))
        if not parser.contract or parser.count != 1:
            return raw
        bundle = json.loads("".join(parser.chunks))
        if (
            not isinstance(bundle, dict)
            or not isinstance(bundle.get("resources"), dict)
            or not isinstance(bundle.get("assets"), dict)
        ):
            return raw
        index = bundle["resources"].get("api/index.json")
        if not isinstance(index, dict) or not isinstance(index.get("cases"), list):
            return raw
        # Do not allow a title containing </script> to become executable markup.
        payload = json.dumps(bundle, ensure_ascii=True, allow_nan=False).replace("<", "\\u003c")
    except (UnicodeError, ValueError, TypeError):
        return raw
    template = (APP_DIST_DIR / "assembly-review.html").read_text()
    return template.replace("__ASSEMBLY_REVIEW_DATA__", payload).encode()
