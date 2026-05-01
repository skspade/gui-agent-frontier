"""Tests for build_site.aggregate_cells — pure data aggregation."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from build_site import aggregate_cells  # noqa: E402


CONFIG = {
    "models": [
        {"id": "ui-venus-1.5-8b"},
        {"id": "mai-ui-8b"},
    ],
    "tests": {
        "B": [{"id": "saucedemo_backpack_only"}],
        "D": [{"id": "ikea_billy"}],
    },
}


def test_pass_counts_via_category():
    runs = [
        {"task": "saucedemo_backpack_only", "model": "ui-venus-1.5-8b",
         "category": "pass", "outcome": "call_user", "ts": "2026-04-30T14:01"},
        {"task": "saucedemo_backpack_only", "model": "ui-venus-1.5-8b",
         "category": "stuck_loop", "outcome": "stuck_loop", "ts": "2026-04-30T14:02"},
        {"task": "saucedemo_backpack_only", "model": "ui-venus-1.5-8b",
         "category": "pass", "outcome": "done", "ts": "2026-04-30T14:03"},
    ]
    cells = aggregate_cells(runs, CONFIG)
    cell = cells[("ui-venus-1.5-8b", "saucedemo_backpack_only")]
    assert cell["k"] == 2
    assert cell["n"] == 3


def test_legacy_rows_without_category_use_outcome_fallback():
    runs = [
        {"task": "ikea_billy", "model": "mai-ui-8b",
         "outcome": "done", "ts": "2026-04-30T14:00"},
        {"task": "ikea_billy", "model": "mai-ui-8b",
         "outcome": "call_user", "ts": "2026-04-30T14:01"},
        {"task": "ikea_billy", "model": "mai-ui-8b",
         "outcome": "max_steps_reached", "ts": "2026-04-30T14:02"},
        {"task": "ikea_billy", "model": "mai-ui-8b",
         "outcome": "stuck_loop", "ts": "2026-04-30T14:03"},
    ]
    cells = aggregate_cells(runs, CONFIG)
    cell = cells[("mai-ui-8b", "ikea_billy")]
    assert cell["k"] == 2  # done + call_user
    assert cell["n"] == 4


def test_runs_outside_config_are_dropped():
    runs = [
        {"task": "saucedemo_backpack_only", "model": "unknown-model",
         "category": "pass", "outcome": "done", "ts": "2026-04-30T14:00"},
        {"task": "unknown_test", "model": "ui-venus-1.5-8b",
         "category": "pass", "outcome": "done", "ts": "2026-04-30T14:01"},
    ]
    cells = aggregate_cells(runs, CONFIG)
    assert cells == {}


def test_empty_runs_returns_empty_dict():
    assert aggregate_cells([], CONFIG) == {}


def test_runs_are_sorted_by_timestamp():
    runs = [
        {"task": "saucedemo_backpack_only", "model": "ui-venus-1.5-8b",
         "category": "pass", "outcome": "done", "ts": "2026-04-30T14:03"},
        {"task": "saucedemo_backpack_only", "model": "ui-venus-1.5-8b",
         "category": "pass", "outcome": "done", "ts": "2026-04-30T14:01"},
        {"task": "saucedemo_backpack_only", "model": "ui-venus-1.5-8b",
         "category": "pass", "outcome": "done", "ts": "2026-04-30T14:02"},
    ]
    cells = aggregate_cells(runs, CONFIG)
    cell = cells[("ui-venus-1.5-8b", "saucedemo_backpack_only")]
    timestamps = [r["ts"] for r in cell["runs"]]
    assert timestamps == sorted(timestamps)
