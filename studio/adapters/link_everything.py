"""Read a generated connection-design artifact without importing its CAD environment."""

from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.parse import unquote, urlsplit


class AssemblyProjectError(ValueError):
    def __init__(self, code: str, message: str, status: int = 409):
        super().__init__(message)
        self.code = code
        self.status = status


def project(source: str) -> dict:
    """Return a local GLB handoff; credentials and other project data stay private."""
    locations = {
        "legacy": ("project.json", "revisions"),
        "manual": ("manual/project.json", "manual/revisions"),
        "presets": ("presets/project.json", "presets/revisions"),
    }
    if source not in locations:
        raise AssemblyProjectError("bad_source", "Unknown connection-design source.", 400)
    default = Path(__file__).resolve().parents[2] / "experiments" / "link-everything"
    root = Path(os.environ.get("LINK_EVERYTHING_ROOT", str(default))).resolve()
    state_name, revisions_name = locations[source]
    outputs = root / "outputs"
    try:
        state = json.loads((outputs / state_name).read_text(encoding="utf-8"))
        artifact = next(item for item in state["artifacts"] if item["id"] == "assembly.glb")
        url = urlsplit(artifact["url"])
        if url.scheme or url.netloc or url.query or url.fragment:
            raise ValueError("Expected a local artifact.")
        file = (root / unquote(url.path).lstrip("/")).resolve()
        revision_root = (outputs / revisions_name).resolve()
        if not file.is_relative_to(revision_root) or not file.is_file() or file.suffix.lower() != ".glb":
            raise ValueError("Invalid artifact.")
        revision = state["revision"]
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
            raise ValueError("Invalid revision.")
    except (OSError, ValueError, KeyError, TypeError, StopIteration) as exc:
        raise AssemblyProjectError(
            "assembly_not_ready", "Generate a valid connection-design revision before importing."
        ) from exc
    return {
        "revision": revision,
        "preset_id": state.get("preset_id"),
        "source": source,
        "import_file": str(file),
        "units": "m",
    }
