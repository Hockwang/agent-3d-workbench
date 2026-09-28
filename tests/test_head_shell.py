import json
from pathlib import Path
import time

import numpy as np
import pytest
import trimesh

from studio.core.head_shell import head_shell, load_components, eroded_cavity, head_envelope, clearance_cutter
from studio.core.kernels.mechanical_geometry import mesh, overlap, solid
from studio.core.tasks import Tasks


def wait(tasks, task_id):
    until = time.monotonic() + 180
    while time.monotonic() < until:
        state = tasks.state(task_id, include_log=True)
        if state["status"] not in ("queued", "running", "cancelling"):
            return state
        time.sleep(0.1)
    raise AssertionError("shell task did not terminate")


def source(tmp_path):
    m = trimesh.creation.box([80, 70, 100])
    m.apply_translation([0, 0, 50])
    path = tmp_path / "box.stl"
    m.export(path)
    return path


def params():
    return {
        "target_width_mm": 80,
        "wall_mm": 3,
        "voxel_mm": 1,
        "neck_width_mm": 26,
        "neck_depth_mm": 30,
        "neck_top_mm": 20,
        "magnet_pairs": 4,
    }


def test_shell_is_open_but_material_is_watertight_and_source_unchanged(tmp_path):
    path = source(tmp_path)
    raw = path.read_bytes()
    out = tmp_path / "out"
    head_shell({"inputs": [str(path)], "params": params(), "output": str(out)})
    r = json.loads((out / "report.json").read_text())
    assert path.read_bytes() == raw and r["head_fit"]["status"] == "not_measured"
    assert r["magnet"]["magnet_count"] == 8 and r["static_collisions"] == {}
    assert max(x["overlap_mm3"] for x in r["shell_insertion_samples"]) < 1e-4
    for name in ["front_shell", "back_shell"]:
        s = trimesh.load_mesh(out / (name + ".stl"), process=True)
        assert s.is_volume and len(s.split()) == 1
        # A head-sized internal box and the bottom neck channel are void.
        probe = trimesh.creation.box([10, 10, 80])
        probe.apply_translation([0, 0, 40])
        assert overlap(solid(s), solid(probe)) < 1e-4
    assert r["neck"]["connected_to_cavity"]
    assembly = json.loads((out / "audit" / "assembly-verification.json").read_text())
    assert r["assembly"] == {
        "status": assembly["status"],
        "unresolved_parts": assembly["unresolved_parts"],
        "order": assembly["assembly_order"],
        "tested_collision_poses": assembly["tested_collision_poses"],
    }
    assert assembly["status"] == "pass_sampled"
    assert assembly["half_groups"] == {"front_shell": ["front_shell"], "back_shell": ["back_shell"]}


def test_cavity_conservative_wall_and_reject_impossible_resolution(tmp_path):
    path = source(tmp_path)
    parts, _ = load_components({"inputs": [str(path)], "params": {"target_width_mm": 80}})
    cavity, report = eroded_cavity(parts, 3, 1)
    inner = mesh(cavity)
    # On the analytic box every cavity vertex must have >=3 mm skin.
    b = parts[0].bounds
    d = np.minimum(inner.vertices - b[0], b[1] - inner.vertices).min()
    assert d >= 3
    with pytest.raises(ValueError, match="一半"):
        eroded_cavity(parts, 3, 2)


def test_bad_source_or_color_plan_rejected(tmp_path):
    path = source(tmp_path)
    with pytest.raises(ValueError, match="SHA256"):
        load_components({"inputs": [str(path)], "params": {"source_sha256": "0" * 64}})
    m = trimesh.creation.box()
    m.update_faces(np.arange(len(m.faces)) != 0)
    m.export(path)
    with pytest.raises(ValueError, match="闭合"):
        load_components({"inputs": [str(path)], "params": {}})


def test_head_circumference_and_bounded_socket_offset():
    import math

    dims = head_envelope({"head_circumference_mm": 600, "padding_mm": 10})
    a, b = (dims[:2] - 20) / 2
    assert math.pi * (3 * (a + b) - math.sqrt((3 * a + b) * (a + 3 * b))) == pytest.approx(600)
    s = solid(trimesh.creation.icosphere(subdivisions=2, radius=10))
    cutter = clearance_cutter(s, 0.25)
    assert (s - cutter).volume() < 1e-5
    with pytest.raises(ValueError):
        head_envelope({"head_circumference_mm": float("nan")})


def test_shell_template_freezes_source_and_rebuilds_magnet_size(tmp_path):
    path = source(tmp_path)
    tasks = Tasks(tmp_path / "tasks")
    first = tasks.start(
        {"template": "shell-kit", "inputs": [str(path)], "params": params(), "timeout_seconds": 180}, "ai"
    )["task"]
    done = wait(tasks, first["id"])
    assert done["status"] == "completed", done
    original = {x["name"]: x["sha256"] for x in done["artifacts"]}
    path.write_bytes(b"changed external source")
    next_task = tasks.rebuild({"id": first["id"], "params": {"magnet_diameter_mm": 8}}, "ai")["task"]
    second = wait(tasks, next_task["id"])
    assert second["status"] == "completed", second
    r = json.loads(Path(next(x["path"] for x in second["artifacts"] if x["name"] == "report.json")).read_text())
    assert r["magnet"]["hole_diameter_mm"] == 8.2
    assert {x["name"]: x["sha256"] for x in tasks.state(first["id"])["artifacts"]} == original
