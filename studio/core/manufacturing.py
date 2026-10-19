"""Persistent manufacturing checkpoints. Geometry runs in the existing task worker.

Sources and previous receipts are immutable. A stage publishes only against its
claim token; interrupted/stale workers cannot overwrite a newer checkpoint.
Neither this module nor its UI sends a job to a printer.
"""

from __future__ import annotations

from contextlib import contextmanager
import copy
import csv
import base64
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import shutil
import time
import uuid
import zipfile

import numpy as np
import trimesh

from studio.core import filelock
from studio.core.editor import EditorError, _atomic, _check_static
from studio.core.tasks import ACTIVE

STAGES = ("inspect", "local_repair", "split", "connect", "coupon", "audit", "prepare", "compare", "deliver", "reprint")
GEOMETRY = ("inspect", "local_repair", "split", "connect")
DEFAULTS = dict(
    printer="Bambu Lab P1S 0.4 nozzle",
    material="PLA",
    scale=1.0,
    target_max_mm=None,
    split_mode="fit",
    palette_rgb=[[255, 255, 255], [255, 0, 0]],
    pull_direction=[0, 0, 1],
    inlay_depth_mm=1.2,
    clearance_mm=0.2,
    radius_mm=2.0,
    depth_mm=6.0,
    min_wall_mm=1.6,
    profile="keyed",
    strategy="auto",
    gap_mm=4.0,
    shape="generic",
    process=None,
    filament=None,
    protected_boxes_mm=[],
    label_map={},
    guided_seam_tolerance_mm=0.0,
)


def fail(message, code="manufacturing_invalid"):
    raise EditorError(message, code=code)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def dump(path, value):
    _atomic(Path(path), (json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2) + "\n").encode())


def clearance_candidates(clearance):
    # Keep three usable samples, including the requested fit, at both limits.
    candidates = [max(clearance - 0.1, clearance / 2), clearance, min(2.0, clearance + 0.1)]
    if candidates[1] == candidates[2]:
        candidates = [clearance - 0.2, clearance - 0.1, clearance]
    rounded = [round(value, 3) for value in candidates]
    return rounded if min(rounded) > 0 and len(set(rounded)) == 3 and clearance in rounded else candidates


def validate_requirements(p):
    if not isinstance(p, dict) or set(p) - set(DEFAULTS):
        fail("制造要求包含未知字段 / Unknown manufacturing requirement")
    p = {**copy.deepcopy(DEFAULTS), **p}
    for k, lo, hi in (
        ("scale", 0, 1000),
        ("target_max_mm", 0, 10000),
        ("clearance_mm", 0, 2),
        ("radius_mm", 0, 20),
        ("depth_mm", 0, 100),
        ("min_wall_mm", 0, 20),
        ("inlay_depth_mm", 0, 100),
        ("gap_mm", -0.001, 100),
        ("guided_seam_tolerance_mm", -0.001, 20),
    ):
        v = p[k]
        if k == "target_max_mm" and v is None:
            continue
        if type(v) not in (int, float) or not math.isfinite(v) or not lo < v <= hi:
            fail(f"制造参数超出范围 / Out of range: {k}")
        if k == "guided_seam_tolerance_mm" and v < 0:
            fail("接缝拟合误差不能为负 / Negative guided seam tolerance")
    if p["target_max_mm"] is not None and p["scale"] != 1:
        fail("scale 与 target_max_mm 不能同时指定 / Conflicting size requirements")
    choices = dict(
        split_mode=("fit", "color", "guided", "keep"),
        profile=("round", "keyed"),
        strategy=("auto", "flat", "support", "upright"),
        shape=("generic", "figurine", "relief", "mechanical"),
    )
    for k, values in choices.items():
        if p[k] not in values:
            fail(f"制造选项无效 / Invalid option: {k}")
    for k in ("printer", "material"):
        if not isinstance(p[k], str) or not 1 <= len(p[k]) <= 200:
            fail(f"制造要求缺失 / Missing requirement: {k}")
    for k in ("process", "filament"):
        if p[k] is not None and (not isinstance(p[k], str) or len(p[k]) > 300):
            fail(f"无效参数 / Invalid: {k}")
    from studio.core.fabrication import vector

    vector(p["pull_direction"], "pull_direction", True)
    colors = np.asarray(p["palette_rgb"])
    if (
        colors.shape[1:] != (3,)
        or not 2 <= len(colors) <= 8
        or colors.dtype.kind not in "iu"
        or np.any((colors < 0) | (colors > 255))
    ):
        fail("色板需要 2–8 个 RGB 整数颜色 / Palette requires 2–8 RGB colors")
    if len(np.unique(colors, axis=0)) != len(colors):
        fail("色板存在重复颜色 / Duplicate palette colors")
    boxes = p["protected_boxes_mm"]
    if not isinstance(boxes, list) or len(boxes) > 32:
        fail("保护区域最多 32 个 / At most 32 protected regions")
    for box in boxes:
        b = np.asarray(box, float)
        if b.shape != (2, 3) or not np.isfinite(b).all() or np.any(b[0] >= b[1]):
            fail("保护区域需要 [minXYZ,maxXYZ] / Invalid protected box")
    if (
        not isinstance(p["label_map"], dict)
        or len(p["label_map"]) > 128
        or any(
            not isinstance(k, str) or not isinstance(v, str) or not v.strip() or len(k) > 100 or len(v) > 100
            for k, v in p["label_map"].items()
        )
    ):
        fail("分区合并映射无效 / Invalid label map")
    return p


class Manufacturing:
    def __init__(self, root, tasks=None):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.tasks = tasks

    def folder(self, identity):
        if not isinstance(identity, str) or not re.fullmatch(r"[a-f0-9]{32}", identity):
            fail("制造流程 ID 无效 / Invalid workflow ID")
        path = self.root / identity
        if not (path / "workflow.json").is_file():
            fail("制造流程不存在 / Workflow not found")
        return path

    @contextmanager
    def locked(self, identity):
        path = self.folder(identity)
        fd = os.open(path / ".lock", os.O_CREAT | os.O_RDWR, 0o600)
        try:
            filelock.lock(fd)
            yield path, json.loads((path / "workflow.json").read_text())
        finally:
            os.close(fd)

    def save(self, path, doc):
        doc["revision"] += 1
        doc["updated"] = time.time()
        dump(path / "workflow.json", doc)

    def create(self, files, requirements=None, title="", source_ids=None):
        if not isinstance(files, list) or not 1 <= len(files) <= 20:
            fail("请选择 1–20 个模型 / Select 1–20 model files")
        p = validate_requirements(requirements or {})
        sources = []
        for value in files:
            f = Path(value).expanduser()
            if not f.is_absolute() or not f.is_file() or f.suffix.lower() not in (".stl", ".glb", ".obj", ".ply"):
                fail("需要绝对路径的 STL/GLB/OBJ/PLY / Expected a local model file")
            if f.stat().st_size > 500_000_000:
                fail("单个模型不能超过 500 MB / Model exceeds 500 MB")
            _check_static(f)
            sources.append(f)
        identity = uuid.uuid4().hex
        path = self.root / identity
        (path / "sources").mkdir(parents=True)
        frozen = []
        try:
            for i, f in enumerate(sources):
                digest = sha(f)
                dest = path / "sources" / f"{i:02d}" / f.name
                dest.parent.mkdir()
                shutil.copyfile(f, dest)
                if sha(dest) != digest or sha(f) != digest:
                    fail("导入过程中源模型发生变化 / Source changed during import")
                frozen.append(dict(path=str(dest), name=f.name, source_sha256=digest))
            doc = dict(
                schema_version=1,
                id=identity,
                title=str(title or sources[0].stem)[:160],
                revision=0,
                created=time.time(),
                updated=time.time(),
                sources=frozen,
                source_ids=source_ids or [],
                requirements=p,
                stages={},
                history=[],
                active=None,
                defects=[],
                calibration=[],
                labels=None,
                repair_api=dict(
                    status="not_connected",
                    available=False,
                    input_sha256=[x["source_sha256"] for x in frozen],
                    reinspection_required=True,
                ),
            )
            dump(path / "workflow.json", doc)
            return doc
        except Exception:
            shutil.rmtree(path)
            raise

    def allowed(self, doc, scope):
        return scope is None or bool(doc["source_ids"]) and set(doc["source_ids"]) <= set(scope)

    def read(self, identity, scope=None):
        with self.locked(identity) as (path, doc):
            if not self.allowed(doc, scope):
                fail("当前部件会话不能访问此制造流程 / Workflow outside scope", "scope_violation")
            active = doc.get("active")
            if active and active.get("task_id") and self.tasks:
                state = self.tasks.state(active["task_id"])
                if state["status"] not in ACTIVE:
                    # Worker failures/timeouts do not run our finally block.
                    row = doc["stages"][active["stage"]]
                    row.update(
                        status="interrupted" if state["status"] == "completed" else state["status"],
                        error=state.get("error") or "任务未发布检查点 / No checkpoint published",
                    )
                    doc["active"] = None
                    self.save(path, doc)
            return doc

    def execute(self, body, actor="ai", scope=None):
        action = body.get("action", "list")
        if action == "list":
            rows = [self.read(p.parent.name, scope=None) for p in self.root.glob("*/workflow.json")]
            return dict(
                ok=True,
                workflows=sorted([d for d in rows if self.allowed(d, scope)], key=lambda d: d["updated"], reverse=True)[
                    :100
                ],
            )
        if action == "create":
            if scope is not None and (not body.get("source_ids") or not set(body["source_ids"]) <= set(scope)):
                fail("部件会话只能使用当前选区 / Scoped workflow requires selected parts", "scope_violation")
            return dict(
                ok=True,
                workflow=self.create(
                    body.get("files"), body.get("requirements"), body.get("title"), body.get("source_ids")
                ),
            )
        identity = body.get("id")
        doc = self.read(identity, scope)
        if action == "read":
            return dict(ok=True, workflow=doc)
        if action == "repair_status":
            return dict(ok=True, workflow=doc, repair_api=doc["repair_api"])
        if action == "photo":
            defect = next((d for d in doc["defects"] if d["id"] == body.get("defect_id")), None)
            index = body.get("photo_index")
            if not defect or type(index) is not int or not 0 <= index < len(defect["photos"]):
                fail("缺陷照片不存在 / Defect photo not found")
            photo = defect["photos"][index]
            if sha(photo["path"]) != photo["sha256"]:
                fail("缺陷证据指纹发生变化 / Defect evidence hash changed")
            from PIL import Image, ImageOps

            with Image.open(photo["path"]) as im:
                im = ImageOps.exif_transpose(im).convert("RGB")
                im.thumbnail((1200, 1200))
                buffer = io.BytesIO()
                im.save(buffer, format="JPEG", quality=85)
            return dict(
                ok=True,
                mime="image/jpeg",
                data_base64=base64.b64encode(buffer.getvalue()).decode(),
                source_sha256=photo["sha256"],
            )
        if body.get("expected_revision") != doc["revision"]:
            fail("制造流程已变化，请刷新 / Workflow changed; refresh first", "revision_conflict")
        if action == "cancel":
            if not doc.get("active") or not doc["active"].get("task_id"):
                fail("没有正在运行的阶段 / No running stage")
            return self.tasks.cancel(doc["active"]["task_id"])
        with self.locked(identity) as (path, doc):
            if body["expected_revision"] != doc["revision"]:
                fail("制造流程已变化，请刷新 / Workflow changed", "revision_conflict")
            if doc.get("active"):
                fail("请等待当前阶段结束或取消 / Wait for or cancel current stage", "busy")
            if action == "update":
                next_p = validate_requirements({**doc["requirements"], **body.get("requirements", {})})
                changed = {k for k in next_p if next_p[k] != doc["requirements"].get(k, DEFAULTS[k])}
                if not changed:
                    return dict(ok=True, workflow=doc)
                if changed & {"scale", "target_max_mm", "min_wall_mm"}:
                    invalid = STAGES
                elif changed & {
                    "split_mode",
                    "palette_rgb",
                    "pull_direction",
                    "inlay_depth_mm",
                    "protected_boxes_mm",
                    "label_map",
                    "guided_seam_tolerance_mm",
                }:
                    invalid = STAGES[2:]
                elif "clearance_mm" in changed and next_p["split_mode"] == "color":
                    invalid = STAGES[2:]
                elif changed & {"radius_mm", "depth_mm", "profile", "clearance_mm"}:
                    invalid = STAGES[3:]
                elif changed & {"printer"}:
                    invalid = STAGES[2:]
                else:
                    invalid = STAGES[6:]
                if "material" in changed:
                    invalid = (*invalid, "coupon")
                for stage in invalid:
                    if stage in doc["stages"]:
                        doc["stages"][stage]["status"] = "stale"
                doc["requirements"] = next_p
            elif action == "labels":
                value = body.get("labels")
                if not isinstance(value, dict) or value.get("source_sha256") not in [
                    x["source_sha256"] for x in doc["sources"]
                ]:
                    fail("分区必须绑定当前源模型 SHA256 / Labels must match source SHA256")
                if len(json.dumps(value)) > 20_000_000:
                    fail("分区文件过大 / Label document too large")
                if doc.get("labels") == value:
                    return dict(ok=True, workflow=doc)
                doc["labels"] = value
                for stage in STAGES[2:]:
                    if stage in doc["stages"]:
                        doc["stages"][stage]["status"] = "stale"
            elif action == "defect":
                if actor != "human":
                    fail("实物缺陷记录需要本人操作 / Physical records require human input", "human_required")
                text = body.get("note", "")
                if not isinstance(text, str) or not text.strip() or len(text) > 2000:
                    fail("请填写缺陷与实物复检记录 / Describe the physical observation")
                old = next((d for d in doc["defects"] if d["id"] == body.get("defect_id")), None)
                if old:
                    if body.get("resolved") is not True:
                        fail("复检需要明确的 resolved=true / Explicit physical reinspection required")
                    old.update(resolved=True, reinspection=text, resolved_at=time.time())
                else:
                    photos = []
                    if not isinstance(body.get("photos", []), list) or len(body.get("photos", [])) > 10:
                        fail("每项缺陷最多 10 张照片 / At most 10 photos per defect")
                    for item in body.get("photos", []):
                        f = Path(item)
                        if (
                            not f.is_absolute()
                            or not f.is_file()
                            or f.suffix.lower() not in (".jpg", ".jpeg", ".png")
                            or f.stat().st_size > 20_000_000
                        ):
                            fail("缺陷照片无效 / Invalid defect photograph")
                        dest = path / "evidence" / (uuid.uuid4().hex + f.suffix.lower())
                        dest.parent.mkdir(exist_ok=True)
                        shutil.copyfile(f, dest)
                        photos.append(dict(path=str(dest), sha256=sha(dest)))
                    doc["defects"].append(
                        dict(id=uuid.uuid4().hex, note=text, photos=photos, resolved=False, at=time.time())
                    )
                for stage in ("audit", "deliver"):
                    if stage in doc["stages"]:
                        doc["stages"][stage]["status"] = "stale"
            elif action == "calibration":
                if actor != "human":
                    fail("实物公差标定需要本人操作 / Calibration requires human input", "human_required")
                value = body.get("clearance_mm")
                validate_requirements({"clearance_mm": value})
                note = body.get("note", "")
                if not isinstance(note, str) or not note.strip() or len(note) > 2000:
                    fail("请记录实际试片结果 / Record physical coupon outcome")
                coupon = doc["stages"].get("coupon", {})
                if coupon.get("status") != "completed" or value not in coupon["report"]["clearance_candidates_mm"]:
                    fail("请选择已生成试片中的公差 / Select a generated coupon clearance")
                doc["calibration"].append(
                    dict(
                        printer=doc["requirements"]["printer"],
                        material=doc["requirements"]["material"],
                        clearance_mm=value,
                        note=note,
                        coupon_sha256=coupon["sha256"],
                        at=time.time(),
                    )
                )
            elif action == "run":
                stage = body.get("stage")
                if stage not in STAGES:
                    fail("制造阶段无效 / Invalid stage")
                self.check_stage(doc, stage, body)
                token = uuid.uuid4().hex
                prior = copy.deepcopy(doc["stages"])
                doc["history"].append(dict(stage=stage, previous=prior.get(stage), at=time.time()))
                # Preserve prior immutable artifacts, invalidate dependants.
                if stage in GEOMETRY:
                    start = STAGES.index(stage) + 1
                    for s in STAGES[start:]:
                        if s != "coupon" and s in doc["stages"]:
                            doc["stages"][s]["status"] = "stale"
                elif stage == "prepare":
                    for s in ("compare", "deliver"):
                        if s in doc["stages"]:
                            doc["stages"][s]["status"] = "stale"
                doc["active"] = dict(stage=stage, token=token)
                doc["stages"][stage] = dict(status="running", token=token, started=time.time())
                self.save(path, doc)
                try:
                    result = self.tasks.start(
                        dict(
                            engine="python",
                            render_preview=False,
                            timeout_seconds=1800,
                            title=f"制造准备 · {stage} · {doc['title']}",
                            script="from studio.core.manufacturing import run\nrun(workbench)",
                            params=dict(
                                root=str(self.root),
                                id=identity,
                                token=token,
                                stage=stage,
                                snapshot={**doc, "stages": prior},
                                part_ids=body.get("part_ids"),
                            ),
                            inputs=[x["path"] for x in doc["sources"]],
                        ),
                        actor,
                    )
                except Exception:
                    doc["active"] = None
                    doc["stages"][stage]["status"] = "failed"
                    self.save(path, doc)
                    raise
                doc["active"]["task_id"] = result["task"]["id"]
                doc["stages"][stage]["task_id"] = result["task"]["id"]
                self.save(path, doc)
                return dict(ok=True, workflow=doc, task=result["task"], print_submitted=False)
            else:
                fail("制造操作无效 / Invalid manufacturing action")
            self.save(path, doc)
            return dict(ok=True, workflow=doc, print_submitted=False)

    def check_stage(self, doc, stage, body):
        def done(s):
            return doc["stages"].get(s, {}).get("status") == "completed"

        if stage in ("local_repair", "split") and not done("inspect"):
            fail("请先完成模型诊断 / Inspect model first")
        if stage == "split" and doc["requirements"]["split_mode"] == "guided" and len(doc["sources"]) != 1:
            fail("P3 引导切割需要单个源模型；请分别创建制造任务 / Guided splitting requires a single source model")
        if stage in ("connect", "audit", "prepare", "compare", "deliver", "reprint") and not done("split"):
            fail("请先完成拆件；保留整件也要验证 / Run split or keep stage first")
        if stage in ("connect", "audit", "prepare", "compare", "deliver", "reprint"):
            source = current_geometry(doc)
            if not source["report"].get("closed_outputs", False):
                fail("开放分区不能进入制造 / Open regions cannot enter manufacturing")
        if stage == "deliver" and (not done("audit") or not done("prepare")):
            fail("交付前需要装配复检与出盘 / Audit and plate preparation required")
        if stage == "deliver" and not isinstance(
            doc["stages"]["audit"]["report"].get("unchecked_thickness_parts"), list
        ):
            fail("旧装配报告缺少壁厚检查完整性记录，请重跑装配复检 / Rerun audit to verify thickness coverage")
        if stage == "deliver" and (
            doc["stages"]["audit"]["report"]["status"] != "pass_sampled"
            or doc["stages"]["audit"]["report"]["unchecked_thickness_parts"]
            or any(not d["resolved"] for d in doc["defects"])
        ):
            fail("存在装配问题或未复检的实物缺陷 / Unresolved assembly or physical defect")
        if stage == "reprint":
            parts = current_geometry(doc)["report"]["parts"]
            ids = body.get("part_ids")
            if (
                not isinstance(ids, list)
                or not ids
                or len(ids) != len(set(ids))
                or not set(ids) <= {p["id"] for p in parts}
            ):
                fail("请选择需要重打的有效零件 / Select valid parts to reprint")


def current_geometry(doc):
    for stage in reversed(GEOMETRY):
        row = doc["stages"].get(stage, {})
        if row.get("status") == "completed":
            if sha(row["scene"]) != row["sha256"] or sha(row["geometry"]) != row["geometry_sha256"]:
                fail("检查点模型已变化 / Checkpoint model changed")
            return row
    fail("没有可用模型检查点 / No model checkpoint")


def checkpoint_meshes(row):
    meshes = load_meshes([row["scene"]])
    with np.load(row["geometry"], allow_pickle=False) as data:
        for i, name in enumerate(data["names"].tolist()):
            meshes[name] = trimesh.Trimesh(
                data[f"v{i}"], data[f"f{i}"], process=False, visual=meshes[name].visual.copy()
            )
    return meshes


def load_meshes(files, *, safe_names=True):
    from studio.core.task_operations import scene_input

    result = {}
    for f in files:
        scene = scene_input(f)
        for node in scene.graph.nodes_geometry:
            transform, key = scene.graph[node]
            mesh = scene.geometry[key].copy()
            mesh.apply_transform(transform)
            name = (re.sub(r"[^\w-]", "_", str(node))[:80] or "mesh") if safe_names else str(node)
            mesh.metadata["source_node"] = str(node)
            while name in result:
                name += "_copy"
            result[name] = mesh
    if not result or len(result) > 128 or any(not isinstance(m, trimesh.Trimesh) for m in result.values()):
        fail("需要 1–128 个静态网格 / Expected static meshes")
    return result


def welded(mesh):
    v, inverse = np.unique(mesh.vertices, axis=0, return_inverse=True)
    return trimesh.Trimesh(v, inverse[mesh.faces], process=False)


def thickness_samples(mesh, wall):
    """Up to 96 deterministic inward rays; dense meshes use a triangle index.

    Keep the same exact ray/triangle test and sample faces on both paths. The
    near segment finds thin walls cheaply; otherwise search to the mesh diagonal.
    Missing exit hits are incomplete evidence, never whole-wall proof.
    """
    if not len(mesh.faces):
        return dict(status="not_checked", reason="empty_mesh", whole_wall_verified=False)
    tri = mesh.triangles
    e1, e2 = tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]
    tree = mesh.triangles_tree if len(tri) > 30000 else None
    values = []
    eps = max(float(mesh.extents.max()) * 1e-8, 1e-7)
    travel = float(np.linalg.norm(mesh.extents)) + eps
    pad = max(float(mesh.extents.max()) * 1e-7, eps)
    count = min(96, len(tri))
    for i in np.linspace(0, len(tri) - 1, count, dtype=int):
        direction = -mesh.face_normals[i]
        origin = mesh.triangles_center[i] + direction * eps
        for distance in ((wall, travel) if tree is not None else (travel,)):
            if tree is None:
                a, b, starts = e1, e2, tri[:, 0]
            else:
                end = origin + direction * distance
                # Include the existing barycentric tolerance at triangle edges.
                bounds = np.r_[np.minimum(origin, end) - pad, np.maximum(origin, end) + pad]
                ids = np.fromiter(tree.intersection(bounds), dtype=np.int64)
                a, b, starts = e1[ids], e2[ids], tri[ids, 0]
            h = np.cross(direction, b)
            det = np.einsum("ij,ij->i", a, h)
            inv = np.divide(1.0, det, out=np.zeros_like(det), where=np.abs(det) > 1e-12)
            s = origin - starts
            u = inv * np.einsum("ij,ij->i", s, h)
            q = np.cross(s, a)
            v = inv * (q @ direction)
            t = inv * np.einsum("ij,ij->i", b, q)
            hits = t[(np.abs(det) > 1e-12) & (u >= -1e-8) & (v >= -1e-8) & (u + v <= 1 + 1e-8)
                     & (t > eps) & (t <= distance)]
            if len(hits):
                values.append(dict(face=int(i), thickness_mm=float(hits.min() + eps)))
                break
    return dict(
        status="sampled" if len(values) == count else "incomplete",
        samples=values,
        min_sample_mm=min((v["thickness_mm"] for v in values), default=None),
        thin_samples=[v for v in values if v["thickness_mm"] < wall],
        whole_wall_verified=False,
    )


def diagnostic(meshes, requirements):
    from studio.core.kernels import mechanical_geometry as g

    rows = []
    for name, original in meshes.items():
        mesh = welded(original)
        finite = bool(np.isfinite(mesh.vertices).all())
        solid = False
        if finite and mesh.is_volume:
            try:
                solid = g.solid(mesh).status().name == "NoError"
            except Exception:
                pass
        counts = np.unique(np.sort(mesh.edges, axis=1), axis=0, return_counts=True)[1]
        rows.append(
            dict(
                name=name,
                source_node=original.metadata.get("source_node", name),
                faces=len(mesh.faces),
                extents_mm=mesh.extents.tolist(),
                open_edges=int(np.sum(counts == 1)),
                nonmanifold_edges=int(np.sum(counts > 2)),
                degenerate_faces=int(np.sum(mesh.area_faces < 1e-10)),
                finite=finite,
                watertight=bool(mesh.is_watertight),
                winding_consistent=bool(mesh.is_winding_consistent),
                solid_valid=solid,
                components=len(mesh.split(only_watertight=False)),
                thickness=thickness_samples(mesh, requirements["min_wall_mm"]) if solid else dict(status="not_checked"),
            )
        )
    closed = all(r["solid_valid"] and not r["degenerate_faces"] for r in rows)
    return dict(
        diagnostics=rows,
        closed_outputs=closed,
        units="mm",
        axis="Z-up",
        self_intersections="not_exhaustively_checked",
        status="checked_with_limits" if closed else "needs_repair",
        physical_quality_verified=False,
    )


def cap_planar(mesh):
    """Close planar simple boundary loops; reject curved or ambiguous seams."""
    from shapely.geometry import Polygon
    from shapely.ops import triangulate

    mesh = welded(mesh)
    edges, first, counts = np.unique(np.sort(mesh.edges, axis=1), axis=0, return_index=True, return_counts=True)
    boundary = edges[counts == 1]
    links = {}
    for a, b in boundary:
        links.setdefault(int(a), []).append(int(b))
        links.setdefault(int(b), []).append(int(a))
    if any(len(v) != 2 for v in links.values()):
        fail("分区边界不是简单闭环 / Region boundary is not a simple loop")
    faces = list(mesh.faces)
    remaining = set(links)
    while remaining:
        start = min(remaining)
        loop, prev, cur = [], None, start
        while True:
            loop.append(cur)
            remaining.discard(cur)
            nxt = next(n for n in links[cur] if n != prev)
            prev, cur = cur, nxt
            if cur == start:
                break
            if cur in loop:
                fail("分区边界有交叉 / Ambiguous region boundary")
        points = mesh.vertices[loop]
        center = points.mean(0)
        _, _, basis = np.linalg.svd(points - center)
        if np.max(np.abs((points - center) @ basis[2])) > 1e-4:
            fail("引导分区接缝不是平面；需要切割 API 封口 / Nonplanar seam needs cutting API completion")
        xy = (points - center) @ basis[:2].T
        poly = Polygon(xy)
        if not poly.is_valid or poly.area < 1e-8:
            fail("分区封口轮廓无效 / Invalid cap polygon")
        triangles = [t for t in triangulate(poly) if poly.covers(t)]
        if not np.isclose(sum(t.area for t in triangles), poly.area, rtol=1e-6):
            fail("封口没有覆盖完整边界 / Cap coverage failed")
        for triangle in triangles:
            coords = np.asarray(triangle.exterior.coords)[:3]
            ids = [loop[int(np.linalg.norm(xy - q, axis=1).argmin())] for q in coords]
            faces.append(ids)
    result = trimesh.Trimesh(mesh.vertices, faces, process=False)
    trimesh.repair.fix_normals(result, multibody=True)
    if not result.is_volume:
        fail("分区封口后不是闭合实体 / Capped region is not a solid")
    return result


def fitted_guided_regions(mesh, values, tolerance, protected_boxes, min_wall_mm=0):
    """Bounded common planes cut the source solid, never rebuild its surface.

    A coordinate-axis chain of 2–16 regions is required. Up to 22 bounded
    proposals per axis are tried. Each boundary vertex respects the requested
    tolerance and conservative exterior reassignment is <=5% per region and
    interval, counting crossing triangles in full. Thinness is sampled only.
    """
    from studio.core.kernels import mechanical_geometry as g

    mesh = welded(mesh)
    labels = sorted(set(values))
    if len(labels) == 1:
        return [(labels[0], mesh)], dict(method="single_region", cuts=[])
    if not mesh.is_volume or not 2 <= len(labels) <= 16:
        fail("平面拟合需要闭合实体和 2–16 个合并分区 / Merge labels on a closed solid")
    boundaries = {}
    for faces, edge in zip(mesh.face_adjacency, mesh.face_adjacency_edges):
        a, b = values[faces]
        if a != b:
            boundaries.setdefault(tuple(sorted((a, b))), []).extend(edge)
    candidates = []
    for axis in range(3):
        order = sorted(labels, key=lambda label: np.average(
            mesh.triangles_center[values == label, axis], weights=mesh.area_faces[values == label]))
        pairs = [tuple(sorted(pair)) for pair in zip(order, order[1:])]
        if set(boundaries) != set(pairs):
            continue
        coordinates = [mesh.vertices[np.unique(boundaries[pair]), axis] for pair in pairs]
        midpoints = np.array([(q.min() + q.max()) / 2 for q in coordinates])
        slacks = tolerance - np.array([np.ptp(q) / 2 for q in coordinates])
        if np.any(slacks < 0):
            continue
        representative = np.clip([np.median(q) for q in coordinates], midpoints - slacks / 2, midpoints + slacks / 2)
        proposals = [representative, *[midpoints + f * slacks for f in np.linspace(-1, 1, 21)]]
        seen = set()
        for offsets in proposals:
            key = tuple(np.round(offsets, 9))
            if key in seen or np.any(np.diff(offsets) <= 1e-6):
                continue
            seen.add(key)
            cuts = [dict(axis="XYZ"[axis], offset_mm=float(off),
                         max_boundary_error_mm=float(np.max(np.abs(q - off))), labels=list(pair))
                    for off, q, pair in zip(offsets, coordinates, pairs)]
            if any(c["max_boundary_error_mm"] > tolerance + 1e-9 or
                   any(box[0][axis] < c["offset_mm"] < box[1][axis] for box in protected_boxes) for c in cuts):
                continue
            lower = mesh.triangles[:, :, axis].min(1)
            upper = mesh.triangles[:, :, axis].max(1)
            crossing = np.any((lower[:, None] < offsets - 1e-7) & (upper[:, None] > offsets + 1e-7), axis=1)
            predicted = np.searchsorted(offsets, mesh.triangles_center[:, axis])
            agreement = []
            for i, label in enumerate(order):
                owned, interval = values == label, predicted == i
                error = crossing | (owned != interval)
                recall_error = float(mesh.area_faces[owned & error].sum() / mesh.area_faces[owned].sum())
                interval_error = float(mesh.area_faces[interval & error].sum() / mesh.area_faces[interval].sum()) if np.any(interval) else 1.0
                agreement.append(dict(label=label, worst_surface_reassignment_fraction=recall_error,
                                      worst_interval_reassignment_fraction=interval_error))
            if any(max(row["worst_surface_reassignment_fraction"], row["worst_interval_reassignment_fraction"]) > .05 for row in agreement):
                continue
            candidates.append((max(c["max_boundary_error_mm"] for c in cuts), axis, order, cuts, agreement))
    for _, axis, order, cuts, agreement in sorted(candidates, key=lambda item: (item[0], item[1])):
        remainder = g.solid(mesh)
        outputs = []
        try:
            for label, cut in zip(order, cuts):
                positive, negative = remainder.split_by_plane(np.eye(3)[axis], cut["offset_mm"])
                outputs.append((label, g.mesh(negative)))
                remainder = positive
            outputs.append((order[-1], g.mesh(remainder)))
        except ValueError:
            continue
        if any(len(g.solid(piece).decompose()) != 1 for _, piece in outputs):
            continue
        samples = [(label, thickness_samples(piece, min_wall_mm)) for label, piece in outputs] if min_wall_mm else []
        if any(row["status"] != "sampled" or row["min_sample_mm"] is None or row["thin_samples"] for _, row in samples):
            continue
        return outputs, dict(method="source_solid_common_planes", tolerance_mm=tolerance,
                             cuts=cuts, surface_agreement=agreement, max_reassignment_fraction=.05,
                             candidate_count=len(candidates), thickness_samples=dict(samples),
                             original_exterior_preserved=True, semantic_quality="review_required")
    fail("分区拟合的误差、归属、连通实体、保护区域或采样厚度检查未通过 / Guided seam fit rejected")


def split_meshes(meshes, doc, out):
    from studio.core.auto_cut import CutPlanner
    from print_prep import cli, profiles, printer_catalog
    from studio.core.kernels import mechanical_geometry as g

    p = doc["requirements"]
    mode, reports = p["split_mode"], []
    if mode == "keep":
        return meshes, dict(operation="keep", cuts=[], semantic_protection=False)
    if mode == "fit":
        _, _, idx, name = printer_catalog.context(p["printer"])
        bed = {**profiles.bed_params(profiles.resolve(name, idx)), "margin_mm": cli.DEFAULT_MARGIN_MM}

        class ProtectedPlanner(CutPlanner):
            def split(self, mesh, axis, fraction):
                offset = mesh.bounds[0, axis] + mesh.extents[axis] * fraction
                if any(box[0][axis] < offset < box[1][axis] for box in p["protected_boxes_mm"]):
                    return None
                return super().split(mesh, axis, fraction)

        pieces = {}
        for name, mesh in meshes.items():
            plan = ProtectedPlanner(bed).plan(welded(mesh), name)
            for i, piece in enumerate(plan["pieces"]):
                pieces[f"{name}_cut_{i + 1}"] = piece["mesh"]
            reports.append({k: v for k, v in plan.items() if k != "pieces"})
        return pieces, dict(
            operation="fit", plans=reports, protected_boxes_mm=p["protected_boxes_mm"], original_size_preserved=True
        )
    if mode == "color":
        from studio.core.color_inlays import run as color

        source = current_geometry(doc)["scene"]
        color(
            dict(
                inputs=[source],
                output=str(out),
                params=dict(
                    palette_rgb=p["palette_rgb"],
                    pull_direction=p["pull_direction"],
                    depth_mm=p["inlay_depth_mm"],
                    clearance_mm=p["clearance_mm"],
                ),
            )
        )
        return load_meshes([out / "scene.glb"]), json.loads((out / "report.json").read_text())
    labels = doc.get("labels")
    if not labels:
        fail("请导入 P3-RW 分区标签并确认 / Import source-bound P3-RW labels")
    source = next(s for s in doc["sources"] if s["source_sha256"] == labels["source_sha256"])
    original = load_meshes([source["path"]], safe_names=False)
    if set(labels.get("nodes", {})) != set(original):
        fail("分区标签的节点与源模型不一致 / Label nodes differ from source")
    ratio = doc["stages"]["inspect"]["report"]["scale_applied"]
    pieces = {}
    fitted = []
    for node, mesh in original.items():
        mesh.apply_scale(ratio)
        values = labels["nodes"][node]
        if len(values) != len(mesh.faces) or not all(isinstance(x, str) and 0 < len(x) <= 100 for x in values):
            fail("每一个源面都需要有效标签 / Every source face needs a label")
        values = np.array([p["label_map"].get(x, x) for x in values])
        outputs = []
        tolerance = p.get("guided_seam_tolerance_mm", 0)
        if tolerance:
            regions, fit = fitted_guided_regions(mesh, values, tolerance, p["protected_boxes_mm"], p["min_wall_mm"])
            fitted.append(dict(node=node, **fit))
        else:
            regions = [(label, cap_planar(mesh.submesh([np.flatnonzero(values == label)], append=True, repair=False)))
                       for label in sorted(set(values))]
        for label, part in regions:
            if len(pieces) >= 32:
                fail("分区超过 32 件；请合并碎件 / Merge fragments to <=32 parts")
            safe_label = re.sub(r"[^\w-]", "_", label)[:60]
            pieces[f"region_{len(pieces) + 1:03d}_{safe_label}"] = part
            outputs.append(part)
            reports.append(dict(node=node, label=label, faces=int(np.sum(values == label))))
        solids = [g.solid(m) for m in outputs]
        from itertools import combinations

        if any(g.overlap(a, b) > 1e-5 for a, b in combinations(solids, 2)) or not np.isclose(
            sum(m.volume for m in outputs), welded(mesh).volume, rtol=1e-5
        ):
            fail("分区有重叠或丢失体积 / Regions overlap or lose volume")
    return pieces, dict(
        operation="guided",
        source_sha256=labels["source_sha256"],
        regions=reports,
        capped=True,
        label_map=p["label_map"],
        seam_fits=fitted,
        semantic_quality="human_review_required",
    )


def connect_meshes(meshes, p, out):
    from shapely.geometry import Polygon
    from shapely.ops import unary_union, polylabel
    from studio.core.connect_parts import run as connect
    from studio.core.task_operations import deliver
    from studio.core.kernels import mechanical_geometry as g

    if not 2 <= len(meshes) <= 16:
        fail("自动定位销需要 2–16 件 / Automatic pins require 2–16 parts")
    bodies = dict(meshes)
    pins, seams, used = {}, [], []
    names = list(meshes)
    for i, a in enumerate(names):
        for b in names[i + 1 :]:
            ma, mb = bodies[a], bodies[b]
            for axis in range(3):
                pair = (a, b) if abs(ma.bounds[1, axis] - mb.bounds[0, axis]) < 0.001 else (b, a)
                neg, pos = (bodies[n] for n in pair)
                plane = neg.bounds[1, axis]
                if abs(plane - pos.bounds[0, axis]) >= 0.001:
                    continue
                uv = [k for k in range(3) if k != axis]

                def patch(m):
                    mask = np.all(np.abs(m.triangles[:, :, axis] - plane) < 0.001, axis=1)
                    return unary_union([Polygon(t[:, uv]) for t in m.triangles[mask]])

                region = patch(neg).intersection(patch(pos))
                guard = p["radius_mm"] + p["clearance_mm"] + p["min_wall_mm"]
                safe = region.buffer(-guard)
                if safe.is_empty:
                    continue
                if safe.geom_type == "MultiPolygon":
                    safe = max(safe.geoms, key=lambda s: s.area)
                if safe.geom_type != "Polygon":
                    continue
                point = polylabel(safe, tolerance=0.05)
                center = np.zeros(3)
                center[axis] = plane
                center[uv] = [point.x, point.y]
                direction = np.eye(3)[axis]
                hint = np.eye(3)[uv[0]]
                plan = dict(
                    center_mm=center.tolist(),
                    axis=direction.tolist(),
                    x_hint=hint.tolist(),
                    **{k: p[k] for k in ("radius_mm", "depth_mm", "clearance_mm", "min_wall_mm", "profile")},
                )
                folder = out / f"seam_{len(seams):02d}"
                folder.mkdir()
                deliver(dict(zip(pair, (neg, pos))), folder, {}, stl=False)
                connect(
                    dict(
                        inputs=[str(folder / "scene.glb")],
                        output=str(folder),
                        params=dict(parts=list(pair), connectors=[plan]),
                    )
                )
                # Keep exact kernel coordinates for subsequent booleans; the
                # GLB display copy rounds coordinates to float32 metres.
                radius, depth, gap = p["radius_mm"], p["depth_mm"], p["clearance_mm"]
                frame = g.frame(direction, hint)
                for side, name in enumerate(pair):
                    lo, hi = (-depth, 0.01) if side == 0 else (-0.01, depth)
                    bore = g.keyed(radius, lo, hi, gap) if p["profile"] == "keyed" else g.cyl(radius + gap, lo, hi)
                    bodies[name] = g.mesh(g.solid(bodies[name]) - g.transform(bore, frame, center))
                pin = (
                    g.keyed(radius, -depth + gap, depth - gap)
                    if p["profile"] == "keyed"
                    else g.cyl(radius, -depth + gap, depth - gap)
                )
                pins[f"pin_{len(pins) + 1:03d}"] = g.mesh(g.transform(pin, frame, center))
                used.append(tuple(sorted(pair)))
                seams.append(
                    dict(parts=list(pair), connector=plan, report=json.loads((folder / "report.json").read_text()))
                )
                break
    if not seams:
        fail("没有满足销孔壁厚的共享平面接缝；请调整拆件或参数 / No usable planar seam with requested socket walls")
    connected = {names[0]}
    while True:
        new = connected | {n for pair in used if set(pair) & connected for n in pair}
        if new == connected:
            break
        connected = new
    if connected != set(names):
        fail("部分零件没有可制造的定位接口 / Some parts lack manufacturable interfaces")
    all_parts = {**bodies, **pins}
    from itertools import combinations

    solids = [g.solid(m) for m in all_parts.values()]
    if any(g.overlap(a, b) > 1e-5 for a, b in combinations(solids, 2)):
        fail("连接加工后存在零件干涉 / Parts interfere after connector machining")
    # Recheck all earlier hole walls after all later holes have been machined.
    for seam in seams:
        q = seam["connector"]
        frame = g.frame(q["axis"], q["x_hint"])
        r, wall, d, gap = q["radius_mm"], q["min_wall_mm"], q["depth_mm"], q["clearance_mm"]
        for side, name in enumerate(seam["parts"]):
            lo, hi = (-d - wall, -1e-4) if side == 0 else (1e-4, d + wall)
            guard_solid = g.transform(g.cyl(r + gap + wall, lo, hi), frame, q["center_mm"])
            lo, hi = (-d, 0.01) if side == 0 else (-0.01, d)
            bore = g.keyed(r, lo, hi, gap) if q["profile"] == "keyed" else g.cyl(r + gap, lo, hi)
            required = guard_solid - g.transform(bore, frame, q["center_mm"])
            if (required - g.solid(bodies[name])).volume() > 1e-5:
                fail("后续孔破坏了已有孔壁 / Later socket damaged an earlier wall")
    return all_parts, dict(
        operation="automatic_planar_pins", seams=seams, holding_strength_verified=False, physical_calibration="pending"
    )


def assembly_audit(meshes, doc):
    from itertools import combinations
    from studio.core.kernels import mechanical_geometry as g

    solids = {n: g.solid(m) for n, m in meshes.items()}
    overlaps = [dict(parts=[a, b], overlap_mm3=g.overlap(solids[a], solids[b])) for a, b in combinations(solids, 2)]
    clashes = [r for r in overlaps if r["overlap_mm3"] > 1e-5]
    remaining, steps = list(solids), []
    distance = float(np.ptp(np.vstack([m.vertices for m in meshes.values()]), axis=0).max()) * 2 + 1
    while remaining and not clashes:
        found = False
        for n in remaining:
            others = [solids[q] for q in remaining if q != n]
            for axis in [sign * v for v in np.eye(3) for sign in (-1, 1)]:
                samples = []
                for t in np.linspace(0, distance, 41):
                    moving = solids[n].translate((axis * t).tolist())
                    overlap = 0.0
                    for other in others:
                        overlap += g.overlap(moving, other)
                        if overlap >= 1e-5:
                            break
                    samples.append(overlap)
                    # One collision rejects a direction; passing directions
                    # still evaluate all 41 poses against every remaining part.
                    if overlap >= 1e-5:
                        break
                if max(samples) < 1e-5:
                    steps.append(
                        dict(
                            part=n,
                            direction=axis.tolist(),
                            travel_mm=distance,
                            samples=41,
                            max_overlap_mm3=max(samples),
                        )
                    )
                    remaining.remove(n)
                    found = True
                    break
            if found:
                break
        if not found:
            break
    defect = any(not x["resolved"] for x in doc["defects"])
    thickness = {n: thickness_samples(welded(m), doc["requirements"]["min_wall_mm"])
                 for n, m in meshes.items() if not n.startswith("pin_")}
    thin = [n for n, row in thickness.items() if row.get("thin_samples")]
    unchecked = [n for n, row in thickness.items()
                 if row.get("status") != "sampled" or not row.get("samples")]
    return dict(
        status="needs_review" if clashes or remaining or defect or thin or unchecked else "pass_sampled",
        overlaps=overlaps,
        disassembly_steps=steps,
        assembly_order=[x["part"] for x in reversed(steps)],
        unresolved_parts=remaining,
        thin_sample_parts=thin,
        unchecked_thickness_parts=unchecked,
        unresolved_physical_defects=defect,
        continuous_motion_checked=False,
        physical_quality_verified=False,
        self_intersections="not_exhaustively_checked",
    )


def plate_job(meshes, requirements, out, strategy=None, check=False):
    from studio.core import print_state
    from studio.core.geometry_store import stl_bytes
    from print_prep import job

    folder = out / (strategy or "plates")
    (folder / "sources").mkdir(parents=True)
    files = []
    for name, mesh in meshes.items():
        path = folder / "sources" / f"{name}.stl"
        path.write_bytes(stl_bytes(mesh))
        files.append(str(path))
    p = requirements
    print_state.api_load(folder, dict(files=files, printer=p["printer"]))
    print_state.api_orient(folder, dict(strategy=strategy or p["strategy"], shape=p["shape"]))
    print_state.api_arrange(folder, dict(mode="auto", gap=p["gap_mm"]))
    print_state.api_export(folder, dict(shape=p["shape"], process=p["process"], filament=p["filament"]))
    if check:
        print_state.api_check(folder, {})
    data = job.load_job(folder)
    return dict(
        job=str(folder),
        plates=data["export"]["plates"],
        arrange=data["arrange"],
        check=data.get("check"),
        strategy=strategy or p["strategy"],
        print_submitted=False,
    )


def run(w):
    p = w["params"]
    store = Manufacturing(p["root"])
    doc, stage = p["snapshot"], p["stage"]
    out = Path(w["output"])
    requirements = doc["requirements"]
    metadata = {}
    try:
        for source in doc["sources"]:
            if sha(source["path"]) != source["source_sha256"]:
                fail("源检查点指纹变化 / Source checkpoint hash changed")
        from studio.core.task_operations import deliver

        if stage == "inspect":
            meshes = load_meshes([x["path"] for x in doc["sources"]])
            bounds = np.vstack([m.vertices for m in meshes.values()])
            size = float(np.ptp(bounds, axis=0).max())
            ratio = requirements["target_max_mm"] / size if requirements["target_max_mm"] else requirements["scale"]
            if size <= 0 or not math.isfinite(ratio):
                fail("模型尺寸无效 / Invalid model dimensions")
            for mesh in meshes.values():
                mesh.apply_scale(ratio)
            report = {
                **diagnostic(meshes, requirements),
                "scale_applied": ratio,
                "input_units": "GLB metres; STL/OBJ/PLY millimetres",
            }
        elif stage == "coupon":
            from studio.core.kernels import mechanical_geometry as g

            candidates = clearance_candidates(requirements["clearance_mm"])
            meshes = {}
            for i, gap in enumerate(candidates):
                r, d = requirements["radius_mm"], requirements["depth_mm"]
                kind = requirements["profile"]
                width = 2 * (r + gap + requirements["min_wall_mm"] + 2)
                x = i * (width + 5)
                host = g.box(
                    [x - width / 2, -width / 2, -d - requirements["min_wall_mm"] - 2], [x + width / 2, width / 2, 0]
                )
                bore = g.keyed(r, -d, 0.01, gap) if kind == "keyed" else g.cyl(r + gap, -d, 0.01)
                pin = g.keyed(r, -d + 0.05, 2) if kind == "keyed" else g.cyl(r, -d + 0.05, 2)
                meshes[f"coupon_{i + 1}_socket"] = g.mesh(host - bore.translate([i * (width + 5), 0, 0]))
                meshes[f"coupon_{i + 1}_pin"] = g.mesh(pin.translate([i * (width + 5), width + 5, 0]))
            report = dict(
                operation="clearance_coupon",
                clearance_candidates_mm=candidates,
                printer=requirements["printer"],
                material=requirements["material"],
                physical_calibration="pending",
                closed_outputs=True,
            )
        else:
            geometry_doc = copy.deepcopy(doc)
            if stage in GEOMETRY:
                for previous_stage in GEOMETRY[GEOMETRY.index(stage) :]:
                    geometry_doc["stages"].pop(previous_stage, None)
            source = current_geometry(geometry_doc)
            meshes = checkpoint_meshes(source)
            metadata = copy.deepcopy(source["report"].get("part_metadata", {}))
            if stage == "local_repair":
                repaired = {}
                for name, mesh in meshes.items():
                    m = welded(mesh)
                    if m.is_volume and np.all(m.nondegenerate_faces()) and np.all(m.unique_faces()):
                        # An already valid colored/UV mesh needs no welding or
                        # face edits. Keep its visual seams and original data.
                        repaired[name] = mesh.copy()
                        continue
                    rgba = (
                        np.asarray(mesh.visual.to_color().vertex_colors)[mesh.faces].mean(axis=1)
                        if mesh.visual.kind == "texture"
                        else np.asarray(mesh.visual.face_colors)
                    )
                    m.visual.face_colors = rgba
                    m.update_faces(m.nondegenerate_faces())
                    m.update_faces(m.unique_faces())
                    m.remove_unreferenced_vertices()
                    trimesh.repair.fix_normals(m, multibody=True)
                    trimesh.repair.fill_holes(m)  # only bounded triangle/quad holes
                    repaired[name] = m
                meshes = repaired
                report = {
                    **diagnostic(meshes, requirements),
                    "operation": "bounded_local_repair",
                    "repair_api_used": False,
                    "repaired_texture_policy": "preserve_untouched_mesh; face_colors_on_changed_topology",
                }
            elif stage == "split":
                if not source["report"].get("closed_outputs"):
                    fail("模型有孔洞或拓扑问题；先修复并复检 / Repair and reinspect model before splitting")
                meshes, detail = split_meshes(meshes, geometry_doc, out)
                metadata = {}
                numbered = {}
                for i, (name, mesh) in enumerate(meshes.items()):
                    identity = f"P{i + 1:03d}"
                    rgba = np.asarray(mesh.visual.face_colors)
                    color = rgba[0, :3].tolist() if len(rgba) and np.all(rgba == rgba[0]) else None
                    metadata[identity] = dict(source_name=name, color_rgb=color, material=requirements["material"])
                    numbered[identity] = mesh
                meshes = numbered
                report = {**detail, **diagnostic(meshes, requirements)}
            elif stage == "connect":
                meshes, detail = connect_meshes(meshes, requirements, out)
                report = {**detail, **diagnostic(meshes, requirements)}
            elif stage == "audit":
                report = assembly_audit(meshes, doc)
            elif stage in ("prepare", "reprint", "compare"):
                if stage == "reprint":
                    meshes = {n: m for n, m in meshes.items() if n in p["part_ids"]}
                if stage == "compare":
                    report = dict(
                        operation="real_slice_comparison",
                        scenarios=[
                            plate_job(meshes, requirements, out, strategy=s, check=True) for s in ("flat", "support")
                        ],
                        estimated=False,
                        print_submitted=False,
                    )
                else:
                    report = plate_job(meshes, requirements, out)
                    if stage == "reprint":
                        report["selected_part_ids"] = p["part_ids"]
            elif stage == "deliver":
                report = dict(
                    operation="manufacturing_delivery",
                    physical_quality_verified=False,
                    assembly=doc["stages"]["audit"]["report"],
                    printer=requirements["printer"],
                    material=requirements["material"],
                    source_sha256=[s["source_sha256"] for s in doc["sources"]],
                    calibration=doc["calibration"],
                    repair_api=doc["repair_api"],
                    slice_comparison=doc["stages"].get("compare", {}).get("report")
                    if doc["stages"].get("compare", {}).get("status") == "completed"
                    else None,
                )
                with (out / "BOM.csv").open("w", newline="") as f:
                    writer = csv.writer(f)
                    writer.writerow(["part_id", "quantity", "material", "color_rgb", "source_name", "volume_mm3"])
                    material = requirements["material"]
                    if material[:1] in "=+-@":
                        material = "'" + material

                    def cell(value):
                        return "'" + value if isinstance(value, str) and value[:1] in "=+-@" else value

                    for name, mesh in meshes.items():
                        meta = metadata.get(name, {})
                        writer.writerow(
                            [
                                cell(name),
                                1,
                                material,
                                str(meta.get("color_rgb") or ""),
                                cell(meta.get("source_name", name)),
                                float(mesh.volume),
                            ]
                        )
                order = report["assembly"]["assembly_order"]
                (out / "ASSEMBLY.txt").write_text(
                    "装配顺序（离散采样验证）：\n"
                    + " → ".join(order)
                    + "\n按同名零件编号取件。定位销用于间隙/胶接配合，保持力未实测。\n先打印公差试片，再打印正式件。\n"
                    "薄壁与拔出路径仅采样检查；实物质量需要打印后复检。\n",
                    encoding="utf-8",
                )
                for plate in doc["stages"]["prepare"]["report"]["plates"]:
                    for key in ("geometry_3mf", "project_3mf"):
                        if plate.get(key):
                            shutil.copyfile(plate[key], out / f"plate_{plate['index']:02d}_{key}.3mf")

            else:
                fail("未知制造阶段 / Unknown stage")
        report["part_metadata"] = metadata
        report["parts"] = [
            dict(
                id=n,
                name=metadata.get(n, {}).get("source_name", n),
                color_rgb=metadata.get(n, {}).get("color_rgb"),
                material=requirements["material"],
                volume_mm3=float(m.volume),
                extents_mm=m.extents.tolist(),
            )
            for n, m in meshes.items()
        ]
        report.update(stage=stage, units="mm", print_submitted=False)
        deliver(meshes, out, report, stl=all(welded(m).is_volume for m in meshes.values()))
        dump(out / "report.json", report)
        if stage == "deliver":
            manifest = {f.name: sha(f) for f in out.iterdir() if f.is_file()}
            dump(out / "manifest.json", manifest)
            with zipfile.ZipFile(out / "manufacturing-package.zip", "w", zipfile.ZIP_DEFLATED) as archive:
                for f in out.iterdir():
                    if f.is_file() and f.suffix != ".zip":
                        archive.write(f, f.name)
        exact = {"names": np.asarray(list(meshes))}
        for i, mesh in enumerate(meshes.values()):
            exact[f"v{i}"] = np.asarray(mesh.vertices, np.float64)
            exact[f"f{i}"] = np.asarray(mesh.faces, np.int64)
        np.savez_compressed(out / "geometry-mm.npz", **exact)
        row = dict(
            status="completed",
            geometry=str(out / "geometry-mm.npz"),
            geometry_sha256=sha(out / "geometry-mm.npz"),
            report=report,
            scene=str(out / "scene.glb"),
            sha256=sha(out / "scene.glb"),
            output=str(out),
            finished=time.time(),
            token=p["token"],
            task_id=out.parent.name,
        )
        with store.locked(p["id"]) as (path, latest):
            if (latest.get("active") or {}).get("token") != p["token"]:
                fail("阶段已被恢复或替换，旧结果拒绝发布 / Obsolete stage claim")
            latest["stages"][stage] = row
            latest["active"] = None
            store.save(path, latest)
    except Exception as exc:
        with store.locked(p["id"]) as (path, latest):
            if (latest.get("active") or {}).get("token") == p["token"]:
                latest["stages"][stage].update(status="failed", error=str(exc), finished=time.time())
                latest["active"] = None
                store.save(path, latest)
        raise
