"""Compatibility entry point for `.mcp.json` files generated before the
studio/core|adapters|shell restructure; re-run install.sh to regenerate one
pointing at studio/shell/mcp_server.py directly."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from studio.shell.mcp_server import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
