"""`Tasks.resume` (studio/core/tasks.py) re-runs a task's saved `script.py`
byte-for-byte, forever — including tasks saved before the studio/core |
studio/adapters | studio/shell package split. Those old scripts (and a couple
of hand-written templates from that era) still say things like
`from studio.services import run`. `studio/core/task_bootstrap.py` installs a
`sys.meta_path` finder that redirects those flat `studio.<name>` imports to
their new home; this exercises it exactly the way a resumed task would — as a
real subprocess (`--` engine="python" path), not just an in-process import.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_BOOTSTRAP = Path(__file__).resolve().parent.parent / "studio" / "core" / "task_bootstrap.py"


def _run_legacy_script(tmp_path: Path, script_body: str) -> subprocess.CompletedProcess:
    folder = tmp_path / "task"
    (folder / "output").mkdir(parents=True)
    (folder / "request.json").write_text(json.dumps({"engine": "python", "inputs": [], "params": {}}))
    (folder / "script.py").write_text(script_body)
    return subprocess.run(
        [sys.executable, str(_BOOTSTRAP), str(folder)],
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_pre_refactor_flat_imports_still_resolve(tmp_path):
    script = "\n".join(
        [
            "import studio.services",
            "import studio.task_operations",
            "import studio.tasks",
            "import studio.editor",
            "import studio.generated_editing",
            "import studio.observation_run",
            "import studio.assembly_review",
            "import studio.kernels.mechanical_geometry",
            "assert studio.services.__name__ == 'studio.adapters.services'",
            "assert studio.task_operations.__name__ == 'studio.core.task_operations'",
            "assert studio.tasks.__name__ == 'studio.core.tasks'",
            "assert studio.editor.__name__ == 'studio.core.editor'",
            "assert studio.generated_editing.__name__ == 'studio.core.generated_editing'",
            "assert studio.observation_run.__name__ == 'studio.core.observation_run'",
            "assert studio.assembly_review.__name__ == 'studio.core.assembly_review'",
            "assert studio.kernels.mechanical_geometry.__name__ == 'studio.core.kernels.mechanical_geometry'",
            "from studio.services import run",
            "assert callable(run)",
            "from studio.editor import EditorError",
            "assert issubclass(EditorError, Exception)",
        ]
    )
    result = _run_legacy_script(tmp_path, script)
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "task" / "success.json").exists()


def test_unknown_flat_module_still_raises_module_not_found_not_something_else(tmp_path):
    result = _run_legacy_script(tmp_path, "import studio.this_module_never_existed\n")
    assert result.returncode == 1
    assert "ModuleNotFoundError" in result.stderr


def test_pre_rename_shell_kit_import_still_resolves(tmp_path):
    """`studio/shell_kit.py` was renamed to `studio/core/head_shell.py` after the
    "角色头壳制作" feature shipped; a task saved under the old module name must
    keep resuming."""
    script = "\n".join(
        [
            "import studio.shell_kit",
            "assert studio.shell_kit.__name__ == 'studio.core.head_shell'",
            "from studio.shell_kit import shell_kit",
            "assert callable(shell_kit)",
            "assert shell_kit is studio.shell_kit.head_shell",
        ]
    )
    result = _run_legacy_script(tmp_path, script)
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "task" / "success.json").exists()
