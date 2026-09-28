"""SPEC.md §5 第 8 条：真实端到端（标 `@pytest.mark.bambu`，本机有 Bambu Studio
才跑）。对 5 件真实手办 STL 分别跑 `prepare --shape figurine` 与
`prepare --shape mechanical`（都不带 `--open`），断言工程 3MF 存在、是合法
zip、含 `Metadata/project_settings.config`，并把两条实测结论打印出来。

两臂都要跑的原因（SPEC.md §5 第 8 条）：`figurine` 走 `upright` 朝向策略，五件
的 `print_up` 大多恒为 +Z、旋转矩阵恒为单位阵——测不出 `read_project_transforms`
里 `t_b - R_b @ offset` 这条公式在 `R_b != I` 时是否写对；`mechanical` 走
`flat` 策略，朝向会带真实旋转，这一臂才是对该公式的实证检验。

产物写到 pytest 的 `tmp_path`，不进仓库。
"""

from __future__ import annotations

import os
import sys
import zipfile
from pathlib import Path

import pytest

from print_prep import export3mf, job as job_mod, profiles

# 真实零件在仓外：用环境变量 PRINT_PREP_E2E_PARTS 指向一个装着多个 STL 的目录；没设或目录不在，整组跳过。
_PARTS_ENV = os.environ.get("PRINT_PREP_E2E_PARTS", "")
REAL_PARTS_DIR = Path(_PARTS_ENV).expanduser() if _PARTS_ENV else None
REAL_PART_NAMES = (
    sorted(p.name for p in REAL_PARTS_DIR.glob("*.stl")) if REAL_PARTS_DIR and REAL_PARTS_DIR.is_dir() else []
)

pytestmark = [
    pytest.mark.bambu,
    pytest.mark.skipif(not REAL_PART_NAMES, reason="没有设 PRINT_PREP_E2E_PARTS（仓外的真实零件目录）"),
]


def _bambu_available() -> bool:
    return profiles.bambu_binary().exists()


def _run_prepare(tmp_path, run, shape: str):
    """跑一次 `prepare --shape <shape>`（不带 `--open`），返回
    `(payload, plates, job_dir)`。"""
    files = [str(REAL_PARTS_DIR / name) for name in REAL_PART_NAMES]
    for f in files:
        assert Path(f).exists(), f"缺测试数据: {f}"

    job_dir = tmp_path / f"job_{shape}"
    exit_code, payload, stderr_text = run(["prepare", "--job", str(job_dir), *files, "--shape", shape])

    assert exit_code == 0, f"prepare 失败（shape={shape}）: {payload}"
    assert payload["ok"] is True
    assert payload["print_submitted"] is False

    export_step = next(s for s in payload["steps"] if s["step"] == "export")
    plates = export_step["result"]["plates"]
    assert plates, "至少要有一盘"
    return payload, plates, job_dir


def _verify_plates_not_moved(job_dir: Path, plates: list[dict]) -> list[dict]:
    """对每一盘的工程 3MF 直接调 `export3mf.compare_project_transforms` 重新
    核验（不依赖 `cli.py` 此刻是否已经把 `unmatched_parts` 透传进 plate
    记录），断言：工程 3MF 是合法 zip、含 `Metadata/project_settings.config`、
    没有零件在工程文件里对不上号、Bambu 没有移动任何对象、平移差 < 0.01mm。
    返回每盘的 `compare_project_transforms` 结果供打印诊断用。
    """
    data = job_mod.load_job(job_dir)
    plates_by_index = {p["index"]: p for p in data["arrange"]["plates"]}

    results = []
    for plate in plates:
        project_3mf = plate.get("project_3mf")
        assert project_3mf, f"plate {plate['index']} 没有导出工程 3MF: {plate}"
        project_path = Path(project_3mf)
        assert project_path.exists(), f"工程 3MF 不存在: {project_path}"

        with zipfile.ZipFile(project_path) as z:
            assert z.testzip() is None, f"{project_path} 不是合法 zip"
            names = z.namelist()
            assert "Metadata/project_settings.config" in names, (
                f"{project_path} 里没有 Metadata/project_settings.config，实际内容: {names}"
            )

        placements = plates_by_index[plate["index"]]["placements"]
        compare = export3mf.compare_project_transforms(project_path, placements)
        results.append(compare)

        assert compare["unmatched_parts"] == [], (
            f"plate {plate['index']} 有零件在工程 3MF 里没能对上号: {compare['unmatched_parts']}"
        )
        assert compare["bambu_moved_objects"] is False, f"plate {plate['index']} Bambu 移动了对象: {compare}"
        assert compare["diff"]["max_translation_diff_mm"] < 0.01, (
            f"plate {plate['index']} 平移差超出 0.01mm: {compare['diff']}"
        )
    return results


def _print_conclusions(label: str, plates: list[dict], results: list[dict]) -> None:
    used_fallback_overall = any(bool(p.get("used_slice_fallback")) for p in plates)
    max_translation = max((r["diff"]["max_translation_diff_mm"] for r in results), default=0.0)
    max_rotation = max((r["diff"]["max_rotation_diff"] for r in results), default=0.0)

    print(f"\n=== SPEC.md §5 第 8 条实测结论（{label}） ===", file=sys.stderr)
    if used_fallback_overall:
        print("命令行不切片能否导出工程 3MF: 不能——已自动改用 --slice 0 兜底", file=sys.stderr)
    else:
        print("命令行不切片能否导出工程 3MF: 能，不需要 --slice 兜底", file=sys.stderr)
    print(
        f"Bambu 是否移动了对象: 否（平移差最大 {max_translation:.6f} mm，"
        f"旋转差最大 {max_rotation:.2e}——修正 Bambu 自己的对象居中偏移量 "
        f"`t_b - R_b @ offset` 后，落地变换与我们请求的摆盘变换一致）",
        file=sys.stderr,
    )


@pytest.mark.skipif(not _bambu_available(), reason="本机没有安装 Bambu Studio")
@pytest.mark.skipif(not REAL_PART_NAMES, reason="测试用真实 STL 目录不存在")
def test_prepare_five_real_figurine_parts_end_to_end(tmp_path, run):
    payload, plates, job_dir = _run_prepare(tmp_path, run, "figurine")
    results = _verify_plates_not_moved(job_dir, plates)
    _print_conclusions("figurine，upright 策略，R 恒为单位阵", plates, results)


@pytest.mark.skipif(not _bambu_available(), reason="本机没有安装 Bambu Studio")
@pytest.mark.skipif(not REAL_PART_NAMES, reason="测试用真实 STL 目录不存在")
def test_prepare_five_real_mechanical_parts_end_to_end(tmp_path, run):
    """`--shape mechanical` 走 `flat` 朝向策略，朝向会带真实旋转——这一臂才是
    对读回公式 `t_b - R_b @ offset` 的实证检验（`figurine` 那臂 R 恒为单位
    阵，测不出 `R_b != I` 时的偏差）。"""
    payload, plates, job_dir = _run_prepare(tmp_path, run, "mechanical")
    results = _verify_plates_not_moved(job_dir, plates)
    _print_conclusions("mechanical，flat 策略，带真实旋转", plates, results)
