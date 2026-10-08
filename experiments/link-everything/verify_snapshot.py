"""Verify the public module's byte identity without reading runtime outputs."""

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main():
    manifest = json.loads((ROOT / "snapshot_manifest.json").read_text(encoding="utf-8"))
    for record in manifest["files"]:
        path = ROOT / record["path"]
        data = path.read_bytes()
        if len(data) != record["bytes"] or hashlib.sha256(data).hexdigest() != record["sha256"]:
            raise SystemExit(f"Snapshot mismatch: {record['path']}")
    print(f"Verified {len(manifest['files'])} public source files")


if __name__ == "__main__":
    main()
