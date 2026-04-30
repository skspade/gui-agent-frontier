# Harness Environmental Noise Reduction — Master Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Phases 2–5 are intentionally stubbed — re-expand each one with bite-sized tasks **after** the prior phase's re-measurement, so the design follows what was learned. Don't implement Phase 2+ until Phase 1's re-measurement is in.

**Goal:** Move local 8B / 30B-A3B models on Class B and Class D cart tasks from the current frontier-sketch ~50% PASS rate (Phase 16/18 mixed) toward 70–80% by absorbing **environmental** failure modes (cart-state opacity, modal/overlay noise, infinite no-progress loops, lossy action feedback) into deterministic harness tooling. Whatever residual gap remains after Phase 5 is then a clean signal that the failure is **model-capability-bound**, which is itself a useful Pareto-frontier datapoint.

**Architecture:** All five priorities target the **`scripts/custom_agent`** dispatcher (the CDP harness used for Class B+D). The browser-use harness is *out of scope* for this plan — it's already retired for serious Class B/D work in favor of `custom_agent` (Phase 14+). Verification and cleanup utilities live as importable modules under `scripts/custom_agent/` and are wired in at three insertion points: pre-page (preflight cleanup), post-action (cart-state probe + overlay probe + receipt construction), and history-rendering (surface receipts to the model). The model's action vocabulary is **not** extended — the harness drives all probes and surfaces results in the `previous_actions` block of the next prompt, matching the existing `no_effect` / "STOP" injection pattern at `scripts/custom_agent/model.py:184`.

**Tech Stack:** Python 3.14, `cdp_use` (CDP client), Chromium DevTools Protocol, llama.cpp inference server, existing `scripts/custom_agent` package.

---

## Scope decisions (read first — these are the assumptions the rest of the plan rests on)

The handoff doc reads as a generic spec; the codebase reality is more specific. The decisions below resolve the mismatches; **Phase 0 Task 0.0 confirms them with the user before any code changes**.

| Decision | Default in this plan | Why |
|---|---|---|
| **Which 5 sites?** | `saucedemo_full_checkout` (B), `saucedemo_backpack_only` (B), `ikea_search_add` (D), `ikea_billy` (D), `bestbuy_airpods` (D) | These are the 5 cart-completion smokes already in `scripts/custom_agent_tasks/`. Match the doc's "5 sites" exactly. `saucedemo_headed`/`headless` are excluded — the former is Class A login-only (no cart), the latter is excluded from frontier mapping per `docs/thesis.md`. Excalidraw smokes are Class C (not cart-task). |
| **Which 5 models?** | The 5 active-registry models: `ui-venus-1.5-8b`, `mai-ui-8b`, `ui-venus-1.5-30b-a3b`, `bu-30b-a3b-preview`, `holo3-35b-a3b`. | Matches `MODEL_HARNESS_REGISTRY` in `scripts/custom_agent/__init__.py:12`. |
| **Which harness?** | `scripts/custom_agent` only. Browser-use harness skipped. | Phase 14+ moved Class B/D evaluation to `custom_agent`; browser-use is now used only for richly-DOM'd dev-loop probes. |
| **How does the model "see" cart-state / overlay info?** | Injected as structured lines in the next turn's `previous_actions` block (model.py:178). NO new action verbs. | The model's action grammar is closed (`<action>...</action>`). Adding tool-call verbs would require per-harness changes (uivenus, holo3, toolcall) and break the closed-grammar invariant. The `no_effect` / "STOP" injection already proves history-block injection works. |
| **Do we baseline against the broken dispatcher?** | No. Fix F-6 (scroll convention) **first**, before any baseline runs. F-5 (UI-Venus 30B-A3B Best Buy hang) is left as-is and that cell is recorded as `dispatch_hang` in baseline. | Per `docs/thesis.md`: "n ≥ 3 runs on the post-2026-04-29 dispatcher (silent-CDP-drop fix applied — pre-fix runs are lower bounds, not measurements)." Same logic applies to F-6 — baseline against a known-broken scroll path is a lower bound, not a measurement. |
| **n per cell?** | Tier-2: n=3 per (site, model). 75 runs total at baseline. ~30s–2min per run + ~30s per model swap. | Doc says "Run each test 3 times and record success rate, not pass/fail." Matches `docs/thesis.md`'s Tier-2 frontier-sketch threshold. |
| **Frontier API ceiling** | Run **once** at the end (Phase 6), not once per priority milestone. | Doc says "Don't run frontier models on every iteration — once per milestone is enough." Saves API spend; the within-priority signal we care about is local-model deltas, where frontier-as-ceiling doesn't move. |

If any of these assumptions is wrong, **stop at Task 0.0** and redirect — every subsequent task depends on them.

---

## Phase 0: Lock scope, fix F-6, build measurement infra, take baseline

Before any harness improvements: confirm scope, eliminate the known F-6 confound, build a structured-results logger, and capture a clean baseline. Without this, every "we improved by X%" claim downstream is uncalibrated.

### Task 0.0: Confirm scope with the user

**Files:** none — this is a sync gate.

**Step 1: Surface the 6 scope decisions above.**

Read this section of the plan to the user. Get a yes/no on each row of the scope table. Do not proceed if any answer is "redirect."

**Step 2: Record any redirections.**

If the user redirects, edit this plan in place to reflect the new defaults — do not silently work against different assumptions.

---

### Task 0.1: Fix F-6 (scroll-direction convention)

The `ikea_billy` regression on UI-Venus-1.5-8B (Phase 18, `docs/findings.md`) showed the dispatcher's `direction='up'` → `deltaY=-600` mapping is the **opposite** of what UI-Venus's mobile-trained convention emits. Five consecutive no-op scrolls tripped stuck-loop early-out at step 9. Baseline against this is a known confound.

**Files:**
- Modify: `scripts/custom_agent/actions.py:411-429` (the `_scroll` direction-mapping branch)
- Modify: `scripts/custom_agent/model.py:106` (the `Scroll(...)` line in `NAV_USER_PROMPT`)
- Test: `scripts/custom_agent/test_scroll_direction.py` (new)

**Step 1: Write the failing test.**

```python
# scripts/custom_agent/test_scroll_direction.py
"""F-6 regression test: 'up' direction must move viewport DOWN (UI-Venus
mobile/swipe convention: up = swipe content up = see content below).
"""
from unittest.mock import AsyncMock, MagicMock
import asyncio
from scripts.custom_agent.actions import _scroll, _MIN_SCROLL_DELTA
from scripts.custom_agent.model import Action


def test_scroll_up_means_see_content_below():
    page = MagicMock()
    page.session_id = "sid"
    page.client = MagicMock()
    sent = []

    async def send_raw(method, params, session_id=None):
        sent.append((method, params))
        if method == "Runtime.evaluate" and "scrollY" in params.get("expression", ""):
            return {"result": {"value": 0}}
        return {"result": {"value": ""}}

    page.client.send_raw = AsyncMock(side_effect=send_raw)
    action = Action(kind="scroll", direction="up", raw="Scroll(direction='up')")
    asyncio.run(_scroll(page, action, (1280, 800)))

    wheel_calls = [p for m, p in sent if m == "Input.dispatchMouseEvent" and p.get("type") == "mouseWheel"]
    assert wheel_calls, "no mouseWheel dispatched"
    assert wheel_calls[0]["deltaY"] == _MIN_SCROLL_DELTA, (
        f"direction='up' should produce positive deltaY (viewport scrolls DOWN to reveal content below), "
        f"got deltaY={wheel_calls[0]['deltaY']}"
    )


def test_scroll_down_means_see_content_above():
    page = MagicMock()
    page.session_id = "sid"
    page.client = MagicMock()
    sent = []

    async def send_raw(method, params, session_id=None):
        sent.append((method, params))
        if method == "Runtime.evaluate" and "scrollY" in params.get("expression", ""):
            return {"result": {"value": 100}}
        return {"result": {"value": ""}}

    page.client.send_raw = AsyncMock(side_effect=send_raw)
    action = Action(kind="scroll", direction="down", raw="Scroll(direction='down')")
    asyncio.run(_scroll(page, action, (1280, 800)))

    wheel_calls = [p for m, p in sent if m == "Input.dispatchMouseEvent" and p.get("type") == "mouseWheel"]
    assert wheel_calls[0]["deltaY"] == -_MIN_SCROLL_DELTA
```

**Step 2: Run the test, verify it fails.**

Run: `cd /home/seans/Source/vision-model && .venv/bin/python -m pytest scripts/custom_agent/test_scroll_direction.py -v`
Expected: both tests FAIL (current mapping has `down → +`, `up → −`).

**Step 3: Apply F-6 Approach 3 (both: dispatcher + prompt).**

In `scripts/custom_agent/actions.py:411-429`, swap the direction-to-delta sign:

```python
async def _scroll(page: Page, action: Action, viewport_css: tuple[int, int]) -> None:
    if action.start_xy is not None:
        sx, sy = remap(action.start_xy, viewport_css)
    else:
        sx, sy = viewport_css[0] // 2, viewport_css[1] // 2
    if action.start_xy is not None and action.end_xy is not None:
        ex, ey = remap(action.end_xy, viewport_css)
        dx, dy = ex - sx, ey - sy
    else:
        # F-6: UI-Venus / mobile-grounding convention — direction names what
        # the user "swipes", not which way the viewport moves. up = swipe
        # content up = viewport reveals content BELOW. Sign is inverted from
        # desktop wheel convention; the dispatcher owns the mapping so all
        # models in MODEL_HARNESS_REGISTRY share one convention.
        d = action.direction or "down"
        dy_sign = +1 if d == "up" else -1 if d == "down" else 0
        dx_sign = +1 if d == "left" else -1 if d == "right" else 0
        dx, dy = dx_sign * _MIN_SCROLL_DELTA, dy_sign * _MIN_SCROLL_DELTA
    # ... (rest unchanged)
```

In `scripts/custom_agent/model.py:106`, replace:
```
Scroll(start=(x1, y1), end=(x2, y2), direction='down/up/right/left')
```
with:
```
Scroll(start=(x1, y1), end=(x2, y2), direction='down/up/right/left')
  - direction='up' = see content BELOW the current view (swipe content up)
  - direction='down' = see content ABOVE the current view (swipe content down)
  - Prefer (start, end) coords over direction when you can pinpoint a target.
```

**Step 4: Run tests, verify they pass.**

Run: `.venv/bin/python -m pytest scripts/custom_agent/test_scroll_direction.py -v`
Expected: both tests PASS.

**Step 5: Sanity-run `ikea_billy` against UI-Venus-1.5-8B.**

Per `docs/findings.md` Phase 18: BILLY stuck-looped at step 9 before this fix. Acceptance: reaches "Add to bag."

```bash
sudo bash scripts/swap_model.sh ui-venus-1.5-8b
DISPLAY=:0 XAUTHORITY=/run/user/1000/xauth_rVYaGJ XDG_RUNTIME_DIR=/run/user/1000 \
  PYTHONUNBUFFERED=1 .venv/bin/python -u scripts/custom_agent.py ikea_billy \
  > /tmp/billy_postf6.log 2>&1
```

Expected: log shows scroll actions with positive `dy` and `y: 0->600+`; outcome is `done`/`call_user` not `stuck_loop`. Final screenshot at `/tmp/custom_agent_final.png` shows the cart with BILLY in it (or blocks at a later step).

**Step 6: Commit.**

```bash
git add scripts/custom_agent/actions.py scripts/custom_agent/model.py scripts/custom_agent/test_scroll_direction.py
git commit -m "fix(harness): F-6 — invert scroll direction convention (UI-Venus mobile/swipe)"
```

---

### Task 0.2: Add a structured run logger

The doc requires "JSONL preferred so we can analyze patterns." Currently `custom_agent.py` only prints to stdout; results have to be eyeballed from per-run logs. Build a minimal logger that writes one JSONL row per run.

**Files:**
- Create: `scripts/custom_agent/run_log.py`
- Modify: `scripts/custom_agent.py` (call it from the `run()` finally branch)
- Test: `scripts/custom_agent/test_run_log.py`

**Step 1: Write the failing test.**

```python
# scripts/custom_agent/test_run_log.py
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
```

**Step 2: Run, verify fail.**

Run: `.venv/bin/python -m pytest scripts/custom_agent/test_run_log.py -v`
Expected: `ModuleNotFoundError: No module named 'scripts.custom_agent.run_log'`.

**Step 3: Implement.**

```python
# scripts/custom_agent/run_log.py
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
```

**Step 4: Run, verify pass.**

Run: `.venv/bin/python -m pytest scripts/custom_agent/test_run_log.py -v`
Expected: PASS.

**Step 5: Wire into `custom_agent.py`.**

In `scripts/custom_agent.py`, in the `try`/`finally` of `run()`, after the `print(f"\n=== outcome: ...")` line, add:

```python
from scripts.custom_agent.run_log import append_run, DEFAULT_LOG
append_run(DEFAULT_LOG, {
    "task": task_module.__name__.rsplit(".", 1)[-1],
    "task_class": getattr(task_module, "TASK_CLASS", None),
    "model": os.environ.get("MODEL", "ui-venus-1.5-8b"),
    "harness": HARNESS,
    "outcome": outcome,
    "steps": len(history),
    "elapsed_s": round(elapsed, 1),
    "final_screenshot": str(FINAL_PNG),
})
```

**Step 6: Smoke-run and verify the JSONL row appears.**

```bash
sudo bash scripts/swap_model.sh ui-venus-1.5-8b
DISPLAY=:0 XAUTHORITY=/run/user/1000/xauth_rVYaGJ XDG_RUNTIME_DIR=/run/user/1000 \
  PYTHONUNBUFFERED=1 .venv/bin/python -u scripts/custom_agent.py saucedemo_backpack_only \
  > /tmp/runlog_smoke.log 2>&1
tail -1 data/runs.jsonl
```

Expected: one row with `task: "saucedemo_backpack_only"`, `model: "ui-venus-1.5-8b"`, sane `outcome`/`steps`/`elapsed_s`.

**Step 7: Commit.**

```bash
git add scripts/custom_agent/run_log.py scripts/custom_agent/test_run_log.py scripts/custom_agent.py
git commit -m "feat(harness): JSONL run logger at data/runs.jsonl"
```

---

### Task 0.3: Failure-category classifier

Tag each run row with a deterministic failure category so we can track shifts across phases without re-eyeballing screenshots.

**Files:**
- Modify: `scripts/custom_agent/run_log.py` (add `classify_failure()`)
- Modify: `scripts/custom_agent.py` (call it before `append_run`)
- Test: `scripts/custom_agent/test_run_log.py` (extend)

**Step 1: Write the failing test.**

```python
def test_classify_done_is_pass():
    assert classify_failure(outcome="done", steps=12, history_summary="...") == "pass"

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
```

**Step 2-4: Run-fail, implement, run-pass.**

```python
# Add to run_log.py
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
```

The classifier is deliberately thin at this stage — categories that need post-action probes (overlay-noise, cart-verification-blocked) come online in Phases 1–3. Until then, the classifier is a passthrough on `outcome`.

**Step 5: Wire into `custom_agent.py`.**

```python
append_run(DEFAULT_LOG, {
    ...
    "category": classify_failure(outcome=outcome, steps=len(history)),
})
```

**Step 6: Commit.**

```bash
git add scripts/custom_agent/run_log.py scripts/custom_agent/test_run_log.py scripts/custom_agent.py
git commit -m "feat(harness): failure-category classifier on run logs"
```

---

### Task 0.4: Capture baseline (75 runs)

Now that the dispatcher is F-6-clean and the logger is wired, capture the baseline. **This is the calibration anchor for every claim downstream.**

**Files:** none touched — produces `data/runs.jsonl` rows + `data/screenshots/baseline/<model>__<task>__<run>.png`.

**Step 1: Write a baseline-runner shell script.**

```bash
# /tmp/baseline.sh
#!/usr/bin/env bash
set -u
set -o pipefail

MODELS=(ui-venus-1.5-8b mai-ui-8b ui-venus-1.5-30b-a3b bu-30b-a3b-preview holo3-35b-a3b)
TASKS=(saucedemo_full_checkout saucedemo_backpack_only ikea_search_add ikea_billy bestbuy_airpods)
RUNS=3
OUTDIR=/home/seans/Source/vision-model/data/screenshots/baseline
mkdir -p "$OUTDIR"

for model in "${MODELS[@]}"; do
  echo "=== swap to $model ==="
  sudo bash /home/seans/Source/vision-model/scripts/swap_model.sh "$model" || { echo "swap failed; skipping $model"; continue; }
  for task in "${TASKS[@]}"; do
    for run in $(seq 1 "$RUNS"); do
      tag="${model}__${task}__r${run}"
      echo "--- $tag ---"
      MODEL="$model" DISPLAY=:0 XAUTHORITY=/run/user/1000/xauth_rVYaGJ XDG_RUNTIME_DIR=/run/user/1000 \
        timeout 600 .venv/bin/python -u /home/seans/Source/vision-model/scripts/custom_agent.py "$task" \
        > "/tmp/${tag}.log" 2>&1
      cp /tmp/custom_agent_final.png "${OUTDIR}/${tag}.png" 2>/dev/null || true
    done
  done
done
```

**Step 2: Run the baseline (background, ~4–6 hours).**

```bash
cd /home/seans/Source/vision-model
nohup bash /tmp/baseline.sh > /tmp/baseline_master.log 2>&1 &
```

Monitor with: `tail -f /tmp/baseline_master.log` and `wc -l data/runs.jsonl` (should reach 75).

**Step 3: Tabulate baseline pass rates.**

Quick analysis script (not committed — one-shot):

```bash
.venv/bin/python -c "
import json
from collections import Counter, defaultdict
rows = [json.loads(l) for l in open('data/runs.jsonl')]
by_cell = defaultdict(list)
for r in rows:
    by_cell[(r['model'], r['task'])].append(r['category'])
print(f'{\"model\":<25} {\"task\":<32} {\"pass\":>5} {\"runs\":>5}')
for (m, t), cats in sorted(by_cell.items()):
    p = sum(1 for c in cats if c == 'pass')
    print(f'{m:<25} {t:<32} {p:>5}/{len(cats):<5}')
"
```

**Step 4: Append a Phase 19 section to `docs/findings.md`** with the baseline table, dominant failure categories per cell, and any new failure modes that didn't fit existing categories.

**Step 5: Commit.**

```bash
git add data/runs.jsonl data/screenshots/baseline/ docs/findings.md
git commit -m "data(baseline): Phase 19 — 75-run baseline (5 models × 5 cart sites × n=3) post-F6 fix"
```

---

### Task 0.5: Spot-check baseline against scope assumptions

Before moving on: do the baseline numbers match the cliffs hypothesized in `docs/thesis.md`? If MAI-UI 8B is *worse* than UI-Venus 8B on Class B with n=3 (Phase 17 had it at 6/9 vs 4/9 strict at n=1), or if any model lands an unexpected 0/9 across all cart sites, surface that as a finding before continuing — it changes which priorities matter most.

**No code change.** Read the table; update `docs/thesis.md` "Frontier as currently known" with the n=3 cells; add hypothesis revisions to `docs/findings.md` Phase 19.

**Acceptance for Phase 0:**
- F-6 fix passes its tests + `ikea_billy` reaches "Add to bag" on UI-Venus 8B.
- `data/runs.jsonl` has ≥70 rows (75 minus tolerated `dispatch_hang` from F-5).
- Per-cell pass rates documented in `docs/findings.md` Phase 19.
- Frontier table in `docs/thesis.md` updated for the 5×5 cells covered.

---

## Phase 1: Priority 1 — Cart state verification

The doc's highest-impact priority. Add a deterministic post-action `verify_cart_state(page, site_config)` probe; surface its output in the next-turn `previous_actions` block so the model has an authoritative cart-state signal independent of the screenshot.

**Insertion point:** new `scripts/custom_agent/cart_state.py`; called from `scripts/custom_agent.py:166-174` (between `dispatch()` and `await page.wait_for_load()`); rendered in `scripts/custom_agent/model.py:178-200` `prev` block.

### Task 1.1: Per-site cart-state config registry

**Files:**
- Create: `scripts/custom_agent/site_configs/__init__.py`
- Create: `scripts/custom_agent/site_configs/saucedemo.py`
- Create: `scripts/custom_agent/site_configs/ikea.py`
- Create: `scripts/custom_agent/site_configs/bestbuy.py`
- Create: `scripts/custom_agent/site_configs/_default.py` (heuristic fallback)
- Test: `scripts/custom_agent/test_site_configs.py`

**Step 1: Failing test.**

```python
def test_match_site_config_by_url():
    cfg = match_site_config("https://www.saucedemo.com/inventory.html")
    assert cfg.name == "saucedemo"

def test_unknown_url_falls_back_to_default():
    cfg = match_site_config("https://example.com/xyz")
    assert cfg.name == "_default"
```

**Step 2: Run-fail.**

**Step 3: Implement.**

```python
# scripts/custom_agent/site_configs/__init__.py
from __future__ import annotations
from dataclasses import dataclass, field
from urllib.parse import urlparse


@dataclass
class SiteConfig:
    name: str
    host_patterns: tuple[str, ...]
    cart_storage_keys: tuple[str, ...] = ()
    cart_count_selectors: tuple[str, ...] = ()
    cart_api: str | None = None  # GET path, JSONPath-ish for count


# Registry built lazily so adding a new site is one file under site_configs/.
def _all_configs() -> list[SiteConfig]:
    from . import saucedemo, ikea, bestbuy, _default
    return [m.CONFIG for m in (saucedemo, ikea, bestbuy)] + [_default.CONFIG]


def match_site_config(url: str) -> SiteConfig:
    host = (urlparse(url).hostname or "").lower()
    for cfg in _all_configs():
        if any(p in host for p in cfg.host_patterns):
            return cfg
    return _all_configs()[-1]  # _default
```

Per-site files (filled with the keys/selectors observed on each):

```python
# saucedemo.py
from . import SiteConfig
CONFIG = SiteConfig(
    name="saucedemo",
    host_patterns=("saucedemo.com",),
    cart_storage_keys=("cart-contents",),
    cart_count_selectors=(".shopping_cart_badge",),
)

# ikea.py
CONFIG = SiteConfig(
    name="ikea",
    host_patterns=("ikea.com",),
    cart_storage_keys=("ikea-cart", "shoppingBag"),
    cart_count_selectors=("[data-tracking-label='shoppingBag'] .hnf-badge", "[data-cart-count]"),
)

# bestbuy.py
CONFIG = SiteConfig(
    name="bestbuy",
    host_patterns=("bestbuy.com",),
    cart_storage_keys=("cart", "BBYCart"),
    cart_count_selectors=(".cart-icon-count", "[data-track='cartIcon'] .count"),
)

# _default.py — heuristics that work on any cart site
CONFIG = SiteConfig(
    name="_default",
    host_patterns=(),
    cart_storage_keys=("cart", "shopping_cart", "basket", "bag"),
    cart_count_selectors=(
        "[class*='cart-count']",
        "[data-cart-count]",
        "[aria-label*='cart' i]",
        "[class*='basket']",
    ),
)
```

The selectors above are *seed values*; they will be refined by per-site testing in Task 1.4. **Don't over-tune them now** — let the smoke runs surface what actually works.

**Step 4-5: Run-pass, commit.**

---

### Task 1.2: `verify_cart_state` probe

**Files:**
- Create: `scripts/custom_agent/cart_state.py`
- Test: `scripts/custom_agent/test_cart_state.py`

**Step 1: Failing test (with mocked CDP page).**

```python
import asyncio
from unittest.mock import AsyncMock, MagicMock
from scripts.custom_agent.cart_state import verify_cart_state, CartState
from scripts.custom_agent.site_configs.saucedemo import CONFIG as SAUCEDEMO


def test_localStorage_strategy_returns_count_and_method():
    page = MagicMock()
    page.session_id = "sid"
    page.client = MagicMock()
    # Mock Runtime.evaluate to return a JSON-encoded saucedemo cart
    async def send_raw(method, params, session_id=None):
        if "localStorage" in params.get("expression", ""):
            return {"result": {"value": '["sauce-labs-backpack","sauce-labs-bike-light"]'}}
        return {"result": {"value": None}}
    page.client.send_raw = AsyncMock(side_effect=send_raw)

    state = asyncio.run(verify_cart_state(page, SAUCEDEMO, "https://www.saucedemo.com/inventory.html"))
    assert state.cart_items == 2
    assert state.confidence == "high"
    assert state.verification_method == "localStorage"


def test_no_signals_returns_none_method_and_low_confidence():
    page = MagicMock()
    page.session_id = "sid"
    page.client = MagicMock()
    async def send_raw(method, params, session_id=None):
        return {"result": {"value": None}}
    page.client.send_raw = AsyncMock(side_effect=send_raw)
    from scripts.custom_agent.site_configs._default import CONFIG as DEF
    state = asyncio.run(verify_cart_state(page, DEF, "https://unknown.example/"))
    assert state.cart_items is None
    assert state.confidence == "low"
    assert state.verification_method == "none"


def test_dom_strategy_used_when_localStorage_empty():
    page = MagicMock()
    page.session_id = "sid"
    page.client = MagicMock()
    async def send_raw(method, params, session_id=None):
        e = params.get("expression", "")
        if "localStorage" in e:
            return {"result": {"value": None}}
        if "querySelector" in e:
            return {"result": {"value": "3"}}
        return {"result": {"value": None}}
    page.client.send_raw = AsyncMock(side_effect=send_raw)
    state = asyncio.run(verify_cart_state(page, SAUCEDEMO, "https://www.saucedemo.com/inventory.html"))
    assert state.cart_items == 3
    assert state.verification_method == "dom"
    assert state.confidence == "medium"
```

**Step 2: Run-fail.**

**Step 3: Implement.**

```python
# scripts/custom_agent/cart_state.py
"""Deterministic cart-state probe.

Strategies (in priority order):
  1. localStorage / sessionStorage — most reliable when the site uses it
  2. cart-count DOM selectors — works on most ecommerce sites
  3. (optional, future) GET /cart or /api/cart — only when a JSON endpoint
     is known and idempotent

Returns a CartState with verification_method recorded so callers (and the
model, via the previous_actions block) can judge confidence.
"""
from __future__ import annotations
import json
import time
from dataclasses import dataclass
from typing import Optional

from scripts.custom_agent.browser import Page
from scripts.custom_agent.site_configs import SiteConfig


@dataclass
class CartState:
    cart_items: Optional[int]
    confidence: str  # "high" | "medium" | "low"
    verification_method: str  # "localStorage" | "dom" | "api" | "none"
    raw: Optional[str] = None
    elapsed_ms: int = 0


async def verify_cart_state(page: Page, cfg: SiteConfig, url: str) -> CartState:
    t0 = time.time()
    # Strategy 1: localStorage / sessionStorage
    if cfg.cart_storage_keys:
        keys_js = json.dumps(list(cfg.cart_storage_keys))
        expr = (
            f"(()=>{{const keys={keys_js};"
            "for(const k of keys){"
            "const v=localStorage.getItem(k)||sessionStorage.getItem(k);"
            "if(v)return v;}return null;}})()"
        )
        r = await page.client.send_raw(
            "Runtime.evaluate", {"expression": expr, "returnByValue": True},
            session_id=page.session_id,
        )
        raw = r["result"].get("value")
        if raw:
            count = _count_from_storage(raw)
            return CartState(count, "high", "localStorage", raw=str(raw)[:200],
                             elapsed_ms=int((time.time() - t0) * 1000))

    # Strategy 2: DOM cart-count selectors
    if cfg.cart_count_selectors:
        sel_js = json.dumps(list(cfg.cart_count_selectors))
        expr = (
            f"(()=>{{const sels={sel_js};"
            "for(const s of sels){const e=document.querySelector(s);"
            "if(e&&e.textContent){const n=parseInt(e.textContent.trim(),10);"
            "if(!isNaN(n))return String(n);}}return null;}})()"
        )
        r = await page.client.send_raw(
            "Runtime.evaluate", {"expression": expr, "returnByValue": True},
            session_id=page.session_id,
        )
        raw = r["result"].get("value")
        if raw is not None:
            return CartState(int(raw), "medium", "dom", raw=str(raw),
                             elapsed_ms=int((time.time() - t0) * 1000))

    return CartState(None, "low", "none",
                     elapsed_ms=int((time.time() - t0) * 1000))


def _count_from_storage(raw: str | int | list | dict) -> int | None:
    """Heuristic: parse common cart shapes."""
    if isinstance(raw, int):
        return raw
    if isinstance(raw, list):
        return len(raw)
    if isinstance(raw, dict):
        for k in ("count", "items", "lines", "products"):
            if k in raw:
                v = raw[k]
                if isinstance(v, int): return v
                if isinstance(v, list): return len(v)
        return None
    if isinstance(raw, str):
        s = raw.strip()
        if not s: return None
        try:
            return _count_from_storage(json.loads(s))
        except json.JSONDecodeError:
            return None
    return None
```

**Step 4: Run-pass.**

Run: `.venv/bin/python -m pytest scripts/custom_agent/test_cart_state.py -v`
Expected: all 3 PASS.

**Step 5: Commit.**

---

### Task 1.3: Wire `verify_cart_state` into the run loop

**Files:**
- Modify: `scripts/custom_agent.py` (call after `dispatch()`)
- Modify: `scripts/custom_agent/model.py` (render in `prev`)
- Modify: `scripts/custom_agent/model.py` (extend `Action` with `cart_after` field)

**Step 1: Failing integration test.**

```python
# scripts/custom_agent/test_cart_in_history.py
from scripts.custom_agent.model import Action, _render_history_block
from scripts.custom_agent.cart_state import CartState


def test_cart_state_renders_in_history_block():
    a = Action(kind="click", raw="Click(box=(500,400))", conclusion="add to cart")
    a.cart_after = CartState(cart_items=1, confidence="high", verification_method="localStorage", raw="[\"backpack\"]", elapsed_ms=12)
    out = _render_history_block([a])
    assert "cart=1" in out
    assert "verification_method=localStorage" in out
```

**Step 2-4: Run-fail, implement, run-pass.**

In `scripts/custom_agent/model.py`:
1. Add `cart_after: object | None = None` to `Action`.
2. Extract the prev-rendering logic into a `_render_history_block(history)` function (it's currently inlined in `step()`).
3. In the per-step formatter, append `[cart={state.cart_items}, m={state.verification_method}]` when `cart_after` is set and not `verification_method=='none'`.

In `scripts/custom_agent.py`, after `await page.wait_for_load()`:

```python
# Cart-state probe (Phase 1). Cheap (~10-30ms) so runs every step; the
# prev-block only renders it when the verification method is non-trivial,
# so noise is automatic.
from scripts.custom_agent.cart_state import verify_cart_state
from scripts.custom_agent.site_configs import match_site_config

current_url = post_url(page)  # need a tiny helper to read location.href
site_cfg = match_site_config(current_url)
action.cart_after = await verify_cart_state(page, site_cfg, current_url)
```

(The `post_url` helper is one CDP `Runtime.evaluate` for `location.href` — add to `browser.py:Page` as `async def url(self) -> str`.)

**Step 5: Commit.**

```bash
git add scripts/custom_agent/cart_state.py scripts/custom_agent/site_configs/ \
  scripts/custom_agent/test_cart_state.py scripts/custom_agent/test_site_configs.py \
  scripts/custom_agent/test_cart_in_history.py \
  scripts/custom_agent/model.py scripts/custom_agent.py scripts/custom_agent/browser.py
git commit -m "feat(harness): Priority 1 — verify_cart_state post-action probe"
```

---

### Task 1.4: Per-site selector calibration via single-model dry run

The selectors in Task 1.1 are seed values. Validate them by running each of the 5 cart smokes once on UI-Venus-1.5-8B post-Task-1.3 and inspecting the `cart=...` lines in the per-step logs. Refine any selector that consistently returns `verification_method=none` past the point where the agent has clearly added to cart (per the verification screenshot).

**No code change unless a selector misses on a site.** Outcome: each of saucedemo / ikea / bestbuy returns `verification_method ∈ {localStorage, dom}` post-cart-action ≥80% of steps.

**Acceptance for Task 1.4:**
- Per-site smoke logs show `cart=N` (non-null) on the post-cart steps.
- Where a selector misses, the per-site config file has been updated and the smoke re-run shows non-null.

---

### Task 1.5: Re-measure (75 runs)

Re-run the baseline harness with cart-state injected. Same script as Task 0.4, but rows now have `verification_method` and `cart_items` populated.

**Files:** none — produces new `data/runs.jsonl` rows tagged `phase: "phase1_cartverify"`.

Add a `phase` label to `append_run()` (passed in via env var or a constant in `custom_agent.py`).

**Step 1-3: same shape as Task 0.4** — Run, tabulate, append a Phase 19/Priority-1 section to `docs/findings.md` with the n=3 deltas vs. baseline.

**Step 4: Commit.**

```bash
git add data/runs.jsonl docs/findings.md
git commit -m "data(phase1): re-measure post-cart-verification — N runs, deltas vs. baseline"
```

**Acceptance for Phase 1:**
- Cart-state lines visible in 100% of post-cart-action steps on saucedemo, ikea, bestbuy.
- Aggregate pass rate vs. baseline measured. **Document the actual delta** — even if it's smaller than the doc's hypothesized 50% → 70-80%, that's a useful signal toward "model-capability-bound" hypothesis.
- `docs/findings.md` Phase 19/Priority-1 section appended with per-cell pass-rate table.

---

## Phase 2: Priority 2 — Pre-flight DOM cleanup *(stub — expand after Phase 1 measurement)*

**Goal:** Dismiss cookie banners, newsletter modals, chat widgets, notification prompts before the model sees the first screenshot.

**Insertion point:** `scripts/custom_agent.py` after `await page.goto(task_module.START_URL)` and before the screenshot loop.

**Key questions to resolve when expanding:**
- Selector list source: pull from uBlock Origin's annoyances list as a starting point, but freeze it at a specific commit so we don't get drift between runs.
- Per-site override: some sites need the modal kept (none in current 5, but design the hook anyway).
- Logging: which dismissals fired, on which selectors. (One JSONL line per page-load event.)

**Don't expand until** Phase 1's re-measurement is in `docs/findings.md` — modal noise might be smaller than expected once cart-state stops absorbing the model's attention.

---

## Phase 3: Priority 4 — Loop-detection upgrade *(stub)*

**Goal:** Replace the existing 5-no-effect early-out (`scripts/custom_agent.py:184-201`) with a re-plan injection: surface a structured "you appear stuck — restate the goal and try a different approach" message in the next-turn prompt before bailing.

**Why before Priority 3 (mid-task overlays):** the doc itself recommends this order ("quick win, prevents wasted compute"). The current early-out terminates the run; a re-plan keeps it alive for ~3 more steps before bailing.

**Notes for expansion:**
- The current `streak >= 5` is the natural gate — at `streak == 3`, inject the re-plan; at `streak == 5`, still bail (don't loop forever).
- Track loop-break events as a distinct `category` in run logs (Task 0.3 already supports new categories).
- The doc's hashing-by-`(action_type, target_element, surrounding_context)` is over-engineered for our case — `no_effect` already detects "page didn't change," which is the strict version of identical-action.

---

## Phase 4: Priority 3 — Mid-task overlay detection *(stub)*

**Goal:** Detect overlays appearing mid-task (exit-intent popups, timing-triggered modals) and dismiss them with model guidance.

**Key design call when expanding:**
- Heuristic for "new overlay": before/after diff of "elements with z-index > 9000 and position fixed/absolute and area > 25% viewport." Cheap, scriptable.
- Surface to model as a `[overlay_detected: type=newsletter_signup, dismiss_options=...]` line in `previous_actions`. Same insertion pattern as cart-state.
- 2-attempt fallback: harness force-removes via `element.remove()`. Logged as `auto_dismiss`.

---

## Phase 5: Priority 5 — Action receipts *(stub — biggest refactor; do last)*

**Goal:** Replace per-step terse stdout (`[step N] click ...`) with structured receipts: target description, executed coords, actual element clicked, URL before/after, DOM-diff summary, network activity, duration.

Most of the inputs already exist:
- `pre`/`post` `_input_probe` (URL change, click counter)
- DOM diff: extend the existing `pre_hash != post_hash` check to a `domDiffSummary` (list newly-added node summaries)
- Network: enable `Network.enable` and capture `Network.requestWillBeSent` + `Network.responseReceived` for the action window

**Why last:** biggest refactor surface; smaller refactors (Phases 1-4) might already close the gap, in which case this stays at the rough cost-benefit threshold.

---

## Phase 6: Frontier API ceiling *(once, at the end)*

Run the same 5 cart smokes against Claude Sonnet 4.6 computer-use, n=3 each, using **Anthropic's reference computer-use scaffolding** (per `docs/backlog.md` E-9). Compute $/successful-task and add a "Frontier-API baseline" section to `docs/thesis.md`. This is the upper bound for the harness.

**Out of scope of this plan** — file as a follow-up issue (`E-9`) once Phases 0–5 are landed.

---

## Out of scope (per the doc)

- Fine-tuning models on task-specific data.
- Set-of-Mark visual grounding aids.
- Multi-tab / multi-window scenarios.
- Authenticated / checkout-beyond-add-to-cart flows.
- Captcha handling.
- F-5 (UI-Venus-30B-A3B Best Buy hang) is a known dispatch-side bug; runs are tagged `dispatch_hang` and excluded from pass-rate denominators. Filed; not blocking.

---

## Order of operations summary

1. Task 0.0 — confirm scope assumptions
2. Tasks 0.1–0.3 — F-6 fix, run logger, classifier
3. Task 0.4 — capture baseline (75 runs, ~4–6 hours)
4. Task 0.5 — analyze baseline; revise plan if surprising
5. Tasks 1.1–1.4 — Priority 1 cart verification + selector calibration
6. Task 1.5 — re-measure (75 runs)
7. **Pause**, expand Phase 2 plan based on what Phase 1 changed
8. Phase 2 (Priority 2 preflight cleanup) → re-measure
9. Phase 3 (Priority 4 loop upgrade) → re-measure
10. Phase 4 (Priority 3 mid-task overlay) → re-measure
11. Phase 5 (Priority 5 action receipts) → re-measure
12. Phase 6 (frontier ceiling, once)
