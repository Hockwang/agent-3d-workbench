"""Prepare immutable model evidence; render with the installed Blender process."""

from pathlib import Path
import json
import math
import shutil
import subprocess
import time

import numpy as np
import trimesh
from PIL import Image, ImageDraw

from print_prep.export3mf import topology_signature
from studio.core.observation import dependencies, digest, mesh_ref, options
from studio.core.tasks import blender_path
from studio.i18n import render


def metrics(scene):
    parts = []
    for node in sorted(scene.graph.nodes_geometry):
        matrix, name = scene.graph[node]
        mesh = scene.geometry[name]
        if not isinstance(mesh, trimesh.Trimesh) or not len(mesh.faces):
            continue
        if not np.isfinite(mesh.vertices).all() or not np.isfinite(matrix).all():
            raise ValueError(render("observation_run.non_finite_coordinates"))
        world = mesh.copy()
        world.apply_transform(matrix)
        signature = topology_signature(mesh)
        parts.append(
            {
                "name": str(node),
                **signature,
                "watertight": bool(mesh.is_watertight),
                "bounds_m": world.bounds.tolist(),
                "surface_area_m2": float(world.area),
                "volume_m3": abs(float(world.volume)) if world.is_volume else None,
            }
        )
    if not parts:
        raise ValueError(render("observation_run.no_observable_mesh"))
    return {
        "parts": parts,
        "part_count": len(parts),
        "faces": sum(p["faces"] for p in parts),
        "boundary_edges": sum(p["boundary_edges"] for p in parts),
        "nonmanifold_edges": sum(p["nonmanifold_edges"] for p in parts),
        "bounds_m": scene.bounds.tolist(),
        "extents_m": scene.extents.tolist(),
        "all_watertight": all(p["watertight"] for p in parts),
    }


def load_urdf(path):
    """Load a URDF's own meshes via yourdfpy and return `(robot, joints)`.

    `robot` is a live `yourdfpy.URDF` (its `.scene` / `.update_cfg(...)` reflect
    the current joint configuration); `joints` is the same validated
    name/type/parent/child/axis/range/mimic description this module renders
    into `observation.json`. Factored out so other modules (e.g.
    `task_operations.assembly_audit`'s URDF mode) can load and sweep a URDF's
    joints without duplicating this validation.
    """
    from yourdfpy import URDF

    class EvidenceURDF(URDF):
        def _geometry2trimeshscene(self, geometry, load_file, force_mesh, skip_materials):
            if geometry.mesh is None:
                return super()._geometry2trimeshscene(geometry, load_file, force_mesh, skip_materials)
            if not load_file:
                return None
            result = trimesh.load_scene(
                self._filename_handler(fname=geometry.mesh.filename), process=False, allow_remote=False
            )
            if geometry.mesh.scale is not None:
                result.apply_scale(geometry.mesh.scale)
            return result

    parsed = URDF.load(str(path), load_meshes=False, build_scene_graph=False)
    robot = EvidenceURDF(
        robot=parsed.robot,
        filename_handler=lambda fname: str(mesh_ref(path, fname)),
        load_meshes=True,
        load_collision_meshes=False,
        build_collision_scene_graph=False,
    )
    joints = []
    for joint in robot.robot.joints:
        if joint.type not in ("fixed", "revolute", "continuous", "prismatic"):
            raise ValueError(render("observation_run.unsupported_joint_type", type=joint.type, name=joint.name))
        limit = joint.limit
        bounds = (
            [-math.pi, math.pi]
            if joint.type == "continuous"
            else ([limit.lower, limit.upper] if limit and limit.lower is not None and limit.upper is not None else None)
        )
        if joint.type != "fixed" and bounds is None:
            raise ValueError(render("observation_run.actuated_joint_missing_range", name=joint.name))
        if bounds and (not all(math.isfinite(x) for x in bounds) or bounds[0] > bounds[1]):
            raise ValueError(render("observation_run.joint_range_invalid", name=joint.name))
        joints.append(
            {
                "name": joint.name,
                "type": joint.type,
                "parent": joint.parent,
                "child": joint.child,
                "axis": joint.axis.tolist() if joint.axis is not None else None,
                "range": bounds,
                "mimic": bool(joint.mimic),
            }
        )
    return robot, joints


def run(workbench):
    start = time.monotonic()
    out = Path(workbench["output"])
    p = options(workbench["params"])
    sources = p.get("sources", workbench["inputs"])
    labels = p.get("labels", [Path(x).stem for x in sources])
    if not 1 <= len(sources) <= 4 or len(labels) != len(sources):
        raise ValueError(render("observation_run.variant_count_mismatch"))
    refs = list(dict.fromkeys(r for path in sources for r in dependencies(path)))
    fingerprints = [{"path": str(r), "sha256": digest(r), "bytes": r.stat().st_size} for r in refs]
    variants, renders = [], []
    (out / "models").mkdir()
    (out / "views").mkdir()
    for index, filename in enumerate(sources):
        path = Path(filename)
        suffix = path.suffix.lower()
        robot = None
        joints = []
        if suffix == ".urdf":
            robot, joints = load_urdf(path)
            scene = robot.scene.copy()
        else:
            scene = trimesh.load_scene(path, process=False, allow_remote=False)
        if suffix in (".stl", ".ply"):
            scene.apply_scale(0.001)
        if suffix in (".stl", ".ply") or (robot and p["urdf_up"] == "z"):
            scene.apply_transform(trimesh.transformations.rotation_matrix(-math.pi / 2, [1, 0, 0]))
        info = metrics(scene)
        variant = {
            "index": index,
            "label": labels[index],
            "source": str(path),
            "source_sha256": digest(path),
            "metrics": info,
            "joints": joints,
            "dof": len(robot.actuated_joints) if robot else None,
            "metrics_pose": render("observation_run.metrics_pose_urdf_zero")
            if robot
            else render("observation_run.metrics_pose_bind"),
            "provenance": (p.get("provenance") or [{} for _ in sources])[index],
            "models": [],
        }
        for phase_index, phase in enumerate(p["phases"]):
            target = f"models/v{index:02d}-p{phase_index:02d}.glb"
            if robot:
                cfg = {
                    j["name"]: j["range"][0] + (j["range"][1] - j["range"][0]) * phase
                    for j in joints
                    if j["range"] and not j["mimic"]
                }
                robot.update_cfg(cfg)
                posed = robot.scene.copy()
                if p["urdf_up"] == "z":
                    posed.apply_transform(trimesh.transformations.rotation_matrix(-math.pi / 2, [1, 0, 0]))
                (out / target).write_bytes(posed.export(file_type="glb"))
            elif suffix == ".glb":
                shutil.copyfile(path, out / target)  # retain animations, skins, textures
            else:
                (out / target).write_bytes(scene.export(file_type="glb"))
            variant["models"].append({"phase": phase, "file": target.replace("models/", "snapshots/")})
            renders.append(
                {
                    "variant": index,
                    "phase_index": phase_index,
                    "phase": phase,
                    "model": target,
                    "animated": suffix == ".glb",
                    "views": p["views"],
                }
            )
        variants.append(variant)
    exe = blender_path()
    if not exe:
        raise ValueError(render("observation_run.blender_required"))
    request = {"renders": renders, "resolution": p["resolution"], "output": str(out)}
    config = out.parent / "observation-render.json"
    config.write_text(json.dumps(request))
    result = subprocess.run(
        [
            exe,
            "--background",
            "--factory-startup",
            "--python",
            str(Path(__file__).with_name("observation_render.py")),
            "--",
            str(config),
        ],
        check=False,
    )
    if result.returncode or not (out / "camera.json").exists():
        raise RuntimeError(render("observation_run.render_failed"))
    for variant in variants:
        for model in variant["models"]:
            if not (out / model["file"]).is_file():
                raise RuntimeError(render("observation_run.snapshot_incomplete"))
    shutil.rmtree(out / "models")  # task-owned temporary render inputs, never source files
    for ref in fingerprints:
        if digest(ref["path"]) != ref["sha256"]:
            raise ValueError(render("observation_run.input_changed"))
    columns = [(phase, view) for phase in p["phases"] for view in p["views"]]
    # One compact visual receipt for the agent; full-resolution cells stay available.
    tile = min(384, p["resolution"])
    cell_h = tile + 27
    sheet = Image.new("RGB", (tile * len(columns), cell_h * len(variants)), "#10151d")
    draw = ImageDraw.Draw(sheet)
    images = []
    for item in renders:
        for view_index, view in enumerate(item["views"]):
            file = f"views/v{item['variant']:02d}-p{item['phase_index']:02d}-{view}.png"
            column = item["phase_index"] * len(p["views"]) + view_index
            x, y = tile * column, cell_h * item["variant"]
            with Image.open(out / file) as image:
                image.load()
                sheet.paste(image.convert("RGB").resize((tile, tile)), (x, y + 27))
            draw.text((x + 8, y + 7), f"V{item['variant'] + 1} | {view} | phase {item['phase']:g}", fill="#b9d8dc")
            images.append({"variant": item["variant"], "phase": item["phase"], "view": view, "file": file})
    sheet.thumbnail((3072, 2048))
    sheet.save(out / "contact-sheet.png")
    report = {
        "schema": "workbench-observation/v1",
        "variants": variants,
        "images": images,
        "inputs": fingerprints,
        "camera": json.loads((out / "camera.json").read_text()),
        "views": p["views"],
        "phases": p["phases"],
        "contact_sheet": "contact-sheet.png",
        "observation_seconds": time.monotonic() - start,
        "limitations": [
            render("observation_run.limitation_no_auto_registration"),
            render("observation_run.limitation_geometry_not_semantic"),
            render("observation_run.limitation_urdf_phase_sampling"),
            render("observation_run.limitation_unit_convention"),
        ],
        "verdict": "unreviewed",
    }
    (out / "observation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))
