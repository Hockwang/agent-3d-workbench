"""Chunked file intake shared by the MCP iframe and browser, never overwrites inputs."""

import base64
import binascii
import hashlib
import json
from pathlib import Path
import re
import uuid
from studio.core.editor import EditorError, _atomic

EXTENSIONS = {
    ".glb",
    ".gltf",
    ".stl",
    ".obj",
    ".ply",
    ".3mf",
    ".blend",
    ".fbx",
    ".bvh",
    ".step",
    ".stp",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".json",
    ".npy",
    ".npz",
    ".svg",
}


def upload(root, body):
    name = body.get("name")
    if (
        not isinstance(name, str)
        or name == "meta.json"
        or len(name) > 200
        or any(ord(c) < 32 for c in name)
        or Path(name).name != name
        or Path(name).suffix.lower() not in EXTENSIONS
    ):
        raise EditorError.coded("uploads.bad_name_or_type")
    size, offset = body.get("size"), body.get("offset", 0)
    if type(size) is not int or not 0 < size <= 500 * 1024 * 1024 or type(offset) is not int or not 0 <= offset <= size:
        raise EditorError.coded("uploads.bad_size_or_offset")
    encoded = body.get("data_base64", "")
    if not isinstance(encoded, str) or len(encoded) > 1_400_000:
        raise EditorError.coded("uploads.chunk_too_large")
    try:
        chunk = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        raise EditorError.coded("uploads.bad_base64") from None
    if not chunk or offset + len(chunk) > size:
        raise EditorError.coded("uploads.chunk_length_mismatch")
    identifier = body.get("upload_id")
    if identifier is None:
        if offset != 0:
            raise EditorError.coded("uploads.first_chunk_must_start_at_zero")
        identifier = uuid.uuid4().hex
        directory = Path(root) / identifier
        directory.mkdir(parents=True)
        _atomic(directory / "meta.json", json.dumps({"name": name, "size": size}).encode())
    else:
        if not isinstance(identifier, str) or not re.fullmatch("[a-f0-9]{32}", identifier):
            raise EditorError.coded("uploads.bad_upload_id")
        directory = Path(root) / identifier
        if not (directory / "meta.json").is_file() or json.loads((directory / "meta.json").read_text()) != {
            "name": name,
            "size": size,
        }:
            raise EditorError.coded("uploads.metadata_mismatch")
    final = directory / name
    partial = directory / "data.partial"
    path = final if final.is_file() else partial
    current = path.stat().st_size if path.exists() else 0
    if offset < current:
        with path.open("rb") as source:
            source.seek(offset)
            prior = source.read(len(chunk))
        if prior != chunk:
            raise EditorError.coded("uploads.duplicate_chunk_mismatch")
    elif offset == current:
        with partial.open("ab") as output:
            output.write(chunk)
        current += len(chunk)
    else:
        raise EditorError.coded("uploads.chunk_not_contiguous")
    result = {"ok": True, "upload_id": identifier, "received": current, "complete": current == size}
    if current == size:
        if partial.exists():
            partial.replace(final)
        with final.open("rb") as source:
            digest = hashlib.file_digest(source, "sha256").hexdigest()
        result.update(path=str(final.resolve()), sha256=digest)
    return result
