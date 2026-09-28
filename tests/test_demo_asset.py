"""`examples/demo/make_demo_parts.py` builds the only redistributable demo
asset in the repo (the head-shell example is bound to a user-provided STL).
This locks its contract: 5 named watertight parts, correct mm extents, a GLB
that imports with the right node names, and byte-identical output across
runs (no randomness, no timestamps).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import trimesh

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "examples" / "demo" / "make_demo_parts.py"

# mm, Z up — mirrors the design constants documented in make_demo_parts.py.
EXPECTED_EXTENTS_MM = {
    "body": (40.0, 40.0, 45.0),
    "handle": (14.0, 8.0, 23.0),
    "lid": (42.0, 42.0, 3.0),
    "knob": (8.0, 8.0, 8.0),
    "base": (60.0, 60.0, 3.0),
}


def _run(out_dir: Path) -> dict:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--out", str(out_dir)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_build_produces_five_named_watertight_parts(tmp_path):
    payload = _run(tmp_path / "demo")

    names = {part["name"] for part in payload["parts"]}
    assert names == set(EXPECTED_EXTENTS_MM)
    assert len(payload["parts"]) == 5

    for part in payload["parts"]:
        assert part["watertight"] is True
        expected = EXPECTED_EXTENTS_MM[part["name"]]
        actual = part["extents_mm"]
        assert len(actual) == 3
        for got, want in zip(actual, expected):
            assert got == pytest.approx(want, abs=1.0), (part["name"], actual, expected)


def test_build_writes_glb_with_matching_named_geometries(tmp_path):
    payload = _run(tmp_path / "demo")

    glb_path = Path(payload["glb"])
    assert glb_path.is_file()
    assert payload["glb_bytes"] == glb_path.stat().st_size

    scene = trimesh.load(str(glb_path), process=False)
    assert isinstance(scene, trimesh.Scene)
    assert set(scene.graph.nodes_geometry) == set(EXPECTED_EXTENTS_MM)
    assert len(scene.geometry) == 5


def test_build_is_deterministic(tmp_path):
    payload_a = _run(tmp_path / "run_a")
    payload_b = _run(tmp_path / "run_b")

    for name in EXPECTED_EXTENTS_MM:
        stl_a = (Path(payload_a["out"]) / "parts" / f"{name}.stl").read_bytes()
        stl_b = (Path(payload_b["out"]) / "parts" / f"{name}.stl").read_bytes()
        assert stl_a == stl_b, f"{name}.stl differs between runs"

    glb_a = Path(payload_a["glb"]).read_bytes()
    glb_b = Path(payload_b["glb"]).read_bytes()
    assert glb_a == glb_b


def test_glb_imports_into_the_editor_with_mm_z_up_bounds(tmp_path):
    """The GLB is written in glTF metres / Y-up; after the workbench's own import
    it must come back as millimetres / Z-up in the designed positions. This is
    the check that would catch a wrong axis rotation or scale factor, which the
    STL-only assertions above cannot see."""
    import json
    import subprocess
    import sys
    from pathlib import Path

    repo = Path(__file__).resolve().parents[1]
    out = tmp_path / "out"
    subprocess.run(
        [sys.executable, str(repo / "examples/demo/make_demo_parts.py"), "--out", str(out)],
        check=True,
        capture_output=True,
        text=True,
        cwd=repo,
    )
    doc = tmp_path / "ws"
    apply = subprocess.run(
        [
            sys.executable,
            "-m",
            "studio.core",
            "editor",
            "apply",
            "--doc",
            str(doc),
            "--action",
            "import",
            "--params",
            json.dumps({"files": [str(out / "demo-parts.glb")]}),
        ],
        check=True,
        capture_output=True,
        text=True,
        cwd=repo,
    )
    assert json.loads(apply.stdout)["ok"] is True
    inspect = subprocess.run(
        [sys.executable, "-m", "studio.core", "editor", "inspect", "--doc", str(doc)],
        check=True,
        capture_output=True,
        text=True,
        cwd=repo,
    )
    objects = {o["name"]: o for o in json.loads(inspect.stdout)["objects"]}
    assert set(objects) == {"body", "handle", "lid", "knob", "base"}
    # z ranges (mm): base sits on the floor, body on the base, lid on the body, knob on the lid
    expected_z = {"base": (0, 3), "body": (3, 48), "lid": (48, 51), "knob": (51, 59)}
    for name, (lo, hi) in expected_z.items():
        (_, _, zmin), (_, _, zmax) = objects[name]["bounds_mm"]
        assert abs(zmin - lo) < 0.5 and abs(zmax - hi) < 0.5, (name, zmin, zmax)
    # the handle hangs off the +X side of the body and is centred in Y
    (xmin, ymin, _), (xmax, ymax, _) = objects["handle"]["bounds_mm"]
    assert 17 < xmin < 19 and 31 < xmax < 33, (xmin, xmax)
    assert abs(ymin + ymax) < 0.5, (ymin, ymax)
