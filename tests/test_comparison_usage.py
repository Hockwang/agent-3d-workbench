import importlib.util
import json
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "report_usage", Path(__file__).parents[1] / "examples/assembly_comparison/report_usage.py"
)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def make_log(tmp_path, *, writes=0, terminal=True, malformed=False, missing=False):
    p = tmp_path / "private.jsonl"
    tokens = dict(
        input_tokens=1000,
        cached_input_tokens=800,
        cache_write_input_tokens=writes,
        output_tokens=200,
        reasoning_output_tokens=150,
        total_tokens=1200,
    )
    if missing:
        del tokens["cached_input_tokens"]
    rows = [
        {
            "type": "session_meta",
            "timestamp": "2026-09-29T00:00:00Z",
            "payload": {"id": "private-session", "cwd": "/private/path"},
        },
        {"type": "turn_context", "payload": {"model": "gpt-6-astra", "effort": "ultra"}},
        *[
            {"type": "event_msg", "payload": {"type": "token_count", "info": {"total_token_usage": tokens}}}
            for _ in range(3)
        ],
    ]
    if malformed:
        rows.append(None)
    if terminal:
        rows.append({"type": "event_msg", "timestamp": "2026-09-29T00:01:30Z", "payload": {"type": "task_complete"}})
    p.write_text("\n".join(json.dumps(r) if r is not None else "{" for r in rows))
    return p


def test_cumulative_and_subset_tokens_not_double_counted(tmp_path):
    r = m.parse_rollout(make_log(tmp_path))
    assert r["tokens"]["input_tokens"] == 1000
    assert r["wall_seconds"] == 90
    assert m.estimate(r)["usd"]["standard_short"] == pytest.approx(0.0128)


@pytest.mark.parametrize("kwargs", [{"terminal": False}, {"malformed": True}, {"missing": True}])
def test_incomplete_is_not_priced(tmp_path, kwargs):
    r = m.parse_rollout(make_log(tmp_path, **kwargs))
    assert r["usage_status"] == "incomplete"
    assert "usd" not in m.estimate(r)


def test_unknown_write_semantics_fail_closed(tmp_path):
    assert "usd" not in m.estimate(m.parse_rollout(make_log(tmp_path, writes=50)))


def test_public_export_excludes_all_private_fields(tmp_path):
    item = {
        "case": "fox-rig",
        "route": "rig-local",
        "result": "completed",
        "input_sha256": "a" * 64,
        "rollout": str(make_log(tmp_path)),
        "service_cost": 1234,
        "api_receipt": {"secret": "LEAK_MARKER"},
        "notes": "LEAK_MARKER",
        "internal_url": "http://private",
    }
    output = json.dumps(m.export({"runs": [item], "private_cost": "LEAK_MARKER"}))
    for value in ("LEAK_MARKER", "1234", "/private/path", "private-session", str(tmp_path), "http://private"):
        assert value not in output
    with pytest.raises(ValueError):
        m.export({"runs": [item, item]})


def test_counter_regression_cannot_be_a_bill(tmp_path):
    p = make_log(tmp_path, terminal=False)
    row = {
        "type": "event_msg",
        "payload": {
            "type": "token_count",
            "info": {
                "total_token_usage": dict(
                    input_tokens=1,
                    cached_input_tokens=0,
                    cache_write_input_tokens=0,
                    output_tokens=1,
                    reasoning_output_tokens=0,
                    total_tokens=2,
                )
            },
        },
    }
    with p.open("a") as f:
        f.write("\n" + json.dumps(row))
        f.write(
            "\n"
            + json.dumps(
                {"type": "event_msg", "timestamp": "2026-09-29T00:01:30Z", "payload": {"type": "task_complete"}}
            )
        )
    result = m.parse_rollout(p)
    assert result["counter_regression"]
    assert "usd" not in m.estimate(result)


def test_later_review_turn_does_not_change_frozen_experiment(tmp_path):
    p = make_log(tmp_path)
    expected = m.parse_rollout(p)
    with p.open("a") as f:
        for row in [
            {"type": "event_msg", "timestamp": "2026-09-29T01:00:00Z", "payload": {"type": "task_started"}},
            {"type": "turn_context", "payload": {"model": "different-model", "effort": "low"}},
            {
                "type": "event_msg",
                "payload": {"type": "token_count", "info": {"total_token_usage": {key: 99999 for key in m.TOKEN_KEYS}}},
            },
            {"type": "event_msg", "timestamp": "2026-09-29T02:00:00Z", "payload": {"type": "task_complete"}},
        ]:
            f.write("\n" + json.dumps(row))
    assert m.parse_rollout(p) == expected
