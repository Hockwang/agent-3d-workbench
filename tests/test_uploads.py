import base64
from pathlib import Path
import pytest
from studio.core.uploads import upload
from studio.core.editor import EditorError


def test_chunked_upload_is_idempotent_and_does_not_overwrite(tmp_path):
    body = {"name": "input.glb", "size": 6, "data_base64": base64.b64encode(b"abc").decode(), "offset": 0}
    first = upload(tmp_path, body)
    repeat = upload(tmp_path, {**body, "upload_id": first["upload_id"]})
    assert repeat["received"] == 3
    final = upload(
        tmp_path,
        {**body, "upload_id": first["upload_id"], "offset": 3, "data_base64": base64.b64encode(b"def").decode()},
    )
    assert final["complete"] and Path(final["path"]).read_bytes() == b"abcdef"
    second = upload(tmp_path, body)
    assert second["upload_id"] != first["upload_id"]
    with pytest.raises(EditorError):
        upload(tmp_path, {**body, "name": "../input.glb"})
    with pytest.raises(EditorError):
        upload(tmp_path, {**body, "name": "meta.json"})
    with pytest.raises(EditorError):
        upload(tmp_path, {**body, "upload_id": first["upload_id"], "data_base64": base64.b64encode(b"xyz").decode()})
