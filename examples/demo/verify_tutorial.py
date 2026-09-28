"""Replay the README editing tutorial over real stdio MCP, in isolated state.

Run: uv run python examples/demo/verify_tutorial.py [--out /absolute/new/directory]
No host account, UI automation, Blender or generation-service key is used.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import numpy as np
import trimesh
from mcp import ClientSession, StdioServerParameters, stdio_client

import studio


async def verify(out: Path) -> dict:
    demo = json.loads(subprocess.check_output(
        [sys.executable, str(ROOT / "examples/demo/make_demo_parts.py"), "--out", str(out / "demo")],
        text=True,
    ))
    home = out / "state"
    config = out / "services.json"
    config.write_text('{"providers":{}}\n')
    env = {
        "PRINT_PREP_HOME": str(home), "PRINT_PREP_WORKSPACES_HOME": str(home),
        "PRINT_PREP_WORKSPACE_ID": "readme-tutorial", "CODEX_HOME": str(out / "empty-codex"),
        "WORKBENCH_SERVICE_CONFIG": str(config), "STUDIO_LANG": "en",
    }
    params = StdioServerParameters(command=sys.executable, args=[str(ROOT / "studio/shell/mcp_server.py")], env=env)
    calls = []
    try:
        async with stdio_client(params) as streams:
            async with ClientSession(*streams) as client:
                await client.initialize()

                async def call(name, args=None):
                    result = await client.call_tool(name, args or {})
                    if result.is_error:
                        raise RuntimeError(f"{name}: {result.content}")
                    calls.append(name)
                    return result.structured_content or json.loads(result.content[0].text)

                async def state():
                    return (await call("studio_get_state"))["workbench"]

                async def edit(action, args=None):
                    current = await state()
                    return await call("studio_edit", {"action": action, "expected_revision": current["revision"], "params": args or {}})

                await call("studio_open", {"mode": "edit"})
                await edit("import", {"files": [demo["glb"]]})
                initial = await state()
                objects = {o["name"]: o for o in initial["objects"]}
                assert set(objects) == {"body", "handle", "lid", "knob", "base"}
                handle = objects["handle"]
                before = handle["extents_mm"]
                assert np.allclose(before, [14, 8, 23], atol=0.001), before
                await edit("select", {"ids": [handle["id"]]})
                await edit("transform", {"ids": [handle["id"]], "scale": [1.5, 1.5, 1.5]})
                changed = await state()
                after = next(o["extents_mm"] for o in changed["objects"] if o["id"] == handle["id"])
                assert np.allclose(after, [21, 12, 34.5], atol=0.001), after
                for o in changed["objects"]:
                    if o["id"] != handle["id"]:
                        assert o["asset"] == objects[o["name"]]["asset"]
                        assert np.allclose(o["transform"], objects[o["name"]]["transform"])
                await edit("inspect", {"ids": [handle["id"]]})
                await edit("undo")
                restored = await state()
                assert np.allclose(next(o["extents_mm"] for o in restored["objects"] if o["id"] == handle["id"]), before)
                archive = await edit("save", {"path": str(out / "tutorial.3dworkbench")})
                exported = await edit("export", {"path": str(out / "tutorial.glb"), "format": "glb"})
                scene = trimesh.load(exported["path"], process=False)
                assert len(scene.geometry) == 5
                assert Path(archive["path"]).is_file()
                await edit("open", {"path": archive["path"]})
                reopened = await state()
                assert len(reopened["objects"]) == 5
                assert np.allclose(next(o["extents_mm"] for o in reopened["objects"] if o["name"] == "handle"), before)
                return {"status": "pass", "parts": 5, "handle_before_mm": before, "handle_scaled_mm": after,
                        "undo_restored": True, "saved_project": archive["path"], "exported_glb": exported["path"],
                        "reopened_parts": 5, "mcp_calls": calls, "ui_clicks_verified": False}
    finally:
        studio.stop_server(home=home)
        for workspace in (home / "workspaces").glob("*"):
            studio.stop_server(home=workspace)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    if args.out:
        out = args.out.expanduser().resolve()
        out.mkdir(parents=True, exist_ok=False)
    else:
        out = Path(tempfile.mkdtemp(prefix="3d-workbench-tutorial-"))
    report = asyncio.run(verify(out))
    (out / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({**report, "report": str(out / "report.json")}, indent=2))


if __name__ == "__main__":
    main()
