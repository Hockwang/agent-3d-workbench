"""Run the current repository's HTTP workbench next to the independent CAD backend."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

MODULE_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = MODULE_ROOT.parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT))

from studio.shell.server import create_httpd


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8767)
    args = parser.parse_args()
    os.environ["LINK_EVERYTHING_ROOT"] = str(MODULE_ROOT)
    # Keep this demo's workspaces and settings away from an installed plugin.
    os.environ["PRINT_PREP_HOME"] = str(MODULE_ROOT / "outputs" / "workbench_home")
    job = MODULE_ROOT / "outputs" / "workbench_project"
    job.mkdir(parents=True, exist_ok=True)
    httpd, port, _ = create_httpd(job, port=args.port)
    print(f"Link Everything workbench: http://127.0.0.1:{port}/?mode=assembly", flush=True)
    try:
        httpd.serve_forever()
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
