"""Small editable examples built from Blender's own operators, not vendor code."""

CATALOG = [
    {
        "id": "container",
        "title": "task_templates.container_title",
        "description": "task_templates.container_description",
        "params": {"diameter_mm": 80, "height_mm": 100, "wall_mm": 3, "clearance_mm": 0.3},
    },
    {
        "id": "hinge",
        "title": "task_templates.hinge_title",
        "description": "task_templates.hinge_description",
        "params": {"width_mm": 40, "height_mm": 60, "pin_mm": 4, "clearance_mm": 0.3, "angle_deg": 100, "frames": 80},
    },
    {
        "id": "mesh-process",
        "title": "task_templates.mesh_process_title",
        "description": "task_templates.mesh_process_description",
        "params": {"operation": "smooth", "ratio": 0.5, "thickness_mm": 2, "voxel_mm": 1, "iterations": 5},
    },
    {
        "id": "scene-layout",
        "title": "task_templates.scene_layout_title",
        "description": "task_templates.scene_layout_description",
        "params": {"spacing_mm": 30},
    },
]

COMMON = """
import bpy, math
from pathlib import Path
from mathutils import Vector
p = workbench['params']
out = Path(workbench['output'])
def mm(key, default):
    value = float(p.get(key, default))
    if not math.isfinite(value) or value <= 0 or value > 10000:
        raise ValueError(key + ' must be between 0 and 10000 mm')
    return value / 1000
def color(obj, rgba):
    mat = bpy.data.materials.new(obj.name + '_material')
    mat.diffuse_color = rgba
    mat.use_nodes = True
    mat.node_tree.nodes.get('Principled BSDF').inputs['Base Color'].default_value = rgba
    obj.data.materials.clear()
    obj.data.materials.append(mat)
def cylinder(name, radius, depth, location):
    bpy.ops.mesh.primitive_cylinder_add(vertices=96, radius=radius, depth=depth, location=location)
    obj = bpy.context.object; obj.name = name
    return obj
def box(name, size, location):
    bpy.ops.mesh.primitive_cube_add(size=1, location=location)
    obj = bpy.context.object; obj.name = name; obj.dimensions = size
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    return obj
def boolean(a, b, operation='DIFFERENCE'):
    bpy.context.view_layer.objects.active = a
    mod = a.modifiers.new('Solid', 'BOOLEAN'); mod.operation = operation; mod.object = b
    bpy.ops.object.modifier_apply(modifier=mod.name)
    bpy.data.objects.remove(b, do_unlink=True)
def load_inputs():
    objects = []
    for filename in workbench['inputs']:
        old = set(bpy.data.objects)
        path = Path(filename); ext = path.suffix.lower()
        if ext in ('.glb', '.gltf'): bpy.ops.import_scene.gltf(filepath=str(path))
        elif ext == '.blend':
            with bpy.data.libraries.load(str(path), link=False) as (source, target): target.objects = source.objects
            for item in target.objects:
                if item is not None:
                    bpy.context.scene.collection.objects.link(item)
                    if item.type == 'CAMERA' and bpy.context.scene.camera is None: bpy.context.scene.camera = item
        elif ext == '.fbx': bpy.ops.import_scene.fbx(filepath=str(path))
        elif ext == '.bvh': bpy.ops.import_anim.bvh(filepath=str(path), global_scale=.01)
        elif ext == '.stl': bpy.ops.wm.stl_import(filepath=str(path), global_scale=.001)
        elif ext == '.obj': bpy.ops.wm.obj_import(filepath=str(path), global_scale=.001)
        elif ext == '.ply': bpy.ops.wm.ply_import(filepath=str(path), global_scale=.001)
        else: raise ValueError('Use GLB/GLTF/STL/OBJ/PLY/BLEND/FBX/BVH inputs')
        widgets = {bone.custom_shape for arm in bpy.context.scene.objects if arm.type == 'ARMATURE' for bone in arm.pose.bones if bone.custom_shape}
        for widget in widgets: widget.hide_render = True
        objects.extend(o for o in bpy.context.scene.objects if o not in old and o.type == 'MESH' and o not in widgets)
    if not objects and not any(o.type=='ARMATURE' for o in bpy.context.scene.objects): raise ValueError('This task requires mesh or armature inputs')
    return objects
"""

SCRIPTS = {
    "container": """
d, h, wall = mm('diameter_mm', 80), mm('height_mm', 100), mm('wall_mm', 3)
gap = mm('clearance_mm', .3)
if wall * 4 >= min(d, h): raise ValueError('Wall thickness leaves no usable cavity')
body = cylinder('container', d/2, h, (0, 0, h/2))
inner = cylinder('cavity', d/2-wall, h, (0, 0, h/2+wall))
boolean(body, inner)
lid = cylinder('lid', d/2+wall, wall, (d*1.3, 0, wall/2))
plug = cylinder('lid_locator', d/2-wall-gap, wall*2, (d*1.3, 0, wall*2))
boolean(lid, plug, 'UNION')
color(body, (.16,.32,.56,1)); color(lid, (.68,.72,.78,1))
""",
    "hinge": """
w, h, pin, gap = mm('width_mm',40), mm('height_mm',60), mm('pin_mm',4), mm('clearance_mm',.3)
if pin*4 >= min(w,h): raise ValueError('Pin is too large for the hinge leaves')
radius=pin/2; outer=radius+max(pin/2,.002); thickness=max(pin*.6,.002)
left=box('fixed_leaf',(w,thickness,h),(-w/2-outer+thickness,0,h/2))
right=box('moving_leaf',(w,thickness,h),(w/2+outer-thickness,0,h/2))
segment=h/5
for i in range(5):
    knuckle=cylinder('knuckle',outer,segment-gap*2,(0,0,(i+.5)*segment))
    bore=cylinder('bore',radius+gap,segment,(0,0,(i+.5)*segment))
    boolean(knuckle,bore)
    boolean(left if i%2==0 else right,knuckle,'UNION')
shaft=cylinder('pin',radius,h+pin,(0,0,h/2))
color(left,(.18,.32,.56,1));color(right,(.8,.49,.16,1));color(shaft,(.65,.68,.72,1))
bpy.context.scene.cursor.location=(0,0,0)
bpy.ops.object.select_all(action='DESELECT');right.select_set(True);bpy.context.view_layer.objects.active=right
bpy.ops.object.origin_set(type='ORIGIN_CURSOR')
angle_limit=float(p.get('angle_deg',100));frames=int(p.get('frames',80))
if not math.isfinite(angle_limit) or not 0<angle_limit<=160 or not 6<=frames<=2400: raise ValueError('angle_deg must be (0,160], frames 6–2400')
for frame,angle in [(1,0),(frames//2,angle_limit),(frames,0)]:
    right.rotation_euler.z=math.radians(angle);right.keyframe_insert(data_path='rotation_euler',frame=frame)
bpy.context.scene.frame_end=frames;bpy.context.scene.render.fps=24
""",
    "mesh-process": """
objects=load_inputs(); operation=p.get('operation','smooth')
original_faces={obj.name:len(obj.data.polygons) for obj in objects}
for obj in objects:
    bpy.ops.object.select_all(action='DESELECT');obj.select_set(True);bpy.context.view_layer.objects.active=obj
    if operation=='uv':
        bpy.ops.object.mode_set(mode='EDIT');bpy.ops.mesh.select_all(action='SELECT')
        bpy.ops.uv.smart_project(island_margin=.02);bpy.ops.object.mode_set(mode='OBJECT')
        continue
    if operation=='smooth':
        mod=obj.modifiers.new('Smooth','SMOOTH');mod.factor=.5;mod.iterations=max(1,min(100,int(p.get('iterations',5))))
    elif operation=='decimate':
        ratio=float(p.get('ratio',.5))
        if not 0<ratio<1: raise ValueError('ratio must be between 0 and 1')
        mod=obj.modifiers.new('Decimate','DECIMATE');mod.ratio=ratio
    elif operation=='solidify':
        mod=obj.modifiers.new('Thickness','SOLIDIFY');mod.thickness=mm('thickness_mm',2);mod.offset=-1
    elif operation=='remesh':
        mod=obj.modifiers.new('Remesh','REMESH');mod.mode='VOXEL';mod.voxel_size=mm('voxel_mm',1)
    else: raise ValueError('operation is smooth/decimate/solidify/remesh/uv')
    bpy.ops.object.modifier_apply(modifier=mod.name)
import bmesh, json
reports=[]
for obj in objects:
    bm=bmesh.new();bm.from_mesh(obj.data)
    reports.append({'object':obj.name,'before_polygons':original_faces[obj.name],'after_polygons':len(obj.data.polygons),
        'boundary_edges':sum(e.is_boundary for e in bm.edges),'nonmanifold_edges':sum(not e.is_manifold for e in bm.edges),
        'uv_layers':len(obj.data.uv_layers)})
    bm.free()
(out/'report.json').write_text(json.dumps({'operation':operation,'objects':reports,'quality':'review geometry and appearance before delivery'},indent=2))
""",
    "scene-layout": """
objects=load_inputs();gap=mm('spacing_mm',30);cursor=0
for obj in objects:
    points=[obj.matrix_world@Vector(c) for c in obj.bound_box]
    lo=Vector([min(v[i] for v in points) for i in range(3)])
    hi=Vector([max(v[i] for v in points) for i in range(3)])
    matrix=obj.matrix_world.copy();matrix.translation+=Vector((cursor-lo.x,-(lo.y+hi.y)/2,-lo.z));obj.matrix_world=matrix;cursor+=hi.x-lo.x+gap
""",
}


def script_for(template):
    if template in {entry["id"] for entry in FABRICATION_CATALOG}:
        return f"from studio.core.fabrication import run\nrun({template!r}, workbench)"
    from studio.core.editor import EditorError
    from studio.core.task_operations import OPERATIONS
    from studio.core.generated_editing import OPERATIONS as GENERATED

    if template == "shell-kit":
        return "from studio.core.head_shell import head_shell\nhead_shell(workbench)"
    if template in {"merge-review", "a8-review"}:
        return f"from studio.core.assembly_review import run\nrun({template!r}, workbench)"
    if template in GENERATED:
        return f"from studio.core.generated_editing import OPERATIONS\nOPERATIONS[{template!r}](workbench)"
    if template == "model-observe":
        return "from studio.core.observation_run import run\nrun(workbench)"
    if template in OPERATIONS:
        return f"from studio.core.task_operations import run\nrun({template!r}, workbench)"
    if template in {x["id"] for x in BLENDER_CATALOG}:
        return COMMON + f"\nfrom studio.core.blender_ops import run\nrun({template!r}, globals())"
    if template not in SCRIPTS:
        raise EditorError.coded("task_templates.unknown_template")
    return COMMON + "\n" + SCRIPTS[template]


from studio.core.task_operations import CATALOG as PYTHON_CATALOG

CATALOG.extend(PYTHON_CATALOG)

from studio.core.blender_catalog import CATALOG as BLENDER_CATALOG

CATALOG.extend(BLENDER_CATALOG)

from studio.core.observation import CATALOG as OBSERVATION_CATALOG

CATALOG.extend(OBSERVATION_CATALOG)

from studio.core.generated_editing import CATALOG as GENERATED_CATALOG

CATALOG.extend(GENERATED_CATALOG)

from studio.core.assembly_review import CATALOG as ASSEMBLY_CATALOG

CATALOG.extend(ASSEMBLY_CATALOG)

from studio.core.head_shell import CATALOG as HEAD_SHELL_CATALOG

CATALOG.extend(HEAD_SHELL_CATALOG)

from studio.core.fabrication import CATALOG as FABRICATION_CATALOG

CATALOG.extend(FABRICATION_CATALOG)


def localized_catalog():
    """`CATALOG` (built once, at import time, by concatenating every producer
    module's list above) stores message *codes* in its display fields — see
    the CATALOG-convention note in `studio/core/messages_tasks.py` — because a
    module-level list can't itself follow the per-request language. This
    renders a deep copy in whatever language `studio.i18n.get_language()`
    currently reports, which is what `Tasks.capabilities()` hands to callers
    as `"templates"`.

    A field that isn't a registered code (e.g. a producer module not yet
    converted, or observation.py's own `observation.*` codes registered
    elsewhere) renders back to itself unchanged (`studio.i18n.render()`'s
    fallback), so a catalog built from modules in different conversion states
    is harmless here.
    """
    import copy

    from studio.i18n import render

    result = copy.deepcopy(CATALOG)
    for entry in result:
        for key in ("title", "description", "hint"):
            value = entry.get(key)
            if isinstance(value, str):
                entry[key] = render(value)
        labels = entry.get("labels")
        if isinstance(labels, dict):
            entry["labels"] = {k: render(v) if isinstance(v, str) else v for k, v in labels.items()}
        choices = entry.get("choices")
        if isinstance(choices, dict):
            entry["choices"] = {
                field: (
                    {value: render(label) if isinstance(label, str) else label for value, label in options.items()}
                    if isinstance(options, dict)
                    else options
                )
                for field, options in choices.items()
            }
    return result
