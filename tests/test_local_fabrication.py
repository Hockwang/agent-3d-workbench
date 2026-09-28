"""Real solid geometry checks for the local fabrication task contracts."""

import hashlib
import json
from pathlib import Path
import numpy as np
import pytest
import trimesh

from studio.core.fabrication import run
from studio.core.editor import EditorError
from studio.core.task_operations import deliver, assembly_audit_urdf


def source_scene(tmp_path, meshes):
    source = tmp_path / "source"
    source.mkdir()
    deliver(meshes, source, {}, stl=False)
    return source / "scene.glb"


def box(center, size):
    return trimesh.creation.box(extents=size).apply_translation(center)


def workbench(tmp_path, inputs, params):
    out = tmp_path / "out"
    out.mkdir()
    return {"inputs": list(map(str, inputs)), "output": str(out), "params": params}


def report(w):
    return json.loads(Path(w["output"], "report.json").read_text())


def connection_case(tmp_path):
    source = source_scene(tmp_path, {"lower": box([0, 0, -5], [30, 30, 10]), "upper": box([0, 0, 5], [30, 30, 10])})
    return workbench(
        tmp_path,
        [source],
        {"parts": ["lower", "upper"], "connectors": [{"center_mm": [0, 0, 0], "axis": [0, 0, 1], "depth_mm": 4}]},
    )


@pytest.mark.parametrize("profile", ["round", "keyed"])
def test_connect_real_sockets_pins_clearance_and_readback(tmp_path, profile):
    w = connection_case(tmp_path)
    w["params"]["connectors"][0]["profile"] = profile
    before = hashlib.sha256(Path(w["inputs"][0]).read_bytes()).hexdigest()
    run("connect-parts", w)
    r = report(w)
    assert r["status"] == "pass" and len(r["parts"]) == 3
    assert r["connectors"][0]["anti_rotation"] == (profile == "keyed")
    assert r["connectors"][0]["min_hole_wall_mm_lower_bound"] == 1.6
    assert all(s["overlap_mm3"] < 1e-6 for s in r["withdrawal_samples"])
    assert hashlib.sha256(Path(w["inputs"][0]).read_bytes()).hexdigest() == before
    pin = trimesh.load_mesh(Path(w["output"]) / "pin_00.stl")
    assert pin.is_volume and np.isclose(pin.extents[2], 7.6, atol=1e-5)


def test_connect_rejects_thin_walls_and_no_artifacts(tmp_path):
    w = connection_case(tmp_path)
    w["params"]["connectors"][0]["center_mm"] = [14, 0, 0]
    with pytest.raises(EditorError, match="socket_wall_envelope"):
        run("connect-parts", w)
    assert not list(Path(w["output"]).iterdir())


def test_later_connector_cannot_consume_earlier_thick_wall(tmp_path):
    w = connection_case(tmp_path)
    w["params"]["connectors"] = [
        {"center_mm": [-3, 0, 0], "axis": [0, 0, 1], "depth_mm": 4, "min_wall_mm": 4},
        {"center_mm": [3, 0, 0], "axis": [0, 0, 1], "depth_mm": 4, "min_wall_mm": 1},
    ]
    with pytest.raises(EditorError, match="final_socket_wall_envelope"):
        run("connect-parts", w)
    assert not list(Path(w["output"]).iterdir())


def test_color_inlays_are_closed_and_remove_from_real_host(tmp_path):
    m = box([0, 0, 0], [20, 20, 10])
    # glTF stores vertex colors. Distinct face colors need split seam vertices;
    # sharing them averages red and blue during export, changing the fixture.
    m.unmerge_vertices()
    m.visual.face_colors = [0, 0, 255, 255]
    m.visual.face_colors[m.face_normals[:, 2] > 0.9] = [255, 0, 0, 255]
    source = source_scene(tmp_path, {"colored": m})
    w = workbench(tmp_path, [source], {"palette_rgb": [[0, 0, 255], [255, 0, 0]], "pull_direction": [0, 0, 1]})
    run("color-inlays", w)
    r = report(w)
    assert r["status"] == "pass" and len(r["regions"]) == 1
    assert all(x["watertight"] for x in r["parts"])
    assert all(x["overlap_mm3"] < 1e-6 for x in r["removal_samples"])
    insert = trimesh.load_mesh(Path(w["output"]) / "color_01_00.stl")
    assert np.isclose(insert.volume, 20 * 20 * 1.2, atol=0.01)
    assert r["source_textures_preserved"] is False
    w["params"]["pull_direction"] = [0, 0, -1]
    with pytest.raises(EditorError, match="outward_facing_color_patches"):
        run("color-inlays", w)


def test_uv_texture_sampling_and_palette_mismatch(tmp_path):
    from PIL import Image

    m = box([0, 0, 0], [20, 20, 10])
    m.unmerge_vertices()
    uv = np.tile([0.25, 0.5], (len(m.vertices), 1))
    uv[np.repeat(m.face_normals[:, 2] > 0.9, 3), 0] = 0.75
    image = Image.fromarray(np.array([[[0, 0, 255, 255], [255, 0, 0, 255]]] * 2, dtype=np.uint8))
    m.visual = trimesh.visual.texture.TextureVisuals(uv=uv, image=image)
    source = source_scene(tmp_path, {"textured": m})
    w = workbench(tmp_path, [source], {"palette_rgb": [[0, 0, 255], [255, 0, 0]], "pull_direction": [0, 0, 1]})
    run("color-inlays", w)
    assert len(report(w)["regions"]) == 1
    assert np.isclose(trimesh.load_mesh(Path(w["output"]) / "color_01_00.stl").volume, 480, atol=0.01)
    w["params"]["palette_rgb"][1] = [0, 255, 0]
    with pytest.raises(EditorError, match="palette_color_distance"):
        run("color-inlays", w)


def test_concave_color_patch_remains_one_solid_after_extrusion(tmp_path):
    from scripts.verify_user_journeys import BADGE

    source = tmp_path / "source"
    source.mkdir()
    exec(BADGE, {"workbench": {"output": str(source)}})
    w = workbench(
        tmp_path,
        [source / "scene.glb"],
        {
            "palette_rgb": [[0, 70, 180], [230, 40, 40]],
            "pull_direction": [0, 0, 1],
            "depth_mm": 2.2,
            "clearance_mm": 0.2,
        },
    )
    run("color-inlays", w)
    r = report(w)
    assert r["status"] == "pass" and len(r["regions"]) == 1
    insert = trimesh.load_mesh(Path(w["output"]) / "color_01_00.stl")
    assert insert.is_volume and len(insert.split()) == 1
    assert np.isclose(insert.volume, (12 * 32 * 2 - 12 * 12) * 2.2, atol=0.001)


JOINT_CASES = [
    ("pin_hinge", [[-25, 0, 0], [30, 0, 0]]),
    ("slew", [[-20, 0, -1.5], [20, 0, 2.2]]),
    ("slider", [[0, -20, 0], [0, 20, 0]]),
    ("ball_socket", [[-22, 0, -2], [22, 0, 0]]),
]


@pytest.mark.parametrize("family,anchors", JOINT_CASES)
def test_joint_installs_into_actual_hosts_and_preserves_outside_zone(tmp_path, family, anchors):
    source = source_scene(tmp_path, {"fixed": box(anchors[0], [8, 8, 8]), "moving": box(anchors[1], [8, 8, 8])})
    w = workbench(
        tmp_path,
        [source],
        {
            "parts": ["fixed", "moving"],
            "family": family,
            "center_mm": [0, 0, 0],
            "axis": [0, 0, 1],
            "anchors_mm": anchors,
            "machining_box_mm": [[-40, -40, -20], [40, 40, 20]],
            "mount_radius_mm": 0.75,
        },
    )
    run("install-joint", w)
    r = report(w)
    assert r["status"] == "pass" and len(r["parts"]) >= 2
    assert all(part["watertight"] for part in r["parts"])
    assert all(pair["overlap_mm3"] < 1e-6 for pair in r["rest_collisions"])
    assert all(change["outside_zone_changed_mm3"] == 0 for change in r["changes"])
    assert r["travel_checked"] is False and r["holding_strength_verified"] is False
    joints = 3 if family == "ball_socket" else 1
    rest = assembly_audit_urdf(
        Path(w["output"]) / "assembly.urdf",
        {"sampling": "explicit", "configurations": [{f"joint_{i}": 0 for i in range(joints)}]},
    )
    assert rest["status"] == "pass" and len(rest["objects"]) == 2
    if family == "ball_socket":
        sweep = assembly_audit_urdf(Path(w["output"]) / "assembly.urdf", {"sampling": "grid", "steps": 5})
        assert sweep["status"] == "pass" and len(sweep["samples"]) == 125
    if family == "slew":
        import xml.etree.ElementTree as ET

        urdf = ET.parse(Path(w["output"]) / "assembly.urdf")
        moving_files = {m.get("filename") for m in urdf.findall("link[@name='child']/visual/geometry/mesh")}
        assert moving_files == {"child.stl", "retaining_cap.stl"}
    w["params"]["machining_box_mm"] = [[-1, -1, -1], [1, 1, 1]]
    with pytest.raises(EditorError, match="machining_zone"):
        run("install-joint", w)


@pytest.mark.parametrize("family,anchors", [JOINT_CASES[0], JOINT_CASES[3]])
def test_exported_joint_frame_matches_machined_meshes_and_motion(tmp_path, family, anchors):
    from studio.core.kernels.mechanical_geometry import frame
    from yourdfpy import URDF

    center = np.array([41, -27, 13])
    rotation = frame([1, 2, 3])
    transform = np.eye(4)
    transform[:3, :3], transform[:3, 3] = rotation, center
    meshes = {name: box(a, [8, 8, 8]).apply_transform(transform) for name, a in zip(["fixed", "moving"], anchors)}
    source = source_scene(tmp_path, meshes)
    w = workbench(
        tmp_path,
        [source],
        {
            "parts": ["fixed", "moving"],
            "family": family,
            "center_mm": center.tolist(),
            "axis": rotation[:, 2].tolist(),
            "x_hint": rotation[:, 0].tolist(),
            "anchors_mm": [(rotation @ a + center).tolist() for a in anchors],
            "machining_box_mm": [[-100, -100, -100], [100, 100, 100]],
            "mount_radius_mm": 0.75,
        },
    )
    run("install-joint", w)
    out = Path(w["output"])
    robot = URDF.load(str(out / "assembly.urdf"))
    all_meshes = {p.stem: trimesh.load_mesh(p) for p in out.glob("*.stl")}
    assert np.allclose(robot.scene.bounds * 1000, trimesh.util.concatenate(list(all_meshes.values())).bounds, atol=1e-4)
    robot.update_cfg({"joint_0": 0.1})
    axis = rotation[:, 0] if family == "ball_socket" else rotation[:, 2]
    all_meshes["child"].apply_transform(trimesh.transformations.rotation_matrix(0.1, axis, center))
    assert np.allclose(robot.scene.bounds * 1000, trimesh.util.concatenate(list(all_meshes.values())).bounds, atol=1e-4)


def mixed_urdf(tmp_path):
    box([0, 0, 0], [0.1, 0.1, 0.1]).export(tmp_path / "cube.stl")
    path = tmp_path / "mixed.urdf"
    links = "".join(
        f'<link name="{name}"><visual><origin xyz="{origin}"/><geometry><mesh filename="cube.stl"/></geometry></visual></link>'
        for name, origin in [("base", "10 10 10"), ("a", "0 0 0"), ("b", "0 0 0")]
    )
    joints = "".join(
        f'<joint name="{name}" type="prismatic"><parent link="base"/><child link="{name}"/><origin xyz="{origin}"/><axis xyz="{axis}"/><limit lower="0" upper="2" effort="1" velocity="1"/></joint>'
        for name, origin, axis in [("a", "0 0 0", "1 0 0"), ("b", "1 0 0", "0 1 0")]
    )
    path.write_text(f'<robot name="mixed">{links}{joints}</robot>')
    return path


def test_combined_grid_finds_collision_diagonal_misses(tmp_path):
    path = mixed_urdf(tmp_path)
    assert assembly_audit_urdf(path, {"steps": 3})["status"] == "pass"
    w = workbench(tmp_path, [path], {"steps": 3})
    run("motion-check", w)
    r = report(w)
    assert r["status"] == "fail" and r["sweep"] == "grid" and len(r["samples"]) == 9
    hit = next(s for s in r["samples"] if s["configuration"] == {"a": 1, "b": 0})
    assert hit["collisions"] and hit["collisions"][0]["overlap_mm3"] > 999999
    assert {"a": 1, "b": 0} not in r["clear_configurations"]
    assert r["continuous_motion_checked"] is False and r["retention_checked"] is False


def test_explicit_configurations_and_bounded_work(tmp_path):
    path = mixed_urdf(tmp_path)
    w = workbench(tmp_path, [path], {"sampling": "explicit", "configurations": [{"a": 0, "b": 0}, {"a": 2, "b": 2}]})
    run("motion-check", w)
    assert report(w)["status"] == "pass"
    for params in [
        {"steps": 101},
        {"sampling": "explicit", "configurations": [{"a": 1}]},
        {"sampling": "explicit", "configurations": [{"a": 3, "b": 0}]},
    ]:
        w["params"] = params
        with pytest.raises(EditorError):
            run("motion-check", w)
