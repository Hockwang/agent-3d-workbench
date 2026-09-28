import json
import uuid

import pytest

from studio.core import collaboration as c, workspaces
from studio.shell import part_chat as pc
from studio.core.editor import Workspace, EditorError

PARENT = "11111111-1111-4111-8111-111111111111"
CHILD = "22222222-2222-4222-8222-222222222222"


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv("PRINT_PREP_HOME", str(tmp_path / "studio"))
    w = Workspace(workspaces.job_dir(PARENT) / "workbench")
    w.execute({"action": "primitive", "expected_revision": 0})
    w.execute({"action": "primitive", "expected_revision": 1})
    token = c.SESSION.set(PARENT)

    class Bridge:
        forks = 0
        mode = None

        def __init__(self, *args):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self, key):
            return {"id": key, "cwd": str(tmp_path), "forkedFromId": PARENT if key == CHILD else None}

        def fork(self, parent, cwd, callback):
            Bridge.forks += 1
            if Bridge.mode == "timeout":
                raise RuntimeError("timeout")
            child = self.read(CHILD)
            callback(child)
            if Bridge.mode == "after_started":
                raise RuntimeError("response lost")
            return child

        def rename(self, child, name):
            pass

    monkeypatch.setattr(pc, "CodexBridge", Bridge)
    adapter = {"executable": "/verified/codex", "home": str(tmp_path), "version": "0.154.0"}
    monkeypatch.setattr(pc, "identity", lambda: adapter.copy())
    body = {
        "action": "create",
        "object_id": w.doc["objects"][0]["id"],
        "expected_revision": 2,
        "operation_id": str(uuid.uuid4()),
    }
    yield w, Bridge, body, adapter
    c.SESSION.reset(token)


def call(w, body):
    return pc.handle(w, body, "human")


def test_consent_scope_revoke_and_no_model_calls(setup):
    w, bridge, body, adapter = setup
    assert call(w, {"action": "status"})["decision"] == "ask"
    with pytest.raises(EditorError, match="允许"):
        call(w, body)
    assert bridge.forks == 0
    with pytest.raises(EditorError, match="工作台"):
        pc.handle(w, {"action": "allow"}, "ai")
    call(w, {"action": "allow"})
    result = call(w, body)
    assert result["status"] == "bound" and result["child_id"] == CHILD
    assert workspaces.project_id(CHILD) == PARENT
    assert c.SESSION.get() == PARENT  # Coordinator never impersonates child.
    with_child = c.SESSION.set(CHILD)
    try:
        state = w.state()
        assert state["selection"] == [body["object_id"]] and state["collaboration"]["scope"] == [body["object_id"]]
        other = next(o["id"] for o in w.doc["objects"] if o["id"] != body["object_id"])
        with pytest.raises(EditorError, match="绑定零件"):
            w.execute({"action": "rename", "expected_revision": 2, "params": {"ids": [other], "name": "outside"}})
        w.execute(
            {"action": "rename", "expected_revision": 2, "params": {"ids": [body["object_id"]], "name": "child repair"}}
        )
    finally:
        c.SESSION.reset(with_child)
    assert w.state()["objects"][0]["name"] == "child repair"
    call(w, {"action": "deny"})
    with pytest.raises(EditorError, match="允许"):
        call(w, body)
    assert workspaces.project_id(CHILD) == PARENT
    assert bridge.forks == 1


def test_duplicate_click_same_or_new_operation_returns_existing_child(setup):
    w, bridge, body, _ = setup
    call(w, {"action": "allow"})
    first = call(w, body)
    assert call(w, body) == first
    assert call(w, {**body, "operation_id": str(uuid.uuid4())})["child_id"] == CHILD
    assert bridge.forks == 1
    with pytest.raises(EditorError, match="另一个零件"):
        call(w, {**body, "object_id": w.doc["objects"][1]["id"]})


def test_timeout_is_durable_and_never_reforks(setup):
    w, bridge, body, _ = setup
    call(w, {"action": "allow"})
    bridge.mode = "timeout"
    assert call(w, body)["status"] == "uncertain"
    bridge.mode = None
    assert call(w, body)["status"] == "uncertain"
    assert call(w, {**body, "operation_id": str(uuid.uuid4())})["status"] == "uncertain"
    assert bridge.forks == 1


def test_started_notification_persists_child_and_retry_only_binds(setup):
    w, bridge, body, _ = setup
    call(w, {"action": "allow"})
    bridge.mode = "after_started"
    result = call(w, body)
    assert result["status"] == "binding_failed" and result["child_id"] == CHILD
    bridge.mode = None
    assert call(w, body)["status"] == "bound" and bridge.forks == 1


def test_source_revision_child_lineage_and_target_project_protected(setup, monkeypatch):
    w, bridge, body, _ = setup
    call(w, {"action": "allow"})
    before = w.path.read_bytes()
    with pytest.raises(EditorError, match="工程已改变"):
        call(w, {**body, "expected_revision": 0})
    assert w.path.read_bytes() == before and bridge.forks == 0
    Workspace(workspaces.job_dir(CHILD) / "workbench")
    result = call(w, body)
    assert result["status"] == "binding_failed" and "已有独立工程" in result["message"]
    assert workspaces.project_id(CHILD) == CHILD
    with pytest.raises(EditorError, match="来源不一致"):
        pc._verify_thread({"id": CHILD, "cwd": str(w.root), "forkedFromId": "wrong"}, CHILD, parent=PARENT)


def test_permission_invalidated_by_adapter_identity_change(setup):
    w, bridge, body, adapter = setup
    call(w, {"action": "allow"})
    adapter["home"] = "/another-home"
    assert call(w, {"action": "status"})["enabled"] is False
    with pytest.raises(EditorError, match="允许"):
        call(w, body)
    assert bridge.forks == 0


def test_no_public_child_or_arbitrary_rpc_arguments(setup):
    w, _, _, _ = setup
    for body in (
        {"action": "allow", "child_id": CHILD},
        {"action": "thread/delete"},
        {"action": "allow", "command": "oops"},
    ):
        with pytest.raises(EditorError, match="无效"):
            call(w, body)
    foreign = c.SESSION.set(CHILD)
    try:
        with pytest.raises(EditorError, match="不属于"):
            call(w, {"action": "allow"})
    finally:
        c.SESSION.reset(foreign)


def test_expired_invite_retry_uses_existing_child_with_fresh_part_version(setup):
    w, bridge, body, _ = setup
    call(w, {"action": "allow"})
    bridge.mode = "after_started"
    call(w, body)
    for invite in w.doc["collaboration"]["invitations"].values():
        invite["expires_at"] = 0
    w.execute({"action": "rename", "expected_revision": 2, "params": {"ids": [body["object_id"]], "name": "new"}})
    bridge.mode = None
    assert call(w, {**body, "expected_revision": 3})["status"] == "bound"
    assert bridge.forks == 1


def test_folder_project_chat_in_git_subdirectory_forks_at_exact_cwd(setup, tmp_path, monkeypatch):
    import subprocess
    from studio.core import projects

    _, bridge, body, _ = setup
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    sub = repo / "models"
    sub.mkdir()
    project_id = projects.key(repo.resolve())
    workspaces.home(project_id).mkdir(parents=True)
    (workspaces.home(project_id) / "project-location.json").write_text(
        json.dumps({"folder": str(repo), "project_id": project_id})
    )
    (workspaces.home(PARENT) / "binding.json").write_text(json.dumps({"project_id": project_id, "worktree": str(repo)}))
    w = Workspace(workspaces.job_dir(PARENT) / "workbench")
    w.execute({"action": "primitive", "expected_revision": 0})
    c.control(w, {"action": "project_join", "worktree": str(repo)})

    def read(self, key):
        return {"id": key, "cwd": str(sub), "forkedFromId": PARENT if key == CHILD else None}

    monkeypatch.setattr(bridge, "read", read)
    call(w, {"action": "allow"})
    result = call(w, {**body, "object_id": w.doc["objects"][0]["id"], "expected_revision": 1})
    assert result["status"] == "bound" and bridge.forks == 1
    assert w.doc["collaboration"]["worktree"] == str(repo.resolve())
    assert w.doc["collaboration"]["members"][CHILD]["scope"] == [w.doc["objects"][0]["id"]]
