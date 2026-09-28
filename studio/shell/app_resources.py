"""MCP App resources. Preview geometry never replaces the printing mesh on disk."""

from __future__ import annotations

import base64
import hashlib
import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

import numpy as np

from print_prep import job, mesh_io
from studio.core.editor import _KERNEL_LOCK

UI_MIME = "text/html;profile=mcp-app"
from studio.i18n import configured_language
from studio.paths import APP_DIST_DIR

UI_PATH = APP_DIST_DIR / "studio.html"
LANGUAGE_META = '<meta name="studio-language" content="">'


def stamp_language(html: bytes) -> bytes:
    """Tell the page which language this server was started with.

    studio/web/i18n.js reads `<meta name="studio-language">` before it renders
    anything, so the panel follows an explicit STUDIO_LANG (the install-time
    choice) unless the person toggled a language in that browser. With no
    STUDIO_LANG set the placeholder stays empty and the page falls back to the
    browser language. Used for the browser page (studio/shell/server.py) and
    the MCP App bundle (`ui_html` below); a page without the placeholder is
    returned unchanged.
    """
    lang = configured_language()
    if not lang:
        return html
    return html.replace(LANGUAGE_META.encode(), LANGUAGE_META.replace('""', f'"{lang}"').encode(), 1)


LEGACY_UI_URI = "ui://print-prep/studio-v6.html"


def ui_resource_uri(html: str) -> str:
    """The host caches templates by URI, independently of plugin version."""
    digest = hashlib.sha256(html.encode()).hexdigest()[:20]
    return f"ui://print-prep/studio-{digest}.html"


@dataclass(frozen=True)
class UiBundle:
    html: str
    uri: str


def load_ui() -> UiBundle:
    """Read a single build snapshot, not one frozen at server startup.

    MCP connections can outlive plugin updates. Opening/listing the UI is rare;
    reading here avoids serving an old bundle until the whole host restarts.
    The build publishes via atomic rename, keeping bytes and hash consistent.
    """
    html = UI_PATH.read_text()
    return UiBundle(html, ui_resource_uri(html))


def ui_html(uri: str) -> str | None:
    """Hash is a host cache-buster, not an immutable artifact contract.

    Historical launcher addresses remain compatibility aliases for the current
    bundle. This also works when the plugin manager deletes the old package.
    """
    parsed = urlsplit(uri)
    address = parsed._replace(query="", fragment="").geturl()
    if parsed.fragment or not (
        address == LEGACY_UI_URI or re.fullmatch(r"ui://print-prep/studio-[a-f0-9]{20}\.html", address)
    ):
        return None
    from studio.core.workspaces import validate_id

    workspace_id = parse_qs(parsed.query).get("workspace", [""])[0]
    if workspace_id:
        validate_id(workspace_id)
    html = load_ui().html.replace('data-workspace-id=""', f'data-workspace-id="{workspace_id}"', 1)
    return stamp_language(html.encode()).decode()


def workspace_ui_uri(workspace_id: str, bundle: UiBundle | None = None) -> str:
    from studio.core.workspaces import validate_id

    return (bundle or load_ui()).uri + "?workspace=" + validate_id(workspace_id)


def widget_session_id(job_dir: str, bundle: UiBundle | None = None) -> str:
    """Reuse a live workspace only while both the job and UI build match."""
    key = json.dumps([job_dir, (bundle or load_ui()).uri], ensure_ascii=False)
    return "print-prep-" + hashlib.sha256(key.encode()).hexdigest()[:24]


PREVIEW_FACE_LIMIT = 30_000
_preview_lock = _KERNEL_LOCK  # Shared with editing: fast-simplification is not reentrant.


def read_preview(uri: str, job_dir: str) -> dict:
    parsed = urlsplit(uri)
    if parsed.scheme != "print-prep" or parsed.netloc != "preview" or parsed.fragment:
        raise ValueError("Unsupported preview resource URI")
    name = unquote(parsed.path.removeprefix("/"))
    version = parse_qs(parsed.query).get("v", [None])[0]
    parts = job.load_job(Path(job_dir)).get("inspect", {}).get("parts", [])
    part = next((p for p in parts if p["name"] == name), None)
    if part is None:
        raise ValueError("Part is not in the current job")
    path = Path(part["stl_path"]).resolve()
    stat = path.stat()
    if version != str(stat.st_mtime_ns):
        raise ValueError("Preview is stale; refresh the current job")
    with _preview_lock:
        return _make_preview(str(path), stat.st_mtime_ns, stat.st_size)


@lru_cache(maxsize=8)
def _make_preview(path: str, mtime_ns: int, size: int) -> dict:
    mesh = mesh_io.load_part_stl(path)
    original_faces = len(mesh.faces)
    if original_faces > PREVIEW_FACE_LIMIT:
        mesh = mesh.simplify_quadric_decimation(face_count=PREVIEW_FACE_LIMIT)
    vertices = np.asarray(mesh.vertices, dtype="<f4")
    faces = np.asarray(mesh.faces, dtype="<u4")
    if not np.isfinite(vertices).all() or len(faces) > PREVIEW_FACE_LIMIT:
        raise ValueError("Cannot produce a bounded mesh preview")
    # Detect an overlapping load: don't pair a new file with an old version key.
    stat = Path(path).stat()
    if stat.st_mtime_ns != mtime_ns or stat.st_size != size:
        raise ValueError("Mesh changed while preparing preview; refresh")
    return {
        "positions": base64.b64encode(vertices.tobytes()).decode("ascii"),
        "indices": base64.b64encode(faces.tobytes()).decode("ascii"),
        "original_faces": original_faces,
        "preview_faces": len(faces),
        "preview_only": True,
    }


def preview_json(uri: str, job_dir: str) -> str:
    return json.dumps(read_preview(uri, job_dir), separators=(",", ":"))
