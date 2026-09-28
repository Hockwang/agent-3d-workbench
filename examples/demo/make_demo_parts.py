"""Build the redistributable "5-part mug" demo asset.

Units are millimetres, Z up (this repo's workspace convention, see
`studio/core/editor.py`). Every dimension below is a literal constant, every
solid comes out of `manifold3d` booleans (no randomness, no timestamps), so
running this script twice produces byte-identical output. Geometry is built
with the shared kernel helpers in `studio/core/kernels/mechanical_geometry.py`
(`box`/`cyl`/`ball`/`union`/`mesh`) rather than duplicating boolean plumbing.

Usage: `uv run python examples/demo/make_demo_parts.py --out <dir>` (default
`examples/demo/out`, relative to this file).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import trimesh

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from studio.core.kernels.mechanical_geometry import ball, box, cyl, mesh, union  # noqa: E402

# --- design constants (mm, Z up) --------------------------------------------
# All parts are centred on the origin in XY except `handle`. `base` sits with
# its bottom at z=0; every other part stacks on top of it.

BASE_SIZE = 60.0
BASE_THICK = 3.0

BODY_OUTER_R = 20.0  # outer Ø40
BODY_WALL = 2.5
BODY_HEIGHT = 45.0
BODY_Z0 = BASE_THICK
BODY_Z1 = BODY_Z0 + BODY_HEIGHT

LID_OUTER_R = 21.0  # outer Ø42
LID_THICK = 3.0
LID_Z0 = BODY_Z1
LID_Z1 = LID_Z0 + LID_THICK

KNOB_R = 4.0  # Ø8
KNOB_CENTER = (0.0, 0.0, LID_Z1 + KNOB_R)

# `handle` is a squared-off "C"/staple bracket on the +X side of `body`: a
# top bar and a bottom bar reach out from inside the body wall to an outer
# bridge, leaving the grip gap open toward the body (-X), like a mug handle.
HANDLE_X0 = BODY_OUTER_R - 2.0  # 2 mm into the body wall, so it visibly attaches
HANDLE_X1 = 32.0
HANDLE_BRIDGE_X0 = 29.0
HANDLE_HALF_Y = 4.0
HANDLE_BAR_THICK = 3.0
HANDLE_Z0 = 14.0
HANDLE_Z1 = 37.0

MAX_TOTAL_FACES = 60_000

# --- geometry ----------------------------------------------------------------


def build_base() -> trimesh.Trimesh:
    half = BASE_SIZE / 2
    return mesh(box([-half, -half, 0.0], [half, half, BASE_THICK]))


def build_body() -> trimesh.Trimesh:
    outer = cyl(BODY_OUTER_R, BODY_Z0, BODY_Z1)
    inner_r = BODY_OUTER_R - BODY_WALL
    floor_top = BODY_Z0 + BODY_WALL
    # Overshoot the inner cylinder past the outer top so the boolean leaves
    # an open rim instead of a capped top.
    inner = cyl(inner_r, floor_top, BODY_Z1 + 1.0)
    return mesh(outer - inner)


def build_lid() -> trimesh.Trimesh:
    return mesh(cyl(LID_OUTER_R, LID_Z0, LID_Z1))


def build_knob() -> trimesh.Trimesh:
    return mesh(ball(KNOB_R).translate(KNOB_CENTER))


def build_handle() -> trimesh.Trimesh:
    top_bar = box(
        [HANDLE_X0, -HANDLE_HALF_Y, HANDLE_Z1 - HANDLE_BAR_THICK],
        [HANDLE_X1, HANDLE_HALF_Y, HANDLE_Z1],
    )
    bottom_bar = box(
        [HANDLE_X0, -HANDLE_HALF_Y, HANDLE_Z0],
        [HANDLE_X1, HANDLE_HALF_Y, HANDLE_Z0 + HANDLE_BAR_THICK],
    )
    bridge = box(
        [HANDLE_BRIDGE_X0, -HANDLE_HALF_Y, HANDLE_Z0],
        [HANDLE_X1, HANDLE_HALF_Y, HANDLE_Z1],
    )
    return mesh(union([top_bar, bottom_bar, bridge]))


def build_parts() -> dict[str, trimesh.Trimesh]:
    return {
        "body": build_body(),
        "handle": build_handle(),
        "lid": build_lid(),
        "knob": build_knob(),
        "base": build_base(),
    }


# --- glTF export --------------------------------------------------------------
# The workbench stores assets as GLB in raw glTF units (metres, Y up) and
# converts to/from its own workspace convention (millimetres, Z up) on
# import/export — see `GLTF_TO_WORKSPACE`/`WORKSPACE_TO_GLTF` in
# `studio/core/editor.py` and the `factor = 1000 if gltf else 1` branch in
# `studio.core.editor_actions.import_files`. To make a GLB that round-trips
# back to the millimetre design above, bake the inverse of that conversion
# (rotate Z up -> Y up, scale mm -> m) into each part's vertices before
# writing it, so every node's own transform can stay the glTF-export default
# (identity).


def _bake_to_gltf_frame(part: trimesh.Trimesh) -> trimesh.Trimesh:
    baked = part.copy()
    transform = trimesh.transformations.rotation_matrix(-np.pi / 2, [1.0, 0.0, 0.0])
    transform[:3] *= 0.001
    baked.apply_transform(transform)
    return baked


def write_glb(parts: dict[str, trimesh.Trimesh], path: Path) -> int:
    scene = trimesh.Scene()
    for name, part in parts.items():
        scene.add_geometry(_bake_to_gltf_frame(part), node_name=name, geom_name=f"{name}_geom")
    raw = scene.export(file_type="glb")
    path.write_bytes(raw)
    return len(raw)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path(__file__).resolve().parent / "out")
    args = parser.parse_args()

    out_dir: Path = args.out
    parts_dir = out_dir / "parts"
    parts_dir.mkdir(parents=True, exist_ok=True)

    parts = build_parts()
    if sum(len(part.faces) for part in parts.values()) > MAX_TOTAL_FACES:
        raise RuntimeError("demo asset exceeded the 60k total face budget")

    summary = []
    for name, part in parts.items():
        stl_path = parts_dir / f"{name}.stl"
        stl_path.write_bytes(part.export(file_type="stl"))
        reloaded = trimesh.load(str(stl_path), force="mesh")
        if not reloaded.is_watertight or reloaded.volume <= 0:
            raise RuntimeError(f"part {name!r} is not a watertight, positive-volume solid")
        summary.append(
            {
                "name": name,
                "faces": int(len(part.faces)),
                "watertight": bool(reloaded.is_watertight),
                "extents_mm": [round(float(v), 3) for v in part.extents],
            }
        )

    glb_path = out_dir / "demo-parts.glb"
    glb_bytes = write_glb(parts, glb_path)

    print(
        json.dumps(
            {
                "out": str(out_dir),
                "parts": summary,
                "glb": str(glb_path),
                "glb_bytes": glb_bytes,
            }
        )
    )


if __name__ == "__main__":
    main()
