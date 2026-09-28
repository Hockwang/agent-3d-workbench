"""Billing-adjacent extras for the optional, key-gated Lux3D adapter: read-only
account/quote/history plus local quote-to-request binding.

Quotes do not authorize payment. Explicit generation starts the work. A quote
shown by the UI is bound to the regional account, exact parameters and input
hashes, so editing a form cannot silently spend against an earlier estimate.
"""

import hashlib
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

from studio.core.editor import EditorError, _atomic
from studio.adapters.lux3d_service import ROUTES, get_task, input_payload, prepare_payload, request


def expiry(value):
    try:
        d = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if d.tzinfo is None:
            raise ValueError()
        return d.timestamp()
    except (ValueError, TypeError, AttributeError):
        raise EditorError.coded("lux3d_commerce.timestamp_invalid") from None


def credits(value):
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise EditorError.coded("lux3d_commerce.credits_invalid")
    return value


def balance(spec):
    d = request(spec, "GET", "/lux3d/v1/account/balance?source=1")
    fields = (
        "availableCredits",
        "trialCountMap",
        "member",
        "memberType",
        "snapshotAt",
        "uniqueId",
        "uniqueIdExpiresAt",
    )
    if not isinstance(d, dict) or not all(k in d for k in fields):
        raise EditorError.coded("lux3d_commerce.account_response_incomplete")
    result = {k: d[k] for k in fields}
    credits(result["availableCredits"])
    if not isinstance(d["uniqueId"], str) or not re.fullmatch(r"ctx_[0-9a-f]{32}", d["uniqueId"]):
        raise EditorError.coded("lux3d_commerce.account_context_invalid")
    if type(d["member"]) is not bool or type(d["memberType"]) is not int:
        raise EditorError.coded("lux3d_commerce.member_status_invalid")
    if d["trialCountMap"] is not None:
        if not isinstance(d["trialCountMap"], dict):
            raise EditorError.coded("lux3d_commerce.trial_credits_invalid")
        for v in d["trialCountMap"].values():
            credits(v)
    if expiry(d["uniqueIdExpiresAt"]) <= max(datetime.now(timezone.utc).timestamp(), expiry(d["snapshotAt"])):
        raise EditorError.coded("lux3d_commerce.account_context_expired")
    return result


def fingerprint(spec, operation, payload, inputs):
    from studio.adapters.service_connections import credential

    files = []
    for name in inputs:
        path = Path(name).expanduser()
        if not path.is_absolute() or not path.is_file():
            raise EditorError.coded("lux3d_commerce.quote_input_must_be_local_file")
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        files.append(digest)
    raw = {
        "base_url": spec["base_url"],
        "region": spec["region"],
        "operation": operation,
        "payload": prepare_payload(
            operation, {k: v for k, v in payload.items() if k not in ("quote_id", "quote_item")}
        ),
        "inputs": files,
        "account": hashlib.sha256(credential(spec).encode()).hexdigest(),
    }
    return hashlib.sha256(json.dumps(raw, sort_keys=True, allow_nan=False).encode()).hexdigest()


def quote_path(quote_id):
    from studio.adapters.service_connections import store_path

    if not isinstance(quote_id, str) or not re.fullmatch(r"quote_[0-9a-f]{32}", quote_id):
        raise EditorError.coded("lux3d_commerce.quote_id_invalid")
    root = store_path().parent / "lux3d-quotes"
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    return root / (quote_id + ".json")


def quote(spec, operation, payload, inputs):
    return quote_plan(spec, [{"operation": operation, "params": payload, "inputs": inputs}])


def quote_plan(spec, items):
    if not isinstance(items, list) or not 1 <= len(items) <= 50:
        raise EditorError.coded("lux3d_commerce.plan_size_range")
    records = {}
    requests = {}
    for index, item in enumerate(items, 1):
        if not isinstance(item, dict) or set(item) - {"operation", "params", "inputs"}:
            raise EditorError.coded("lux3d_commerce.quote_item_fields_required")
        operation = item.get("operation")
        payload = item.get("params", {})
        inputs = item.get("inputs", [])
        signature = fingerprint(spec, operation, payload, inputs)
        normalized = input_payload(spec, operation, payload, inputs)
        normalized.pop("quote_id", None)
        normalized.pop("quote_item", None)
        if "remote_task_id" in normalized:
            raise EditorError.coded("lux3d_commerce.resume_task_no_requote")
        sequence = str(index)
        records[sequence] = {"fingerprint": signature, "payload": normalized, "operation": operation}
        requests[sequence] = {
            "endpoint": {"method": "POST", "path": ROUTES[operation]},
            "parameters": {"body": json.dumps(normalized, ensure_ascii=False)},
        }
    account = balance(spec)
    body = {"source": 1, "uniqueId": account["uniqueId"], "items": requests}
    d = request(spec, "POST", "/lux3d/v1/pricing/openapi-quotes", body)
    fields = (
        "source",
        "uniqueId",
        "quoteId",
        "pricingScope",
        "estimatedCreditsTotal",
        "details",
        "quotedAt",
        "expiresAt",
    )
    if not isinstance(d, dict) or not all(k in d for k in fields):
        raise EditorError.coded("lux3d_commerce.quote_response_incomplete")
    if (
        type(d["source"]) is not int
        or d["source"] != 1
        or d["uniqueId"] != account["uniqueId"]
        or d["pricingScope"] != "BEFORE_ACCOUNT_BENEFITS"
    ):
        raise EditorError.coded("lux3d_commerce.quote_account_mismatch")
    if (
        not isinstance(d["details"], dict)
        or set(d["details"]) != set(records)
        or not math.isclose(
            sum(credits(v) for v in d["details"].values()), credits(d["estimatedCreditsTotal"]), abs_tol=1e-8
        )
    ):
        raise EditorError.coded("lux3d_commerce.quote_totals_mismatch")
    if expiry(d["expiresAt"]) <= max(datetime.now(timezone.utc).timestamp(), expiry(d["quotedAt"])):
        raise EditorError.coded("lux3d_commerce.quote_expired")
    q = {k: d[k] for k in fields}
    path = quote_path(q["quoteId"])
    _atomic(
        path,
        json.dumps(
            {"items": records, "quote": q, "account_expires": account["uniqueIdExpiresAt"]}, ensure_ascii=False
        ).encode(),
    )
    path.chmod(0o600)
    return {
        "ok": True,
        "account": account,
        "quote": q,
        "quote_id": q["quoteId"],
        "items": {
            k: {"operation": v["operation"], "quote_item": k, "estimated_credits": d["details"][k]}
            for k, v in records.items()
        },
        "generation_started": False,
    }


def quoted_payload(spec, operation, payload, inputs):
    path = quote_path(payload.get("quote_id"))
    if not path.exists():
        raise EditorError.coded("lux3d_commerce.quote_not_found")
    record = json.loads(path.read_text())
    selected = record.get("items", {"1": record}).get(payload.get("quote_item", "1"))
    if not selected or selected["fingerprint"] != fingerprint(spec, operation, payload, inputs):
        raise EditorError.coded("lux3d_commerce.quote_stale")
    now = datetime.now(timezone.utc).timestamp()
    if min(expiry(record["quote"]["expiresAt"]), expiry(record["account_expires"])) <= now:
        raise EditorError.coded("lux3d_commerce.quote_expired_refetch")
    return selected["payload"]


def execute(body):
    from studio.adapters.services import config, catalog

    spec = config().get(body.get("id"))
    if not spec or spec.get("adapter") != "lux3d":
        raise EditorError.coded("lux3d_commerce.connection_required")
    if not next(x for x in catalog() if x["id"] == body["id"])["configured"]:
        raise EditorError.coded("lux3d_commerce.key_not_configured")
    action = body["action"]
    if action == "balance":
        return {"ok": True, "account": balance(spec), "generation_started": False}
    if action == "quote":
        if "items" in body:
            if any(k in body for k in ("operation", "params", "inputs")):
                raise EditorError.coded("lux3d_commerce.items_and_single_operation_conflict")
            return quote_plan(spec, body["items"])
        return quote(spec, body.get("operation"), body.get("params", {}), body.get("inputs", []))
    if action == "remote_task":
        d = get_task(spec, body.get("remote_task_id"))
        return {
            "ok": True,
            "task": {k: str(d[k]) if k == "taskId" else d.get(k) for k in ("taskId", "status", "bizId")},
            "generation_started": False,
        }
    if action == "remote_tasks":
        page = body.get("page", 1)
        if type(page) is not int or page < 1:
            raise EditorError.coded("lux3d_commerce.page_must_be_positive_int")
        query = {"page": page, "pagesize": body.get("pagesize", 20)}
        if type(query["pagesize"]) is not int or not 1 <= query["pagesize"] <= 100:
            raise EditorError.coded("lux3d_commerce.pagesize_range")
        for field in ("status", "starttime", "endtime"):
            if field in body:
                value = body[field]
                if type(value) is not int or value < 0 or (field == "status" and value not in (0, 1, 3, 4, 6)):
                    raise EditorError.coded("lux3d_commerce.task_query_invalid")
                query[field] = value
        if "starttime" in query and "endtime" in query and query["starttime"] >= query["endtime"]:
            raise EditorError.coded("lux3d_commerce.task_query_time_range_invalid")
        d = request(spec, "GET", "/lux3d/v1/generate/task/list?" + urlencode(query))

        # History need not expose prompts, source images or signed output URLs.
        def clean(v):
            if isinstance(v, list):
                return [clean(x) for x in v]
            if isinstance(v, dict):
                return {
                    k: str(x) if k == "taskId" else clean(x)
                    for k, x in v.items()
                    if k
                    in (
                        "taskId",
                        "status",
                        "bizId",
                        "createTime",
                        "createdAt",
                        "total",
                        "page",
                        "pagesize",
                        "list",
                        "items",
                        "records",
                        "data",
                        "tasks",
                    )
                }
            return v

        return {"ok": True, "history": clean(d), "generation_started": False}
    raise EditorError.coded("lux3d_commerce.unknown_action")
