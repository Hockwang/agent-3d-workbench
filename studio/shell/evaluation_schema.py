TOOLS = [
    {
        "name": "studio_evaluation",
        "description": (
            "Connect to the Assembly/WaveAB review platform, reusing its batches, case matrix, "
            "C0-C4 metrics, issue tags, five-dimension comparison and frozen reports. connect sets "
            "the root address and an optional token environment-variable name; read returns "
            "data/sha256; review/compare_review must pass the expected_sha256 just read. An AI "
            "review is saved as a local suggestion — it only enters the platform's human gate after "
            "a human adopts and submits it in the workbench. evaluate uses the platform's original "
            "async analysis task; report only generates a deterministic report and never calls a "
            "paid model; export saves CSV/Markdown locally. preview returns a workbench task; wait "
            "on it with studio_tasks. focus shares the currently focused case."
        ),
        "method": "POST",
        "path": "/api/evaluation",
        "readOnly": False,
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "status",
                        "connect",
                        "catalog",
                        "read",
                        "focus",
                        "inspect",
                        "intake",
                        "create_analysis",
                        "review",
                        "compare_review",
                        "evaluate",
                        "report",
                        "preview",
                        "export",
                    ],
                },
                "base_url": {"type": "string"},
                "auth_env": {"type": "string"},
                "resource": {
                    "type": "string",
                    "enum": [
                        "health",
                        "batches",
                        "analyses",
                        "dimensions",
                        "issue_tags",
                        "test_sets",
                        "cases",
                        "bad_cases",
                        "batch",
                        "analysis",
                        "case",
                        "comparison",
                        "review_data",
                        "reports",
                        "report",
                        "analysis_job",
                        "diagnostic",
                        "nodes",
                    ],
                },
                "id": {"type": "string"},
                "group_id": {"type": "string"},
                "case_run_id": {"type": "string"},
                "case_run_ids": {"type": "array", "items": {"type": "string"}, "maxItems": 4},
                "batch_ids": {"type": "array", "items": {"type": "string"}, "maxItems": 8},
                "name": {"type": "string"},
                "comparison_factor": {"type": "string", "enum": ["spec_level", "demo_version", "generator"]},
                "files": {"type": "array", "items": {"type": "string"}, "maxItems": 8},
                "intake": {
                    "type": "object",
                    "description": (
                        "display_name, package_sha256s, factors "
                        "(spec_level/demo_version/generator/test_set), mappings and tags, confirmed "
                        "after inspection"
                    ),
                },
                "expected_sha256": {"type": "string"},
                "review": {"type": "object"},
                "detail": {
                    "type": "boolean",
                    "description": "true returns the platform's full evidence; default returns condensed data, metric values are not recomputed",
                },
                "offset": {"type": "integer", "minimum": 0},
                "limit": {"type": "integer", "minimum": 1, "maximum": 100},
            },
            "required": ["action"],
        },
    }
]
