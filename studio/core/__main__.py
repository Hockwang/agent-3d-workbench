"""`python -m studio.core` —— shell-independent entry point.

Runs the argparse CLI in `studio/core/cli.py` and exits with its return
code. See `docs/CORE_CLI.md` for the full command reference; MCP/HTTP
(`studio/shell/`) remain the Codex path and are unaffected by this module.
"""

from __future__ import annotations

import sys

from studio.core.cli import main

if __name__ == "__main__":
    sys.exit(main())
