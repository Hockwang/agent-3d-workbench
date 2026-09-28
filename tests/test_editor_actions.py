"""Coverage for the `studio.core.editor_actions` registry that
`Workspace._apply` dispatches to (see that module's docstring for the shape).

These tests do not re-verify individual action *behaviour* — every action
function was moved verbatim out of the old `_apply` if/elif chain, and the
existing `test_editor.py` / `test_motion.py` / `test_scene_assets.py` /
`test_collaboration.py` suites already exercise that behaviour end to end
through `Workspace.execute`. What is new here, and worth a dedicated test
for, is the *registry* itself: that it covers exactly the action names the
MCP schema advertises (minus the ones dispatched to sibling subsystems
before `_apply` ever looks at the registry), that its declared metadata
matches what `Workspace.execute` actually does with each action name, and
that unknown/known-but-guarded actions still fail the same way they did
before the refactor.
"""

from __future__ import annotations

import pytest

from studio.core import editor_actions
from studio.core.editor import EditorError, Workspace
from studio.shell.editor_schema import TOOLS
from tests.helpers import act

# Action names `Workspace._apply` dispatches to `city.py` / `scene_assets.py`
# / `motion.py` before it ever consults `editor_actions.ACTIONS` — see the
# top of `Workspace._apply`. These own their own action namespaces and are
# intentionally absent from this registry.
_DELEGATED_PREFIXES = ("city_", "scene_", "motion_")


def _schema_actions() -> set[str]:
    (edit_tool,) = [t for t in TOOLS if t["name"] == "studio_edit"]
    return set(edit_tool["inputSchema"]["properties"]["action"]["enum"])


def test_registry_matches_schema_minus_delegated_prefixes():
    """`ACTIONS` and the `studio_edit` schema enum must describe exactly the
    same set of core actions. A name added to one and not the other is a
    real drift (a schema-advertised action nothing handles, or a registered
    action nobody can ever call) — report it here instead of quietly
    special-casing either side."""
    schema_actions = _schema_actions()
    delegated = {a for a in schema_actions if a.startswith(_DELEGATED_PREFIXES)}
    core_schema_actions = schema_actions - delegated

    assert set(editor_actions.ACTIONS) == core_schema_actions, (
        f"only in schema: {sorted(core_schema_actions - set(editor_actions.ACTIONS))}; "
        f"only in registry: {sorted(set(editor_actions.ACTIONS) - core_schema_actions)}"
    )
    # Sanity check on the split itself, so a typo'd prefix can't silently
    # empty out `delegated` and make the assertion above vacuous.
    assert delegated and all(not a.startswith(_DELEGATED_PREFIXES) for a in core_schema_actions)


def test_no_duplicate_or_unregistered_action_names():
    assert len(editor_actions.ACTIONS) > 20  # guard against an empty/partial registry
    for name, spec in editor_actions.ACTIONS.items():
        assert spec.name == name
        assert callable(spec.func)


# The exact action-name sets `Workspace.execute` branches on to skip the undo
# snapshot / revision bump for a given action (see its two `action not in
# (...)` checks). `_apply`'s registry doesn't drive that logic — `execute`
# still does, unchanged — but `ActionSpec.snapshot`/`read_only` claim to
# document the same branch, so pin them against each other here: if a future
# edit changes one without the other, this fails instead of silently
# documenting a lie.
_NOT_SNAPSHOTTED = {"undo", "redo", "select", "inspect", "export", "save", "print_copy"}
_READ_ONLY = {"inspect"}


def test_snapshot_and_read_only_metadata_matches_execute_behaviour():
    assert {n for n, s in editor_actions.ACTIONS.items() if not s.snapshot} == _NOT_SNAPSHOTTED
    assert {n for n, s in editor_actions.ACTIONS.items() if s.read_only} == _READ_ONLY
    # read_only actions never snapshot either (both skip lists agree on this).
    assert _READ_ONLY <= _NOT_SNAPSHOTTED


_BLOCKS_MOTION_SCENE = {
    "replace",
    "material",
    "repair",
    "simplify",
    "plane_cut",
    "split_components",
    "extract_faces",
    "merge",
    "boolean",
}


def test_blocks_motion_scene_matches_former_geometry_actions_set():
    assert {n for n, s in editor_actions.ACTIONS.items() if s.blocks_motion_scene} == _BLOCKS_MOTION_SCENE
    for name in _BLOCKS_MOTION_SCENE:
        assert editor_actions.blocks_motion_scene(name)
    assert not editor_actions.blocks_motion_scene("rename")
    assert not editor_actions.blocks_motion_scene("not-a-real-action")


@pytest.fixture
def w(tmp_path):
    return Workspace(tmp_path / "workspace")


def test_unregistered_action_name_raises_unknown_edit_action_error(w):
    with pytest.raises(EditorError, match="未知编辑操作"):
        act(w, "not-a-real-action")


def test_undo_redo_dispatch_through_the_registry(w, tmp_path):
    import trimesh

    path = tmp_path / "box.stl"
    trimesh.creation.box([10, 10, 10]).export(path)
    act(w, "import", files=[str(path)])
    assert len(w.state()["objects"]) == 1
    act(w, "delete")
    assert w.state()["objects"] == []
    act(w, "undo")
    assert len(w.state()["objects"]) == 1
    act(w, "redo")
    assert w.state()["objects"] == []
    with pytest.raises(EditorError, match="没有可撤销/重做的操作"):
        act(w, "redo")
