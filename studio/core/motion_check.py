"""Bounded, explicit configuration sampling; never infer continuous safety."""

import itertools
from pathlib import Path
import numpy as np
from studio.core import fabrication as f


def configurations(joints, p):
    mode = p.get("sampling", "simultaneous_linear")
    steps = p.get("steps", 21 if mode == "simultaneous_linear" else 5)
    if type(steps) is not int or not 2 <= steps <= 101:
        f.invalid("steps")
    ranges = {j["name"]: j["range"] for j in joints}
    if any(not np.isfinite(bounds).all() or bounds[0] > bounds[1] for bounds in ranges.values()):
        f.invalid("joint_ranges")
    if mode == "simultaneous_linear":
        return mode, [
            {"phase": float(t), "configuration": {k: float(lo + (hi - lo) * t) for k, (lo, hi) in ranges.items()}}
            for t in np.linspace(0, 1, steps if joints else 1)
        ]
    if mode == "explicit":
        configs = p.get("configurations")
        if not isinstance(configs, list) or not 1 <= len(configs) <= 4096:
            f.invalid("configurations")
        for cfg in configs:
            if not isinstance(cfg, dict) or set(cfg) != set(ranges):
                f.invalid("configuration joint names")
            for k, v in cfg.items():
                if (
                    isinstance(v, bool)
                    or not isinstance(v, (int, float))
                    or not np.isfinite(v)
                    or not ranges[k][0] <= v <= ranges[k][1]
                ):
                    f.invalid("configuration joint limits")
        return mode, [{"configuration": {name: float(value) for name, value in cfg.items()}} for cfg in configs]
    if mode != "grid" or steps ** len(ranges) > 4096:
        f.invalid("sampling/grid exceeds 4096 configurations")
    axes = [np.linspace(lo, hi, steps) for lo, hi in ranges.values()]
    return mode, [{"configuration": dict(zip(ranges, map(float, values)))} for values in itertools.product(*axes)]


def run(w):
    from studio.core.task_operations import assembly_audit_urdf, write_json
    from studio.core.observation import dependencies, digest

    if len(w["inputs"]) != 1 or Path(w["inputs"][0]).suffix.lower() != ".urdf":
        f.invalid("single URDF input")
    params = {**w["params"], "sampling": w["params"].get("sampling", "grid")}
    if params["sampling"] not in ("grid", "explicit"):
        f.invalid("sampling must be grid or explicit")
    refs = dependencies(w["inputs"][0])
    hashes = {str(path): digest(path) for path in refs}
    report = assembly_audit_urdf(Path(w["inputs"][0]), params)
    f.require(all(digest(path) == value for path, value in hashes.items()), "motion_inputs_changed")
    report["input_sha256"] = hashes
    report["operation"] = "motion-check"
    report["clear_configurations"] = [s["configuration"] for s in report["samples"] if not s["collisions"]]
    report["sampled_clear_values"] = {
        j["name"]: sorted({cfg[j["name"]] for cfg in report["clear_configurations"]}) for j in report["joints"]
    }
    report["range_claim"] = "sampled configurations only; per-axis values cannot be recombined as a safe range"
    report["retention_checked"] = False
    report["physical_calibration"] = "pending"
    write_json(Path(w["output"]) / "motion-check.json", report)
    write_json(Path(w["output"]) / "report.json", report)
