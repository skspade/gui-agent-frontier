"""Build the findings webapp into web/.

Reads:
  data/runs.jsonl                 — per-run records (source of truth for k/n).
  data/sweeps/*/summary.json      — sweep results with per-run screenshot paths.
  web/config.yaml                 — curated row/column ordering and labels.

Writes:
  web/index.html                  — self-contained page with inlined data.
  web/screenshots/<model>/<task>/<n>.png — copied from referenced paths.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


PASS_OUTCOMES_FALLBACK = {"done", "call_user"}


def _is_pass(run: dict[str, Any]) -> bool:
    if "category" in run and run["category"] is not None:
        return run["category"] == "pass"
    return run.get("outcome") in PASS_OUTCOMES_FALLBACK


def aggregate_cells(
    runs: list[dict[str, Any]], config: dict[str, Any]
) -> dict[tuple[str, str], dict[str, Any]]:
    """Aggregate runs into per-(model, test) cells.

    Cells with zero matching runs are omitted; renderers treat absence
    as "not run".
    """
    model_ids = {m["id"] for m in config["models"]}
    test_ids = {t["id"] for tests in config["tests"].values() for t in tests}

    cells: dict[tuple[str, str], dict[str, Any]] = {}
    for run in runs:
        model, task = run.get("model"), run.get("task")
        if model not in model_ids or task not in test_ids:
            continue
        cell = cells.setdefault((model, task), {"k": 0, "n": 0, "runs": []})
        cell["n"] += 1
        if _is_pass(run):
            cell["k"] += 1
        cell["runs"].append(run)

    for cell in cells.values():
        cell["runs"].sort(key=lambda r: r.get("ts", ""))
    return cells
