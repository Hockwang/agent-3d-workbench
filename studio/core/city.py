"""Frozen city packages and scoped, materialized instances in the mesh workspace."""

from __future__ import annotations

import copy
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

import numpy as np
import trimesh

from studio.i18n import render

SCHEMA = "studio-city/v1"
MAX_PACKAGE = 2 * 1024**3
from studio.paths import PLUGIN_ROOT

ROOT = PLUGIN_ROOT


def trust_directory():
    # Server session/log homes are per task; source-build trust is per machine.
    # Worktree branches share receipts but still require their own package root.
    from studio import print_prep_home

    return Path(os.environ.get("PRINT_PREP_WORKSPACES_HOME") or print_prep_home()) / "city-trust"


def fail(code, **params):
    from studio.core.editor import EditorError

    raise EditorError.coded(code, **params)


def safe_name(name):
    p = PurePosixPath(name)
    if not name or p.is_absolute() or ".." in p.parts or "\\" in name or ":" in name:
        fail("city.invalid_package_path")
    return p.as_posix()


def package_path(workspace, digest):
    if not isinstance(digest, str) or not re.fullmatch("[a-f0-9]{64}", digest):
        fail("city.invalid_package_digest")
    return workspace.root / "cities" / f"{digest}.zip"


def roots(objects):
    return [o for o in objects if o.get("city")]


def validate(workspace, objects):
    items = roots(objects)
    if len(items) > 1:
        fail("city.only_one_city_per_project")
    for obj in items:
        c = obj["city"]
        if c.get("schema") != SCHEMA:
            fail("city.invalid_schema")
        path = package_path(workspace, c.get("package"))
        if not path.is_file():
            fail("city.missing_source_package")
        if not np.allclose(obj["transform"], np.eye(4)):
            fail("city.root_transform_not_allowed")
    instances = set()
    for obj in objects:
        link = obj.get("city_link")
        if link:
            if link.get("instance") in instances:
                fail("city.instance_has_two_edit_branches")
            instances.add(link.get("instance"))
            if not items or link.get("root") != items[0]["id"] or not obj.get("scene"):
                fail("city.instance_source_project_missing")
            row = next((r for r in catalog(workspace, items[0]) if r["id"] == link.get("instance")), None)
            if (
                not row
                or link.get("kind") != row["kind"]
                or link.get("base_matrix") != row["matrix"]
                or link.get("bones", {}) != row.get("bones", {})
                or link.get("source_clip") != row.get("source_clip")
            ):
                fail("city.instance_binding_mismatch")


def resource(workspace, digest, name):
    if not any(o["city"]["package"] == digest for o in roots(workspace.doc["objects"])):
        fail("city.package_not_in_project")
    name = safe_name(name)
    path = package_path(workspace, digest)
    with zipfile.ZipFile(path) as z:
        manifest = package_manifest(z, digest)
        if name == "package.json":
            return z.read(name)
        entry = manifest["files"].get(name)
        if not entry or entry["bytes"] > 500 * 1024**2:
            fail("city.resource_missing_or_too_large")
        raw = z.read(name)
        if hashlib.sha256(raw).hexdigest() != entry["sha256"]:
            fail("city.resource_checksum_mismatch")
        if name == "runtime.js":
            receipt = trust_directory() / f"{digest}.json"
            if not receipt.is_file() or json.loads(receipt.read_text()).get("runtime_sha256") != entry["sha256"]:
                fail("city.runtime_not_built_locally")
        return raw


def package_manifest(z, digest):
    if z.getinfo("package.json").file_size > 8 * 1024**2:
        fail("city.manifest_too_large")
    raw = z.read("package.json")
    if hashlib.sha256(raw).hexdigest() != digest:
        fail("city.manifest_hash_mismatch")
    manifest = json.loads(raw)
    if manifest.get("schema") != SCHEMA or not isinstance(manifest.get("files"), dict):
        fail("city.invalid_package_manifest")
    for name, entry in manifest["files"].items():
        safe_name(name)
        if (
            not isinstance(entry, dict)
            or type(entry.get("bytes")) is not int
            or not 0 <= entry["bytes"] <= 500 * 1024**2
            or not re.fullmatch("[a-f0-9]{64}", str(entry.get("sha256", "")))
        ):
            fail("city.invalid_manifest_entry")
    return manifest


def _unpack_source(path, output):
    # Only code/assets and the pure JS/WASM Rapier dependency are read. No
    # executable from the attached node_modules or package scripts is run.
    prefixes = ("lib/", "public/", "node_modules/@dimforge/rapier3d-compat/")
    total = 0
    with zipfile.ZipFile(path) as z:
        seen = set()
        for i in z.infolist():
            name = safe_name(i.filename)
            if name.startswith("__MACOSX/"):
                continue
            if not name.startswith(prefixes):
                name = name.partition("/")[2]
            if i.is_dir() or not name.startswith(prefixes):
                continue
            if name in seen or (i.external_attr >> 16) & 0o170000 == 0o120000:
                fail("city.duplicate_or_symlink_entry")
            seen.add(name)
            total += i.file_size
            if total > MAX_PACKAGE or i.file_size > 500 * 1024**2:
                fail("city.package_too_large")
            target = output / name
            target.parent.mkdir(parents=True, exist_ok=True)
            with z.open(i) as src, target.open("wb") as dst:
                shutil.copyfileobj(src, dst)


def prepare(workspace, value):
    path = Path(value).expanduser()
    if not path.is_absolute() or not path.is_file() or path.suffix.lower() != ".zip":
        fail("city.invalid_local_zip_path")
    if path.stat().st_size > MAX_PACKAGE:
        fail("city.zip_too_large")
    directory = workspace.root / "cities"
    directory.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="city-build-", dir=directory) as temp:
        temp = Path(temp)
        source = temp / "source"
        source.mkdir()
        _unpack_source(path, source)
        if not (source / "lib/sim/engine.ts").is_file():
            fail("city.missing_cubely_source")
        runtime = temp / "runtime.js"
        result = subprocess.run(
            ["node", str(ROOT / "scripts/build_city_runtime.mjs"), str(source), str(runtime)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=180,
        )
        if result.returncode:
            fail("city.runtime_build_failed", stderr=result.stderr[-2500:])
        # Basic locomotion is bundled in the source. Online expressive-motion
        # generation is deliberately disabled for the local Studio preview.
        config = source / "public/npc-motion-config.json"
        config.write_text(json.dumps({"enabled": False, "clips": []}))
        files = {"runtime.js": runtime}
        for f in sorted((source / "public").rglob("*")):
            if f.is_file():
                files["public/" + f.relative_to(source / "public").as_posix()] = f
        if "public/models/pedestrians/manifest.json" not in files:
            fail("city.missing_pedestrian_manifest")
        manifest = {"schema": SCHEMA, "adapter": "cubely-20260920/v1", "files": {}}
        for name, f in files.items():
            raw = f.read_bytes()
            manifest["files"][name] = {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
        # Source identity is frozen even though only runtime assets are shipped.
        h = hashlib.sha256()
        for f in sorted((source / "lib").rglob("*")):
            if f.is_file():
                h.update(f.relative_to(source).as_posix().encode())
                h.update(f.read_bytes())
        manifest["source_sha256"] = h.hexdigest()
        raw = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
        digest = hashlib.sha256(raw).hexdigest()
        target = package_path(workspace, digest)
        if not target.exists():
            staged = temp / "package.zip"
            with zipfile.ZipFile(staged, "w", zipfile.ZIP_STORED) as z:
                z.writestr("package.json", raw)
                for name, f in files.items():
                    z.write(f, name)
            staged.replace(target)
        trust = trust_directory()
        trust.mkdir(parents=True, exist_ok=True)
        (trust / f"{digest}.json").write_text(json.dumps({"runtime_sha256": manifest["files"]["runtime.js"]["sha256"]}))
        return digest, manifest


def catalog_path(workspace, root):
    return workspace.root / "cities" / f"{root['city']['package']}.catalog.json"


def catalog(workspace, root):
    path = catalog_path(workspace, root)
    if not path.exists():
        return []
    if path.stat().st_size > 16 * 1024**2:
        fail("city.catalog_too_large")
    rows = json.loads(path.read_text())
    validate_catalog(workspace, root, rows)
    return rows


def validate_catalog(workspace, root, rows):
    if not isinstance(rows, list) or len(rows) > 10000:
        fail("city.invalid_catalog")
    ids = set()
    with zipfile.ZipFile(package_path(workspace, root["city"]["package"])) as z:
        files = package_manifest(z, root["city"]["package"])["files"]
    for row in rows:
        if (
            row.get("kind") not in ("person", "facility")
            or not re.fullmatch("[a-zA-Z0-9_-]{1,160}", row.get("id", ""))
            or row["id"] in ids
        ):
            fail("city.invalid_instance_id")
        ids.add(row["id"])
        if not isinstance(row.get("name"), str) or len(row["name"]) > 160:
            fail("city.invalid_instance_name")
        matrix = np.asarray(row.get("matrix"), dtype=float)
        if matrix.shape != (4, 4) or not np.isfinite(matrix).all() or not np.allclose(matrix[3], [0, 0, 0, 1]):
            fail("city.invalid_instance_transform")
        if not str(row.get("url", "")).startswith("/models/"):
            fail("city.invalid_instance_url")
        if "public/" + safe_name(row["url"].lstrip("/")) not in files:
            fail("city.instance_references_missing_model")
    for row in rows:
        if not isinstance(row.get("source_clip"), str) or len(row["source_clip"]) > 200:
            fail("city.invalid_clip_binding")
        bones = row.get("bones", {})
        if not isinstance(bones, dict) or len(bones) > 1000 or any(not isinstance(v, str) for v in bones.values()):
            fail("city.invalid_bone_binding")


def apply(workspace, doc, action, p):
    from studio.core.editor import _atomic, GLTF_TO_WORKSPACE, WORKSPACE_TO_GLTF
    from studio.core import scene_assets

    if action == "city_import":
        if roots(doc["objects"]):
            fail("city.project_already_has_city")
        digest, manifest = prepare(workspace, p.get("path", ""))
        obj = workspace._object(trimesh.creation.box([1, 1, 1]), "Cubely 城市")
        obj["city"] = {"schema": SCHEMA, "package": digest, "source_sha256": manifest["source_sha256"]}
        doc["objects"].append(obj)
        doc["selection"] = [obj["id"]]
        return {"summary": render("city.import_summary"), "created": [obj["id"]]}
    items = roots(doc["objects"])
    if len(items) != 1:
        fail("city.requires_city_import")
    root = items[0]
    if action == "city_catalog":
        rows = catalog(workspace, root)
        q = str(p.get("query", "")).lower()
        rows = [r for r in rows if not q or q in (r["id"] + " " + r["name"] + " " + r["kind"]).lower()]
        start = max(0, int(p.get("offset", 0)))
        limit = min(100, max(1, int(p.get("limit", 30))))
        return {
            "summary": render("city.catalog_summary"),
            "total": len(rows),
            "items": rows[start : start + limit],
            "root_id": root["id"],
        }
    if action == "city_register":
        rows = p.get("instances")
        if not isinstance(rows, list) or not 1 <= len(rows) <= 10000:
            fail("city.instances_empty_or_too_large")
        validate_catalog(workspace, root, rows)
        path = catalog_path(workspace, root)
        if path.exists():
            if json.loads(path.read_text()) != rows:
                fail("city.catalog_frozen_mismatch")
        else:
            _atomic(path, json.dumps(rows, ensure_ascii=False, allow_nan=False).encode())
        return {"summary": render("city.register_summary", count=len(rows)), "count": len(rows)}
    if action == "city_checkout":
        key = p.get("instance_id")
        existing = next((o for o in doc["objects"] if o.get("city_link", {}).get("instance") == key), None)
        if existing:
            doc["selection"] = [existing["id"]]
            return {"summary": render("city.checkout_existing_summary"), "created": [existing["id"]]}
        row = next((r for r in catalog(workspace, root) if r["id"] == key), None)
        if not row:
            fail("city.instance_not_found")
        raw = resource(workspace, root["city"]["package"], "public/" + safe_name(row["url"].lstrip("/")))
        obj = scene_assets.create(workspace, raw, row["name"])
        to_studio = GLTF_TO_WORKSPACE.copy()
        to_studio[:3, :3] *= 1000
        to_gltf = WORKSPACE_TO_GLTF.copy()
        to_gltf[:3, :3] *= 0.001
        obj["transform"] = (to_studio @ np.asarray(row["matrix"]) @ to_gltf).tolist()
        obj["city_link"] = {
            "root": root["id"],
            "instance": key,
            "kind": row["kind"],
            "source_asset": obj["scene"]["asset"],
            "base_matrix": row["matrix"],
            "bones": row.get("bones", {}),
            "source_clip": row.get("source_clip"),
            "clip_duration": next(
                (c["duration"] for c in obj.get("motion", {}).get("clips", []) if c["name"] == row.get("source_clip")),
                0,
            ),
        }
        doc["objects"].append(obj)
        doc["selection"] = [obj["id"]]
        return {"summary": render("city.checkout_summary"), "created": [obj["id"]]}
    fail("city.unknown_action")


def guard(objects, selected, action):
    if any(o.get("city") for o in selected) and action not in ("select", "rename", "save", "inspect"):
        fail("city.root_managed_by_runtime")
    if any(o.get("city_link") for o in selected) and action in ("duplicate", "delete", "motion_set", "motion_clear"):
        fail("city.instance_action_unsupported")


def check_replacement(old, new, raw):
    link = old.get("city_link")
    if not link:
        return
    from studio.core.scene_assets import inspect

    doc, info = inspect(raw)
    names = {doc["nodes"][i].get("name") for skin in doc.get("skins", []) for i in skin["joints"]}
    if link["kind"] == "person":
        if not new.get("motion") or not set(link["bones"]).issubset(names):
            fail("city.replacement_missing_bones")
    if link.get("source_clip") not in {c["name"] for c in info["clips"]}:
        fail("city.replacement_missing_clip")
    duration = next(c["duration"] for c in info["clips"] if c["name"] == link["source_clip"])
    if duration + 1e-4 < link.get("clip_duration", 0):
        fail("city.replacement_clip_too_short")
    new["city_link"] = copy.deepcopy(link)


def copy_packages(objects, source_root, target_root):
    for obj in roots(objects):
        digest = obj["city"]["package"]
        safe_name(digest)
        if not re.fullmatch("[a-f0-9]{64}", digest):
            fail("city.invalid_package_digest")
        (target_root / "cities").mkdir(exist_ok=True)
        for suffix in (".zip", ".catalog.json"):
            src = source_root / "cities" / f"{digest}{suffix}"
            if src.is_file() and not (target_root / "cities" / src.name).exists():
                shutil.copyfile(src, target_root / "cities" / src.name)


def archive(workspace, objects, z, read=False):
    for obj in roots(objects):
        digest = obj["city"]["package"]
        target = package_path(workspace, digest)
        for suffix in (".zip", ".catalog.json"):
            path = target.with_name(digest + suffix)
            name = "cities/" + path.name
            if read:
                if name not in z.namelist():
                    if suffix == ".zip":
                        fail("city.archive_missing_package")
                    continue
                path.parent.mkdir(exist_ok=True)
                from studio.core.editor import _atomic

                raw = z.read(name)
                if suffix == ".zip":
                    with zipfile.ZipFile(io.BytesIO(raw)) as package:
                        infos = package.infolist()
                        if (
                            len({i.filename for i in infos}) != len(infos)
                            or sum(i.file_size for i in infos) > MAX_PACKAGE
                        ):
                            fail("city.archive_package_too_large_or_duplicate")
                        m = package_manifest(package, digest)
                        for entry, meta in m["files"].items():
                            if (
                                package.getinfo(entry).file_size != meta["bytes"]
                                or hashlib.sha256(package.read(entry)).hexdigest() != meta["sha256"]
                            ):
                                fail("city.archive_resource_checksum_mismatch")
                else:
                    if len(raw) > 16 * 1024**2:
                        fail("city.catalog_too_large")
                    validate_catalog(workspace, obj, json.loads(raw))
                    if path.exists() and json.loads(path.read_text()) != json.loads(raw):
                        fail("city.archive_catalog_mismatch")
                _atomic(path, raw)
            elif path.exists():
                z.write(path, name)
    if read:
        validate(workspace, objects)
