"""print_prep.orient —— 选朝向（哪个方向朝上打印）。

候选生成 / 打分改编自作者早期私有研究代码 `manufacturing_kit/engine/print_waveab_v0/kitlib/plate.py`
的 `_planar_patch_normals`/`choose_print_up`（自有代码），扩成 SPEC.md §3.3 要求
的 flat/support/upright/auto 四种策略 + 悬空面积的"法向直方图"快路径。

性能设计：真正贵的是"给候选方向逐面判断悬空"这一步——`support` 策略会加 200
个斐波那契球面方向，如果对每个候选都对全部面做一次 `face_normals @ (-up)`，
200 万面 x 200+ 候选会是上亿次浮点运算还要重复很多次。做法是先把面法向按约
1 度分箱、一次性把每个箱子的面积累加好（"法向直方图"，只需要遍历一次全部面），
后面每个候选只需要对箱子（数量远小于面数）求和就能得到一个悬空面积的近似值；
拿这个近似值给候选排序，只对近似分数最好的 12 个候选再做一次逐面精确计算
（贴床接触面积、精确悬空面积、高度——这些需要按候选方向重新投影顶点，只在
候选数收窄到 12 个之后才做得起）。

SPEC.md §3.3（修订）：这个预筛**只作用于斐波那契球面候选**。大平面片法向与
六个坐标轴数量少（通常几十个）且"大平底朝下"恰恰是悬空近似算法算出来最差
的那个方向（贴床面本身就会被直方图记成一大块"悬空"，因为直方图不排除贴床
面）——如果把预筛也套在它们头上，会把正确答案筛掉（见 gotcha：12 边棱柱
`flat` 曾经被筛成侧面朝下）。所以大平面片 + 六坐标轴无条件进入精确评估，只
有斐波那契候选会被近似值预筛到 12 个。
"""

from __future__ import annotations

from typing import Any, Optional, Sequence

import numpy as np
import trimesh

from .messages import render

AXES6 = [
    np.array([1.0, 0.0, 0.0]),
    np.array([-1.0, 0.0, 0.0]),
    np.array([0.0, 1.0, 0.0]),
    np.array([0.0, -1.0, 0.0]),
    np.array([0.0, 0.0, 1.0]),
    np.array([0.0, 0.0, -1.0]),
]

DEFAULT_ANGLE_DEG = 30.0
DEFAULT_BASE_MARGIN_MM = 0.05
DEFAULT_MIN_AREA_SHARE = 0.03
DEFAULT_ANGLE_TOL_DEG = 1.0
DEFAULT_TOP_K = 12
DEFAULT_N_FIBONACCI = 200

# "贴床接触面" = 离最低点 tol_mm 以内 **且** 朝下的面；自有阈值：法向与 -up 的
# 夹角要小于 45 度才算"朝下"，避免把贴着地面的竖直墙面也计进接触面积。
CONTACT_DOWN_COS_THRESHOLD = 0.70710678  # cos(45deg)

# SPEC.md §3.3：贴床面积不到这个值的候选/结果视为"不稳"。support 策略只在
# 稳定候选里挑悬空最小的；upright 只有当 +Z 不稳且存在稳定候选时才退让。
STABLE_CONTACT_MM2 = 20.0


def unit(v) -> np.ndarray:
    v = np.asarray(v, dtype=float)
    n = np.linalg.norm(v)
    if n < 1e-12:
        raise ValueError(render("orient.zero_vector", v=v))
    return v / n


def _rotation_to_up_z(direction) -> np.ndarray:
    d = unit(direction)
    R4 = trimesh.geometry.align_vectors(d, [0.0, 0.0, 1.0])
    return np.asarray(R4)[:3, :3]


def _normal_area_bins(
    mesh: trimesh.Trimesh, angle_tol_deg: float = DEFAULT_ANGLE_TOL_DEG
) -> tuple[np.ndarray, np.ndarray]:
    """把面法向按方向分箱（箱宽 ~= angle_tol_deg，用 `np.unique(axis=0)` 分组），
    返回 (箱内面积加权法向和 (B,3)（未归一化）, 箱面积 (B,))。`planar_patch_normals`
    与 `direction_histogram` 共用同一次分箱，两者只是对箱子的后处理不同。逐面
    贪心两两比较是 O(n^2)，分箱是 O(n log n)。"""
    normals = np.asarray(mesh.face_normals, dtype=np.float64)
    areas = np.asarray(mesh.area_faces, dtype=np.float64)
    if len(normals) == 0:
        return np.zeros((0, 3)), np.zeros((0,))
    step = float(np.radians(angle_tol_deg))
    keys = np.round(normals / step).astype(np.int64)
    uniq, inv = np.unique(keys, axis=0, return_inverse=True)
    inv = inv.reshape(-1)
    bin_area = np.zeros(len(uniq))
    np.add.at(bin_area, inv, areas)
    bin_vec = np.zeros((len(uniq), 3))
    np.add.at(bin_vec, inv, normals * areas[:, None])
    return bin_vec, bin_area


def planar_patch_normals(
    mesh: trimesh.Trimesh, min_area_share: float = DEFAULT_MIN_AREA_SHARE, angle_tol_deg: float = DEFAULT_ANGLE_TOL_DEG
) -> list[tuple[np.ndarray, float]]:
    """返回份额 >= min_area_share 的 (面积加权平均法向, 面积份额) 列表，按面积从
    大到小排。"""
    bin_vec, bin_area = _normal_area_bins(mesh, angle_tol_deg)
    total = float(bin_area.sum())
    if total <= 0:
        return []
    order = np.argsort(-bin_area)
    clusters = []
    for i in order:
        share = bin_area[i] / total
        if share < min_area_share:
            break
        avg = bin_vec[i] / (np.linalg.norm(bin_vec[i]) + 1e-12)
        clusters.append((avg, float(share)))
    return clusters


def direction_histogram(
    mesh: trimesh.Trimesh, angle_tol_deg: float = DEFAULT_ANGLE_TOL_DEG
) -> tuple[np.ndarray, np.ndarray]:
    """法向直方图：把面法向按约 angle_tol_deg 度分箱，返回 (箱代表方向 (B,3),
    箱面积 (B,))——一次 O(F) 遍历，后面每个候选只对 B 个箱子求和。"""
    bin_vec, bin_area = _normal_area_bins(mesh, angle_tol_deg)
    if len(bin_area) == 0:
        return np.zeros((0, 3)), np.zeros((0,))
    norms = np.linalg.norm(bin_vec, axis=1, keepdims=True)
    norms[norms < 1e-12] = 1.0
    bin_dirs = bin_vec / norms
    return bin_dirs, bin_area


def overhang_area_histogram(hist: tuple[np.ndarray, np.ndarray], up, angle_deg: float = DEFAULT_ANGLE_DEG) -> float:
    """用法向直方图近似算悬空面积（不排除贴床面——排除贴床面需要按候选方向重新
    投影顶点，这是留给"精确计算"那一步做的事；这里只用来快速给候选粗排序，以及
    跟精确值做误差对比）。"""
    bin_dirs, bin_areas = hist
    if len(bin_areas) == 0:
        return 0.0
    up = unit(up)
    cos_vals = bin_dirs @ (-up)
    mask = cos_vals > np.cos(np.radians(angle_deg))
    return float(bin_areas[mask].sum())


def overhang_area_exact(
    mesh: trimesh.Trimesh,
    up,
    angle_deg: float = DEFAULT_ANGLE_DEG,
    exclude_base: bool = False,
    base_margin_mm: float = DEFAULT_BASE_MARGIN_MM,
) -> float:
    """逐面精确算悬空面积（面法向与 -up 的点积 > cos(阈值)）；`exclude_base=True`
    时排除贴床面，是生产用于 top-12 候选的口径。"""
    up = unit(up)
    normals = mesh.face_normals
    areas = mesh.area_faces
    cos_vals = normals @ (-up)
    mask = cos_vals > np.cos(np.radians(angle_deg))
    if exclude_base:
        proj = mesh.vertices @ up
        base_level = proj.min()
        face_proj = proj[mesh.faces].mean(axis=1)
        base_mask = (face_proj - base_level) <= base_margin_mm
        mask = mask & (~base_mask)
    return float(areas[mask].sum())


def base_contact_area(
    mesh: trimesh.Trimesh,
    up,
    tol_mm: float = DEFAULT_BASE_MARGIN_MM,
    down_cos_threshold: float = CONTACT_DOWN_COS_THRESHOLD,
) -> float:
    """贴床接触面积：离最低点 tol_mm 以内 **且** 朝下（法向与 -up 夹角 < 45 度）
    的面积之和。"""
    up = unit(up)
    proj = mesh.vertices @ up
    base_level = proj.min()
    face_proj = proj[mesh.faces].mean(axis=1)
    near_base = (face_proj - base_level) <= tol_mm
    facing_down = (mesh.face_normals @ (-up)) > down_cos_threshold
    mask = near_base & facing_down
    return float(mesh.area_faces[mask].sum())


def height_along(mesh: trimesh.Trimesh, up) -> float:
    up = unit(up)
    proj = mesh.vertices @ up
    return float(proj.max() - proj.min())


def fibonacci_sphere(n: int) -> list[np.ndarray]:
    """n 个近似均匀分布在单位球面上的方向（黄金螺旋法）。"""
    pts = []
    golden_angle = np.pi * (3.0 - np.sqrt(5.0))
    for i in range(n):
        z = 1.0 - 2.0 * (i + 0.5) / n
        radius = np.sqrt(max(0.0, 1.0 - z * z))
        theta = golden_angle * i
        x = np.cos(theta) * radius
        y = np.sin(theta) * radius
        pts.append(np.array([x, y, z]))
    return pts


def candidate_directions(
    mesh: trimesh.Trimesh,
    include_fibonacci: bool,
    min_area_share: float = DEFAULT_MIN_AREA_SHARE,
    angle_tol_deg: float = DEFAULT_ANGLE_TOL_DEG,
    n_fibonacci: int = DEFAULT_N_FIBONACCI,
) -> tuple[list[np.ndarray], list[bool]]:
    """候选朝上方向 = 大平面片法向的反方向 + 六个坐标轴（+ `support`/`upright`
    策略额外加 `n_fibonacci` 个斐波那契球面方向）。去重：夹角小于约 2.6 度
    （dot > 0.999）的候选视为同一个方向，只保留先出现的那个（先出现的决定
    `forced`：如果一个斐波那契方向撞上了已有的大平面片/坐标轴候选，它沿用
    那个候选的 `forced=True`）。

    返回 `(候选方向列表, forced 列表)`。SPEC.md §3.3：大平面片候选与六个坐标轴
    `forced=True`——数量少，且"大平底朝下"的近似悬空值恰恰是最差的那档，不能
    被 `rank_candidates` 的预筛剔除；斐波那契候选 `forced=False`，可以被预筛。
    """
    patches = planar_patch_normals(mesh, min_area_share=min_area_share, angle_tol_deg=angle_tol_deg)
    cands: list[np.ndarray] = []
    forced: list[bool] = []

    def add(v: np.ndarray, is_forced: bool) -> None:
        v = unit(v)
        for existing in cands:
            if np.dot(existing, v) > 0.999:
                return
        cands.append(v)
        forced.append(is_forced)

    for normal, _share in patches:
        add(-normal, True)
    for ax in AXES6:
        add(ax, True)
    if include_fibonacci:
        for v in fibonacci_sphere(n_fibonacci):
            add(v, False)
    return cands, forced


def evaluate_orientation(
    mesh: trimesh.Trimesh, up, angle_deg: float = DEFAULT_ANGLE_DEG, base_margin_mm: float = DEFAULT_BASE_MARGIN_MM
) -> dict[str, Any]:
    """对一个具体候选方向算三项精确指标（贴床接触面积 / 悬空面积 / 高度）。"""
    up = unit(up)
    return {
        "print_up": [round(float(x), 6) for x in up],
        "contact_area_mm2": base_contact_area(mesh, up, tol_mm=base_margin_mm),
        "overhang_area_mm2": overhang_area_exact(
            mesh, up, angle_deg=angle_deg, exclude_base=True, base_margin_mm=base_margin_mm
        ),
        "height_mm": height_along(mesh, up),
    }


def rank_candidates(
    mesh: trimesh.Trimesh,
    candidates: Sequence[np.ndarray],
    forced: Optional[Sequence[bool]] = None,
    angle_deg: float = DEFAULT_ANGLE_DEG,
    base_margin_mm: float = DEFAULT_BASE_MARGIN_MM,
    top_k: int = DEFAULT_TOP_K,
) -> list[dict[str, Any]]:
    """先用法向直方图给全部候选算一个近似悬空面积。SPEC.md §3.3：预筛（取近似
    悬空最小的前 `top_k` 个）**只作用于 `forced[i] is False` 的候选**（斐波那契
    球面方向）；`forced[i] is True` 的候选（大平面片 + 六坐标轴）无条件进入精确
    评估。`forced=None` 时视为全部 True（不筛）。对这些候选做精确指标计算
    （贴床接触面积 + 精确悬空面积 + 高度）。"""
    if not candidates:
        return []
    if forced is None:
        forced = [True] * len(candidates)
    hist = direction_histogram(mesh)
    approx = [overhang_area_histogram(hist, c, angle_deg) for c in candidates]
    forced_idx = [i for i in range(len(candidates)) if forced[i]]
    prefilterable = sorted((i for i in range(len(candidates)) if not forced[i]), key=lambda i: approx[i])
    shortlist = sorted(set(forced_idx) | set(prefilterable[:top_k]))
    evaluated = []
    for i in shortlist:
        metrics = evaluate_orientation(mesh, candidates[i], angle_deg, base_margin_mm)
        metrics["approx_overhang_area_mm2"] = approx[i]
        evaluated.append(metrics)
    return evaluated


def stability_warnings(metrics: dict[str, Any]) -> list[str]:
    """SPEC.md §3.3：任何方式选出的朝向（含手工指定）若贴床面积 < `STABLE_CONTACT_MM2`
    都要带 `unstable_contact` 警告。`metrics` 只需要有 `contact_area_mm2` 键。"""
    if metrics["contact_area_mm2"] < STABLE_CONTACT_MM2:
        return ["unstable_contact"]
    return []


def _stability_order_key(metrics: dict[str, Any]) -> tuple[int, float, float]:
    """`support`（以及 `upright` 退让后）的排序键：稳定候选（贴床面积达标）排在
    不稳候选前面；组内按悬空面积升序、平手比高度。没有任何稳定候选时，这个键
    自然退化成对全体候选按悬空面积排序——即 SPEC.md §3.3 说的"没有稳定候选时
    取全体悬空最小"。"""
    stable_rank = 0 if metrics["contact_area_mm2"] >= STABLE_CONTACT_MM2 else 1
    return (stable_rank, metrics["overhang_area_mm2"], metrics["height_mm"])


def manual_result(
    mesh: trimesh.Trimesh, up, angle_deg: float = DEFAULT_ANGLE_DEG, base_margin_mm: float = DEFAULT_BASE_MARGIN_MM
) -> dict[str, Any]:
    """SPEC.md §3.3 `--set NAME=x,y,z` 手工指定 print_up 的结果，形状与
    `choose_orientation` 的返回值相同，方便 `cli.py` 统一处理。"""
    metrics = evaluate_orientation(mesh, up, angle_deg, base_margin_mm)
    return {
        "print_up": metrics["print_up"],
        "strategy_used": "manual",
        "contact_area_mm2": metrics["contact_area_mm2"],
        "overhang_area_mm2": metrics["overhang_area_mm2"],
        "height_mm": metrics["height_mm"],
        "upright_rejected": False,
        "upright_rejected_reason": None,
        "warnings": stability_warnings(metrics),
        "top_candidates": [metrics],
    }


def choose_orientation(
    mesh: trimesh.Trimesh,
    strategy: str,
    shape_label: str = "generic",
    angle_deg: float = DEFAULT_ANGLE_DEG,
    base_margin_mm: float = DEFAULT_BASE_MARGIN_MM,
    min_area_share: float = DEFAULT_MIN_AREA_SHARE,
    angle_tol_deg: float = DEFAULT_ANGLE_TOL_DEG,
    n_fibonacci: int = DEFAULT_N_FIBONACCI,
) -> dict[str, Any]:
    """按策略选一个 print_up。`auto` 先按 `shape_table` 把 shape_label 翻成具体策略。"""
    from . import shape_table  # 延迟 import，避免顶层循环依赖

    if strategy is None or strategy == "auto":
        strategy = shape_table.lookup(shape_label)["orient_strategy"]
    if strategy not in ("flat", "support", "upright"):
        raise ValueError(render("orient.unknown_strategy", strategy=strategy))

    needs_fibonacci = strategy in ("support", "upright")
    candidates, forced = candidate_directions(
        mesh,
        include_fibonacci=needs_fibonacci,
        min_area_share=min_area_share,
        angle_tol_deg=angle_tol_deg,
        n_fibonacci=n_fibonacci,
    )
    evaluated = rank_candidates(mesh, candidates, forced=forced, angle_deg=angle_deg, base_margin_mm=base_margin_mm)
    if not evaluated:
        # 极端退化网格（比如没有任何面）：退回 +Z，指标全 0。
        evaluated = [evaluate_orientation(mesh, (0.0, 0.0, 1.0), angle_deg, base_margin_mm)]

    upright_rejected = False
    upright_rejected_reason: Optional[str] = None

    if strategy == "flat":
        ordered = sorted(evaluated, key=lambda e: (-e["contact_area_mm2"], e["overhang_area_mm2"]))
        chosen = ordered[0]
        strategy_used = "flat"
    else:
        # support 与 upright 的退让结果共用同一个"稳定优先、悬空最小"排序。
        ordered = sorted(evaluated, key=_stability_order_key)
        support_best = ordered[0]
        if strategy == "support":
            chosen = support_best
            strategy_used = "support"
        else:  # upright
            source_metrics = evaluate_orientation(mesh, (0.0, 0.0, 1.0), angle_deg, base_margin_mm)
            source_stable = source_metrics["contact_area_mm2"] >= STABLE_CONTACT_MM2
            fallback_stable = support_best["contact_area_mm2"] >= STABLE_CONTACT_MM2
            if source_stable or not fallback_stable:
                # +Z 本身够稳；或者 +Z 不稳但压根没有更稳的候选可退——两种情况都
                # 保持 +Z（SPEC.md §3.3："仅当 +Z 不稳定且存在稳定候选时才退让"）。
                chosen = source_metrics
                strategy_used = "upright"
            else:
                chosen = support_best
                strategy_used = "support"
                upright_rejected = True
                upright_rejected_reason = render(
                    "orient.upright_rejected_reason",
                    contact_area_mm2=source_metrics["contact_area_mm2"],
                    stable_contact_mm2=STABLE_CONTACT_MM2,
                )

    result = {
        "print_up": chosen["print_up"],
        "strategy_used": strategy_used,
        "contact_area_mm2": chosen["contact_area_mm2"],
        "overhang_area_mm2": chosen["overhang_area_mm2"],
        "height_mm": chosen["height_mm"],
        "upright_rejected": upright_rejected,
        "upright_rejected_reason": upright_rejected_reason,
        "warnings": stability_warnings(chosen),
        "top_candidates": ordered[:3],
    }
    return result
