# Findings Webapp Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a single-page static site that displays the project's
findings as a model-vs-test cliff matrix, populated by a Python build
script that aggregates `data/runs.jsonl` and `data/sweeps/*/summary.json`.

**Architecture:** Python build script (`scripts/build_site.py`) reads
runs/sweeps/config and emits `web/index.html` with cell data inlined as
`<script type="application/json">`, plus copied screenshots under
`web/screenshots/`. Front-end is hand-written vanilla HTML/CSS/JS — no
framework, no bundler. Pure aggregation logic is TDD'd; rendering is
checked manually + with smoke tests on the build artifact.

**Tech Stack:** Python 3.14 (existing `.venv`), PyYAML (already
installed), pytest (already installed). Front-end: vanilla HTML/CSS/JS.

**Reference design:** `docs/plans/2026-05-01-findings-webapp-design.md`.

---

## Task 1: Scaffolding

**Files:**
- Create: `web/config.yaml`
- Create: `web/.gitkeep`
- Create: `tests/__init__.py`
- Create: `tests/build_site/__init__.py`
- Modify: `.gitignore`

**Step 1: Create the directory layout**

```bash
mkdir -p web tests/build_site
touch tests/__init__.py tests/build_site/__init__.py web/.gitkeep
```

**Step 2: Add gitignore entries for built artifacts**

Append to `.gitignore`:
```
# Findings webapp — built artifacts (rebuild with scripts/build_site.py)
web/index.html
web/screenshots/
```

**Step 3: Write the curated config**

Create `web/config.yaml`:
```yaml
# Hand-curated ordering for the findings webapp.
# Models are listed in order of total parameter count (rows top→bottom).
# Tests are grouped by class and ordered easy→hard within each class
# (columns left→right).

intro: |
  The contribution is the boundary, not a single point. For each
  task class, where does the (model, harness) cliff sit — where does
  smaller-model-plus-smarter-harness stop working and you have to spend
  parameters or API dollars? This page shows each model's cliff
  side-by-side: rows are models ordered by parameter count, columns
  are tests grouped by class A/B/C/D and ordered easy→hard within
  each band.

class_labels:
  A: "Known-site DOM, short horizon"
  B: "Known-site DOM, long horizon + grounding pinches"
  C: "Visual grounding required (canvas / shadow-DOM)"
  D: "Novel real-world e-commerce"

models:
  - id: ui-venus-1.5-8b
    label: "UI-Venus 1.5 8B"
    params: "8B"
  - id: mai-ui-8b
    label: "MAI-UI 8B"
    params: "8B"
  - id: ui-venus-1.5-30b-a3b
    label: "UI-Venus 1.5 30B-A3B"
    params: "30B (A3B)"
  - id: bu-30b-a3b-preview
    label: "bu-30B-A3B preview"
    params: "30B (A3B)"
  - id: holo3-35b-a3b
    label: "Holo3 35B-A3B"
    params: "35B (A3B)"
  - id: qwen2.5-vl-72b-instruct
    label: "Qwen 2.5-VL 72B"
    params: "72B"

tests:
  A:
    - id: saucedemo_headed
      label: "saucedemo (headed)"
      desc: "DOM-traversable, short horizon — baseline."
  B:
    - id: saucedemo_backpack_only
      label: "saucedemo: backpack only"
      desc: "Add one product to cart on a known DOM site."
    - id: saucedemo_full_checkout
      label: "saucedemo: full checkout"
      desc: "20+ step DOM flow with cart-icon precision pinch."
  C:
    - id: excalidraw_drag
      label: "excalidraw: drag rectangle"
      desc: "Pure pixel-coord drag on a canvas."
    - id: excalidraw_drag_v2
      label: "excalidraw: drag (v2, no Escape)"
      desc: "Phase 22 variant — no post-drag keyboard input."
    - id: excalidraw_toolbar
      label: "excalidraw: toolbar walk"
      desc: "Identify and click each toolbar icon visually."
  D:
    - id: ikea_billy
      label: "IKEA: BILLY"
      desc: "Direct-PDP add-to-cart with cookie/upsell overlays."
    - id: ikea_search_add
      label: "IKEA: search → add"
      desc: "Search-result variant disambiguation + overlays."
    - id: bestbuy_airpods
      label: "Best Buy: AirPods"
      desc: "Dense PDP, color/variant picker, overlay dismissal."
```

**Step 4: Commit**

```bash
git add tests/__init__.py tests/build_site/__init__.py web/config.yaml web/.gitkeep .gitignore
git commit -m "chore(web): scaffold web/, tests/, and config.yaml for findings site"
```

---

## Task 2: Aggregation logic (TDD)

**Files:**
- Create: `scripts/build_site.py`
- Test: `tests/build_site/test_aggregate.py`

The `aggregate_cells(runs, config)` function takes a list of run dicts
(parsed from `runs.jsonl`) and the loaded config, and returns
`{(model_id, test_id): {"k": int, "n": int, "runs": [run_dicts]}}` for
every `(model, test)` pair that appears in either source. Cells with
zero runs are *not* included — the renderer treats absent entries as
"not run" (gray).

**Step 1: Write the failing tests**

Create `tests/build_site/test_aggregate.py`:
```python
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
```

**Step 2: Run the tests to verify they fail**

```bash
cd /home/seans/Source/vision-model
.venv/bin/pytest tests/build_site/test_aggregate.py -v
```

Expected: ImportError or `aggregate_cells` undefined.

**Step 3: Write minimal implementation**

Create `scripts/build_site.py`:
```python
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
```

**Step 4: Run the tests to verify they pass**

```bash
.venv/bin/pytest tests/build_site/test_aggregate.py -v
```

Expected: 5 passed.

**Step 5: Commit**

```bash
git add scripts/build_site.py tests/build_site/test_aggregate.py
git commit -m "feat(web): aggregate_cells with k/n counts and category fallback"
```

---

## Task 3: Screenshot resolution (TDD)

**Files:**
- Modify: `scripts/build_site.py`
- Test: `tests/build_site/test_screenshots.py`

Each cell's runs may reference screenshots in three places:
1. `data/sweeps/<sweep_id>/<model>_<quant>/run-N/final.png` — durable, real path.
2. `final_screenshot` field in `runs.jsonl` pointing at an absolute path
   (sometimes a `/tmp/...` path that no longer exists).
3. Nothing.

`resolve_screenshots(cell, sweep_index)` returns a list of `{run, src_path}`
entries — one per run, with `src_path=None` when no usable file exists.
`build_sweep_index(sweeps_dir)` returns
`{(model, task): [(timestamp, abs_path)]}` so resolver can pair sweep
screenshots with runs by nearest timestamp.

**Step 1: Write the failing tests**

Create `tests/build_site/test_screenshots.py`:
```python
"""Tests for screenshot resolution."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from build_site import build_sweep_index, resolve_screenshots  # noqa: E402


def test_build_sweep_index_groups_by_model_and_task(tmp_path):
    sweep = tmp_path / "20260501-001" / "ui-venus-1.5-8b_Q6_K" / "run-1"
    sweep.mkdir(parents=True)
    (sweep / "final.png").write_bytes(b"png")
    summary = tmp_path / "20260501-001" / "summary.json"
    summary.write_text(json.dumps({
        "task": "saucedemo_full_checkout",
        "results": [{
            "model": "ui-venus-1.5-8b",
            "quant": "Q6_K",
            "run_index": 1,
            "screenshot_path": str(sweep / "final.png"),
            "duration_s": 12.0,
        }],
    }))
    summary_extra = tmp_path / "20260501-001" / "summary.json"  # already wrote
    index = build_sweep_index(tmp_path)
    assert ("ui-venus-1.5-8b", "saucedemo_full_checkout") in index
    paths = [p for _, p in index[("ui-venus-1.5-8b", "saucedemo_full_checkout")]]
    assert paths == [str(sweep / "final.png")]


def test_resolve_screenshots_uses_runs_jsonl_path_when_real(tmp_path):
    real = tmp_path / "shot.png"
    real.write_bytes(b"png")
    cell = {"runs": [
        {"model": "m", "task": "t", "ts": "2026-05-01T00:00",
         "final_screenshot": str(real)},
    ]}
    resolved = resolve_screenshots(cell, sweep_index={})
    assert resolved[0]["src_path"] == str(real)


def test_resolve_screenshots_skips_missing_tmp_paths(tmp_path):
    cell = {"runs": [
        {"model": "m", "task": "t", "ts": "2026-05-01T00:00",
         "final_screenshot": "/tmp/does_not_exist.png"},
    ]}
    resolved = resolve_screenshots(cell, sweep_index={})
    assert resolved[0]["src_path"] is None


def test_resolve_screenshots_falls_back_to_sweep_index(tmp_path):
    sweep_shot = tmp_path / "sweep.png"
    sweep_shot.write_bytes(b"png")
    cell = {"runs": [
        {"model": "m", "task": "t", "ts": "2026-05-01T00:00",
         "final_screenshot": "/tmp/gone.png"},
    ]}
    sweep_index = {("m", "t"): [("2026-05-01T00:00", str(sweep_shot))]}
    resolved = resolve_screenshots(cell, sweep_index=sweep_index)
    assert resolved[0]["src_path"] == str(sweep_shot)
```

**Step 2: Run the tests to verify they fail**

```bash
.venv/bin/pytest tests/build_site/test_screenshots.py -v
```

Expected: ImportError on `build_sweep_index` and `resolve_screenshots`.

**Step 3: Add the implementation**

Append to `scripts/build_site.py`:
```python
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
```

**Step 4: Run the tests to verify they pass**

```bash
.venv/bin/pytest tests/build_site/ -v
```

Expected: all tests pass (5 from Task 2 + 4 here = 9 total).

**Step 5: Commit**

```bash
git add scripts/build_site.py tests/build_site/test_screenshots.py
git commit -m "feat(web): screenshot resolver — runs.jsonl path or sweep fallback"
```

---

## Task 4: Build script wiring (the `main` entrypoint)

**Files:**
- Modify: `scripts/build_site.py`
- Test: `tests/build_site/test_main.py`

`main()` reads runs.jsonl, sweeps, and config; calls aggregate_cells +
resolve_screenshots; copies screenshot files into `web/screenshots/`; and
writes `web/index.html`. The HTML template is a static skeleton with one
`<script type="application/json" id="app-data">` block carrying the full
payload; `web/app.js` reads that on page load.

The payload schema:
```json
{
  "intro": "...",
  "class_labels": {"A": "...", ...},
  "models": [{"id": "...", "label": "...", "params": "..."}, ...],
  "tests": {"A": [{"id": "...", "label": "...", "desc": "..."}, ...], ...},
  "cells": [
    {
      "model": "ui-venus-1.5-8b",
      "test": "saucedemo_backpack_only",
      "k": 2,
      "n": 3,
      "runs": [
        {"ts": "...", "outcome": "done", "category": "pass",
         "steps": 8, "elapsed_s": 19.2,
         "screenshot": "screenshots/ui-venus-1.5-8b/saucedemo_backpack_only/0.png"}
      ]
    }
  ],
  "built_at": "2026-05-01T..."
}
```

**Step 1: Write a smoke test for main**

Create `tests/build_site/test_main.py`:
```python
"""End-to-end smoke test: run main against synthetic inputs, check the
html artifact contains the embedded payload."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import build_site  # noqa: E402


def test_main_writes_index_with_embedded_payload(tmp_path):
    repo = tmp_path
    (repo / "data").mkdir()
    (repo / "data" / "sweeps").mkdir()
    (repo / "web").mkdir()

    # Minimal config
    (repo / "web" / "config.yaml").write_text(
        "intro: hello\n"
        "class_labels: {B: 'long horizon'}\n"
        "models:\n"
        "  - {id: m1, label: 'M1', params: '8B'}\n"
        "tests:\n"
        "  B:\n"
        "    - {id: t1, label: 'T1', desc: 'test 1'}\n"
    )

    # One run with a real screenshot
    shot = repo / "data" / "shot.png"
    shot.write_bytes(b"png-bytes")
    (repo / "data" / "runs.jsonl").write_text(json.dumps({
        "task": "t1", "task_class": "B", "model": "m1",
        "harness": "uivenus", "outcome": "done", "category": "pass",
        "steps": 5, "elapsed_s": 10.0, "ts": "2026-05-01T00:00:00",
        "final_screenshot": str(shot),
    }) + "\n")

    build_site.main(repo_root=repo)

    html = (repo / "web" / "index.html").read_text()
    assert '<script type="application/json" id="app-data">' in html

    start = html.index('id="app-data">') + len('id="app-data">')
    end = html.index("</script>", start)
    payload = json.loads(html[start:end])
    assert payload["intro"] == "hello"
    assert payload["models"][0]["id"] == "m1"
    assert len(payload["cells"]) == 1
    cell = payload["cells"][0]
    assert (cell["model"], cell["test"]) == ("m1", "t1")
    assert cell["k"] == 1 and cell["n"] == 1
    assert cell["runs"][0]["screenshot"].startswith("screenshots/m1/t1/")

    copied = repo / "web" / cell["runs"][0]["screenshot"]
    assert copied.is_file()
    assert copied.read_bytes() == b"png-bytes"
```

**Step 2: Run the test to verify it fails**

```bash
.venv/bin/pytest tests/build_site/test_main.py -v
```

Expected: AttributeError on `build_site.main`.

**Step 3: Implement main + HTML template**

Append to `scripts/build_site.py`:
```python
import datetime as _dt
import shutil

import yaml


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

    html = HTML_TEMPLATE.replace("__PAYLOAD__", json.dumps(payload))
    (web_dir / "index.html").write_text(html)
    print(f"Wrote {web_dir / 'index.html'} — {len(out_cells)} cells")


if __name__ == "__main__":
    main()
```

**Step 4: Run the tests to verify they pass**

```bash
.venv/bin/pytest tests/build_site/ -v
```

Expected: 10 passed total.

**Step 5: Run the script against real data and check it doesn't crash**

```bash
.venv/bin/python scripts/build_site.py
ls web/index.html web/screenshots/
```

Expected: prints `Wrote .../web/index.html — N cells` where N > 0.
`web/index.html` exists; `web/screenshots/` has at least one file.

**Step 6: Commit**

```bash
git add scripts/build_site.py tests/build_site/test_main.py
git commit -m "feat(web): build_site main() — emit index.html with inlined payload"
```

---

## Task 5: HTML/CSS skeleton + matrix rendering

**Files:**
- Create: `web/app.js`
- Create: `web/styles.css`

The matrix is an HTML `<table>`. Rows are models (in the order given by
config). Columns are tests grouped by class with a class-band header
row plus visible `<td>` separators between bands. Each cell shows
`k/n` (with `n` smaller subscript), background-color from a green→red
gradient (`hsl(120 * (k/n), 60%, 55%)` clamped). Empty cells are gray.

**Step 1: Write `web/styles.css`**

```css
:root {
  --bg: #f6f7f9;
  --fg: #1a1d23;
  --muted: #6c7280;
  --line: #d6dae0;
  --accent: #0b6cff;
  --gray-cell: #e7e9ee;
}

* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; }
body {
  font: 14px/1.45 system-ui, -apple-system, "Segoe UI", sans-serif;
  background: var(--bg);
  color: var(--fg);
}

main { max-width: 1400px; margin: 0 auto; padding: 24px 24px 96px; }

header.intro h1 { margin: 0 0 6px; font-size: 22px; }
header.intro .built { color: var(--muted); font-size: 12px; }
header.intro p { max-width: 78ch; }
header.intro .legend {
  display: flex; flex-wrap: wrap; gap: 16px;
  margin: 12px 0 24px; font-size: 12px; color: var(--muted);
}
header.intro .legend b { color: var(--fg); }

table.matrix {
  border-collapse: collapse;
  width: 100%;
  font-size: 13px;
}
table.matrix th, table.matrix td {
  border: 1px solid var(--line);
  padding: 6px 8px;
  text-align: center;
  white-space: nowrap;
}
table.matrix th.row-label {
  text-align: left;
  font-weight: 500;
  background: #fff;
}
table.matrix th.row-label .params {
  color: var(--muted); font-size: 11px; margin-left: 6px;
}
table.matrix th.class-band {
  background: #eef1f6;
  font-weight: 600;
}
table.matrix td.cell {
  cursor: pointer;
  font-variant-numeric: tabular-nums;
}
table.matrix td.cell:hover { outline: 2px solid var(--accent); }
table.matrix td.cell .n {
  font-size: 10px; color: rgba(0,0,0,0.55); margin-left: 2px;
}
table.matrix td.empty { background: var(--gray-cell); color: var(--muted); }
table.matrix td.band-sep { border-left: 3px solid var(--line); }
```

**Step 2: Write `web/app.js` (matrix render only — panel comes in Task 6)**

```javascript
"use strict";

const data = JSON.parse(document.getElementById("app-data").textContent);

const cellMap = new Map();
for (const c of data.cells) cellMap.set(c.model + "::" + c.test, c);

function cellColor(k, n) {
  if (n === 0) return "var(--gray-cell)";
  const ratio = k / n;
  return `hsl(${Math.round(120 * ratio)}, 60%, 78%)`;
}

function renderHeader() {
  const classKeys = Object.keys(data.tests);
  const classRow = ["<th></th>"];
  for (const cls of classKeys) {
    const span = data.tests[cls].length;
    classRow.push(`<th class="class-band" colspan="${span}">${cls} — ${data.class_labels[cls] || ""}</th>`);
  }
  const testRow = ["<th></th>"];
  classKeys.forEach((cls, i) => {
    data.tests[cls].forEach((t, j) => {
      const sep = (j === 0 && i > 0) ? " band-sep" : "";
      testRow.push(`<th class="test-label${sep}" title="${t.desc || ""}">${t.label}</th>`);
    });
  });
  return `<thead><tr>${classRow.join("")}</tr><tr>${testRow.join("")}</tr></thead>`;
}

function renderRow(model) {
  const tds = [
    `<th class="row-label">${model.label}<span class="params">${model.params}</span></th>`,
  ];
  const classKeys = Object.keys(data.tests);
  classKeys.forEach((cls, i) => {
    data.tests[cls].forEach((t, j) => {
      const cell = cellMap.get(model.id + "::" + t.id);
      const sep = (j === 0 && i > 0) ? " band-sep" : "";
      if (!cell) {
        tds.push(`<td class="empty${sep}">—</td>`);
      } else {
        const bg = cellColor(cell.k, cell.n);
        tds.push(
          `<td class="cell${sep}" style="background:${bg}" data-model="${model.id}" data-test="${t.id}">` +
          `${cell.k}/${cell.n}<span class="n">·n=${cell.n}</span></td>`
        );
      }
    });
  });
  return `<tr>${tds.join("")}</tr>`;
}

function renderMatrix() {
  const rows = data.models.map(renderRow).join("");
  return `<table class="matrix">${renderHeader()}<tbody>${rows}</tbody></table>`;
}

function renderIntro() {
  const legendBits = Object.entries(data.class_labels).map(
    ([k, v]) => `<span><b>${k}:</b> ${v}</span>`
  ).join("");
  return `
    <header class="intro">
      <h1>Findings — local GUI grounding agents</h1>
      <div class="built">Built ${data.built_at}</div>
      <p>${data.intro}</p>
      <div class="legend">
        ${legendBits}
        <span><b>Cells:</b> k/n pass count · green = pass, red = fail, gray = not run.</span>
      </div>
    </header>`;
}

document.getElementById("app").innerHTML = renderIntro() + renderMatrix();
```

**Step 3: Rebuild and visually inspect**

```bash
.venv/bin/python scripts/build_site.py
.venv/bin/python -m http.server --directory web 8000 &
SERVER_PID=$!
sleep 1
echo "Open http://localhost:8000 and verify the matrix renders with rows/cols/colors."
echo "When done, kill server with: kill $SERVER_PID"
```

Expected (visual): matrix shows model rows, A/B/C/D class band header,
cells with k/n values colored along a green→red gradient. Empty cells
are gray with `—`.

**Step 4: Commit**

```bash
git add web/styles.css web/app.js
git commit -m "feat(web): matrix rendering — class bands, cliff-friendly grid"
```

---

## Task 6: Side panel + lightbox

**Files:**
- Modify: `web/app.js`
- Modify: `web/styles.css`

Click on a cell → side panel slides in from the right with per-run
detail and screenshot thumbnails. Click a thumbnail → full-size
lightbox overlay. Click outside the panel or hit `Escape` → close.

**Step 1: Add panel + lightbox CSS**

Append to `web/styles.css`:
```css
aside#panel {
  position: fixed; top: 0; right: 0; bottom: 0;
  width: min(440px, 90vw);
  background: #fff;
  border-left: 1px solid var(--line);
  box-shadow: -8px 0 24px rgba(0,0,0,0.06);
  overflow-y: auto;
  padding: 20px 22px;
}
aside#panel[hidden] { display: none; }
aside#panel h2 { margin: 0 0 4px; font-size: 16px; }
aside#panel .agg { color: var(--muted); margin-bottom: 16px; }
aside#panel .run {
  border-top: 1px solid var(--line);
  padding: 12px 0;
}
aside#panel .run .meta {
  font-size: 12px; color: var(--muted);
  display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 6px;
}
aside#panel .run .meta .pass { color: #1f7a3a; font-weight: 600; }
aside#panel .run .meta .fail { color: #b3261e; font-weight: 600; }
aside#panel .run img.thumb {
  max-width: 100%; max-height: 220px;
  border: 1px solid var(--line);
  cursor: zoom-in;
}
aside#panel button.close {
  position: absolute; top: 10px; right: 12px;
  background: transparent; border: 0;
  font-size: 18px; cursor: pointer; color: var(--muted);
}

#lightbox {
  position: fixed; inset: 0;
  background: rgba(0,0,0,0.85);
  display: flex; align-items: center; justify-content: center;
  cursor: zoom-out;
  z-index: 100;
}
#lightbox[hidden] { display: none; }
#lightbox img { max-width: 96vw; max-height: 96vh; }
```

**Step 2: Add panel + lightbox JS**

Append to `web/app.js`:
```javascript
const panel = document.getElementById("panel");
const lightbox = document.getElementById("lightbox");

function openPanel(modelId, testId) {
  const model = data.models.find(m => m.id === modelId);
  const test = Object.values(data.tests).flat().find(t => t.id === testId);
  const cell = cellMap.get(modelId + "::" + testId);
  if (!cell) return;
  const runs = cell.runs.map(r => {
    const passClass = r.category === "pass" ? "pass" : "fail";
    const passLabel = r.category || r.outcome || "?";
    const ts = (r.ts || "").replace("T", " ").slice(0, 16);
    const steps = r.steps != null ? `${r.steps} steps` : "";
    const elapsed = r.elapsed_s != null ? `${r.elapsed_s.toFixed(1)}s` : "";
    const thumb = r.screenshot
      ? `<img class="thumb" src="${r.screenshot}" data-full="${r.screenshot}" alt="final screenshot">`
      : `<div class="meta">(no screenshot available)</div>`;
    return `
      <div class="run">
        <div class="meta">
          <span class="${passClass}">${passLabel}</span>
          <span>${ts}</span>
          <span>${steps}</span>
          <span>${elapsed}</span>
          <span>${r.harness || ""}</span>
        </div>
        ${thumb}
      </div>`;
  }).join("");
  panel.innerHTML = `
    <button class="close" aria-label="Close">×</button>
    <h2>${model.label} × ${test.label}</h2>
    <div class="agg">${cell.k}/${cell.n} pass · n=${cell.n}</div>
    ${runs}`;
  panel.hidden = false;
}

function closePanel() { panel.hidden = true; }
function openLightbox(src) {
  lightbox.innerHTML = `<img src="${src}" alt="full screenshot">`;
  lightbox.hidden = false;
}
function closeLightbox() { lightbox.hidden = true; lightbox.innerHTML = ""; }

document.addEventListener("click", (e) => {
  const cellEl = e.target.closest("td.cell");
  if (cellEl) {
    openPanel(cellEl.dataset.model, cellEl.dataset.test);
    return;
  }
  if (e.target.matches("aside#panel button.close")) {
    closePanel();
    return;
  }
  if (e.target.matches("aside#panel img.thumb")) {
    openLightbox(e.target.dataset.full);
    return;
  }
  if (e.target.closest("#lightbox")) {
    closeLightbox();
    return;
  }
});

document.addEventListener("keydown", (e) => {
  if (e.key !== "Escape") return;
  if (!lightbox.hidden) closeLightbox();
  else if (!panel.hidden) closePanel();
});
```

**Step 3: Rebuild and visually inspect**

```bash
.venv/bin/python scripts/build_site.py
.venv/bin/python -m http.server --directory web 8000 &
SERVER_PID=$!
sleep 1
echo "Open http://localhost:8000."
echo "Click a non-empty cell — panel should appear with per-run rows."
echo "Click a thumbnail — full-size lightbox opens."
echo "Press Escape — closes lightbox first, then panel."
echo "kill $SERVER_PID  # when done"
```

**Step 4: Commit**

```bash
git add web/app.js web/styles.css
git commit -m "feat(web): cell side panel with screenshot thumbnails + lightbox"
```

---

## Task 7: Cliff-edge marker

**Files:**
- Modify: `web/app.js`
- Modify: `web/styles.css`

For each model row, mark the **rightmost cell with pass-rate ≥ 70%**
with a thin trailing edge — that's the Pareto-meaningful floor from
`docs/thesis.md`. The eye sweeps across rows and the cliff is visible.

**Step 1: Add cliff CSS**

Append to `web/styles.css`:
```css
table.matrix td.cliff-edge {
  border-right: 3px solid #1a1d23 !important;
}
table.matrix td.cliff-edge::after {
  content: "▌"; color: #1a1d23;
  font-size: 10px; margin-left: 4px; opacity: 0.55;
}
```

**Step 2: Add cliff-edge logic to renderRow**

In `web/app.js`, add a helper and update `renderRow`:

```javascript
const CLIFF_THRESHOLD = 0.7;

function findCliffIndex(modelId, allTests) {
  let lastPassIdx = -1;
  allTests.forEach((t, idx) => {
    const cell = cellMap.get(modelId + "::" + t.id);
    if (cell && cell.n > 0 && cell.k / cell.n >= CLIFF_THRESHOLD) lastPassIdx = idx;
  });
  return lastPassIdx;
}
```

Replace the existing `renderRow` body with:
```javascript
function renderRow(model) {
  const tds = [
    `<th class="row-label">${model.label}<span class="params">${model.params}</span></th>`,
  ];
  const classKeys = Object.keys(data.tests);
  const flatTests = classKeys.flatMap(cls => data.tests[cls]);
  const cliffIdx = findCliffIndex(model.id, flatTests);
  let absIdx = -1;
  classKeys.forEach((cls, i) => {
    data.tests[cls].forEach((t, j) => {
      absIdx += 1;
      const sep = (j === 0 && i > 0) ? " band-sep" : "";
      const cliff = absIdx === cliffIdx ? " cliff-edge" : "";
      const cell = cellMap.get(model.id + "::" + t.id);
      if (!cell) {
        tds.push(`<td class="empty${sep}${cliff}">—</td>`);
      } else {
        const bg = cellColor(cell.k, cell.n);
        tds.push(
          `<td class="cell${sep}${cliff}" style="background:${bg}" data-model="${model.id}" data-test="${t.id}">` +
          `${cell.k}/${cell.n}<span class="n">·n=${cell.n}</span></td>`
        );
      }
    });
  });
  return `<tr>${tds.join("")}</tr>`;
}
```

**Step 3: Rebuild and visually verify**

```bash
.venv/bin/python scripts/build_site.py
.venv/bin/python -m http.server --directory web 8000 &
SERVER_PID=$!
sleep 1
echo "Open http://localhost:8000."
echo "Each model row should have a thicker right-border on its rightmost"
echo "≥70% pass cell — the cliff edge."
echo "kill $SERVER_PID  # when done"
```

**Step 4: Commit**

```bash
git add web/app.js web/styles.css
git commit -m "feat(web): cliff-edge marker (rightmost ≥70% pass cell per row)"
```

---

## Task 8: Build instructions + final verification

**Files:**
- Modify: `scripts/build_site.py` (top docstring)
- Test: re-run full suite

**Step 1: Expand the top docstring with usage**

Replace the top docstring of `scripts/build_site.py` with:
```python
"""Build the findings webapp into web/.

Usage
-----
    cd /home/seans/Source/vision-model
    .venv/bin/python scripts/build_site.py

Then serve locally:

    .venv/bin/python -m http.server --directory web 8000
    # → http://localhost:8000

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
```

**Step 2: Run the full test suite**

```bash
.venv/bin/pytest tests/build_site/ -v
```

Expected: all tests pass.

**Step 3: Build against real data and sanity check**

```bash
.venv/bin/python scripts/build_site.py
```

Manually verify the printed cell count is plausible (>10, <80 given
6 models × 9 tests = 54 max).

```bash
.venv/bin/python -m http.server --directory web 8000 &
SERVER_PID=$!
sleep 1
```

In the browser:
- [ ] Intro paragraph + legend + build timestamp appear at top.
- [ ] Matrix has 6 model rows, A/B/C/D class bands.
- [ ] At least one cell in each band is non-gray.
- [ ] Cliff edge is visible on at least one row.
- [ ] Click a cell with `n ≥ 1` → panel opens with run rows.
- [ ] Thumbnails appear for at least some runs.
- [ ] Click thumbnail → lightbox opens. Escape closes it.
- [ ] Click a non-empty cell on a different model → panel content updates.

```bash
kill $SERVER_PID
```

**Step 4: Commit**

```bash
git add scripts/build_site.py
git commit -m "docs(web): expand build_site.py usage docstring"
```

---

## What's intentionally excluded (per design)

- Markdown rendering of `findings.md`.
- Phase-timeline view, backlog view, raw runs table view.
- Live data / file-watcher / auto-rebuild on commit.
- Charting library, frontend framework, bundler.
- Backend, auth, analytics.
- Per-cell harness profile (v1 treats all rows as default `(1,1,1,1)`).

These are deferred to a future iteration if/when the use case shows up.
