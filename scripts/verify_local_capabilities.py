"""Run local fabrication through real stdio MCP, optionally denying external networking.

uv run python scripts/verify_local_capabilities.py --out /absolute/new/directory --deny-external-network
"""

import argparse
import asyncio
import errno
import json
import os
from pathlib import Path
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import trimesh
from mcp import ClientSession, StdioServerParameters, stdio_client
from studio.core.task_operations import deliver


def box(center, size):
    return trimesh.creation.box(extents=size).apply_translation(center)


def cases(root):
    def scene(name, meshes):
        folder = root / name
        folder.mkdir()
        deliver(meshes, folder, {}, stl=False)
        return str(folder / "scene.glb")

    connection = scene(
        "connection-source", {"lower": box([0, 0, -5], [30, 30, 10]), "upper": box([0, 0, 5], [30, 30, 10])}
    )
    result = [
        {
            "name": "connection",
            "template": "connect-parts",
            "inputs": [connection],
            "params": {
                "parts": ["lower", "upper"],
                "connectors": [{"center_mm": [0, 0, 0], "axis": [0, 0, 1], "depth_mm": 4}],
            },
        }
    ]
    colored = box([0, 0, 0], [20, 20, 10])
    colored.unmerge_vertices()
    colored.visual.face_colors = [0, 0, 255, 255]
    colored.visual.face_colors[colored.face_normals[:, 2] > 0.9] = [255, 0, 0, 255]
    result.append(
        {
            "name": "color",
            "template": "color-inlays",
            "inputs": [scene("color-source", {"colored": colored})],
            "params": {"palette_rgb": [[0, 0, 255], [255, 0, 0]], "pull_direction": [0, 0, 1]},
        }
    )
    for family, anchors in [
        ("pin_hinge", [[-25, 0, 0], [30, 0, 0]]),
        ("slew", [[-20, 0, -1.5], [20, 0, 2.2]]),
        ("slider", [[0, -20, 0], [0, 20, 0]]),
        ("ball_socket", [[-22, 0, -2], [22, 0, 0]]),
    ]:
        path = scene(family + "-source", {"fixed": box(anchors[0], [8, 8, 8]), "moving": box(anchors[1], [8, 8, 8])})
        result.append(
            {
                "name": family,
                "template": "install-joint",
                "inputs": [path],
                "params": {
                    "parts": ["fixed", "moving"],
                    "family": family,
                    "center_mm": [0, 0, 0],
                    "axis": [0, 0, 1],
                    "anchors_mm": anchors,
                    "machining_box_mm": [[-40, -40, -20], [40, 40, 20]],
                    "mount_radius_mm": 0.75,
                },
            }
        )
    folder = root / "mixed-source"
    folder.mkdir()
    box([0, 0, 0], [0.1, 0.1, 0.1]).export(folder / "cube.stl")
    links = "".join(
        f'<link name="{name}"><visual><origin xyz="{origin}"/><geometry><mesh filename="cube.stl"/></geometry></visual></link>'
        for name, origin in [("base", "10 10 10"), ("a", "0 0 0"), ("b", "0 0 0")]
    )
    joints = "".join(
        f'<joint name="{name}" type="prismatic"><parent link="base"/><child link="{name}"/><origin xyz="{origin}"/><axis xyz="{axis}"/><limit lower="0" upper="2" effort="1" velocity="1"/></joint>'
        for name, origin, axis in [("a", "0 0 0", "1 0 0"), ("b", "1 0 0", "0 1 0")]
    )
    (folder / "mixed.urdf").write_text(f'<robot name="mixed">{links}{joints}</robot>')
    result.append(
        {
            "name": "mixed-collision",
            "template": "motion-check",
            "inputs": [str(folder / "mixed.urdf")],
            "params": {"steps": 3},
            "expected": "fail",
        }
    )
    return result


async def run(root, deny_external):
    (root / "services.json").write_text("{}")
    home = root / "home"
    wid = "local-capabilities-" + uuid.uuid4().hex[:12]
    env = {k: os.environ[k] for k in ("PATH", "HOME", "TMPDIR", "LANG", "SYSTEMROOT", "WINDIR") if k in os.environ}
    env.update(
        PRINT_PREP_HOME=str(home),
        PRINT_PREP_WORKSPACES_HOME=str(home),
        PRINT_PREP_WORKSPACE_ID=wid,
        WORKBENCH_SERVICE_CONFIG=str(root / "services.json"),
        STUDIO_LANG="en",
    )
    command = sys.executable
    arguments = [str(ROOT / "studio/shell/mcp_server.py")]
    if deny_external:
        if sys.platform != "darwin":
            raise RuntimeError("--deny-external-network currently requires macOS sandbox-exec")
        profile = root / "loopback-only.sb"
        profile.write_text(
            '(version 1)\n(allow default)\n(deny network*)\n(allow network-bind (local ip "localhost:*"))\n(allow network-inbound (local ip "localhost:*"))\n(allow network-outbound (remote ip "localhost:*"))\n'
        )
        arguments = ["-f", str(profile), command, *arguments]
        command = "/usr/bin/sandbox-exec"
    evidence = {"external_network_denied": deny_external, "configured_services": 0, "cases": []}
    logs = []

    def save():
        (root / "results.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2))
        (root / "mcp-calls.json").write_text(json.dumps(logs, ensure_ascii=False, indent=2))

    params = StdioServerParameters(command=command, args=arguments, env=env, cwd=str(ROOT))
    try:
        async with stdio_client(params) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                await session.initialize()

                async def call(name, args=None):
                    r = await session.call_tool(name, args or {})
                    value = r.structured_content or next(
                        (json.loads(c.text) for c in r.content if c.type == "text"), {}
                    )
                    logs.append({"tool": name, "arguments": args or {}, "result": value, "is_error": r.is_error})
                    save()
                    assert not r.is_error, (name, value)
                    return value

                async def wait(task):
                    deadline = time.monotonic() + 180
                    while task["status"] in ("running", "queued", "cancelling"):
                        assert time.monotonic() < deadline, "task timeout"
                        await asyncio.sleep(0.25)
                        task = (await call("studio_tasks", {"id": task["id"]}))["task"]
                    assert task["status"] == "completed", task
                    return task, {a["name"]: a for a in task["artifacts"]}

                await call("studio_open", {"mode": "tasks"})
                caps = await call("studio_capabilities")
                assert not any(s.get("configured") for s in caps["services"])
                evidence["local_templates"] = len(caps["templates"])
                if deny_external:
                    script = f"import socket,errno,json\nfrom pathlib import Path\ns=socket.socket()\ns.settimeout(1)\ntry:\n s.connect(('192.0.2.1',443))\nexcept OSError as exc:\n assert exc.errno=={errno.EPERM}\nelse:\n raise RuntimeError('external networking not blocked')\nfinally:\n s.close()\nPath(workbench['output'],'network.json').write_text(json.dumps({{'external_connect':'EPERM'}}))"
                    await wait(
                        (
                            await call(
                                "studio_task",
                                {"action": "start", "engine": "python", "script": script, "render_preview": False},
                            )
                        )["task"]
                    )
                generated = []
                for case in cases(root):
                    task = (
                        await call(
                            "studio_task",
                            {
                                "action": "start",
                                "title": case["name"],
                                "template": case["template"],
                                "inputs": case["inputs"],
                                "params": case["params"],
                                "render_preview": False,
                            },
                        )
                    )["task"]
                    task, artifacts = await wait(task)
                    report = json.loads(Path(artifacts["report.json"]["path"]).read_text())
                    assert report["status"] == case.get("expected", "pass"), report
                    evidence["cases"].append(
                        {
                            "name": case["name"],
                            "task_id": task["id"],
                            "status": task["status"],
                            "report_status": report["status"],
                            "artifacts": artifacts,
                        }
                    )
                    if "scene.glb" in artifacts:
                        generated.append((case["name"], artifacts["scene.glb"]["path"]))
                    if "assembly.urdf" in artifacts:
                        count = 3 if case["name"] == "ball_socket" else 1
                        check = (
                            await call(
                                "studio_task",
                                {
                                    "action": "start",
                                    "template": "motion-check",
                                    "inputs": [artifacts["assembly.urdf"]["path"]],
                                    "params": {
                                        "sampling": "explicit",
                                        "configurations": [{f"joint_{i}": 0 for i in range(count)}],
                                    },
                                    "render_preview": False,
                                },
                            )
                        )["task"]
                        _, out = await wait(check)
                        assert json.loads(Path(out["report.json"]["path"]).read_text())["status"] == "pass"
                        evidence["cases"][-1]["urdf_rest_check"] = out
                        plans = [("grid", {"steps": 5}, "fail" if case["name"] == "slew" else "pass")]
                        if case["name"] == "slew":
                            # The two fixture hosts collide at half a turn. Keep
                            # that failure, then explicitly check a smaller plan.
                            plans.append(
                                ("refined_grid", {"steps": 17, "joint_ranges": {"joint_0": [-1.4, 1.4]}}, "pass")
                            )
                        for label, plan, expected in plans:
                            check = (
                                await call(
                                    "studio_task",
                                    {
                                        "action": "start",
                                        "template": "motion-check",
                                        "inputs": [artifacts["assembly.urdf"]["path"]],
                                        "params": plan,
                                        "render_preview": False,
                                    },
                                )
                            )["task"]
                            _, out = await wait(check)
                            checked = json.loads(Path(out["report.json"]["path"]).read_text())
                            assert checked["status"] == expected, checked
                            evidence["cases"][-1][label] = {
                                "status": checked["status"],
                                "samples": len(checked["samples"]),
                                "artifacts": out,
                            }
                    print(case["name"], report["status"], flush=True)
                first = evidence["cases"][0]
                state = (await call("studio_get_state"))["workbench"]
                await call(
                    "studio_task",
                    {
                        "action": "import",
                        "id": first["task_id"],
                        "artifact_id": first["artifacts"]["scene.glb"]["id"],
                        "expected_revision": state["revision"],
                    },
                )
                state = (await call("studio_get_state"))["workbench"]
                assert len(state["objects"]) == 3
                evidence["editor_import_objects"] = 3
                if caps["blender"]["available"]:
                    evidence["observations"] = []
                    for start in range(0, len(generated), 4):
                        batch = generated[start : start + 4]
                        observation = (
                            await call(
                                "studio_observe",
                                {
                                    "action": "start",
                                    "inputs": [path for _, path in batch],
                                    "labels": [name for name, _ in batch],
                                    "params": {"views": ["iso"], "phases": [0], "resolution": 320},
                                },
                            )
                        )["task"]
                        _, observed = await wait(observation)
                        evidence["observations"].append(observed)
                evidence["status"] = "passed"
                save()
    finally:
        # Stop only the backend created in this new output folder.
        import studio

        studio.stop_server(home=home / "workspaces" / wid)
    print("PASS; evidence:", root, flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--deny-external-network", action="store_true")
    args = parser.parse_args()
    root = args.out.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=False)
    asyncio.run(run(root, args.deny_external_network))


if __name__ == "__main__":
    main()
