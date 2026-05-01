"""Build the findings webapp into web/.

Usage
-----
    cd /home/seans/Source/vision-model
    .venv/bin/python scripts/build_site.py

Then serve locally:

    .venv/bin/python -m http.server --directory web 8000
    # → http://localhost:8000

Or deploy to GitHub Pages (gh-pages branch on origin):

    bash scripts/deploy_site.sh
    # → https://skspade.github.io/gui-agent-frontier/

Reads:
    data/runs.jsonl              — per-run records (source of truth for k/n).
    data/sweeps/*/summary.json   — sweep results with screenshot paths.
    web/config.yaml              — curated row/column ordering and labels.

Writes (gitignored):
    web/index.html
    web/screenshots/<model>/<task>/<n>.png

Pass criterion: `category == "pass"`, falling back to
`outcome ∈ {"done", "call_user"}` for legacy rows missing `category`.
"""

from __future__ import annotations

import datetime as _dt
import json
import shutil
from pathlib import Path
from typing import Any

import yaml


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
    for entries in index.values():
        entries.sort(key=lambda x: x[0])
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
        if (
            candidate
            and not candidate.startswith("/tmp/")
            and Path(candidate).is_file()
        ):
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


HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Findings — vision-model</title>
<link rel="stylesheet" href="styles.css">
</head>
<body>
<main id="app"></main>
<aside id="panel" hidden></aside>
<div id="lightbox" hidden></div>
<script type="application/json" id="app-data">__PAYLOAD__</script>
<script src="app.js"></script>
</body>
</html>
"""


def _slug(s: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in s)


def main(repo_root: Path | None = None) -> None:
    repo_root = Path(repo_root) if repo_root else Path(__file__).resolve().parents[1]
    runs_path = repo_root / "data" / "runs.jsonl"
    sweeps_dir = repo_root / "data" / "sweeps"
    web_dir = repo_root / "web"
    config = yaml.safe_load((web_dir / "config.yaml").read_text())

    runs: list[dict[str, Any]] = []
    if runs_path.exists():
        for line in runs_path.read_text().splitlines():
            line = line.strip()
            if line:
                runs.append(json.loads(line))

    sweep_index = build_sweep_index(sweeps_dir) if sweeps_dir.exists() else {}
    cells = aggregate_cells(runs, config)

    shots_root = web_dir / "screenshots"
    if shots_root.exists():
        shutil.rmtree(shots_root)

    out_cells: list[dict[str, Any]] = []
    for (model, test), cell in cells.items():
        resolved = resolve_screenshots(cell, sweep_index)
        runs_out: list[dict[str, Any]] = []
        for i, item in enumerate(resolved):
            run = item["run"]
            shot_rel: str | None = None
            if item["src_path"]:
                dst = shots_root / _slug(model) / _slug(test) / f"{i}.png"
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(item["src_path"], dst)
                shot_rel = f"screenshots/{_slug(model)}/{_slug(test)}/{i}.png"
            runs_out.append({
                "ts": run.get("ts"),
                "outcome": run.get("outcome"),
                "category": run.get("category"),
                "pass": _is_pass(run),
                "steps": run.get("steps"),
                "elapsed_s": run.get("elapsed_s"),
                "harness": run.get("harness"),
                "screenshot": shot_rel,
            })
        out_cells.append({
            "model": model,
            "test": test,
            "k": cell["k"],
            "n": cell["n"],
            "runs": runs_out,
        })

    payload = {
        "intro": config.get("intro", ""),
        "class_labels": config.get("class_labels", {}),
        "models": config["models"],
        "tests": config["tests"],
        "cells": out_cells,
        "built_at": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
    }

    html = HTML_TEMPLATE.replace(
        "__PAYLOAD__",
        json.dumps(payload).replace("<", "\\u003c"),
    )
    (web_dir / "index.html").write_text(html)
    print(f"Wrote {web_dir / 'index.html'} — {len(out_cells)} cells")


if __name__ == "__main__":
    main()
