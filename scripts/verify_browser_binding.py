"""Verify browser/MCP identity and bidirectional selection through public APIs.

Run against an isolated acceptance workspace, never an unrelated user's project.
No service credentials, model generation, or geometry edits are needed.
"""

import argparse
import asyncio
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mcp import ClientSession, StdioServerParameters, stdio_client
import studio


async def verify(args):
    started = time.monotonic()
    home, out = args.home.resolve(), args.out.resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    config = out.parent / "no-services.json"
    config.write_text("{}\n")
    env = {
        "PRINT_PREP_HOME": str(home),
        "PRINT_PREP_WORKSPACES_HOME": str(home),
        "PRINT_PREP_WORKSPACE_ID": args.workspace_id,
        "CODEX_HOME": str(home / "empty-codex"),
        "WORKBENCH_SERVICE_CONFIG": str(config),
        "STUDIO_LANG": "en",
    }
    report = {"status": "failed", "workspace_id": args.workspace_id}
    try:
        params = StdioServerParameters(
            command=sys.executable, args=[str(ROOT / "studio/shell/mcp_server.py")], env=env, cwd=str(ROOT)
        )
        async with stdio_client(params) as streams:
            async with ClientSession(*streams) as client:
                await client.initialize()

                async def call(name, body=None):
                    result = await client.call_tool(name, body or {})
                    data = result.structured_content or json.loads(result.content[0].text)
                    assert not result.is_error, data
                    return data

                opened = await call("studio_open", {"presentation": "browser"})
                base = opened["url"].split("?", 1)[0].rstrip("/")
                token = None

                def request(path, body=None, workspace=None):
                    headers = {"X-Studio-Workspace": workspace or args.workspace_id}
                    if token:
                        headers["X-Studio-Token"] = token
                    if body is not None:
                        headers["Content-Type"] = "application/json"
                    req = urllib.request.Request(
                        base + path, headers=headers, data=json.dumps(body).encode() if body is not None else None
                    )
                    try:
                        with urllib.request.urlopen(req, timeout=20) as response:
                            return response.status, json.load(response)
                    except urllib.error.HTTPError as exc:
                        return exc.code, json.load(exc)

                status, session = await asyncio.to_thread(request, "/api/session")
                assert status == 200
                token = session["token"]
                before = await call("studio_get_state")
                assert session["job"] == opened["job"] == before["job"]
                status, browser = await asyncio.to_thread(request, "/api/state")
                assert status == 200 and browser["workbench"] == before["workbench"]
                original_selection = before["workbench"]["selection"]
                objects = before["workbench"]["objects"]
                assert objects, "Use a completed acceptance case with at least one object"
                try:
                    status, _ = await asyncio.to_thread(
                        request,
                        "/api/edit",
                        {
                            "action": "select",
                            "expected_revision": before["workbench"]["revision"],
                            "params": {"ids": [objects[0]["id"]]},
                        },
                    )
                    assert status == 200
                    selected = await call("studio_get_state")
                    assert selected["workbench"]["selection"] == [objects[0]["id"]]
                finally:
                    latest = await call("studio_get_state")
                    await call(
                        "studio_edit",
                        {
                            "action": "select",
                            "expected_revision": latest["workbench"]["revision"],
                            "params": {"ids": original_selection},
                        },
                    )
                final = await call("studio_get_state")
                status, browser = await asyncio.to_thread(request, "/api/state")
                assert status == 200 and browser["workbench"] == final["workbench"]
                assert final["workbench"]["objects"] == objects
                status, rejected = await asyncio.to_thread(request, "/api/session", workspace="unrelated-chat")
                assert status == 409 and rejected["error"]["code"] == "workspace_mismatch"
                report.update(
                    status="pass",
                    job=before["job"],
                    object_count=len(objects),
                    browser_mcp_same_project=True,
                    browser_selection_visible_to_mcp=True,
                    mcp_selection_visible_to_browser=True,
                    geometry_unchanged=True,
                    wrong_chat_rejected=True,
                )
    except Exception as exc:
        report["error"] = str(exc)
        raise
    finally:
        for folder in (home / "workspaces").glob("*"):
            studio.stop_server(home=folder)
        report["elapsed_seconds"] = round(time.monotonic() - started, 3)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path, required=True)
    parser.add_argument("--workspace-id", required=True)
    parser.add_argument("--out", type=Path, required=True)
    asyncio.run(verify(parser.parse_args()))
