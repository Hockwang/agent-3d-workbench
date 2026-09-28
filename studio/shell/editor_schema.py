"""One editing contract for MCP, WebMCP and human UI actions."""

TOOLS = [
    {
        "name": "studio_edit",
        "description": (
            "City: city_import takes a Cubely ZIP via params.path; city_catalog paginates through "
            "people/fixtures; city_checkout loads a local edit via params.instance_id. city_register "
            "is for viewport initialization. "
            "Edits the 3D Workbench; humans and the AI share the same state. scene_import imports "
            "complete GLB instances (files), preserving hierarchy/skinning/animation; "
            "scene_export exports the local-edit source (meters/Y-up) of a single instance in ids, "
            "and scene_replace updates a single id in place with the GLB at path, preserving its "
            "ID/placement and affecting only the selected instance. "
            "Make the edits to the source in Blender and verify via observation; do not use a plain "
            "replace, which would flatten the skeleton. Scene instances support transform, duplicate, "
            "material, save/undo and motion_set. "
            "Read studio_get_state.workbench first, "
            "and submit expected_revision with every call; on conflict, refresh and retry. Object IDs "
            "are workbench.objects[].id. "
            "Coordinates are millimeters, Z-up. import appends; GLB is auto-converted from "
            "meters/Y-up, STL/OBJ default to millimeters/Z-up. "
            "transform is a world-space delta around the selection center; matrix instead sets an "
            "absolute transform on a single object. "
            "plane_cut requires a closed solid; plane_cut/boolean/simplify/repair convert the result "
            "to a plain-color mesh, so allow_material_loss must be set explicitly when the object is "
            "textured. "
            "merge only concatenates mesh data; boolean is the one that does a solid operation. "
            "repair only fixes small holes, normals, and duplicate/degenerate faces. "
            "export defaults to exporting the visible objects; pass ids to export specific objects. "
            "save writes a self-contained project; open opens a project and can be undone. "
            "print_copy only creates a millimeter STL copy and returns files, which can then be "
            "handed to studio_load; it never sends anything to print. "
            "All edits autosave and support undo/redo. Paths must be local absolute paths; export "
            "never overwrites an existing file. "
            "material can target one object's specific material slot(s) via material_slots (slot "
            "indices are in objects[].materials); "
            "replace substitutes one model file from files for one part in ids, keeping the first "
            "part's ID (additional meshes in the file become derived parts); the file's coordinates "
            "must match those at export time — there is no automatic centering or alignment. "
            "Omitting the slot indices modifies every material on the selected object(s). "
            "base_color_texture is a local image path or null (removes the base-color texture); it "
            "requires the object to already have UVs."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["action", "expected_revision"],
            "properties": {
                "expected_revision": {"type": "integer", "minimum": 0},
                "expected_versions": {
                    "type": "object",
                    "additionalProperties": {"type": "integer", "minimum": 0},
                    "description": (
                        "For shared-project edits, recommended to carry {object_id: "
                        "objects[].version}; different parts can be submitted in parallel against the "
                        "same project version, and a stale version for the same part is rejected."
                    ),
                },
                "action": {
                    "type": "string",
                    "enum": [
                        "city_import",
                        "city_catalog",
                        "city_register",
                        "city_checkout",
                        "scene_import",
                        "scene_replace",
                        "scene_export",
                        "motion_set",
                        "motion_clear",
                        "motion_import",
                        "motion_export",
                        "import",
                        "replace",
                        "primitive",
                        "select",
                        "rename",
                        "visibility",
                        "isolate",
                        "show_all",
                        "duplicate",
                        "delete",
                        "transform",
                        "plane_cut",
                        "split_components",
                        "merge",
                        "boolean",
                        "inspect",
                        "repair",
                        "simplify",
                        "material",
                        "extract_faces",
                        "undo",
                        "redo",
                        "save",
                        "open",
                        "export",
                        "print_copy",
                    ],
                },
                "params": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "ids": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Defaults to the current selection; export defaults to every visible object",
                        },
                        "instance_id": {"type": "string"},
                        "query": {"type": "string"},
                        "offset": {"type": "integer", "minimum": 0},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 100},
                        "instances": {"type": "array", "items": {"type": "object"}},
                        "files": {"type": "array", "items": {"type": "string"}},
                        "units": {"type": "string", "enum": ["auto", "mm", "cm", "m"]},
                        "name": {"type": "string"},
                        "visible": {"type": "boolean"},
                        "kind": {"type": "string", "enum": ["box", "sphere"]},
                        **{
                            key: {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3}
                            for key in ["size", "translate_mm", "rotate_deg", "scale", "normal", "point_mm"]
                        },
                        "matrix": {
                            "type": "array",
                            "minItems": 4,
                            "maxItems": 4,
                            "items": {"type": "array", "items": {"type": "number"}, "minItems": 4, "maxItems": 4},
                        },
                        "operation": {"type": "string", "enum": ["union", "difference", "intersection"]},
                        "allow_material_loss": {"type": "boolean"},
                        "require_watertight": {"type": "boolean"},
                        "face_ids": {
                            "type": "array",
                            "items": {"type": "integer", "minimum": 0},
                            "description": (
                                "extract_faces: triangle indices on the current object; preserves "
                                "UV/material and does not auto-cap the resulting hole"
                            ),
                        },
                        "radius_mm": {
                            "type": "number",
                            "exclusiveMinimum": 0,
                            "description": (
                                "extract_faces: when face_ids is omitted, splits off triangles whose "
                                "center falls within this radius of point_mm"
                            ),
                        },
                        "ratio": {"type": "number", "exclusiveMinimum": 0, "exclusiveMaximum": 1},
                        "color": {"type": "string", "pattern": "^#[0-9a-fA-F]{6}$"},
                        "roughness": {"type": "number", "minimum": 0, "maximum": 1},
                        "metallic": {"type": "number", "minimum": 0, "maximum": 1},
                        "material_slots": {
                            "type": "array",
                            "minItems": 1,
                            "uniqueItems": True,
                            "items": {"type": "integer", "minimum": 0},
                        },
                        "base_color_texture": {"type": ["string", "null"]},
                        "motion": {"type": "object"},
                        "blend_path": {"type": "string"},
                        "path": {"type": "string"},
                        "format": {"type": "string", "enum": ["glb", "stl", "zip"]},
                    },
                },
            },
        },
        "readOnly": False,
        "method": "POST",
        "path": "/api/edit",
    }
]
