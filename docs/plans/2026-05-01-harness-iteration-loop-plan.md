# Harness Iteration Loop Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a 7-test regression suite for the custom CDP harness plus a 20-iteration autonomous loop driven by `claude --print` (Max subscription) that proposes one harness change per iteration and lets a deterministic driver decide commit-or-revert based on suite delta.

**Architecture:** Three layers. (1) Suite wrapper `scripts/regression_suite.py` runs four pytest unit tests (regression locks for the four documented historical bugs), one mechanical CDP probe (`scripts/saucedemo_flow_probe.py`), and two end-to-end agent runs (saucedemo full checkout, IKEA BILLY) and emits a JSON report. (2) Iteration driver `scripts/iteration_step.py` compares before/after suite JSON, owns the commit/revert decision, and appends a `learnings.md` block per iteration. (3) Orchestrator `scripts/iteration_loop.sh` runs in a git worktree on a `harness-loop/<ts>` branch, spawning one `claude --print` subprocess per iteration with a restricted tool whitelist and rendered prompts.

**Tech Stack:** Python 3.14 + pytest, bash, `claude` CLI in headless mode (`--print --output-format json --allowed-tools ...`), git worktree for branch isolation.

**Reference docs:**
- Design: `docs/plans/2026-05-01-harness-iteration-loop-design.md`
- Findings: `docs/findings.md` (sections on F-7, double-remap, scroll clamp at L2549, iframe skip at L2553)
- Project rules: `CLAUDE.md` (display env vars, smoke-run conventions)

---

## Pre-flight

Run these once before starting:

```bash
.venv/bin/python -c "import pytest; print(pytest.__version__)"
which claude && claude --version   # verify CLI on PATH and Max-authenticated
git status                         # working tree should be clean before Task 1
mkdir -p tests/regression          # placeholder for Phase 1 tests
```

If any fails: stop, surface the gap. Do not proceed.

---

## Phase 1: Regression-lock unit tests

Each of these is a tight pytest module under `tests/regression/`. The fixes are already in place, so the test should pass on first run. The task in each case is: write the test, prove it captures the invariant by running it, then prove it would catch a regression by toggling the relevant constant or branch in a quick scratch experiment (do **not** commit the toggle — just verify the test fails when the fix is reverted, then restore).

### Task 1: Regression lock — wrong quant default (F-7)

**Files:**
- Create: `tests/regression/__init__.py` (empty)
- Create: `tests/regression/test_swap_model_quant_defaults.py`
- Reference: `scripts/swap_model.sh:21-64`

**Step 1: Write the failing test**

```python
"""Regression lock for F-7: swap_model.sh per-model quant defaults.

Phase 19 baseline failed because swap_quant.sh's script-wide Q6_K default
didn't exist for 30B-A3B class models — the gguf-existence check exited 1
without ever touching systemd. Fix: per-model `QUANT="${2:-…}"` overrides
in swap_model.sh's `case` block. Test pins those defaults so a refactor
that drops them fails loudly.
"""
from __future__ import annotations
import re
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "swap_model.sh"
EXPECTED_DEFAULTS = {
    "ui-venus-1.5-8b":      "Q6_K",      # script-wide default
    "mai-ui-8b":            "Q6_K",      # script-wide default
    "ui-venus-1.5-30b-a3b": "Q3_K_M",
    "bu-30b-a3b-preview":   "Q3_K_M",
    "holo3-35b-a3b":        "IQ3_XXS",
}


def _parse_per_model_overrides(text: str) -> dict[str, str]:
    """Return {model_name: per-model quant default} for cases that override
    QUANT, falling back to the top-level QUANT="${2:-Q6_K}" default for the
    rest."""
    top_default_match = re.search(r'^QUANT="\$\{2:-([A-Z0-9_]+)\}"', text, re.M)
    assert top_default_match, "top-level QUANT default not found in swap_model.sh"
    top_default = top_default_match.group(1)

    out: dict[str, str] = {}
    case_block = re.search(r"case \"\$MODEL\" in\n(.+?)\n\s*esac", text, re.S)
    assert case_block, "case block not found in swap_model.sh"
    for arm in re.finditer(
        r"\n\s*([a-z0-9.\-]+)\)\n(.+?);;",
        "\n" + case_block.group(1),
        re.S,
    ):
        name, body = arm.group(1), arm.group(2)
        if name == "*":
            continue
        per_model = re.search(r'QUANT="\$\{2:-([A-Z0-9_]+)\}"', body)
        out[name] = per_model.group(1) if per_model else top_default
    return out


def test_per_model_quant_defaults_match_expected():
    text = SCRIPT.read_text()
    defaults = _parse_per_model_overrides(text)
    assert defaults == EXPECTED_DEFAULTS, (
        f"swap_model.sh per-model quant defaults drifted.\n"
        f"  expected: {EXPECTED_DEFAULTS}\n"
        f"  got:      {defaults}"
    )
```

**Step 2: Run test to verify it passes (fix is in place)**

Run: `.venv/bin/python -m pytest tests/regression/test_swap_model_quant_defaults.py -v`
Expected: 1 passed

**Step 3: Verify the test would catch a regression**

Manually flip `QUANT="${2:-Q3_K_M}"` to `QUANT="${2:-Q6_K}"` inside the `holo3-35b-a3b)` arm of `scripts/swap_model.sh`. Re-run the test.
Expected: FAIL with the dict diff message.
Then `git checkout -- scripts/swap_model.sh` to restore.

**Step 4: Commit**

```bash
git add tests/regression/__init__.py tests/regression/test_swap_model_quant_defaults.py
git commit -m "test(regression): lock per-model quant defaults in swap_model.sh (F-7)"
```

---

### Task 2: Regression lock — coordinate double-remap (Holo3 click_at)

**Files:**
- Create: `tests/regression/test_action_kind_coord_space.py`
- Reference: `scripts/custom_agent/actions.py:18-54`

**Step 1: Write the failing test**

```python
"""Regression lock for the coord double-remap bug.

The R1 / Phase 14 bug: Holo3 emits viewport-pixel click coords (its own
localizer rescales). The dispatcher was passing those through
`grounding_remap`, which assumes 0-1000 normalized coords, sending the
click 50-200px off-target. Fix: split `kind="click"` (UI-Venus norm,
remap) from `kind="click_at"` / `kind="click_then_type"` (Holo3 viewport
pixels, no remap). Test pins both branches.
"""
from __future__ import annotations
import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.custom_agent.actions import dispatch
from scripts.custom_agent.model import Action

VIEWPORT = (1280, 800)


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_click_kind_applies_grounding_remap():
    """UI-Venus 'click' coords are 0-1000 normalized → must be remapped."""
    action = Action(kind="click", xy=(500, 500), raw="click(point=(500,500))")
    page = object()  # never touched; _click is mocked
    with patch("scripts.custom_agent.actions._click", new=AsyncMock()) as mck:
        _run(dispatch(page, action, VIEWPORT))
        assert mck.await_count == 1
        _, x, y = mck.await_args.args
        # grounding_remap((500,500), (1280,800)) → (640, 400)
        assert (x, y) == (640, 400), (
            f"'click' kind must go through grounding_remap; got ({x},{y}) "
            f"— a regression to the double-remap bug or a remap removal."
        )


def test_click_at_kind_bypasses_grounding_remap():
    """Holo3 'click_at' coords are viewport pixels → must NOT be remapped."""
    action = Action(kind="click_at", xy=(640, 400), raw="click_element(640,400)")
    page = object()
    with patch("scripts.custom_agent.actions._click", new=AsyncMock()) as mck:
        _run(dispatch(page, action, VIEWPORT))
        assert mck.await_count == 1
        _, x, y = mck.await_args.args
        assert (x, y) == (640, 400), (
            f"'click_at' kind must bypass grounding_remap (Holo3 already "
            f"emits viewport-pixel coords); got ({x},{y}). "
            f"This is the double-remap bug — see findings.md L1551."
        )


def test_click_then_type_bypasses_grounding_remap():
    """Holo3 'click_then_type' compounds click+type; click coords still raw."""
    action = Action(kind="click_then_type", xy=(640, 400), text="hello",
                    raw="write_element(640,400,'hello')")
    page = object()
    with patch("scripts.custom_agent.actions._click", new=AsyncMock()) as mck_click, \
         patch("scripts.custom_agent.actions._type_keys", new=AsyncMock()):
        _run(dispatch(page, action, VIEWPORT))
        _, x, y = mck_click.await_args.args
        assert (x, y) == (640, 400), \
            f"'click_then_type' must bypass remap (same reason as click_at); got ({x},{y})"
```

**Step 2: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/regression/test_action_kind_coord_space.py -v`
Expected: 3 passed

**Step 3: Verify it catches a regression**

Manually edit `scripts/custom_agent/actions.py:28-32` so the `click_at` branch reads `x, y = remap(action.xy, viewport_css); await _click(page, x, y)`. Re-run.
Expected: `test_click_at_kind_bypasses_grounding_remap` FAILS. Restore via `git checkout -- scripts/custom_agent/actions.py`.

**Step 4: Commit**

```bash
git add tests/regression/test_action_kind_coord_space.py
git commit -m "test(regression): lock per-action-kind coord-space convention (Holo3 double-remap)"
```

---

### Task 3: Regression lock — `_MIN_SCROLL_DELTA` clamp

**Files:**
- Create: `tests/regression/test_scroll_min_delta.py`
- Reference: `scripts/custom_agent/actions.py:404-435`

**Step 1: Write the failing test**

```python
"""Regression lock for Phase 18 scroll-clamp fix.

Best Buy AirPods Pro 3 Add-to-Cart sits ~2500-3500px down a long PDP. The
model's start->end coords typically span 250-300px. Without the clamp,
the agent burned its step budget at 254px/scroll. Fix: floor the magnitude
at _MIN_SCROLL_DELTA = 600 while preserving direction sign.
"""
from __future__ import annotations
import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.custom_agent.actions import _scroll, _MIN_SCROLL_DELTA
from scripts.custom_agent.model import Action

VIEWPORT = (1280, 800)


def test_min_scroll_delta_constant():
    assert _MIN_SCROLL_DELTA >= 600, (
        f"_MIN_SCROLL_DELTA dropped below 600 (got {_MIN_SCROLL_DELTA}). "
        f"Phase 18 found 600 was the floor that kept BestBuy AirPods PDP "
        f"reachable in the step budget."
    )


def _make_page_with_dispatch_capture():
    """Returns (page, captured_calls). page.client.send_raw is an AsyncMock
    that records each invocation."""
    page = MagicMock()
    page.session_id = "x"
    page.client.send_raw = AsyncMock(return_value={"result": {"value": {"clicks": 0, "keys": 0, "url": "http://x"}}})
    return page, page.client.send_raw


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_small_span_clamped_to_floor_down():
    """start (640, 400) → end (640, 650) is a 250px-down span; deltaY must
    be clamped to _MIN_SCROLL_DELTA, sign negative-to-positive preserved."""
    action = Action(kind="scroll", start_xy=(500, 500), end_xy=(500, 813),  # 250px in viewport-px after remap
                    raw="scroll(start=(500,500),end=(500,813))")
    page, send_raw = _make_page_with_dispatch_capture()
    # Stub the helpers _scroll uses internally
    with patch("scripts.custom_agent.actions._input_probe", new=AsyncMock(return_value={"clicks": 0, "keys": 0, "url": "http://x"})), \
         patch("scripts.custom_agent.actions._scroll_y", new=AsyncMock(return_value=0)), \
         patch("scripts.custom_agent.actions._scroll_layout_probe", new=AsyncMock(return_value={"docH": 5000, "innerH": 800})):
        _run(_scroll(page, action, VIEWPORT))

    wheel_calls = [c for c in send_raw.await_args_list
                   if c.args[0] == "Input.dispatchMouseEvent"
                   and c.args[1].get("type") == "mouseWheel"]
    assert wheel_calls, "expected at least one mouseWheel dispatch"
    dy = wheel_calls[0].args[1]["deltaY"]
    assert abs(dy) >= _MIN_SCROLL_DELTA, (
        f"deltaY={dy} not clamped to floor {_MIN_SCROLL_DELTA}. "
        f"Phase 18 regression."
    )
    assert dy > 0, f"sign must be preserved (down→positive); got {dy}"


def test_direction_only_uses_floor_magnitude():
    """direction='down' with no start/end → must produce a wheel dispatch
    with magnitude == _MIN_SCROLL_DELTA, sign negative (down = viewport
    moves down = content scrolls up = negative deltaY in F-6 convention
    inversion → actually NEGATIVE per actions.py:429)."""
    action = Action(kind="scroll", direction="down", raw="scroll('down')")
    page, send_raw = _make_page_with_dispatch_capture()
    with patch("scripts.custom_agent.actions._input_probe", new=AsyncMock(return_value={"clicks": 0, "keys": 0, "url": "http://x"})), \
         patch("scripts.custom_agent.actions._scroll_y", new=AsyncMock(return_value=0)), \
         patch("scripts.custom_agent.actions._scroll_layout_probe", new=AsyncMock(return_value={"docH": 5000, "innerH": 800})):
        _run(_scroll(page, action, VIEWPORT))

    wheel_calls = [c for c in send_raw.await_args_list
                   if c.args[0] == "Input.dispatchMouseEvent"
                   and c.args[1].get("type") == "mouseWheel"]
    dy = wheel_calls[0].args[1]["deltaY"]
    assert abs(dy) == _MIN_SCROLL_DELTA
    assert dy < 0, f"direction='down' must produce negative deltaY (F-6 convention); got {dy}"
```

**Step 2: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/regression/test_scroll_min_delta.py -v`
Expected: 3 passed

**Step 3: Verify regression catch**

Temporarily set `_MIN_SCROLL_DELTA = 100` in `scripts/custom_agent/actions.py:404`. Re-run.
Expected: `test_min_scroll_delta_constant` and `test_small_span_clamped_to_floor_down` FAIL.
Restore.

**Step 4: Commit**

```bash
git add tests/regression/test_scroll_min_delta.py
git commit -m "test(regression): lock _MIN_SCROLL_DELTA scroll-clamp invariant (Phase 18)"
```

---

### Task 4: Regression lock — iframe skip in JS click fallback

**Files:**
- Create: `tests/regression/test_js_click_iframe_skip.py`
- Reference: `scripts/custom_agent/actions.py:121-157`

This test asserts the *generated JS string* contains the iframe-filter logic, since exercising it for real requires a browser. That's a deliberate trade — we lose end-to-end coverage but get a stable, fast lock against accidental string-edit regressions.

**Step 1: Write the test**

```python
"""Regression lock for the iframe-skip fix in _js_click_fallback.

Best Buy stacks invisible analytics iframes over interactive areas.
elementsFromPoint returned the IFRAME element first, and the JS
fallback's `IFRAME.click()` is a no-op (clicking the iframe wrapper
doesn't activate the document inside). Fix: filter IFRAMEs from the
elementsFromPoint stack at every layer.

We can't easily exercise the fallback without a real Chromium; instead,
we lock the JS template's filter clause so it can't drift via
string-edit regressions.
"""
from __future__ import annotations
import asyncio
import inspect
import re
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.custom_agent.actions import _js_click_fallback


def _captured_js_for_call(x: int, y: int) -> str:
    page = MagicMock()
    page.session_id = "x"
    page.client.send_raw = AsyncMock(
        return_value={"result": {"value": {"tag": "BUTTON", "skipped": 0}}}
    )
    asyncio.get_event_loop().run_until_complete(_js_click_fallback(page, x, y))
    return page.client.send_raw.await_args.args[1]["expression"]


def test_fallback_filters_iframe_from_elements_from_point():
    js = _captured_js_for_call(100, 200)
    # Must read the full stack (not just topmost), then filter IFRAMEs.
    assert "elementsFromPoint(100,200)" in js, "must use elementsFromPoint, not elementFromPoint"
    assert re.search(r"filter\s*\(\s*[a-z]\s*=>\s*[a-z]\.tagName\s*!==\s*['\"]IFRAME['\"]\s*\)", js), (
        "iframe filter clause missing from _js_click_fallback JS — Phase 18 regression"
    )
    # Must surface the count of skipped iframes for diagnostic logging.
    assert "skipped" in js, "must report `skipped` count for [skipped N iframe] log line"


def test_fallback_handles_iframe_only_stack():
    js = _captured_js_for_call(50, 50)
    # If post-filter list is empty, must return a {dropped:'iframe-only',...}
    # marker so the dispatcher logs the no-op rather than silently clicking.
    assert re.search(r"dropped\s*:\s*['\"]iframe-only['\"]", js), (
        "iframe-only stack handler missing — without it the fallback "
        "silently no-ops on Best Buy ad-frame stacks."
    )
```

**Step 2: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/regression/test_js_click_iframe_skip.py -v`
Expected: 2 passed

**Step 3: Verify regression catch**

Edit `scripts/custom_agent/actions.py:136` and remove `.filter(e=>e.tagName!=='IFRAME')` from the JS template (so `els` becomes `all`). Re-run.
Expected: `test_fallback_filters_iframe_from_elements_from_point` FAILS.
Restore.

**Step 4: Commit**

```bash
git add tests/regression/test_js_click_iframe_skip.py
git commit -m "test(regression): lock iframe-skip filter in _js_click_fallback (Phase 18)"
```

---

## Phase 2: Suite wrapper

### Task 5: Suite wrapper skeleton + JSON shape contract

**Files:**
- Create: `scripts/regression_suite.py`
- Create: `tests/regression/test_suite_wrapper.py`

**Step 1: Write the failing test for the JSON contract**

```python
"""Tests the regression_suite.py wrapper produces a stable JSON document
that the iteration driver can rely on. Tests the shape, not the values."""
from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_suite_wrapper_emits_valid_json_with_expected_keys(tmp_path):
    # --unit-only short-circuits the E2E + mechanical-probe runs so this
    # test is fast. Full mode is exercised end-to-end manually before Phase 4.
    proc = subprocess.run(
        [sys.executable, "-u", str(ROOT / "scripts" / "regression_suite.py"),
         "--unit-only", "--out", str(tmp_path / "suite.json")],
        capture_output=True, text=True,
    )
    assert proc.returncode in (0, 1), f"unexpected exit {proc.returncode}: {proc.stderr}"
    doc = json.loads((tmp_path / "suite.json").read_text())
    assert set(doc.keys()) >= {"all_green", "duration_s", "tests"}
    assert isinstance(doc["all_green"], bool)
    assert isinstance(doc["duration_s"], (int, float))
    expected_unit_keys = {
        "regression_quant_default",
        "regression_coord_remap",
        "regression_scroll_clamp",
        "regression_iframe_skip",
    }
    assert expected_unit_keys.issubset(doc["tests"].keys())
    for k, v in doc["tests"].items():
        assert {"pass", "duration_s", "log_excerpt"}.issubset(v.keys())
        assert isinstance(v["pass"], bool)
```

**Step 2: Run to verify it fails (script doesn't exist yet)**

Run: `.venv/bin/python -m pytest tests/regression/test_suite_wrapper.py -v`
Expected: FAIL — script not found.

**Step 3: Implement the wrapper (unit-only first; E2E in Task 6, 7)**

```python
"""Regression suite wrapper for the custom CDP harness.

Composes:
  - 4 unit-test regression locks under tests/regression/
  - 1 mechanical CDP probe (saucedemo_flow_probe.py)
  - 2 E2E custom-agent runs (saucedemo_full_checkout, ikea_billy)

Emits a JSON document the iteration_loop driver consumes:
  {
    "all_green": bool,
    "duration_s": float,
    "tests": {
      "<test_id>": {"pass": bool, "duration_s": float, "log_excerpt": str},
      ...
    }
  }

Per-test log files land in <log_dir>/<test_id>.log (default
/tmp/regression_suite/<run_id>/).

Run:
  .venv/bin/python -u scripts/regression_suite.py [--unit-only] [--out PATH] [--log-dir DIR]

Exit codes: 0 if all_green, 1 otherwise.
"""
from __future__ import annotations
import argparse
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

UNIT_TESTS = {
    "regression_quant_default":  "tests/regression/test_swap_model_quant_defaults.py",
    "regression_coord_remap":    "tests/regression/test_action_kind_coord_space.py",
    "regression_scroll_clamp":   "tests/regression/test_scroll_min_delta.py",
    "regression_iframe_skip":    "tests/regression/test_js_click_iframe_skip.py",
}


def _run_pytest(test_file: str, log_path: Path) -> tuple[bool, float]:
    t0 = time.time()
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", str(ROOT / test_file), "-v", "--tb=short"],
        capture_output=True, text=True, timeout=120,
    )
    dur = time.time() - t0
    log_path.write_text(proc.stdout + "\n--- STDERR ---\n" + proc.stderr)
    return proc.returncode == 0, dur


def _excerpt(log_path: Path, max_chars: int = 2000) -> str:
    try:
        text = log_path.read_text()
    except FileNotFoundError:
        return ""
    if len(text) <= max_chars:
        return text
    return text[:max_chars // 2] + "\n...[truncated]...\n" + text[-max_chars // 2:]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--unit-only", action="store_true")
    parser.add_argument("--out", default=None, help="JSON output path; default stdout")
    parser.add_argument("--log-dir", default=None)
    args = parser.parse_args()

    run_id = uuid.uuid4().hex[:8]
    log_dir = Path(args.log_dir) if args.log_dir else Path(f"/tmp/regression_suite/{run_id}")
    log_dir.mkdir(parents=True, exist_ok=True)

    results: dict[str, dict] = {}
    suite_t0 = time.time()

    for test_id, rel_path in UNIT_TESTS.items():
        log_path = log_dir / f"{test_id}.log"
        ok, dur = _run_pytest(rel_path, log_path)
        results[test_id] = {
            "pass": ok,
            "duration_s": round(dur, 2),
            "log_excerpt": _excerpt(log_path),
        }

    # Phase 2 Task 6, 7 will plug mechanical probe + E2E here.
    if not args.unit_only:
        from scripts._regression_e2e import run_mechanical_probe, run_saucedemo_e2e, run_billy_e2e  # type: ignore
        for fn, key in [(run_mechanical_probe, "saucedemo_probe"),
                        (run_saucedemo_e2e,    "saucedemo_full_checkout"),
                        (run_billy_e2e,        "ikea_billy")]:
            log_path = log_dir / f"{key}.log"
            ok, dur = fn(log_path)
            results[key] = {"pass": ok, "duration_s": round(dur, 2),
                            "log_excerpt": _excerpt(log_path)}

    doc = {
        "all_green": all(r["pass"] for r in results.values()),
        "duration_s": round(time.time() - suite_t0, 2),
        "run_id": run_id,
        "log_dir": str(log_dir),
        "tests": results,
    }
    out_text = json.dumps(doc, indent=2)
    if args.out:
        Path(args.out).write_text(out_text)
    else:
        sys.stdout.write(out_text + "\n")
    return 0 if doc["all_green"] else 1


if __name__ == "__main__":
    sys.exit(main())
```

**Step 4: Run the suite-wrapper test to verify pass**

Run: `.venv/bin/python -m pytest tests/regression/test_suite_wrapper.py -v`
Expected: 1 passed.

Also run end-to-end once: `.venv/bin/python -u scripts/regression_suite.py --unit-only`
Expected: JSON doc on stdout, exit 0 (all four locks pass).

**Step 5: Commit**

```bash
git add scripts/regression_suite.py tests/regression/test_suite_wrapper.py
git commit -m "feat(regression): suite wrapper with --unit-only path + JSON contract"
```

---

### Task 6: Add mechanical CDP probe to the suite

**Files:**
- Create: `scripts/_regression_e2e.py`
- Reference: `scripts/saucedemo_flow_probe.py` (the script to invoke)

**Step 1: Implement `run_mechanical_probe`**

Edit `scripts/_regression_e2e.py`:

```python
"""E2E + mechanical-probe runners for regression_suite.py. Kept in a
separate module so importing the wrapper for unit-only mode does not
drag in browser/Chromium dependencies."""
from __future__ import annotations
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DISPLAY_ENV = {
    "DISPLAY": ":0",
    "XAUTHORITY": "/run/user/1000/xauth_rVYaGJ",
    "XDG_RUNTIME_DIR": "/run/user/1000",
    "PYTHONUNBUFFERED": "1",
}


def _venv_python() -> str:
    return str(ROOT / ".venv" / "bin" / "python")


def run_mechanical_probe(log_path: Path) -> tuple[bool, float]:
    """saucedemo_flow_probe walks CP1-CP9 with DOM-truth coords through the
    dispatcher. Pass = the script's last line says '9/9 checkpoints PASS'."""
    t0 = time.time()
    env = {**os.environ, **DISPLAY_ENV}
    proc = subprocess.run(
        [_venv_python(), "-u", str(ROOT / "scripts" / "saucedemo_flow_probe.py")],
        env=env, capture_output=True, text=True, timeout=180,
    )
    dur = time.time() - t0
    log_path.write_text(proc.stdout + "\n--- STDERR ---\n" + proc.stderr)
    last_lines = proc.stdout.strip().splitlines()[-5:]
    ok = any("9/9" in l and "PASS" in l for l in last_lines)
    return ok, dur


def run_saucedemo_e2e(log_path: Path) -> tuple[bool, float]:
    """Placeholder — implemented in Task 7."""
    raise NotImplementedError


def run_billy_e2e(log_path: Path) -> tuple[bool, float]:
    """Placeholder — implemented in Task 7."""
    raise NotImplementedError
```

**Step 2: Verify the probe runs and the parser works**

Run: `.venv/bin/python -c "from pathlib import Path; from scripts._regression_e2e import run_mechanical_probe; ok, dur = run_mechanical_probe(Path('/tmp/probe_check.log')); print(ok, dur)"`
Expected: `True <duration>` (dispatcher is currently 9/9).

**Step 3: Commit**

```bash
git add scripts/_regression_e2e.py
git commit -m "feat(regression): mechanical CDP probe runner"
```

---

### Task 7: Add E2E saucedemo + BILLY runners

**Files:**
- Modify: `scripts/_regression_e2e.py` (replace the two `NotImplementedError` stubs)

**Step 1: Implement both E2E runners**

The custom-agent CLI is `scripts/custom_agent.py <task_id>`. Each task module under `scripts/custom_agent_tasks/` exposes a TASK string and config; the agent prints structured run-log JSON. Pass = the run log's final action's `category == "pass"` (preferred) or `outcome ∈ {"done","call_user"}` (legacy).

```python
import json
import re

def _run_custom_agent(task: str, log_path: Path, timeout_s: int) -> tuple[bool, float]:
    t0 = time.time()
    env = {**os.environ, **DISPLAY_ENV, "MODEL": os.environ.get("MODEL", "ui-venus-1.5-8b")}
    proc = subprocess.run(
        [_venv_python(), "-u", str(ROOT / "scripts" / "custom_agent.py"), task],
        env=env, capture_output=True, text=True, timeout=timeout_s,
    )
    dur = time.time() - t0
    log_path.write_text(proc.stdout + "\n--- STDERR ---\n" + proc.stderr)
    return _parse_pass_from_runlog(proc.stdout), dur


def _parse_pass_from_runlog(stdout: str) -> bool:
    """Find the last JSON-shaped run-log block on stdout and apply the
    same pass rule as web/build_site._is_pass: category == 'pass' first,
    fallback to outcome in {done, call_user}."""
    matches = re.findall(r"\{[^{}]*\"outcome\"[^{}]*\}", stdout)
    if not matches:
        return False
    try:
        last = json.loads(matches[-1])
    except json.JSONDecodeError:
        return False
    if "category" in last:
        return last["category"] == "pass"
    return last.get("outcome") in ("done", "call_user")


def run_saucedemo_e2e(log_path: Path) -> tuple[bool, float]:
    return _run_custom_agent("saucedemo_full_checkout", log_path, timeout_s=600)


def run_billy_e2e(log_path: Path) -> tuple[bool, float]:
    return _run_custom_agent("ikea_billy", log_path, timeout_s=900)
```

**Step 2: Sanity-check the run-log parser with a synthetic stdout**

```bash
.venv/bin/python - <<'PY'
from scripts._regression_e2e import _parse_pass_from_runlog
assert _parse_pass_from_runlog('foo\n{"outcome":"done","category":"pass"}\nend') is True
assert _parse_pass_from_runlog('foo\n{"outcome":"abort","category":"fail_dispatcher"}\nend') is False
assert _parse_pass_from_runlog('foo\n{"outcome":"call_user"}\nend') is True
assert _parse_pass_from_runlog('no json here') is False
print("parser ok")
PY
```
Expected: `parser ok`.

**Step 3: One real saucedemo run as smoke (optional but recommended)**

This is the slow part (~3-5 min). Skip if you want to defer until full-suite validation in Task 13.

```bash
sudo systemctl status vision-model.service | head -1   # confirm running
.venv/bin/python -u scripts/regression_suite.py --out /tmp/suite_smoke.json
cat /tmp/suite_smoke.json | python -m json.tool | head -50
```

**Step 4: Commit**

```bash
git add scripts/_regression_e2e.py
git commit -m "feat(regression): E2E saucedemo + BILLY runners using custom-agent run-log"
```

---

## Phase 3: Iteration step (decision logic)

### Task 8: `iteration_step.py` skeleton + `strict_improvement`

**Files:**
- Create: `scripts/iteration_step.py`
- Create: `tests/regression/test_iteration_step.py`

**Step 1: Write the failing tests**

```python
from __future__ import annotations
from scripts.iteration_step import strict_improvement, format_suite_delta, render_learnings_block


def _doc(passes: dict[str, bool]) -> dict:
    return {
        "all_green": all(passes.values()),
        "duration_s": 1.0,
        "tests": {k: {"pass": v, "duration_s": 0.1, "log_excerpt": ""} for k, v in passes.items()},
    }


def test_strict_improvement_only_grows_passes():
    before = _doc({"a": False, "b": True})
    after_grew  = _doc({"a": True,  "b": True})
    after_same  = _doc({"a": False, "b": True})
    after_swap  = _doc({"a": True,  "b": False})
    after_lost  = _doc({"a": False, "b": False})
    assert strict_improvement(before, after_grew)  is True
    assert strict_improvement(before, after_same)  is False
    assert strict_improvement(before, after_swap)  is False  # introduces a new fail
    assert strict_improvement(before, after_lost)  is False


def test_strict_improvement_handles_new_test_keys():
    before = _doc({"a": True})
    after  = _doc({"a": True, "b": False})
    # Adding a new failing key is NOT progress.
    assert strict_improvement(before, after) is False


def test_format_suite_delta_renders_per_test_arrows():
    before = _doc({"a": False, "b": True})
    after  = _doc({"a": True, "b": True})
    delta = format_suite_delta(before, after)
    assert "a: fail → pass" in delta
    assert "b: pass → pass" in delta


def test_render_learnings_block_contains_required_sections():
    block = render_learnings_block(
        iteration=3,
        verdict="GREEN",
        hypothesis="bump scroll clamp",
        change_files=["scripts/custom_agent/actions.py"],
        suite_delta_text="ikea_billy: fail → pass",
        outcome_line="committed as abc1234",
        invalidates="iteration 1 hypothesis 'lower clamp' — opposite-direction fix on same lines",
    )
    assert "## Iteration 3" in block
    assert "GREEN" in block
    assert "bump scroll clamp" in block
    assert "scripts/custom_agent/actions.py" in block
    assert "ikea_billy: fail → pass" in block
    assert "abc1234" in block
    assert "iteration 1" in block.lower()
```

**Step 2: Verify they fail (module not found)**

Run: `.venv/bin/python -m pytest tests/regression/test_iteration_step.py -v`
Expected: ImportError / file-not-found.

**Step 3: Implement `iteration_step.py`**

```python
"""Iteration-loop decision logic. Pure functions exposed for unit testing;
CLI entry point at the bottom is invoked by iteration_loop.sh after each
claude --print call."""
from __future__ import annotations
import argparse
import datetime
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _passes(doc: dict) -> set[str]:
    return {k for k, v in doc["tests"].items() if v["pass"]}


def _fails(doc: dict) -> set[str]:
    return {k for k, v in doc["tests"].items() if not v["pass"]}


def strict_improvement(before: dict, after: dict) -> bool:
    """Return True iff after's pass-set strictly contains before's, AND
    after's fail-set is a subset of before's fail-set (no new fails)."""
    pb, pa = _passes(before), _passes(after)
    fb, fa = _fails(before),  _fails(after)
    return pa > pb and fa.issubset(fb)


def format_suite_delta(before: dict, after: dict) -> str:
    keys = sorted(set(before["tests"]) | set(after["tests"]))
    lines = []
    for k in keys:
        b = before["tests"].get(k, {}).get("pass")
        a = after["tests"].get(k, {}).get("pass")
        bs = "pass" if b else ("fail" if b is False else "absent")
        as_ = "pass" if a else ("fail" if a is False else "absent")
        lines.append(f"  - {k}: {bs} → {as_}")
    return "\n".join(lines)


def render_learnings_block(
    *, iteration: int, verdict: str, hypothesis: str,
    change_files: list[str], suite_delta_text: str,
    outcome_line: str, invalidates: str | None,
) -> str:
    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return (
        f"## Iteration {iteration} — {ts} — {verdict}\n\n"
        f"**Hypothesis**: {hypothesis}\n"
        f"**Change**: {', '.join(change_files) if change_files else '(none)'}\n"
        f"**Suite delta**:\n{suite_delta_text}\n"
        f"**Outcome**: {outcome_line}\n"
        f"**Invalidates**: {invalidates or '(none)'}\n"
    )


def _git(args: list[str], cwd: Path) -> str:
    return subprocess.check_output(["git", *args], cwd=cwd, text=True).strip()


def _decide_and_act(*, iteration: int, before_path: Path, after_path: Path,
                    transcript_path: Path, learnings_path: Path,
                    workdir: Path) -> str:
    before = json.loads(before_path.read_text())
    after  = json.loads(after_path.read_text())
    transcript = json.loads(transcript_path.read_text()) if transcript_path.exists() else {}
    hypothesis = transcript.get("result", {}).get("hypothesis") or transcript.get("hypothesis") or "(not reported)"
    change_files = sorted(set(transcript.get("result", {}).get("change_files") or transcript.get("change_files") or []))

    delta = format_suite_delta(before, after)

    if after["all_green"] and not before["all_green"]:
        verdict = "GREEN"
    elif strict_improvement(before, after):
        verdict = "PARTIAL"
    elif _passes(after) == _passes(before) and _fails(after) == _fails(before):
        verdict = "NO-IMPROVEMENT"
    else:
        verdict = "REGRESSION"

    if verdict in ("GREEN", "PARTIAL"):
        _git(["add", "-A"], workdir)
        msg = f"iter {iteration}: {hypothesis} [+suite {verdict.lower()}]"
        _git(["commit", "-m", msg], workdir)
        sha = _git(["rev-parse", "--short", "HEAD"], workdir)
        outcome_line = f"committed as `{sha}`"
    else:
        # Save the diff for forensic reference, then revert.
        diff_path = before_path.parent / f"iter_{iteration}.diff"
        diff_path.write_text(_git(["diff"], workdir))
        _git(["checkout", "--", "."], workdir)
        # Clean only files in the harness scope; preserve unrelated untracked.
        _git(["clean", "-fd", "scripts/", "tests/", "docs/", "prompts/"], workdir)
        outcome_line = f"reverted (verdict={verdict}); diff saved to {diff_path}"

    block = render_learnings_block(
        iteration=iteration, verdict=verdict, hypothesis=hypothesis,
        change_files=change_files, suite_delta_text=delta,
        outcome_line=outcome_line, invalidates=None,
    )
    with learnings_path.open("a") as f:
        f.write("\n" + block)
    return verdict


def _finalize_report(*, learnings_path: Path, report_path: Path) -> None:
    text = learnings_path.read_text() if learnings_path.exists() else "(no learnings)"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        "# Harness Iteration Loop — Final Report\n\n"
        + f"Generated: {datetime.datetime.now(datetime.timezone.utc).isoformat()}\n\n"
        + "## Iteration log\n\n"
        + text + "\n"
    )


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    decide = sub.add_parser("decide")
    decide.add_argument("--iteration", type=int, required=True)
    decide.add_argument("--before", required=True)
    decide.add_argument("--after",  required=True)
    decide.add_argument("--transcript", required=True)
    decide.add_argument("--learnings", required=True)
    decide.add_argument("--workdir", required=True)
    final = sub.add_parser("finalize")
    final.add_argument("--learnings", required=True)
    final.add_argument("--report", required=True)
    args = p.parse_args()

    if args.cmd == "decide":
        verdict = _decide_and_act(
            iteration=args.iteration,
            before_path=Path(args.before),
            after_path=Path(args.after),
            transcript_path=Path(args.transcript),
            learnings_path=Path(args.learnings),
            workdir=Path(args.workdir),
        )
        sys.stdout.write(verdict + "\n")
    elif args.cmd == "finalize":
        _finalize_report(learnings_path=Path(args.learnings), report_path=Path(args.report))


if __name__ == "__main__":
    main()
```

**Step 4: Run the unit tests to verify pass**

Run: `.venv/bin/python -m pytest tests/regression/test_iteration_step.py -v`
Expected: 4 passed.

**Step 5: Commit**

```bash
git add scripts/iteration_step.py tests/regression/test_iteration_step.py
git commit -m "feat(regression): iteration_step.py — strict_improvement + commit/revert decision"
```

---

### Task 9: Iteration prompts

**Files:**
- Create: `prompts/loop_system.md`
- Create: `prompts/loop_user.md.tmpl`

**Step 1: Write the system prompt**

`prompts/loop_system.md`:

```markdown
You are iteration N of an autonomous harness-hardening loop for the
custom CDP harness in this repo (`scripts/custom_agent/`,
`scripts/coord_remap.py`, `scripts/harness_patches.py`).

Your contract this iteration:

1. **Read `learnings.md` first.** Do not repeat any hypothesis already
   marked REGRESSION or NO-IMPROVEMENT in a prior iteration unless you
   have a substantively new reason and state it explicitly.
2. **Read the failing test logs** in `/tmp/regression_suite/<run_id>/`
   (path provided in the user prompt) for any test marked failing.
3. **Propose exactly one focused change.** Edit the minimum set of
   files. Scope: `scripts/custom_agent/`, `scripts/coord_remap.py`,
   `scripts/harness_patches.py`, `scripts/custom_agent.py`. Do not
   touch tests, smokes, docs, or browser-use code.
4. **Run the suite once** as a sanity check via
   `.venv/bin/python -u scripts/regression_suite.py --unit-only` (cheap)
   or full mode if the failing test is E2E. Do not retry within an
   iteration; if your change makes things worse, the driver will revert.
5. **Do not commit, push, add, or stash anything.** The driver makes
   commit decisions deterministically based on suite delta.
6. **Return JSON on stdout** as your final response with shape:
   ```
   {
     "hypothesis": "<one sentence>",
     "reasoning": "<2-4 sentences citing the prior learnings or test log>",
     "change_files": ["scripts/custom_agent/actions.py"],
     "pre_run_suite_result": {"all_green": false, "tests": {...}}
   }
   ```

Hard limits: 60-minute wall budget; no network calls beyond the suite's
own; no model swaps; no Thunder-cloud commands. The git working tree at
the start of your turn is your input — at the end it is your output.
```

**Step 2: Write the user prompt template**

`prompts/loop_user.md.tmpl`:

```
This is iteration {iteration} of {max_iterations}.

Current suite state ("before"):
{before_json}

Path to per-test logs (read the failing ones first):
  {log_dir}

Existing learnings.md is at:
  {learnings_path}

Task: per the system contract, propose ONE change to the harness, edit
the file(s), and return your JSON summary.
```

**Step 3: Smoke-render the template**

```bash
.venv/bin/python - <<'PY'
from pathlib import Path
tmpl = Path("prompts/loop_user.md.tmpl").read_text()
out = tmpl.format(iteration=1, max_iterations=20,
                  before_json='{"all_green": false, ...}',
                  log_dir="/tmp/regression_suite/abc12345",
                  learnings_path="/tmp/learnings.md")
print(out[:500])
PY
```
Expected: rendered text with placeholders filled.

**Step 4: Commit**

```bash
git add prompts/loop_system.md prompts/loop_user.md.tmpl
git commit -m "feat(regression): loop prompts (system contract + user template)"
```

---

## Phase 4: Orchestrator (bash)

### Task 10: `iteration_loop.sh`

**Files:**
- Create: `scripts/iteration_loop.sh`

**Step 1: Implement the orchestrator**

```bash
#!/usr/bin/env bash
# Autonomous harness-hardening loop. Spawns one `claude --print` per
# iteration with a restricted tool whitelist; the deterministic driver
# (scripts/iteration_step.py) decides commit-or-revert based on the
# regression suite's before/after delta.
#
# Usage:
#   bash scripts/iteration_loop.sh [--max N] [--branch NAME]
#
# Defaults: --max 20, branch=harness-loop/<timestamp>.
set -euo pipefail

MAX=20
BRANCH=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --max) MAX="$2"; shift 2;;
        --branch) BRANCH="$2"; shift 2;;
        *) echo "unknown flag: $1" >&2; exit 1;;
    esac
done

REPO_ROOT="$(git rev-parse --show-toplevel)"
TS="$(date -u +%Y%m%dT%H%M%SZ)"
BRANCH="${BRANCH:-harness-loop/${TS}}"
WORKTREE="${REPO_ROOT}/../vision-model-harness-loop-${TS}"
LEARNINGS="${WORKTREE}/learnings.md"
REPORT="${WORKTREE}/reports/iteration_loop_${TS}.md"
PROMPT_USER_TMPL="${REPO_ROOT}/prompts/loop_user.md.tmpl"
PROMPT_SYSTEM="${REPO_ROOT}/prompts/loop_system.md"

# Pre-flight
command -v claude >/dev/null 2>&1 || { echo "claude CLI missing" >&2; exit 1; }
[[ -f "$PROMPT_SYSTEM" ]] || { echo "prompts/loop_system.md missing" >&2; exit 1; }
[[ -f "$PROMPT_USER_TMPL" ]] || { echo "prompts/loop_user.md.tmpl missing" >&2; exit 1; }

# Worktree on a fresh branch
git -C "$REPO_ROOT" worktree add -b "$BRANCH" "$WORKTREE" HEAD
mkdir -p "${WORKTREE}/reports"
echo "# Harness Iteration Loop — Run ${TS}" > "$LEARNINGS"
echo "Branch: ${BRANCH}" >> "$LEARNINGS"
echo "Max iterations: ${MAX}" >> "$LEARNINGS"
echo >> "$LEARNINGS"

ALLOWED_TOOLS='Read,Grep,Glob,Edit,Bash(.venv/bin/python -u scripts/regression_suite.py:*),Bash(.venv/bin/python -u scripts/regression_suite.py *:*),Bash(git diff:*),Bash(git status:*)'

prev_all_green=0

for ((i=1; i<=MAX; i++)); do
    echo "=== Iteration $i / $MAX ===" | tee -a "$LEARNINGS" >&2
    BEFORE="${WORKTREE}/.iter/${i}_before.json"
    AFTER="${WORKTREE}/.iter/${i}_after.json"
    TRANSCRIPT="${WORKTREE}/.iter/${i}_transcript.json"
    mkdir -p "$(dirname "$BEFORE")"

    # Snapshot suite BEFORE
    set +e
    "${WORKTREE}/.venv/bin/python" -u "${WORKTREE}/scripts/regression_suite.py" --out "$BEFORE"
    before_rc=$?
    set -e

    if [[ $before_rc -eq 0 && $prev_all_green -eq 1 ]]; then
        echo "Two consecutive green iterations — stopping early." | tee -a "$LEARNINGS"
        break
    fi
    [[ $before_rc -eq 0 ]] && prev_all_green=1 || prev_all_green=0

    # Read run-id and log_dir from BEFORE for the prompt
    LOG_DIR=$("${WORKTREE}/.venv/bin/python" -c "import json; print(json.load(open('$BEFORE'))['log_dir'])")

    # Render user prompt
    USER_PROMPT="${WORKTREE}/.iter/${i}_user.md"
    "${WORKTREE}/.venv/bin/python" - <<PY > "$USER_PROMPT"
from pathlib import Path
import json
tmpl = Path("$PROMPT_USER_TMPL").read_text()
before = Path("$BEFORE").read_text()
print(tmpl.format(
    iteration=$i, max_iterations=$MAX,
    before_json=before,
    log_dir="$LOG_DIR",
    learnings_path="$LEARNINGS",
))
PY

    # Spawn claude with restricted whitelist; 60-min hard timeout
    set +e
    timeout 3600 claude --print \
        --output-format json \
        --append-system-prompt "$(cat "$PROMPT_SYSTEM")" \
        --allowed-tools "$ALLOWED_TOOLS" \
        --cwd "$WORKTREE" \
        < "$USER_PROMPT" > "$TRANSCRIPT" 2>"${TRANSCRIPT}.stderr"
    claude_rc=$?
    set -e
    if [[ $claude_rc -ne 0 ]]; then
        echo "  claude exited rc=$claude_rc (timeout or error); recording as TIMEOUT/ERROR" >&2
        echo "{}" > "$TRANSCRIPT"
    fi

    # Snapshot suite AFTER (re-run; ground truth)
    set +e
    "${WORKTREE}/.venv/bin/python" -u "${WORKTREE}/scripts/regression_suite.py" --out "$AFTER"
    set -e

    # Driver decides + commits or reverts
    "${WORKTREE}/.venv/bin/python" "${WORKTREE}/scripts/iteration_step.py" decide \
        --iteration "$i" \
        --before "$BEFORE" --after "$AFTER" --transcript "$TRANSCRIPT" \
        --learnings "$LEARNINGS" --workdir "$WORKTREE"
done

# Finalize report
"${WORKTREE}/.venv/bin/python" "${WORKTREE}/scripts/iteration_step.py" finalize \
    --learnings "$LEARNINGS" --report "$REPORT"
echo "Final report: $REPORT"
echo "Worktree:     $WORKTREE"
echo "Branch:       $BRANCH"
```

**Step 2: Make executable**

```bash
chmod +x scripts/iteration_loop.sh
```

**Step 3: Lint with `bash -n` and `shellcheck` if available**

```bash
bash -n scripts/iteration_loop.sh
which shellcheck && shellcheck scripts/iteration_loop.sh || echo "(shellcheck not installed; skipping)"
```
Expected: no syntax errors. Shellcheck warnings are OK to triage; resolve any error-level findings before committing.

**Step 4: Commit**

```bash
git add scripts/iteration_loop.sh
git commit -m "feat(regression): orchestrator iteration_loop.sh with worktree isolation"
```

---

## Phase 5: End-to-end smoke

### Task 11: Dry-run with synthetic transcript

This task validates the orchestrator's plumbing without spending Max-subscription tokens. Replace the `claude --print` call with a stub that always returns a fixed transcript and emits no edits. Run one iteration, observe a `NO-IMPROVEMENT` verdict, confirm the worktree, learnings.md, and report all populate correctly.

**Files (temporary):**
- Edit `scripts/iteration_loop.sh` line invoking `claude --print` to instead invoke a stub. Do this on a throwaway branch; **revert before committing the loop's first real run**.

**Step 1: Create the stub**

```bash
cat > /tmp/claude_stub.sh <<'EOF'
#!/usr/bin/env bash
cat <<'JSON'
{"type":"result","result":"{\"hypothesis\":\"stub: no change proposed\",\"change_files\":[]}","session_id":"stub"}
JSON
EOF
chmod +x /tmp/claude_stub.sh
```

**Step 2: Apply temporary swap**

In `scripts/iteration_loop.sh`, replace the `timeout 3600 claude --print ...` block with `/tmp/claude_stub.sh > "$TRANSCRIPT"`. Save.

**Step 3: Run for max=2 iterations and inspect**

```bash
bash scripts/iteration_loop.sh --max 2 2>&1 | tee /tmp/dryrun.log
ls ../vision-model-harness-loop-*/  | tail -5
cat ../vision-model-harness-loop-*/learnings.md
cat ../vision-model-harness-loop-*/reports/iteration_loop_*.md
```

Expected:
- Worktree created
- Two iteration blocks in learnings.md, both `NO-IMPROVEMENT` (no change made)
- Final report contains both blocks
- No commits on the new branch beyond the initial state

**Step 4: Restore `iteration_loop.sh` and commit nothing from this task**

```bash
git -C "$REPO_ROOT" checkout -- scripts/iteration_loop.sh
git -C "$REPO_ROOT" worktree remove --force ../vision-model-harness-loop-* || true
```

**Step 5: Document the validation in CLAUDE.md**

Add a short paragraph under a new sub-heading "Harness regression suite & iteration loop":

```markdown
## Harness regression suite & iteration loop

`scripts/regression_suite.py` is the single entry point for verifying
the custom CDP harness's invariants. It runs four pytest regression
locks (quant default, coord-space convention, scroll clamp, iframe
skip), the 9/9 mechanical CDP probe, and two E2E custom-agent runs
(saucedemo full checkout, IKEA BILLY). JSON output to `--out` or stdout;
exit 0 iff all green.

`scripts/iteration_loop.sh` runs an autonomous harness-hardening loop
in a fresh worktree on `harness-loop/<ts>`, spawning one `claude --print`
per iteration (Max subscription, restricted tool whitelist) and letting
`scripts/iteration_step.py` decide commit-or-revert based on suite
delta. Stops on two consecutive greens or after `--max` (default 20)
iterations. Final report at `reports/iteration_loop_<ts>.md`.
```

```bash
git add CLAUDE.md
git commit -m "docs: regression suite + iteration loop usage in CLAUDE.md"
```

---

### Task 12: First real iteration (gated)

**Do NOT run automatically.** This task documents how to launch the first real loop, but operator runs it explicitly. Cost ~1-3 hours of `claude` Max-subscription wall time.

**Pre-flight checklist** (operator must verify each):

- [ ] `git status` clean on main
- [ ] `vision-model.service` active and serving the intended model
  (default UI-Venus-1.5-8B Q6_K): `systemctl is-active vision-model.service`
- [ ] `DISPLAY=:0` Plasma session logged in (smokes need headed Chromium)
- [ ] One full suite run as baseline:
  ```bash
  .venv/bin/python -u scripts/regression_suite.py --out /tmp/baseline.json
  cat /tmp/baseline.json | python -m json.tool
  ```
  Note which tests are red — those are the loop's targets.

**Run:**

```bash
bash scripts/iteration_loop.sh --max 20 2>&1 | tee /tmp/loop_run.log
```

**Post-flight:**

- Inspect `<worktree>/reports/iteration_loop_<ts>.md`
- Cherry-pick any `GREEN`/`PARTIAL` commits onto main via PR (manual review)
- `git worktree remove <worktree>` once you're done with the artifacts

No commit in this task; it's runbook documentation only.

---

## Acceptance criteria for the implementation

- All 7 regression-suite tests run individually and as a group; the four
  unit tests pass on first run, the mechanical probe passes (currently
  9/9), the two E2E tests have a documented current state in
  `learnings.md` baseline.
- `strict_improvement(before, after)` is unit-tested for the four
  cases (grow / same / swap / lose) plus the new-key edge case.
- `iteration_step.py decide` produces a correctly-formatted
  `learnings.md` block for at least one `GREEN`, one `PARTIAL`, one
  `REGRESSION`, one `NO-IMPROVEMENT` synthetic input (covered by the
  Task 8 unit tests).
- `iteration_loop.sh` dry-runs end-to-end with the stub (Task 11) and
  produces a worktree + learnings.md + final report without errors.
- `claude --print --allowed-tools` whitelist confirmed accepted by the
  CLI on the operator's machine (verified during Task 12 pre-flight).

---

## Out-of-scope reminders

- Browser-use code (`scripts/smokes/`, `scripts/smoke_browser_use.py`)
  is not changed.
- Model swaps, Thunder cloud, findings webapp build/deploy: untouched.
- The loop never pushes to remote; `git push` is not in the whitelist.
