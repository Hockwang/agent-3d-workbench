"""Read multi-brand FDM presets from installed slicer distributions.

Catalog presence is configuration coverage, not hardware validation. Nonrectangular
beds are excluded; rectangular beds retain their native origin. No vendor presets
are bundled with this package.
"""

from __future__ import annotations

import copy
import json
import math
import os
import threading
import time
from pathlib import Path

from . import profiles, slicers

SOURCES = ("orca", "creality", "elegoo", "snapmaker")
_cache: dict = {}
_cache_lock = threading.Lock()


def source_root(slicer: str) -> Path:
    configured = os.environ.get(f"MFG_{slicer.upper()}_PROFILE_ROOT")
    if configured:
        return Path(configured).expanduser()
    app = slicers.app_path(slicer)
    if app.suffix == ".app":
        return app / "Contents/Resources/profiles"
    return app.parent / "resources/profiles"


def vendor_roots(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    # Discover every installed vendor, including new ones after a slicer upgrade.
    # Symlinks must not escape the selected preset tree.
    return sorted(p for p in root.iterdir() if (p / "machine").is_dir()
                  and p.resolve().parent == root.resolve())


def vendor_index(root: Path) -> dict[str, Path]:
    idx = profiles._index(root)
    # Forks inherit common filament libraries alongside their vendor directory.
    for shared in sorted(root.parent.glob("*FilamentLibrary/filament")):
        for path in sorted(shared.rglob("*.json")):
            raw = json.loads(path.read_text())
            idx.setdefault(path.stem, path)
            if raw.get("name"):
                idx.setdefault(raw["name"], path)
    return idx


def context(name: str) -> tuple[str, Path, dict[str, Path], str]:
    if "::" not in name:
        root = profiles.profile_root()
        return "bambu", root, profiles._index(root), name
    fields = name.split("::", 2)
    if len(fields) != 3 or fields[0] not in SOURCES or not fields[2]:
        raise profiles.ProfileError(profiles.render("slicer.profile_id", name=name))
    source, vendor, native = fields
    roots = {p.name: p for p in vendor_roots(source_root(source))}
    if vendor not in roots:
        raise profiles.ProfileError(profiles.render("slicer.profile_id", name=name))
    root = roots[vendor]
    return source, root, vendor_index(root), native


def _supported_bed(machine: dict) -> bool:
    points = set(profiles._parse_points(machine.get("printable_area")))
    bed = profiles.bed_params(machine)
    bx, by, bz = bed["bed_mm"]
    ox, oy = bed["bed_origin_mm"]
    return (all(math.isfinite(v) for v in (bx, by, bz, ox, oy))
            and min(bx, by, bz) > 0
            and points == {(ox, oy), (ox + bx, oy), (ox + bx, oy + by), (ox, oy + by)})


def catalog() -> dict:
    roots = {source: source_root(source) for source in SOURCES}
    key = tuple((source, str(root)) for source, root in roots.items())
    # State and printer-list requests arrive together on page load. Share one
    # scan, and start its TTL at completion so a slow scan is not born expired.
    with _cache_lock:
        now = time.monotonic()
        if _cache.get("key") != key or now - _cache.get("at", 0) >= 30:
            result = _scan_catalog(roots)
            _cache.update(key=key, at=time.monotonic(), value=result)
        return copy.deepcopy(_cache["value"])


def _scan_catalog(roots: dict[str, Path]) -> dict:
    result: dict = {"printers": [], "excluded": [], "errors": []}
    for source, root in roots.items():
        for vendor_root in vendor_roots(root):
            vendor = vendor_root.name
            try:
                idx = vendor_index(vendor_root)
            except (profiles.ProfileError, OSError, ValueError) as exc:
                result["errors"].append({"slicer": source, "vendor": vendor, "error": str(exc)})
                continue
            for path in sorted((vendor_root / "machine").rglob("*.json")):
                try:
                    raw = json.loads(path.read_text())
                    # Model description records have no instance/inheritance.
                    if str(raw.get("instantiation")).lower() != "true":
                        continue
                    native = raw["name"]
                    machine = profiles.resolve(native, idx)
                    if not _supported_bed(machine):
                        result["excluded"].append({"slicer": source, "vendor": vendor, "name": native, "reason": "unsupported_bed"})
                        continue
                    process = machine.get("default_print_profile")
                    filaments = machine.get("default_filament_profile") or []
                    filament = filaments[0] if filaments else None
                    # Do not advertise an automatic route without resolvable presets.
                    profiles.resolve(process, idx)
                    profiles.resolve(filament, idx)
                    bed = profiles.bed_params(machine)
                    nozzle = machine.get("nozzle_diameter") or []
                    if isinstance(nozzle, str):
                        nozzle = nozzle.split(",")
                    result["printers"].append({
                        "name": f"{source}::{vendor}::{native}",
                        "display_name": native,
                        "slicer": source,
                        "vendor": vendor,
                        "printer_model": machine.get("printer_model"),
                        "nozzle_mm": float(nozzle[0]) if nozzle else None,
                        **bed,
                        "default_process": process,
                        "default_filament": filament,
                        "overhang_angle_deg": profiles.DEFAULT_OVERHANG_ANGLE_DEG,
                    })
                except (profiles.ProfileError, OSError, ValueError, KeyError, TypeError) as exc:
                    result["errors"].append({"slicer": source, "vendor": vendor, "path": str(path), "error": str(exc)})
    return result
