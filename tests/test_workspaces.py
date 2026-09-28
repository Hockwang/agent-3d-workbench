import asyncio
import copy
import sys

import pytest
from mcp import ClientSession, StdioServerParameters, stdio_client

from studio.core.editor import Workspace, EditorError
from studio.core import branches, workspaces
from tests.helpers import MCP_SERVER_SCRIPT, mcp_call


@pytest.mark.anyio
async def test_sessions_and_resources_are_isolated_and_fork_merge_is_checked(mcp_session):
    await mcp_call(mcp_session, "studio_edit", "task-a", action="primitive", expected_revision=0)
    await mcp_call(
        mcp_session, "studio_edit", "task-a", action="primitive", expected_revision=1, params={"shape": "sphere"}
    )
    a = (await mcp_call(mcp_session, "studio_get_state", "task-a"))["workbench"]
    b = (await mcp_call(mcp_session, "studio_get_state", "task-b"))["workbench"]
    assert len(a["objects"]) == 2 and b["objects"] == [] and b["history"] == []
    first, second = [o["id"] for o in a["objects"]]
    uri = f"print-prep://editor/{a['objects'][0]['asset']}?workspace=task-a"
    assert (await mcp_session.read_resource(uri)).contents[0].blob
    with pytest.raises(Exception, match="网格已不在当前工程"):
        await mcp_session.read_resource(uri.replace("task-a", "task-b"))
    await mcp_call(mcp_session, "studio_workspaces", "task-c", action="fork", source_id="task-a", expected_revision=2)
    await mcp_call(
        mcp_session,
        "studio_edit",
        "task-a",
        action="rename",
        expected_revision=2,
        params={"ids": [first], "name": "A changed"},
    )
    await mcp_call(
        mcp_session,
        "studio_edit",
        "task-c",
        action="rename",
        expected_revision=0,
        params={"ids": [second], "name": "C changed"},
    )
    merged = await mcp_call(mcp_session, "studio_workspaces", "task-c", action="merge", expected_revision=3)
    assert merged["merged_ids"] == [second]
    state = (await mcp_call(mcp_session, "studio_get_state", "task-a"))["workbench"]
    assert {o["name"] for o in state["objects"]} == {"A changed", "C changed"}
    assert state["can_undo"]
    # Idempotent re-application never creates a duplicate edit.
    same = await mcp_call(mcp_session, "studio_workspaces", "task-c", action="merge", expected_revision=4)
    assert same["merged_ids"] == [] and same["revision"] == 4
    await mcp_call(
        mcp_session,
        "studio_edit",
        "task-a",
        action="rename",
        expected_revision=4,
        params={"ids": [second], "name": "A newer"},
    )
    await mcp_call(
        mcp_session,
        "studio_edit",
        "task-c",
        action="rename",
        expected_revision=1,
        params={"ids": [second], "name": "C newer"},
    )
    before = await mcp_call(mcp_session, "studio_get_state", "task-a")
    rejected = await mcp_session.call_tool(
        "studio_workspaces", {"workspace_id": "task-c", "action": "merge", "expected_revision": 5}
    )
    assert rejected.is_error and "branch_conflict" in rejected.content[0].text
    after = await mcp_call(mcp_session, "studio_get_state", "task-a")
    assert before["workbench"] == after["workbench"]
    # Forks cannot replace an already-opened target, even if empty.
    rejected = await mcp_session.call_tool(
        "studio_workspaces", {"workspace_id": "task-b", "action": "fork", "source_id": "task-a", "expected_revision": 5}
    )
    assert rejected.is_error


@pytest.mark.anyio
async def test_missing_binding_refuses_shared_write_and_reconnect_uses_same_workspace(mcp_home):
    params = StdioServerParameters(
        command=sys.executable, args=[str(MCP_SERVER_SCRIPT)], env={"PRINT_PREP_HOME": str(mcp_home)}
    )
    for iteration in range(2):
        async with stdio_client(params) as streams:
            async with ClientSession(*streams) as client:
                await client.initialize()
                rejected = await client.call_tool("studio_edit", {"action": "primitive", "expected_revision": 0})
                assert rejected.is_error and "workspace_id" in rejected.content[0].text
                if iteration == 0:
                    await mcp_call(client, "studio_edit", "persistent-task", action="primitive", expected_revision=0)
                state = await mcp_call(client, "studio_get_state", "persistent-task")
                assert state["workbench"]["revision"] == 1 and len(state["workbench"]["objects"]) == 1
    assert not (mcp_home / "job").exists()


@pytest.mark.anyio
async def test_historical_ui_uri_is_a_compatible_launcher(mcp_session):
    for suffix in ("7df60a3ddd256d1757e7", "5a52481e845e6884392e"):
        uri = f"ui://print-prep/studio-{suffix}.html?workspace=my-task"
        resource = (await mcp_session.read_resource(uri)).contents[0]
        assert 'data-workspace-id="my-task"' in resource.text
        assert 'id="workspace-error"' in resource.text
    with pytest.raises(Exception):
        await mcp_session.read_resource("ui://print-prep/studio-../../bad.html")


def test_legacy_fork_preserves_source_and_copies_immutable_assets(tmp_path, monkeypatch):
    monkeypatch.setenv("PRINT_PREP_HOME", str(tmp_path))
    source = Workspace(tmp_path / "job" / "workbench")
    source.execute({"action": "primitive", "expected_revision": 0})
    before = source.path.read_bytes()
    snapshot = copy.deepcopy(source.doc)
    workspaces.fork("new-task", "legacy", snapshot)
    fork = Workspace(workspaces.job_dir("new-task") / "workbench")
    assert fork.doc["objects"] == source.doc["objects"]
    assert fork.doc["revision"] == 0 and fork.doc["undo"] == []
    assert source.path.read_bytes() == before
    asset = source.doc["objects"][0]["asset"]
    assert fork.asset_bytes(asset) == source.asset_bytes(asset)
    with pytest.raises(ValueError):
        workspaces.validate_id("../job")


def test_three_way_merge_handles_delete_add_and_same_change():
    a, b = {"id": "a", "name": "old"}, {"id": "b", "name": "new"}
    merged, ids = branches.changes([a], [b], [a])
    assert merged == [b] and set(ids) == {"a", "b"}
    merged, ids = branches.changes([a], [b], [b])
    assert merged == [b] and ids == []
    with pytest.raises(EditorError, match="不能覆盖"):
        branches.changes([a], [], [{"id": "a", "name": "modified"}])


@pytest.mark.anyio
async def test_two_connections_start_and_edit_independent_workspaces_in_parallel(mcp_home):
    params = StdioServerParameters(
        command=sys.executable, args=[str(MCP_SERVER_SCRIPT)], env={"PRINT_PREP_HOME": str(mcp_home)}
    )

    async def edit_one(key):
        async with stdio_client(params) as streams:
            async with ClientSession(*streams) as client:
                await client.initialize()
                await mcp_call(client, "studio_edit", key, action="primitive", expected_revision=0)
                await mcp_call(client, "studio_edit", key, action="rename", expected_revision=1, params={"name": key})
                return await mcp_call(client, "studio_get_state", key)

    a, b = await asyncio.gather(edit_one("parallel-a"), edit_one("parallel-b"))
    assert a["job"] != b["job"]
    assert [o["name"] for o in a["workbench"]["objects"]] == ["parallel-a"]
    assert [o["name"] for o in b["workbench"]["objects"]] == ["parallel-b"]


@pytest.mark.anyio
async def test_native_chat_binding_shares_model_but_not_view_and_forks_isolate(mcp_session, tmp_path):
    await mcp_call(mcp_session, "studio_edit", "chat-owner", action="primitive", expected_revision=0)
    await mcp_call(mcp_session, "studio_edit", "chat-owner", action="primitive", expected_revision=1)
    state = (await mcp_call(mcp_session, "studio_get_state", "chat-owner"))["workbench"]
    a, b = [o["id"] for o in state["objects"]]
    invite = await mcp_call(
        mcp_session,
        "studio_workspaces",
        "chat-owner",
        action="invite",
        object_id=a,
        worktree=str(tmp_path),
        expected_revision=2,
    )
    joined = await mcp_call(
        mcp_session,
        "studio_workspaces",
        "chat-child",
        action="join",
        source_id="chat-owner",
        invitation=invite["invitation"],
        worktree=str(tmp_path),
    )
    assert joined["scope"] == [a]
    await mcp_call(
        mcp_session,
        "studio_edit",
        "chat-child",
        action="rename",
        expected_revision=2,
        expected_versions={a: 0},
        params={"ids": [a], "name": "child live"},
    )
    await mcp_call(
        mcp_session,
        "studio_edit",
        "chat-owner",
        action="rename",
        expected_revision=2,
        expected_versions={b: 0},
        params={"ids": [b], "name": "owner live"},
    )
    parent = await mcp_call(mcp_session, "studio_get_state", "chat-owner")
    child = await mcp_call(mcp_session, "studio_get_state", "chat-child")
    assert parent["job"] == child["job"]
    assert child["workbench"]["selection"] == [a]
    assert parent["workbench"]["selection"] == [b]
    assert parent["workbench"]["objects"] == child["workbench"]["objects"]
    opened_a = await mcp_session.call_tool("studio_open", {"workspace_id": "chat-owner"})
    opened_b = await mcp_session.call_tool("studio_open", {"workspace_id": "chat-child"})
    assert opened_a.meta["openai/widgetSessionId"] != opened_b.meta["openai/widgetSessionId"]
    bad = await mcp_session.call_tool(
        "studio_edit",
        {
            "workspace_id": "chat-owner",
            "action": "rename",
            "expected_revision": 4,
            "params": {"ids": [a], "name": "overwrite"},
        },
    )
    assert bad.is_error and "part_locked" in bad.content[0].text
    await mcp_call(
        mcp_session, "studio_workspaces", "chat-isolated", action="fork", source_id="chat-owner", expected_revision=4
    )
    isolated = await mcp_call(mcp_session, "studio_get_state", "chat-isolated")
    assert "collaboration" not in isolated["workbench"]
    assert isolated["job"] != parent["job"]
