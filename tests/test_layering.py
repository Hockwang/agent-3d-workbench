"""Walks the source tree and enforces the layer rule from `docs/ARCHITECTURE.md`
("Package layout"): `studio.core` must not depend on `studio.adapters` or
`studio.shell`; `studio.adapters` must not depend on `studio.shell`; `print_prep`
must not depend on `studio` at all; and nothing outside `studio.shell` should
reach for the `mcp` SDK, `studio.shell.tools_schema`, or `studio.shell.codex_bridge`
directly (those are the wire-contract layer).

Both module-level and function-level imports are collected (`ast.walk` does not
care about nesting), since most of the cross-layer calls in this codebase are
deliberately deferred imports inside a function body to avoid import cycles.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

# (importing module, imported name) -> why this one specific cross-layer import
# is left in place rather than fixed by parameter injection. Each entry must
# still show up in a fresh scan, or it is stale and should be deleted.
KNOWN_VIOLATIONS: set[tuple[str, str]] = {
    (
        "studio.core.projects",
        "studio.shell.mcp_server",
    ),  # open_project() joins collaboration on the project's own locally-running
    # HTTP server via mcp_server._call_http; this is a loopback call to a server
    # this same process may have just started, not a "hosted adapter" in the
    # studio.adapters sense. Untangling it needs `open_project` (three call
    # sites, one of them itself inside studio.core.projects) to take an HTTP
    # caller as an injected parameter — a real signature change, not a
    # one-line fix, so it is left as a documented violation for now.
    (
        "studio.core.tasks",
        "studio.adapters.services",
    ),  # Tasks.capabilities() surfaces the hosted-service catalog and
    # Tasks.start() can queue a task whose body dispatches to a hosted
    # adapter — the local task queue intentionally knows optional hosted
    # services exist. `Tasks` is instantiated from several places
    # (studio/shell/server.py, scripts/, tests/); threading a services-lookup
    # dependency through its constructor is a real DI refactor, not a
    # one-line fix, so it is left as a documented violation for now.
}


def _iter_py_files(*dirs: Path) -> list[Path]:
    files: list[Path] = []
    for d in dirs:
        files.extend(sorted(p for p in d.rglob("*.py") if "__pycache__" not in p.parts))
    return files


def _module_name(path: Path) -> str:
    rel = path.relative_to(REPO_ROOT).with_suffix("")
    parts = rel.parts
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _imported_names(path: Path) -> set[str]:
    """Every module dotted-path this file imports, from any depth of nesting."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                names.add(node.module)
    return names


def _starts_with_any(name: str, prefixes: tuple[str, ...]) -> bool:
    return any(name == prefix or name.startswith(prefix + ".") for prefix in prefixes)


CORE_DIR = REPO_ROOT / "studio" / "core"
ADAPTERS_DIR = REPO_ROOT / "studio" / "adapters"
SHELL_DIR = REPO_ROOT / "studio" / "shell"
PRINT_PREP_DIR = REPO_ROOT / "print_prep"


def _collect_violations() -> list[tuple[str, str, str]]:
    """Returns a list of (module, imported_name, rule) for anything that
    breaks the layer rule and is not in KNOWN_VIOLATIONS."""
    violations: list[tuple[str, str, str]] = []

    def check(files: list[Path], forbidden: tuple[str, ...], rule: str):
        for path in files:
            module = _module_name(path)
            for name in _imported_names(path):
                if _starts_with_any(name, forbidden) and (module, name) not in KNOWN_VIOLATIONS:
                    violations.append((module, name, rule))

    check(_iter_py_files(CORE_DIR), ("studio.adapters", "studio.shell"), "core -> adapters/shell")
    check(_iter_py_files(ADAPTERS_DIR), ("studio.shell",), "adapters -> shell")
    check(_iter_py_files(PRINT_PREP_DIR), ("studio",), "print_prep -> studio")
    check(
        _iter_py_files(CORE_DIR, ADAPTERS_DIR, PRINT_PREP_DIR),
        ("mcp", "studio.shell.tools_schema", "studio.shell.codex_bridge"),
        "non-shell -> wire-contract layer (mcp / tools_schema / codex_bridge)",
    )
    return violations


def test_layer_boundaries_hold():
    violations = _collect_violations()
    assert not violations, "cross-layer imports outside KNOWN_VIOLATIONS:\n" + "\n".join(
        f"  {module} imports {name} ({rule})" for module, name, rule in violations
    )


def test_known_violations_are_still_present():
    """A KNOWN_VIOLATIONS entry that no longer triggers is stale — delete it
    instead of leaving a silent allowance nobody understands anymore."""
    all_names: dict[str, set[str]] = {}
    for path in _iter_py_files(CORE_DIR, ADAPTERS_DIR, SHELL_DIR, PRINT_PREP_DIR):
        all_names[_module_name(path)] = _imported_names(path)

    stale = [
        (module, name) for module, name in KNOWN_VIOLATIONS if module not in all_names or name not in all_names[module]
    ]
    assert not stale, f"stale KNOWN_VIOLATIONS entries (no longer import this): {stale}"


@pytest.mark.parametrize("layer_dir", [CORE_DIR, ADAPTERS_DIR, SHELL_DIR])
def test_layer_packages_exist(layer_dir: Path):
    assert (layer_dir / "__init__.py").is_file()
