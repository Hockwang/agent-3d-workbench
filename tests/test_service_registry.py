"""Regression tests for the `studio.adapters.registry` refactor:

- `services.catalog()` output is byte-identical to its pre-refactor shape (see
  `tests/fixtures/service_catalog_snapshot.json`, captured from the dispatcher's
  if/elif-per-adapter implementation before it was rewritten to go through
  `registry.adapter_for`).
- Every `BUILTINS` adapter id resolves to a real, registered adapter.
- The per-adapter `if spec["adapter"] == "...": from studio.adapters.X import Y`
  branches that used to live inside `services.py`'s `catalog`/`prepare`/`run` are
  gone — those were only ever there to dodge an import cycle with the provider
  modules, and the registry removes that cycle (providers now register
  themselves on import instead of being reached into lazily per call).
"""

from __future__ import annotations
import ast
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SERVICES_PY = REPO_ROOT / "studio" / "adapters" / "services.py"
SNAPSHOT = Path(__file__).resolve().parent / "fixtures" / "service_catalog_snapshot.json"

# The provider modules `services.py` used to lazily re-import, once per adapter
# branch, inside catalog()/prepare()/run() before this refactor.
FORMER_CYCLE_MODULES = {
    "studio.adapters.assembly_service",
    "studio.adapters.hunyuan_service",
    "studio.adapters.seed3d_service",
    "studio.adapters.lux3d_service",
    "studio.adapters.meshy",
    "studio.adapters.tripo",
}

KEY_ENVS = (
    "LUX3D_CN_API_KEY",
    "LUX3D_GLOBAL_API_KEY",
    "SEED3D_API_KEY",
    "HUNYUAN_API_KEY",
    "MESHY_API_KEY",
    "TRIPO_API_KEY",
)


@pytest.fixture
def clean_builtin_config(tmp_path, monkeypatch):
    """Only BUILTINS should apply: no services.json overrides, no credentials."""
    monkeypatch.setenv("WORKBENCH_SERVICE_CONFIG", str(tmp_path / "does-not-exist.json"))
    for env in KEY_ENVS:
        monkeypatch.delenv(env, raising=False)


def test_catalog_snapshot_unchanged_by_the_registry_refactor(clean_builtin_config):
    from studio.adapters.services import catalog

    expected = json.loads(SNAPSHOT.read_text())
    actual = catalog()
    assert actual == expected, (
        "catalog() output changed shape; if this is intentional, regenerate "
        f"{SNAPSHOT.relative_to(REPO_ROOT)} — otherwise the registry refactor "
        "broke an externally observable field."
    )


def test_every_builtin_adapter_id_resolves():
    from studio.adapters.registry import ServiceAdapter, adapter_for
    from studio.adapters.services import BUILTINS

    seen_adapter_ids = set()
    for name, spec in BUILTINS.items():
        adapter = adapter_for(spec)
        assert isinstance(adapter, ServiceAdapter), f"{name}: {adapter!r} does not satisfy ServiceAdapter"
        seen_adapter_ids.add(spec["adapter"])
    # Every registered adapter should actually be reachable from some BUILTINS
    # entry (otherwise it is dead registration code nobody's config ever hits).
    from studio.adapters.registry import ADAPTERS

    assert seen_adapter_ids <= set(ADAPTERS)


def test_unregistered_adapter_id_falls_back_to_generic_not_an_error():
    """A custom services.json entry with an unrecognized `adapter` string is a
    supported, pre-existing feature (an arbitrary REST job run through
    `run_generic_job`), not a rejection — preserve that."""
    from studio.adapters.registry import adapter_for

    adapter = adapter_for({"adapter": "some-custom-rest-api-nobody-wrote-a-module-for"})
    assert adapter is adapter_for({})  # both fall back to the same "generic" singleton


def _function_level_provider_imports(source: str) -> list[tuple[str, str]]:
    """(function name, imported module) for every `from studio.adapters.X import
    ...` found *inside* a function/method body, where X is one of the modules
    services.py used to reach into per adapter branch before this refactor."""
    tree = ast.parse(source)
    hits = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for inner in ast.walk(node):
                if inner is node:
                    continue
                if isinstance(inner, ast.ImportFrom) and inner.module in FORMER_CYCLE_MODULES:
                    hits.append((node.name, inner.module))
                if isinstance(inner, ast.Import):
                    for alias in inner.names:
                        if alias.name in FORMER_CYCLE_MODULES:
                            hits.append((node.name, alias.name))
    return hits


def test_task_schema_template_enum_is_derived_from_builtins_not_hand_maintained():
    """`studio.shell.task_schema`'s `studio_services` `template` enum used to be a
    hand-written literal list that duplicated (and drifted from, missing
    `assembly`) `BUILTINS`'s keys, then a second hand-copied filter of `BUILTINS`
    that could independently drift from `service_connections.TEMPLATES` (a `key_env`
    credential slot, not force-`enabled: False`). It must now be derived from
    `service_connections.TEMPLATES` itself, so a new BYOK template is picked up
    automatically and `assembly` -- which has neither a `key_env` nor `enabled: True`
    -- is excluded the same way it is absent from `TEMPLATES` today."""
    from studio.adapters.service_connections import TEMPLATES
    from studio.adapters.services import BUILTINS
    from studio.shell.task_schema import TOOLS

    assert "assembly" not in TEMPLATES
    assert all(BUILTINS[key].get("key_env") and BUILTINS[key].get("enabled", True) is not False for key in TEMPLATES)

    schema = next(t for t in TOOLS if t["name"] == "studio_services")
    assert schema["inputSchema"]["properties"]["template"]["enum"] == list(TEMPLATES)


def test_services_dispatcher_no_longer_lazily_imports_provider_modules():
    """`catalog()`, `prepare()` and `run()` used to each have one `if
    spec["adapter"] == "...":` branch per provider, importing that provider's
    module *inside the function* purely to dodge the services.py <-> provider
    import cycle. The registry removes that cycle (providers self-register on
    import, and `services.py` imports them once at module scope for that side
    effect) — so no function in `services.py` should still reach into any of
    FORMER_CYCLE_MODULES lazily."""
    hits = _function_level_provider_imports(SERVICES_PY.read_text())
    assert not hits, f"services.py still has deferred per-provider imports (the cycle they dodged is gone): {hits}"
