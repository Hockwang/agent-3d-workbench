"""Human/AI motion editing shares workspace transactions and the FK evaluator."""

from studio.shell.editor_schema import TOOLS as EDITOR_TOOLS
import copy

_PARAMS = copy.deepcopy(EDITOR_TOOLS[0]["inputSchema"]["properties"]["params"])
TOOLS = [
    {
        "name": "studio_motion",
        "description": (
            "Motion editing: set saves a studio-motion/v1 document on one object (mechanical joint: "
            "MotionForge world axis x/y/z, pivot in the parent joint's local coordinates in meters, "
            "angle in deg / translation in m; skin: the original GLB bone's local XYZ rotation in "
            "deg, or an original clip). "
            "parameters=[{id,default,unit,desc}]; steps=[{id,t_start,t_end,value_start,value_end,"
            "easing}]; a skin step additionally has bone/axis; keyframes=[{time,value}]. "
            "joint={type:revolute|prismatic|fixed,axis,origin:[x,y,z],parent:object ID or "
            "null,limits:[min,max]}. Every motion document needs schema, kind, duration, fps, mode, "
            "parameters, steps, keyframes. "
            "Check studio_get_state first to see an object's motion; set/clear take ids, "
            "expected_revision and expected_versions. "
            "import accepts a self-contained rigged GLB (optionally with a blend_path carrying "
            "packed assets) or a MotionForge v7 / Studio ZIP; export accepts zip (an editable "
            "project) or glb (baked animation; the skeleton must be a single rig). "
            "Rigging does not need an LLM API: currently GPT uses studio_task's "
            "rig-bind/skin-weights/Blender script, then imports the result. "
            "The current v7 external import supports a single clip with fixed topology; it does not "
            "support reparent events/overflow. save also preserves every motion document in the "
            "project."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["action", "expected_revision"],
            "properties": {
                "action": {"type": "string", "enum": ["set", "clear", "import", "export"]},
                "expected_revision": {"type": "integer", "minimum": 0},
                "expected_versions": {"type": "object", "additionalProperties": {"type": "integer", "minimum": 0}},
                "params": _PARAMS,
            },
        },
        "readOnly": False,
        "method": "POST",
        "path": "/api/motion",
    }
]
