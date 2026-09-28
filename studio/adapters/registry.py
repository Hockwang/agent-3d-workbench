"""Registry mapping each `services.json` `adapter` id to the object that speaks
that hosted service's wire protocol (payload shaping, submission, polling, and
optionally a UI catalog or a read-only connection probe).

Provider modules (`lux3d_service.py`, `hunyuan_service.py`, `seed3d_service.py`,
`assembly_service.py`, `meshy.py`, `tripo.py`) register an instance of their own
adapter here on import. `studio.adapters.services` then dispatches every request
through `adapter_for(spec)` instead of branching on the adapter string itself.
This module knows nothing about any specific provider.
"""

from __future__ import annotations
from typing import Protocol, runtime_checkable

from studio.core.editor import EditorError


@runtime_checkable
class ServiceAdapter(Protocol):
    """What `studio.adapters.services` needs from a hosted-service adapter.

    Every adapter is expected to implement all five methods (subclassing
    `BaseAdapter` below gives sensible no-op defaults for the ones a given
    provider does not need), so the dispatcher can call them unconditionally
    instead of checking adapter-specific capability flags.
    """

    def operation_catalog(self, spec: dict, item: dict, *, internal_http: bool) -> dict:
        """Extra fields to merge into a `services.catalog()` entry (operation
        templates, timeout, setup message, ...), or `{}` for adapters with no
        dedicated UI catalog (Meshy, Tripo, and any unregistered/custom adapter
        id)."""
        ...

    def prepare_payload(self, spec: dict, operation: str, payload: dict) -> dict:
        """Validate/normalize task params before a task is queued (before any
        file upload happens — `workbench["inputs"]` is not available yet)."""
        ...

    def run(self, workbench: dict) -> None:
        """Execute a queued task end to end: submit once, poll, download
        artifacts, and write `service.json`. Owns its own resume/ledger state
        via the task's `service-receipt.json`."""
        ...

    def probe(self, spec: dict) -> dict:
        """Read-only connection test for the 3D services settings UI. Returns
        the provider-specific fields to merge into `{"ok": True, "id": name}`."""
        ...

    def on_save(self, spec: dict, template_spec: dict, old: dict) -> None:
        """Extra validation when a connection profile is saved
        (`service_connections.save()`). `template_spec` is the fresh, un-merged
        `BUILTINS[template]` entry for the template just selected (`spec` itself
        already has `old`'s fields merged in, so a field the two share cannot be
        told apart there). Raise `EditorError` to reject the save."""
        ...


class BaseAdapter:
    """Default, no-op implementation of every `ServiceAdapter` hook. Provider
    adapters subclass this and override only what actually differs for them."""

    def operation_catalog(self, spec, item, *, internal_http):
        return {}

    def prepare_payload(self, spec, operation, payload):
        return dict(payload)

    def run(self, workbench):
        raise NotImplementedError

    def probe(self, spec):
        raise EditorError.coded("registry.no_probe_available")

    def on_save(self, spec, template_spec, old):
        pass


ADAPTERS: dict[str, ServiceAdapter] = {}


def register(adapter_id):
    """Class/instance decorator: `@register("lux3d")` on the module's adapter
    instance registers it under that `services.json` `adapter` id."""

    def decorator(adapter):
        ADAPTERS[adapter_id] = adapter
        return adapter

    return decorator


def adapter_for(spec):
    """Resolve a spec's registered adapter, falling back to the generic REST-job
    adapter (see `services.run_generic_job`) for any `adapter` id with no
    dedicated module — this preserves `services.json`'s existing support for
    pointing at an arbitrary provider-agnostic REST API."""
    adapter_id = spec.get("adapter", "generic")
    adapter = ADAPTERS.get(adapter_id) or ADAPTERS.get("generic")
    if adapter is None:
        raise EditorError.coded("registry.unknown_adapter", adapter_id=adapter_id)
    return adapter
