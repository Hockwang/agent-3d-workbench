"""SPEC.md §10 P1：本机服务 `studio/shell/server.py` 的接口测试。

不碰真实的 `~/.print-prep`：每个用例都用 `create_httpd()` 直接在进程内起一个
绑定随机端口（`port=0`）的实例、指向 `tmp_path` 下的临时 job 目录，测试结束
`httpd.shutdown()` + `server_close()`。也顺手把 `PRINT_PREP_HOME` 环境变量指到
临时目录（防御性的——这份测试其实全程没有代码路径会碰它，但万一将来改动引入
了依赖，测试环境也不会被污染）。
"""

from __future__ import annotations

import http.client
import json
import threading
import time
from pathlib import Path
from typing import Any

import numpy as np
import trimesh

from .conftest import write_box_stl

from print_prep import job as job_mod
from print_prep import shape_table
from tests.helpers import Client


def _write_inverted_cone_stl(path) -> None:
    """See `tests/test_cli_contract.py::_write_inverted_cone_stl` for why this
    shape's overhang classification flips sharply around angle_deg~63-64 for
    up=(0,0,1): every lateral face sits at the same slope, so it is a clean
    two-value probe for "did a different angle_deg actually change the result".
    """
    cone = trimesh.creation.cone(radius=15.0, height=30.0, sections=48)
    cone.apply_transform(trimesh.transformations.rotation_matrix(np.pi, [1.0, 0.0, 0.0]))
    cone.export(path, file_type="stl")


def test_post_without_token_rejected(studio_env):
    client: Client = studio_env["client"]
    status, payload = client.post("/api/load", {"files": []}, token=None)
    assert status == 403
    assert payload["ok"] is False
    assert payload["error"]["code"] == "forbidden"


def test_bad_host_header_rejected(studio_env):
    port = studio_env["port"]
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    conn.putrequest("GET", "/api/state", skip_host=True)
    conn.putheader("Host", "evil.example.com")
    conn.endheaders()
    resp = conn.getresponse()
    body = json.loads(resp.read())
    conn.close()
    assert resp.status == 400
    assert body["ok"] is False
    assert body["error"]["code"] == "bad_host"


def test_shapes_endpoint(studio_env):
    client: Client = studio_env["client"]
    status, resp = client.get("/api/shapes")
    assert status == 200
    assert resp["ok"] is True
    assert resp["print_submitted"] is False
    assert [s["label"] for s in resp["shapes"]] == list(shape_table.VALID_LABELS)
    by_label = {s["label"]: s for s in resp["shapes"]}
    assert by_label["generic"]["process_overrides"] == {}
    assert by_label["figurine"]["process_overrides"]["support_type"] == "tree(auto)"


def test_full_pipeline_state_shape_and_rev(studio_env, tmp_path):
    client: Client = studio_env["client"]
    box1 = write_box_stl(tmp_path, "box1", (30, 20, 5))
    box2 = write_box_stl(tmp_path, "box2", (15, 10, 40))

    status, state0 = client.get("/api/state")
    assert status == 200
    assert state0["parts"] == []
    assert state0["printer"] is None
    assert state0["plates"] is None
    assert state0["export"] is None
    assert state0["check"] is None
    assert state0["sent"] is None
    assert state0["steps"] == {"inspect": False, "orient": False, "arrange": False, "export": False, "check": False}
    assert state0["options"] == {"shape": "generic", "strategy": "auto", "mode": "auto", "gap": 4.0}
    rev0 = state0["rev"]

    status, resp = client.post("/api/load", {"files": [str(box1), str(box2)]})
    assert status == 200 and resp["ok"] is True

    status, state1 = client.get("/api/state")
    assert state1["rev"] > rev0
    assert state1["steps"]["inspect"] is True
    assert state1["steps"]["orient"] is False
    assert {p["name"] for p in state1["parts"]} == {"box1", "box2"}
    assert state1["printer"]["name"] == "Bambu Lab P1S 0.4 nozzle"
    assert state1["printer"]["bed_mm"] == [256.0, 256.0, 250.0]
    assert state1["printer"]["exclude_areas"] == [[0.0, 0.0, 18.0, 28.0]]
    for p in state1["parts"]:
        assert p["orient"] is None
        assert p["stl_url"].startswith(f"/api/part/{p['name']}.stl?v=")
        assert p["source_center_mm"] is not None

    status, resp = client.post("/api/orient", {"shape": "relief"})
    assert status == 200 and resp["ok"] is True

    status, resp = client.post("/api/arrange", {"gap": 5})
    assert status == 200 and resp["ok"] is True

    status, resp = client.post("/api/export", {"no_project": True})
    assert status == 200 and resp["ok"] is True, resp

    status, state2 = client.get("/api/state")
    assert status == 200
    assert state2["steps"] == {"inspect": True, "orient": True, "arrange": True, "export": True, "check": False}
    assert state2["rev"] > state1["rev"]
    assert state2["options"]["shape"] == "relief"
    assert len(state2["plates"]) >= 1
    assert state2["export"]["plates"][0]["geometry_3mf"]
    assert state2["export"]["overrides"] == {"enable_support": "0"}
    for p in state2["parts"]:
        assert p["orient"] is not None
        assert p["orient"]["strategy_used"] == "flat"


def test_orient_angle_deg_out_of_range_rejected(studio_env, tmp_path):
    client: Client = studio_env["client"]
    box1 = write_box_stl(tmp_path, "box1", (10, 10, 10))
    status, resp = client.post("/api/load", {"files": [str(box1)]})
    assert status == 200 and resp["ok"] is True

    status, resp = client.post("/api/orient", {"angle_deg": 3})
    assert status == 400
    assert resp["ok"] is False
    assert resp["error"]["code"] == "bad_angle_deg"

    status, resp = client.post("/api/orient", {"angle_deg": 90})
    assert status == 400
    assert resp["ok"] is False
    assert resp["error"]["code"] == "bad_angle_deg"


def test_orient_angle_deg_override_changes_result_and_is_recorded(studio_env, tmp_path):
    client: Client = studio_env["client"]
    job_dir: Path = studio_env["job_dir"]
    cone_path = tmp_path / "cone.stl"
    _write_inverted_cone_stl(cone_path)
    status, resp = client.post("/api/load", {"files": [str(cone_path)]})
    assert status == 200 and resp["ok"] is True

    status, tight = client.post("/api/orient", {"set": {"cone": [0, 0, 1]}, "angle_deg": 60})
    assert status == 200 and tight["ok"] is True
    assert tight["angle_deg"] == 60.0
    assert tight["parts"]["cone"]["overhang_area_mm2"] == 0.0

    status, loose = client.post("/api/orient", {"set": {"cone": [0, 0, 1]}, "angle_deg": 70})
    assert status == 200 and loose["ok"] is True
    assert loose["angle_deg"] == 70.0
    assert loose["parts"]["cone"]["overhang_area_mm2"] > 1000.0

    status, state = client.get("/api/state")
    assert status == 200
    for p in state["parts"]:
        if p["name"] == "cone":
            assert p["orient"]["overhang_area_mm2"] > 1000.0

    # additive job.json key: the angle_deg actually used by the most recent orient.
    data = job_mod.load_job(job_dir)
    assert data["orient"]["angle_deg"] == 70.0


def test_state_inspect_rev_tracks_last_load(studio_env, tmp_path):
    """`studio.core.print_state.build_state` 的可加性字段 `inspect_rev`：记录
    当前载入模型最后一次真正跑出新 `inspect` 快照时的 `rev`
    （`StudioBackend.run_write` 按 `before_job`/`after_job` 的 `inspect` 字段
    是否变化统一调用 `mark_inspect_rev`——不是只在 `op_name == "load"` 时才
    更新：`prepare` 会重新跑 inspect（可能换了输入），也必须跟着刷新，否则前端
    会拿着一个过期的 `inspect_rev` 误判"模型没换"。`inspect_rev` 字段之前只
    在 `build_state()` 里读出局部变量却从没塞进响应体。"""
    client: Client = studio_env["client"]
    box1 = write_box_stl(tmp_path, "box1", (10, 10, 10))

    status, state0 = client.get("/api/state")
    assert status == 200
    assert state0["inspect_rev"] == 0  # 还没 load 过

    status, resp = client.post("/api/load", {"files": [str(box1)]})
    assert status == 200 and resp["ok"] is True

    status, state1 = client.get("/api/state")
    assert status == 200
    assert state1["inspect_rev"] == state1["rev"]

    # 之后跑一个不重新 load 的写操作：`rev` 继续涨，但 `inspect_rev` 原地不动
    # ——orient 不碰 `inspect`。
    status, resp = client.post("/api/orient", {"shape": "relief"})
    assert status == 200 and resp["ok"] is True

    status, state2 = client.get("/api/state")
    assert status == 200
    assert state2["rev"] > state1["rev"]
    assert state2["inspect_rev"] == state1["inspect_rev"]

    # `prepare`（op_name == "prepare"，不是 "load"）换一个不同的输入重新跑
    # inspect：`inspect_rev` 必须跟着刷新到这次写操作完成时的 `rev`，不能停留
    # 在上一次 `load` 的旧值上（回归：之前只有 `load` 会调用
    # `mark_inspect_rev`，`prepare` 触发的 inspect 变化会被漏掉）。
    box2 = write_box_stl(tmp_path, "box2", (20, 20, 20))
    status, resp = client.post("/api/prepare", {"files": [str(box2)], "no_project": True})
    assert status == 200 and resp["ok"] is True, resp

    status, state3 = client.get("/api/state")
    assert status == 200
    assert [p["name"] for p in state3["parts"]] == ["box2"]
    assert state3["rev"] > state2["rev"]
    assert state3["inspect_rev"] == state3["rev"]
    assert state3["inspect_rev"] > state2["inspect_rev"]


def test_part_stl_path_traversal_rejected(studio_env, tmp_path):
    client: Client = studio_env["client"]
    box1 = write_box_stl(tmp_path, "box1", (10, 10, 10))
    status, resp = client.post("/api/load", {"files": [str(box1)]})
    assert status == 200

    status, state = client.get("/api/state")
    stl_url = state["parts"][0]["stl_url"]
    status, body = client.get(stl_url)
    assert status == 200
    assert isinstance(body, (bytes, bytearray)) and len(body) > 0

    status, _ = client.get("/api/part/../x.stl")
    assert status == 404
    status, _ = client.get("/api/part/nonexistent.stl")
    assert status == 404


def test_upload_stores_file_under_uploads_dir(studio_env):
    client: Client = studio_env["client"]
    status, resp = client.raw_bytes("/api/upload?name=weird%20name.stl", b"binary-stl-bytes-placeholder")
    assert status == 200
    assert resp["ok"] is True
    stored = Path(resp["path"])
    assert stored.is_file()
    assert stored.parent == (studio_env["job_dir"] / "uploads")
    assert stored.read_bytes() == b"binary-stl-bytes-placeholder"


def test_upload_rejects_unsupported_extension(studio_env):
    client: Client = studio_env["client"]
    status, resp = client.raw_bytes("/api/upload?name=evil.exe", b"x")
    assert status == 400
    assert resp["error"]["code"] == "unsupported_extension"


def test_concurrent_write_gets_409(studio_env):
    backend = studio_env["backend"]
    client: Client = studio_env["client"]

    def slow_op():
        time.sleep(0.4)
        return {"ok": True, "command": "load"}

    result_holder: dict[str, Any] = {}

    def run_slow():
        result_holder["result"] = backend.run_write("load", slow_op)

    t = threading.Thread(target=run_slow)
    t.start()
    time.sleep(0.1)
    status, resp = client.post("/api/load", {"files": []})
    t.join(timeout=5)

    assert status == 409
    assert resp["ok"] is False
    assert resp["error"]["code"] == "busy"
    assert result_holder["result"][0] == 200


def test_send_dry_run_does_not_launch_anything(studio_env):
    client: Client = studio_env["client"]
    job_dir: Path = studio_env["job_dir"]

    # 绕开真实 Bambu Studio 命令行（本机测试环境不一定装了它）：直接往
    # job.json 里塞一份合法形状的 export 记录，只为了验证 `/api/send
    # --dry-run` 本身的行为（cmd_open 只要求 export.plates[].project_3mf
    # 存在，不要求那个文件真的存在——dry-run 分支从不读它）。
    data = job_mod.load_job(job_dir)
    fake_project = job_dir / "plates" / "plate_01.project.3mf"
    data["export"] = {
        "printer": "Bambu Lab P1S 0.4 nozzle",
        "shape": "generic",
        "process_preset": "x",
        "filament_preset": "y",
        "no_project": False,
        "plates": [
            {
                "index": 1,
                "geometry_3mf": str(fake_project),
                "project_3mf": str(fake_project),
                "bambu_moved_objects": False,
                "unmatched_parts": [],
            }
        ],
        "notes": [],
    }
    job_mod.save_job(job_dir, data)

    status, resp = client.post("/api/send", {"plate": 1, "dry_run": True})
    assert status == 200, resp
    assert resp["ok"] is True
    assert resp["launched"] is False
    assert resp["loaded"] == "unverified"
    assert len(resp["opened"]) == 1
    assert resp["opened"][0]["executed"] is False
    assert "open" in resp["opened"][0]["command"][0]

    status, state = client.get("/api/state")
    assert state["sent"]["plates"] == [1]
    assert state["sent"]["launched"] is False
    assert state["sent"]["loaded"] == "unverified"


def test_sse_pushes_new_rev_after_write(studio_env):
    port = studio_env["port"]
    client: Client = studio_env["client"]

    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
    conn.request("GET", "/api/events", headers={"X-Studio-Token": client.token})
    resp = conn.getresponse()
    assert resp.status == 200
    assert resp.getheader("Content-Type") == "text/event-stream"

    events: list[bytes] = []

    def trigger():
        time.sleep(0.2)
        client.post("/api/orient", {})  # 会失败（还没 inspect）但仍然会让 rev 前进两次

    t = threading.Thread(target=trigger)
    t.start()

    buf = b""
    deadline = time.time() + 10
    while time.time() < deadline and len(events) < 2:
        try:
            chunk = resp.fp.read1(256)
        except TimeoutError:
            continue  # 单次 socket 读超时不等于"没等到事件"，留给外层 deadline 判定
        if not chunk:
            break
        buf += chunk
        while b"\n\n" in buf:
            line, buf = buf.split(b"\n\n", 1)
            if line.startswith(b"data:"):
                events.append(line)
    t.join(timeout=10)
    conn.close()

    assert len(events) >= 2
    revs = [json.loads(e[len(b"data:") :])["rev"] for e in events]
    assert revs[1] == revs[0] + 1
