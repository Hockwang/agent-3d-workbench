"""Color intent survives print-copy STL and is checked after slicer serialization."""

import json
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile, ZIP_DEFLATED

import pytest
import trimesh

from print_prep import color_intent, export3mf, job, profiles, bambu
from studio.core.editor import Workspace
from tests.helpers import act


@pytest.fixture
def color_profiles(tmp_path, monkeypatch):
    root = tmp_path / "presets"
    presets = {
        "machine": {
            "name": "Bambu Lab P1S 0.4 nozzle",
            "instantiation": "true",
            "printable_area": ["0x0", "256x0", "256x256", "0x256"],
            "printable_height": "250",
            "default_print_profile": "test process",
            "default_filament_profile": ["test PLA"],
        },
        "process": {"name": "test process", "layer_height": "0.2"},
        "filament": {"name": "test PLA", "filament_colour": ["#00AE42"]},
    }
    for kind, data in presets.items():
        folder = root / kind
        folder.mkdir(parents=True)
        (folder / "test.json").write_text(json.dumps(data))
    monkeypatch.setenv("MFG_BAMBU_PROFILE_ROOT", str(root))
    return root


def badge_meshes():
    body = trimesh.creation.box([40, 40, 4])
    cross = trimesh.creation.box([24, 8, 2.2]).union(trimesh.creation.box([8, 24, 2.2]))
    body.visual.face_colors = [0, 0, 255, 255]
    cross.visual.face_colors = [255, 0, 0, 255]
    return {"body": body, "cross": cross}


def test_badge_editor_print_copy_inspect_and_export(tmp_path, color_profiles, run):
    w = Workspace(tmp_path / "workspace")
    scene = trimesh.Scene()
    for name, mesh in badge_meshes().items():
        scene.add_geometry(mesh, node_name=name, geom_name=name)
    source = tmp_path / "badge.glb"
    scene.export(source)
    act(w, "import", files=[str(source)], units="mm")
    copies = act(w, "print_copy")["files"]
    assert {color_intent.read_stl_color(Path(p)) for p in copies} == {"#0000FF", "#FF0000"}
    job_dir = tmp_path / "job"
    code, result, _ = run(["prepare", "--job", str(job_dir), *copies, "--mode", "per_part", "--no-project"])
    assert code == 0, result
    data = job.load_job(job_dir)
    assert {p["color"] for p in data["inspect"]["parts"]} == {"#0000FF", "#FF0000"}
    plates = data["export"]["plates"]
    assert len(plates) == 2
    assert {next(iter(p["color_mapping"].values()))["color"] for p in plates} == {"#0000FF", "#FF0000"}
    for plate in plates:
        assert plate["readback"]["pass"]
        assert "color_readback" not in plate  # no slicer, no actual-project verification claim
        color = next(iter(plate["color_mapping"].values()))["color"]
        assert json.loads(Path(plate["filament_paths"][0]).read_text())["filament_colour"] == [color]


def test_uniform_colors_only_and_stale_stl_manifest(tmp_path):
    mesh = trimesh.creation.box()
    assert color_intent.uniform_mesh_color(mesh) is None
    mesh.visual.face_colors = [0, 0, 255, 255]
    assert color_intent.uniform_mesh_color(mesh) == "#0000FF"
    mesh.visual.face_colors[0] = [255, 0, 0, 255]
    assert color_intent.uniform_mesh_color(mesh) is None
    path = tmp_path / "body.stl"
    mesh.export(path)
    color_intent.write_stl_color(path, "#0000ff")
    path.write_bytes(path.read_bytes() + b"changed")
    with pytest.raises(ValueError, match="Stale"):
        color_intent.read_stl_color(path)


@pytest.mark.parametrize("collapse", [False, True])
def test_export_checks_actual_slicer_assignment_and_invalidates_ready(
    tmp_path, color_profiles, run, monkeypatch, collapse
):
    source = tmp_path / "badge.glb"
    scene = trimesh.Scene()
    for name, mesh in badge_meshes().items():
        scene.add_geometry(mesh, node_name=name, geom_name=name)
    scene.export(source)
    job_dir = tmp_path / "job"
    code, result, _ = run(["prepare", "--job", str(job_dir), str(source), "--no-project"])
    assert code == 0, result

    def serialize_project(geometry, out_dir, machine, process, filaments, project_name):
        # Test double for Bambu serialization: strip core colors, use only real settings.
        with ZipFile(geometry) as archive:
            entries = {n: archive.read(n) for n in archive.namelist()}
        model = ET.fromstring(entries["3D/3dmodel.model"])
        for obj in model.findall(f"{{{export3mf.CORE_NS}}}resources/{{{export3mf.CORE_NS}}}object"):
            obj.attrib.pop("name", None)
            obj.attrib.pop("pid", None)
            obj.attrib.pop("pindex", None)
        entries["3D/3dmodel.model"] = ET.tostring(model)
        config = ET.fromstring(entries["Metadata/model_settings.config"])
        for obj in config.findall("object"):
            if collapse:
                obj.find("metadata[@key='extruder']").set("value", "1")
        entries["Metadata/model_settings.config"] = ET.tostring(config)
        entries["Metadata/project_settings.config"] = json.dumps(
            {"filament_colour": [json.loads(Path(p).read_text())["filament_colour"][0] for p in filaments]}
        ).encode()
        path = out_dir / (project_name + ".project.3mf")
        with ZipFile(path, "w", ZIP_DEFLATED) as archive:
            for name, raw in entries.items():
                archive.writestr(name, raw)
        return {"ok": True, "project_3mf": str(path), "used_slice_fallback": False}

    monkeypatch.setattr(bambu, "export_project_3mf", serialize_project)
    code, result, _ = run(["export", "--job", str(job_dir)])
    if collapse:
        assert code == 1
        assert result["error"]["code"] == "project_color_changed"
        assert "export" not in job.load_job(job_dir)
    else:
        assert code == 0, result
        plate = result["plates"][0]
        assert plate["color_readback"]["pass"]
        assert plate["geometry_readback"]["pass"]
        assert not plate["bambu_moved_objects"]


@pytest.mark.parametrize("mode", ["per_part", "single"])
@pytest.mark.bambu
def test_badge_real_bambu_project(tmp_path, run, mode):
    """Optional real serializer acceptance; no AMS/hardware/print submission."""
    if not profiles.bambu_binary().exists() or not profiles.profile_root().is_dir():
        pytest.skip("Bambu Studio binary and vendor profiles required")
    source = tmp_path / "badge.glb"
    scene = trimesh.Scene()
    for name, mesh in badge_meshes().items():
        scene.add_geometry(mesh, node_name=name, geom_name=name)
    scene.export(source)
    code, payload, _ = run(["prepare", "--job", str(tmp_path / "job"), str(source), "--mode", mode])
    assert code == 0, payload
    plates = next(s["result"]["plates"] for s in payload["steps"] if s["step"] == "export")
    assert {i["color"] for p in plates for i in p["color_mapping"].values()} == {"#0000FF", "#FF0000"}
    for plate in plates:
        assert plate["color_readback"]["pass"]
        assert plate["geometry_readback"]["pass"]
        assert not plate["bambu_moved_objects"]


@pytest.mark.parametrize("entry", ["body=red", "missing=#FF0000", "invalid"])
def test_explicit_color_rejects_invalid_or_unknown_parts(tmp_path, color_profiles, run, entry):
    source = tmp_path / "body.stl"
    trimesh.creation.box([20, 20, 4]).export(source)
    job_dir = tmp_path / "job"
    code, payload, _ = run(["prepare", "--job", str(job_dir), str(source), "--no-project"])
    assert code == 0, payload
    code, payload, _ = run(["export", "--job", str(job_dir), "--part-color", entry, "--no-project"])
    assert code == 2
    assert payload["error"]["code"] == "bad_part_color"


def test_explicit_colors_override_sources_and_check_uses_same_filaments(tmp_path, color_profiles, run, monkeypatch):
    source = tmp_path / "body.stl"
    trimesh.creation.box([20, 20, 4]).export(source)
    job_dir = tmp_path / "job"
    code, payload, _ = run(
        ["prepare", "--job", str(job_dir), str(source), "--no-project", "--part-color", "body=#0000ff"]
    )
    assert code == 0, payload
    plate = job.load_job(job_dir)["export"]["plates"][0]
    assert plate["color_mapping"] == {"body": {"color": "#0000FF", "filament_slot": 1}}

    def check_slice(geometry, out_dir, machine, process, filaments, name):
        assert [str(p) for p in filaments] == plate["filament_paths"]
        assert json.loads(filaments[0].read_text())["filament_colour"] == ["#0000FF"]
        return {
            "grams": 1,
            "seconds": 10,
            "wall_seconds": 0,
            "warnings": [],
            "returncode": 0,
            "error": None,
            "execution": {},
            "sliced_3mf": None,
        }

    monkeypatch.setattr(bambu, "check_slice", check_slice)
    code, payload, _ = run(["check", "--job", str(job_dir)])
    assert code == 0, payload
