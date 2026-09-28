"""Meshy's public REST API (text/image-to-3D, retexture, remesh, rigging).

Meshy has no dedicated task-params validator or settings-UI catalog of its own
(BaseAdapter's no-op defaults apply); it only needs the payload shaped right
before submission and the result envelope parsed on completion, both plugged
into `services.run_generic_job`'s shared submit/poll/download loop. Registers
itself as the `meshy` adapter.
"""

from studio.adapters.registry import BaseAdapter, register
from studio.adapters.transport import files, request

from studio.core.editor import EditorError
from studio.i18n import render

OPERATIONS = {
    "text-to-3d": "/openapi/v2/text-to-3d",
    **{
        x: "/openapi/v1/" + x
        for x in ("image-to-3d", "multi-image-to-3d", "retexture", "remesh", "rigging", "animations")
    },
}


def _build_payload(spec, operation, payload, inputs):
    if operation == "text-to-3d":
        payload.setdefault("mode", "preview")
    if inputs and operation == "image-to-3d":
        payload.setdefault("image_url", {"$file": inputs[0]})
    if inputs and operation == "multi-image-to-3d":
        payload.setdefault("image_urls", [{"$file": p} for p in inputs])
    if inputs and operation in ("rigging", "remesh", "retexture"):
        payload.setdefault("model_url", {"$file": inputs[0]})
    return files(payload)


def _extract_urls(spec, operation, route, result):
    urls = {
        key: value
        for key, value in (result.get("model_urls") or {}).items()
        if key in ("glb", "fbx", "stl", "3mf") and value
    }
    if result.get("rigged_character_glb_url"):
        urls["glb"] = result["rigged_character_glb_url"]
    for key in ("animation_glb_url", "glb_url"):
        if result.get(key):
            urls["glb"] = result[key]
    # Animation API stores generated animations under result.
    animated = result.get("result") or {}
    for key, value in animated.items() if isinstance(animated, dict) else []:
        if isinstance(value, str) and ("glb" in key or "fbx" in key):
            urls[key] = value
    if result.get("thumbnail_url"):
        urls["preview.png"] = result["thumbnail_url"]
    return urls


class _MeshyAdapter(BaseAdapter):
    def run(self, workbench):
        # Deferred: services.py needs OPERATIONS (above) before it can define
        # run_generic_job, so this cannot be a module-level import (see
        # services.py's own registration-order comment).
        from studio.adapters import services

        services.run_generic_job(workbench, build_payload=_build_payload, extract_urls=_extract_urls)

    def probe(self, spec):
        result = request(spec, "GET", "/openapi/v1/balance", timeout=20)
        if type(result.get("balance")) not in (int, float):
            raise EditorError.coded("meshy.balance_invalid")
        return {"models": [], "message": render("meshy.probe_ok"), "generation_tested": False}


register("meshy")(_MeshyAdapter())
