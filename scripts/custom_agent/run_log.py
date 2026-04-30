"""JSONL run logger for harness baseline + ablation runs.

One row per (task, model, run) for offline analysis. Schema is flat-and-cheap;
add fields freely as new probes come online.
"""
from __future__ import annotations
import json
from datetime import datetime
from pathlib import Path

DEFAULT_LOG = Path("/home/seans/Source/vision-model/data/runs.jsonl")


def append_run(path: Path, row: dict) -> None:
    """Append one JSON object as a single line. Creates parent dirs."""
    path.parent.mkdir(parents=True, exist_ok=True)
    row.setdefault("ts", datetime.now().isoformat(timespec="seconds"))
    with path.open("a") as f:
        f.write(json.dumps(row) + "\n")


_OUTCOME_MAP = {
    "done": "pass",
    "call_user": "pass",
    "stuck_loop": "stuck_loop",
    "stuck_premature_done": "premature_done",
    "parse_error": "parse_error",
    "model_error": "model_error",
    "unhandled_action": "unhandled_action",
    "max_steps_reached": "exhausted",
    "dispatch_hang": "dispatch_hang",
}


def classify_failure(*, outcome: str, steps: int = 0, history_summary: str = "") -> str:
    return _OUTCOME_MAP.get(outcome, f"unknown:{outcome}")
