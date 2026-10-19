"""Single opaque color intent per solid, kept outside lossy STL geometry."""

from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np

from . import mesh_io


def normalize_color(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
        raise ValueError("Part colors must be opaque #RRGGBB values")
    return value.upper()


def uniform_mesh_color(mesh) -> str | None:
    """Only explicit uniform colors; never average textures or synthesize defaults."""
    visual = mesh.visual
    if visual.kind in ("face", "vertex") and visual.defined:
        colors = visual.face_colors if visual.kind == "face" else visual.vertex_colors
        if len(colors) and np.all(colors == colors[0]) and colors[0][3] == 255:
            return "#" + "".join(f"{int(c):02X}" for c in colors[0][:3])
    if visual.kind == "texture":
        mat = visual.material
        if getattr(mat, "baseColorTexture", None) is not None or getattr(mat, "image", None) is not None:
            return None
        rgba = getattr(mat, "baseColorFactor", None)
        if rgba is not None and len(rgba) == 4 and rgba[3] == 255:
            return "#" + "".join(f"{int(c):02X}" for c in rgba[:3])
    return None


def write_stl_color(path: Path, color: str) -> None:
    path.with_suffix(path.suffix + ".color.json").write_text(
        json.dumps({"version": 1, "stl_sha256": mesh_io.sha256_file(path), "color": normalize_color(color)}),
        encoding="utf-8",
    )


def read_stl_color(path: Path) -> str | None:
    sidecar = path.with_suffix(path.suffix + ".color.json")
    if not sidecar.exists():
        return None
    data = json.loads(sidecar.read_text(encoding="utf-8"))
    if data.get("version") != 1 or data.get("stl_sha256") != mesh_io.sha256_file(path):
        raise ValueError(f"Stale or unsupported STL color manifest: {sidecar}")
    return normalize_color(data["color"])
