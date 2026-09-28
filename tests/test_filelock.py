"""studio.core.filelock —— cross-platform whole-file mutex used by
studio/core/workspaces.py, studio/adapters/service_connections.py and
studio/shell/part_chat.py. Two things need real coverage that a plain
same-process import can't give:

1. None of those three modules may do a module-level `import fcntl` any more
   (that used to crash the whole MCP/HTTP service at startup on Windows,
   where `fcntl` doesn't exist) — verified in a subprocess with
   `sys.modules["fcntl"] = None`, the standard trick to simulate an absent
   module without actually needing to run on Windows.
2. `filelock.lock()`'s POSIX path (`fcntl.flock`) has to really exclude a
   second locker, not just avoid crashing — verified with two independent
   file objects on the same path and a background thread.
"""

from __future__ import annotations

import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from studio.core import filelock

_REPO_ROOT = Path(__file__).resolve().parent.parent


def test_workspaces_service_connections_and_part_chat_import_without_fcntl():
    script = (
        "import sys\n"
        "sys.modules['fcntl'] = None\n"
        "import studio.core.filelock as fl\n"
        "assert fl.fcntl is None, 'filelock should have detected fcntl as absent'\n"
        "import studio.core.workspaces\n"
        "import studio.adapters.service_connections\n"
        "import studio.shell.part_chat\n"
        "print('OK')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "OK"


def test_lock_and_unlock_raise_a_clear_error_when_no_primitive_is_available(monkeypatch):
    monkeypatch.setattr(filelock, "fcntl", None)
    monkeypatch.setattr(filelock, "msvcrt", None)
    with pytest.raises(RuntimeError, match="no file locking primitive"):
        filelock.lock(0)
    with pytest.raises(RuntimeError, match="no file locking primitive"):
        filelock.unlock(0)


@pytest.mark.skipif(filelock.fcntl is None, reason="needs a real POSIX fcntl to prove exclusion")
def test_posix_lock_really_excludes_a_second_locker(tmp_path):
    path = tmp_path / "test.lock"
    path.touch()
    events: list[str] = []

    with path.open("a") as first:
        filelock.lock(first)

        def second_locker():
            with path.open("a") as second:
                filelock.lock(second)
                events.append("second-acquired")
                filelock.unlock(second)

        thread = threading.Thread(target=second_locker)
        thread.start()
        time.sleep(0.2)
        # `first` still holds the lock: the second locker must still be blocked.
        assert events == []
        events.append("first-released")
        filelock.unlock(first)
        thread.join(timeout=2)

    assert not thread.is_alive()
    assert events == ["first-released", "second-acquired"]
