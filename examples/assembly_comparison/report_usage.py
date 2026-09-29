"""Export an allowlisted usage report; never export prompts, paths or service costs.

Input: private JSON {"runs": [{"case": ..., "route": ..., "rollout": ...,
"input_sha256": ..., "result": "completed|failed|timeout|incomplete"}]}.
Run with --manifest outside-the-repo.json --output public-report.json.
The price is an API-equivalent scenario estimate, not a Codex subscription bill.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import re

TOKEN_KEYS = (
    "input_tokens",
    "cached_input_tokens",
    "cache_write_input_tokens",
    "output_tokens",
    "reasoning_output_tokens",
    "total_tokens",
)
MODELS = {"gpt-6-astra"}
CASES = {"fox-rig", "drawers-rigid", "fan-segment"}
ROUTES = {"rig-local", "rig-api", "rigid-local", "rigid-api", "segment-local", "segment-p3", "segment-cube"}
RESULTS = {"completed", "failed", "timeout", "incomplete"}
PRICING = {
    "source": "https://developers.openai.com/api/docs/pricing",
    "checked_on": "2026-09-29",
    "model": "gpt-6-astra",
    "currency": "USD",
    "unit": "per_million_tokens",
    "standard_short": {"input": 10, "cached_input": 1, "cache_write": 12.5, "output": 50},
    "standard_long": {"input": 20, "cached_input": 2, "cache_write": 25, "output": 75},
    "note": "Scenario estimates only. Not actual subscription billing. Excludes service API charges and infrastructure.",
}


def number(value):
    return value if type(value) is int and value >= 0 else None


def timestamp(value):
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except (AttributeError, TypeError, ValueError):
        return None


def parse_rollout(path: Path):
    """Read the first task's cumulative counters, ending at its terminal event.

    Use a fresh session per experiment. Later review/documentation turns in a
    reused session must not change the frozen experiment's token or time totals.
    """
    usage = {k: None for k in TOKEN_KEYS}
    models, efforts = set(), set()
    started = ended = None
    malformed = regression = False
    max_request_input = None
    snapshots = 0
    for line in path.open(encoding="utf-8"):
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            malformed = True
            continue
        data = row.get("payload", {})
        if not isinstance(data, dict):
            continue
        at = timestamp(row.get("timestamp"))
        if row.get("type") == "session_meta" and started is None:
            started = timestamp(data.get("timestamp")) or at
        if row.get("type") == "turn_context":
            models.add(data.get("model"))
            efforts.add(data.get("effort"))
        if row.get("type") != "event_msg":
            continue
        if data.get("type") == "task_started":
            started = started if started is not None else at
            ended = None
        if data.get("type") in {"task_complete", "task_aborted", "turn_aborted"}:
            ended = at
            break
        if data.get("type") != "token_count":
            continue
        info = data.get("info") or {}
        total = info.get("total_token_usage")
        if not isinstance(total, dict):
            continue
        current = {k: number(total.get(k)) for k in TOKEN_KEYS}
        for k in TOKEN_KEYS:
            if usage[k] is not None and current[k] is not None and current[k] < usage[k]:
                regression = True
        usage = current
        snapshots += 1
        last = number((info.get("last_token_usage") or {}).get("input_tokens"))
        if last is not None:
            max_request_input = max(max_request_input or 0, last)
    known = all(usage[k] is not None for k in TOKEN_KEYS)
    consistent = (
        known
        and usage["cached_input_tokens"] <= usage["input_tokens"]
        and usage["reasoning_output_tokens"] <= usage["output_tokens"]
        and usage["total_tokens"] == usage["input_tokens"] + usage["output_tokens"]
    )
    status = "complete" if consistent and ended is not None and not malformed and not regression else "incomplete"
    return {
        "model": next(iter(models)) if len(models) == 1 and models <= MODELS else "unverified_or_mixed",
        "reasoning_effort": next(iter(efforts))
        if len(efforts) == 1 and efforts <= {"low", "medium", "high", "xhigh", "max", "ultra"}
        else "unverified_or_mixed",
        "usage_status": status,
        "tokens": usage,
        "max_observed_request_input_tokens": max_request_input,
        "wall_seconds": round(ended - started, 3)
        if started is not None and ended is not None and ended >= started
        else None,
        "counter_snapshots": snapshots,
        "malformed_log": malformed,
        "counter_regression": regression,
        "measurement_scope": "session_start_through_first_task_terminal",
    }


def estimate(report):
    u = report["tokens"]
    if report["model"] != "gpt-6-astra" or report["usage_status"] != "complete":
        return {"status": "unavailable_incomplete_or_mixed_usage"}
    # Codex logs currently report zero writes in this batch. Until their write
    # inclusion semantics are documented, do not guess for nonzero/missing writes.
    if u["cache_write_input_tokens"] != 0:
        return {"status": "unavailable_cache_write_semantics"}
    costs = {}
    for scenario in ("standard_short", "standard_long"):
        rates = PRICING[scenario]
        costs[scenario] = round(
            (
                (u["input_tokens"] - u["cached_input_tokens"]) * rates["input"]
                + u["cached_input_tokens"] * rates["cached_input"]
                + u["output_tokens"] * rates["output"]
            )
            / 1_000_000,
            6,
        )
    return {"status": "scenario_estimate_not_invoice", "usd": costs}


def export(manifest):
    rows, seen_routes = [], set()
    for item in manifest["runs"]:
        case, route, result = item["case"], item["route"], item["result"]
        if case not in CASES or route not in ROUTES or result not in RESULTS or route in seen_routes:
            raise ValueError("Unknown or duplicate comparison row")
        seen_routes.add(route)
        sha = item["input_sha256"]
        if not isinstance(sha, str) or not re.fullmatch(r"[a-f0-9]{64}", sha):
            raise ValueError("Invalid input hash")
        report = parse_rollout(Path(item["rollout"]))
        # Deliberately do not copy arbitrary manifest keys or nested API receipts.
        rows.append(
            {
                "case": case,
                "route": route,
                "result": result,
                "input_sha256": sha,
                **report,
                "api_equivalent_price": estimate(report),
            }
        )
    return {"schema": "assembly-comparison-usage/v1", "pricing": PRICING, "runs": rows}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--manifest", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    report = export(json.loads(args.manifest.read_text()))
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
