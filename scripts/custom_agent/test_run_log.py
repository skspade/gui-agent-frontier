import json
from pathlib import Path
from PIL import Image
from scripts.custom_agent.run_log import (
    append_run,
    classify_failure,
    count_non_white_in_region,
)


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


def _make_png(tmp_path: Path, name: str, w: int, h: int, draw_box=None):
    """Make a w×h PNG with a white background; optionally draw a black box at
    `draw_box = (x0, y0, x1, y1)` in pixel coords to simulate a drawn rectangle."""
    img = Image.new("RGB", (w, h), (255, 255, 255))
    if draw_box is not None:
        from PIL import ImageDraw
        ImageDraw.Draw(img).rectangle(draw_box, outline=(0, 0, 0), width=3)
    p = tmp_path / name
    img.save(p)
    return p


def test_count_non_white_empty_canvas_in_canvas_core(tmp_path):
    # 1248x615 all-white canvas — qwen-72B premature_done baseline
    p = _make_png(tmp_path, "empty.png", 1248, 615)
    assert count_non_white_in_region(p, (0.30, 0.30, 0.70, 0.70)) == 0


def test_count_non_white_drawn_rectangle_in_canvas_core(tmp_path):
    # Rectangle drawn squarely inside the canvas-core region — UV-8B genuine pass
    p = _make_png(tmp_path, "drawn.png", 1248, 615, draw_box=(500, 250, 750, 400))
    assert count_non_white_in_region(p, (0.30, 0.30, 0.70, 0.70)) > 150


def test_count_non_white_rectangle_outside_region_does_not_count(tmp_path):
    # Rectangle drawn in the toolbar area (top of image), NOT in canvas-core
    p = _make_png(tmp_path, "toolbar.png", 1248, 615, draw_box=(50, 30, 200, 80))
    assert count_non_white_in_region(p, (0.30, 0.30, 0.70, 0.70)) == 0
