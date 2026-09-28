"""studio.shell.tools_schema — the single source of truth for tool definitions shared by WebMCP
(the page's `navigator.modelContext`) and stdio MCP (SPEC.md §8). `GET /api/tools` hands `TOOLS`
to the page as-is; `studio/shell/mcp_server.py` builds its `tools/list` response from the same
definitions, so both sides always agree on parameters and descriptions without maintaining two
copies.

Each tool: `name` / `description` (English — this is content the model reads, including the
English wording of disclaimers like "this tool never sends anything to a printer") /
`inputSchema` (JSON Schema, object at the root) / `readOnly` (bool) / `method` ("GET"|"POST") /
`path` (the corresponding local service endpoint).

`studio_open` only exists on the stdio side (appended separately in `mcp_server.py`) and is not
in this list — it should not be registered as a WebMCP tool on the page (opening the panel is
the precondition for "seeing the panel" in the first place, not a button you click inside it).
"""

from __future__ import annotations

import copy
from studio.shell.editor_schema import TOOLS as EDITOR_TOOLS
from studio.shell.motion_schema import TOOLS as MOTION_TOOLS
from studio.shell.recipe_schema import TOOLS as RECIPE_TOOLS
from typing import Any

_NO_PRINT_NOTE = "This tool never sends anything to a printer."

TOOLS: list[dict[str, Any]] = [
    {
        "name": "studio_get_state",
        "description": (
            "Read-only: read the current panel state (parts, orientation, plate layout, export, "
            "test-slice, send record). The response also includes selection (the part(s) the human "
            "clicked in the viewport), history (operation log), readiness (six readiness items), and "
            "stale (previous results invalidated by an earlier step being redone). " + _NO_PRINT_NOTE
        ),
        "inputSchema": {"type": "object", "properties": {}},
        "readOnly": True,
        "method": "GET",
        "path": "/api/state",
    },
    {
        "name": "studio_list_printers",
        "description": f"Read-only: list the available printer presets (name/bed size/exclusion zones). {_NO_PRINT_NOTE}",
        "inputSchema": {
            "type": "object",
            "properties": {
                "filter": {"type": "string", "description": "Substring filter on the name; empty lists all"}
            },
        },
        "readOnly": True,
        "method": "GET",
        "path": "/api/printers",
    },
    {
        "name": "studio_load",
        "description": (
            "Load a batch of model files (STL/OBJ/PLY/GLB/GLTF/3MF) and compute their geometry stats "
            "(equivalent to the `inspect` CLI command). " + _NO_PRINT_NOTE
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "files": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of absolute file paths",
                },
                "printer": {
                    "type": "string",
                    "description": "Printer preset name; defaults to Bambu Lab P1S 0.4 nozzle",
                },
                "scale": {
                    "type": "number",
                    "description": "Uniform scale factor, must be > 0; mutually exclusive with target_max_mm",
                },
                "target_max_mm": {
                    "type": "number",
                    "description": (
                        "Scale the longest edge of the combined bounding box of all parts to this many "
                        "millimeters; mutually exclusive with scale"
                    ),
                },
                "merge": {"type": "boolean", "description": "Merge each file into a single part"},
            },
            "required": ["files"],
        },
        "readOnly": False,
        "method": "POST",
        "path": "/api/load",
    },
    {
        "name": "studio_orient",
        "description": f"Choose a print orientation for the loaded parts (equivalent to the `orient` CLI command). {_NO_PRINT_NOTE}",
        "inputSchema": {
            "type": "object",
            "properties": {
                "strategy": {
                    "type": "string",
                    "enum": ["auto", "flat", "support", "upright"],
                    "description": "Defaults to auto (looked up by shape)",
                },
                "shape": {
                    "type": "string",
                    "enum": ["generic", "figurine", "relief", "mechanical"],
                    "description": "Shape tag; defaults to generic",
                },
                "set": {
                    "type": "object",
                    "description": (
                        "Manually pin print_up for specific parts, shaped like {part_name: [x,y,z]}; "
                        "takes priority over strategy"
                    ),
                },
                "angle_deg": {
                    "type": "number",
                    "description": (
                        "Overhang angle threshold in degrees, must be between 5 and 85; default comes from "
                        "the printer profile (currently 30 for every printer)"
                    ),
                },
            },
        },
        "readOnly": False,
        "method": "POST",
        "path": "/api/orient",
    },
    {
        "name": "studio_arrange",
        "description": f"Lay the oriented parts out on the printer bed (equivalent to the `arrange` CLI command). {_NO_PRINT_NOTE}",
        "inputSchema": {
            "type": "object",
            "properties": {
                "mode": {
                    "type": "string",
                    "enum": ["single", "per_part", "auto"],
                    "description": "Defaults to auto: opens a new plate automatically when one plate doesn't fit",
                },
                "gap": {
                    "type": "number",
                    "description": "Spacing between parts in millimeters, must be >= 0; defaults to 4",
                },
            },
        },
        "readOnly": False,
        "method": "POST",
        "path": "/api/arrange",
    },
    {
        "name": "studio_export",
        "description": (
            "Write the geometry 3MF and invoke the Bambu Studio CLI to generate a project file "
            "(equivalent to the `export` CLI command); can take tens of seconds with multiple plates. " + _NO_PRINT_NOTE
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "shape": {
                    "type": "string",
                    "enum": ["generic", "figurine", "relief", "mechanical"],
                    "description": (
                        "Determines the process preset's layer-height tier and increments; defaults to "
                        "the shape used by orient"
                    ),
                },
                "process": {
                    "type": "string",
                    "description": "Directly name a process preset, overriding the shape lookup",
                },
                "filament": {
                    "type": "string",
                    "description": "Directly name a filament preset; defaults to the machine's default filament",
                },
                "set": {
                    "type": "object",
                    "description": "Overrides for process preset fields, shaped like {field_name: value}",
                },
                "no_project": {
                    "type": "boolean",
                    "description": "Only write the geometry 3MF; do not invoke Bambu Studio to generate a project file",
                },
            },
        },
        "readOnly": False,
        "method": "POST",
        "path": "/api/export",
    },
    {
        "name": "studio_check",
        "description": (
            "Headless test-slice to estimate weight and print time (equivalent to the `check` CLI "
            "command); can take minutes, and the result is only an estimate. " + _NO_PRINT_NOTE
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "plate": {
                    "type": "integer",
                    "description": "Only test-slice this plate; defaults to test-slicing every plate",
                }
            },
        },
        "readOnly": False,
        "method": "POST",
        "path": "/api/check",
    },
    {
        "name": "studio_send_to_bambu",
        "description": (
            "Open the project file in the Bambu Studio GUI and stop there, waiting for a human to "
            "confirm printing manually (equivalent to the `open` CLI command). The loaded field is "
            "always unverified — the CLI cannot confirm the file actually finished loading in the "
            "GUI, so do not claim the file has loaded based on it. " + _NO_PRINT_NOTE
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "plate": {"type": "integer", "description": "Open this plate; defaults to plate 1"},
                "all": {
                    "type": "boolean",
                    "description": "Open every plate one by one, waiting 3 seconds between each",
                },
                "dry_run": {
                    "type": "boolean",
                    "description": "Only return the command that would run, without actually opening anything",
                },
            },
        },
        "readOnly": False,
        "method": "POST",
        "path": "/api/send",
    },
    {
        "name": "studio_prepare",
        "description": (
            "Run load -> orient -> arrange -> export in one go (optionally plus test-slice and "
            "sending to Bambu Studio), equivalent to the `prepare` CLI command; stops at the first "
            "step that fails. Steps that are omitted use each endpoint's own defaults. " + _NO_PRINT_NOTE
        ),
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": True},
        "readOnly": False,
        "method": "POST",
        "path": "/api/prepare",
    },
    {
        "name": "studio_select",
        "description": (
            "Highlight the given parts in the viewport, so a human can also see which part the AI is "
            "talking about (equivalent to the /api/select endpoint). Does not hold the write lock or "
            "count as a logged operation; a human can click a different part at any time to override "
            "it. " + _NO_PRINT_NOTE
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "parts": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "List of part names to highlight; pass an empty array to clear the selection. "
                        "Every name must be among the currently loaded parts"
                    ),
                },
            },
            "required": ["parts"],
        },
        "readOnly": False,
        "method": "POST",
        "path": "/api/select",
    },
    {
        "name": "studio_undo",
        "description": (
            "Undo the most recent undoable operation (equivalent to the `undo` CLI command/endpoint); "
            "only orient and arrange are undoable, and undoing one cascades to invalidate the "
            "export/check steps that came after it in the pipeline. Passing an id that is not the "
            "most recent undoable record -> 409 not_latest; no undoable record at all -> 409 "
            "nothing_to_undo. " + _NO_PRINT_NOTE
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "id": {
                    "type": "integer",
                    "description": (
                        "id of the record to undo; defaults to undoing the most recent undoable, not-yet-undone record"
                    ),
                },
            },
        },
        "readOnly": False,
        "method": "POST",
        "path": "/api/undo",
    },
]


from studio.shell.task_schema import TOOLS as TASK_TOOLS
from studio.shell.evaluation_schema import TOOLS as EVALUATION_TOOLS


def get_tools() -> list[dict[str, Any]]:
    """Return a deep copy of this definition, so callers can't mutate it in place and pollute the source of truth."""
    return copy.deepcopy(TOOLS + EDITOR_TOOLS + MOTION_TOOLS + RECIPE_TOOLS + TASK_TOOLS + EVALUATION_TOOLS)
