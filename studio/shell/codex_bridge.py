"""Bounded official App Server client. No model turns or private desktop IPC."""

from __future__ import annotations

import json
import os
import queue
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path

from studio.i18n import render


class BridgeError(RuntimeError):
    pass


def identity():
    executable = shutil.which("codex")
    if not executable:
        raise BridgeError(render("codex_bridge.cli_not_found"))
    result = subprocess.run([executable, "--version"], capture_output=True, text=True, timeout=10, check=True)
    version = result.stdout.strip()
    match = re.search(r"codex-cli (\d+)\.(\d+)\.(\d+)", version)
    if not match or tuple(map(int, match.groups())) < (0, 154, 0):
        raise BridgeError(render("codex_bridge.cli_too_old"))
    return {
        "executable": str(Path(executable).resolve()),
        "version": version,
        "home": str(Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")).resolve()),
    }


class CodexBridge:
    METHODS = {"thread/read", "thread/fork", "thread/name/set"}

    def __init__(self, verified_identity=None):
        self.identity = verified_identity or identity()
        self.process = None

    def __enter__(self):
        env = dict(os.environ)
        env.pop("CODEX_THREAD_ID", None)
        self.process = subprocess.Popen(
            [self.identity["executable"], "app-server", "--listen", "stdio://"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            env=env,
            start_new_session=True,
        )
        self.messages = queue.Queue()
        self.sequence = 0

        def read():
            try:
                for line in self.process.stdout:
                    try:
                        self.messages.put(json.loads(line))
                    except ValueError:
                        continue
            finally:
                self.messages.put(None)

        self.reader = threading.Thread(target=read, daemon=True)
        self.reader.start()
        try:
            self._rpc(
                "initialize",
                {
                    "clientInfo": {"name": "studio_part_chat", "version": "1.0.0"},
                    "capabilities": {"experimentalApi": True},
                },
            )
            self._send({"method": "initialized"})
        except Exception:
            self.__exit__(None, None, None)
            raise
        return self

    def _send(self, data):
        self.process.stdin.write(json.dumps(data) + "\n")
        self.process.stdin.flush()

    def _rpc(self, method, params, on_started=None):
        if method not in self.METHODS | {"initialize"}:
            raise BridgeError(render("codex_bridge.unsupported_operation"))
        self.sequence += 1
        request_id = self.sequence
        self._send({"id": request_id, "method": method, "params": params})
        deadline = time.monotonic() + 90
        while True:
            try:
                item = self.messages.get(timeout=max(0.01, deadline - time.monotonic()))
            except queue.Empty:
                raise BridgeError(render("codex_bridge.timeout_do_not_retry")) from None
            if item is None:
                raise BridgeError(render("codex_bridge.disconnected"))
            if item.get("method") == "thread/started" and on_started:
                on_started(item["params"]["thread"])
            # This adapter never approves tools or executes a model turn.
            if "method" in item and "id" in item:
                self._send({"id": item["id"], "error": {"code": -32601, "message": "Unsupported by part-chat adapter"}})
            elif item.get("id") == request_id:
                if "error" in item:
                    raise BridgeError(str(item["error"].get("message", render("codex_bridge.request_failed_fallback"))))
                return item["result"]
            if time.monotonic() >= deadline:
                raise BridgeError(render("codex_bridge.timeout"))

    def read(self, thread_id):
        return self._rpc("thread/read", {"threadId": thread_id, "includeTurns": False})["thread"]

    def fork(self, parent_id, cwd, on_started):
        return self._rpc(
            "thread/fork",
            {
                "threadId": parent_id,
                "cwd": cwd,
                "excludeTurns": True,
                "ephemeral": False,
                "deferGoalContinuation": True,
            },
            on_started,
        )["thread"]

    def rename(self, thread_id, title):
        return self._rpc("thread/name/set", {"threadId": thread_id, "name": title})

    def __exit__(self, *_):
        if self.process:
            self.process.stdin.close()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.terminate()
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=5)
            self.reader.join(timeout=1)
            self.process.stdout.close()
