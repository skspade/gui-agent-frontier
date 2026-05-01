# Findings webapp — design

**Status:** approved 2026-05-01.
**Implementation plan:** to follow in a sibling `…-plan.md`.

## Purpose

A single-page static site that displays the project's findings as a
**model-vs-test cliff matrix**. Doubles as (a) a personal navigator
for runs and screenshots while working, and (b) a presentable link to
share the thesis without forcing readers to clone the repo.

The framing is the user's: tests get progressively harder; for each
model we want to see *where it falls off the cliff*, and whether
parameter count correlates with cliff position.

## Architecture

Plain static site — no framework, no Node toolchain. A Python build
script reads existing data files and emits the site into `web/`. The
output is a self-contained `index.html` with cell data inlined as
`<script type="application/json">`, plus copied screenshot assets.
Served locally with `python -m http.server` or uploaded as-is to any
static host.

Rationale: the project is Python-heavy with zero JS infra; data is
small (~120 runs, ≤6 models, ≤10 tests) and already structured;
audience is "personal + presentable" so a one-file artifact you can
open from `file://` is the lowest-friction path. No backend means no
service, no live-tail, no auth.

## The matrix (the spine)

- **Rows = models, ordered by parameter count**: UI-Venus 1.5 8B →
  MAI-UI 8B → UI-Venus 1.5 30B-A3B → bu-30B-A3B-preview → Holo3
  35B-A3B → Qwen 2.5-VL 72B. Row label shows model name plus
  active-bytes / total-bytes (the meaningful axis for MoE).
- **Columns = tests, grouped by class** with visible band separators
  `[ A ] [ B ] [ C ] [ D ]`. Within each band, ordered easy → hard
  (curated in config). Column header is the test slug; hover shows the
  human description.
- **Cells = pass rate** as a `k/n` fraction with a green-to-red
  background-color gradient; gray for "not run". A small subscript
  shows `n` so n=1 doesn't visually weigh the same as n=3.
- **Cliff edge**: per row, a thin trailing edge marks the rightmost
  cell with ≥70% pass — the Pareto-meaningful floor from the thesis.
  The eye sweeps across rows and the cliff falls out.

## Intro band (above the matrix)

One screen-height band, three things, no more:

- One paragraph of thesis framing — "the contribution is the boundary,
  not a single point" — pulled verbatim from `docs/thesis.md`.
- A legend: A/B/C/D class definitions in one sentence each, harness
  profile shorthand, color/cell-fraction key.
- A "data built at" timestamp — commit hash + date.

No phase timeline, no backlog, no thesis prose beyond the paragraph.

## Side panel drilldown

Click a cell → right-side panel slides in; matrix stays visible.

Panel content:
- Header: `<model> × <test>`, aggregate `k/n`.
- For each run (chronological): outcome category (pass / stuck_loop /
  exhausted / call_user), step count, elapsed seconds, run timestamp,
  thumbnail of `final.png` linking to a full-size lightbox.
- A "phase reference" line if the cell maps to a documented phase
  (e.g. `Phase 19, 19a`) — text only.

No log viewer, no markdown rendering. This is a findings viewer, not
a debugger; logs stay in `data/sweeps/...`.

## Data pipeline

`scripts/build_site.py` reads:

- `data/runs.jsonl` — per-run records (task, model, harness, outcome,
  category, steps, elapsed_s, ts, final_screenshot).
- `data/sweeps/*/summary.json` — per-sweep results with
  `screenshot_path` per run-index.
- `web/config.yaml` — **the one hand-maintained file**: model order,
  tests grouped by class in column order, human labels, intro
  paragraph.

Aggregation:
- Cell runs = union of `runs.jsonl` matches on `(model, task)` and
  sweep results for the same pair.
- Pass = `category == "pass"` (existing convention). For older rows
  missing `category`, treat `outcome ∈ {done, call_user}` as pass —
  matches implicit Phase 19 scoring.
- `n` = total aggregated runs; `k` = passes.

Output:
- `web/index.html` — self-contained with inlined JSON cell data.
- `web/screenshots/<model>/<task>/<run-id>.png` — copied from
  referenced paths.
- `web/styles.css`, `web/app.js` — small, hand-written.

## File layout

```
web/
  index.html       # built artifact
  app.js           # ~150 LOC vanilla JS — matrix render, panel toggle, lightbox
  styles.css       # ~100 LOC
  config.yaml      # hand-curated row/col order + intro text + class labels
  screenshots/     # built artifact
scripts/
  build_site.py    # reads jsonl/json/yaml → emits web/index.html + screenshots
```

`.gitignore` excludes `web/index.html` and `web/screenshots/` so the
repo stays clean; either gets rebuilt by anyone with the data.

## Out of scope (explicit "no")

- No phase-timeline view, no Markdown rendering of `findings.md`.
- No backlog view (planned ≠ findings).
- No live data, no file watcher, no auto-rebuild on commit. Run the
  build script when the site needs refreshing.
- No charting library, no frontend framework, no bundler.
- No backend, no auth, no analytics.

## Open implementation choices (deferred to plan)

- How `web/screenshots/` is populated when `final_screenshot` in
  `runs.jsonl` points at `/tmp/...` (a known artifact of the smoke
  runner). Likely: skip those rows for thumbnails, fall back to the
  first sweep run that does have a real path; revisit during planning.
- Exact color gradient (linear vs. perceptual) and whether to mark
  n=1 cells distinctly from n≥3 cells beyond the subscript.
- Whether `config.yaml` carries the harness profile per cell or
  whether harness is implicit (default `(1,1,1,1)` for all rows in
  v1).
