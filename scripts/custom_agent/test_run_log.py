import json
from pathlib import Path
from scripts.custom_agent.run_log import append_run, classify_failure


def test_append_run_writes_one_jsonl_row(tmp_path):
    log = tmp_path / "runs.jsonl"
    append_run(log, {
        "task": "ikea_billy",
        "model": "ui-venus-1.5-8b",
        "outcome": "done",
        "steps": 12,
        "elapsed_s": 88.4,
        "stuck_loop": False,
        "parse_error": False,
        "final_screenshot": "/tmp/custom_agent_final.png",
        "ts": "2026-04-30T19:00:00",
    })
    rows = [json.loads(l) for l in log.read_text().splitlines()]
    assert len(rows) == 1
    assert rows[0]["task"] == "ikea_billy"
    assert rows[0]["model"] == "ui-venus-1.5-8b"
    assert rows[0]["outcome"] == "done"


def test_append_run_appends_not_overwrites(tmp_path):
    log = tmp_path / "runs.jsonl"
    append_run(log, {"task": "a", "model": "m", "outcome": "done", "steps": 1, "elapsed_s": 1.0})
    append_run(log, {"task": "b", "model": "m", "outcome": "stuck_loop", "steps": 5, "elapsed_s": 5.0})
    rows = log.read_text().splitlines()
    assert len(rows) == 2


def test_classify_done_is_pass():
    assert classify_failure(outcome="done", steps=12, history_summary="...") == "pass"

def test_classify_call_user_is_pass():
    # call_user is the model's "report final answer" verb (e.g. PASS/FAIL message);
    # the run loop treats it like done, so the classifier must too.
    assert classify_failure(outcome="call_user", steps=8) == "pass"

def test_classify_stuck_loop():
    assert classify_failure(outcome="stuck_loop", steps=5) == "stuck_loop"

def test_classify_parse_error():
    assert classify_failure(outcome="parse_error", steps=3) == "parse_error"

def test_classify_max_steps():
    assert classify_failure(outcome="max_steps_reached", steps=40) == "exhausted"

def test_classify_premature_done():
    assert classify_failure(outcome="stuck_premature_done", steps=15) == "premature_done"

def test_classify_dispatch_hang():
    # Set when wall-clock per-step exceeds N×median (Phase 0.4 will tune N)
    assert classify_failure(outcome="dispatch_hang", steps=4) == "dispatch_hang"

def test_classify_unknown_outcome_is_namespaced():
    assert classify_failure(outcome="weird_new_thing", steps=1) == "unknown:weird_new_thing"
