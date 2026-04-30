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
