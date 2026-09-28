"""Independent readback and staged assembly checks for a head-shell output,
plus the geometric core those checks share with the standalone
`removal-audit` task template.

`audit(folder, output)` reads a `shell-kit` task's delivered STLs and
`report.json` straight back off disk (no shared state with
`studio.core.head_shell`) and samples a discrete removal/assembly order per
half-shell. Called by `studio.core.head_shell` at the end of the `shell-kit`
task; not a task template on its own.

`audit_parts(...)` is the reusable geometric core `audit()` is a thin reader
around: given already-loaded, already-validated meshes plus group/insertion
declarations, it does the removal-order sampling and returns the exact dict
shape both `audit()` and `studio.core.task_operations.removal_audit()` write
to disk. Extracted so any watertight-STL assembly (not just a head-shell) can
get the same check via the `removal-audit` task template.
"""

from pathlib import Path
from itertools import product
import json

import numpy as np
import trimesh

from studio.i18n import render
from studio.core.kernels.mechanical_geometry import solid, union, overlap
from studio.core.task_operations import write_json


def audit_parts(meshes, *, groups, insertion_directions, radial_center_mm, split_axis=1, split_value=0.0):
    """Sample a discrete per-group removal order for `meshes` (name -> an
    already-validated single-watertight trimesh, in millimetres).

    `groups` declares known membership as `{group_name: [part names]}` (may
    be partial or `{}`). Any mesh name not already listed in some group is
    auto-assigned: if the name equals a group's own key it joins that group
    as the group's fixed host/chassis (never itself a removal candidate --
    this is how `head_shell`'s "front_shell"/"back_shell" shells stay put
    while their decorative parts get ordered); otherwise it is assigned to
    the first or second declared group by comparing
    `mesh.center_mass[split_axis]` (millimetres) against `split_value`,
    which needs at least two declared groups to be meaningful.

    `insertion_directions` is `{part_name: [x, y, z]}`, a declared "pull this
    way first" guess per part; `radial_center_mm` seeds a second guess (pull
    straight away from this point) for parts with no declared direction.

    Returns the exact dict shape `head_shell.audit()` has always written to
    `assembly-verification.json` (`half_groups`/`whole_halves` keep their
    head-shell-era field names, including `translation_y_mm`, even when
    `split_axis` is not Y, so `audit()`'s output stays byte-identical). When
    `groups` does not resolve to exactly two buckets, `whole_halves` is left
    empty -- the "pull the two main sub-assemblies apart" check is inherently
    a two-group question.
    """
    parts = {n: solid(m) for n, m in meshes.items()}
    resolved = {name: list(members) for name, members in groups.items()}
    assigned = {n for members in resolved.values() for n in members}
    bucket_names = list(resolved)
    for name in meshes:
        if name in assigned:
            continue
        if name in resolved:
            target = name
        elif len(bucket_names) >= 2:
            target = bucket_names[0] if meshes[name].center_mass[split_axis] < split_value else bucket_names[1]
        else:
            raise ValueError(render("head_shell_audit.ungrouped_parts_need_two_groups", name=name))
        resolved[target].append(name)
        assigned.add(name)
    whole = []
    if len(bucket_names) == 2:
        axis_vector = np.eye(3)[split_axis]
        front = union([parts[n] for n in resolved[bucket_names[0]]])
        back = union([parts[n] for n in resolved[bucket_names[1]]])
        for mm in np.linspace(0, 450, 46):
            whole.append(
                {
                    "translation_y_mm": float(mm),
                    "overlap_mm3": overlap(front, back.translate((axis_vector * mm).tolist())),
                }
            )
    directions = np.array([d for d in product((-1, 0, 1), repeat=3) if any(d)], float)
    steps = []
    unresolved = []
    tested = 0
    distances = np.r_[np.arange(0, 15, 0.5), np.arange(15, 451, 5)]
    radial_center = np.asarray(radial_center_mm, float)
    # Split the halves first. Test each decorative removal on its own open half;
    # the opposite half is not an obstacle during this manufacturing stage.
    for host, group in resolved.items():
        remaining = set(group)
        pending = set(group) - {host}
        while pending:
            progressed = False
            for name in sorted(pending, key=lambda n: meshes[n].volume):
                others = union([parts[n] for n in sorted(remaining) if n != name])
                radial = meshes[name].center_mass - radial_center
                declared = insertion_directions.get(name, [0, 0, 0])
                candidates = np.vstack([declared, radial, -radial, [0, -1, 0], [0, 1, 0], directions])
                for vector in candidates:
                    if np.linalg.norm(vector) < 1e-8:
                        continue
                    direction = vector / np.linalg.norm(vector)
                    worst = 0
                    for mm in distances:
                        v = overlap(parts[name].translate(direction * mm), others)
                        tested += 1
                        worst = max(worst, v)
                        if v > 0.001:
                            break
                    if worst <= 0.001:
                        steps.append(
                            {
                                "part": name,
                                "host": host,
                                "remove_direction": direction.tolist(),
                                "max_overlap_mm3": worst,
                                "samples": len(distances),
                                "travel_mm": float(distances[-1]),
                            }
                        )
                        remaining.remove(name)
                        pending.remove(name)
                        progressed = True
                        break
                if progressed:
                    break
            if not progressed:
                unresolved.extend(sorted(pending))
                break
    return {
        "readback": {"parts": len(parts), "all_single_watertight": True},
        "half_groups": resolved,
        "whole_halves": whole,
        "decorative_removal_steps": steps,
        "assembly_order": list(reversed([x["part"] for x in steps])),
        "unresolved_parts": unresolved,
        "tested_collision_poses": tested,
        "status": "pass_sampled"
        if not unresolved and (not whole or max(x["overlap_mm3"] for x in whole) <= 0.001)
        else "needs_review",
        "limitations": [
            "先各自在敞开的半壳上安装分色件，最后合壳",
            "离散采样，不是连续碰撞或实物装配证明",
        ],
    }


def audit(folder, output):
    folder = Path(folder)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    meshes = {p.stem: trimesh.load_mesh(p, process=True) for p in sorted(folder.glob("*.stl"))}
    for n, m in meshes.items():
        if not m.is_volume or len(m.split(only_watertight=False, repair=False)) != 1:
            raise ValueError(render("head_shell_audit.stl_not_single_watertight", name=n))
    report = json.loads((folder / "report.json").read_text())
    named = report["params"].get("component_names", {})
    declared_by_index = report["params"].get("insertion_directions", {})
    insertion_directions = {}
    for i, name in named.items():
        if name not in insertion_directions and i in declared_by_index:
            insertion_directions[name] = declared_by_index[i]
    result = audit_parts(
        meshes,
        groups={"front_shell": [], "back_shell": []},
        insertion_directions=insertion_directions,
        radial_center_mm=[0, 8, 140],
        split_axis=1,
        split_value=report["params"].get("split_y_mm", 0),
    )
    result = {"source_task_output": str(folder), **result}
    write_json(output / "assembly-verification.json", result)
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return result
