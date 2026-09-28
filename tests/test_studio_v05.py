"""SPEC_V05.md §2：本机服务新增内容的测试——谁做的（X-Studio-Actor）/ `/api/state`
新字段（selection、step_actors、stale、readiness、history）/ 两个新接口
（`/api/select`、`/api/undo`）/ 两个新工具（`studio_select`、`studio_undo`）/
持久化（`studio_meta.json`）/ cookie 鉴权加固（§2.6）。

沿用 `test_studio_api.py` 的写法：`create_httpd()` 在进程内起一个绑定随机端口
（`port=0`）的实例、指向 `tmp_path` 下的临时 job 目录，不碰真实的
`~/.print-prep`。`Client` 直接复用那边定义的那一份，避免重复造轮子。
"""

from __future__ import annotations

import http.client
import json
from pathlib import Path

import pytest

from .conftest import write_box_stl

from studio.core import history
from studio.shell import tools_schema
from studio.shell.server import StudioBackend
from tests.helpers import Client


def _load_two_boxes(client: Client, tmp_path: Path):
    box1 = write_box_stl(tmp_path, "box1", (30, 20, 5))
    box2 = write_box_stl(tmp_path, "box2", (15, 10, 40))
    status, resp = client.post("/api/load", {"files": [str(box1), str(box2)]})
    assert status == 200 and resp["ok"] is True, resp
    return box1, box2


@pytest.mark.parametrize("fail_export", [False, True])
def test_prepare_replaces_model_and_cannot_undo_old_model(studio_env, tmp_path, monkeypatch, fail_export):
    from print_prep import cli

    client = studio_env["client"]
    _load_two_boxes(client, tmp_path)
    assert client.post("/api/orient", {})[0] == 200
    assert client.post("/api/arrange", {})[0] == 200
    assert client.post("/api/select", {"parts": ["box1"]})[0] == 200
    studio_env["backend"]._delivered = True
    studio_env["backend"].sent = {"plates": [1], "launched": True}
    if fail_export:

        def fail(_):
            raise cli.UserError("Test export failure")

        monkeypatch.setattr(cli, "cmd_export", fail)
    replacement = write_box_stl(tmp_path, "replacement", (10, 10, 10))
    status, _ = client.post(
        "/api/prepare", {"files": [str(replacement)], "no_project": True}, headers={"X-Studio-Actor": "human"}
    )
    assert (status == 200) is not fail_export
    _, state = client.get("/api/state")
    assert [p["name"] for p in state["parts"]] == ["replacement"]
    assert not any(e["undoable"] for e in state["history"])
    assert state["selection"]["parts"] == []
    assert state["step_actors"]["inspect"] == "human"
    assert state["sent"] is None
    assert next(i for i in state["readiness"]["items"] if i["key"] == "deliver")["status"] == "todo"
    assert client.post("/api/undo", {})[0] == 409


def test_reorient_invalidates_previous_delivery(studio_env, tmp_path):
    client = studio_env["client"]
    _load_two_boxes(client, tmp_path)
    studio_env["backend"]._delivered = True
    studio_env["backend"].sent = {"plates": [1], "launched": True}
    assert client.post("/api/orient", {})[0] == 200
    _, state = client.get("/api/state")
    assert state["sent"] is None
    assert next(i for i in state["readiness"]["items"] if i["key"] == "deliver")["status"] == "todo"


# --------------------------------------------------------------------- 1
# X-Studio-Actor 写进 history 与 step_actors；缺省记 ai。
# ---------------------------------------------------------------------


def test_actor_header_recorded_in_history_and_step_actors(studio_env, tmp_path):
    client: Client = studio_env["client"]
    _load_two_boxes(client, tmp_path)  # 不带 X-Studio-Actor -> 缺省 ai

    status, resp = client.post("/api/orient", {}, headers={"X-Studio-Actor": "human"})
    assert status == 200 and resp["ok"] is True

    status, state = client.get("/api/state")
    assert state["history"][0]["op"] == "orient"
    assert state["history"][0]["actor"] == "human"
    assert state["step_actors"]["orient"] == "human"
    assert state["history"][-1]["op"] == "load"
    assert state["history"][-1]["actor"] == "ai"
    assert state["step_actors"]["inspect"] == "ai"

    # 非法值（既不是 human 也不是 ai）也按 ai 记
    status, resp = client.post("/api/arrange", {}, headers={"X-Studio-Actor": "bogus"})
    assert status == 200 and resp["ok"] is True
    status, state = client.get("/api/state")
    assert state["history"][0]["op"] == "arrange"
    assert state["history"][0]["actor"] == "ai"
    assert state["step_actors"]["arrange"] == "ai"


# --------------------------------------------------------------------- 2
# orient -> arrange -> 再 orient：history 顺序、stale 里出现 arrange 的旧摘要、
# 重新 arrange 后 stale 清掉。
# ---------------------------------------------------------------------


def test_orient_arrange_reorient_history_order_and_stale(studio_env, tmp_path):
    client: Client = studio_env["client"]
    _load_two_boxes(client, tmp_path)

    status, resp = client.post("/api/orient", {"shape": "generic"})
    assert status == 200 and resp["ok"] is True
    status, resp = client.post("/api/arrange", {"gap": 4})
    assert status == 200 and resp["ok"] is True

    status, state = client.get("/api/state")
    assert [e["op"] for e in state["history"][:3]] == ["arrange", "orient", "load"]
    assert state["stale"] == {}
    # 第一次 orient 之前没有上一次 orient，overhang_mm2_before 是 null。
    first_orient_summary = state["history"][1]["summary"]
    assert first_orient_summary["overhang_mm2_before"] is None
    assert first_orient_summary["overhang_mm2_after"] is not None

    # 再 orient 一次：arrange 因为失效级联被删掉，进 stale。
    status, resp = client.post("/api/orient", {"shape": "relief"})
    assert status == 200 and resp["ok"] is True

    status, state = client.get("/api/state")
    assert [e["op"] for e in state["history"][:4]] == ["orient", "arrange", "orient", "load"]
    assert state["steps"]["arrange"] is False
    assert "arrange" in state["stale"]
    assert state["stale"]["arrange"]["mode"] == "auto"
    assert state["stale"]["arrange"]["gap_mm"] == 4.0
    assert isinstance(state["stale"]["arrange"]["plates"], int) and state["stale"]["arrange"]["plates"] >= 1
    # 第二次 orient 之前存在一次 orient，overhang_mm2_before 不是 null。
    assert state["history"][0]["summary"]["overhang_mm2_before"] is not None

    # 重新 arrange：从 stale 里消失。
    status, resp = client.post("/api/arrange", {})
    assert status == 200 and resp["ok"] is True
    status, state = client.get("/api/state")
    assert "arrange" not in state["stale"]
    assert state["steps"]["arrange"] is True


# --------------------------------------------------------------------- 3
# undo：还原 orient/arrange 两段并删掉 export/check；id 不是最新可撤销条目 ->
# 409 not_latest；没有可撤销 -> 409 nothing_to_undo；load 之后旧记录不可撤销。
# ---------------------------------------------------------------------


def test_undo_restores_snapshot_and_cascades(studio_env, tmp_path):
    client: Client = studio_env["client"]
    _load_two_boxes(client, tmp_path)
    assert client.post("/api/orient", {})[0] == 200
    assert client.post("/api/arrange", {})[0] == 200
    status, resp = client.post("/api/export", {"no_project": True})
    assert status == 200 and resp["ok"] is True, resp

    status, state = client.get("/api/state")
    assert [e["op"] for e in state["history"][:4]] == ["export", "arrange", "orient", "load"]
    arrange_entry = state["history"][1]
    assert arrange_entry["op"] == "arrange"
    assert arrange_entry["undoable"] is True
    assert arrange_entry["undone"] is False

    status, resp = client.post("/api/undo", {})
    assert status == 200 and resp["ok"] is True
    assert resp["target_id"] == arrange_entry["id"]
    assert resp["target_op"] == "arrange"

    status, state = client.get("/api/state")
    assert state["steps"]["orient"] is True
    assert state["steps"]["arrange"] is False
    assert state["steps"]["export"] is False
    by_id = {e["id"]: e for e in state["history"]}
    assert by_id[arrange_entry["id"]]["undone"] is True
    assert by_id[arrange_entry["id"]]["undoable"] is False
    assert state["history"][0]["op"] == "undo"
    assert state["history"][0]["undoable"] is False
    assert state["history"][0]["summary"] == {"target_id": arrange_entry["id"], "target_op": "arrange"}

    orient_entry = next(e for e in state["history"] if e["op"] == "orient")

    # 重新 arrange，产生一条新的可撤销记录；此时给一个不是"最近一条"的 id。
    status, resp = client.post("/api/arrange", {})
    assert status == 200 and resp["ok"] is True
    status, resp = client.post("/api/undo", {"id": orient_entry["id"]})
    assert status == 409
    assert resp["ok"] is False
    assert resp["error"]["code"] == "not_latest"

    # 之后再跑一次 load：此前所有记录一律变为不可撤销。
    _load_two_boxes(client, tmp_path)
    status, state = client.get("/api/state")
    assert all(e["undoable"] is False for e in state["history"])

    status, resp = client.post("/api/undo", {})
    assert status == 409
    assert resp["error"]["code"] == "nothing_to_undo"


def test_undo_of_reorient_brings_back_arrange_and_original_makers(studio_env, tmp_path):
    """SPEC_V05.md §2.3：撤销要同时还原 orient / arrange 两段。重新选朝向会把分盘级联删掉，
    撤销这次选朝向之后分盘必须回来，且仍算原来那个人（这里是 ai）做的；export 照旧作废。"""
    client: Client = studio_env["client"]
    _load_two_boxes(client, tmp_path)
    ai = {"X-Studio-Actor": "ai"}
    human = {"X-Studio-Actor": "human"}
    assert client.post("/api/orient", {}, headers=ai)[0] == 200
    assert client.post("/api/arrange", {}, headers=ai)[0] == 200
    assert client.post("/api/export", {"no_project": True}, headers=ai)[0] == 200
    _, before = client.get("/api/state")
    plates_before = before["plates"]

    assert client.post("/api/orient", {"strategy": "flat"}, headers=human)[0] == 200
    _, mid = client.get("/api/state")
    assert mid["steps"]["arrange"] is False
    assert set(mid["stale"]) == {"arrange", "export"}
    assert mid["step_actors"] == {"inspect": "ai", "orient": "human"} or mid["step_actors"]["orient"] == "human"

    status, resp = client.post("/api/undo", {}, headers=human)
    assert status == 200 and resp["target_op"] == "orient", resp
    _, after = client.get("/api/state")
    assert after["steps"]["orient"] is True
    assert after["steps"]["arrange"] is True
    assert after["steps"]["export"] is False
    assert after["plates"] == plates_before
    assert after["options"]["strategy"] == before["options"]["strategy"]
    assert after["step_actors"]["orient"] == "ai"
    assert after["step_actors"]["arrange"] == "ai"
    assert set(after["stale"]) == {"export"}


def test_undo_nothing_to_undo_without_any_undoable_entry(studio_env, tmp_path):
    client: Client = studio_env["client"]
    _load_two_boxes(client, tmp_path)  # 只 load，没有任何可撤销的 orient/arrange

    status, resp = client.post("/api/undo", {})
    assert status == 409
    assert resp["ok"] is False
    assert resp["error"]["code"] == "nothing_to_undo"


# --------------------------------------------------------------------- 4
# /api/select：正常、未知零件 400、selection 出现在 state 里、rev 增加、不进
# history。
# ---------------------------------------------------------------------


def test_select_endpoint(studio_env, tmp_path):
    client: Client = studio_env["client"]
    _load_two_boxes(client, tmp_path)

    status, state0 = client.get("/api/state")
    assert state0["selection"] == {"parts": [], "by": None, "at": None}
    rev0 = state0["rev"]
    history_len0 = len(state0["history"])

    status, resp = client.post("/api/select", {"parts": ["box1"]}, headers={"X-Studio-Actor": "human"})
    assert status == 200 and resp["ok"] is True
    assert resp["selection"]["parts"] == ["box1"]
    assert resp["selection"]["by"] == "human"

    status, state1 = client.get("/api/state")
    assert state1["selection"]["parts"] == ["box1"]
    assert state1["selection"]["by"] == "human"
    assert state1["rev"] > rev0
    assert len(state1["history"]) == history_len0  # 不进操作记录

    status, resp = client.post("/api/select", {"parts": ["nope"]})
    assert status == 400
    assert resp["error"]["code"] == "unknown_part"


# --------------------------------------------------------------------- 5
# readiness 各状态（pass/warn/todo）至少各一例。
# ---------------------------------------------------------------------


def test_readiness_status_matrix():
    # 全 todo（什么都没跑过）。
    r = history.compute_readiness({}, delivered=False)
    assert r["passed"] == 0 and r["total"] == 6
    assert {it["key"]: it["status"] for it in r["items"]} == {
        "model": "todo",
        "orient": "todo",
        "arrange": "todo",
        "export": "todo",
        "check": "todo",
        "deliver": "todo",
    }

    all_pass_data = {
        "inspect": {"parts": [{"watertight": True, "fits_bed": True}], "warnings": []},
        "orient": {"parts": {"a": {"warnings": []}}},
        "arrange": {"plates": [{"index": 1}]},
        "export": {"plates": [{"unmatched_parts": [], "used_slice_fallback": False}]},
        "check": {"plates": [{"plate": 1, "grams": 118.0, "seconds": 25320, "warnings": [], "returncode": 0}]},
    }
    r = history.compute_readiness(all_pass_data, delivered=True)
    assert r["passed"] == 6
    assert all(it["status"] == "pass" for it in r["items"])

    # 对齐 SPEC_V05.md §2.2 的例子：4 个 pass、check 是 1 条警告的 warn、
    # deliver 还没发送过是 todo。
    check_warn_data = dict(all_pass_data)
    check_warn_data["check"] = {
        "plates": [{"plate": 1, "grams": 118.0, "seconds": 25320, "warnings": ["x"], "returncode": 0}],
    }
    r = history.compute_readiness(check_warn_data, delivered=False)
    by_key = {it["key"]: it for it in r["items"]}
    assert r["passed"] == 4 and r["total"] == 6
    assert by_key["check"]["status"] == "warn"
    assert by_key["check"]["detail"]
    assert by_key["deliver"]["status"] == "todo"

    # model / orient / export 各自的 warn 分支。
    warn_data = {
        "inspect": {"parts": [{"watertight": False, "fits_bed": True}], "warnings": []},
        "orient": {"parts": {"a": {"warnings": ["unstable_contact"]}}},
        "export": {"plates": [{"unmatched_parts": ["a"], "used_slice_fallback": False}]},
    }
    r = history.compute_readiness(warn_data, delivered=False)
    by_key = {it["key"]: it for it in r["items"]}
    assert by_key["model"]["status"] == "warn"
    assert by_key["orient"]["status"] == "warn"
    assert by_key["export"]["status"] == "warn"


def test_readiness_deliver_reflects_backend_delivered_flag(studio_env, tmp_path):
    client: Client = studio_env["client"]
    backend: StudioBackend = studio_env["backend"]
    _load_two_boxes(client, tmp_path)

    status, state = client.get("/api/state")
    deliver = next(it for it in state["readiness"]["items"] if it["key"] == "deliver")
    assert deliver["status"] == "todo"

    backend._delivered = True  # 等价于真的（非 dry-run）send 成功过一次
    status, state = client.get("/api/state")
    deliver = next(it for it in state["readiness"]["items"] if it["key"] == "deliver")
    assert deliver["status"] == "pass"


# --------------------------------------------------------------------- 6
# studio_meta.json 落盘后新建一个 backend 能读回 history / stale / step_actors。
# ---------------------------------------------------------------------


def test_studio_meta_persists_across_backend_instances(studio_env, tmp_path):
    client: Client = studio_env["client"]
    job_dir: Path = studio_env["job_dir"]
    _load_two_boxes(client, tmp_path)
    assert client.post("/api/orient", {}, headers={"X-Studio-Actor": "human"})[0] == 200
    assert client.post("/api/arrange", {})[0] == 200
    # 再 orient 一次，让 stale 里也有内容可验证。
    assert client.post("/api/orient", {"shape": "relief"})[0] == 200

    status, state_before = client.get("/api/state")
    assert state_before["stale"]  # 确认这次确实有 stale 内容，不是空对照

    new_backend = StudioBackend(job_dir, token="irrelevant-token-for-this-test")
    assert new_backend.history_store.public_history() == state_before["history"]
    assert new_backend.history_store.public_step_actors() == state_before["step_actors"]
    assert new_backend.history_store.public_stale() == state_before["stale"]


# --------------------------------------------------------------------- 7
# GET 系接口现在要求令牌（请求头；cookie 只给 events 与 part/*.stl）；/api/session 的
# Sec-Fetch-Site 校验与 Set-Cookie。
# ---------------------------------------------------------------------


def test_get_state_requires_token_header(studio_env):
    port = studio_env["port"]
    backend: StudioBackend = studio_env["backend"]

    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request("GET", "/api/state")
    resp = conn.getresponse()
    body = json.loads(resp.read())
    conn.close()
    assert resp.status == 403
    assert body["error"]["code"] == "forbidden"

    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request("GET", "/api/state", headers={"X-Studio-Token": backend.token})
    resp = conn.getresponse()
    body = json.loads(resp.read())
    conn.close()
    assert resp.status == 200 and body["ok"] is True

    # cookie 只给带不了请求头的两个 GET 用（/api/events、/api/part/*.stl）；其余 GET 只认请求头。
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request("GET", "/api/state", headers={"Cookie": f"studio_token={backend.token}"})
    resp = conn.getresponse()
    resp.read()
    conn.close()
    assert resp.status == 403


def test_cookie_only_works_for_events_and_part_stl(studio_env, tmp_path):
    client: Client = studio_env["client"]
    _load_two_boxes(client, tmp_path)
    port = studio_env["port"]
    backend: StudioBackend = studio_env["backend"]
    _, state = client.get("/api/state")
    stl_url = state["parts"][0]["stl_url"]

    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request("GET", stl_url, headers={"Cookie": f"studio_token={backend.token}"})
    resp = conn.getresponse()
    resp.read()
    conn.close()
    assert resp.status == 200

    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request("GET", stl_url)
    resp = conn.getresponse()
    resp.read()
    conn.close()
    assert resp.status == 403


def test_post_with_cookie_only_or_foreign_origin_is_rejected(studio_env, tmp_path):
    """盲审抓到的回归：SameSite=Strict 按站点算、端口不算，本机别的端口上的网页发 POST 会带上 cookie。
    写接口只认请求头令牌，并拒绝别的来源。"""
    client: Client = studio_env["client"]
    _load_two_boxes(client, tmp_path)
    port = studio_env["port"]
    backend: StudioBackend = studio_env["backend"]

    def post(headers):
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request("POST", "/api/orient", body=b"{}", headers=headers)
        resp = conn.getresponse()
        body = json.loads(resp.read())
        conn.close()
        return resp.status, body

    status, body = post({"Cookie": f"studio_token={backend.token}", "Content-Type": "text/plain"})
    assert status == 403 and body["error"]["code"] == "forbidden"

    status, body = post(
        {"X-Studio-Token": backend.token, "Origin": "http://127.0.0.1:9999", "Content-Type": "application/json"}
    )
    assert status == 403 and body["error"]["code"] == "bad_origin"

    status, body = post(
        {"X-Studio-Token": backend.token, "Sec-Fetch-Site": "same-site", "Content-Type": "application/json"}
    )
    assert status == 403 and body["error"]["code"] == "bad_origin"

    _, state = client.get("/api/state")
    assert state["steps"]["orient"] is False  # 上面三次都没有真的执行

    status, body = post(
        {
            "X-Studio-Token": backend.token,
            "Origin": f"http://127.0.0.1:{port}",
            "Sec-Fetch-Site": "same-origin",
            "Content-Type": "application/json",
        }
    )
    assert status == 200 and body["ok"] is True


def test_undo_of_the_only_orient_is_not_reported_as_stale_and_load_clears_selection(studio_env, tmp_path):
    client: Client = studio_env["client"]
    _load_two_boxes(client, tmp_path)
    assert client.post("/api/orient", {})[0] == 200
    assert client.post("/api/select", {"parts": ["box1"]})[0] == 200
    assert client.post("/api/undo", {})[0] == 200
    _, state = client.get("/api/state")
    assert state["steps"]["orient"] is False
    assert "orient" not in state["stale"]
    assert state["selection"]["parts"] == ["box1"]

    _load_two_boxes(client, tmp_path)
    _, state = client.get("/api/state")
    assert state["selection"]["parts"] == []


def test_damaged_meta_file_does_not_block_startup(tmp_path):
    job_dir = tmp_path / "job"
    job_dir.mkdir()
    (job_dir / "studio_meta.json").write_text("[1, 2, 3]")
    store = history.HistoryStore(job_dir)
    assert store.public_history() == []
    (job_dir / "studio_meta.json").write_text(
        json.dumps({"history": [{"id": 1, "undoable": True}], "undo_snapshots": {"x": {}}})
    )
    store = history.HistoryStore(job_dir)
    assert store.public_history()[0]["undoable"] is False


def test_session_rejects_cross_site_and_sets_cookie(studio_env):
    port = studio_env["port"]

    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request("GET", "/api/session", headers={"Sec-Fetch-Site": "cross-site"})
    resp = conn.getresponse()
    body = json.loads(resp.read())
    conn.close()
    assert resp.status == 403
    assert body["error"]["code"] == "bad_origin"

    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request("GET", "/api/session", headers={"Sec-Fetch-Site": "same-origin"})
    resp = conn.getresponse()
    resp.read()
    set_cookie = resp.getheader("Set-Cookie")
    conn.close()
    assert resp.status == 200
    assert set_cookie is not None
    assert "studio_token=" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "SameSite=Strict" in set_cookie


# --------------------------------------------------------------------- 8
# HTTP tools_schema 包含打印、编辑与观察操作。
# ---------------------------------------------------------------------


def test_tools_schema_has_print_and_editor_operations():
    tools = tools_schema.get_tools()
    names = {t["name"] for t in tools}
    assert {"studio_select", "studio_undo"}.issubset(names)
    assert "studio_edit" in names
    assert "studio_observe" in names
    assert "studio_evaluation" in names
    assert "studio_services" in names
    assert len(tools) == 22


def test_api_tools_endpoint_reports_print_and_editor_tools(studio_env):
    client: Client = studio_env["client"]
    status, resp = client.get("/api/tools")
    assert status == 200
    assert len(resp["tools"]) == 22
    names = {t["name"] for t in resp["tools"]}
    assert "studio_evaluation" in names
    assert "studio_observe" in names
    assert {"studio_select", "studio_undo"}.issubset(names)
