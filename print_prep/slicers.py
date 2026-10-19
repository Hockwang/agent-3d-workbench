"""Local slicer discovery and explicit file handoff. Never contacts a printer."""

from __future__ import annotations

import os
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

from . import profiles
from .messages import render

# App/executable names, not printer protocols. Each CLI is verified separately.
SLICERS = {
    "bambu": ("Bambu Studio", "BambuStudio", "bambu-studio", "BAMBU_STUDIO"),
    "orca": ("OrcaSlicer", "OrcaSlicer", "orca-slicer", "ORCA_SLICER"),
    "creality": ("Creality Print", "Creality Print", "CrealityPrint", "CREALITY_PRINT"),
    "elegoo": ("ElegooSlicer", "ElegooSlicer", "ElegooSlicer", "ELEGOO_SLICER"),
    "snapmaker": ("Snapmaker Orca", "Snapmaker Orca", "Snapmaker_Orca", "SNAPMAKER_ORCA"),
}


class SlicerError(RuntimeError):
    """An unavailable or unsuccessful local handoff."""


def definition(slicer: str) -> tuple[str, str, str, str]:
    if slicer not in SLICERS:
        raise SlicerError(render("slicer.unknown", slicer=slicer))
    return SLICERS[slicer]


def app_path(slicer: str) -> Path:
    label, mac_name, executable, prefix = definition(slicer)
    if slicer == "bambu":
        return profiles.app_root()
    configured = os.environ.get(f"{prefix}_APP") or os.environ.get(f"{prefix}_PATH")
    if configured:
        return Path(configured).expanduser()
    if sys.platform == "darwin":
        return Path("/Applications") / f"{mac_name}.app"
    if sys.platform == "win32":
        return Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / label / f"{executable}.exe"
    executable = {"elegoo": "elegoo-slicer", "snapmaker": "snapmaker-orca"}.get(slicer, executable)
    found = shutil.which(executable)
    return Path(found) if found else Path.home() / ".local/bin" / executable


def binary_path(slicer: str) -> Path:
    _, mac_name, _, prefix = definition(slicer)
    if slicer == "bambu":
        return profiles.bambu_binary()
    configured = os.environ.get(f"{prefix}_PATH")
    if configured:
        return Path(configured).expanduser()
    app = app_path(slicer)
    if app.suffix != ".app":
        return app
    info = app / "Contents/Info.plist"
    if info.is_file():
        with info.open("rb") as stream:
            executable = plistlib.load(stream).get("CFBundleExecutable", mac_name)
        if not isinstance(executable, str) or Path(executable).name != executable:
            raise SlicerError(render("slicer.app_missing", slicer=slicer, path=app))
        return app / "Contents/MacOS" / executable
    return app / "Contents/MacOS" / mac_name


def list_slicers() -> list[dict]:
    return [
        {
            "id": key,
            "name": spec[0],
            "installed": app_path(key).exists(),
            "app": str(app_path(key)),
            "automated_profiles": True,
            "project_export": key != "creality",
            "headless_slice": key != "creality",
            "hardware_validation": "not_inferred_from_preset",
        }
        for key, spec in SLICERS.items()
    ]


def open_file(slicer: str, path: Path, *, dry_run: bool = False) -> dict:
    app = app_path(slicer)
    if not path.is_file():
        raise SlicerError(render("slicer.file_missing", path=path))
    if sys.platform == "darwin" and app.suffix == ".app":
        command = ["open", "-a", str(app), str(path.resolve())]
    else:
        command = [str(app), str(path.resolve())]
    if not dry_run:
        if not app.exists():
            raise SlicerError(render("slicer.app_missing", slicer=definition(slicer)[0], path=app))
        try:
            if sys.platform == "darwin" and app.suffix == ".app":
                subprocess.run(command, check=True, capture_output=True, timeout=30)
            else:
                subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        except (OSError, subprocess.SubprocessError) as exc:
            raise SlicerError(render("slicer.open_failed", slicer=slicer, error=str(exc))) from exc
    return {"command": command, "executed": not dry_run, "path": str(path), "loaded": "unverified"}
