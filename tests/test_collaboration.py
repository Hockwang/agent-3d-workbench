import copy

import pytest
from studio.core.editor import Workspace, EditorError
from studio.core import collaboration as c
from studio.core import workspaces
from tests.helpers import session


@pytest.fixture
def shared(tmp_path):
    w = Workspace(tmp_path / "project")
    for n in range(2):
        w.execute({"action": "primitive", "expected_revision": n})
    a, b = [o["id"] for o in w.doc["objects"]]
    with session("owner"):
        invite = c.control(w, {"action": "invite", "object_id": a, "worktree": str(tmp_path), "expected_revision": 2})
    with session("child"):
        c.control(w, {"action": "join", "worktree": str(tmp_path), "invitation": invite["invitation"]})
    return w, a, b, tmp_path


def edit(w, key, part, name, revision=2, version=0):
    with session(key):
        return w.execute(
            {
                "action": "rename",
                "expected_revision": revision,
                "expected_versions": {part: version},
                "params": {"ids": [part], "name": name},
            }
        )


def test_two_chats_edit_different_parts_and_keep_selection_and_undo(shared):
    w, a, b, _ = shared
    with session("owner"):
        w.execute({"action": "select", "expected_revision": 2, "params": {"ids": [b]}})
    edit(w, "child", a, "child A")
    edit(w, "owner", b, "owner B")  # Same old project revision is valid for untouched B.
    with session("child"):
        state = w.state()
        assert state["selection"] == [a]
        assert {o["name"] for o in state["objects"]} == {"child A", "owner B"}
        w.execute({"action": "undo", "expected_revision": 4})
        assert next(o for o in w.doc["objects"] if o["id"] == b)["name"] == "owner B"
        w.execute({"action": "redo", "expected_revision": 5})
        assert next(o for o in w.doc["objects"] if o["id"] == a)["name"] == "child A"
    with session("owner"):
        assert w.state()["selection"] == [b]


def test_lease_scope_and_stale_revision_fail_without_mutation(shared):
    w, a, b, _ = shared
    before = w.path.read_bytes()
    with pytest.raises(EditorError, match="正由任务"):
        edit(w, "owner", a, "overwrite")
    with pytest.raises(EditorError, match="绑定零件"):
        edit(w, "child", b, "outside")
    assert w.path.read_bytes() == before
    edit(w, "child", a, "first")
    w.doc["collaboration"]["leases"][a]["expires_at"] = 0
    with pytest.raises(EditorError, match="零件已改变"):
        edit(w, "owner", a, "stale")
    edit(w, "owner", a, "newer", version=1)
    with session("child"), pytest.raises(EditorError, match="后续修改"):
        w.execute({"action": "undo", "expected_revision": w.doc["revision"]})


def test_late_heartbeat_does_not_reacquire_or_steal_released_part(shared):
    w, a, _, _ = shared
    with session("child"):
        c.control(w, {"action": "release", "ids": [a]})
        c.control(w, {"action": "renew", "ids": [a]})
    assert a not in w.doc["collaboration"]["leases"]
    edit(w, "owner", a, "next editor")
    lease = copy.deepcopy(w.doc["collaboration"]["leases"][a])
    with session("child"):
        c.control(w, {"action": "renew", "ids": [a]})
    assert w.doc["collaboration"]["leases"][a] == lease


def test_split_descendants_stay_in_chat_scope_and_other_parts_untouched(shared):
    w, a, b, _ = shared
    with session("child"):
        w.execute({"action": "duplicate", "expected_revision": 2, "params": {"ids": [a]}})
        state = w.state()
        child = next(o for o in state["objects"] if o["id"] not in (a, b))
        assert child["id"] in state["collaboration"]["scope"]
        w.execute(
            {
                "action": "transform",
                "expected_revision": 3,
                "params": {"ids": [child["id"]], "translate_mm": [10, 0, 0]},
            }
        )
        with pytest.raises(EditorError, match="绑定零件"):
            w.execute({"action": "primitive", "expected_revision": 4})


def test_join_is_single_use_same_worktree_and_persistent(shared):
    w, a, b, root = shared
    with session("owner"):
        invite = c.control(w, {"action": "invite", "object_id": b, "worktree": str(root), "expected_revision": 2})
    other = root / "another"
    other.mkdir()
    with session("second"), pytest.raises(EditorError, match="不同 worktree"):
        c.control(w, {"action": "join", "worktree": str(other), "invitation": invite["invitation"]})
    with session("second"):
        c.control(w, {"action": "join", "worktree": str(root), "invitation": invite["invitation"]})
    with session("third"), pytest.raises(EditorError, match="邀请无效"):
        c.control(w, {"action": "join", "worktree": str(root), "invitation": invite["invitation"]})
    with session("second"):
        assert Workspace(w.root).state()["selection"] == [b]
    with session(None), pytest.raises(EditorError, match="尚未绑定"):
        w.execute({"action": "primitive", "expected_revision": 2})


def test_fork_drops_shared_members_and_binding_never_overwrites_project(shared, monkeypatch):
    w, a, b, root = shared
    monkeypatch.setenv("PRINT_PREP_HOME", str(root))
    source = workspaces.home("owner") / "job" / "workbench"
    source.mkdir(parents=True)
    workspaces.copy_assets(w.doc["objects"], w.root / "assets", source / "assets")
    workspaces.fork("separate", "owner", copy.deepcopy(w.doc))
    assert "collaboration" not in Workspace(workspaces.job_dir("separate") / "workbench").doc
    with pytest.raises(ValueError, match="已有独立工程"):
        workspaces.bind("separate", "owner", lambda: {"ok": True})


def test_multiple_undo_redo_and_reload(shared):
    w, a, b, _ = shared
    original = next(o["name"] for o in w.doc["objects"] if o["id"] == a)
    edit(w, "child", a, "one")
    edit(w, "child", a, "two", revision=3, version=1)
    w = Workspace(w.root)
    with session("child"):
        for action, expected in [("undo", "one"), ("undo", original), ("redo", "one"), ("redo", "two")]:
            w.execute({"action": action, "expected_revision": w.doc["revision"]})
            assert next(o["name"] for o in w.doc["objects"] if o["id"] == a) == expected


def test_interleaved_parts_undo_redo_after_reload(shared):
    w, _, b, _ = shared
    original = next(o["name"] for o in w.doc["objects"] if o["id"] == b)
    with session("owner"):
        for action, params in [
            ("rename", {"ids": [b], "name": "one"}),
            ("primitive", {}),
            ("rename", {"ids": [b], "name": "two"}),
        ]:
            w.execute({"action": action, "params": params, "expected_revision": w.doc["revision"]})
        for action, name, count in [
            ("undo", "one", 3),
            ("undo", "one", 2),
            ("undo", original, 2),
            ("redo", "one", 2),
            ("redo", "one", 3),
            ("redo", "two", 3),
        ]:
            w = Workspace(w.root)
            w.execute({"action": action, "expected_revision": w.doc["revision"]})
            assert next(o["name"] for o in w.doc["objects"] if o["id"] == b) == name
            assert len(w.doc["objects"]) == count


def test_interleaved_undo_still_rejects_foreign_edits(shared):
    w, _, b, root = shared
    with session("owner"):
        w.execute({"action": "rename", "params": {"ids": [b], "name": "owner"}, "expected_revision": 2})
        w.execute({"action": "primitive", "expected_revision": 3})
        invite = c.control(w, {"action": "invite", "object_id": b, "worktree": str(root), "expected_revision": 4})
    with session("third"):
        c.control(w, {"action": "join", "worktree": str(root), "invitation": invite["invitation"]})
        w.execute({"action": "rename", "params": {"ids": [b], "name": "third"}, "expected_revision": 4})
        c.control(w, {"action": "release", "ids": [b]})
    with session("owner"):
        w.execute({"action": "undo", "expected_revision": 5})
        before = w.path.read_bytes()
        with pytest.raises(EditorError) as exc:
            w.execute({"action": "undo", "expected_revision": 6})
        assert exc.value.code == "revision_conflict"
        assert w.path.read_bytes() == before


def test_external_repair_can_replace_owned_part_and_undo_preserves_other_part(shared):
    import trimesh

    w, a, b, root = shared
    mesh = trimesh.creation.box([10, 12, 14])
    mesh.apply_translation([30, 40, 50])
    path = root / "repaired.stl"
    mesh.export(path)
    before_b = copy.deepcopy(next(o for o in w.doc["objects"] if o["id"] == b))
    with session("child"):
        w.execute({"action": "replace", "expected_revision": 2, "params": {"ids": [a], "files": [str(path)]}})
        obj = next(o for o in w.state()["objects"] if o["id"] == a)
        assert obj["bounds_mm"] == [[25.0, 34.0, 43.0], [35.0, 46.0, 57.0]]
        assert next(o for o in w.doc["objects"] if o["id"] == b) == before_b
        w.execute({"action": "undo", "expected_revision": 3})
        assert len(w.doc["objects"]) == 2


def test_glb_export_replace_roundtrip_preserves_world_bounds(shared):
    import numpy as np

    w, a, b, _ = shared
    with session("child"):
        w.execute(
            {
                "action": "transform",
                "expected_revision": 2,
                "params": {"ids": [a], "translate_mm": [30, -20, 45], "rotate_deg": [15, 0, 30]},
            }
        )
        original = next(o["bounds_mm"] for o in w.state()["objects"] if o["id"] == a)
        export = w.execute({"action": "export", "expected_revision": 3, "params": {"ids": [a], "format": "glb"}})
        w.execute({"action": "replace", "expected_revision": 3, "params": {"ids": [a], "files": [export["path"]]}})
        updated = next(o["bounds_mm"] for o in w.state()["objects"] if o["id"] == a)
        np.testing.assert_allclose(updated, original, atol=1e-4)
