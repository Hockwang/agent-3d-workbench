"""`studio/mcp_server.py` is a compatibility stub for `.mcp.json` files
generated before the studio/core|adapters|shell restructure (they still point
at `studio/mcp_server.py`, which no longer holds the real implementation).
Smoke-tested as a real subprocess, the same way an existing install's Codex
would actually invoke it.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_STUB = Path(__file__).resolve().parent.parent / "studio" / "mcp_server.py"


def test_compat_stub_exits_cleanly_without_a_traceback():
    # The real server (studio/shell/mcp_server.py) has no argparse of its own —
    # `--help` is simply ignored, same as any other argv here — but with
    # stdin closed the stdio-MCP loop sees immediate EOF and returns 0, which
    # is exactly what a stale `.mcp.json` handshake attempt should not choke on.
    result = subprocess.run(
        [sys.executable, str(_STUB), "--help"],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    assert "Traceback" not in result.stderr
    assert result.stdout == ""


def test_compat_stub_forwards_to_the_real_shell_module():
    from studio.shell import mcp_server as real

    import studio.mcp_server as stub

    assert stub.main is real.main
