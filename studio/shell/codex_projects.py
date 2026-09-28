"""The Codex-specific `resolve_cwd` resolver for `studio.core.projects`.

`studio.core.projects.thread_folder()`/`auto_attach()` need to turn a Codex
task ID into that thread's working directory, but `studio.core` must not
import `studio.shell.codex_bridge` directly (layer rule, see
`docs/ARCHITECTURE.md`). This module is the one place that bridges the two:
`studio.shell.mcp_server` passes `resolve_cwd` in at the call site, and
`studio.core.projects` only ever sees a plain callable.
"""

from __future__ import annotations

from typing import Any

from studio.shell.codex_bridge import CodexBridge, identity


def resolve_cwd(workspace_id: str) -> dict[str, Any]:
    """Read the named Codex thread; returns its raw `{"id": ..., "cwd": ...}`."""
    with CodexBridge(identity()) as bridge:
        return bridge.read(workspace_id)
