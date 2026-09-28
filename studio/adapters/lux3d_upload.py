"""Upload helper for the optional, key-gated Lux3D adapter (`lux3d_service.py`):
puts a local file into Lux3D's public regional Asset API so generation calls can
reference it by URL. Only the short-lived, per-upload OUS token goes to Lux3D's
storage endpoint — never the long-lived Lux3D API key itself."""

import hashlib
import json
import math
from pathlib import Path
import re
import time
import urllib.error
import urllib.request
import uuid

from studio.core.editor import EditorError
from studio.adapters.services import NoRedirect, validate_url


def multipart(fields, filename=None, content=None):
    boundary = "studio-" + uuid.uuid4().hex
    data = []
    for key, value in fields.items():
        data.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode())
    if filename is not None:
        # Local filenames never become unsanitized HTTP header bytes.
        name = "input" + Path(filename).suffix.lower()
        data += [
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{name}"\r\nContent-Type: application/octet-stream\r\n\r\n'.encode(),
            content,
            b"\r\n",
        ]
    data.append(f"--{boundary}--\r\n".encode())
    return b"".join(data), "multipart/form-data; boundary=" + boundary


def storage_request(token, method, path, fields=None, filename=None, content=None):
    url = validate_url(token["globalDomain"].rstrip("/") + path)
    headers = {"ous-token-v2": token["ousToken"]}
    data = None
    if fields is not None:
        data, headers["Content-Type"] = multipart(fields, filename, content)
    try:
        with urllib.request.build_opener(NoRedirect()).open(
            urllib.request.Request(url, data=data, headers=headers, method=method), timeout=120
        ) as response:
            raw = response.read(1024 * 1024 + 1)
            if len(raw) > 1024 * 1024:
                raise EditorError.coded("lux3d_upload.response_too_large")
            result = json.loads(raw)
    except (urllib.error.URLError, TimeoutError, ValueError):
        raise EditorError.coded("lux3d_upload.connection_failed_or_invalid") from None
    if not isinstance(result, dict):
        raise EditorError.coded("lux3d_upload.response_invalid")
    if "c" in result:
        if result["c"] not in ("0", 0, None, ""):
            raise EditorError.coded("lux3d_upload.upload_rejected")
        result = result.get("d")
    if not isinstance(result, dict):
        raise EditorError.coded("lux3d_upload.response_missing_data")
    return result


def missing_blocks(value, count):
    if value in (None, "", []):
        return list(range(1, count + 1))
    if isinstance(value, str):
        value = value.split(",")
    if not isinstance(value, list):
        raise EditorError.coded("lux3d_upload.missing_blocks_invalid")
    blocks = set()
    for part in value:
        if not re.fullmatch(r"[0-9]+(?:-[0-9]+)?", str(part)):
            raise EditorError.coded("lux3d_upload.block_number_invalid")
        numbers = [int(x) for x in str(part).split("-")]
        start, end = numbers[0], numbers[-1]
        if not 1 <= start <= end <= count:
            raise EditorError.coded("lux3d_upload.block_number_out_of_range")
        blocks.update(range(start, end + 1))
    return sorted(blocks)


def upload(spec, filename):
    from studio.adapters.lux3d_service import request

    path = Path(filename).expanduser()
    if not path.is_absolute() or not path.is_file() or not 0 < path.stat().st_size <= 1024**3:
        raise EditorError.coded("lux3d_upload.file_must_exist_and_fit")
    with path.open("rb") as stream:
        checksum = hashlib.file_digest(stream, "md5").hexdigest()
    token = request(spec, "GET", "/asset/v1/token")
    if (
        not isinstance(token, dict)
        or not isinstance(token.get("ousToken"), str)
        or not token["ousToken"]
        or any(c.isspace() for c in token["ousToken"])
        or type(token.get("blockSize")) is not int
        or not 0 < token["blockSize"] <= 128 * 1024 * 1024
        or not isinstance(token.get("globalDomain"), str)
    ):
        raise EditorError.coded("lux3d_upload.token_invalid")
    validate_url(token["globalDomain"])
    block_size = token["blockSize"]
    size = path.stat().st_size
    if size <= block_size:
        storage_request(token, "POST", "/ous/api/v2/single/upload", {"md5": checksum}, path.name, path.read_bytes())
    else:
        count = math.ceil(size / block_size)
        result = storage_request(
            token,
            "POST",
            "/ous/api/v2/block/upload/init",
            {"md5": checksum, "blocks": count, "size": size, "name": path.name},
        )
        blocks = missing_blocks(result.get("lackBlocks"), count)
        with path.open("rb") as stream:
            for number in blocks:
                stream.seek((number - 1) * block_size)
                storage_request(
                    token,
                    "POST",
                    "/ous/api/v2/block/upload/part",
                    {"block": number},
                    path.name,
                    stream.read(block_size),
                )
    for _ in range(120):
        result = storage_request(token, "GET", "/ous/api/v2/upload/status")
        if result.get("status") == 5:
            if result.get("md5") not in (None, checksum):
                raise EditorError.coded("lux3d_upload.checksum_mismatch")
            return validate_url(result.get("url", ""))
        if result.get("status") in (6, 8):
            raise EditorError.coded("lux3d_upload.upload_failed")
        time.sleep(1)
    raise EditorError.coded("lux3d_upload.upload_timeout")
