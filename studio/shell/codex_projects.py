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

from studio.i18n import render
from studio.shell.codex_bridge import BridgeError, CodexBridge, identity


class ThreadNotReady(BridgeError):
    code = "codex_projects.thread_not_ready"

    def __init__(self):
        super().__init__(render(self.code))


def resolve_cwd(workspace_id: str) -> dict[str, Any]:
    """Read the named Codex thread; returns its raw `{"id": ..., "cwd": ...}`."""
    with CodexBridge(identity()) as bridge:
        try:
            return bridge.read(workspace_id)
        except BridgeError as exc:
            message = str(exc)
            # A separate app-server cannot read an in-memory desktop draft yet.
            # Match only the two observed readiness failures for this exact ID;
            # permission, corrupt metadata and transport failures stay errors.
            if message == f"thread not loaded: {workspace_id}" or (
                message.startswith(
                    "failed to read thread: thread-store internal error: failed to read session metadata "
                )
                and f"-{workspace_id}.jsonl: rollout at " in message
                and message.endswith(f"-{workspace_id}.jsonl is empty")
            ):
                raise ThreadNotReady() from exc
            raise
