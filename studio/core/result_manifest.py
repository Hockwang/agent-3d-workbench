"""Optional, artifact-bound display identity for a completed modeling result.

This is presentation metadata, not geometry acceptance. A registration task copies
explicitly supplied files into the current project; it never imports into its editor.
"""

import hashlib
import json
from pathlib import Path
import re
import shutil

from studio.core.editor import EditorError
from studio.i18n import register, render

register(
    {
        "results.invalid": {
            "en": "Invalid result identity or artifact reference.",
            "zh-CN": "成果名称或关联文件无效。",
        },
        "results.inputs": {
            "en": "Register one local GLB and optionally one PNG/JPEG/WebP thumbnail.",
            "zh-CN": "请登记一个本地 GLB，可附一张 PNG/JPEG/WebP 缩略图。",
        },
        "results.source_changed": {
            "en": "The source changed during registration; register it again after writing finishes.",
            "zh-CN": "登记时源文件发生变化，请等文件写入完成后重新登记。",
        },
    }
)

FILENAME = "workbench-result.json"
SCHEMA = "workbench-result/v1"


def validate(data, artifacts):
    """Only expose short text and references to delivered artifacts, never URLs."""
    if not isinstance(data, dict) or data.get("schema") != SCHEMA:
        raise EditorError.coded("results.invalid")
    result = {"schema": SCHEMA}
    for key, limit in (("work_id", 96), ("work_title", 160), ("variant", 100), ("version", 48), ("note", 280)):
        value = data.get(key, "")
        if not isinstance(value, str) or len(value) > limit or any(ord(c) < 32 for c in value):
            raise EditorError.coded("results.invalid")
        result[key] = value.strip()
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,95}", result["work_id"]) or not all(
        result[k] for k in ("work_title", "variant")
    ):
        raise EditorError.coded("results.invalid")
    by_name = {a["name"]: a for a in artifacts}
    for key, extensions in (("primary", (".glb",)), ("thumbnail", (".png", ".jpg", ".jpeg", ".webp"))):
        value = data.get(key)
        if key == "thumbnail" and value is None:
            continue
        if not isinstance(value, str) or value not in by_name or not value.lower().endswith(extensions):
            raise EditorError.coded("results.invalid")
        result[key] = value
    return result


def read_manifest(output, artifacts):
    path = Path(output) / FILENAME
    if not path.exists():
        return None
    if path.is_symlink() or path.stat().st_size > 8192:
        raise EditorError.coded("results.invalid")
    try:
        return validate(json.loads(path.read_text()), artifacts)
    except (ValueError, UnicodeError):
        raise EditorError.coded("results.invalid") from None


def register_existing(workbench):
    """Call from an ordinary Python studio_task; inputs are model[, thumbnail]."""
    inputs = [Path(p) for p in workbench["inputs"]]
    if not 1 <= len(inputs) <= 2 or inputs[0].suffix.lower() != ".glb":
        raise EditorError.coded("results.inputs")
    if len(inputs) == 2:
        from PIL import Image

        image = inputs[1]
        if image.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp") or image.stat().st_size > 20 * 1024**2:
            raise EditorError.coded("results.inputs")
        try:
            with Image.open(image) as img:
                if img.format not in ("PNG", "JPEG", "WEBP"):
                    raise ValueError()
                img.verify()
        except (ValueError, OSError):
            raise EditorError.coded("results.inputs") from None
    names = ["scene.glb"] + (["preview" + inputs[1].suffix.lower()] if len(inputs) == 2 else [])
    metadata = {**workbench["params"], "schema": SCHEMA, "primary": names[0]}
    if len(inputs) == 2:
        metadata["thumbnail"] = names[1]
    metadata = validate(metadata, [{"name": name} for name in names])
    out = Path(workbench["output"])
    for source, name in zip(inputs, names):
        with source.open("rb") as stream:
            before = hashlib.file_digest(stream, "sha256").hexdigest()
        target = out / name
        shutil.copyfile(source, target)
        with target.open("rb") as stream:
            after = hashlib.file_digest(stream, "sha256").hexdigest()
        if before != after:
            raise RuntimeError(render("results.source_changed"))
    (out / FILENAME).write_text(json.dumps(metadata, ensure_ascii=False, indent=2))
