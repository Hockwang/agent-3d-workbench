"""Bounded, offline reuse of MDE's merge/A8 scene viewer in task results.

The source catalog is read only. Geometry stays in the declared coordinate frame;
an editor GLB is emitted only for static merge datasets, never for A8 joints.
"""

from pathlib import Path, PurePosixPath
import base64
import hashlib
import io
import json
import mimetypes

from studio.core.kernels.scene_viewer.adapters import a8_catalog, merge_ui
from studio.core.kernels.scene_viewer.scene_contract import make_index, validate_scene

from studio.paths import APP_DIST_DIR

LIMIT = 90 * 1024 * 1024
CATALOG = [
    {
        "id": "merge-review",
        "title": "assembly_review.merge_review_title",
        "engine": "python",
        "description": "assembly_review.merge_review_description",
        "params": {"title": "拆件审阅", "units": "m"},
        "labels": {
            "title": "assembly_review.merge_review_label_title",
            "units": "assembly_review.merge_review_label_units",
        },
        "choices": {
            "units": {
                "m": "assembly_review.merge_review_choice_units_m",
                "mm": "assembly_review.merge_review_choice_units_mm",
            }
        },
    },
    {
        "id": "a8-review",
        "title": "assembly_review.a8_review_title",
        "engine": "python",
        "description": "assembly_review.a8_review_description",
        "params": {"case_ids": "", "parts_dir": "", "batch_id": "", "compare_case_id": ""},
        "labels": {
            "case_ids": "assembly_review.a8_review_label_case_ids",
            "parts_dir": "assembly_review.a8_review_label_parts_dir",
            "batch_id": "assembly_review.a8_review_label_batch_id",
            "compare_case_id": "assembly_review.a8_review_label_compare_case_id",
        },
        "optional_params": ["case_ids", "parts_dir", "batch_id", "compare_case_id"],
    },
]


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def read_json(path):
    if path.stat().st_size > 8 * 1024 * 1024:
        raise ValueError("Catalog exceeds 8 MB")
    return json.loads(path.read_text())


def relative_file(root, value):
    # Declared local symlinks are legitimate MDE inputs; URL/absolute/traversal
    # references are not. Never fetch remote geometry from a catalog.
    name = PurePosixPath(str(value))
    if not str(value) or name.is_absolute() or ".." in name.parts or ":" in str(value) or "\\" in str(value):
        raise ValueError(f"Expected a relative local asset: {value}")
    result = root / str(name)
    if not result.is_file():
        raise ValueError(f"Missing asset: {result}")
    return result


class Bundle:
    def __init__(self):
        self.assets = {}
        self.sources = []
        self.total = 0

    def asset(self, path):
        from studio.core.task_operations import glb_data

        size = path.stat().st_size
        if size > LIMIT or self.total + size > LIMIT:
            raise ValueError("Selected assets exceed 90 MB; select fewer cases")
        if path.suffix.lower() == ".glb":
            raw, doc, _ = glb_data(path)
            if doc.get("animations") or doc.get("skins"):
                raise ValueError("Articulated review needs rigid link GLBs, not skin/clip animation")
        elif path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
            raw = path.read_bytes()
        else:
            raise ValueError("Use self-contained GLB geometry or PNG/JPEG/WebP references")
        sha = digest(raw)
        key = "assets/" + sha + path.suffix.lower()
        if key not in self.assets:
            self.total += len(raw)
            self.assets[key] = {
                "data": base64.b64encode(raw).decode(),
                "mime": mimetypes.guess_type(path.name)[0] or "application/octet-stream",
            }
        self.sources.append({"path": str(path), "bytes": len(raw), "sha256": sha, "asset": key})
        return key, raw


def validate_graph(scene):
    validate_scene(scene)
    parents, names = {}, set()
    for joint in scene["joints"]:
        if not joint["name"] or joint["name"] in names:
            raise ValueError("Joint names must be nonempty and unique")
        names.add(joint["name"])
        parents[joint["child"]] = joint["parent"]
        import math

        for field in ["axis", "origin", "rpy", "motionRange", "poseRange"]:
            value = joint.get(field)
            if value is not None and (
                len(value) != (2 if field.endswith("Range") else 3)
                or not all(isinstance(x, (int, float)) and math.isfinite(x) for x in value)
            ):
                raise ValueError(f"Invalid joint {field}")
        if joint["motionType"] != "fixed" and not any(joint.get("axis", [])):
            raise ValueError("Movable joint axis must be nonzero")
    for child in parents:
        seen, current = set(), child
        while current in parents:
            if current in seen:
                raise ValueError("Cyclic joint graph")
            seen.add(current)
            current = parents[current]
    if scene["root"] in parents:
        raise ValueError("Root must not have a parent joint")


def finish_scene(scene):
    validate_graph(scene)
    # Bind the complete transform/coordinate/asset contract, not only filenames.
    scene.pop("contentSha256", None)
    scene["contentSha256"] = digest(json.dumps(scene, sort_keys=True, ensure_ascii=True, allow_nan=False).encode())
    return scene


def merge_scene(path, bundle, title, units, export=False):
    if path.name != "manifest.json":
        raise ValueError("Use the original merge_ui manifest.json path, with its sibling GLBs")
    read_json(path)
    scene = merge_ui.from_dataset(path.parent, base_url="local", title=title)
    if len(scene["parts"]) > 512:
        raise ValueError("Select a dataset with at most 512 parts")
    import trimesh

    combined = trimesh.Scene()
    for part in scene["parts"]:
        visual = part["visuals"][0]
        file = relative_file(path.parent, visual["file"].removeprefix("local/"))
        visual["file"], raw = bundle.asset(file)
        if units == "mm":
            visual["scale"] = [0.001, 0.001, 0.001]
        if export:
            source = trimesh.load(io.BytesIO(raw), file_type="glb", force="scene", process=False)
            # Preserve node transforms, UVs and materials. Do not concatenate
            # dissimilar materials into a single untextured mesh.
            for n, node in enumerate(source.graph.nodes_geometry):
                transform, key = source.graph[node]
                mesh = source.geometry[key].copy()
                mesh.apply_transform(transform)
                if units == "mm":
                    mesh.apply_scale(0.001)
                name = part["name"] if len(source.graph.nodes_geometry) == 1 else f"{part['name']}__{n}"
                combined.add_geometry(mesh, node_name=name, geom_name=name)
    for ref in scene["refs"]:
        ref["url"], _ = bundle.asset(relative_file(path.parent, ref["url"].removeprefix("local/")))
    scene["provenance"]["units"] = units
    return finish_scene(scene), combined


def a8_scenes(path, params, bundle):
    batch = str(params.get("batch_id") or "")
    if path.name == "catalog_registry.json":
        payload = read_json(path)
        batches = a8_catalog.load_registry(path)
        batch = batch or payload.get("defaultBatchId")
        if batch not in batches:
            raise ValueError("Select an available batch_id: " + ", ".join(batches))
        spec = batches[batch]
        data, parts = spec["dataDir"], spec["partsDir"]
    else:
        if path.name not in {"cases.json", "cases.js"}:
            raise ValueError("Use cases.json, cases.js or catalog_registry.json")
        data = path.parent
        parts = Path(str(params.get("parts_dir") or "")).expanduser()
        if not parts.is_absolute() or not parts.is_dir():
            raise ValueError("parts_dir must be an existing absolute directory")
        batch = batch or data.parent.name
    source = data / ("cases.json" if (data / "cases.json").is_file() else "cases.js")
    if source.stat().st_size > 8 * 1024 * 1024:
        raise ValueError("Catalog exceeds 8 MB")
    cases = a8_catalog.load_cases(data, parts)
    requested = params.get("case_ids") or ""
    ids = [x.strip() for x in requested.split(",") if x.strip()] if isinstance(requested, str) else list(requested)
    if len(ids) != len(set(ids)):
        raise ValueError("Repeated case ID")
    by_id = {c["id"]: c for c in cases}
    missing = set(ids) - by_id.keys()
    if missing:
        raise ValueError("Unavailable case IDs: " + ", ".join(sorted(missing)))
    chosen = [by_id[x] for x in ids] if ids else cases[:8]
    if len(chosen) > 8:
        raise ValueError("Select at most 8 cases")
    scenes = []
    for case in chosen:
        if not case["id"] or PurePosixPath(case["id"]).name != case["id"] or case["id"] in {".", ".."}:
            raise ValueError("Invalid case ID")
        if len(case["links"]) > 512:
            raise ValueError("Case exceeds 512 links")
        if any(
            j.get("motionType", "fixed") not in {"fixed", "revolute", "continuous", "prismatic"} for j in case["joints"]
        ):
            raise ValueError("Unsupported motionType; refusing to silently freeze the joint")
        scene = a8_catalog.build_scene(case, base_url="local", batch_label=batch)
        for part, link in zip(scene["parts"], case["links"], strict=True):
            key, raw = bundle.asset(relative_file(case["partsDir"], link["file"]))
            if link.get("sha256") and link["sha256"] != digest(raw):
                raise ValueError(f"Asset SHA256 mismatch: {link['file']}")
            part["visuals"][0]["file"] = key
        for ref in scene["refs"]:
            ref["url"], _ = bundle.asset(relative_file(data, case["reference"]))
        scenes.append((case["id"], finish_scene(scene)))
    return scenes, batch, len(cases)


def run(template, w):
    paths = [Path(x) for x in w["inputs"]]
    if not paths:
        raise ValueError("Supply the original catalog/manifest path; uploading JSON alone loses its sibling assets")
    p, out, bundle = w["params"], Path(w["output"]), Bundle()
    resources, entries = {}, []
    if template == "merge-review":
        if len(paths) > 2:
            raise ValueError("Use one manifest, or two for comparison")
        units = p.get("units", "m")
        if units not in {"m", "mm"}:
            raise ValueError("units must be m or mm")
        main, editable = merge_scene(paths[0], bundle, p.get("title", "拆件审阅"), units, export=True)
        if len(paths) == 2:
            compare, _ = merge_scene(paths[1], bundle, paths[1].parent.name, units)
            resources["compare.json"] = compare
            main["compare"] = {
                "mode": "compare",
                "label": compare["title"],
                "sceneUrl": "compare.json",
                "contentSha256": compare["contentSha256"],
                "self": {"mode": "merge", "label": main["title"]},
            }
            finish_scene(main)
        (out / "parts.glb").write_bytes(editable.export(file_type="glb"))
        scenes, batch, available = [("merge", main)], paths[0].parent.name, 1
    elif template == "a8-review":
        if len(paths) != 1:
            raise ValueError("Use a single A8 catalog")
        scenes, batch, available = a8_scenes(paths[0], p, bundle)
    else:
        raise ValueError("Unknown assembly review template")
    compare_id = p.get("compare_case_id")
    if compare_id:
        comparison = next(((i, s) for i, (cid, s) in enumerate(scenes) if cid == compare_id), None)
        if comparison is None:
            raise ValueError("compare_case_id must be in the selected cases")
        ci, cs = comparison
        for cid, scene in scenes:
            if cid != compare_id:
                scene["compare"] = {
                    "mode": "compare",
                    "label": cs["title"],
                    "sceneUrl": f"scenes/{ci}.json",
                    "contentSha256": cs["contentSha256"],
                }
                finish_scene(scene)
    for i, (case_id, scene) in enumerate(scenes):
        key = f"scenes/{i}.json"
        resources[key] = scene
        entries.append(
            {
                "id": case_id,
                "title": scene["title"],
                "sceneUrl": key,
                "executionKey": f"{batch}::{case_id}",
                "batchId": batch,
                "eyebrow": scene["eyebrow"],
                "parts": len(scene["parts"]),
                "joints": sum(j["motionType"] != "fixed" and not j.get("fixed") for j in scene["joints"]),
                "contentSha256": scene["contentSha256"],
            }
        )
    index = make_index(p.get("title") or "A8 机构审阅", entries)
    index.update({"batchId": batch, "catalog": {"id": batch, "kind": template, "writable": False}})
    resources["api/index.json"] = index
    payload = {"resources": resources, "assets": bundle.assets}
    encoded = json.dumps(payload, ensure_ascii=True, allow_nan=False).replace("<", "\\u003c")
    html = (APP_DIST_DIR / "assembly-review.html").read_text()
    (out / "index.html").write_text(html.replace("__ASSEMBLY_REVIEW_DATA__", encoded))
    (out / "scenes.json").write_text(json.dumps(resources, ensure_ascii=False, indent=2))
    (out / "report.json").write_text(
        json.dumps(
            {
                "template": template,
                "offline": True,
                "source_modified": False,
                "available_cases": available,
                "selected_cases": [x["id"] for x in entries],
                "asset_bytes": bundle.total,
                "assets": bundle.sources,
                "curation": "Session only; export JSON to save. Source registry is never modified.",
                "editing": "parts.glb imports static geometry only; A8 joints remain in the review, not the mesh editor.",
            },
            ensure_ascii=False,
            indent=2,
        )
    )
