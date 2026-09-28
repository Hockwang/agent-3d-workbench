"""No API calls: import both finished routes, move one handle, undo and export.

Uses separate disposable MCP workspaces. Run once with --out pointing to the
comparison output directory. API part meshes are normalized to 114 mm display
height explicitly; this is a presentation assumption, not image-derived scale.
"""

import argparse
import asyncio
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import numpy as np
import trimesh
from mcp import ClientSession, StdioServerParameters, stdio_client
import studio


async def verify(root, route, model, expected_parts):
    out = root / (route + "-edit")
    out.mkdir(exist_ok=False)
    home = out / "state"
    env = {
        "PRINT_PREP_HOME": str(home),
        "PRINT_PREP_WORKSPACES_HOME": str(home),
        "PRINT_PREP_WORKSPACE_ID": "cup-edit",
        "CODEX_HOME": str(out / "empty-codex"),
        "WORKBENCH_SERVICE_CONFIG": str(out / "unconfigured.json"),
        "STUDIO_LANG": "en",
    }
    params = StdioServerParameters(command=sys.executable, args=[str(ROOT / "studio/shell/mcp_server.py")], env=env)
    calls = []
    try:
        async with stdio_client(params) as streams:
            async with ClientSession(*streams) as client:
                await client.initialize()

                async def call(name, args=None):
                    result = await client.call_tool(name, args or {})
                    assert not result.is_error, result.content
                    calls.append(name)
                    return result.structured_content or json.loads(result.content[0].text)

                async def state():
                    return (await call("studio_get_state"))["workbench"]

                async def edit(action, args=None):
                    s = await state()
                    return await call(
                        "studio_edit", {"action": action, "expected_revision": s["revision"], "params": args or {}}
                    )

                await call("studio_open", {"mode": "edit"})
                await edit("import", {"files": [str(model)]})
                initial = await state()
                objects = initial["objects"]
                assert len(objects) == expected_parts
                # Verified in this example: the smaller API segment is the handle.
                handle = next((o for o in objects if o["name"] == "handle"), min(objects, key=lambda o: o["faces"]))
                ids = [o["id"] for o in objects]
                inspection = await edit("inspect", {"ids": ids})
                before = {o["id"]: np.array(o["transform"]) for o in objects}
                await edit("transform", {"ids": [handle["id"]], "translate_mm": [25, 0, 0]})
                moved = await state()
                for o in moved["objects"]:
                    expected = before[o["id"]].copy()
                    if o["id"] == handle["id"]:
                        expected[0, 3] += 25
                    assert np.allclose(o["transform"], expected), o["name"]
                await edit("export", {"path": str(out / "handle-moved.glb"), "format": "glb"})
                await edit("undo")
                for o in (await state())["objects"]:
                    assert np.allclose(o["transform"], before[o["id"]])
                await edit("export", {"path": str(out / "restored.glb"), "format": "glb"})
                saved = await edit("save", {"path": str(out / "project.3dworkbench")})
                await edit("open", {"path": saved["path"]})
                reopened = await state()
                assert len(reopened["objects"]) == expected_parts
                source = trimesh.load(model, force="scene", process=False)
                output = trimesh.load(out / "restored.glb", force="scene", process=False)
                assert np.allclose(source.bounds, output.bounds, atol=1e-6)
                checks = [{k: v for k, v in row.items() if k != "id"} for row in inspection["reports"]]
                report = {
                    "status": "passed",
                    "route": route,
                    "parts": len(objects),
                    "handle_name": handle["name"],
                    "move_handle_mm": 25,
                    "other_objects_unchanged": True,
                    "undo_verified": True,
                    "export_bounds_verified": True,
                    "project_reopened": True,
                    "inspection": checks,
                    "mcp_calls": calls,
                    "printed": False,
                    "ui_clicks_verified": False,
                }
                (out / "report.json").write_text(json.dumps(report, indent=2))
                print(json.dumps(report, indent=2), flush=True)
    finally:
        studio.stop_server(home=home)
        for w in (home / "workspaces").glob("*"):
            studio.stop_server(home=w)


async def main(root):
    source = trimesh.load(root / "split/combined.glb", force="scene", process=False)
    factor = 0.114 / source.extents[1]
    source.apply_scale(factor)
    source.apply_translation([0, -source.bounds[0, 1], 0])
    target = root / "api-display-114mm.glb"
    source.export(target)
    (root / "display-normalization.json").write_text(
        json.dumps({"api_split_scale": factor, "display_height_mm": 114, "physical_size_calibrated": False}, indent=2)
    )
    await verify(root, "local", root / "local/scene.glb", 4)
    await verify(root, "api", target, 2)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", type=Path, required=True)
    asyncio.run(main(p.parse_args().out.expanduser().resolve()))
