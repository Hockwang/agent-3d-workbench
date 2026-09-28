"""print_prep.arrange —— 排盘（把已经决定好 print_up 的零件摆到床上）。

货架法摆盘改编自作者早期私有研究代码 `manufacturing_kit/engine/print_waveab_v0/kitlib/plate.py::arrange`
（自有代码）：大件优先、按行摆满就换行；这里在其基础上加了 SPEC.md §3.4 要求的
三种模式（`single`/`per_part`/`auto`）、任意矩形避让区列表（原实现只硬编码了
P1S 一个固定角落）、以及"先转正、再在 0/90 度里选占地更小的那个"这一步。
"""

from __future__ import annotations

from typing import Any, Optional, Sequence

import numpy as np
import trimesh

from .messages import render

VALID_MODES = ("single", "per_part", "auto")


class PartTooLargeError(ValueError):
    """单件超出可用区（不管怎么摆都放不下），退出码 2；带建议缩放系数。"""

    def __init__(self, name: str, dims_mm: list[float], avail: dict[str, float], suggested_scale: Optional[float]):
        self.name = name
        self.dims_mm = dims_mm
        self.avail = avail
        self.suggested_scale = suggested_scale
        msg = render(
            "arrange.part_too_large",
            name=name,
            dims_mm=dims_mm,
            avail_dims=[avail["w"], avail["h"], avail["z"]],
            suggested_scale=suggested_scale,
        )
        super().__init__(msg)


class SinglePlateOverflowError(ValueError):
    """`--mode single` 放不下全部零件；报告改用 `auto` 需要几盘。"""

    def __init__(self, needed_plates: int):
        self.needed_plates = needed_plates
        super().__init__(render("arrange.single_plate_overflow", needed_plates=needed_plates))


class PartsDroppedError(RuntimeError):
    """内部不变量被打破：所有零件必须恰好出现一次。出现这个异常说明打包逻辑
    本身有 bug（不是用户能通过改参数规避的错误），cli.py 按未预期异常兜成
    退出码 1 即可；用显式 `raise` 而不是 `assert`，避免 `python -O` 剥掉检查。"""


def _unit(v) -> np.ndarray:
    v = np.asarray(v, dtype=float)
    n = np.linalg.norm(v)
    if n < 1e-12:
        raise ValueError(render("arrange.zero_vector", v=v))
    return v / n


def _rotation_to_up_z(direction) -> np.ndarray:
    d = _unit(direction)
    R4 = trimesh.geometry.align_vectors(d, [0.0, 0.0, 1.0])
    return np.asarray(R4)[:3, :3]


def _hom_rotation(R: np.ndarray) -> np.ndarray:
    T = np.eye(4)
    T[:3, :3] = R
    return T


def _hom_translation(t) -> np.ndarray:
    T = np.eye(4)
    T[:3, 3] = t
    return T


_RZ90 = np.array([[0.0, -1.0, 0.0], [1.0, 0.0, 0.0], [0.0, 0.0, 1.0]])


def prepare_item(part: dict[str, Any], avail_w: float, avail_z: float) -> dict[str, Any]:
    """把零件先按 `print_up` 转到 +Z 朝上，再绕 Z 取 0 度或 90 度：优先让长边
    沿 X（货架法的行高 = footprint 的 h，长边沿 X 时行高更小），若那样宽度
    （footprint 的 w）超出可用区宽度才退回另一个朝向（SPEC.md §3.4）。

    绕 Z 转不改变 XY 占地面积（只是把 w/h 互换），按面积挑是死代码——两个候选
    面积恒等，"选面积更小的"里的 `<=` 会让 0 度候选永远胜出而 90 度分支形同
    虚设；真正该比的是"哪个候选的长边落在 X 轴上"。
    """
    up = _unit(part["print_up"])
    R0 = _rotation_to_up_z(up)
    R0_hom = _hom_rotation(R0)
    mesh0 = part["mesh"].copy()
    mesh0.apply_transform(R0_hom)
    dims0 = mesh0.extents

    R90_hom = _hom_rotation(_RZ90) @ R0_hom
    mesh90 = part["mesh"].copy()
    mesh90.apply_transform(R90_hom)
    dims90 = mesh90.extents

    if dims0[0] >= dims0[1]:
        long_x_mesh, long_x_R, long_x_dims = mesh0, R0_hom, dims0
        other_mesh, other_R, other_dims = mesh90, R90_hom, dims90
    else:
        long_x_mesh, long_x_R, long_x_dims = mesh90, R90_hom, dims90
        other_mesh, other_R, other_dims = mesh0, R0_hom, dims0

    if long_x_dims[0] <= avail_w:
        chosen_mesh, chosen_R, dims = long_x_mesh, long_x_R, long_x_dims
    else:
        chosen_mesh, chosen_R, dims = other_mesh, other_R, other_dims

    if dims[2] > avail_z:
        raise ValueError(f"part {part.get('name')!r} height {dims[2]:.3f}mm exceeds usable bed height {avail_z:.3f}mm")

    return {"name": part.get("name"), "mesh": chosen_mesh, "R": chosen_R, "w": float(dims[0]), "h": float(dims[1])}


def _rects_intersect(ax0, ay0, ax1, ay1, bx0, by0, bx1, by1) -> bool:
    if ax1 <= bx0 or bx1 <= ax0:
        return False
    if ay1 <= by0 or by1 <= ay0:
        return False
    return True


def _find_slot(
    cursor_x: float,
    cursor_y: float,
    shelf_h: float,
    w: float,
    h: float,
    avail: dict[str, float],
    exclude_areas: Sequence[list[float]],
    gap_mm: float,
    placed: Sequence[dict[str, Any]],
    max_rounds: int = 64,
    eps: float = 1e-6,
) -> Optional[tuple[float, float, float]]:
    """从货架游标出发给一个 w x h 的矩形找落位点，返回 `(x, y, 该行已有行高)`，
    找不到返回 None。规则：这一行放不下就换行；压到避让区先试着往右躲，右边
    不够宽就另起一行、并把这一行抬到避让区上沿之外（只会往右躲的话，一个宽度
    接近整床的长条件会被左前角的避让区永远堵死，而它其实往上挪一点就放得下）。
    返回前一律过 `_placement_fits` 这道独立校验。
    """
    x, y, sh = cursor_x, cursor_y, shelf_h
    for _ in range(max_rounds):
        if x + w > avail["x1"] + eps:
            x, y, sh = avail["x0"], y + sh + (gap_mm if sh > 0 else 0.0), 0.0
        if y + h > avail["y1"] + eps:
            return None
        hits = [e for e in exclude_areas if _rects_intersect(x, y, x + w, y + h, e[0], e[1], e[2], e[3])]
        if not hits:
            return (x, y, sh) if _placement_fits(x, y, w, h, avail, exclude_areas, placed) else None
        right = max(e[2] for e in hits) + gap_mm
        if right + w <= avail["x1"] + eps:
            x = right
            continue
        above = max(e[3] for e in hits) + gap_mm
        x, y, sh = avail["x0"], max(above, y + sh + (gap_mm if sh > 0 else 0.0)), 0.0
    return None


def _placement_fits(
    x: float,
    y: float,
    w: float,
    h: float,
    avail: dict[str, float],
    exclude_areas: Sequence[list[float]],
    placed: Sequence[dict[str, Any]],
    eps: float = 1e-6,
) -> bool:
    """SPEC.md §3.4「放置后置校验」：落位矩形必须整体在可用区内，且不与任何
    避让区、也不与本盘已放置的零件相交。这是唯一的、独立于 `_find_slot` 找位
    逻辑的真值校验。
    """
    x1, y1 = x + w, y + h
    if x < avail["x0"] - eps or y < avail["y0"] - eps or x1 > avail["x1"] + eps or y1 > avail["y1"] + eps:
        return False
    for ex0, ey0, ex1, ey1 in exclude_areas:
        if _rects_intersect(x, y, x1, y1, ex0, ey0, ex1, ey1):
            return False
    for other in placed:
        ox0, oy0 = other["x_mm"], other["y_mm"]
        ow, oh = other["footprint_mm"]
        if _rects_intersect(x, y, x1, y1, ox0, oy0, ox0 + ow, oy0 + oh):
            return False
    return True


def _pack_plates(
    items: list[dict[str, Any]],
    avail: dict[str, float],
    exclude_areas: Sequence[list[float]],
    gap_mm: float,
    max_plates: Optional[int] = None,
) -> list[dict[str, Any]]:
    """货架法把 items（已按 footprint 面积降序排列）装进尽量少的盘；
    `max_plates` 非 None 时超过就抛 `SinglePlateOverflowError`（附带"改用 auto
    需要几盘"的估计，用同一个打包器不设 `max_plates` 重跑一次得到）。"""
    remaining = list(items)
    plates: list[dict[str, Any]] = []
    while remaining:
        if max_plates is not None and len(plates) >= max_plates:
            needed = len(plates) + len(_pack_plates(remaining, avail, exclude_areas, gap_mm))
            raise SinglePlateOverflowError(needed)
        cursor_x, cursor_y, shelf_h = avail["x0"], avail["y0"], 0.0
        placements = []
        placed_names = []
        leftover = []
        for it in remaining:
            w, h = it["w"], it["h"]
            slot = _find_slot(cursor_x, cursor_y, shelf_h, w, h, avail, exclude_areas, gap_mm, placements)
            if slot is None:
                # 这一盘放不下这一件，留给下一盘（不得带病落位）。
                leftover.append(it)
                continue
            x, cursor_y, shelf_h = slot

            bounds_min = it["mesh"].bounds[0]
            t = np.array([x - bounds_min[0], cursor_y - bounds_min[1], -bounds_min[2]])
            T = _hom_translation(t) @ it["R"]
            placements.append(
                {"part": it["name"], "T": T.tolist(), "x_mm": float(x), "y_mm": float(cursor_y), "footprint_mm": [w, h]}
            )
            placed_names.append(it["name"])
            cursor_x = x + w + gap_mm
            shelf_h = max(shelf_h, h)

        if not placements:
            # 每件的尺寸早已在 prepare_item / 上层校验过放得进可用区本身；这里
            # 为空只可能是避让区在一个全空的盘上仍然堵死了它——不是"尺寸超出
            # 可用区"，而是"这个位置放不进去"，同样报 part_too_large + 建议
            # 缩放系数（不得以未预期异常/退出码 1 收场，SPEC.md §3.4）。
            blocked = remaining[0]
            z_mm = float(blocked["mesh"].extents[2])
            suggested = _suggest_scale_blocked(blocked["w"], blocked["h"], z_mm, avail, exclude_areas, gap_mm)
            raise PartTooLargeError(blocked.get("name"), [blocked["w"], blocked["h"], z_mm], avail, suggested)
        plates.append({"placements": placements, "parts": placed_names})
        remaining = leftover
    return plates


def arrange(
    parts: Sequence[dict[str, Any]],
    bed_mm: Sequence[float],
    margin_mm: float,
    exclude_areas: Sequence[list[float]],
    mode: str = "auto",
    gap_mm: float = 4.0,
) -> list[dict[str, Any]]:
    """主入口。`parts` 每项至少要有 `name`/`mesh`/`print_up`。v0.1 没有
    `--group-by`（载入阶段不解析颜色，SPEC.md §3.4）。

    返回 `plates`（`index` 从 1 起）；函数末尾显式校验所有零件恰好出现一次——
    不许静默丢件（用 `raise` 而不是 `assert`，见 `PartsDroppedError`）。
    """
    if mode not in VALID_MODES:
        raise ValueError(render("arrange.unknown_mode", mode=mode, valid_modes=VALID_MODES))
    if gap_mm < 0:
        raise ValueError(render("arrange.gap_negative", gap_mm=gap_mm))

    avail = {
        "x0": margin_mm,
        "y0": margin_mm,
        "x1": bed_mm[0] - margin_mm,
        "y1": bed_mm[1] - margin_mm,
        "w": bed_mm[0] - 2 * margin_mm,
        "h": bed_mm[1] - 2 * margin_mm,
        "z": bed_mm[2] - margin_mm,
    }

    all_names_in: list[str] = [p.get("name") for p in parts]

    items = []
    for part in parts:
        # 高度不受绕 Z 旋转影响，用未挑选朝向前的一次快速投影就能判断是否超高，
        # 这样即使超高也能算出一个"按哪几个维度"给出的建议缩放系数。
        up_only = _hom_rotation(_rotation_to_up_z(part["print_up"]))
        probe = part["mesh"].copy()
        probe.apply_transform(up_only)
        height_z = float(probe.extents[2])
        try:
            item = prepare_item(part, avail["w"], avail["z"])
        except ValueError as exc:
            suggested = _suggest_scale(probe.extents[0], probe.extents[1], height_z, avail)
            raise PartTooLargeError(part.get("name"), [float(x) for x in probe.extents], avail, suggested) from exc
        if item["w"] > avail["w"] or item["h"] > avail["h"]:
            suggested = _suggest_scale(item["w"], item["h"], height_z, avail)
            raise PartTooLargeError(part.get("name"), [item["w"], item["h"], height_z], avail, suggested)
        items.append(item)
    items.sort(key=lambda it: -(it["w"] * it["h"]))

    if mode == "single":
        plates = _pack_plates(items, avail, exclude_areas, gap_mm, max_plates=1)
    elif mode == "per_part":
        plates = []
        for it in items:
            plates.extend(_pack_plates([it], avail, exclude_areas, gap_mm))
    else:  # auto
        plates = _pack_plates(items, avail, exclude_areas, gap_mm)

    plates_out = []
    placed_names: list[str] = []
    for i, plate in enumerate(plates, start=1):
        placed_names.extend(plate["parts"])
        plates_out.append({"index": i, "parts": plate["parts"], "placements": plate["placements"]})

    if sorted(placed_names) != sorted(all_names_in):
        raise PartsDroppedError(
            render("arrange.parts_dropped", input_names=sorted(all_names_in), placed_names=sorted(placed_names))
        )
    return plates_out


def _suggest_scale(w: float, h: float, z: float, avail: dict[str, float]) -> float:
    """跟 `mesh_io.fits_any_axis` 同样的"向下取 3 位小数"算法，但只看当前这一个
    已经定好的方向（print_up 已经定了，不再重新搜六个轴）。"""
    import math

    ratios = [
        avail["w"] / w if w > 0 else math.inf,
        avail["h"] / h if h > 0 else math.inf,
        avail["z"] / z if z > 0 else math.inf,
    ]
    ratio = min(ratios)
    return math.floor(ratio * 1000) / 1000.0


def _suggest_scale_blocked(
    w: float, h: float, z: float, avail: dict[str, float], exclude_areas: Sequence[list[float]], gap_mm: float
) -> Optional[float]:
    """尺寸本身没超可用区、却被避让区堵死时的建议缩放：二分找最大的系数，使缩小后的
    占地在一张空盘上找得到位置；向下取 3 位小数。一个都找不到返回 None。"""
    import math

    def fits(scale: float) -> bool:
        if z * scale > avail["z"]:
            return False
        return (
            _find_slot(avail["x0"], avail["y0"], 0.0, w * scale, h * scale, avail, exclude_areas, gap_mm, [])
            is not None
        )

    lo, hi = 0.0, 1.0
    if fits(hi):
        return None  # 其实放得下，调用方不该走到这里
    for _ in range(40):
        mid = (lo + hi) / 2.0
        if fits(mid):
            lo = mid
        else:
            hi = mid
    lo = math.floor(lo * 1000.0) / 1000.0
    return lo if lo > 0 else None
