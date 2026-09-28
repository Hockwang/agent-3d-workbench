"""Run one stage of the shared-image comparison through real stdio MCP.

generate/split are paid calls. Existing tasks are polled/resumed, never regenerated.
Local geometry is authored by the agent after looking at the shared reference.
Use an output directory outside the repository and keep private config there.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from mcp import ClientSession, StdioServerParameters, stdio_client
import studio
from studio.core.editor import _atomic


async def run(out, stage, config):
    out.mkdir(parents=True, exist_ok=True)
    home = out / "state"
    env = {
        "PRINT_PREP_HOME": str(home),
        "PRINT_PREP_WORKSPACES_HOME": str(home),
        "PRINT_PREP_WORKSPACE_ID": "cup-comparison",
        "CODEX_HOME": str(out / "empty-codex"),
        "WORKBENCH_SERVICE_CONFIG": str(config or out / "unconfigured-services.json"),
        "STUDIO_LANG": "en",
    }
    for key in ("HUNYUAN_API_KEY", "ONEAPI_API_KEY", "WORKBENCH_BLENDER"):
        if key in os.environ:
            env[key] = os.environ[key]
    params = StdioServerParameters(command=sys.executable, args=[str(ROOT / "studio/shell/mcp_server.py")], env=env)
    try:
        async with stdio_client(params) as streams:
            async with ClientSession(*streams) as client:
                await client.initialize()

                async def call(name, args=None):
                    response = await client.call_tool(name, args or {})
                    if response.is_error:
                        raise RuntimeError(f"{name}: {response.content}")
                    return response.structured_content or json.loads(response.content[0].text)

                title = "Shared cup image / " + stage
                if stage == "local":
                    title += (
                        " / "
                        + hashlib.sha256((ROOT / "examples/cup_comparison/make_cup.py").read_bytes()).hexdigest()[:8]
                    )
                tasks = (await call("studio_tasks"))["tasks"]
                existing = [t for t in tasks if t["title"] == title]
                if len(existing) > 1:
                    raise RuntimeError("Multiple tasks with this title; inspect before continuing.")
                if existing:
                    task = existing[0]
                    if task.get("can_resume"):
                        await call("studio_task", {"action": "resume", "id": task["id"]})
                else:
                    if stage in ("generate", "split"):
                        probe = await call("studio_services", {"action": "probe", "id": "hunyuan"})
                        model = "hunyuan-3d-3.1-pro" if stage == "generate" else "hunyuan-3d-1.5-part"
                        if model not in probe["models"]:
                            raise RuntimeError("Required model is unavailable: " + model)
                    if stage == "generate":
                        body = {
                            "provider": "hunyuan",
                            "operation": "image-to-3d",
                            "inputs": [str(out / "reference.png")],
                            "params": {"model": model, "output_format": "FBX", "face_count": 60000, "pbr": True},
                        }
                    elif stage == "split":
                        source = json.loads((out / "generate.private.json").read_text())["task_id"]
                        body = {"provider": "hunyuan", "operation": "segment", "params": {"source_task": source}}
                    elif stage == "local":
                        body = {
                            "engine": "python",
                            "script": (ROOT / "examples/cup_comparison/make_cup.py").read_text(),
                            "inputs": [str(out / "reference.png")],
                            "params": {"body_diameter_mm": 88, "body_height_mm": 90},
                        }
                    else:
                        raise ValueError(stage)
                    task = (
                        await call(
                            "studio_task",
                            {
                                "action": "start",
                                "title": title,
                                "timeout_seconds": 1800,
                                "render_preview": False,
                                **body,
                            },
                        )
                    )["task"]
                checkpoint = out / (stage + ".private.json")
                _atomic(checkpoint, json.dumps({"task_id": task["id"]}).encode())
                checkpoint.chmod(0o600)
                last = None
                while True:
                    task = (await call("studio_tasks", {"id": task["id"]}))["task"]
                    status = (task["status"], (task.get("service") or {}).get("status"))
                    if last != status:
                        print(json.dumps({"stage": stage, "status": status}), flush=True)
                        last = status
                    if task["status"] not in ("queued", "running", "cancelling"):
                        break
                    await asyncio.sleep(5)
                if task["status"] != "completed":
                    raise RuntimeError(f"{stage}: {task['status']}; {task.get('error')}. Do not resubmit.")
                current = await call("studio_get_state")
                source = Path(current["job"]) / "tasks" / task["id"] / "output"
                target = out / stage
                shutil.copytree(source, target, dirs_exist_ok=True)
                record = {
                    "task_id": task["id"],
                    "output": str(target),
                    "elapsed_seconds": task.get("elapsed_seconds"),
                    "artifacts": [{k: a[k] for k in ("name", "bytes", "sha256")} for a in task["artifacts"]],
                }
                _atomic(checkpoint, json.dumps(record, indent=2).encode())
                print(
                    json.dumps(
                        {
                            "stage": stage,
                            "status": "completed",
                            "output": str(target),
                            "artifacts": [a["name"] for a in task["artifacts"]],
                        }
                    ),
                    flush=True,
                )
    finally:
        studio.stop_server(home=home)
        for workspace in (home / "workspaces").glob("*"):
            studio.stop_server(home=workspace)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("generate", "split", "local"))
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--service-config", type=Path, help="Private gateway config; only required for generate/split")
    args = parser.parse_args()
    if args.stage != "local" and args.service_config is None:
        parser.error("generate/split require --service-config; local needs no service configuration")
    config = args.service_config.expanduser().resolve() if args.service_config else None
    asyncio.run(run(args.out.expanduser().resolve(), args.stage, config))
