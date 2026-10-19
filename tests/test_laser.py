import base64
import json
import xml.etree.ElementTree as ET

import pytest
import trimesh
from shapely.geometry import box
from studio.core.editor import EditorError
from studio.core.laser import Laser, parameters, panel_geometry, nest
from studio.adapters.lightburn import LightBurn


def test_large_valid_design_preview_contains_every_path(tmp_path):
    import re

    laser = Laser(tmp_path)
    workflow = laser.execute(
        {
            "action": "create",
            "params": {
                "width_mm": 500,
                "depth_mm": 250,
                "height_mm": 400,
            },
        }
    )["workflow"]
    workflow = run(laser, workflow, "design")
    tree = ET.fromstring((tmp_path / workflow["id"] / "design/design.svg").read_bytes())
    x, y, w, h = map(float, tree.attrib["viewBox"].split())
    for path in tree.findall("{http://www.w3.org/2000/svg}path"):
        for px, py in re.findall(r"(-?[\d.]+),(-?[\d.]+)", path.attrib["d"]):
            assert x <= float(px) <= x + w
            assert y <= float(py) <= y + h


def test_laser_accepts_an_injected_connector_and_has_no_implicit_network(tmp_path):
    class Connector:
        def status(self):
            return {"paired": True, "test": "injected"}

    laser = Laser(tmp_path, connector_factory=Connector)
    assert laser.execute({"action": "connection"})["connection"]["test"] == "injected"
    with pytest.raises(EditorError, match="连接器|connector"):
        Laser(tmp_path).execute({"action": "connection"})


def test_lightburn_closed_event_stream_fails_without_spinning(tmp_path, monkeypatch):
    import io
    from studio.adapters import lightburn

    class Stream(io.BytesIO):
        def readline(self, *args):
            reads.append(True)
            return super().readline(*args)

    reads = []
    clock = iter(range(100))
    monkeypatch.setattr(lightburn.time, "monotonic", lambda: next(clock))
    client = LightBurn(tmp_path / "credential.json")
    path = tmp_path / "sheet.svg"
    path.write_text("<svg/>")
    monkeypatch.setattr(client, "preflight", lambda expected: {"shape_count": 0})
    monkeypatch.setattr(
        client,
        "request",
        lambda url, *args, **kwargs: Stream(b":connected\n\n") if url == "/api/events" else {"status": "accepted"},
    )
    with pytest.raises(EditorError, match="未确认"):
        client.import_svg(path, {"bounds_mm": [0, 0, 10, 10], "panels": 1})
    assert len(reads) <= 3, "EOF must stop reading rather than spin until the deadline"


def run(laser, w, stage, **kw):
    return laser.execute(dict(action="run", id=w["id"], expected_revision=w["revision"], stage=stage, **kw))["workflow"]


def test_tissue_box_checkpoints_and_geometry(tmp_path):
    laser = Laser(tmp_path)
    w = laser.execute({"action": "create"})["workflow"]
    with pytest.raises(EditorError):
        run(laser, w, "nest")
    w = run(laser, w, "design")
    report = w["stages"]["design"]["report"]
    assert report["outer_mm"] == [236, 126, 93]
    assert report["solid_intersections"] == 0
    scene = trimesh.load(tmp_path / w["id"] / "design/assembly.glb")
    assert len(scene.geometry) == 5
    assert all(m.is_volume for m in scene.geometry.values())
    assert scene.extents == pytest.approx([0.236, 0.093, 0.126], abs=1e-6)
    w = run(laser, w, "panels")
    w = run(laser, w, "nest")
    report = w["stages"]["nest"]["report"]
    assert report["sheets"] == 1 and report["collisions"] == 0
    assert report["files"][0]["closed_contours"] == 6
    path = tmp_path / w["id"] / "nest/sheet-01.svg"
    svg = ET.fromstring(path.read_bytes())
    assert svg.attrib["width"] == "600mm" and svg.attrib["height"] == "300mm"
    assert len(svg) == 5
    assert all(p.attrib["d"].endswith(" Z") for p in svg)
    receipt = laser.execute({"action": "artifact", "id": w["id"], "name": "nest/sheet-01.svg"})
    assert base64.b64decode(receipt["base64"]) == path.read_bytes()
    with pytest.raises(EditorError):
        laser.execute({"action": "artifact", "id": w["id"], "name": "../../workflow.json"})
    path.write_text("tampered")
    with pytest.raises(EditorError):
        laser.execute({"action": "artifact", "id": w["id"], "name": "nest/sheet-01.svg"})


@pytest.mark.parametrize(
    "params",
    [
        {"width_mm": float("nan")},
        {"thickness_mm": True},
        {"unknown": 3},
        {"width_mm": 20},
        {"slot_length_mm": 300},
        {"sheet_width_mm": 601},
    ],
)
def test_bad_parameters(params):
    with pytest.raises(EditorError):
        parameters(params)


def test_kerf_spacing_and_multiple_sheets():
    p = parameters({"sheet_width_mm": 260, "sheet_height_mm": 150})
    panels = panel_geometry(p)
    sheets, positions = nest(p, panels)
    assert len(sheets) > 1
    assert {p["panel"] for p in positions} == set(panels)
    for items in sheets:
        for i, (_, shape) in enumerate(items):
            assert box(5, 5, 255, 145).buffer(1e-6).covers(shape)
            for _, other in items[i + 1 :]:
                assert shape.distance(other) >= 5 - 1e-6
    nominal = panels["top"]
    cut = nominal.buffer(0.075, join_style="mitre")
    assert cut.area > nominal.area
    assert len(cut.interiors) == len(nominal.interiors) == 1


def test_revision_isolation_and_idempotency(tmp_path):
    laser = Laser(tmp_path / "a")
    other = Laser(tmp_path / "b")
    w = laser.execute({"action": "create"})["workflow"]
    with pytest.raises(EditorError):
        other.execute({"action": "read", "id": w["id"]})
    fresh = run(laser, w, "design")
    with pytest.raises(EditorError):
        run(laser, w, "panels")
    again = run(laser, fresh, "design")
    assert again == fresh


def test_lightburn_202_not_success(tmp_path, monkeypatch):
    import io

    client = LightBurn(tmp_path / "credential.json")
    path = tmp_path / "sheet.svg"
    path.write_text("<svg/>")
    calls = []

    def request(url, *args, **kwargs):
        calls.append(url)
        if url == "/api/project":
            return {"shape_count": 0, "workspace": {"machine_size": {"x": 600, "y": 300}, "machine_view": True}}
        if url == "/api/events/poll":
            return {"job": {"state": "idle"}}
        if url == "/api/events":
            return io.BytesIO(b':connected\n\nevent: file_imported\ndata: {"success": false}\n\n')
        if url == "/api/file/upload":
            return {"status": "accepted"}
        raise AssertionError(url)

    monkeypatch.setattr(client, "request", request)
    with pytest.raises(EditorError, match="未确认"):
        client.import_svg(path, {"bounds_mm": [5, 5, 500, 230], "panels": 5, "sheet_mm": [600, 300]})
    assert calls.index("/api/events") < calls.index("/api/file/upload")


def test_lightburn_event_and_readback(tmp_path, monkeypatch):
    import io

    client = LightBurn(tmp_path / "credential.json")
    path = tmp_path / "sheet.svg"
    path.write_text("<svg/>")
    uploaded = []

    def request(url, *args, **kwargs):
        if url == "/api/project":
            return {
                "shape_count": 6 if uploaded else 0,
                "workspace": {"machine_size": {"x": 600, "y": 300}, "machine_view": True},
            }
        if url == "/api/events/poll":
            return {"job": {"state": "idle"}}
        if url == "/api/events":
            return io.BytesIO(b':connected\n\nevent: file_imported\ndata: {"success": true}\n\n')
        if url == "/api/file/upload":
            uploaded.append(args)
            return {"status": "accepted"}
        if url == "/api/layers":
            return {"layers": [{"index": 0, "shape_count": 6}]}
        raise AssertionError(url)

    monkeypatch.setattr(client, "request", request)
    result = client.import_svg(path, {"bounds_mm": [5, 5, 500, 230], "panels": 5, "sheet_mm": [600, 300]})
    assert result["status"] == "imported" and result["project"]["shape_count"] == 6
    assert result["physical_cut_verified"] is False
    assert uploaded[0][1]["X-Group-Shapes"] == "false"
    assert uploaded[0][1]["X-Origin"] == "bottom-left"


def test_connection_secret_redacted(tmp_path, monkeypatch):
    client = LightBurn(tmp_path / "connection.json")
    monkeypatch.setattr(
        client,
        "request",
        lambda url, *a, **k: {"status": "ok", "secret": "private"}
        if url == "/api/connect"
        else {"shape_count": 0, "workspace": {"machine_size": {"x": 600, "y": 300}, "machine_view": True}},
    )
    result = client.connect()
    assert "private" not in json.dumps(result) and "secret" not in json.dumps(result)
    assert client.credential.stat().st_mode & 0o777 == 0o600
    assert len(client.token()) == 64


def test_lightburn_blocks_small_workspace_before_upload(tmp_path, monkeypatch):
    client = LightBurn(tmp_path / "credential.json")
    project = {"shape_count": 0, "workspace": {"machine_size": {"x": 300, "y": 200}}}
    monkeypatch.setattr(client, "request", lambda url: project if url == "/api/project" else {"job": {"state": "idle"}})
    with pytest.raises(EditorError, match="画布小于"):
        client.preflight({"sheet_mm": [600, 300]})
    project["workspace"]["machine_size"] = {"x": 600, "y": 300}
    project["workspace"]["workpiece_size"] = {"x": 300, "y": 200}
    with pytest.raises(EditorError, match="材料页小于"):
        client.preflight({"sheet_mm": [600, 300]})
    project["device"] = {"laser": {"controller": "No Machine"}}
    assert client.preflight({"sheet_mm": [600, 300]}) == project
