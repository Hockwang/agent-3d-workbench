"""Board-based laser preparation, shared by MCP and the browser workbench.

All lengths are mm. Design polygons describe finished material; kerf offsets
produce separate tool paths. Checkpoints are immutable, scoped to the scene.
"""

from __future__ import annotations

import base64
import hashlib
import html
import json
import math
from pathlib import Path
import re
import time
import uuid

import numpy as np
import trimesh
from shapely import affinity
from shapely.geometry import Polygon, box
from shapely.geometry.polygon import orient
from shapely.ops import unary_union

from studio.core import filelock
from studio.core.editor import EditorError, _atomic

DEFAULTS = dict(
    width_mm=230,
    depth_mm=120,
    height_mm=90,
    thickness_mm=3,
    slot_length_mm=120,
    slot_width_mm=35,
    clearance_mm=0.15,
    kerf_mm=0.15,
    sheet_width_mm=600,
    sheet_height_mm=300,
    margin_mm=5,
    gap_mm=5,
)
STAGES = ("design", "panels", "nest", "lightburn")


def fail(text):
    raise EditorError(text, code="laser_invalid")


def dump(path, value):
    _atomic(path, (json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2) + "\n").encode())


def parameters(value):
    if not isinstance(value, dict) or set(value) - set(DEFAULTS):
        fail("激光参数名称无效")
    p = {**DEFAULTS, **value}
    limits = {
        "thickness_mm": (1, 12),
        "clearance_mm": (0, 1),
        "kerf_mm": (0, 0.6),
        "margin_mm": (1, 30),
        "gap_mm": (1, 30),
        "sheet_width_mm": (50, 600),
        "sheet_height_mm": (50, 300),
    }
    for key, v in p.items():
        low, high = limits.get(key, (10, 550))
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or not low <= v <= high:
            fail(f"{key} 必须在 {low}–{high} mm 内")
    t = p["thickness_mm"]
    if min(p["width_mm"], p["depth_mm"], p["height_mm"]) < 8 * t:
        fail("板件太小，无法布置指接")
    if (
        p["slot_length_mm"] < p["slot_width_mm"]
        or p["slot_length_mm"] > p["width_mm"] - 4 * t
        or p["slot_width_mm"] > p["depth_mm"] - 4 * t
    ):
        fail("抽纸孔必须留出至少两倍板厚的边缘")
    return p


def fingers(length, inset=0):
    # Alternating, centred tabs; neither end is a tab, avoiding corner clashes.
    n = max(5, min(19, int((length - 2 * inset) / 12) | 1))
    pitch = (length - 2 * inset) / n
    return [(inset + i * pitch, inset + (i + 1) * pitch) for i in range(1, n, 2)]


def panel_geometry(p):
    w, d, h, t, c = (p[k] for k in ("width_mm", "depth_mm", "height_mm", "thickness_mm", "clearance_mm"))
    W, D = w + 2 * t, d + 2 * t
    front, side, top = box(0, 0, W, h), box(t, 0, D - t, h), box(0, 0, W, D)
    for a, b in fingers(h):
        # Short wall tabs enter the open edge notches of both long walls.
        side = side.union(box(0, a, t, b)).union(box(D - t, a, D, b))
        for x in (0, W - t):
            front = front.difference(box(x - c / 2, a - c / 2, x + t + c / 2, b + c / 2))
    for a, b in fingers(W, 2 * t):
        front = front.union(box(a, h, b, h + t))
        for y in (0, D - t):
            top = top.difference(box(a - c / 2, y - c / 2, b + c / 2, y + t + c / 2))
    for a, b in fingers(D, 2 * t):
        side = side.union(box(a, h, b, h + t))
        for x in (0, W - t):
            top = top.difference(box(x - c / 2, a - c / 2, x + t + c / 2, b + c / 2))
    sl, sw = p["slot_length_mm"], p["slot_width_mm"]
    # Capsule opening with explicit tessellation; same polygon is exported and extruded.
    from shapely.geometry import LineString

    opening = LineString([(W / 2 - (sl - sw) / 2, D / 2), (W / 2 + (sl - sw) / 2, D / 2)]).buffer(sw / 2, quad_segs=24)
    top = top.difference(opening)
    result = {"top": top, "front": front, "back": front, "left": side, "right": side}
    for poly in result.values():
        if not isinstance(poly, Polygon) or not poly.is_valid or poly.area <= 0:
            fail("板件必须是单个闭合有效区域")
    return result


def contour(poly, project=None):
    def ring(coords):
        points = [project(x, y) if project else (x, y) for x, y in coords]
        return "M" + " L".join(f"{x:.5f},{y:.5f}" for x, y in points[:-1]) + " Z"

    return " ".join(ring(r.coords) for r in (poly.exterior, *poly.interiors))


def svg(width, height, items, preview=False):
    # Only closed vector paths in fabrication SVG; labels belong to preview only.
    rows = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}mm" height="{height}mm" viewBox="0 0 {width} {height}">'
    ]
    if preview:
        rows += [f'<rect width="{width}" height="{height}" fill="#faf7ef"/>']
    for name, poly in items:
        rows += [
            f'<path id="{html.escape(name)}" d="{contour(poly)}" fill="{"#e6c896" if preview else "none"}" fill-rule="evenodd" stroke="#000000" stroke-width="{0.3 if preview else 0.01}"/>'
        ]
        if preview:
            x, y = poly.representative_point().coords[0]
            rows += [
                f'<text x="{x}" y="{y}" text-anchor="middle" font-size="5" fill="#514938">{html.escape(name)}</text>'
            ]
    return "\n".join(rows + ["</svg>"])


def assembly(p, panels, folder):
    import manifold3d

    W, D, h, t = (
        p["width_mm"] + 2 * p["thickness_mm"],
        p["depth_mm"] + 2 * p["thickness_mm"],
        p["height_mm"],
        p["thickness_mm"],
    )
    transforms = {
        "top": lambda u, v, z: (u, v, z + h),
        "front": lambda u, v, z: (u, z, v),
        "back": lambda u, v, z: (u, D - t + z, v),
        "left": lambda u, v, z: (z, u, v),
        "right": lambda u, v, z: (W - t + z, u, v),
    }
    scene = trimesh.Scene()
    for i, (name, poly) in enumerate(panels.items()):
        po = orient(poly, 1)
        solid = (
            manifold3d.CrossSection([list(r.coords)[:-1] for r in (po.exterior, *po.interiors)]).extrude(t).to_mesh()
        )
        vertices = np.array([transforms[name](*v[:3]) for v in solid.vert_properties])
        mesh = trimesh.Trimesh(vertices=vertices, faces=solid.tri_verts, process=True)
        mesh.fix_normals()
        if not mesh.is_volume:
            fail("板件实体校验失败")
        mesh.visual.face_colors = [215 - i * 9, 181 - i * 7, 128 - i * 5, 255]
        scene.add_geometry(mesh, node_name=name)
    # GLB convention: metres, Y-up. The design itself remains mm/Z-up.
    converted = scene.copy()
    converted.apply_transform(np.array([[0.001, 0, 0, 0], [0, 0, 0.001, 0], [0, -0.001, 0, 0], [0, 0, 0, 1]]))
    (folder / "assembly.glb").write_bytes(converted.export(file_type="glb"))

    def iso(x, y, z):
        return 210 + 0.85 * (x - y), 40 + 0.36 * (x + y) + h - z

    projected = np.array([iso(*v) for mesh in scene.geometry.values() for v in mesh.vertices])
    x0, y0 = projected.min(axis=0) - 20
    x1, y1 = projected.max(axis=0) + [20, 40]
    width, height = max(x1 - x0, 360), y1 - y0
    rows = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{x0} {y0} {width} {height}" width="1020" height="{1020 * height / width}">',
        f'<rect x="{x0}" y="{y0}" width="{width}" height="{height}" fill="#faf7ef"/>',
    ]
    for name, color in (
        ("front", "#c6a272"),
        ("left", "#d7b47d"),
        ("back", "#d8b681"),
        ("right", "#b79160"),
        ("top", "#ecd3a6"),
    ):
        fn = transforms[name]

        def project(u, v):
            return iso(*fn(u, v, t if name == "top" else 0))

        rows.append(
            f'<path d="{contour(panels[name], project)}" fill="{color}" fill-rule="evenodd" stroke="#735d3e" stroke-width=".65"/>'
        )
    rows.append(
        f'<text x="{x0 + 10}" y="{y1 - 12}" fill="#514938" font-size="12">{W:g} × {D:g} × {h + t:g} mm · 5 panels · open bottom</text></svg>'
    )
    (folder / "design.svg").write_text("\n".join(rows))
    # Bounding-box and volume-intersection audit from actual assembled solids.
    meshes = list(scene.geometry.values())
    overlaps = []
    for i, a in enumerate(meshes):
        for j, b in enumerate(meshes[i + 1 :], i + 1):
            intersection = trimesh.boolean.intersection([a, b], engine="manifold")
            if len(intersection.faces) and abs(intersection.volume) > 0.01:
                overlaps.append([i, j, float(intersection.volume)])
    if overlaps:
        fail("装配板件存在实体干涉")
    return {
        "outer_mm": [W, D, h + t],
        "inner_mm": [p["width_mm"], p["depth_mm"], h],
        "panel_count": 5,
        "solid_intersections": 0,
        "opening_mm": [p["slot_length_mm"], p["slot_width_mm"]],
        "assembly": "四块侧板指接围合，再压入顶板；底部开放，可套住纸巾包装。配合需材料试片确认。",
    }


def nest(p, panels):
    W, H, m, g = (p[k] for k in ("sheet_width_mm", "sheet_height_mm", "margin_mm", "gap_mm"))
    paths = {name: poly.buffer(p["kerf_mm"] / 2, join_style="mitre") for name, poly in panels.items()}
    sheets, rows, placed = [[]], [], []
    for name, poly in sorted(paths.items(), key=lambda item: item[1].area, reverse=True):
        if not isinstance(poly, Polygon) or len(poly.interiors) != len(panels[name].interiors):
            fail("切缝补偿破坏了孔或轮廓，请减小切缝")
        x0, y0, x1, y1 = poly.bounds
        w, h = x1 - x0, y1 - y0
        if w > W - 2 * m or h > H - 2 * m:
            fail(f"{name} 超出材料尺寸；请修改设计或换板，不自动缩放")
        found = next((row for row in rows if h <= row["height"] and row["x"] + w <= W - m), None)
        if found is None:
            y = rows[-1]["y"] + rows[-1]["height"] + g if rows else m
            if y + h > H - m:
                sheets.append([])
                rows = []
                y = m
            found = {"x": m, "y": y, "height": h}
            rows.append(found)
        out = affinity.translate(poly, found["x"] - x0, found["y"] - y0)
        sheets[-1].append((name, out))
        placed.append(
            {
                "panel": name,
                "sheet": len(sheets),
                "x_mm": found["x"],
                "y_mm": found["y"],
                "rotation_deg": 0,
                "bounds_mm": list(out.bounds),
            }
        )
        found["x"] += w + g
    for items in sheets:
        for i, (_, a) in enumerate(items):
            if not box(m, m, W - m, H - m).buffer(1e-6).covers(a):
                fail("排版越界")
            for _, b in items[i + 1 :]:
                if a.distance(b) < g - 1e-6:
                    fail("排版间距不足")
    return sheets, placed


class Laser:
    def __init__(self, root, connector_factory=None):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.connector_factory = connector_factory

    def connector(self):
        if self.connector_factory is None:
            fail("未配置 LightBurn 连接器 / LightBurn connector is not configured")
        return self.connector_factory()

    def folder(self, identifier):
        if not isinstance(identifier, str) or not re.fullmatch(r"[a-f0-9]{32}", identifier):
            fail("激光任务编号无效")
        folder = self.root / identifier
        if not (folder / "workflow.json").is_file():
            fail("当前对话中没有此激光任务")
        return folder

    def read(self, identifier):
        return json.loads((self.folder(identifier) / "workflow.json").read_text())

    def execute(self, body, actor="ai"):
        action = body.get("action", "list")
        if action == "list":
            return {
                "ok": True,
                "workflows": sorted(
                    [json.loads(p.read_text()) for p in self.root.glob("*/workflow.json")],
                    key=lambda v: v["created"],
                    reverse=True,
                ),
            }
        if action == "connect":
            return {"ok": True, "connection": self.connector().connect()}
        if action == "connection":
            return {"ok": True, "connection": self.connector().status()}
        if action == "create":
            p = parameters(body.get("params", {}))
            identifier = uuid.uuid4().hex
            folder = self.root / identifier
            folder.mkdir()
            workflow = {
                "id": identifier,
                "title": str(body.get("title") or "R1 纸巾盒")[:120],
                "created": time.time(),
                "revision": 1,
                "params": p,
                "device": {
                    "name": "Bambu Lab R1",
                    "area_mm": [600, 300],
                    "profile": "geometry_only",
                    "physical_cut_verified": False,
                },
                "calibration": {"kerf": "unverified", "fit": "unverified", "power_speed": "unset"},
                "stages": {},
                "history": [],
            }
            dump(folder / "workflow.json", workflow)
        else:
            folder = self.folder(body.get("id"))
        with (folder / "workflow.lock").open("a+") as lock:
            filelock.lock(lock)
            workflow = self.read(folder.name)
            if action in ("read", "create"):
                return {"ok": True, "workflow": workflow}
            if action == "artifact":
                name = body.get("name", "")
                allowed = {a["name"]: a for s in workflow["stages"].values() for a in s.get("artifacts", [])}
                if name not in allowed:
                    fail("该文件不属于任务成果")
                path = folder / name
                raw = path.read_bytes()
                if hashlib.sha256(raw).hexdigest() != allowed[name]["sha256"]:
                    fail("成果文件已改变，请重新生成")
                return {
                    "ok": True,
                    "name": Path(name).name,
                    "base64": base64.b64encode(raw).decode(),
                    "mime": "image/svg+xml" if path.suffix == ".svg" else "application/octet-stream",
                }
            if body.get("expected_revision") != workflow["revision"]:
                fail("任务已更新，请读取最新 revision 后重试")
            if action != "run" or body.get("stage") not in STAGES:
                fail("激光操作无效")
            stage = body["stage"]
            if workflow["stages"].get(stage, {}).get("status") == "completed":
                return {"ok": True, "workflow": workflow, "already_complete": True}
            index = STAGES.index(stage)
            if index and STAGES[index - 1] not in workflow["stages"]:
                fail("请先完成上一步")
            p = workflow["params"]
            panels = panel_geometry(p)
            output = folder / stage
            output.mkdir(exist_ok=True)
            if stage == "design":
                report = assembly(p, panels, output)
            elif stage == "panels":
                report = {"count": len(panels), "closed": True, "units": "mm", "parts": []}
                for name, poly in panels.items():
                    w, h = poly.bounds[2:]
                    (output / f"{name}.svg").write_text(svg(w, h, [(name, poly)]))
                    report["parts"].append(
                        {"id": name, "size_mm": [w, h], "area_mm2": poly.area, "holes": len(poly.interiors)}
                    )
                # Overview is explicitly a preview, never exported as cutting paths.
                preview = []
                x = y = 8
                row = 0
                for name, poly in panels.items():
                    w, h = poly.bounds[2:]
                    if x + w > 590:
                        x = 8
                        y += row + 14
                        row = 0
                    preview.append((name, affinity.translate(poly, x, y)))
                    x += w + 10
                    row = max(row, h)
                (output / "panels-preview.svg").write_text(svg(600, y + row + 8, preview, True))
            elif stage == "nest":
                sheets, placed = nest(p, panels)
                report = {
                    "sheets": len(sheets),
                    "placements": placed,
                    "sheet_mm": [p["sheet_width_mm"], p["sheet_height_mm"]],
                    "gap_mm": p["gap_mm"],
                    "margin_mm": p["margin_mm"],
                    "collisions": 0,
                    "kerf_mm": p["kerf_mm"],
                    "calibration": "unverified",
                    "files": [],
                }
                for i, items in enumerate(sheets, 1):
                    name = f"sheet-{i:02}.svg"
                    (output / name).write_text(svg(p["sheet_width_mm"], p["sheet_height_mm"], items))
                    (output / f"sheet-{i:02}-preview.svg").write_text(
                        svg(p["sheet_width_mm"], p["sheet_height_mm"], items, True)
                    )
                    report["files"].append(
                        {
                            "name": name,
                            "bounds_mm": list(unary_union([poly for _, poly in items]).bounds),
                            "panels": len(items),
                            "closed_contours": sum(1 + len(poly.interiors) for _, poly in items),
                        }
                    )
                report["utilization_percent"] = (
                    100
                    * sum(poly.area for poly in panels.values())
                    / (len(sheets) * p["sheet_width_mm"] * p["sheet_height_mm"])
                )
            else:
                sheet = body.get("sheet", 1)
                files = workflow["stages"]["nest"]["report"]["files"]
                if not isinstance(sheet, int) or isinstance(sheet, bool) or not 1 <= sheet <= len(files):
                    fail("材料板编号无效")
                source = folder / "nest" / files[sheet - 1]["name"]
                expected = next(
                    a for a in workflow["stages"]["nest"]["artifacts"] if a["name"] == f"nest/{source.name}"
                )
                if hashlib.sha256(source.read_bytes()).hexdigest() != expected["sha256"]:
                    fail("排版文件已改变，请新建任务")
                # A receipt per sheet prevents silent duplicate appends or loss of a partial import.
                client = self.connector()
                import_spec = {**files[sheet - 1], "sheet_mm": workflow["stages"]["nest"]["report"]["sheet_mm"]}
                client.preflight(import_spec)
                pending = output / f"sheet-{sheet:02}-receipt.json"
                if pending.exists():
                    fail("此板已有导入尝试记录，请先核对 LightBurn；不自动重复导入")
                dump(pending, {"status": "attempting", "source_sha256": expected["sha256"], "at": time.time()})
                try:
                    report = client.import_svg(source, import_spec)
                except Exception as exc:
                    dump(pending, {"status": "unverified", "error": str(exc), "at": time.time()})
                    raise
                report.update(sheet=sheet, total_sheets=len(files), source_sha256=expected["sha256"])
                dump(pending, report)
                imported = [
                    i
                    for i in range(1, len(files) + 1)
                    if (output / f"sheet-{i:02}-receipt.json").is_file()
                    and json.loads((output / f"sheet-{i:02}-receipt.json").read_text()).get("status") == "imported"
                ]
                report["imported_sheets"] = imported
                report["remaining_sheets"] = [i for i in range(1, len(files) + 1) if i not in imported]
            dump(output / "report.json", report)
            artifacts = [
                {
                    "name": str(f.relative_to(folder)),
                    "path": str(f),
                    "sha256": hashlib.sha256(f.read_bytes()).hexdigest(),
                }
                for f in sorted(output.iterdir())
                if f.is_file()
            ]
            workflow["stages"][stage] = {
                "status": "partial" if report.get("remaining_sheets") else "completed",
                "at": time.time(),
                "report": report,
                "artifacts": artifacts,
            }
            workflow["revision"] += 1
            workflow["history"].append({"stage": stage, "actor": actor, "at": time.time()})
            dump(folder / "workflow.json", workflow)
            return {"ok": True, "workflow": workflow}
