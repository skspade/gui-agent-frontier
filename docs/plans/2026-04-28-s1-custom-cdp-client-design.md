# S-1: Custom CDP client prototype — design

**Status**: design approved 2026-04-28, awaiting implementation plan
**Backlog item**: S-1 (`docs/backlog.md`)
**Depends on**: F-1 (drag action, Phase 9), F-2 (coord remapper, Phase 10)

## Goal

Build a small Python program that drives Chromium directly via CDP, with
UI-Venus-1.5-8B as the planner using its **native** navigation chat
template (`<think>/<action>/<conclusion>`). No browser-use, no
DOM-indexed protocol.

The hypothesis is that the model's native format unlocks capability that
browser-use's DOM-augmented prompts leave on the table on
canvas / shadow-DOM / nested-anchor pages. The prototype either confirms
or refutes that — a negative result is a valid outcome.

## Architecture

```
┌──────────────┐  screenshot   ┌──────────────┐  <action>      ┌──────────────┐
│   Chromium   │ ────────────▶ │  llama.cpp   │ ─────────────▶ │  Agent loop  │
│ (CDP :9222)  │ ◀──────────── │  (UI-Venus)  │                │  (parse +    │
└──────────────┘   dispatch    └──────────────┘                │   remap)     │
                  Mouse/Key                                    └──────────────┘
```

The loop is the only stateful component. It holds task text, action
history, and step count; everything else is stateless I/O.

**Model is the planner** (decided in brainstorming): the loop dispatches
whatever action the model emits and feeds back the next screenshot —
apples-to-apples with browser-use.

## File layout (mirrors existing smoke runner pattern)

```
scripts/
  custom_agent.py                    ← runner, CLI entry point
  custom_agent_tasks/
    __init__.py
    saucedemo_headless.py            ← TASK, START_URL, HEADLESS=True, MAX_STEPS, SUCCESS_CHECK
    excalidraw_toolbar.py            ← TASK, START_URL, HEADLESS=False, MAX_STEPS, SUCCESS_CHECK
  custom_agent/
    __init__.py
    browser.py     (~80 lines)       ← spawn chromium, CDP attach, screenshot, dispatch primitives
    model.py       (~60 lines)       ← format prompt + history → POST llama.cpp, parse <action>
    actions.py     (~80 lines)       ← per-action dispatchers, on-demand
```

Total target ~300 lines including comments. Reuses
`scripts/coord_remap.py` (Phase 10) without modification.

## Data flow (one step)

1. `browser.screenshot()` → CDP `Page.captureScreenshot{format:"png"}`
   → b64. CSS viewport size queried once via `Page.getLayoutMetrics`.
2. `model.step(task, history, screenshot_b64)` → builds the navigation
   chat-template prompt, POSTs to `http://localhost:8080/v1/chat/completions`,
   returns raw text.
3. `parse_action(raw_text)` → regex extracts `<action>...</action>` and
   `<conclusion>...</conclusion>`. Dispatches by action name.
4. For coordinate-bearing actions: `navigation_remap(model_xy,
   css_viewport_size)` (per Phase 10 — but verify on first run, see
   *Empirical risk* below).
5. `actions.dispatch(session, action)` → `Input.dispatchMouseEvent`,
   `Input.insertText`, `Input.dispatchKeyEvent`, etc.
6. Append `(action, conclusion)` to history. If action is `done` or
   `MAX_STEPS` reached, stop.

Server config: we do **not** enforce JSON output. UI-Venus emits
`<think>/<action>/<conclusion>` natively; we regex-parse. If parsing
fails twice in a row on the same step, log the raw output and abort —
re-prompting hides the real failure.

## Action grammar

On-demand. Day-one stubs: `click`, `type`, `scroll`, `done`. New
actions land in `actions.py` the first time the model emits one we
don't handle (e.g. `key`, `drag`, `swipe`). The prototype's job is to
validate the architecture, not to be a complete agent.

## Empirical risk to retire on day one

Phase 10 verified the **grounding prompt** path on the merged 8B (0–1000
normalized coordinates → `grounding_remap`). The **navigation chat
template's** coordinate convention on the merged 8B is *assumed* to be
resized-image pixel space (from upstream
`models/navigation/ui_venus_navi_agent.py::_rescale_coordinate`), but
**unverified empirically**.

**First milestone of implementation**: send one navigation-template
prompt against `/tmp/smoke_final.png` (or any known image with a
labelled target), plot both `grounding_remap` and `navigation_remap`
interpretations on the screenshot, confirm which lands on the asked-for
target. If the result surprises us, the remapper is a one-line swap
thanks to F-2.

## Browser launch

- **Headless saucedemo**: spawn chromium with
  `--headless=new --remote-debugging-port=9222 --user-data-dir=/tmp/...
  --disable-blink-features=AutomationControlled`. No display env needed.
- **Headed Excalidraw**: same, minus `--headless`, plus the display env
  vars from `CLAUDE.md` (`DISPLAY=:0`,
  `XAUTHORITY=/run/user/1000/xauth_rVYaGJ`,
  `XDG_RUNTIME_DIR=/run/user/1000`).
- **Binary**:
  `/home/seans/.cache/ms-playwright/chromium-1208/chrome-linux64/chrome`
  (per `CLAUDE.md`).
- **CDP client**: `cdp-use` (already installed; browser-use uses it).

## Error handling and verification

- **Per-step screenshot**: numbered PNG written to
  `/tmp/custom_agent_steps/NNN.png` after each action. Cheap insurance;
  agent self-reports cannot be trusted (`CLAUDE.md` operational rule 3).
- **Final screenshot**: `/tmp/custom_agent_final.png`, identical to the
  smoke runner convention.
- **Parse failure handling**: log raw response, abort run. No
  re-prompting (would hide the real failure).
- **Action-dispatch failure**: log the failed action, capture
  screenshot, abort. We want to *see* failures, not paper over them.
- **Long runs**: redirect stdout to a log file per `CLAUDE.md`
  operational rule 2.

## Test cases & comparison plan

### Test 1 — saucedemo headless (one of two head-to-head tests)

- Task: log in to saucedemo.com, add an item to cart, navigate to cart,
  proceed to checkout (or analogous flow proving the cart-icon click
  works).
- **Why**: browser-use loops on the cart-icon click in headless
  (findings Phase 2, Smoke 2). A direct
  `Input.dispatchMouseEvent` at remapped pixels should sidestep the
  nested-anchor CDP-click bug entirely.
- Headless mode (default chromium `--headless=new`).
- `MAX_STEPS = 25`.
- Success check: agent self-reports `done` *and* final screenshot shows
  the cart page or checkout page.

### Test 2 — Excalidraw toolbar (canvas-heavy)

- Task: navigate to excalidraw.com, identify the rectangle tool by its
  glyph, click it, draw a rectangle by drag.
- **Why**: canvas, no useful DOM. Closes the loop on the F-1 (drag) +
  F-2 (coord remap) prerequisites and stresses visual grounding.
- Headed mode (Plasma+Wayland Xwayland, per `CLAUDE.md`).
- `MAX_STEPS = 25`.
- Success check: final screenshot shows a rectangle on the canvas in
  the expected region; visually confirmed.

### Comparison metrics (per backlog acceptance)

For each test, record: step count, wall-clock time, success/failure,
final screenshot path, raw model outputs in a log file. Compare against
existing browser-use baselines (Phase 2 smoke 2 for saucedemo; Phase 4 /
Phase 9 smokes for Excalidraw).

## Acceptance criteria

Per backlog S-1:

1. Working prototype in `scripts/custom_agent.py` + `custom_agent/` +
   `custom_agent_tasks/`.
2. Side-by-side comparison entry in `docs/findings.md` Phase 11 with
   numbers from both tests, including at least one task where the
   custom client and browser-use *diverge* (custom succeeds where
   browser-use fails, or vice versa).
3. Backlog item S-1 deleted from `docs/backlog.md` after writing the
   findings entry (history lives in `findings.md`).

## Out of scope (YAGNI)

- Prompt caching, batching, async pool — serial loop only.
- Re-prompt on parse failure (hides bugs).
- Generic action-grammar exhaustive coverage — implement on demand.
- Reverse proxy / auth — that's S-2.
- Test framework (pytest) — a `parse_action` self-test is sufficient.

## Risks and unknowns

| Risk | Mitigation |
|------|-----------|
| Navigation chat template's coord convention unverified on merged 8B | Day-one empirical check with both remappers (see *Empirical risk*) |
| Model's planning quality may be insufficient for end-to-end agent | Negative result is a valid outcome per backlog; document and stop |
| `--headless=new` may have its own click-dispatch quirks | If it does, document and try `--headless=old` or fall back to headed |
| `cdp-use` API surface may differ from assumed sketch | Quick spike at start of implementation; pivot to raw websockets if too friction-y (~30 line addition) |
