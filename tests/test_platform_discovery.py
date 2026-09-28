"""Cross-platform discovery for Bambu Studio / Blender: darwin / win32 / linux
dispatch, including the "tool not found" -> clear error path. These monkeypatch
`sys.platform` (the real interpreter never changes OS mid-test) and environment
variables; nothing here touches the real filesystem beyond `tmp_path`.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from print_prep import bambu, profiles
from studio.core import tasks
from studio.core.editor import EditorError

# ---------------------------------------------------------------------------
# print_prep.profiles: app_root / bambu_binary / profile_root
# ---------------------------------------------------------------------------


def test_app_root_env_var_always_wins(monkeypatch):
    monkeypatch.setenv("BAMBU_STUDIO_APP", "/custom/path/BambuStudio")
    assert profiles.app_root() == Path("/custom/path/BambuStudio")


def test_app_root_darwin_default(monkeypatch):
    monkeypatch.delenv("BAMBU_STUDIO_APP", raising=False)
    monkeypatch.setattr(profiles.sys, "platform", "darwin")
    assert profiles.app_root() == Path(profiles.DEFAULT_APP)


def test_app_root_windows_prefers_an_existing_candidate(monkeypatch, tmp_path):
    monkeypatch.delenv("BAMBU_STUDIO_APP", raising=False)
    monkeypatch.setattr(profiles.sys, "platform", "win32")
    program_files = tmp_path / "Program Files"
    exe = program_files / "Bambu Studio" / "bambu-studio.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"")
    monkeypatch.setenv("ProgramFiles", str(program_files))
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    assert profiles.app_root() == exe


def test_app_root_windows_falls_back_to_a_best_guess_when_nothing_installed(monkeypatch, tmp_path):
    monkeypatch.delenv("BAMBU_STUDIO_APP", raising=False)
    monkeypatch.setattr(profiles.sys, "platform", "win32")
    program_files = tmp_path / "Program Files"
    monkeypatch.setenv("ProgramFiles", str(program_files))
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    assert profiles.app_root() == program_files / "Bambu Studio" / "bambu-studio.exe"


def test_app_root_windows_checks_local_appdata_too(monkeypatch, tmp_path):
    monkeypatch.delenv("BAMBU_STUDIO_APP", raising=False)
    monkeypatch.setattr(profiles.sys, "platform", "win32")
    program_files = tmp_path / "Program Files"
    monkeypatch.setenv("ProgramFiles", str(program_files))
    local_appdata = tmp_path / "AppData" / "Local"
    exe = local_appdata / "Programs" / "Bambu Studio" / "bambu-studio.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"")
    monkeypatch.setenv("LOCALAPPDATA", str(local_appdata))
    assert profiles.app_root() == exe


def test_app_root_linux_uses_path_lookup(monkeypatch):
    monkeypatch.delenv("BAMBU_STUDIO_APP", raising=False)
    monkeypatch.setattr(profiles.sys, "platform", "linux")
    monkeypatch.setattr(
        profiles.shutil, "which", lambda name: "/usr/bin/bambu-studio" if name == "bambu-studio" else None
    )
    assert profiles.app_root() == Path("/usr/bin/bambu-studio")


def test_app_root_linux_falls_back_to_local_bin_when_not_on_path(monkeypatch):
    monkeypatch.delenv("BAMBU_STUDIO_APP", raising=False)
    monkeypatch.setattr(profiles.sys, "platform", "linux")
    monkeypatch.setattr(profiles.shutil, "which", lambda name: None)
    assert profiles.app_root() == Path.home() / ".local" / "bin" / "bambu-studio"


def test_bambu_binary_env_var_wins(monkeypatch):
    monkeypatch.setenv("BAMBU_STUDIO_PATH", "/custom/bambu-studio")
    assert profiles.bambu_binary() == Path("/custom/bambu-studio")


def test_bambu_binary_darwin_is_inside_the_app_bundle(monkeypatch):
    monkeypatch.delenv("BAMBU_STUDIO_PATH", raising=False)
    monkeypatch.setenv("BAMBU_STUDIO_APP", "/Applications/BambuStudio.app")
    monkeypatch.setattr(profiles.sys, "platform", "darwin")
    assert profiles.bambu_binary() == Path("/Applications/BambuStudio.app/Contents/MacOS/BambuStudio")


def test_bambu_binary_windows_is_app_root_itself(monkeypatch):
    monkeypatch.delenv("BAMBU_STUDIO_PATH", raising=False)
    monkeypatch.setenv("BAMBU_STUDIO_APP", "C:/Bambu Studio/bambu-studio.exe")
    monkeypatch.setattr(profiles.sys, "platform", "win32")
    assert profiles.bambu_binary() == Path("C:/Bambu Studio/bambu-studio.exe")


def test_profile_root_env_var_wins(monkeypatch):
    monkeypatch.setenv("MFG_BAMBU_PROFILE_ROOT", "/custom/profiles")
    assert profiles.profile_root() == Path("/custom/profiles")


def test_profile_root_darwin_default_is_inside_the_app_bundle(monkeypatch):
    monkeypatch.delenv("MFG_BAMBU_PROFILE_ROOT", raising=False)
    monkeypatch.setenv("BAMBU_STUDIO_APP", "/Applications/BambuStudio.app")
    monkeypatch.setattr(profiles.sys, "platform", "darwin")
    assert profiles.profile_root() == Path("/Applications/BambuStudio.app/Contents/Resources/profiles/BBL")


def test_profile_root_windows_default_uses_appdata(monkeypatch):
    monkeypatch.delenv("MFG_BAMBU_PROFILE_ROOT", raising=False)
    monkeypatch.setattr(profiles.sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", "C:/Users/test/AppData/Roaming")
    assert profiles.profile_root() == Path("C:/Users/test/AppData/Roaming/BambuStudio/system/BBL")


def test_profile_root_linux_default_uses_dot_config(monkeypatch):
    monkeypatch.delenv("MFG_BAMBU_PROFILE_ROOT", raising=False)
    monkeypatch.setattr(profiles.sys, "platform", "linux")
    assert profiles.profile_root() == Path.home() / ".config" / "BambuStudio" / "system" / "BBL"


def test_missing_profile_root_raises_a_clear_error_not_a_bare_exception(monkeypatch, tmp_path):
    monkeypatch.setenv("MFG_BAMBU_PROFILE_ROOT", str(tmp_path / "does-not-exist"))
    with pytest.raises(profiles.ProfileError, match="does-not-exist"):
        profiles.list_printers()


# ---------------------------------------------------------------------------
# print_prep.bambu: _launch_command / open_project / is_process_running / wait_for_process
# ---------------------------------------------------------------------------


def test_launch_command_darwin_uses_open_dash_a(monkeypatch, tmp_path):
    monkeypatch.setattr(bambu.sys, "platform", "darwin")
    app = tmp_path / "BambuStudio.app"
    project = tmp_path / "plate.3mf"
    assert bambu._launch_command(app, project) == ["open", "-a", str(app), str(project)]


def test_launch_command_windows_uses_the_exe_directly_when_found(monkeypatch, tmp_path):
    monkeypatch.setattr(bambu.sys, "platform", "win32")
    exe = tmp_path / "bambu-studio.exe"
    exe.write_bytes(b"")
    project = tmp_path / "plate.3mf"
    assert bambu._launch_command(exe, project) == [str(exe), str(project)]


def test_launch_command_windows_falls_back_to_os_startfile_when_exe_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(bambu.sys, "platform", "win32")
    missing = tmp_path / "does-not-exist.exe"
    project = tmp_path / "plate.3mf"
    assert bambu._launch_command(missing, project) == ["os.startfile", str(project)]


def test_launch_command_linux_uses_the_binary_when_found(monkeypatch, tmp_path):
    monkeypatch.setattr(bambu.sys, "platform", "linux")
    exe = tmp_path / "bambu-studio"
    exe.write_bytes(b"")
    project = tmp_path / "plate.3mf"
    assert bambu._launch_command(exe, project) == [str(exe), str(project)]


def test_launch_command_linux_falls_back_to_xdg_open(monkeypatch, tmp_path):
    monkeypatch.setattr(bambu.sys, "platform", "linux")
    missing = tmp_path / "does-not-exist"
    project = tmp_path / "plate.3mf"
    assert bambu._launch_command(missing, project) == ["xdg-open", str(project)]


def test_open_project_windows_fallback_uses_os_startfile_not_subprocess(monkeypatch, tmp_path):
    monkeypatch.setattr(bambu.sys, "platform", "win32")
    calls = []
    monkeypatch.setattr(bambu.os, "startfile", lambda path: calls.append(path), raising=False)
    monkeypatch.setattr(
        bambu.subprocess, "run", lambda *a, **k: pytest.fail("must not shell out when using os.startfile")
    )
    missing = tmp_path / "does-not-exist.exe"
    project = tmp_path / "plate.3mf"
    result = bambu.open_project(missing, project)
    assert result == {"command": ["os.startfile", str(project)], "executed": True}
    assert calls == [str(project)]


def test_open_project_darwin_still_uses_blocking_subprocess_run(monkeypatch, tmp_path):
    # `open -a` returns as soon as launchd accepts the request; the darwin
    # path must stay byte-identical to before the detached-Popen fix.
    monkeypatch.setattr(bambu.sys, "platform", "darwin")
    calls = []
    monkeypatch.setattr(bambu.subprocess, "run", lambda cmd, **kwargs: calls.append((cmd, kwargs)))
    monkeypatch.setattr(bambu.subprocess, "Popen", lambda *a, **k: pytest.fail("darwin must not switch to Popen"))
    app = tmp_path / "BambuStudio.app"
    project = tmp_path / "plate.3mf"
    result = bambu.open_project(app, project)
    assert result == {"command": ["open", "-a", str(app), str(project)], "executed": True}
    assert calls == [(["open", "-a", str(app), str(project)], {"check": False})]


def test_open_project_windows_uses_a_detached_popen_and_returns_immediately(monkeypatch, tmp_path):
    monkeypatch.setattr(bambu.sys, "platform", "win32")
    monkeypatch.setattr(bambu.subprocess, "run", lambda *a, **k: pytest.fail("must not block on the GUI process"))
    calls = []

    class _FakePopen:
        def __init__(self, cmd, **kwargs):
            calls.append((cmd, kwargs))

    monkeypatch.setattr(bambu.subprocess, "Popen", _FakePopen)
    exe = tmp_path / "bambu-studio.exe"
    exe.write_bytes(b"")
    project = tmp_path / "plate.3mf"
    result = bambu.open_project(exe, project)
    assert result == {"command": [str(exe), str(project)], "executed": True}
    assert len(calls) == 1
    cmd, kwargs = calls[0]
    assert cmd == [str(exe), str(project)]
    assert kwargs["stdin"] is bambu.subprocess.DEVNULL
    assert kwargs["stdout"] is bambu.subprocess.DEVNULL
    assert kwargs["stderr"] is bambu.subprocess.DEVNULL
    assert kwargs["creationflags"] == bambu._WIN_DETACHED_PROCESS | bambu._WIN_CREATE_NEW_PROCESS_GROUP


def test_open_project_linux_uses_a_detached_popen_with_start_new_session(monkeypatch, tmp_path):
    monkeypatch.setattr(bambu.sys, "platform", "linux")
    monkeypatch.setattr(bambu.subprocess, "run", lambda *a, **k: pytest.fail("must not block on the GUI process"))
    calls = []

    class _FakePopen:
        def __init__(self, cmd, **kwargs):
            calls.append((cmd, kwargs))

    monkeypatch.setattr(bambu.subprocess, "Popen", _FakePopen)
    exe = tmp_path / "bambu-studio"
    exe.write_bytes(b"")
    project = tmp_path / "plate.3mf"
    result = bambu.open_project(exe, project)
    assert result == {"command": [str(exe), str(project)], "executed": True}
    assert len(calls) == 1
    cmd, kwargs = calls[0]
    assert cmd == [str(exe), str(project)]
    assert kwargs["start_new_session"] is True


def test_default_process_name_stays_bambustudio_on_darwin(monkeypatch):
    monkeypatch.setattr(bambu.sys, "platform", "darwin")
    assert bambu._default_process_name() == "BambuStudio"


def test_default_process_name_is_the_discovered_exe_on_windows(monkeypatch, tmp_path):
    monkeypatch.setattr(bambu.sys, "platform", "win32")
    monkeypatch.delenv("BAMBU_STUDIO_PATH", raising=False)
    monkeypatch.setenv("BAMBU_STUDIO_APP", str(tmp_path / "Bambu Studio" / "bambu-studio.exe"))
    assert bambu._default_process_name() == "bambu-studio.exe"


def test_default_process_name_is_the_discovered_binary_on_linux(monkeypatch):
    monkeypatch.setattr(bambu.sys, "platform", "linux")
    monkeypatch.delenv("BAMBU_STUDIO_PATH", raising=False)
    monkeypatch.setenv("BAMBU_STUDIO_APP", "/usr/bin/bambu-studio")
    assert bambu._default_process_name() == "bambu-studio"


def test_is_process_running_defaults_to_the_platform_correct_process_name(monkeypatch):
    monkeypatch.setattr(bambu.sys, "platform", "linux")
    monkeypatch.setattr(bambu, "_default_process_name", lambda: "bambu-studio")
    seen = {}

    def fake_run(cmd, **kwargs):
        seen["name"] = cmd[-1]
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(bambu.subprocess, "run", fake_run)
    assert bambu.is_process_running() is True
    assert seen["name"] == "bambu-studio"


def test_is_process_running_windows_parses_tasklist_hit(monkeypatch):
    monkeypatch.setattr(bambu.sys, "platform", "win32")

    def fake_run(cmd, **kwargs):
        assert cmd[0] == "tasklist"
        return subprocess.CompletedProcess(
            cmd, 0, stdout="Image Name                     PID\nBambuStudio.exe            1234\n"
        )

    monkeypatch.setattr(bambu.subprocess, "run", fake_run)
    assert bambu.is_process_running("BambuStudio") is True


def test_is_process_running_windows_parses_tasklist_miss(monkeypatch):
    monkeypatch.setattr(bambu.sys, "platform", "win32")

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(
            cmd, 0, stdout="INFO: No tasks are running which match the specified criteria.\n"
        )

    monkeypatch.setattr(bambu.subprocess, "run", fake_run)
    assert bambu.is_process_running("BambuStudio") is False


def test_is_process_running_returns_none_when_the_platform_tool_is_missing(monkeypatch):
    monkeypatch.setattr(bambu.sys, "platform", "linux")

    def fake_run(cmd, **kwargs):
        raise OSError("no such file or directory: 'pgrep'")

    monkeypatch.setattr(bambu.subprocess, "run", fake_run)
    assert bambu.is_process_running("BambuStudio") is None


def test_wait_for_process_stops_immediately_on_unknown_instead_of_spinning(monkeypatch):
    calls = {"n": 0}

    def fake_is_running(name):
        calls["n"] += 1
        return None

    monkeypatch.setattr(bambu, "is_process_running", fake_is_running)
    assert bambu.wait_for_process(timeout_s=5, poll_s=0.01) is None
    assert calls["n"] == 1


# ---------------------------------------------------------------------------
# studio.core.tasks: blender_path
# ---------------------------------------------------------------------------


def test_blender_path_env_var_wins_over_any_platform_default(monkeypatch, tmp_path):
    exe = tmp_path / "my-blender"
    exe.write_bytes(b"")
    monkeypatch.setenv("WORKBENCH_BLENDER", str(exe))
    assert tasks.blender_path() == str(exe.resolve())


def test_blender_path_windows_picks_the_newest_version(monkeypatch, tmp_path):
    monkeypatch.delenv("WORKBENCH_BLENDER", raising=False)
    monkeypatch.setattr(tasks.sys, "platform", "win32")
    program_files = tmp_path / "Program Files"
    for version in ("3.6", "4.1", "4.10", "4.2"):
        version_dir = program_files / "Blender Foundation" / f"Blender {version}"
        version_dir.mkdir(parents=True)
        (version_dir / "blender.exe").write_bytes(b"")
    monkeypatch.setenv("ProgramFiles", str(program_files))
    expected = program_files / "Blender Foundation" / "Blender 4.10" / "blender.exe"
    assert tasks.blender_path() == str(expected.resolve())


def test_blender_path_linux_uses_path_lookup(monkeypatch, tmp_path):
    monkeypatch.delenv("WORKBENCH_BLENDER", raising=False)
    monkeypatch.setattr(tasks.sys, "platform", "linux")
    exe = tmp_path / "blender"
    exe.write_bytes(b"")
    monkeypatch.setattr(tasks.shutil, "which", lambda name: str(exe) if name == "blender" else None)
    assert tasks.blender_path() == str(exe.resolve())


def test_blender_path_returns_none_when_nothing_is_found(monkeypatch):
    monkeypatch.delenv("WORKBENCH_BLENDER", raising=False)
    monkeypatch.setattr(tasks.sys, "platform", "linux")
    monkeypatch.setattr(tasks.shutil, "which", lambda name: None)
    assert tasks.blender_path() is None


def test_task_start_raises_a_clear_error_naming_workbench_blender_when_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(tasks, "blender_path", lambda: None)
    store = tasks.Tasks(tmp_path / "tasks")
    with pytest.raises(EditorError, match="WORKBENCH_BLENDER"):
        store.start({"engine": "blender", "script": "pass"}, "human")
