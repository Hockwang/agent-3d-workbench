#!/usr/bin/env python3
"""print-prep Studio 面板的进程管理入口：`start | stop | status | url`（SPEC.md §7）。

跑法固定为 `uv run --project <插件根> python <插件根>/scripts/studio.py <子命令>
[选项]`。stdout 恒为单个 JSON 对象；状态文件与日志都在 `PRINT_PREP_HOME`（缺省
`~/.print-prep`）下——测试必须把这个环境变量指到临时目录，不得碰真实目录。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Optional

_PLUGIN_ROOT = Path(__file__).resolve().parent.parent
if str(_PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(_PLUGIN_ROOT))

import studio  # noqa: E402


def _print(obj: dict[str, Any]) -> None:
    print(json.dumps(obj, ensure_ascii=False))


def cmd_start(job: Optional[str], port: int) -> int:
    job_dir = Path(job).expanduser() if job else studio.default_job_dir()
    try:
        info = studio.start_server(job_dir, port=port)
    except Exception as exc:  # noqa: BLE001
        _print({"ok": False, "error": {"code": "start_failed", "message": str(exc)}})
        return 1
    _print({"ok": True, **info})
    return 0


def cmd_stop() -> int:
    stopped = studio.stop_server()
    _print({"ok": True, "stopped": stopped})
    return 0


def cmd_status() -> int:
    info = studio.current_session()
    if info:
        _print({"ok": True, "running": True, **info})
    else:
        _print({"ok": True, "running": False})
    return 0


def cmd_url() -> int:
    info = studio.current_session()
    if info:
        _print({"ok": True, "url": info["url"]})
        return 0
    _print({"ok": False, "error": {"code": "not_running", "message": "本机服务没有在跑"}})
    return 1


def _parse_start_args(rest: list[str]) -> tuple[Optional[dict[str, Any]], Optional[str], int]:
    job: Optional[str] = None
    port = studio.DEFAULT_PORT
    i = 0
    while i < len(rest):
        if rest[i] == "--job" and i + 1 < len(rest):
            job = rest[i + 1]
            i += 2
        elif rest[i] == "--port" and i + 1 < len(rest):
            try:
                port = int(rest[i + 1])
            except ValueError:
                return (
                    {
                        "ok": False,
                        "error": {"code": "bad_arguments", "message": f"--port 不是合法整数: {rest[i + 1]!r}"},
                    },
                    None,
                    0,
                )
            i += 2
        else:
            return {"ok": False, "error": {"code": "bad_arguments", "message": f"未知参数: {rest[i]!r}"}}, None, 0
    return None, job, port


def main(argv: Optional[list[str]] = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        _print({"ok": False, "error": {"code": "bad_arguments", "message": "缺少子命令: start|stop|status|url"}})
        return 2

    sub, rest = argv[0], argv[1:]
    if sub == "start":
        error, job, port = _parse_start_args(rest)
        if error is not None:
            _print(error)
            return 2
        return cmd_start(job, port)
    if sub == "stop":
        return cmd_stop()
    if sub == "status":
        return cmd_status()
    if sub == "url":
        return cmd_url()
    _print({"ok": False, "error": {"code": "bad_arguments", "message": f"未知子命令: {sub!r}"}})
    return 2


if __name__ == "__main__":
    sys.exit(main())
