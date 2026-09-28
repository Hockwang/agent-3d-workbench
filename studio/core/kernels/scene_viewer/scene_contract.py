"""assembly-scene/v1 —— 统一 viewer 的数据契约。

**一句话**：一个 scene 就是「一组 part + 可选的 joint 图 + 可选的参考图」，
按 URL 引用，不搬文件。

为什么是这个形状：三个前身 viewer（merge_ui / a8 / hackday urdf-viewer）差的
只是**图层强调**，不是数据模型 ——

    炸件 = part 的位移图层        （merge_ui 主场）
    label = part 的着色/编号图层  （三家都有）
    运动 = joint 的变换图层       （hackday / a8 主场）
    材质 = part 的材质图层        （a8 主场）

同一份数据的四种看法。所以 joints 为空是**合法**的：切割结果没有关节，viewer
自动只亮炸件与 label 两层，不是降级也不是报错。

形状刻意贴近 hackday viewer 已验证的 link/joint 树（那份内核跑了几个月），
迁移风险最低；新增的是 part 语义/度量（来自 merge_ui manifest）与评审层
（来自 a8）。
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

SCENE_SCHEMA = "assembly-scene/v1"
INDEX_SCHEMA = "assembly-scene-index/v1"
CURATION_EXPORT_SCHEMA = "assembly-scene-curation/v1"

# 与 hackday viewer 的 motionType 取值保持一致，别自造词表。
MOTION_TYPES = {"revolute", "continuous", "prismatic", "fixed"}

# `motionRange` 本身没有量纲信息。A8/URDF 产物沿用米，img2threejs 的快速柜体
# 编译器则使用相对/推断单位；把两者都渲成 "m" 会制造伪测量。缺字段仍按历史契约
# 解释（viewer 端 m / ZYX），只有新适配器需要显式声明。
LINEAR_UNITS = {"m", "relative"}
ROTATION_ORDERS = {"XYZ", "YZX", "ZXY", "XZY", "YXZ", "ZYX"}

# 逐件配色：viewer 与各适配器共用同一张表，保证「同一件在哪都是同一个颜色」。
PALETTE = [
    0x159D82,
    0xE8A62A,
    0x397FD1,
    0xDF5F68,
    0x8664C7,
    0x5B9F48,
    0xE27635,
    0x319BAA,
    0xB95A9E,
    0x8F9630,
]


class SceneError(ValueError):
    """契约违例。信息里必须点名是哪个 part/joint，否则排查得靠猜。"""


def make_part(
    name: str,
    visual_url: str,
    *,
    part_id: str = "",
    label: str = "",
    labels: list[str] | None = None,
    origin: list[float] | None = None,
    rpy: list[float] | None = None,
    scale: list[float] | None = None,
    metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """一个 part = 一个 link + 一份 visual 引用。

    `visual_url` 是**引用**（相对 scene.json 或绝对 URL），不是要被复制到某个
    注册目录里的东西 —— merge_ui 那 1.9G / 100 个 data_ 目录就是这么来的。
    """
    if not str(name).strip():
        raise SceneError("part.name is required")
    if not str(visual_url).strip():
        raise SceneError(f"part {name!r}: visual_url is required")
    part: dict[str, Any] = {
        "name": str(name),
        "partId": str(part_id or name),
        "visuals": [
            {
                "file": str(visual_url),
                "origin": list(origin or [0.0, 0.0, 0.0]),
                "rpy": list(rpy or [0.0, 0.0, 0.0]),
                **({"scale": list(scale)} if scale else {}),
            }
        ],
    }
    if label:
        part["label"] = str(label)
    if labels:
        part["labels"] = [str(item) for item in labels]
    if metrics:
        part["metrics"] = dict(metrics)
    return part


def make_joint(
    name: str,
    parent: str,
    child: str,
    *,
    motion_type: str = "revolute",
    axis: list[float] | None = None,
    origin: list[float] | None = None,
    rpy: list[float] | None = None,
    motion_range: list[float] | None = None,
    source: str = "",
    linear_unit: str = "",
    rotation_order: str = "",
) -> dict[str, Any]:
    if motion_type not in MOTION_TYPES:
        raise SceneError(f"joint {name!r}: unknown motionType {motion_type!r}; allowed: {sorted(MOTION_TYPES)}")
    if linear_unit and linear_unit not in LINEAR_UNITS:
        raise SceneError(f"joint {name!r}: unknown linearUnit {linear_unit!r}; allowed: {sorted(LINEAR_UNITS)}")
    if rotation_order and rotation_order not in ROTATION_ORDERS:
        raise SceneError(
            f"joint {name!r}: unknown rotationOrder {rotation_order!r}; allowed: {sorted(ROTATION_ORDERS)}"
        )
    joint: dict[str, Any] = {
        "name": str(name),
        "parent": str(parent),
        "child": str(child),
        "motionType": motion_type,
        "axis": list(axis or [0.0, 0.0, 1.0]),
        "origin": list(origin or [0.0, 0.0, 0.0]),
        "rpy": list(rpy or [0.0, 0.0, 0.0]),
        "fixed": motion_type == "fixed",
    }
    if motion_range:
        # prismatic 用 motionRange（量纲由 linearUnit 声明），转动用 poseRange（弧度）。
        key = "motionRange" if motion_type == "prismatic" else "poseRange"
        joint[key] = list(motion_range)
    if source:
        joint["source"] = str(source)
    if linear_unit:
        joint["linearUnit"] = str(linear_unit)
    if rotation_order:
        joint["rotationOrder"] = str(rotation_order)
    return joint


def make_scene(
    *,
    title: str,
    parts: list[dict[str, Any]],
    joints: list[dict[str, Any]] | None = None,
    eyebrow: str = "",
    root: str = "",
    coordinate_system: str = "y-up",
    refs: list[dict[str, Any]] | None = None,
    presets: dict[str, Any] | None = None,
    provenance: dict[str, Any] | None = None,
    compare: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """组装并**当场校验**。宁可在生成侧炸，也不要让 viewer 静默渲染半个模型。"""
    joints = list(joints or [])
    scene = {
        "schema": SCENE_SCHEMA,
        "title": str(title),
        "eyebrow": str(eyebrow),
        "coordinateSystem": coordinate_system,
        "root": str(root or _implicit_root(parts, joints)),
        "parts": list(parts),
        "joints": joints,
        "refs": list(refs or []),
        "presets": dict(presets or {}),
        "provenance": dict(provenance or {}),
    }
    if compare:
        scene["compare"] = dict(compare)
    validate_scene(scene)
    scene["contentSha256"] = content_sha256(scene)
    return scene


def content_sha256(scene: dict[str, Any]) -> str:
    """场景内容指纹 —— 审计标记的陈旧闸门。

    沿用 a8 的做法：一条 golden/bad 标记只在 `contentSha256` 与当前一致时生效。
    切割重跑过、关节改过、件换过文件，指纹就变，旧标记自动失效而不是静默套用到
    新结果上 —— 那种静默套用是审计数据最难发现的污染。

    只吃**会改变被评审对象**的字段：件名、几何文件、关节定义。标题、参考图、
    eyebrow 这类展示层改动不该让人重标一遍。
    """
    payload = {
        "parts": [
            {
                "name": part.get("name"),
                "visuals": [visual.get("file") for visual in part.get("visuals") or []],
            }
            for part in scene.get("parts") or []
        ],
        "joints": [
            {
                key: joint.get(key)
                for key in (
                    "name",
                    "parent",
                    "child",
                    "motionType",
                    "axis",
                    "origin",
                    "rpy",
                    "motionRange",
                    "poseRange",
                    "linearUnit",
                    "rotationOrder",
                )
                if joint.get(key) is not None
            }
            for joint in scene.get("joints") or []
        ],
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _implicit_root(parts: list[dict], joints: list[dict]) -> str:
    """没有显式 root 时：取第一个不当任何 joint 的 child 的 part。

    纯切割结果（零 joint）因此自然落到 parts[0]，其余 part 平铺在 root 下 ——
    这正是「炸件视图」要的拓扑。
    """
    children = {str(joint.get("child", "")) for joint in joints}
    for part in parts:
        if str(part.get("name", "")) not in children:
            return str(part.get("name", ""))
    return str(parts[0].get("name", "")) if parts else ""


def validate_compare(compare: dict[str, Any]) -> None:
    """对照层：同一评审单元里的第二套几何。

    形状 = `{mode, label, sceneUrl}`。**引用而不是内联** —— 对照方往往本身就是
    独立一案（`_src` 既是 `_dress` 的对照，也是自己那一案），内联会让同一份几何
    在两处各存一份，指纹也对不上。

    两条硬规矩，写在这里免得以后有人"顺手扩一下"：
      ① 对照件不参与逐件审阅（不上编号配色、不进部件清单、不响应点选）。
         它是参照物；否则"哪个 part-03"会同时指向两个模型。
      ② 不递归 —— 对照方自己的 compare 一律忽略，只并排两套，不并排一串。
    """
    if not isinstance(compare, dict):
        raise SceneError("compare must be an object")
    url = str(compare.get("sceneUrl", "")).strip()
    if not url:
        raise SceneError("compare.sceneUrl is required (a comparison is a reference, not inline geometry)")
    if not str(compare.get("label", "")).strip():
        raise SceneError("compare.label is required (the mode button needs a name for it)")


def validate_scene(scene: dict[str, Any]) -> None:
    if scene.get("schema") != SCENE_SCHEMA:
        raise SceneError(f"schema must be {SCENE_SCHEMA!r}, got {scene.get('schema')!r}")
    if scene.get("compare"):
        validate_compare(scene["compare"])
    parts = scene.get("parts") or []
    if not parts:
        raise SceneError("scene has no parts")

    names: set[str] = set()
    for part in parts:
        name = str(part.get("name", ""))
        if not name:
            raise SceneError("a part has no name")
        if name in names:
            raise SceneError(f"duplicate part name {name!r}")
        names.add(name)
        if not (part.get("visuals") or []) and part.get("frameOnly") is not True:
            raise SceneError(f"part {name!r} has no visuals")

    if scene.get("root") and scene["root"] not in names:
        raise SceneError(f"root {scene['root']!r} is not a part")

    seen_children: set[str] = set()
    for joint in scene.get("joints") or []:
        jname = str(joint.get("name", ""))
        for side in ("parent", "child"):
            ref = str(joint.get(side, ""))
            if ref not in names:
                raise SceneError(f"joint {jname!r}: {side} {ref!r} is not a part")
        child = str(joint.get("child"))
        # 一个 part 被两个 joint 当 child = 树塌成图，内核 ensureLink 会挂错父节点
        if child in seen_children:
            raise SceneError(f"part {child!r} is the child of more than one joint")
        seen_children.add(child)
        if joint.get("motionType") not in MOTION_TYPES:
            raise SceneError(f"joint {jname!r}: bad motionType {joint.get('motionType')!r}")
        linear_unit = joint.get("linearUnit")
        if linear_unit is not None and linear_unit not in LINEAR_UNITS:
            raise SceneError(f"joint {jname!r}: bad linearUnit {linear_unit!r}")
        rotation_order = joint.get("rotationOrder")
        if rotation_order is not None and rotation_order not in ROTATION_ORDERS:
            raise SceneError(f"joint {jname!r}: bad rotationOrder {rotation_order!r}")


def make_index(title: str, cases: list[dict[str, Any]]) -> dict[str, Any]:
    """案列（评审壳用）。每条只登记 id/标题/scene 地址，不含几何。"""
    for case in cases:
        if not case.get("id") or not case.get("sceneUrl"):
            raise SceneError(f"index case needs id and sceneUrl: {case!r}")
    return {"schema": INDEX_SCHEMA, "title": title, "cases": list(cases)}
