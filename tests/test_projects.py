import asyncio
import json
import shutil
import subprocess

import pytest

from studio.core import projects, workspaces
from tests.helpers import mcp_call


@pytest.mark.anyio
async def test_folder_project_shared_views_conflict_undo_and_restart(mcp_session, tmp_path):
    folder = tmp_path / "Robot"
    folder.mkdir()

    async def connect(who):
        return await mcp_call(mcp_session, "studio_workspaces", who, action="open_project", worktree=str(folder))

    a, b = await asyncio.gather(connect("folder-a"), connect("folder-b"))
    assert a["project_id"] == b["project_id"]
    assert a["job"] == str(folder / ".3dstudio/job")
    await mcp_call(mcp_session, "studio_edit", "folder-a", action="primitive", expected_revision=0)
    await mcp_call(mcp_session, "studio_edit", "folder-b", action="primitive", expected_revision=1)
    state = (await mcp_call(mcp_session, "studio_get_state", "folder-a"))["workbench"]
    x, y = [o["id"] for o in state["objects"]]
    assert state["project_folder"] == str(folder)
    await mcp_call(
        mcp_session,
        "studio_edit",
        "folder-a",
        action="rename",
        expected_revision=1,
        expected_versions={x: 1},
        params={"ids": [x], "name": "arm"},
    )
    await mcp_call(
        mcp_session,
        "studio_edit",
        "folder-b",
        action="rename",
        expected_revision=2,
        expected_versions={y: 1},
        params={"ids": [y], "name": "shell"},
    )
    rejected = await mcp_session.call_tool(
        "studio_edit",
        {
            "workspace_id": "folder-a",
            "action": "rename",
            "expected_revision": 4,
            "params": {"ids": [y], "name": "overwrite"},
        },
    )
    assert rejected.is_error and "part_locked" in rejected.content[0].text
    await mcp_call(mcp_session, "studio_edit", "folder-a", action="undo", expected_revision=4)
    aa = (await mcp_call(mcp_session, "studio_get_state", "folder-a"))["workbench"]
    bb = (await mcp_call(mcp_session, "studio_get_state", "folder-b"))["workbench"]
    assert aa["objects"] == bb["objects"] and aa["selection"] != bb["selection"]
    assert next(o for o in aa["objects"] if o["id"] == y)["name"] == "shell"
    import studio

    studio.stop_server(home=workspaces.home(a["project_id"]))
    restored = (await mcp_call(mcp_session, "studio_get_state", "folder-b"))["workbench"]
    assert restored["objects"] == bb["objects"]
    assert (folder / ".3dstudio/project.json").is_file()
    assert not list((folder / ".3dstudio").rglob("studio.json"))


@pytest.mark.anyio
async def test_folder_copy_preserves_source_and_scoped_chat(mcp_session, tmp_path):
    await mcp_call(mcp_session, "studio_edit", "legacy-owner", action="primitive", expected_revision=0)
    source_path = workspaces.job_dir("legacy-owner") / "workbench/project.json"
    before = source_path.read_bytes()
    path = tmp_path / "adopted"
    path.mkdir()
    await mcp_call(
        mcp_session,
        "studio_workspaces",
        "legacy-owner",
        action="open_project",
        worktree=str(path),
        source_id="legacy-owner",
        expected_revision=1,
    )
    assert source_path.read_bytes() == before
    state = (await mcp_call(mcp_session, "studio_get_state", "legacy-owner"))["workbench"]
    part = state["objects"][0]["id"]
    invitation = await mcp_call(
        mcp_session,
        "studio_workspaces",
        "legacy-owner",
        action="invite",
        worktree=str(path),
        object_id=part,
        expected_revision=0,
    )
    await mcp_call(
        mcp_session,
        "studio_workspaces",
        "part-child",
        action="join",
        source_id="legacy-owner",
        invitation=invitation["invitation"],
        worktree=str(path),
    )
    await mcp_call(mcp_session, "studio_workspaces", "part-child", action="open_project", worktree=str(path))
    child = (await mcp_call(mcp_session, "studio_get_state", "part-child"))["workbench"]
    assert child["collaboration"]["scope"] == [part]
    other = tmp_path / "independent"
    other.mkdir()
    await mcp_call(
        mcp_session,
        "studio_workspaces",
        "branch-chat",
        action="open_project",
        worktree=str(other),
        source_id="legacy-owner",
        expected_revision=0,
    )
    await mcp_call(
        mcp_session,
        "studio_edit",
        "branch-chat",
        action="rename",
        expected_revision=0,
        params={"ids": [part], "name": "variant"},
    )
    original = (await mcp_call(mcp_session, "studio_get_state", "legacy-owner"))["workbench"]
    assert original["objects"][0]["name"] != "variant"
    await mcp_call(mcp_session, "studio_workspaces", "part-child", action="release", ids=[part])
    merged = await mcp_call(mcp_session, "studio_workspaces", "branch-chat", action="merge", expected_revision=0)
    assert merged["merged_ids"] == [part]


@pytest.mark.anyio
async def test_copied_git_worktree_uses_new_runtime_and_members(mcp_session, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    sub = repo / "models"
    sub.mkdir()
    a = await mcp_call(mcp_session, "studio_workspaces", "git-a", action="open_project", worktree=str(sub))
    await mcp_call(mcp_session, "studio_edit", "git-a", action="primitive", expected_revision=0)
    # A copied project must never retain source collaborators or leases.
    copied = tmp_path / "copy"
    copied.mkdir()
    shutil.copytree(repo / ".3dstudio", copied / ".3dstudio")
    b = await mcp_call(mcp_session, "studio_workspaces", "git-b", action="open_project", worktree=str(copied))
    assert a["project_id"] != b["project_id"] and a["folder"] == str(repo)
    state = (await mcp_call(mcp_session, "studio_get_state", "git-b"))["workbench"]
    assert state["collaboration"]["members"] == 1 and state["objects"][0]["lease"] is None
    await mcp_call(
        mcp_session,
        "studio_edit",
        "git-b",
        action="rename",
        expected_revision=1,
        params={"ids": [state["objects"][0]["id"]], "name": "copy"},
    )
    assert (await mcp_call(mcp_session, "studio_get_state", "git-a"))["workbench"]["objects"][0]["name"] != "copy"


def test_new_codex_task_auto_attaches_once_without_scope_widening(tmp_path, monkeypatch):
    monkeypatch.setenv("PRINT_PREP_HOME", str(tmp_path / "runtime"))
    who = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    calls = []
    monkeypatch.setattr(projects, "thread_folder", lambda task: tmp_path)
    monkeypatch.setattr(projects, "open_project", lambda task, directory: calls.append((task, directory)))
    projects.auto_attach(who)
    assert calls == [(who, str(tmp_path))]
    workspaces.home(who).mkdir(parents=True)
    (workspaces.home(who) / "binding.json").write_text(json.dumps({"project_id": "owner"}))
    projects.auto_attach(who)
    assert len(calls) == 1


@pytest.mark.anyio
async def test_fork_from_listed_folder_id_merges_through_owner(mcp_session, tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    result = await mcp_call(
        mcp_session, "studio_workspaces", "source-chat", action="open_project", worktree=str(source)
    )
    await mcp_call(mcp_session, "studio_edit", "source-chat", action="primitive", expected_revision=0)
    state = (await mcp_call(mcp_session, "studio_get_state", "source-chat"))["workbench"]
    part = state["objects"][0]["id"]
    target = tmp_path / "variant"
    target.mkdir()
    await mcp_call(
        mcp_session,
        "studio_workspaces",
        "variant-chat",
        action="open_project",
        worktree=str(target),
        source_id=result["project_id"],
        expected_revision=1,
    )
    await mcp_call(
        mcp_session,
        "studio_edit",
        "variant-chat",
        action="rename",
        expected_revision=0,
        params={"ids": [part], "name": "merged"},
    )
    await mcp_call(mcp_session, "studio_workspaces", "source-chat", action="release", ids=[part])
    await mcp_call(mcp_session, "studio_workspaces", "variant-chat", action="merge", expected_revision=1)
    assert (await mcp_call(mcp_session, "studio_get_state", "source-chat"))["workbench"]["objects"][0][
        "name"
    ] == "merged"


def test_project_rejects_linked_storage(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    target = tmp_path / "target"
    target.mkdir()
    (target / ".3dstudio").symlink_to(source, target_is_directory=True)
    with pytest.raises(ValueError, match="软链接"):
        projects.location_job({"folder": str(target), "project_id": projects.key(target)})


def test_open_project_already_bound_names_workspace_id_workaround(tmp_path, monkeypatch):
    """The `already_bound_to_other_project` message must itself name the way out
    for a Claude Code multi-session setup (every conversation otherwise shares
    the one fixed `install.sh --claude` workspace id, per README.md): give this
    session its own id via `CLAUDE_WORKSPACE_ID` (before `install.sh`) or
    `PRINT_PREP_WORKSPACE_ID` (directly on the MCP server)."""
    monkeypatch.setenv("PRINT_PREP_HOME", str(tmp_path / "runtime"))
    workspace_id = "claude-code"
    folder_a = tmp_path / "a"
    folder_a.mkdir()
    folder_b = tmp_path / "b"
    folder_b.mkdir()

    workspaces.home(workspace_id).mkdir(parents=True)
    (workspaces.home(workspace_id) / "binding.json").write_text(
        json.dumps({"project_id": projects.key(folder_a.resolve())})
    )

    with pytest.raises(ValueError) as exc_info:
        projects.open_project(workspace_id, str(folder_b))
    message = str(exc_info.value)
    assert "PRINT_PREP_WORKSPACE_ID" in message
    assert "CLAUDE_WORKSPACE_ID" in message


def test_removed_folder_does_not_break_workspace_listing(tmp_path, monkeypatch):
    monkeypatch.setenv("PRINT_PREP_HOME", str(tmp_path / "runtime"))
    path = tmp_path / "removed"
    project_id = projects.key(path)
    workspaces.home(project_id).mkdir(parents=True)
    (workspaces.home(project_id) / "project-location.json").write_text(
        json.dumps({"folder": str(path), "project_id": project_id})
    )
    item = next(x for x in workspaces.list_workspaces() if x["id"] == project_id)
    assert item["available"] is False
