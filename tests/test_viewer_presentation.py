import json
import re

from studio.core.viewer_presentation import studio_presentation


def old_report(bundle):
    payload = json.dumps(bundle).replace("<", "\\u003c")
    return (
        '<html data-viewer-contract="scene-viewer-a8-skin-v1"><head>'
        "<style>body{background:old-paper}</style></head><body>"
        f'<script type="application/json" id="assembly-data">{payload}</script>'
        "<script>oldViewer()</script></body></html>"
    ).encode()


def test_old_report_uses_current_presentation_without_changing_evidence(tmp_path):
    bundle = {
        "resources": {
            "api/index.json": {"cases": [], "curationEnabled": False},
            "scene.json": {"title": "</script><script>evil()</script>", "contentSha256": "frozen-evidence"},
        },
        "assets": {"mesh.glb": {"mime": "model/gltf-binary", "data": "AAEC"}},
    }
    path = tmp_path / "index.html"
    raw = old_report(bundle)
    path.write_bytes(raw)
    presented = studio_presentation(path.read_bytes()).decode()
    assert path.read_bytes() == raw
    assert "old-paper" not in presented and "oldViewer()" not in presented
    assert "evil()</script>" not in presented
    assert "--bg-card: rgba(16,16,18,.86)" in presented
    payload = re.search(r'id="assembly-data">(.*?)</script>', presented, re.S)[1]
    assert json.loads(payload) == bundle  # Assets, permission, hash and provenance all survive.


def test_unrecognised_or_malformed_reports_remain_unchanged():
    for raw in [
        b"<html><script>customReport()</script></html>",
        old_report({"resources": {}, "assets": {}}),
        old_report({"resources": {"api/index.json": {"cases": []}}, "assets": {}}).replace(
            b"assembly-data", b"other-data"
        ),
        old_report({"resources": {"api/index.json": {"cases": []}}, "assets": {}}).replace(
            b'"cases": []', b"broken json"
        ),
    ]:
        assert studio_presentation(raw) == raw
