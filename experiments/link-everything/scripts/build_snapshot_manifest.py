"""Hash explicitly allowed public source directories, never runtime state or models."""

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIRECTORIES = ("backend", "frontend", "tests", "integration", "scripts")
ROOT_FILES = (".gitattributes", ".gitignore", "README.md", "Start-Demo.ps1", "verify_snapshot.py", "validation.md")
EXCLUDED = {".venv", "_vendor", "outputs", "__pycache__", ".pytest_cache", "node_modules"}
MODEL_SUFFIXES = {".glb", ".gltf", ".stl", ".obj", ".blend", ".3mf", ".zip", ".webm", ".mp4", ".log", ".pyc"}
PRIVATE_SUFFIXES = {".pem", ".key", ".p12", ".pfx", ".keystore"}


def main():
    paths = [ROOT / name for name in ROOT_FILES]
    for directory in DIRECTORIES:
        paths.extend((ROOT / directory).rglob("*"))
    files = []
    for path in sorted(set(paths)):
        relative = path.relative_to(ROOT)
        if not path.is_file() or any(part in EXCLUDED for part in relative.parts):
            continue
        if (
            path.name.startswith((".env", "credentials", "secrets"))
            or path.name in {"runtime.json", ".netrc"}
            or path.suffix.lower() in MODEL_SUFFIXES | PRIVATE_SUFFIXES
        ):
            continue
        data = path.read_bytes()
        files.append({"path": relative.as_posix(), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
    manifest = {
        "schema": "link-everything.public-source/v1",
        "date": "2026-10-08",
        "workbench_base": "8906e3de11262db9961dfa474ef22a150dab77b7",
        "runtime_outputs_included": False,
        "files": files,
    }
    (ROOT / "snapshot_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"Recorded {len(files)} public source files")


if __name__ == "__main__":
    main()
