"""Executed inside Blender or the plugin Python; no imports of private repos."""

from pathlib import Path
import importlib
import importlib.util
import json
import runpy
import sys
import traceback

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

# `Tasks.resume` (studio/core/tasks.py) reruns a saved task's `script.py`
# byte-for-byte, forever — including tasks saved before the studio/core |
# studio/adapters | studio/shell package split. Those old scripts (and a few
# hand-written templates from that era) still say things like
# `from studio.services import run` or `from studio.editor import EditorError`.
# Without this shim they fail with ModuleNotFoundError forever, since the flat
# `studio.<name>` modules no longer exist on disk. Table lists every module
# that moved; `studio.kernels` (a package, not a single module) is included so
# `studio.kernels.mechanical_geometry` / `studio.kernels.scene_viewer...` keep
# resolving too — the finder below matches on the first path segment only, so
# one entry covers the whole subtree.
_LEGACY_MODULE_MAP = {
    "app_resources": "shell.app_resources",
    "assembly_review": "core.assembly_review",
    "assembly_service": "adapters.assembly_service",
    "blender_catalog": "core.blender_catalog",
    "blender_ops": "core.blender_ops",
    "branches": "core.branches",
    "city": "core.city",
    "codex_bridge": "shell.codex_bridge",
    "collaboration": "core.collaboration",
    "editor": "core.editor",
    "editor_schema": "shell.editor_schema",
    "evaluation": "adapters.evaluation",
    "evaluation_schema": "shell.evaluation_schema",
    "generated_editing": "core.generated_editing",
    "geometry_store": "core.geometry_store",
    "history": "core.history",
    "hunyuan_service": "adapters.hunyuan_service",
    "kernels": "core.kernels",
    "lux3d_commerce": "adapters.lux3d_commerce",
    "lux3d_service": "adapters.lux3d_service",
    "lux3d_upload": "adapters.lux3d_upload",
    "materials": "core.materials",
    "mcp_server": "shell.mcp_server",
    "motion": "core.motion",
    "motion_schema": "shell.motion_schema",
    "observation": "core.observation",
    "observation_render": "core.observation_render",
    "observation_run": "core.observation_run",
    "part_chat": "shell.part_chat",
    "platform_preview": "adapters.platform_preview",
    "projects": "core.projects",
    "recipe_progress": "core.recipe_progress",
    "recipe_schema": "shell.recipe_schema",
    "recipes": "core.recipes",
    "scene_assets": "core.scene_assets",
    "seed3d_service": "adapters.seed3d_service",
    "server": "shell.server",
    "service_connections": "adapters.service_connections",
    "service_diagnostics": "adapters.service_diagnostics",
    "services": "adapters.services",
    "shell_kit": "core.head_shell",
    "shell_kit_audit": "core.head_shell_audit",
    "shell_sight_audit": "core.head_shell_sight",
    "shell_vision": "core.head_shell_vision",
    "task_bootstrap": "core.task_bootstrap",
    "task_operations": "core.task_operations",
    "task_recipe_progress": "core.task_recipe_progress",
    "task_schema": "shell.task_schema",
    "task_templates": "core.task_templates",
    "task_worker": "core.task_worker",
    "tasks": "core.tasks",
    "tools_schema": "shell.tools_schema",
    "uploads": "core.uploads",
    "viewer_presentation": "core.viewer_presentation",
    "workspaces": "core.workspaces",
}


class _LegacyStudioLoader:
    """Delegates to a plain `importlib.import_module()` of the real module;
    since that's a normal import, submodules/attributes behave exactly as if
    the caller had imported the new name directly."""

    def __init__(self, real_name: str):
        self._real_name = real_name

    def create_module(self, spec):
        return importlib.import_module(self._real_name)

    def exec_module(self, module):
        pass  # already fully initialised by create_module()


class _LegacyStudioFinder:
    """`sys.meta_path` finder: redirects `studio.<old>[.sub...]` imports to
    `studio.<new>[.sub...]` for every entry in `_LEGACY_MODULE_MAP`, at any
    depth (so `from studio.kernels.scene_viewer.adapters import a8_catalog`
    keeps working, not just top-level `import studio.kernels`)."""

    def find_spec(self, fullname, path, target=None):
        if not fullname.startswith("studio."):
            return None
        head, _, tail = fullname[len("studio.") :].partition(".")
        new_head = _LEGACY_MODULE_MAP.get(head)
        if new_head is None:
            return None
        real_name = f"studio.{new_head}" + (f".{tail}" if tail else "")
        if real_name == fullname:
            return None
        return importlib.util.spec_from_loader(fullname, _LegacyStudioLoader(real_name))


if not any(isinstance(finder, _LegacyStudioFinder) for finder in sys.meta_path):
    # Must run *before* the stdlib's PathFinder, not after: once an aliased
    # package like `studio.kernels` resolves to the real `studio.core.kernels`
    # module object, that object's `__path__` points at the real on-disk
    # `studio/core/kernels/` directory — so PathFinder alone could "find"
    # `studio.kernels.mechanical_geometry.py` sitting right there and execute
    # it a second time under the alias name, instead of reusing the one
    # `create_module()` already imported. Going first means every
    # `studio.<old>[.sub...]` import is always resolved through the alias
    # table, never accidentally rediscovered via a leaked real path.
    sys.meta_path.insert(0, _LegacyStudioFinder())


def main():
    args = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else sys.argv[1:]
    folder = Path(args[0]).resolve()
    request = json.loads((folder / "request.json").read_text())
    workbench = {"inputs": request["inputs"], "params": request["params"], "output": str(folder / "output")}
    if request["engine"] == "blender":
        import bpy

        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.context.scene.unit_settings.system = "METRIC"
        bpy.context.scene.unit_settings.scale_length = 1
    runpy.run_path(str(folder / "script.py"), init_globals={"workbench": workbench}, run_name="__main__")
    if request["engine"] == "blender":
        import bpy
        from mathutils import Vector

        scene = bpy.context.scene
        meshes = [o for o in scene.objects if o.type == "MESH" and not o.hide_render]
        if meshes:
            scene.frame_set(scene.frame_start)
            bpy.ops.export_scene.gltf(
                filepath=str(folder / "output/scene.glb"),
                export_format="GLB",
                export_animations=True,
                export_skins=True,
                use_renderable=True,
            )
            if request.get("render_preview", True):
                points = [o.matrix_world @ Vector(c) for o in meshes for c in o.bound_box]
                lo = Vector([min(p[i] for p in points) for i in range(3)])
                hi = Vector([max(p[i] for p in points) for i in range(3)])
                center, extent = (lo + hi) / 2, max((hi - lo).length, 0.001)
                if not scene.camera:
                    bpy.ops.object.camera_add(location=center + Vector((0.8, -1.2, 0.85)).normalized() * extent * 1.7)
                    scene.camera = bpy.context.object
                    scene.camera.rotation_euler = (center - scene.camera.location).to_track_quat("-Z", "Y").to_euler()
                    scene.camera.data.clip_start = max(extent / 10000, 0.00001)
                    scene.camera.data.clip_end = extent * 100
                if not any(o.type == "LIGHT" for o in scene.objects):
                    for direction, energy in [((1, -2, 3), 1200), ((-2, 1, 2), 700)]:
                        bpy.ops.object.light_add(type="AREA", location=center + Vector(direction) * extent)
                        light = bpy.context.object
                        light.data.energy = energy * extent**2
                        light.data.shape = "DISK"
                        light.data.size = extent * 2
                        light.rotation_euler = (center - light.location).to_track_quat("-Z", "Y").to_euler()
                scene.render.engine = "CYCLES"
                scene.cycles.samples = max(1, min(256, int(request["params"].get("samples", 16))))
                resolution = max(256, min(4096, int(request["params"].get("resolution", 800))))
                scene.render.resolution_x = resolution
                scene.render.resolution_y = resolution
                scene.render.resolution_percentage = 100
                scene.render.image_settings.file_format = "PNG"
                scene.render.filepath = str(folder / "output/preview.png")
                scene.world = scene.world or bpy.data.worlds.new("World")
                scene.world.color = (0.15, 0.15, 0.15)
                bpy.ops.render.render(write_still=True)
            bpy.ops.wm.save_as_mainfile(filepath=str(folder / "output/scene.blend"))
    (folder / "success.json").write_text(json.dumps({"completed": True}))


if __name__ == "__main__":
    try:
        main()
    except BaseException:
        traceback.print_exc()
        sys.exit(1)
