"""studio.core.capabilities — fine-grained capability names behind a coarse
tool, used by `studio.core.recipes` to validate a `tool#action` recipe step
(see that module's docstring and `recipes/README.md` for the step grammar).

The real MCP/HTTP surface is coarse (22 tools); several of those tools carry
their own, much finer namespace of actions/templates/operations (`studio_edit`
has ~26 actions, `studio_task` has dozens of templates plus whatever hosted
adapters declare, `studio_motion`'s action enum lives in the wire-contract
layer). A recipe step that only checks the coarse tool name can silently
claim "ready" for a fine-grained capability that was never implemented, or
never notice when one gets removed. `build()` returns the map `recipes.py`
checks a `tool#action` suffix against.

Everything derivable from data already living in `studio.core` is read
directly here (`studio.core.editor_actions`, `studio.core.task_templates`).
`studio_motion`'s action enum and hosted-service operation ids are NOT: the
first lives only in `studio.shell.motion_schema` (a wire-contract file core
must not import — see the layer rule in `docs/ARCHITECTURE.md` and
`tests/test_layering.py`), so it is read out of the already-injected tool
schema list instead; the second is an adapters/shell concern
(`studio.adapters.services`), so it arrives as an optional callable a caller
injects (`studio.shell.server` wires this into `studio.core.recipes.configure()`).
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from studio.core.editor_actions import ACTIONS as _EDITOR_ACTIONS


def task_template_ids() -> set[str]:
    """Task-template/operation ids `studio_task` can start locally (no
    hosted service involved) — every entry `studio.core.task_templates.CATALOG`
    concatenates from its producer modules. Exposed separately (not just
    folded into `build()`'s result) so `studio.core.recipes` can tell, for a
    given `studio_task#<id>` step, whether `<id>` is a local template (the
    step's `call` should carry `template`) or a hosted operation (`operation`)
    without re-deriving that distinction from a set difference each time.
    """
    from studio.core.task_templates import CATALOG as _TASK_CATALOG

    return {entry["id"] for entry in _TASK_CATALOG}


def build(
    tools_by_name: dict[str, dict[str, Any]],
    hosted_operations_provider: Optional[Callable[[], set[str]]] = None,
) -> dict[str, set[str]]:
    """`{base_tool: {action_or_template_or_operation names}}` for every base
    tool that has a fine-grained namespace a recipe step's `tool#action`
    suffix can reference. A base tool absent from this map (or a base tool
    whose step has no `#` suffix at all) is only checked for coarse
    existence in `tools_by_name` — see `studio.core.recipes._step_available`.

    `tools_by_name` is the same `{name: schema}` map `studio.core.recipes`
    already builds from its injected tool-schemas provider; passed in here
    (rather than re-fetched) so this module never needs its own provider for
    that half of the picture.
    """
    hosted_ops = set(hosted_operations_provider()) if hosted_operations_provider else set()
    capability_map: dict[str, set[str]] = {
        "studio_edit": set(_EDITOR_ACTIONS),
        "studio_task": task_template_ids() | hosted_ops,
    }
    motion_tool = tools_by_name.get("studio_motion")
    if motion_tool:
        action_schema = (motion_tool.get("inputSchema", {}).get("properties", {}) or {}).get("action", {})
        enum = action_schema.get("enum")
        if enum:
            capability_map["studio_motion"] = set(enum)
    return capability_map
