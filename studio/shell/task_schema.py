"""Modelling task interface shared by MCP and the right-side workspace."""

from studio.adapters.service_connections import TEMPLATES

# `service_connections.TEMPLATES` is the one place that lists which BUILTINS ids are
# a connectable BYOK template (a `key_env` credential slot, not force-`enabled:
# False`); `assembly` has neither and is absent from it. Deriving the enum from
# that constant's keys directly, instead of re-deriving the same filter by hand
# here, means the two sets cannot drift apart the way a hand-copied filter
# previously did.
_CONNECTABLE_SERVICE_TEMPLATES = list(TEMPLATES)

TOOLS = [
    {
        "name": "studio_services",
        "description": (
            "Manage specialized 3D API connections; list returns the configuration status, probe "
            "only runs a read-only auth test and never generates a model. "
            "save supports environment-variable references; plaintext API keys should be entered "
            "encrypted by the user in the right-side 3D services panel — never put them in chat or "
            "tool arguments. "
            "Does not configure general-purpose model APIs such as GPT. expected_revision comes "
            "from list; an existing task keeps the service configuration it was submitted with."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["action"],
            "additionalProperties": False,
            "properties": {
                "action": {
                    "enum": ["list", "save", "delete", "probe", "balance", "quote", "remote_tasks", "remote_task"]
                },
                "id": {"type": "string"},
                "operation": {"type": "string"},
                "params": {"type": "object"},
                "inputs": {"type": "array", "items": {"type": "string"}, "maxItems": 32},
                "items": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 50,
                    "description": (
                        "Lux3D batch quote, one operation/params/inputs per item. Pass quote_id and "
                        "the quote_item detail when generating."
                    ),
                    "items": {
                        "type": "object",
                        "required": ["operation"],
                        "properties": {
                            "operation": {"type": "string"},
                            "params": {"type": "object"},
                            "inputs": {"type": "array", "items": {"type": "string"}, "maxItems": 32},
                        },
                        "additionalProperties": False,
                    },
                },
                "remote_task_id": {"type": "string", "pattern": "^[1-9][0-9]{0,19}$"},
                "page": {"type": "integer", "minimum": 1},
                "pagesize": {"type": "integer", "minimum": 1, "maximum": 100},
                "status": {"type": "integer", "enum": [0, 1, 3, 4, 6]},
                "starttime": {"type": "integer", "minimum": 0},
                "endtime": {"type": "integer", "minimum": 0},
                "expected_revision": {"type": "string"},
                "template": {"enum": _CONNECTABLE_SERVICE_TEMPLATES},
                "title": {"type": "string"},
                "base_url": {"type": "string"},
                "enabled": {"type": "boolean"},
                "clear_key": {"type": "boolean"},
                "key_env": {"type": "string"},
                "sealed_key": {
                    "type": "object",
                    "description": "Encrypted envelope for UI use only; does not accept a plaintext key",
                    "properties": {k: {"type": "string"} for k in ("key_id", "wrapped_key", "iv", "ciphertext")},
                    "required": ["key_id", "wrapped_key", "iv", "ciphertext"],
                    "additionalProperties": False,
                },
            },
        },
        "readOnly": False,
        "method": "POST",
        "path": "/api/services",
    },
    {
        "name": "studio_observe",
        "description": (
            "Observe/compare real models. start generates same-scale multi-view renders and metrics "
            "for 1-4 local GLB/STL/PLY/URDF files or existing tasks, without modifying the input. "
            "Returns a task ID non-blockingly; poll with read. Once complete, read returns real PNGs "
            "and condensed metrics directly to the AI. Use detail=true for per-part detail. "
            "For URDF, declare y/z with params.urdf_up (default z); phases samples the 0-1 travel "
            "range; geometric metrics cannot substitute for a semantic or motion-quality judgment. "
            "review attaches good/bad/needs_review plus a rationale to the report_sha256 returned by "
            "read; AI and human reviews are recorded separately. "
            "focus picks the version and pose in the workspace, shared by human and AI; read without "
            "an id reads the currently focused observation."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["action"],
            "additionalProperties": False,
            "properties": {
                "action": {"type": "string", "enum": ["start", "read", "review", "focus"]},
                "id": {"type": "string"},
                "variant": {"type": "integer", "minimum": 0},
                "phase_index": {"type": "integer", "minimum": 0},
                "title": {"type": "string"},
                "inputs": {"type": "array", "items": {"type": "string"}, "maxItems": 4},
                "source_tasks": {"type": "array", "items": {"type": "string"}, "maxItems": 4},
                "labels": {"type": "array", "items": {"type": "string"}, "maxItems": 4},
                "params": {
                    "type": "object",
                    "properties": {
                        "views": {"type": "array", "items": {"enum": ["front", "right", "back", "left", "top", "iso"]}},
                        "phases": {"type": "array", "items": {"type": "number", "minimum": 0, "maximum": 1}},
                        "resolution": {"type": "integer", "minimum": 256, "maximum": 1024},
                        "urdf_up": {"enum": ["y", "z"]},
                    },
                    "additionalProperties": False,
                },
                "image": {
                    "type": "boolean",
                    "description": "read returns the overview PNG by default; false reads metrics only",
                },
                "image_file": {
                    "type": "string",
                    "description": "Read the image named in the report's images[].file; defaults to contact-sheet.png",
                },
                "detail": {"type": "boolean"},
                "expected_sha256": {"type": "string"},
                "verdict": {"enum": ["good", "bad", "needs_review"]},
                "note": {"type": "string", "maxLength": 4000},
            },
        },
        "readOnly": False,
        "method": "POST",
        "path": "/api/observe",
    },
    {
        "name": "studio_capabilities",
        "description": (
            "Check local Blender/Python/CAD, workflows that need no generation API, task templates, "
            "and optional service configuration. Prefer completing well-defined modelling and "
            "editing locally."
        ),
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        "readOnly": True,
        "method": "GET",
        "path": "/api/capabilities",
    },
    {
        "name": "studio_tasks",
        "description": (
            "Read a background modelling task's status, artifacts, SHA256 and run log. Only a "
            "completed status means the artifact has actually been delivered."
        ),
        "inputSchema": {"type": "object", "properties": {"id": {"type": "string"}}, "additionalProperties": False},
        "readOnly": True,
        "method": "GET",
        "path": "/api/tasks",
    },
    {
        "name": "studio_task",
        "description": (
            "Start/cancel a modelling task in the current workbench, or import a completed static "
            "model artifact into the editor. "
            "start returns a task ID non-blockingly; poll it with studio_tasks. The script runs in "
            "the user's local Blender/Python — it is not a security sandbox. "
            "The script's global variable workbench provides: inputs (path list), params "
            "(parameters), output (artifact directory). Blender uses meters/Z-up, "
            "autosaves scene.blend, and exports scene.glb with animation. A built-in template can be "
            "passed instead. import requires expected_revision. "
            "from_selection=true exports a copy of the current selection as input; it requires "
            "expected_revision and cannot be combined with inputs. "
            "container/hinge/generated-container/local-dimensions freeze the input and return "
            "editable parameters; rebuild uses id plus a params patch to generate a new task from "
            "the original input, keeping the old result."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["action"],
            "additionalProperties": False,
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["start", "rebuild", "cancel", "resume", "import", "upload", "open"],
                },
                "id": {"type": "string"},
                "artifact_id": {"type": "string"},
                "expected_revision": {"type": "integer"},
                "title": {"type": "string"},
                "replace_ids": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 1,
                    "items": {"type": "string"},
                    "description": "On import, replace this part; the file must keep the project's coordinates. Omit to append instead",
                },
                "expected_versions": {"type": "object", "additionalProperties": {"type": "integer", "minimum": 0}},
                "engine": {"type": "string", "enum": ["blender", "python"]},
                "script": {"type": "string"},
                "template": {"type": "string"},
                "params": {"type": "object"},
                "provider": {
                    "type": "string",
                    "description": (
                        "Optional service ID, see studio_capabilities; credentials are referenced "
                        "via key_env/headers_env. Local modelling does not need a provider"
                    ),
                },
                "operation": {
                    "type": "string",
                    "description": (
                        "Service operation; params is the request JSON. Assembly uses remotely "
                        "reachable URLs such as meshUrl — it does not accept local paths from inputs "
                        "or a selection, and nothing is auto-uploaded. Submit only once; resume "
                        "continues collecting the result under the saved ID without resubmitting. "
                        "cancel only stops the local wait; the remote side may keep billing."
                    ),
                },
                "inputs": {"type": "array", "items": {"type": "string"}},
                "from_selection": {"type": "boolean"},
                "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 3600},
                "render_preview": {"type": "boolean"},
                "name": {"type": "string"},
                "upload_id": {"type": "string"},
                "size": {"type": "integer"},
                "offset": {"type": "integer"},
                "data_base64": {
                    "type": "string",
                    "description": "For file upload only, at most 1 MB per chunk; the AI should prefer using an existing inputs path directly",
                },
            },
        },
        "readOnly": False,
        "method": "POST",
        "path": "/api/task",
    },
]
