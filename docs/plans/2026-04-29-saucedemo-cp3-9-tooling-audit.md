# Saucedemo CP3-CP9 tooling audit

Date: 2026-04-29
Status: **ready for execution.** Self-contained handoff. The Phase 15
follow-up unblocked CP1-CP2 by adding a synthetic `<select>` overlay
to the dispatcher; this audit walks CP3-CP9 with DOM-truth coords to
find any other dispatcher gaps before we re-evaluate any model.

## TL;DR

Phase 15 follow-up landed a deterministic 2/9 strict baseline for both
UI-Venus 8B and Holo3-35B-A3B on `saucedemo_full_checkout`. Both fail
at CP3. We don't yet know whether CP3 (and CP4-CP9) fail because of
**model precision** (model clicked the wrong pixel) or **dispatcher
gap** (CDP press+release at the right pixel didn't fire the right
event). The dropdown wall in CP2 was the second category — a tooling
issue masquerading as a model issue for two phases. We don't want to
spend another bake-off finding out CP4-CP9 had similar gaps.

> **Goal: verify mechanically (no model in the loop) that CP3-CP9 each
> succeed when driven by DOM-truth coords through the existing
> dispatcher. For any CP that fails, fix the tooling gap.**

Once this audit is clean, the remaining R1 score gap is unambiguously
a model problem and the 5-stack bake-off becomes a fair test.

## Read these before starting (cold-start orientation)

1. **`CLAUDE.md`** at repo root — non-negotiable operational rules.
   Highlights for this work:
   - Display env vars: `DISPLAY=:0 XAUTHORITY=/run/user/1000/xauth_rVYaGJ XDG_RUNTIME_DIR=/run/user/1000`
   - Privileged ops: write to `/tmp/foo.sh`, run as `sudo bash /tmp/foo.sh`
   - Long-running scripts: redirect stdout to a file (the harness wraps
     `tail -200` and buffers everything in memory)
   - Don't blame HMR / build caches when fixes don't change numbers —
     assume the fix is wrong first
   - Independent verification screenshots are mandatory for visual tasks
   - When corrected on an assumption, restate the corrected assumption
     in one sentence and stop explaining
2. **`docs/findings.md`**, the **Phase 15** entry and the **Phase 15
   follow-up: it was the tooling all along** entry. The follow-up
   describes the dropdown overlay fix and is the template for what
   "fixing a dispatcher gap" looks like.
3. **`scripts/saucedemo_dropdown_probe.py`** — the diagnostic that led
   to the dropdown overlay fix. Mirror its structure for the CP3-CP9
   probe: launch chromium → drive actions via `_click` / `_type_keys`
   directly → query DOM truth via `Runtime.evaluate` → save annotated
   screenshots → print pass/fail per CP.
4. **`scripts/custom_agent_tasks/saucedemo_full_checkout.py`** — the
   9-checkpoint task verbatim. Don't re-derive checkpoint semantics;
   read what TASK says.
5. **`scripts/custom_agent/actions.py`** — the dispatcher. Knowing what
   it CAN do (click via `_click`, type via `_type_keys`, scroll,
   press_enter, etc.) and what it CAN'T do without an extension is the
   prerequisite for diagnosing failures.

## What's already done (don't redo)

- **DPR=1 pin** (`scripts/custom_agent/browser.py`): `--force-device-scale-factor=1`.
  Screenshot dims = viewport CSS dims. Don't undo.
- **`<select>` overlay** (`scripts/custom_agent/actions.py`): clicks on
  a native `<select>` open a synthetic DOM overlay; clicks on overlay
  options are intercepted before CDP press+release and applied via JS
  (set value + dispatch change). Letter-jump fallback for typed
  characters on a focused select. Verified working via the dropdown
  probe and via two model R1 runs (both cleared CP2).
- **`click_at` and `click_then_type` action kinds** for harnesses whose
  models emit already-viewport-pixel coords (Holo3 path). The plain
  `click` kind still applies `grounding_remap` for UI-Venus.
- **Page-change detector and stuck-loop early-out** in `custom_agent.py`.
  Trustworthy signal for "the click did nothing visible." This audit
  doesn't use the run loop — drive the page directly — but the
  semantics are useful when interpreting probe results.

## Hypothesis under test

> Each CP3-CP9 action — when driven by DOM-truth coords through the
> existing dispatcher — produces the expected page state change.
> If any CP fails, there is a dispatcher-level tooling gap (analogous
> to the CP2 dropdown gap) that masks itself as a model failure during
> R1 evaluation.

Falsification: any CP where `_click(x, y)` at the DOM-truth button
center, or the DOM-truth Remove button, or fill-and-Continue on the
checkout form, etc., does not advance the page. That's a tooling bug
to fix.

## Step-by-step plan

### Step 1 — Write the CP3-CP9 probe

Create `scripts/saucedemo_flow_probe.py`. Mirror
`scripts/saucedemo_dropdown_probe.py` in structure: a single
`asyncio.run(main())` that launches headed chromium, walks the flow
step by step, queries DOM truth between steps, and saves an annotated
screenshot per CP.

The probe drives **the same dispatcher functions** the agent loop uses
(`scripts.custom_agent.actions._click`, `_type_keys`, the scroll
helper, `_press_key` if needed). Don't reach around the dispatcher
into raw CDP — the point is to test the dispatcher.

For each CP, the probe needs:

1. **Coord lookup**: query the DOM for the target element's
   `getBoundingClientRect()` and compute the center.
2. **Action**: dispatch the right action(s) at that center.
3. **Verification**: query DOM state OR URL OR text content to confirm
   the CP advanced.
4. **Annotated screenshot**: save `/tmp/saucedemo_flow_probe.cpN.png`
   with a crosshair on the click point.
5. **Pass/fail line**: `print(f"CPn: {label:40} -> PASS|FAIL  {evidence}")`.

Per-CP target selectors and verifications (verbatim from the task plus
saucedemo's known DOM):

| CP | Action | Selector(s) | Verification |
|---|---|---|---|
| 1 | Login | `#user-name`, `#password`, `#login-button` (use `_type_keys` for fields, `_click` for button) | URL becomes `/inventory.html` |
| 2 | Sort by Price low→high | Click `.product_sort_container` (overlay opens), then click overlay option whose text contains "Price (low to high)" | `document.querySelector('.product_sort_container').value === 'lohi'` and `document.querySelector('.inventory_item_name').textContent === 'Sauce Labs Onesie'` |
| 3 | Add third-cheapest to cart | After sort, third-cheapest by price = Sauce Labs Bolt T-Shirt ($15.99). Click `[data-test=add-to-cart-sauce-labs-bolt-t-shirt]` rect center | `.shopping_cart_badge` text === '1', and `[data-test=remove-sauce-labs-bolt-t-shirt]` exists |
| 4 | Add Sauce Labs Backpack | Backpack is in row 3 — may need to scroll. Use `_scroll` direction='down' until `[data-test=add-to-cart-sauce-labs-backpack]` is in viewport, then click its rect center | `.shopping_cart_badge` text === '2' |
| 5 | Open cart | Click `.shopping_cart_link` (cart icon top-right) | URL becomes `/cart.html` |
| 6 | Remove Bolt T-Shirt from cart | Click `[data-test=remove-sauce-labs-bolt-t-shirt]` rect center | `[data-test=remove-sauce-labs-bolt-t-shirt]` no longer exists; `.cart_item` count === 1 |
| 7 | Checkout form | Click `[data-test=checkout]`, fill `#first-name=Test`, `#last-name=User`, `#postal-code=94000`, click `[data-test=continue]` | URL becomes `/checkout-step-two.html` |
| 8 | Verify item total $29.99 | Read-only — check `.summary_subtotal_label` text contains `$29.99` | Boolean assertion, no action |
| 9 | Click Finish | Click `[data-test=finish]` | URL becomes `/checkout-complete.html`; page contains text "Thank you for your order!" |

Implementation note for the dispatcher: `_click` uses CSS pixels via
CDP `Input.dispatchMouseEvent`. With DPR=1 in launch_chromium,
`getBoundingClientRect()` x/y values map directly to dispatcher coords.
Pass them as integers — no scaling.

CLI usage to run the probe:

```bash
DISPLAY=:0 XAUTHORITY=/run/user/1000/xauth_rVYaGJ XDG_RUNTIME_DIR=/run/user/1000 \
  PYTHONUNBUFFERED=1 \
  .venv/bin/python -u scripts/saucedemo_flow_probe.py \
  > /tmp/saucedemo_flow_probe.log 2>&1
```

Read the log file with `Read`, not `cat | tail` — see CLAUDE.md.

**Acceptance for step 1:**
- Probe compiles (`.venv/bin/python -c "import py_compile; py_compile.compile(...)"`)
- Probe runs to completion without raising
- Each CP prints a `PASS|FAIL` line with concrete evidence

### Step 2 — Triage results

Each FAILing CP is a candidate for a dispatcher fix. For each:

1. **Re-read the failure mode**: what does the screenshot show? What
   does DOM state show? What does the dispatcher's stderr trace say
   (e.g., did `_focus_native_select` log anything; did
   `_try_overlay_click` log anything)?
2. **Reach for the smallest fix**: the dropdown overlay was ~50 lines
   of JS plus three small Python helpers. If a CP needs a
   comparable-size affordance, that's fine. If it needs more than a
   day of work, stop and discuss.
3. **Add a regression test** to the probe so the fix can't silently
   break later.

Likely failure categories, with what-to-look-for hints (speculative —
update or delete as data comes in):

- **CP3/CP4 (Add-to-cart)**: probable PASS via DOM-truth coords. If
  PASS, then both models' R1 failure here is pure precision — they
  clicked above the actual button. No dispatcher fix needed; consider
  whether to bias the prompt or the screenshot toward making buttons
  more visually salient.
- **CP4 scroll**: `_scroll` uses `Input.dispatchMouseEvent` with a
  `mouseWheel` deltaY. If the scroll doesn't reveal the next row, check
  whether saucedemo's inventory grid uses scrollable container vs page
  scroll. May need to scroll a specific element rather than the page.
- **CP5 cart icon**: `CLAUDE.md` flags saucedemo's cart icon as a
  headless-click-failure trap (nested anchor pattern). We're in headed
  mode but verify anyway. If fails, the fix is probably to click the
  `<a>` element specifically rather than its child `<svg>` — test both.
- **CP7 checkout fields**: standard text inputs. Should work via
  `_type_keys` with no surprises.
- **CP8**: read-only assertion. No dispatcher concern unless the
  selector is wrong.
- **CP9 Finish button**: standard `<button>`. Should work.

### Step 3 — Spot-check with a single model run

Once all CPs PASS via DOM-truth coords, re-run **one** model (say
UI-Venus 8B since it's deterministic at temp=0) to see how far it gets
through the now-clean tooling. The score is unimportant; what matters
is:
- Is there any *other* dispatcher gap surfacing that the probe didn't
  cover (e.g., the model emits an action shape we haven't seen before
  and the dispatcher doesn't handle it)?
- Are model failures clearly visual/precision now?

If yes to clean tooling: ready for the deferred 5-stack bake-off.
If no: another iteration of probe → fix → spot-check.

### Step 4 — Findings entry

Append a `## 2026-04-29 — Saucedemo flow tooling audit` section to
`docs/findings.md` immediately before the `## Open questions for
retro` section. Match the structure of the Phase 15 follow-up:

- Setup (what was probed, why)
- Result (per-CP PASS/FAIL summary, what fixes were needed)
- Findings (in order of importance — any dispatcher gaps closed)
- Verdict (tooling is clean / specific known limits documented)
- Operator-facing changes (any new dispatcher behaviors, any new
  selectors agents need to know about)

If no gaps were found and probe PASSes all 9, document that too — a
"we audited and there's nothing to fix" finding is just as valuable.

## Acceptance criteria for the whole audit

1. `scripts/saucedemo_flow_probe.py` exists and PASSes all 9
   checkpoints when run end-to-end.
2. Any dispatcher fixes needed to make CP3-CP9 pass are landed in
   `scripts/custom_agent/actions.py` (or wherever appropriate) with the
   same care as the Phase 15 follow-up overlay fix.
3. A spot-check run of `saucedemo_full_checkout` against UI-Venus 8B
   reaches at least the same CP it reached before (regression check).
4. Findings entry merged.

## What NOT to do

- **Don't re-run the Phase 13 5-stack bake-off yet.** That's the
  reason this audit exists — to confirm the tooling is clean before
  paying for another cross-model comparison. Re-running the bake-off
  prematurely just rebuilds the same potentially-flawed numbers.
- **Don't extend the action set** unless absolutely necessary. The
  dropdown overlay was a dispatcher-internal fix that didn't change
  what the model could emit. Prefer the same shape: dispatcher detects
  some condition and silently does the right thing.
- **Don't change the canonical task** in
  `scripts/custom_agent_tasks/saucedemo_full_checkout.py`. The 9
  checkpoints are the contract; if CP3 turns out to be unreasonably
  hard for our class of models, that's a finding, not a reason to
  rewrite the task. (We may eventually want a simpler benchmark — see
  the Phase 15 follow-up's verdict — but that's a separate decision.)

## Files of interest (cheat sheet)

```
scripts/saucedemo_flow_probe.py                         # NEW: this audit creates it
scripts/saucedemo_dropdown_probe.py                     # reference shape; don't touch
scripts/custom_agent/actions.py                         # where dispatcher fixes land
scripts/custom_agent/browser.py                         # don't touch (DPR=1 already set)
scripts/custom_agent_tasks/saucedemo_full_checkout.py   # the canonical task
scripts/custom_agent.py                                 # the run loop (used in step 3 spot-check only)
docs/findings.md                                        # append audit findings entry
```

Reference artifacts from Phase 15 follow-up at
`/tmp/r1_artifacts/{ui-venus-1.5-8b,holo3-35b-a3b.holo3}.overlay2.{log,steps,final.png}`.
The first model click that fails CP3 is in those logs — useful for
calibrating the probe's expectations before running.

## Estimated effort

- Step 1 (write probe): 1-2 hours
- Step 2 (triage + fixes): 1-3 hours depending on gaps found
- Step 3 (spot-check): 5 min
- Step 4 (findings): 30 min
- **Total: 3-6 hours.**

## Decision log

- **Audit before bake-off.** A 5-stack rerun would otherwise replicate
  the dropdown false-failure on every model that hits a CP3-CP9
  tooling gap. Mechanical verification first; model evaluation second.
- **Probe via dispatcher functions, not raw CDP.** The point is to
  exercise the same code path the agent loop uses. Reaching around
  the dispatcher would test something different.
- **DOM-truth coords, not visual approximation.** `getBoundingClientRect()`
  is unambiguous. Fail-by-pixel is a model problem; fail-by-event is
  a dispatcher problem. Keeping these clean is the whole point.
- **Don't expand the action set unless forced.** Dispatcher fixes are
  invisible to the model. Action-set changes ripple into every
  harness.
