"""studio —— print-prep 的 Studio 面板：本机 HTTP 服务 + stdio MCP 服务共用的
最小一组进程管理工具函数（SPEC.md §6/§7）。

`server.py`（本机服务本体）、`mcp_server.py`（stdio MCP 服务）、`scripts/studio.py`
（start/stop/status/url 入口）都从这里取 `PRINT_PREP_HOME` 解析、session 文件的
读写、"服务是不是真的在跑"的判定与"没跑就拉起"的共同逻辑，三处不各写一份。

判活刻意不用 `pgrep`/进程名模式匹配（同仓 memory
`process-liveness-check-discipline`：模式匹配容易连自己都误判），而是三件事
都成立才算真的在跑：状态文件存在 -> 里面的 pid 存活（`os.kill(pid, 0)`）->
`/api/session` 探测得通。
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional

DEFAULT_PORT = 8977


def print_prep_home() -> Path:
    """`PRINT_PREP_HOME` 环境变量，缺省 `~/.print-prep`（SPEC.md §7）。测试必须
    把这个环境变量指到临时目录，不得碰真实的 `~/.print-prep`。"""
    raw = os.environ.get("PRINT_PREP_HOME")
    return Path(raw).expanduser() if raw else (Path.home() / ".print-prep")


def default_job_dir() -> Path:
    """`--job` 缺省值：`PRINT_PREP_HOME/job`（SPEC.md §7）。"""
    return print_prep_home() / "job"


def session_file_path(home: Path | None = None) -> Path:
    return (home or print_prep_home()) / "studio.json"


def log_file_path(home: Path | None = None) -> Path:
    return (home or print_prep_home()) / "studio.log"


def read_session_file(home: Path | None = None) -> Optional[dict[str, Any]]:
    path = session_file_path(home)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def is_pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    except (TypeError, ValueError):
        return False
    return True


def probe_health(base_url: str, timeout: float = 2.0) -> Optional[dict[str, Any]]:
    """探一次 `GET /api/session`，通就返回其 JSON，不通（连不上/超时/非 200）
    一律返回 `None`，不抛异常——调用方只关心"通不通"。"""
    try:
        with urllib.request.urlopen(base_url.rstrip("/") + "/api/session", timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError):
        return None


def current_session(home: Path | None = None) -> Optional[dict[str, Any]]:
    """状态文件存在、其中的 pid 存活、且 `/api/session` 探测得通，三者同时成立
    才认为服务真的在跑；否则返回 `None`（陈旧的状态文件不会被误判成"在跑"）。"""
    info = read_session_file(home)
    if not info:
        return None
    pid = info.get("pid")
    if not isinstance(pid, int) or not is_pid_alive(pid):
        return None
    url = info.get("url")
    if not url or probe_health(url) is None:
        return None
    return info


def start_server(
    job_dir: Path, port: int = DEFAULT_PORT, timeout: float = 15.0, *, home: Path | None = None
) -> dict[str, Any]:
    """后台拉起 `studio/shell/server.py`，轮询健康检查通过后返回 session 信息；已经在
    跑就直接返回现有信息，不重复拉起、也不改它绑定的 job 目录（SPEC.md §7）。"""
    existing = current_session(home)
    if existing:
        return existing

    home = home or print_prep_home()
    home.mkdir(parents=True, exist_ok=True)
    from studio.paths import SHELL_DIR

    server_script = SHELL_DIR / "server.py"
    env = dict(os.environ)
    # The server's own logs/session file use a scoped home. Cross-chat binding
    # must retain the original workspace registry root, not nest it again.
    env.setdefault("PRINT_PREP_WORKSPACES_HOME", str(print_prep_home()))
    env["PRINT_PREP_HOME"] = str(home)
    with open(log_file_path(home), "ab") as log:
        subprocess.Popen(
            [sys.executable, str(server_script), "--job", str(job_dir), "--port", str(port)],
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
            start_new_session=True,
            env=env,
        )

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        info = current_session(home)
        if info:
            return info
        time.sleep(0.2)
    raise RuntimeError(f"本机服务在 {timeout}s 内没有起来，日志见 {log_file_path(home)}")


def stop_server(timeout: float = 5.0, *, home: Path | None = None) -> bool:
    """结束进程并删状态文件；本来就没在跑（无状态文件、或 pid 已死）也会把残留
    的状态文件清掉。返回是否做了实质性的停止动作。"""
    info = read_session_file(home)
    stopped = False
    if info:
        pid = info.get("pid")
        if isinstance(pid, int) and is_pid_alive(pid):
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline and is_pid_alive(pid):
                time.sleep(0.1)
            if is_pid_alive(pid):
                try:
                    os.kill(pid, signal.SIGKILL)
                except OSError:
                    pass
            stopped = True
    path = session_file_path(home)
    if path.exists():
        try:
            path.unlink()
        except OSError:
            pass
        stopped = True
    return stopped
