"""Exercise complete local user journeys through a real stdio MCP client.

Creates procedural assets, edits/manufactures them, observes the outputs, then
loads, orients, arranges, exports and test-slices. Never submits a print or opens
a service connection. Use a fresh --out directory and your own --workspace-id.
"""

import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import traceback
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np
import trimesh
from mcp import ClientSession, StdioServerParameters, stdio_client
from scripts.verify_local_first import CAD
from studio.core.projects import folder as project_folder
from studio.core.task_operations import scene_input


BAR = """
from pathlib import Path
import cadquery as cq
import trimesh
from studio.core.task_operations import deliver
out=Path(workbench['output'])
shape=cq.Workplane('XY').box(320,60,16)
holes=cq.Workplane('XY').pushPoints([(-130,0),(130,0)]).circle(5).extrude(40,both=True)
shape=shape.cut(holes)
cq.exporters.export(shape,str(out/'rail.step'))
cq.exporters.export(shape,str(out/'rail.stl'),tolerance=.02,angularTolerance=.08)
mesh=trimesh.load_mesh(out/'rail.stl')
assert mesh.is_volume
deliver({'rail':mesh},out,{'extents_mm':mesh.extents.tolist()},stl=False)
"""

BADGE = """
from pathlib import Path
import numpy as np
import trimesh
from studio.core.task_operations import deliver
nx,ny=40,24
v=[[x*2-40,y*2-24,6] for y in range(ny+1) for x in range(nx+1)]
faces=[]
for y in range(ny):
 for x in range(nx):
  a=y*(nx+1)+x;b=a+1;c=a+nx+1;d=c+1
  faces.extend([[a,b,d],[a,d,c]])
border=list(range(nx+1))+[y*(nx+1)+nx for y in range(1,ny+1)]+[ny*(nx+1)+x for x in range(nx-1,-1,-1)]+[y*(nx+1) for y in range(ny-1,0,-1)]
base=[]
for i in border:
 base.append(len(v));v.append([v[i][0],v[i][1],0])
bottom=len(v);v.append([0,0,0])
for i,a in enumerate(border):
 j=(i+1)%len(border);b=border[j];lo=base[i];hi=base[j]
 faces.extend([[a,lo,hi],[a,hi,b],[bottom,hi,lo]])
m=trimesh.Trimesh(v,faces,process=False)
assert m.is_volume
c=m.triangles_center
red=(m.face_normals[:,2]>.9)&(((abs(c[:,0])<6)&(abs(c[:,1])<16))|((abs(c[:,0])<16)&(abs(c[:,1])<6)))
m.unmerge_vertices()
m.visual.face_colors=np.tile([0,70,180,255],(len(m.faces),1));m.visual.face_colors[red]=[230,40,40,255]
deliver({'badge':m},Path(workbench['output']),{'extents_mm':m.extents.tolist(),'top_pattern':'explicit two-color cross'},stl=False)
"""

HOSTS = """
from pathlib import Path
from studio.core.kernels import mechanical_geometry as g
from studio.core.task_operations import deliver
meshes={}
for name,x in [('fixed',-28),('moving',30)]:
 s=g.box([x-4,-15,-8],[x+4,15,8])
 for y in [-9,9]:
  s-=g.cx(2,x-5,x+5).translate([0,y,0])
 meshes[name]=g.mesh(s)
deliver(meshes,Path(workbench['output']),{'holes_per_mount':2})
"""


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2))


class Journey:
    def __init__(self, session, folder, workspace_id):
        self.session, self.folder, self.wid = session, folder, workspace_id
        self.calls = []
        self.data = {"case": folder.name, "status": "running", "print_submitted": False, "stages": {}}

    def save(self):
        write(self.folder / "calls.json", self.calls)
        write(self.folder / "result.json", self.data)

    def record(self, key, value):
        self.data["stages"][key] = value
        self.save()

    async def call(self, name, args=None, allow_error=False):
        args = {**(args or {}), "workspace_id": self.wid}
        started = time.monotonic()
        print(self.folder.name, name, args.get("action", ""), flush=True)
        result = await self.session.call_tool(name, args, read_timeout_seconds=1800)
        value = result.structured_content or next((json.loads(c.text) for c in result.content if c.type == "text"), {})
        self.calls.append(
            {
                "tool": name,
                "arguments": args,
                "seconds": time.monotonic() - started,
                "is_error": result.is_error,
                "result": value,
            }
        )
        self.save()
        if not allow_error and (result.is_error or value.get("ok") is False):
            raise RuntimeError(f"{name}: {value}")
        return value

    async def state(self):
        return (await self.call("studio_get_state"))["workbench"]

    async def edit(self, action, params=None):
        state = await self.state()
        return await self.call(
            "studio_edit", {"action": action, "params": params or {}, "expected_revision": state["revision"]}
        )

    async def wait(self, task):
        deadline = time.monotonic() + 600
        while task["status"] in ("queued", "running", "cancelling"):
            if time.monotonic() > deadline:
                raise RuntimeError("Task deadline exceeded; inspect the preserved task state")
            await asyncio.sleep(0.5)
            task = (await self.call("studio_tasks", {"id": task["id"]}))["task"]
        if task["status"] != "completed":
            raise RuntimeError(f"task {task['id']}: {task.get('error')}\n{task.get('log')}")
        artifacts = {a["name"]: a for a in task["artifacts"]}
        for a in artifacts.values():
            assert hashlib.sha256(Path(a["path"]).read_bytes()).hexdigest() == a["sha256"]
        return task, artifacts

    async def task(self, label, template=None, script=None, inputs=(), params=None):
        body = {
            "action": "start",
            "title": label,
            "inputs": list(inputs),
            "params": params or {},
            "render_preview": False,
        }
        if template:
            body["template"] = template
        else:
            body.update(engine="python", script=script)
        task, artifacts = await self.wait((await self.call("studio_task", body))["task"])
        report_name = next((n for n in ("report.json", "removal-audit.json") if n in artifacts), None)
        report = json.loads(Path(artifacts[report_name]["path"]).read_text()) if report_name else None
        self.record(label, {"task_id": task["id"], "artifacts": artifacts, "report": report})
        return task, artifacts

    async def import_task(self, task, artifacts):
        state = await self.state()
        return await self.call(
            "studio_task",
            {
                "action": "import",
                "id": task["id"],
                "artifact_id": artifacts["scene.glb"]["id"],
                "expected_revision": state["revision"],
            },
        )

    async def observe(self, label, inputs, phases=(0,)):
        task, artifacts = await self.wait(
            (
                await self.call(
                    "studio_observe",
                    {
                        "action": "start",
                        "inputs": list(inputs),
                        "params": {"views": ["front", "iso"], "phases": list(phases), "resolution": 420},
                    },
                )
            )["task"]
        )
        self.record(label, {"task_id": task["id"], "artifacts": artifacts})

    async def print_pipeline(self, files, shape="mechanical", mode="auto"):
        for name, args in [
            ("studio_load", {"files": files}),
            ("studio_orient", {"strategy": "flat", "shape": shape}),
            ("studio_arrange", {"mode": mode, "gap": 6}),
            ("studio_export", {"shape": shape}),
            ("studio_check", {}),
        ]:
            result = await self.call(name, args)
            self.record(name, result)
            assert result.get("print_submitted") is False
            if name == "studio_export":
                for plate in result["plates"]:
                    assert plate["readback"]["pass"] and not plate.get("unmatched_parts")
                    assert plate["geometry_readback"]["pass"] and not plate["bambu_moved_objects"]
                    path = Path(plate["project_3mf"])
                    with zipfile.ZipFile(path) as z:
                        assert z.testzip() is None and "Metadata/project_settings.config" in z.namelist()
            if name == "studio_check":
                assert result["plates"]
                assert all(p["returncode"] == 0 and p["grams"] > 0 and p["seconds"] > 0 for p in result["plates"])
        self.record("final_state", await self.call("studio_get_state"))
        self.record("open_command_only", await self.call("studio_send_to_bambu", {"dry_run": True}))

    async def editor_delivery(self):
        state = await self.state()
        ids = [o["id"] for o in state["objects"]]
        inspected = await self.edit("inspect", {"ids": ids})
        self.record("editor_inspection", inspected)
        saved = await self.edit("save")
        self.record("editable_project", saved)
        exported = await self.edit("print_copy", {"ids": ids})
        self.record("print_copies", exported)
        for path in exported["files"]:
            assert trimesh.load_mesh(path).is_volume
        return exported["files"]

    async def run(self, case):
        project = self.folder / "project"
        project.mkdir()
        if project_folder(str(project)) != project:
            raise RuntimeError("--out must be outside an existing Git repository so each case owns its project")
        self.record(
            "project_binding",
            await self.call("studio_workspaces", {"action": "open_project", "worktree": str(project)}),
        )
        self.record("open", await self.call("studio_open", {"mode": "tasks"}))
        assert Path(self.data["stages"]["open"]["job"]).is_relative_to(self.folder)
        caps = await self.call("studio_capabilities")
        assert not any(s.get("configured") for s in caps["services"])
        self.record("capabilities", caps)
        recipe = {"cut": "cut-to-fit", "color": "color-split", "joint": "mechanical-joints"}.get(case)
        if recipe:
            self.record("recipe", await self.call("studio_get_recipe", {"id": recipe}))
            await self.call("studio_use_recipe", {"id": recipe})
        probe = """import socket,errno,json
from pathlib import Path
s=socket.socket();s.settimeout(1)
try:
 s.connect(('192.0.2.1',443))
except OSError as e:
 assert e.errno==errno.EPERM
else:
 raise RuntimeError('External network not blocked')
finally:
 s.close()
Path(workbench['output'],'network.json').write_text(json.dumps({'external_connect':'EPERM'}))
"""
        if self.data["network_isolated"]:
            await self.task("network_probe", script=probe)
        source, assets = await self.task(
            "source", script={"cad": CAD, "cut": BAR, "color": BADGE, "joint": HOSTS}[case]
        )
        source_path = assets["scene.glb"]["path"]
        if case == "cad":
            await self.import_task(source, assets)
            before = await self.state()
            obj = before["objects"][0]
            assert np.allclose(obj["extents_mm"], [80, 40, 50], atol=0.01)
            await self.edit("select", {"ids": [obj["id"]]})
            await self.edit("transform", {"scale": [1.25, 1, 1], "translate_mm": [10, 0, 0]})
            assert np.allclose((await self.state())["objects"][0]["extents_mm"], [100, 40, 50], atol=0.01)
            await self.edit("undo")
            assert np.allclose((await self.state())["objects"][0]["bounds_mm"], obj["bounds_mm"], atol=0.001)
            saved = await self.edit("save")
            await self.edit("primitive", {"kind": "box", "size": [10, 10, 10]})
            state = await self.state()
            reopened = await self.call(
                "studio_edit",
                {"action": "open", "params": {"path": saved["path"]}, "expected_revision": state["revision"]},
                allow_error=True,
            )
            if reopened.get("ok") is False:
                self.record("shared_project_reopen_gap", reopened)
                await self.edit("undo")
            assert len((await self.state())["objects"]) == 1
            self.record(
                "edit_undo_reopen", {"edit_undo_passed": True, "reopen_passed": reopened.get("ok") is not False}
            )
            for action, params in [
                ("rename", {"ids": [obj["id"]], "name": "revision one"}),
                ("primitive", {"kind": "box", "size": [10, 10, 10]}),
                ("rename", {"ids": [obj["id"]], "name": "revision two"}),
            ]:
                await self.edit(action, params)
            for action, name, count in [
                ("undo", "revision one", 2),
                ("undo", "revision one", 1),
                ("undo", obj["name"], 1),
                ("redo", "revision one", 1),
                ("redo", "revision one", 2),
                ("redo", "revision two", 2),
                ("undo", "revision one", 2),
                ("undo", "revision one", 1),
                ("undo", obj["name"], 1),
            ]:
                await self.edit(action)
                state = await self.state()
                assert len(state["objects"]) == count
                assert next(o["name"] for o in state["objects"] if o["id"] == obj["id"]) == name
            self.record("interleaved_undo_redo", {"passed": True, "history_operations": 9})
            await self.observe("observation", [source_path])
        elif case == "cut":
            # Establish that the uncut stock exceeds the selected printer bed.
            self.record("oversize_stock", await self.call("studio_load", {"files": [assets["rail.stl"]["path"]]}))
            await self.import_task(source, assets)
            obj = (await self.state())["objects"][0]
            cut = await self.edit("plane_cut", {"ids": [obj["id"]], "normal": [1, 0, 0], "point_mm": [0, 0, 0]})
            self.record("plane_cut", cut)
            split = await self.edit("export", {"format": "glb"})
            scene = scene_input(split["path"])
            named = []
            for node in scene.graph.nodes_geometry:
                t, key = scene.graph[node]
                m = scene.geometry[key].copy().apply_transform(t)
                named.append((float(m.centroid[0]), node))
            names = [n for _, n in sorted(named)]
            task, output = await self.task(
                "fabrication",
                "connect-parts",
                inputs=[split["path"]],
                params={
                    "parts": names,
                    "connectors": [
                        {
                            "center_mm": [0, y, 0],
                            "axis": [1, 0, 0],
                            "radius_mm": 3,
                            "depth_mm": 8,
                            "min_wall_mm": 2,
                            "profile": "keyed",
                        }
                        for y in [-15, 15]
                    ],
                },
            )
            assert self.data["stages"]["fabrication"]["report"]["status"] == "pass"
            # Replace the two cut objects explicitly; avoid overlapping duplicates.
            state = await self.state()
            replaced = await self.call(
                "studio_task",
                {
                    "action": "import",
                    "id": task["id"],
                    "artifact_id": output["scene.glb"]["id"],
                    "replace_ids": [o["id"] for o in state["objects"]],
                    "expected_revision": state["revision"],
                },
                allow_error=True,
            )
            if replaced.get("ok") is False:
                self.record("multi_object_replace_gap", replaced)
                unchanged = await self.state()
                assert unchanged["revision"] == state["revision"]
                await self.edit("delete", {"ids": [o["id"] for o in state["objects"]]})
                await self.import_task(task, output)
            await self.observe("observation", [source_path, output["scene.glb"]["path"]])
        elif case == "color":
            task, output = await self.task(
                "fabrication",
                "color-inlays",
                inputs=[source_path],
                params={
                    "palette_rgb": [[0, 70, 180], [230, 40, 40]],
                    "pull_direction": [0, 0, 1],
                    "depth_mm": 2.2,
                    "clearance_mm": 0.2,
                },
            )
            assert self.data["stages"]["fabrication"]["report"]["status"] == "pass"
            await self.import_task(task, output)
            await self.observe("observation", [source_path, output["scene.glb"]["path"]])
        else:
            task, output = await self.task(
                "fabrication",
                "install-joint",
                inputs=[source_path],
                params={
                    "parts": ["fixed", "moving"],
                    "family": "pin_hinge",
                    "center_mm": [0, 0, 0],
                    "axis": [0, 0, 1],
                    "anchors_mm": [[-28, 0, 0], [30, 0, 0]],
                    "machining_box_mm": [[-40, -20, -12], [40, 20, 12]],
                    "mount_radius_mm": 2,
                },
            )
            assert self.data["stages"]["fabrication"]["report"]["status"] == "pass"
            _, checked = await self.task(
                "motion", "motion-check", inputs=[output["assembly.urdf"]["path"]], params={"steps": 21}
            )
            assert json.loads(Path(checked["report.json"]["path"]).read_text())["status"] == "pass"
            await self.task(
                "removal",
                "removal-audit",
                inputs=[output[n]["path"] for n in ["parent.stl", "child.stl"]],
                params={"insertion_directions": {"parent": [-1, 0, 0], "child": [1, 0, 0]}, "split_axis": 0},
            )
            assert self.data["stages"]["removal"]["report"]["status"] == "pass_sampled"
            await self.import_task(task, output)
            await self.observe("observation", [output["assembly.urdf"]["path"]], phases=(0, 0.5, 1))
        files = await self.editor_delivery()
        await self.print_pipeline(
            files, shape="relief" if case == "color" else "mechanical", mode="per_part" if case == "color" else "auto"
        )
        if case == "color":
            color_handoff = []
            arranged = self.data["stages"]["studio_arrange"]["plates"]
            for plate in self.data["stages"]["studio_export"]["plates"]:
                name = next(p["parts"][0] for p in arranged if p["index"] == plate["index"])
                expected = "#0046B4" if name.startswith("body_") else "#E62828"
                with zipfile.ZipFile(plate["project_3mf"]) as z:
                    settings = json.loads(z.read("Metadata/project_settings.config"))
                actual = settings.get("filament_colour", [])
                color_handoff.append({"plate": plate["index"], "part": name, "expected": expected, "actual": actual})
            self.record("color_handoff", color_handoff)
            if any([c.upper() for c in row["actual"]] != [row["expected"]] for row in color_handoff):
                self.record("material_color_handoff_gap", {"plates": color_handoff})
        progress = self.data["stages"]["final_state"].get("recipe")
        if progress:
            completed_templates = {
                c["arguments"].get("template")
                for c in self.calls
                if c["tool"] == "studio_task" and c["arguments"].get("action") == "start"
            }
            task_steps = [
                s["key"]
                for s in progress["steps"]
                if s["tool"].removeprefix("studio_task#") in completed_templates and s["status"] == "todo"
            ]
            if task_steps:
                self.record("recipe_progress_gap", {"completed_tasks_still_todo": task_steps, "next": progress["next"]})
        self.data["status"] = (
            "completed_with_gaps" if any(k.endswith("_gap") for k in self.data["stages"]) else "completed"
        )
        artifacts = [
            a for s in self.data["stages"].values() if isinstance(s, dict) for a in s.get("artifacts", {}).values()
        ]
        for a in artifacts:
            assert hashlib.sha256(Path(a["path"]).read_bytes()).hexdigest() == a["sha256"]
        self.data["artifacts_reverified"] = len(artifacts)
        self.save()


async def main(args):
    out = args.out.expanduser().resolve()
    out.mkdir(parents=True, exist_ok=False)
    summaries = []
    for case in args.cases:
        folder = out / case
        folder.mkdir()
        home = folder / "home"
        config = folder / "services.json"
        config.write_text("{}")
        env = {k: os.environ[k] for k in ["PATH", "HOME", "TMPDIR", "LANG"] if k in os.environ}
        env.update(
            PRINT_PREP_HOME=str(home),
            PRINT_PREP_WORKSPACES_HOME=str(home),
            PRINT_PREP_WORKSPACE_ID=args.workspace_id,
            WORKBENCH_SERVICE_CONFIG=str(config),
            STUDIO_LANG="en",
        )
        command = sys.executable
        argv = [str(ROOT / "studio/shell/mcp_server.py")]
        if args.deny_external_network:
            if sys.platform != "darwin":
                raise RuntimeError("Network isolation requires macOS sandbox-exec")
            profile = folder / "loopback-only.sb"
            profile.write_text(
                '(version 1)\n(allow default)\n(deny network*)\n(allow network-bind (local ip "localhost:*"))\n(allow network-inbound (local ip "localhost:*"))\n(allow network-outbound (remote ip "localhost:*"))\n'
            )
            argv = ["-f", str(profile), command, *argv]
            command = "/usr/bin/sandbox-exec"
        j = None
        try:
            async with stdio_client(StdioServerParameters(command=command, args=argv, env=env, cwd=str(ROOT))) as (
                read,
                send,
            ):
                async with ClientSession(read, send) as session:
                    await session.initialize()
                    j = Journey(session, folder, args.workspace_id)
                    j.data["network_isolated"] = args.deny_external_network
                    try:
                        await j.run(case)
                    except Exception as exc:
                        j.data.update(status="failed", error=str(exc), traceback=traceback.format_exc())
                        j.save()
                        print(case, "FAILED", str(exc)[:500], flush=True)
        finally:
            import studio

            for metadata in (home / "workspaces").glob("*/studio.json"):
                studio.stop_server(home=metadata.parent)
        if j:
            summaries.append(j.data)
        write(out / "results.json", summaries)
    print(
        json.dumps(
            [{"case": s["case"], "status": s["status"], "error": s.get("error")} for s in summaries], ensure_ascii=False
        ),
        flush=True,
    )
    return 1 if len(summaries) != len(args.cases) or any(s["status"] == "failed" for s in summaries) else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--workspace-id", required=True)
    parser.add_argument(
        "--cases", nargs="+", choices=["cad", "cut", "color", "joint"], default=["cad", "cut", "color", "joint"]
    )
    parser.add_argument("--deny-external-network", action="store_true")
    sys.exit(asyncio.run(main(parser.parse_args())))
