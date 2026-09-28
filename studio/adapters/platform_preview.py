"""Preview builder for the optional, key-gated Assembly Evaluation Dashboard
adapter (see `evaluation.py`). Reuses the Dashboard's own `viewer_model/v1`
contract and the existing offline assembly viewer rather than reimplementing
either, so a preview always matches what the Dashboard itself would render."""

from pathlib import Path, PurePosixPath
import json
import tempfile
import math

from studio.core.assembly_review import Bundle, finish_scene
from studio.adapters.evaluation import Client, fingerprint, identifier, SOURCE_COMMIT
from studio.core.kernels.scene_viewer.scene_contract import make_scene, make_joint, make_index
from studio.i18n import render

from studio.paths import APP_DIST_DIR


def script():
    return "from studio.adapters.platform_preview import run\nrun(workbench)\n"


def safe_asset(value):
    if not isinstance(value, str):
        raise ValueError(render("platform_preview.viewer_asset_path_not_string"))
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or ".." in path.parts
        or any(x in value for x in (":", "\\", "%", "?", "#"))
        or path.suffix.lower() != ".glb"
    ):
        raise ValueError(render("platform_preview.asset_path_scoped_glb_only"))
    return path.as_posix()


def model_scene(model, title):
    # Same viewer_model contract consumed by MDE adapters/urdf.py, but retain
    # visual-less kinematic frames instead of silently dropping their joints.
    if model.get("schema") != "assembly-dashboard-viewer-model/v1" or model.get("coordinateSystem") not in {
        "y-up",
        "z-up",
    }:
        raise ValueError(render("platform_preview.unsupported_model_or_no_coordinate_system"))
    links = model.get("links", [])
    if not 1 <= len(links) <= 512:
        raise ValueError(render("platform_preview.link_count_range"))
    parts = [
        {
            "name": link["name"],
            "id": link["name"],
            "visuals": link.get("visuals", []),
            **({"frameOnly": True} if not link.get("visuals") else {}),
        }
        for link in links
    ]
    for part in parts:
        for visual in part["visuals"]:
            safe_asset(visual.get("file"))
            for field in ("origin", "rpy", "scale"):
                value = visual.get(field)
                if value is not None and (
                    not isinstance(value, list)
                    or len(value) != 3
                    or not all(type(x) in (int, float) and math.isfinite(x) for x in value)
                ):
                    raise ValueError(render("platform_preview.invalid_visual_field", field=field))
    joints = []
    for j in model.get("joints", []):
        kind = j.get("motionType")
        if kind not in {"fixed", "revolute", "prismatic", "continuous"}:
            raise ValueError(render("platform_preview.unsupported_joint_type_no_silent_fixed"))
        joints.append(
            make_joint(
                j["name"],
                j["parent"],
                j["child"],
                motion_type=kind,
                axis=j.get("axis"),
                origin=j.get("origin"),
                rpy=j.get("rpy"),
                motion_range=j.get("motionRange") or j.get("poseRange"),
            )
        )
    return make_scene(
        title=title,
        parts=parts,
        joints=joints,
        root=model.get("root", ""),
        coordinate_system=model["coordinateSystem"],
        eyebrow=render("platform_preview.eyebrow_raw_result"),
        provenance={"source": "assembly-agent-profiling", "contract_commit": SOURCE_COMMIT},
    )


def run(w):
    p, out = w["params"], Path(w["output"])
    c, bundle = Client(p["connection"]), Bundle()
    selected = p["evidence"]
    if not 1 <= len(selected) <= 4:
        raise ValueError(render("platform_preview.case_run_count_range"))
    scenes, receipts = [], []
    with tempfile.TemporaryDirectory(prefix="workbench-platform-") as temp:
        for item in selected:
            rid = identifier(item["id"])
            current = c.read("case", item["id"])
            if fingerprint(current) != item["sha256"]:
                raise ValueError(render("platform_preview.case_run_changed_regenerate"))
            base = "/viewer/" + rid + "/derived/viewer/model/"
            model = c.request(base + "viewer_model.json")
            scene = model_scene(model, current.get("case_id") or item["id"])
            factors = current.get("factors") or {}
            label = " / ".join(str(factors[k]) for k in ("spec_level", "demo_version", "generator") if factors.get(k))
            scene["title"] = label or item["id"]
            for part in scene["parts"]:
                for visual in part["visuals"]:
                    name = safe_asset(visual["file"])
                    raw = c.request(base + name, binary=True, limit=max(0, 90 * 1024 * 1024 - bundle.total))
                    path = Path(temp) / f"{len(bundle.sources)}.glb"
                    path.write_bytes(raw)
                    visual["file"], _ = bundle.asset(path)
            if fingerprint(c.read("case", item["id"])) != item["sha256"]:
                raise ValueError(render("platform_preview.evidence_changed_during_fetch"))
            scene["provenance"].update(
                case_run_id=item["id"], review_artifact_sha256=item.get("artifact_sha256"), source_sha256=item["sha256"]
            )
            finish_scene(scene)
            scenes.append(scene)
            receipts.append(item)
    resources, entries = {}, []
    for i, scene in enumerate(scenes):
        if len(scenes) > 1:
            other = 1 if i == 0 else 0
            scene["compare"] = {
                "mode": "B",
                "label": scenes[other]["title"],
                "self": {"mode": "A", "label": render("platform_preview.label_current_version")},
                "sceneUrl": f"scenes/{other}.json",
            }
            finish_scene(scene)
        key = f"scenes/{i}.json"
        resources[key] = scene
        entries.append(
            {
                "id": selected[i]["id"],
                "title": scene["title"],
                "sceneUrl": key,
                "executionKey": selected[i]["id"],
                "contentSha256": scene["contentSha256"],
                "parts": len(scene["parts"]),
                "joints": sum(j["motionType"] != "fixed" for j in scene["joints"]),
            }
        )
    resources["api/index.json"] = make_index(render("platform_preview.index_title"), entries)
    resources["api/index.json"]["curationEnabled"] = False
    payload = json.dumps({"resources": resources, "assets": bundle.assets}, ensure_ascii=True, allow_nan=False).replace(
        "<", "\\u003c"
    )
    html = (APP_DIST_DIR / "assembly-review.html").read_text().replace("__ASSEMBLY_REVIEW_DATA__", payload)
    # The shared viewer reads curationEnabled; platform previews use the native
    # review panel. No injected CSS/DOM fork of the viewer is needed.
    (out / "index.html").write_text(html)
    (out / "report.json").write_text(
        json.dumps(
            {
                "source": p["connection"]["base_url"],
                "evidence": receipts,
                "asset_bytes": bundle.total,
                "limitations": [
                    render("platform_preview.limitation_rigid_joints_only"),
                    render("platform_preview.limitation_review_saved_upstream"),
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
