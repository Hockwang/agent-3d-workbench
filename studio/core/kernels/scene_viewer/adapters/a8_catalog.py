"""A8 审阅台的批次目录 → assembly-scene/v1。

A8（`tooling/a8_viewer/`）的一批案子由两个目录构成：

    dataDir/cases.json    案表：审计元数据 + sourceArticulation（逐 link GLB + 关节谱）
    partsDir/<caseId>/    逐 link 的 .glb

`catalog_registry.json` 把 batchId 映到这两个目录。本适配器直接吃它们，于是
**A8 的批次成为统一 viewer 的一种输入**，而不是另一个 viewer 的私有格式。

两件事值得写下来：

① `sourceArticulation` 与参数化线 bundle 里的 `glb.kind == "a8-links"` **同形**
   （name/file、parent/child/origin/axis/motionType/motionRange），所以这里不需要
   解析 URDF，逐条搬即可。

② A8 案表里那 8 个审计字段（topology / profile / a2 / a8 / blocker / blockerCopy /
   note / status）在本契约里没有对应位置 —— 这正是"皮肤照搬过来了、四格事实卡却
   全是 —"的原因。它们统一落进 `provenance.audit`，由 viewer 侧的事实卡直接读；
   **缺字段就留空，不替上游编内容**。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..scene_contract import make_joint, make_part, make_scene

# a8 的 motionType 词表与本契约一致；未知值 fail-closed 成 fixed 而不是猜
_MOTION = {"revolute", "continuous", "prismatic", "fixed"}

# 审计字段：a8 案表里的键 → provenance.audit 里的键（同名，显式列出便于校验）
_AUDIT_KEYS = ("topology", "profile", "a2", "a8", "blocker", "blockerCopy", "note", "status")


def _cases_payload(data_dir: Path) -> list[dict[str, Any]]:
    """cases.json 优先；只有 cases.js 时从 `window.__A8_CASES__ = [...]` 里抠。"""
    direct = data_dir / "cases.json"
    if direct.is_file():
        return json.loads(direct.read_text(encoding="utf-8"))
    js = data_dir / "cases.js"
    if not js.is_file():
        raise ValueError(f"{data_dir}: 既没有 cases.json 也没有 cases.js")
    text = js.read_text(encoding="utf-8")
    start = text.index("[")
    end = text.rindex("]") + 1
    return json.loads(text[start:end])


def load_registry(registry_path: str | Path) -> dict[str, dict[str, Any]]:
    """catalog_registry.json → {batchId: batch}（只保留本机存在的批次）。"""
    registry_path = Path(registry_path)
    payload = json.loads(registry_path.read_text(encoding="utf-8"))
    if payload.get("schema") != "a8_catalog_registry/v1":
        raise ValueError(f"{registry_path}: 不认识的 schema {payload.get('schema')!r}")
    live = {}
    default_id = str(payload.get("defaultBatchId") or "")
    for batch_id, batch in (payload.get("batches") or {}).items():
        data_dir = Path(str(batch.get("dataDir", "")))
        # 冷归档批次的 dataDir 在 UD800 上，没挂载就跳过而不是炸整份 registry
        if data_dir.is_dir():
            live[batch_id] = {
                **batch,
                "batchId": batch_id,
                "dataDir": data_dir,
                "partsDir": Path(str(batch.get("partsDir", ""))),
                # registry 指定的默认批次。"裸跑 serve.py 就能看"
                # 靠它 —— 默认 viewer 不该要求先记住一串 batchId。
                "isDefault": batch_id == default_id,
            }
    return live


def load_cases(data_dir: str | Path, parts_dir: str | Path) -> list[dict[str, Any]]:
    """→ [{id, title, group, partsDir, refPath, links, joints, audit, …}]

    只解析与定位；scene 要等挂载点定下来才拼，那是 serve 层的事。
    """
    data_dir = Path(data_dir)
    parts_dir = Path(parts_dir)
    cases = []
    for entry in _cases_payload(data_dir):
        case_id = str(entry.get("id", "")).strip()
        if not case_id:
            continue
        articulation = entry.get("sourceArticulation") or {}
        links = articulation.get("links") or []
        if not links:
            continue  # 没有几何的案（纯运动学记录）不属于本 viewer
        case_parts = parts_dir / case_id
        if not case_parts.is_dir():
            continue  # 产物不在本机

        reference = str(entry.get("reference") or "")
        ref_path = None
        if reference:
            candidate = (data_dir / reference).resolve()
            if candidate.is_file():
                ref_path = candidate

        cases.append(
            {
                "id": case_id,
                "title": str(entry.get("short") or entry.get("title") or case_id),
                "group": str(entry.get("group", "")),
                "partsDir": case_parts,
                "refPath": ref_path,
                "reference": reference,
                "referenceHash": str(entry.get("referenceHash") or ""),
                "links": links,
                "joints": articulation.get("joints") or [],
                "rootLink": str(articulation.get("rootLink") or ""),
                "referencePose": articulation.get("referencePose"),
                # 旧 A8 清单没有这两个字段：空值保留历史解释（m / ZYX），不在这里
                # 猜默认。img2threejs 适配器会在自己的边界显式补 relative / XYZ。
                "linearUnit": str(articulation.get("linearUnit") or ""),
                "rotationOrder": str(articulation.get("rotationOrder") or ""),
                "stats": entry.get("stats") or {},
                "audit": {key: entry[key] for key in _AUDIT_KEYS if entry.get(key) not in (None, "")},
            }
        )
    if not cases:
        raise ValueError(f"{data_dir}: 本机没有任何一案的 parts 产物（partsDir={parts_dir}）")
    return cases


def build_scene(
    case: dict[str, Any],
    *,
    base_url: str,
    batch_label: str = "",
    provenance_source: str = "a8_catalog",
    provenance_extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """把一条 a8 case 拼成 scene。`base_url` 下能取到该案的逐 link GLB。"""

    def visual_url(link: dict[str, Any]) -> str:
        url = f"{base_url}/{str(link.get('file', ''))}"
        digest = str(link.get("sha256") or "")
        # img2threejs 适配器在挂载时重算完整 GLB SHA。把它放进引用 query，既不搬
        # 文件，也让 assembly-scene 的 contentSha256 真正绑定到字节而非只绑文件名。
        return f"{url}?sha256={digest}" if digest else url

    parts = [
        make_part(str(link.get("name", "")), visual_url(link))
        for link in case["links"]
        if str(link.get("name", "")) and str(link.get("file", ""))
    ]
    joints = []
    for joint in case["joints"]:
        motion_type = str(joint.get("motionType", "fixed"))
        linear_unit = str(joint.get("linearUnit") or case.get("linearUnit") or "")
        rotation_order = str(joint.get("rotationOrder") or case.get("rotationOrder") or "")
        # A8 的历史 prismatic 行程写在 motionRange；真实门柜的 revolute 行程
        # 写在 poseRange。旧 img2threejs bridge 曾把所有类型都写 motionRange，
        # 因此转动关节保留 fallback，但绝不能只读 motionRange 后静默丢门角。
        motion_range = (
            joint.get("motionRange") if motion_type == "prismatic" else joint.get("poseRange", joint.get("motionRange"))
        )
        joints.append(
            make_joint(
                str(joint.get("name", "")),
                str(joint.get("parent", "")),
                str(joint.get("child", "")),
                motion_type=motion_type if motion_type in _MOTION else "fixed",
                axis=joint.get("axis"),
                origin=joint.get("origin"),
                rpy=joint.get("rpy"),
                motion_range=motion_range,
                source="a8" if provenance_source == "a8_catalog" else provenance_source,
                linear_unit=linear_unit if motion_type == "prismatic" else "",
                rotation_order=rotation_order,
            )
        )

    scene = make_scene(
        title=case["title"],
        # A8 的 GLB 由 export 时就转成 Y-up（跟参数化线同一条导出路径），
        # 这里再转一次就是 blender-gltf-zup-double-rotation 那个坑。
        coordinate_system="y-up",
        eyebrow=case["group"] or (batch_label or "A8 批次"),
        root=case["rootLink"],
        parts=parts,
        joints=joints,
        refs=(
            [{"kind": "reference", "url": f"{base_url}/__ref__", "caption": "线上真实输入"}]
            if case.get("refPath")
            else []
        ),
        provenance={
            "source": provenance_source,
            "caseId": case["id"],
            "batch": batch_label,
            "group": case["group"],
            "stats": case.get("stats") or {},
            "audit": case.get("audit") or {},
            "poseSemantics": _pose_semantics(case),
            **dict(provenance_extra or {}),
        },
    )
    return scene


def _pose_semantics(case: dict[str, Any]) -> dict[str, Any]:
    """A8 案表不写两端语义，但 referencePose 说明 0 端是什么。

    没有依据就返回空 —— viewer 会退成 Q0 / Q1，比编一句"收合"诚实。
    """
    reference_pose = case.get("referencePose")
    if reference_pose is None:
        return {}
    return {
        "domain": [0, 1],
        "0": "closed",
        "1": "open",
        "note": f"A8 记录的参考姿态 referencePose={reference_pose}",
    }
