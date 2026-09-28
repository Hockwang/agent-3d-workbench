"""Integration checks for shared recipes, real editor operations and invalidation."""

from pathlib import Path
import json

import pytest

from studio.core import recipes
from studio.shell.server import StudioBackend


@pytest.fixture
def backend(tmp_path, monkeypatch):
    monkeypatch.setenv("PRINT_PREP_HOME", str(tmp_path / "home"))
    return StudioBackend(tmp_path / "job", "test-recipe-token")


def edit(backend, action, params=None, actor="human"):
    body = {"action": action, "params": params or {}, "expected_revision": backend.editor.doc["revision"]}
    status, result = backend.run_write(
        "edit", lambda: backend.editor.execute(body, actor), actor=actor, request_body=body
    )
    assert status == 200, result
    return result


def use(backend, name):
    result = backend.run_write("recipe", lambda: backend.api_recipe_use({"id": name}, "human"))
    assert result[0] == 200, result


def test_complete_catalog_and_real_capability_mapping(backend):
    catalog = backend.api_recipes()
    assert not catalog["problems"]
    assert len(catalog["recipes"]) == 18
    # The four local fabrication templates now bind the five formerly missing
    # routes; readiness is a tool contract, not finished-product acceptance.
    assert sum(r["availability"] == "ready" for r in catalog["recipes"]) == 18
    cut = next(r for r in catalog["recipes"] if r["id"] == "cut-to-fit")
    assert cut["missing_tools"] == []


def test_hosted_task_operations_survives_a_malformed_services_catalog(monkeypatch):
    """`services.catalog()` can raise outright when the local connections store
    (`connections.private.json`) is corrupted (`EditorError`, see
    `service_connections.read_store()`). `_hosted_task_operations()` is the
    provider `recipes.configure()` injects into `load_recipes()`, which has no
    per-recipe try/except around this half of the picture — it must degrade to
    "no hosted operations" instead of taking recipe loading down with it."""
    from studio.shell import server as server_mod

    def boom():
        raise RuntimeError("malformed services.json")

    monkeypatch.setattr(server_mod.services, "catalog", boom)
    assert server_mod._hosted_task_operations() == set()


def test_recipe_catalog_still_loads_when_the_hosted_catalog_is_broken(backend, monkeypatch):
    from studio.shell import server as server_mod

    def boom():
        raise RuntimeError("malformed services.json")

    monkeypatch.setattr(server_mod.services, "catalog", boom)
    catalog = backend.api_recipes()
    assert not catalog["problems"]
    # image-to-print's studio_task#image-to-3d step can no longer be confirmed
    # available without a hosted catalog to ask; it demotes to needs_tools
    # instead of the whole listing crashing.
    image_to_print = next(r for r in catalog["recipes"] if r["id"] == "image-to-print")
    assert image_to_print["availability"] == "needs_tools"
    assert "studio_task#image-to-3d" in image_to_print["missing_tools"]


@pytest.mark.parametrize(
    "name,action,params",
    [
        ("mesh-cleanup", "repair", {}),
        ("mesh-lightweight", "simplify", {"ratio": 0.5}),
        ("mesh-components", "split_components", {}),
        ("mesh-plane-cut", "plane_cut", {"normal": [0, 0, 1], "point_mm": [0, 0, 0]}),
        ("mesh-material", "material", {"color": "#f08030", "roughness": 0.3}),
    ],
)
def test_all_editor_routes_use_real_geometry_and_export(backend, name, action, params):
    use(backend, name)
    assert backend.build_state()["recipe"]["next"] == "load"
    edit(backend, "primitive", {"kind": "sphere", "size": [40, 40, 40]})
    assert backend.build_state()["recipe"]["next"] == "inspect"
    edit(backend, "inspect", actor="ai")
    assert backend.build_state()["recipe"]["next"] == "process"
    edit(backend, action, params)
    assert backend.build_state()["recipe"]["next"] == "export"
    result = edit(backend, "export", {"format": "glb"}, actor="ai")
    assert Path(result["path"]).is_file()
    state = backend.build_state()
    assert state["recipe"]["done"] == 4 and state["recipe"]["next"] is None
    # Restart keeps completed receipts and their binding to this geometry.
    restarted = StudioBackend(backend.job_dir, "replacement-test-token")
    assert restarted.build_state()["recipe"]["done"] == 4
    # Further edits and undo cannot retain a misleading completed route.
    edit(backend, "undo")
    assert backend.build_state()["recipe"]["next"] == "inspect"


def test_inspect_receipt_invalidates_after_selection_or_unrelated_edit(backend):
    edit(backend, "primitive", {"kind": "box", "size": [20, 20, 20]})
    use(backend, "mesh-cleanup")
    edit(backend, "inspect")
    assert backend.build_state()["recipe"]["next"] == "process"
    edit(backend, "transform", {"translate_mm": [1, 0, 0]})
    assert backend.build_state()["recipe"]["next"] == "inspect"
    edit(backend, "inspect")
    edit(backend, "select", {"ids": []})
    assert backend.build_state()["recipe"]["next"] == "inspect"


def test_failed_edit_never_advances_progress(backend):
    edit(backend, "primitive", {"kind": "box", "size": [20, 20, 20]})
    use(backend, "mesh-lightweight")
    edit(backend, "inspect")
    body = {"action": "simplify", "params": {"ratio": -1}, "expected_revision": backend.editor.doc["revision"]}
    status, _ = backend.run_write("edit", lambda: backend.editor.execute(body), request_body=body)
    assert status == 400
    assert backend.build_state()["recipe"]["next"] == "process"


def test_state_polling_does_not_reload_catalog(backend, monkeypatch):
    use(backend, "mesh-cleanup")

    def fail(*args, **kwargs):
        raise AssertionError("state poll loaded catalog")

    monkeypatch.setattr(recipes, "load_recipes", fail)
    for _ in range(20):
        assert backend.build_state()["recipe"]["id"] == "mesh-cleanup"


def test_other_object_inspection_does_not_complete_current_selection(backend):
    edit(backend, "primitive", {"kind": "box", "size": [20, 20, 20]})
    other = backend.editor.doc["selection"][0]
    edit(backend, "primitive", {"kind": "sphere", "size": [20, 20, 20]})
    use(backend, "mesh-cleanup")
    edit(backend, "inspect", {"ids": [other]}, actor="ai")
    assert backend.build_state()["recipe"]["next"] == "inspect"


def test_stl_export_does_not_complete_glb_route(backend):
    edit(backend, "primitive", {"kind": "box", "size": [20, 20, 20]})
    use(backend, "mesh-material")
    edit(backend, "inspect")
    edit(backend, "material", {"color": "#0000ff"})
    edit(backend, "export", {"format": "stl"})
    assert backend.build_state()["recipe"]["next"] == "export"


def test_oversize_but_valid_mesh_can_progress_to_cutting(tmp_path):
    recipe = next(
        r for r in recipes.load_recipes(recipes.BUILTIN_RECIPES_DIR, tmp_path)["recipes"] if r["id"] == "cut-to-fit"
    )
    view = recipes.compute_recipe_view(
        recipe,
        readiness_items=[{"key": "model", "status": "warn"}],
        stale={},
        busy=None,
        print_data={"inspect": {"parts": [{"faces": 12, "watertight": True, "fits_bed": False}]}},
    )
    assert view["next"] == "plane_cut"


@pytest.mark.parametrize(
    "args",
    [
        {"action": "delete"},
        {"action": "simplify", "params": {"allow_material_loss": True}},
        {"action": "inspect", "expected_revision": 9},
    ],
)
def test_recipe_cannot_preset_sensitive_editor_decisions(tmp_path, args):
    source = recipes.BUILTIN_RECIPES_DIR / "mesh-cleanup"
    target = tmp_path / "mesh-cleanup"
    target.mkdir()
    data = json.loads((source / "recipe.json").read_text())
    data["steps"][1]["args"] = args
    (target / "recipe.json").write_text(json.dumps(data))
    (target / "guide.md").write_text("Guide")
    catalog = recipes.load_recipes(tmp_path, tmp_path / "empty")
    assert not catalog["recipes"] and len(catalog["problems"]) == 1
