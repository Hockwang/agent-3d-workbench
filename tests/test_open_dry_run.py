"""SPEC.md §5 第 6 条：`open --dry-run` 输出的命令正确且没有启动任何进程。"""

from __future__ import annotations

import subprocess

from print_prep import job, profiles


def _bambu_running() -> bool:
    result = subprocess.run(["pgrep", "-x", "BambuStudio"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return result.returncode == 0


def test_open_dry_run_prints_correct_command_and_does_not_launch(tmp_path, run):
    job_dir = tmp_path / "job"
    job_dir.mkdir()
    fake_project = tmp_path / "plate_01.project.3mf"
    fake_project.write_bytes(b"not a real 3mf, dry-run never opens it")

    data = {
        "inspect": {"printer": "Bambu Lab P1S 0.4 nozzle"},
        "export": {"plates": [{"index": 1, "project_3mf": str(fake_project)}]},
    }
    job.save_job(job_dir, data)

    was_running_before = _bambu_running()

    exit_code, payload, _ = run(["open", "--job", str(job_dir), "--plate", "1", "--dry-run"])
    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["loaded"] == "unverified"
    assert payload["launched"] is False

    opened = payload["opened"]
    assert len(opened) == 1
    assert opened[0]["executed"] is False
    expected_cmd = ["open", "-a", str(profiles.app_root()), str(fake_project)]
    assert opened[0]["command"] == expected_cmd

    was_running_after = _bambu_running()
    assert was_running_after == was_running_before, "dry-run 不应该改变 BambuStudio 的运行状态"


def test_open_all_dry_run_covers_every_plate(tmp_path, run):
    job_dir = tmp_path / "job"
    job_dir.mkdir()
    p1 = tmp_path / "plate_01.project.3mf"
    p2 = tmp_path / "plate_02.project.3mf"
    p1.write_bytes(b"x")
    p2.write_bytes(b"x")
    data = {
        "inspect": {"printer": "Bambu Lab P1S 0.4 nozzle"},
        "export": {"plates": [{"index": 1, "project_3mf": str(p1)}, {"index": 2, "project_3mf": str(p2)}]},
    }
    job.save_job(job_dir, data)

    exit_code, payload, _ = run(["open", "--job", str(job_dir), "--all", "--dry-run"])
    assert exit_code == 0
    assert len(payload["opened"]) == 2
    assert all(o["executed"] is False for o in payload["opened"])
