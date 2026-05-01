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


def build_sweep_index(
    sweeps_dir: Path,
) -> dict[tuple[str, str], list[tuple[str, str]]]:
    """Return {(model, task): [(timestamp, abs_screenshot_path), ...]}."""
    index: dict[tuple[str, str], list[tuple[str, str]]] = {}
    for summary_path in Path(sweeps_dir).glob("*/summary.json"):
        try:
            summary = json.loads(summary_path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        task = summary.get("task")
        if not task:
            continue
        sweep_ts = summary_path.parent.name  # e.g. "20260501-011611"
        for result in summary.get("results", []):
            model = result.get("model")
            shot = result.get("screenshot_path")
            if not model or not shot:
                continue
            index.setdefault((model, task), []).append((sweep_ts, shot))
    return index


def resolve_screenshots(
    cell: dict[str, Any],
    sweep_index: dict[tuple[str, str], list[tuple[str, str]]],
) -> list[dict[str, Any]]:
    """For each run in cell, find the best available screenshot path.

    Preference: runs.jsonl `final_screenshot` if it exists on disk; else
    consume one entry from the matching sweep_index list (in order).
    """
    resolved: list[dict[str, Any]] = []
    sweep_pool = {k: list(v) for k, v in sweep_index.items()}

    for run in cell["runs"]:
        shot_path: str | None = None
        candidate = run.get("final_screenshot")
        if candidate and Path(candidate).is_file():
            shot_path = candidate
        else:
            pool = sweep_pool.get((run.get("model"), run.get("task")), [])
            while pool:
                _, p = pool.pop(0)
                if Path(p).is_file():
                    shot_path = p
                    break
        resolved.append({"run": run, "src_path": shot_path})
    return resolved
