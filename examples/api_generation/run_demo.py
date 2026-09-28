"""Real stdio MCP demo. --probe does not generate; --generate submits one paid job.

Credentials must already be in the provider's environment variables.
Use --resume with the same output directory after interruption; never resubmit.
Generated state, keys and local model files are not added to this repository.
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

import numpy as np
import trimesh
from mcp import ClientSession, StdioServerParameters, stdio_client

import studio
from studio.core.editor import _atomic


async def run(out: Path, mode: str, image: Path | None = None, service_config: Path | None = None, provider_id="hi3d"):
    out.mkdir(parents=True, exist_ok=True)
    home, checkpoint = out / "state", out / "task.private.json"
    if mode == "generate" and (checkpoint.exists() or any(home.rglob("request.json"))):
        raise RuntimeError("This directory already contains a task. Use --resume; do not generate again.")
    if mode == "resume" and not checkpoint.exists():
        raise RuntimeError("No task checkpoint. Inspect this directory's state before starting any new paid job.")
    if mode == "generate" and (image is None or not image.is_file()):
        raise RuntimeError("--generate needs --image /absolute/reference.png")
    config = service_config or out / "services.json"
    if not service_config and not config.exists():
        config.write_text("{}\n")
    env = {
        "PRINT_PREP_HOME": str(home),
        "PRINT_PREP_WORKSPACES_HOME": str(home),
        "PRINT_PREP_WORKSPACE_ID": "api-tutorial",
        "CODEX_HOME": str(out / "empty-codex"),
        "WORKBENCH_SERVICE_CONFIG": str(config),
        "STUDIO_LANG": "en",
    }
    for key in ("HI3D_ACCESS_KEY", "HI3D_SECRET_KEY", "HUNYUAN_API_KEY", "ONEAPI_API_KEY", "WORKBENCH_BLENDER"):
        if key in os.environ:
            env[key] = os.environ[key]
    params = StdioServerParameters(command=sys.executable, args=[str(ROOT / "studio/shell/mcp_server.py")], env=env)
    calls = []
    try:
        async with stdio_client(params) as streams:
            async with ClientSession(*streams) as client:
                await client.initialize()

                async def call(name, args=None):
                    response = await client.call_tool(name, args or {})
                    if response.is_error:
                        raise RuntimeError(f"{name}: {response.content}")
                    calls.append(name)
                    return response.structured_content or json.loads(response.content[0].text)

                async def state():
                    return (await call("studio_get_state"))["workbench"]

                async def edit(action, params=None):
                    current = await state()
                    return await call(
                        "studio_edit",
                        {"action": action, "expected_revision": current["revision"], "params": params or {}},
                    )

                caps = await call("studio_capabilities")
                provider = next(s for s in caps["services"] if s["id"] == provider_id)
                if not provider["configured"]:
                    raise RuntimeError(
                        "Configure the provider's endpoint and environment variables in the MCP process."
                    )
                probe = await call("studio_services", {"action": "probe", "id": provider_id})
                if provider_id == "hunyuan" and "hunyuan-3d-3.1-pro" not in probe["models"]:
                    raise RuntimeError(
                        "The gateway did not list hunyuan-3d-3.1-pro; choose a supported model explicitly."
                    )
                if mode == "probe" or (mode == "generate" and probe.get("positive_balance") is False):
                    report = {
                        "status": "blocked_no_api_balance" if probe.get("positive_balance") is False else "ready",
                        "authentication": "passed",
                        "provider": provider_id,
                        "generation_submitted": False,
                        "mcp_calls": calls,
                    }
                    _atomic(out / "preflight.json", json.dumps(report, indent=2).encode())
                    print(json.dumps(report), flush=True)
                    return report
                await call("studio_open", {"mode": "tasks"})
                if mode == "generate":
                    task_params = (
                        {}
                        if provider_id == "hi3d"
                        else {"model": "hunyuan-3d-3.1-pro", "output_format": "GLB", "face_count": 60000, "pbr": True}
                    )
                    created = await call(
                        "studio_task",
                        {
                            "action": "start",
                            "provider": provider_id,
                            "operation": "image-to-3d",
                            "inputs": [str(image)],
                            "title": provider_id + " mug demo",
                            "params": task_params,
                            "timeout_seconds": 1800,
                        },
                    )
                    task_id = created["task"]["id"]
                    _atomic(
                        checkpoint,
                        json.dumps({"task_id": task_id, "image": str(image), "provider": provider_id}).encode(),
                    )
                    checkpoint.chmod(0o600)
                else:
                    saved = json.loads(checkpoint.read_text())
                    if saved["provider"] != provider_id:
                        raise RuntimeError("Resume must use the same provider as the saved task.")
                    task_id, image = saved["task_id"], Path(saved["image"])
                    existing = (await call("studio_tasks", {"id": task_id}))["task"]
                    if existing.get("can_resume"):
                        await call("studio_task", {"action": "resume", "id": task_id})
                last = None
                while True:
                    task = (await call("studio_tasks", {"id": task_id}))["task"]
                    progress = (task["status"], (task.get("service") or {}).get("status"))
                    if progress != last:
                        print(json.dumps({"task": progress[0], "service": progress[1]}), flush=True)
                        last = progress
                    if task["status"] not in ("queued", "running", "cancelling"):
                        break
                    await asyncio.sleep(10)
                if task["status"] != "completed":
                    raise RuntimeError(
                        f"Task {task['status']}; can_resume={task.get('can_resume', False)}. Inspect task logs; do not resubmit."
                    )
                glb = next(a for a in task["artifacts"] if a["name"].endswith(".glb"))
                current = await state()
                # The demo's dedicated workspace must stay empty until this import.
                # Once editing/export finished, reruns return the recorded result.
                if (out / "report.json").exists():
                    return json.loads((out / "report.json").read_text())
                if current["objects"]:
                    raise RuntimeError(
                        "The demo scene is nonempty. Review the existing import; it will not be duplicated."
                    )
                await call(
                    "studio_task",
                    {
                        "action": "import",
                        "id": task_id,
                        "artifact_id": glb["id"],
                        "expected_revision": current["revision"],
                    },
                )
                imported = await state()
                ids = [o["id"] for o in imported["objects"]]
                assert ids, "No editable objects imported"
                raw_state = await call("studio_get_state")
                task_output = Path(raw_state["job"]) / "tasks" / task_id / "output"
                source = task_output / glb["name"]
                original = out / "generated.glb"
                shutil.copyfile(source, original)
                assert hashlib.sha256(original.read_bytes()).hexdigest() == glb["sha256"]
                scene = trimesh.load(original, force="scene", process=False)
                assert np.isfinite(scene.bounds).all() and len(scene.geometry) > 0
                inspected = await edit("inspect", {"ids": ids})
                # Demonstrate a reversible 0.5x edit and undo before exporting.
                before = {o["id"]: o["extents_mm"] for o in imported["objects"]}
                await edit("transform", {"ids": ids, "scale": [0.5, 0.5, 0.5]})
                changed = await state()
                for obj in changed["objects"]:
                    assert np.allclose(obj["extents_mm"], np.array(before[obj["id"]]) * 0.5, atol=0.001)
                await edit("undo")
                restored = await state()
                for obj in restored["objects"]:
                    assert np.allclose(obj["extents_mm"], before[obj["id"]], atol=0.001)
                await edit("export", {"path": str(out / "roundtrip.glb"), "format": "glb"})
                await edit("save", {"path": str(out / "api-demo.3dworkbench")})
                loaded = trimesh.load(out / "roundtrip.glb", force="scene", process=False)
                assert np.allclose(loaded.extents, scene.extents, rtol=1e-4, atol=1e-6)
                provenance = (
                    json.loads((task_output / "service.json").read_text())
                    if (task_output / "service.json").exists()
                    else {}
                )
                report = {
                    "status": "passed",
                    "generation_submitted": True,
                    "provider": provider_id,
                    "api_submissions": 1,
                    "model": task["service"]["model"],
                    "cost": provenance.get("cost"),
                    "cost_unit": provenance.get("cost_unit"),
                    "generation_seconds": round(provenance["received_at"] - provenance["submitted_at"], 2)
                    if provenance
                    else None,
                    "input_sha256": hashlib.sha256(image.read_bytes()).hexdigest(),
                    "glb_sha256": glb["sha256"],
                    "glb_bytes": glb["bytes"],
                    "geometry_count": len(scene.geometry),
                    "faces": sum(len(m.faces) for m in scene.geometry.values()),
                    "source_extents_gltf_units": scene.extents.tolist(),
                    "imported_objects": len(ids),
                    "scaled_0_5_verified": True,
                    "undo_verified": True,
                    "export_bounds_verified": True,
                    "physical_size_calibrated": False,
                    "printed": False,
                    "ui_clicks_verified": False,
                    "mcp_calls": calls,
                }
                _atomic(out / "inspection.private.json", json.dumps(inspected, indent=2).encode())
                _atomic(out / "report.json", json.dumps(report, indent=2).encode())
                print(json.dumps(report, indent=2), flush=True)
                return report
    finally:
        studio.stop_server(home=home)
        for workspace in (home / "workspaces").glob("*"):
            studio.stop_server(home=workspace)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    for mode in ("probe", "generate", "resume"):
        modes.add_argument("--" + mode, action="store_true")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--provider", choices=("hi3d", "hunyuan"), default="hi3d")
    parser.add_argument("--image", type=Path)
    parser.add_argument("--service-config", type=Path, help="Optional services.json override; env references only.")
    args = parser.parse_args()
    mode = next(m for m in ("probe", "generate", "resume") if getattr(args, m))
    report = asyncio.run(
        run(
            args.out.expanduser().resolve(),
            mode,
            args.image.expanduser().resolve() if args.image else None,
            args.service_config.expanduser().resolve() if args.service_config else None,
            args.provider,
        )
    )
    if report["status"] == "blocked_no_api_balance":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
