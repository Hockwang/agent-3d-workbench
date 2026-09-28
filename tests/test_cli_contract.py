"""SPEC.md §5 第 12 条：命令行契约。

- argparse 自身的解析错误（未知子命令 / 无子命令 / 非法枚举值 / 未注册的参数）
  必须也走 SPEC.md §3 的统一 JSON 输出：stdout 恰好一个 JSON 对象、退出码 2、
  `error.code == "bad_arguments"`。
- `--scale <= 0`、`--gap < 0`、`orient --set NAME=0,0,0`（零向量）分别在各自命令
  内部校验，同样退出码 2（但各有更具体的 `error.code`）。
- `-h`/`--help` 不受影响：退出码 0，走 argparse 自己的帮助文本（不是 JSON）。

另外顺带覆盖两条相关缺陷的回归（都在 `export --no-project` 产出上验证）：
写盘的 `profiles/*.json` 不能带任何下划线开头的内部键；三处 STL 载入点必须按
位置合并顶点（3MF 里写出的顶点数应该远小于面数乘 3，不是"没合并"的老样子）。
"""

from __future__ import annotations

import json

import numpy as np
import trimesh

from print_prep import job as job_mod
from print_prep.cli import main as cli_main

from .conftest import write_box_stl


def _assert_bad_arguments(run, args: list[str]) -> dict:
    exit_code, payload, _ = run(args)
    assert exit_code == 2
    assert payload["ok"] is False
    assert payload["error"]["code"] == "bad_arguments"
    return payload


def test_unknown_subcommand_emits_json_and_exit_2(run):
    _assert_bad_arguments(run, ["frobnicate"])


def test_missing_subcommand_emits_json_and_exit_2(run):
    _assert_bad_arguments(run, [])


def test_bad_mode_choice_emits_json_and_exit_2(tmp_path, run):
    # choices 校验发生在 argparse 解析阶段，不需要 job 目录真的跑过前置步骤。
    _assert_bad_arguments(run, ["arrange", "--job", str(tmp_path / "job"), "--mode", "bogus"])


def test_prepare_does_not_accept_bare_set_flag(tmp_path, run):
    # `prepare` 只认 `--orient-set`/`--export-set`，裸的 `--set` 对它来说是未注册
    # 的参数——argparse 的"unrecognized arguments"分支，同样要落成 JSON。
    box_path = write_box_stl(tmp_path, "box1", (10, 10, 10))
    _assert_bad_arguments(run, ["prepare", "--job", str(tmp_path / "job"), str(box_path), "--set", "a=b"])


def test_help_exits_zero_and_is_not_forced_into_json(capsys):
    # `-h`/`--help` 走 argparse 自己的帮助文本分支，不应该被我们的 JSON 包装
    # 影响；不能用 `run` fixture（它断言 stdout 只有一个 JSON 对象）。
    exit_code = cli_main(["--help"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "usage" in captured.out.lower()


def test_negative_scale_rejected(tmp_path, run):
    box_path = write_box_stl(tmp_path, "box1", (10, 10, 10))
    exit_code, payload, _ = run(["inspect", "--job", str(tmp_path / "job"), str(box_path), "--scale", "-2"])
    assert exit_code == 2
    assert payload["ok"] is False
    assert payload["error"]["code"] == "bad_scale"


def test_zero_scale_rejected(tmp_path, run):
    box_path = write_box_stl(tmp_path, "box1", (10, 10, 10))
    exit_code, payload, _ = run(["inspect", "--job", str(tmp_path / "job"), str(box_path), "--scale", "0"])
    assert exit_code == 2
    assert payload["ok"] is False
    assert payload["error"]["code"] == "bad_scale"


def test_negative_gap_rejected(tmp_path, run):
    box_path = write_box_stl(tmp_path, "box1", (10, 10, 10))
    job_dir = tmp_path / "job"
    exit_code, _, _ = run(["inspect", "--job", str(job_dir), str(box_path)])
    assert exit_code == 0
    exit_code, _, _ = run(["orient", "--job", str(job_dir)])
    assert exit_code == 0

    exit_code, payload, _ = run(["arrange", "--job", str(job_dir), "--gap", "-5"])
    assert exit_code == 2
    assert payload["ok"] is False
    assert payload["error"]["code"] == "bad_gap"


def test_orient_zero_vector_rejected(tmp_path, run):
    box_path = write_box_stl(tmp_path, "box1", (10, 10, 10))
    job_dir = tmp_path / "job"
    exit_code, _, _ = run(["inspect", "--job", str(job_dir), str(box_path)])
    assert exit_code == 0

    exit_code, payload, _ = run(["orient", "--job", str(job_dir), "--set", "x=0,0,0"])
    assert exit_code == 2
    assert payload["ok"] is False
    assert payload["error"]["code"] == "zero_vector"


def _write_inverted_cone_stl(path) -> None:
    """尖朝下、底面朝上的圆锥（半角 atan(15/30)≈26.57°）：侧面每个面法向与
    "正朝下" 的夹角恒为 90°-26.57°≈63.43°（圆锥侧面斜率处处相同），所以在
    up=(0,0,1) 时 `overhang_area_mm2` 只有两档——angle_deg<=63 时 0（侧面
    整体被判定为"没那么朝下"），angle_deg>=64 时约等于整个侧面积——很适合用
    来验证 --angle-deg 真的改变了判定，而不是数值上的量变。"""
    cone = trimesh.creation.cone(radius=15.0, height=30.0, sections=48)
    cone.apply_transform(trimesh.transformations.rotation_matrix(np.pi, [1.0, 0.0, 0.0]))
    cone.export(path, file_type="stl")


def test_angle_deg_out_of_range_rejected(tmp_path, run):
    box_path = write_box_stl(tmp_path, "box1", (10, 10, 10))
    job_dir = tmp_path / "job"
    exit_code, _, _ = run(["inspect", "--job", str(job_dir), str(box_path)])
    assert exit_code == 0

    exit_code, payload, _ = run(["orient", "--job", str(job_dir), "--angle-deg", "3"])
    assert exit_code == 2
    assert payload["ok"] is False
    assert payload["error"]["code"] == "bad_angle_deg"

    exit_code, payload, _ = run(["orient", "--job", str(job_dir), "--angle-deg", "90"])
    assert exit_code == 2
    assert payload["ok"] is False
    assert payload["error"]["code"] == "bad_angle_deg"


def test_angle_deg_override_changes_result_and_is_recorded(tmp_path, run):
    cone_path = tmp_path / "cone.stl"
    _write_inverted_cone_stl(cone_path)
    job_dir = tmp_path / "job"
    exit_code, _, _ = run(["inspect", "--job", str(job_dir), str(cone_path)])
    assert exit_code == 0

    exit_code, tight, _ = run(["orient", "--job", str(job_dir), "--set", "cone=0,0,1", "--angle-deg", "60"])
    assert exit_code == 0
    assert tight["angle_deg"] == 60.0
    assert tight["parts"]["cone"]["overhang_area_mm2"] == 0.0

    exit_code, loose, _ = run(["orient", "--job", str(job_dir), "--set", "cone=0,0,1", "--angle-deg", "70"])
    assert exit_code == 0
    assert loose["angle_deg"] == 70.0
    assert loose["parts"]["cone"]["overhang_area_mm2"] > 1000.0

    # job.json 记的是最近一次 orient 用的 angle_deg（additive key）。
    data = job_mod.load_job(job_dir)
    assert data["orient"]["angle_deg"] == 70.0


def test_angle_deg_defaults_to_printer_profile_value(tmp_path, run):
    # 没有 --angle-deg 时走 printer profile 的 overhang_angle_deg（当前所有
    # 打印机都是 DEFAULT_OVERHANG_ANGLE_DEG=30），最终等于 orient.DEFAULT_ANGLE_DEG。
    box_path = write_box_stl(tmp_path, "box1", (10, 10, 10))
    job_dir = tmp_path / "job"
    exit_code, _, _ = run(["inspect", "--job", str(job_dir), str(box_path)])
    assert exit_code == 0

    exit_code, payload, _ = run(["orient", "--job", str(job_dir)])
    assert exit_code == 0
    assert payload["angle_deg"] == 30.0


def test_export_profiles_have_no_internal_underscore_keys_and_stl_vertices_are_merged(tmp_path, run):
    """SPEC.md §5 第 12 条附带覆盖的两个缺陷：
    1. `profiles/*.json` 写盘前必须去掉 `_source_path` 这类内部键。
    2. 三处 STL 载入点必须按位置合并顶点——一个 12 面的盒子合并后应该是 8 个
       顶点，不是未合并时的 36 个（12 * 3）。这里通过 `export` 的几何 3MF 读回
       结果（`readback.parts[name].n_vertices`，是文件里实际写出的顶点数）来看。
    """
    box_path = write_box_stl(tmp_path, "box1", (10, 10, 10))
    job_dir = tmp_path / "job"

    exit_code, _, _ = run(["inspect", "--job", str(job_dir), str(box_path)])
    assert exit_code == 0
    exit_code, _, _ = run(["orient", "--job", str(job_dir), "--strategy", "flat"])
    assert exit_code == 0
    exit_code, _, _ = run(["arrange", "--job", str(job_dir)])
    assert exit_code == 0

    exit_code, payload, _ = run(["export", "--job", str(job_dir), "--no-project"])
    assert exit_code == 0

    profiles_dir = job_dir / "profiles"
    for name in ("machine.json", "process.json", "filament-0.json"):
        data = json.loads((profiles_dir / name).read_text())
        underscore_keys = [k for k in data if k.startswith("_")]
        assert underscore_keys == [], f"{name} 里不该有内部键: {underscore_keys}"

    plate = payload["plates"][0]
    part_info = plate["readback"]["parts"]["box1"]
    # 12 个三角面：未合并会是 36 个顶点，合并后一个盒子应该只有 8 个。
    assert part_info["n_faces"] == 12
    assert part_info["n_vertices"] < 3 * part_info["n_faces"]
    assert part_info["n_vertices"] <= 8
