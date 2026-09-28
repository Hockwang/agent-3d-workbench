#!/usr/bin/env python3
"""print-prep 插件的命令行入口。

跑法固定为：`uv run --project <插件根> python <插件根>/scripts/print_prep.py ...`
（插件安装后会被拷进 Codex 的缓存目录，所以这里用"相对本文件"的路径把插件根
加进 `sys.path`，不依赖调用方的当前工作目录）。
"""

from __future__ import annotations

import sys
from pathlib import Path

_PLUGIN_ROOT = Path(__file__).resolve().parent.parent
if str(_PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(_PLUGIN_ROOT))

from print_prep.cli import main  # noqa: E402  (先插 sys.path 再 import)

if __name__ == "__main__":
    sys.exit(main())
