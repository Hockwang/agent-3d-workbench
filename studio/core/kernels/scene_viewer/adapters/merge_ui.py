"""merge_ui 数据集 → assembly-scene/v1。

merge_ui 的病根是「注册即物化」：每看一个东西就在 tooling/merge_ui/ 下建一个
`data_<名字>/` 目录，把 GLB 搬进去（实测 100 个目录 / 1.9G / 270 个实体 GLB）。
本适配器**只读那个目录、指过去**，不搬任何字节 —— 也因此可以直接指向切割器
的原始输出目录，跳过注册这一步。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..scene_contract import make_part, make_scene


def _label_lookup(data_dir: Path) -> dict[str, str]:
    """group.json 若在，取逐件语义名；不在就算了，label 是可选图层。"""
    path = data_dir / "group.json"
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    groups = payload.get("groups") if isinstance(payload, dict) else payload
    labels: dict[str, str] = {}
    for group in groups or []:
        if not isinstance(group, dict):
            continue
        name = str(group.get("name") or group.get("label") or "")
        for member in group.get("parts") or group.get("members") or []:
            labels[str(member)] = name
    return labels


def _registry_entry(data_dir: Path) -> dict[str, Any]:
    """从同级 datasets.json 取这份数据集的登记信息（中文标签 / 分组）。

    那份登记是人手维护的，比从目录名反推的标题好得多 —— `data_hunkey_dress`
    对不上任何东西，"Hunyuan 钥匙柜(闭合) · dress 后"一眼就知道是什么。
    读不到就退回目录名，不是硬依赖。
    """
    registry = data_dir.parent / "datasets.json"
    if not registry.is_file():
        return {}
    try:
        entries = json.loads(registry.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    for entry in entries if isinstance(entries, list) else []:
        if isinstance(entry, dict) and entry.get("dir") == data_dir.name:
            return entry
    return {}


def from_dataset(data_dir: str | Path, *, base_url: str, title: str = "") -> dict[str, Any]:
    """`data_dir` 是磁盘上的目录（读 manifest 用），`base_url` 是浏览器侧能取到
    同一目录的前缀 —— 两者分开，才能做到"文件留在原地、viewer 通过服务读"。
    """
    data_dir = Path(data_dir)
    manifest_path = data_dir / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"no manifest.json in {data_dir}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    # merge_ui 的 manifest 是一个 part 数组（不是带 parts 键的对象）
    entries = manifest if isinstance(manifest, list) else (manifest.get("parts") or [])
    if not entries:
        raise ValueError(f"{manifest_path} lists no parts")

    labels = _label_lookup(data_dir)
    prefix = base_url.rstrip("/")
    parts = []
    for index, entry in enumerate(entries):
        file_name = str(entry.get("file") or f"part-{index:02d}.glb")
        name = Path(file_name).stem
        metrics = {key: entry[key] for key in ("vertices", "faces", "is_watertight") if key in entry}
        if entry.get("bbox", {}).get("extent"):
            metrics["extent"] = entry["bbox"]["extent"]
        parts.append(
            make_part(
                name,
                f"{prefix}/{file_name}",
                part_id=name,
                label=labels.get(name, ""),
                metrics=metrics,
            )
        )

    reference = next(
        (
            item.name
            for item in sorted(data_dir.glob("reference.*"))
            if item.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}
        ),
        "",
    )
    registered = _registry_entry(data_dir)
    group = str(registered.get("group") or "")
    return make_scene(
        title=title or str(registered.get("label") or "") or data_dir.name.replace("data_", ""),
        eyebrow=f"切件 · {group}" if group else "MERGE_UI / 切件",
        parts=parts,
        joints=[],  # 切割结果没有关节 —— 合法，viewer 只亮炸件与 label 两层
        refs=[{"kind": "reference", "url": f"{prefix}/{reference}", "caption": "参考图"}] if reference else [],
        provenance={
            "source": "merge_ui",
            "dataDir": str(data_dir.resolve()),
            **({"group": group} if group else {}),
        },
    )
