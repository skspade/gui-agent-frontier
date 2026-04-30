import json
from pathlib import Path
from scripts.custom_agent.run_log import append_run


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
