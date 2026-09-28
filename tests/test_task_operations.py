import hashlib
import json
import math
from pathlib import Path
import numpy as np
import pytest
import trimesh
from studio.core.task_operations import face_split, laser_slices, asset_preview
from studio.core.geometry_store import encode
from studio.core.task_operations import relief, assembly_audit, interactive_scene, removal_audit


def workbench(tmp_path, inputs, params=None):
    out = tmp_path / "out"
    out.mkdir()
    return {"inputs": [str(p) for p in inputs], "output": str(out), "params": params or {}}


def urdf_fixture(tmp_path, joint_type, limit=None):
    """A 2-link, 1-joint URDF (metres, per the URDF convention): a static
    `parent_link` box off to one side and a `child_link` rod hanging from a
    hinge at the world origin. At rest the rod is clear of the parent box;
    swinging it far enough (see the module-level probe in the PR that picked
    these numbers) drives it into the parent box's far side."""
    trimesh.creation.box(extents=[10, 10, 10]).export(tmp_path / "parent.stl")
    trimesh.creation.box(extents=[2, 2, 20]).export(tmp_path / "child.stl")
    limit_tag = f'<limit lower="{limit[0]}" upper="{limit[1]}" effort="1" velocity="1"/>' if limit else ""
    urdf = tmp_path / "robot.urdf"
    urdf.write_text(
        '<robot name="r">'
        '<link name="parent_link"><visual><origin xyz="-15 0 0"/>'
        '<geometry><mesh filename="parent.stl"/></geometry></visual></link>'
        '<link name="child_link"><visual><origin xyz="0 0 -10"/>'
        '<geometry><mesh filename="child.stl"/></geometry></visual></link>'
        f'<joint name="hinge" type="{joint_type}">'
        '<parent link="parent_link"/><child link="child_link"/>'
        '<origin xyz="0 0 0" rpy="0 0 0"/><axis xyz="0 1 0"/>'
        f"{limit_tag}</joint></robot>"
    )
    return urdf


def test_face_labels_preserve_coverage_uv_and_source_binding(tmp_path):
    mesh = trimesh.creation.box()
    mesh.visual = trimesh.visual.TextureVisuals(
        uv=np.arange(len(mesh.vertices) * 2).reshape(-1, 2) / 20,
        material=trimesh.visual.material.PBRMaterial(baseColorFactor=[100, 150, 200, 255]),
    )
    source = tmp_path / "source.glb"
    source.write_bytes(encode(mesh))
    scene = trimesh.load(source, force="scene", process=False)
    node = list(scene.graph.nodes_geometry)[0]
    spec = {"source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(), "nodes": {node: ["a"] * 6 + ["b"] * 6}}
    labels = tmp_path / "labels.json"
    labels.write_text(json.dumps(spec))
    w = workbench(tmp_path, [source, labels])
    face_split(w)
    actual = trimesh.load(Path(w["output"]) / "scene.glb", force="scene", process=False)
    assert sum(len(m.faces) for m in actual.geometry.values()) == 12
    assert len(actual.geometry) == 2
    assert all(m.visual.uv is not None for m in actual.geometry.values())
    assert np.allclose(actual.bounds, scene.bounds)
    spec["source_sha256"] = "wrong"
    labels.write_text(json.dumps(spec))
    with pytest.raises(ValueError, match="SHA256"):
        face_split(w)


def test_laser_sections_have_mm_dimensions_and_closed_loops(tmp_path):
    mesh = trimesh.creation.box(extents=[20, 30, 12])
    source = tmp_path / "box.stl"
    mesh.export(source)
    w = workbench(tmp_path, [source], {"layer_mm": 3})
    laser_slices(w)
    report = json.loads(Path(w["output"], "layers.json").read_text())
    assert len(report["layers"]) == 4
    assert all(x["closed_loops"] == 1 for x in report["layers"])
    assert 'width="30.0mm"' in Path(w["output"], "layer-000.svg").read_text()
    w["params"]["layer_mm"] = 5
    laser_slices(w)
    report = json.loads(Path(w["output"], "layers.json").read_text())
    assert len(report["layers"]) == 3 and report["layers"][-1]["thickness_mm"] == pytest.approx(2)


def test_preview_preserves_input_bytes(tmp_path):
    source = tmp_path / "box.glb"
    source.write_bytes(trimesh.Scene(trimesh.creation.box()).export(file_type="glb"))
    w = workbench(tmp_path, [source])
    asset_preview(w)
    assert Path(w["output"], "asset-0.glb").read_bytes() == source.read_bytes()


def test_relief_is_closed_and_has_requested_dimensions(tmp_path):
    from PIL import Image

    image = tmp_path / "height.png"
    Image.fromarray(np.tile(np.linspace(0, 255, 24, dtype=np.uint8), (16, 1))).save(image)
    w = workbench(tmp_path, [image], {"width_mm": 60, "base_mm": 2, "relief_mm": 5})
    relief(w)
    mesh = trimesh.load(Path(w["output"], "relief.stl"), force="mesh")
    assert mesh.is_volume
    assert mesh.extents == pytest.approx([60, 40, 7])
    assert mesh.bounds[0, 2] == 0


def test_motion_audit_detects_collision_between_clear_endpoints(tmp_path):
    scene = trimesh.Scene()
    scene.add_geometry(trimesh.creation.box(extents=[0.01] * 3), node_name="fixed")
    moving = trimesh.creation.box(extents=[0.01] * 3)
    moving.apply_translation([0.03, 0, 0])
    scene.add_geometry(moving, node_name="moving")
    source = tmp_path / "assembly.glb"
    source.write_bytes(scene.export(file_type="glb"))
    w = workbench(
        tmp_path,
        [source],
        {"steps": 3, "motions": {"moving": {"type": "prismatic", "axis": [1, 0, 0], "range_mm": [0, -60]}}},
    )
    assembly_audit(w)
    result = json.loads(Path(w["output"], "assembly-audit.json").read_text())
    assert result["status"] == "fail"
    assert not result["samples"][0]["collisions"] and not result["samples"][2]["collisions"]
    assert result["samples"][1]["collisions"][0]["overlap_mm3"] == pytest.approx(1000, rel=1e-5)
    w["params"] = {}
    assembly_audit(w)
    assert json.loads(Path(w["output"], "assembly-audit.json").read_text())["status"] == "pass"


def test_interactive_delivery_embeds_exact_asset_and_safe_text(tmp_path):
    source = tmp_path / "box.glb"
    raw = trimesh.Scene(trimesh.creation.box()).export(file_type="glb")
    source.write_bytes(raw)
    w = workbench(
        tmp_path,
        [source],
        {"title": "</script><script>bad</script>", "hotspots": [{"label": "test", "position": [0, 0, 0]}]},
    )
    interactive_scene(w)
    import base64
    import re

    html = Path(w["output"], "index.html").read_text()
    data = json.loads(
        re.search(r'<script type="application/json" id="project-data">(.*?)</script>', html, re.S).group(1)
    )
    assert base64.b64decode(data["assets"][0]["data"]) == raw
    assert data["title"] == w["params"]["title"] and w["params"]["title"] not in html
    assert "__WORKBENCH_PROJECT_DATA__" not in html
    w["params"]["hotspots"] = [{"label": "bad", "position": [0, 0]}]
    with pytest.raises(ValueError, match="finite XYZ"):
        interactive_scene(w)


def test_urdf_audit_sweeps_joint_and_detects_far_side_collision(tmp_path):
    urdf = urdf_fixture(tmp_path, "revolute", limit=[0, math.radians(90)])
    w = workbench(tmp_path, [urdf], {"steps": 5})
    assembly_audit(w)
    result = json.loads(Path(w["output"], "assembly-audit.json").read_text())
    assert result["mode"] == "urdf" and result["units"] == "mm"
    assert set(result["objects"]) == {"parent_link", "child_link"}
    assert len(result["joints"]) == 1
    joint = result["joints"][0]
    assert joint["name"] == "hinge" and joint["type"] == "revolute"
    assert joint["parent"] == "parent_link" and joint["child"] == "child_link"
    assert joint["range"][0] == pytest.approx(0.0)
    assert joint["range"][1] == pytest.approx(math.radians(90))
    assert not result["samples"][0]["collisions"]
    assert result["status"] == "fail"
    hit = next(s for s in result["samples"] if s["collisions"])
    pair = hit["collisions"][0]
    assert {pair["a"], pair["b"]} == {"parent_link", "child_link"}
    assert pair["overlap_mm3"] > 0


def test_urdf_audit_narrow_declared_range_stays_clear(tmp_path):
    urdf = urdf_fixture(tmp_path, "revolute", limit=[0, math.radians(15)])
    w = workbench(tmp_path, [urdf], {"steps": 5})
    assembly_audit(w)
    result = json.loads(Path(w["output"], "assembly-audit.json").read_text())
    assert result["status"] == "pass"
    assert all(not s["collisions"] for s in result["samples"])


def test_urdf_audit_joint_ranges_overrides_declared_limit(tmp_path):
    urdf = urdf_fixture(tmp_path, "revolute", limit=[0, math.radians(90)])
    w = workbench(tmp_path, [urdf], {"steps": 5, "joint_ranges": {"hinge": [0, math.radians(15)]}})
    assembly_audit(w)
    result = json.loads(Path(w["output"], "assembly-audit.json").read_text())
    assert result["status"] == "pass"
    assert all(not s["collisions"] for s in result["samples"])
    assert result["joints"][0]["range"][1] == pytest.approx(math.radians(15))


def test_urdf_audit_continuous_joint_without_override_errors(tmp_path):
    urdf = urdf_fixture(tmp_path, "continuous")
    w = workbench(tmp_path, [urdf])
    with pytest.raises(ValueError, match="joint_ranges"):
        assembly_audit(w)


def test_urdf_audit_merges_fixed_joint_links_into_one_rigid_group(tmp_path):
    """`bracket_link` is welded onto `base_link` via a `fixed` joint with
    fully overlapping rest geometry -- like a bracket bolted onto its own
    base. Without merging, that pair would be reported as colliding at
    every sampled pose; `arm_link` hangs off a revolute joint far enough
    away and with a narrow enough range to stay clear of everything, so an
    overall "pass" (and `bracket_link` never showing up as its own object)
    proves the fixed pair was folded away before pairwise testing."""
    trimesh.creation.box(extents=[10, 10, 10]).export(tmp_path / "base.stl")
    trimesh.creation.box(extents=[10, 10, 10]).export(tmp_path / "bracket.stl")
    trimesh.creation.box(extents=[2, 2, 20]).export(tmp_path / "arm.stl")
    urdf = tmp_path / "bracket_robot.urdf"
    urdf.write_text(
        '<robot name="r">'
        '<link name="base_link"><visual><origin xyz="0 0 0"/>'
        '<geometry><mesh filename="base.stl"/></geometry></visual></link>'
        '<link name="bracket_link"><visual><origin xyz="0 0 0"/>'
        '<geometry><mesh filename="bracket.stl"/></geometry></visual></link>'
        '<link name="arm_link"><visual><origin xyz="0 0 -10"/>'
        '<geometry><mesh filename="arm.stl"/></geometry></visual></link>'
        '<joint name="weld" type="fixed">'
        '<parent link="base_link"/><child link="bracket_link"/>'
        '<origin xyz="0 0 0" rpy="0 0 0"/></joint>'
        '<joint name="hinge" type="revolute">'
        '<parent link="base_link"/><child link="arm_link"/>'
        '<origin xyz="20 0 0" rpy="0 0 0"/><axis xyz="0 1 0"/>'
        f'<limit lower="0" upper="{math.radians(5)}" effort="1" velocity="1"/></joint>'
        "</robot>"
    )
    w = workbench(tmp_path, [urdf], {"steps": 5})
    assembly_audit(w)
    result = json.loads(Path(w["output"], "assembly-audit.json").read_text())
    assert result["rigid_groups"] == {"base_link": ["base_link", "bracket_link"]}
    assert set(result["objects"]) == {"base_link", "arm_link"}
    assert "bracket_link" not in result["objects"]
    assert result["status"] == "pass"
    assert all(not s["collisions"] for s in result["samples"])


def test_urdf_audit_mimic_joint_follows_its_master(tmp_path):
    """`follow` mimics `hinge` (multiplier 1, offset 0) and is not itself
    swept, but `yourdfpy`'s own forward kinematics resolves it from
    `hinge`'s already-updated value on every sampled step. `mimic_link` and
    `rod_link` share the same geometry and joint origin, so if `follow`
    tracks `hinge` they stay coincident (full-volume overlap) at every
    phase, including the far-side collision with `parent_link` the swing
    produces partway through."""
    trimesh.creation.box(extents=[10, 10, 10]).export(tmp_path / "parent.stl")
    trimesh.creation.box(extents=[2, 2, 20]).export(tmp_path / "rod.stl")
    urdf = tmp_path / "mimic_robot.urdf"
    upper = math.radians(90)
    urdf.write_text(
        '<robot name="r">'
        '<link name="parent_link"><visual><origin xyz="-15 0 0"/>'
        '<geometry><mesh filename="parent.stl"/></geometry></visual></link>'
        '<link name="rod_link"><visual><origin xyz="0 0 -10"/>'
        '<geometry><mesh filename="rod.stl"/></geometry></visual></link>'
        '<link name="mimic_link"><visual><origin xyz="0 0 -10"/>'
        '<geometry><mesh filename="rod.stl"/></geometry></visual></link>'
        '<joint name="hinge" type="revolute">'
        '<parent link="parent_link"/><child link="rod_link"/>'
        '<origin xyz="0 0 0" rpy="0 0 0"/><axis xyz="0 1 0"/>'
        f'<limit lower="0" upper="{upper}" effort="1" velocity="1"/></joint>'
        '<joint name="follow" type="revolute">'
        '<parent link="parent_link"/><child link="mimic_link"/>'
        '<origin xyz="0 0 0" rpy="0 0 0"/><axis xyz="0 1 0"/>'
        f'<limit lower="0" upper="{upper}" effort="1" velocity="1"/>'
        '<mimic joint="hinge" multiplier="1.0" offset="0.0"/></joint>'
        "</robot>"
    )
    w = workbench(tmp_path, [urdf], {"steps": 5})
    assembly_audit(w)
    result = json.loads(Path(w["output"], "assembly-audit.json").read_text())
    assert result["mimic_joints"] == [{"name": "follow", "master": "hinge", "multiplier": 1.0, "offset": 0.0}]
    assert "follow" not in {j["name"] for j in result["joints"]}
    for s in result["samples"]:
        pair = next(c for c in s["collisions"] if {c["a"], c["b"]} == {"rod_link", "mimic_link"})
        assert pair["overlap_mm3"] > 100
    rod_hit = next(
        i
        for i, s in enumerate(result["samples"])
        if {"rod_link", "parent_link"} in [{c["a"], c["b"]} for c in s["collisions"]]
    )
    mimic_hit = next(
        i
        for i, s in enumerate(result["samples"])
        if {"mimic_link", "parent_link"} in [{c["a"], c["b"]} for c in s["collisions"]]
    )
    assert rod_hit == mimic_hit


def test_urdf_audit_link_with_two_visuals_is_one_solid(tmp_path):
    """`parent_link` is split into two abutting `<visual>` halves that
    together reconstruct the same box `urdf_fixture` uses as one mesh; the
    audit must still find the same far-side collision, proving a multi-visual
    link is treated as a single solid."""
    trimesh.creation.box(extents=[5, 10, 10]).export(tmp_path / "parent_half.stl")
    trimesh.creation.box(extents=[2, 2, 20]).export(tmp_path / "child.stl")
    urdf = tmp_path / "two_visuals.urdf"
    urdf.write_text(
        '<robot name="r">'
        '<link name="parent_link">'
        '<visual><origin xyz="-17.5 0 0"/><geometry><mesh filename="parent_half.stl"/></geometry></visual>'
        '<visual><origin xyz="-12.5 0 0"/><geometry><mesh filename="parent_half.stl"/></geometry></visual>'
        "</link>"
        '<link name="child_link"><visual><origin xyz="0 0 -10"/>'
        '<geometry><mesh filename="child.stl"/></geometry></visual></link>'
        '<joint name="hinge" type="revolute">'
        '<parent link="parent_link"/><child link="child_link"/>'
        '<origin xyz="0 0 0" rpy="0 0 0"/><axis xyz="0 1 0"/>'
        f'<limit lower="0" upper="{math.radians(90)}" effort="1" velocity="1"/></joint></robot>'
    )
    w = workbench(tmp_path, [urdf], {"steps": 5})
    assembly_audit(w)
    result = json.loads(Path(w["output"], "assembly-audit.json").read_text())
    assert set(result["objects"]) == {"parent_link", "child_link"}
    assert not result["samples"][0]["collisions"]
    assert result["status"] == "fail"


def two_shells_and_a_clip(tmp_path):
    """Two half-shells split apart in Y (a small gap at y=0) plus one small
    decorative clip that sits well clear of both, off to the side in X."""
    shell_a = trimesh.creation.box(extents=[10, 10, 20])
    shell_a.apply_translation([0, -5.05, 0])
    shell_b = trimesh.creation.box(extents=[10, 10, 20])
    shell_b.apply_translation([0, 5.05, 0])
    decor = trimesh.creation.box(extents=[2, 2, 2])
    decor.apply_translation([10, -5, 0])
    for name, mesh in [("shell_a", shell_a), ("shell_b", shell_b), ("decor_clip", decor)]:
        mesh.export(tmp_path / f"{name}.stl")
    return [tmp_path / "shell_a.stl", tmp_path / "shell_b.stl", tmp_path / "decor_clip.stl"]


def test_removal_audit_orders_decorative_part_within_its_declared_group(tmp_path):
    inputs = two_shells_and_a_clip(tmp_path)
    w = workbench(tmp_path, inputs, {"groups": {"shell_a": ["shell_a"], "shell_b": ["shell_b", "decor_clip"]}})
    removal_audit(w)
    result = json.loads(Path(w["output"], "removal-audit.json").read_text())
    assert result["half_groups"] == {"shell_a": ["shell_a"], "shell_b": ["shell_b", "decor_clip"]}
    assert result["assembly_order"] == ["decor_clip"]
    assert not result["unresolved_parts"]
    step = result["decorative_removal_steps"][0]
    assert step["part"] == "decor_clip" and step["host"] == "shell_b"
    assert result["status"] == "pass_sampled"


def test_removal_audit_defaults_to_one_group_and_validates_inputs(tmp_path):
    inputs = two_shells_and_a_clip(tmp_path)
    w = workbench(tmp_path, inputs)
    removal_audit(w)
    result = json.loads(Path(w["output"], "removal-audit.json").read_text())
    assert list(result["half_groups"]) == ["assembly"]
    assert set(result["half_groups"]["assembly"]) == {"shell_a", "shell_b", "decor_clip"}
    w["params"] = {"groups": {"shell_a": ["not_a_real_part"]}}
    with pytest.raises(ValueError):
        removal_audit(w)
    w["params"] = {"insertion_directions": {"decor_clip": [1, 0]}}
    with pytest.raises(ValueError):
        removal_audit(w)
    w["params"] = {"split_axis": 5}
    with pytest.raises(ValueError):
        removal_audit(w)
    w["params"] = {"split_axis": True}
    with pytest.raises(ValueError):
        removal_audit(w)


def test_removal_audit_reports_generic_limitations_and_axis_neutral_alias(tmp_path, monkeypatch):
    inputs = two_shells_and_a_clip(tmp_path)
    w = workbench(tmp_path, inputs, {"groups": {"shell_a": ["shell_a"], "shell_b": ["shell_b", "decor_clip"]}})
    removal_audit(w)
    result = json.loads(Path(w["output"], "removal-audit.json").read_text())
    assert result["split_axis"] == 1
    assert result["whole_halves"]
    assert all(entry["translation_mm"] == entry["translation_y_mm"] for entry in result["whole_halves"])
    zh_limitations = result["limitations"]
    assert len(zh_limitations) == 2
    assert not any("半壳" in text for text in zh_limitations)
    monkeypatch.setenv("STUDIO_LANG", "en")
    removal_audit(w)
    en_result = json.loads(Path(w["output"], "removal-audit.json").read_text())
    assert en_result["limitations"] != zh_limitations
    assert not any("half-shell" in text.lower() or "half shell" in text.lower() for text in en_result["limitations"])
