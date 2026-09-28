"""studio.paths —— 唯一知道目录树长什么样的地方。

包里所有 `Path(__file__)...` 相对路径推导都改从这里取常量：新增/挪动一个顶层
目录时只改这一份文件，不用满仓找 `__file__` 拼接。除了 `task_worker.py` /
`task_bootstrap.py` 里那两个在 `studio` 包可 import 之前就要跑的 `sys.path`
自举（它们用 `Path(__file__).resolve().parents[N]` 直接算仓库根，不能依赖
这个模块），其余所有 `Path(__file__)` 用法都应该换成这里的常量。
"""

from __future__ import annotations

from pathlib import Path

# studio/paths.py 本身在 studio/ 下，PLUGIN_ROOT 是仓库根（studio/ 的上一级）。
PLUGIN_ROOT: Path = Path(__file__).resolve().parent.parent

STUDIO_DIR: Path = PLUGIN_ROOT / "studio"
CORE_DIR: Path = STUDIO_DIR / "core"
ADAPTERS_DIR: Path = STUDIO_DIR / "adapters"
SHELL_DIR: Path = STUDIO_DIR / "shell"

WEB_DIR: Path = STUDIO_DIR / "web"
APP_DIR: Path = STUDIO_DIR / "app"
APP_DIST_DIR: Path = APP_DIR / "dist"
CITY_DIR: Path = STUDIO_DIR / "city"

KERNELS_DIR: Path = CORE_DIR / "kernels"

RECIPES_DIR: Path = PLUGIN_ROOT / "recipes"
SCRIPTS_DIR: Path = PLUGIN_ROOT / "scripts"
PRINT_PREP_DIR: Path = PLUGIN_ROOT / "print_prep"
