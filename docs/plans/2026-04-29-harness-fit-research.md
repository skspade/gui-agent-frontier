# Research: are we shoehorning the models into the wrong harness?

Date: 2026-04-29
Status: research proposal — no implementation work yet.

## Hypothesis

The local VLMs we evaluated in Phase 13 (UI-Venus-1.5-8B/30B-A3B,
Holo2-30B-A3B, bu-30b-a3b-preview, Holo1.5-7B) are *visually grounded*
models trained to emit pixel coordinates. browser-use exposes a
contract that's primarily *element-index-based*: the model picks a
numbered DOM element from a serialized accessibility-tree-like view
that browser-use produces every step. The model's natural output
("click at (487, 312)") is being translated into the harness's native
output ("click element with index 14") via an awkward middle layer
that breaks down under page churn.

If true, the bottleneck on the long-horizon saucedemo task isn't model
quality — it's the impedance mismatch between models trained on
"screenshots → coords" and a harness whose action vocabulary is
"index → action". A custom harness that lets the model speak its
native language end-to-end might recover most of the lost performance
without any model swap.

## Evidence supporting the hypothesis (from Phase 13)

1. **The element-index churn pattern was identical across all five
   stacks.** The 8B baseline (S1), the UI-Venus 30B (S2), Holo2 (S3),
   AND the model trained specifically for browser-use (bu-30b, S4) all
   failed at saucedemo's "Add to cart" step in the same way: model
   emits `click(index=N)`, browser-use repaints, index N is now stale,
   model loops on "element not available." This is a contract problem,
   not a model problem — even the model trained for browser-use
   couldn't recover.

2. **Holo2's 3-step toolbar win was achieved by a *visual* task.**
   Excalidraw's toolbar is a coordinate-grounded interaction (the
   tools are on a canvas-adjacent strip, indexed by browser-use as a
   group of similar buttons). Holo2 terminated cleanly in 3 steps when
   the model's coord output mapped directly to a click. The same
   model failed on saucedemo because the index-based path forced a
   second translation step.

3. **Phase 11 already saw this.** The custom CDP agent (`scripts/
   custom_agent/`) in Phase 11 was meaningfully better than browser-use
   on canvas tasks (Excalidraw 3 steps / 24s vs browser-use's
   multi-step F-1+F-2 setup) — because it stays in the model's native
   coord space. Phase 11 concluded "use custom CDP for canvas /
   shadow-DOM / heavy-visual UIs" but didn't extend the test to
   shopping flows where the same logic applies.

4. **bu-30b's `start_x/start_y/end_x/end_y` for the `drag` action.**
   We documented `x1/y1/x2/y2`. The model emitted a *different but
   reasonable* parameter convention. That's not weak instruction-
   following; it's the model defaulting to a coord vocabulary that's
   natural to it but doesn't match our harness's chosen names. The
   harness, not the model, is the one with an arbitrary convention.

5. **The `Page.captureScreenshot` ground truth always worked.** Every
   stack's grounding was sound when judged from the screenshot — the
   models knew where things were on the page. The disconnect was at
   the action layer where coords get translated into browser-use's
   index space.

## What we don't know yet

A research phase needs to answer these before we commit to building.

1. **Is browser-use's element-index churn fixable inside browser-use,
   or is it inherent?** Maybe browser-use already supports
   coordinate-only modes that we haven't enabled. The version-0.12 API
   has `Tools.registry` and custom actions; we registered `drag`. Can
   we register a `click_coord(x, y)` and a `type_at_coord(x, y, text)`
   that bypass the element-index lookup entirely? If yes, the existing
   harness with extra actions might suffice without a custom harness.

2. **Does the existing `scripts/custom_agent/` CDP path scale to
   shopping flows?** Phase 11 used it for Excalidraw (canvas) and
   touched saucedemo briefly. We never ran it on the full 9-checkpoint
   long-horizon flow. Before building a new harness, we should run
   the Phase 13 long-horizon task through the existing custom CDP
   agent and see how far it gets. That's the cheapest possible test
   of the hypothesis.

3. **What's the "ideal" harness for these models?** Look at how
   UI-Venus, Holo2, and bu-30b documented inference recipes. The bu-30b
   README's example uses browser-use directly — implying browser-use is
   the intended target. Holo2's docs reference Surfer-H-CLI as the
   reference harness. UI-Venus has an in-paper agent loop that's
   coord-based (the v1 paper, Aug 2025). If three different models
   target three different harnesses, "best harness for X" depends on
   X.

4. **How much of browser-use is genuinely useful?** browser-use ships
   non-trivial value beyond element-index dispatch:
   - System-prompt scaffolding for agentic loops
   - Plan / Memory / Eval per-step structured outputs
   - Loop-detection and stagnation nudges
   - History compaction
   - Sensitive-data masking
   - Browser session management (CDP, profiles, persistence)

   A "custom harness" doesn't necessarily mean "rewrite all of this." A
   surgical change might be: keep browser-use's session/loop framework
   but swap its action vocabulary to coord-first.

## Proposed research experiments

Each of these is small enough to run in a phase. They build on each
other, but each produces a useful answer alone.

### R1 — Cheapest test: long-horizon on existing custom CDP agent

Run `saucedemo_full_checkout` against the *existing* `scripts/
custom_agent.py` path (no harness changes). Score with the same
checkpoint rubric as Phase 13. Compare to the S3 (Holo2) verified
median of 2/9.

If custom CDP reaches more checkpoints with the same model
(UI-Venus-1.5-8B), the hypothesis is supported. If it gets stuck
similarly, the bottleneck is something we missed (e.g. saucedemo's
specific click handlers reject CDP-synthesized clicks). Either
outcome is decisive cheaply.

**Effort: s** (a few hours; no new code, just port the task payload to
`custom_agent_tasks/`).

**Decision rule:** if R1 succeeds, run R2. If R1 fails, the harness
swap is not the answer; investigate elsewhere.

### R2 — Add coord-first actions to browser-use

Register `click_coord(x, y)` and `type_at_coord(x, y, text)` actions
on browser-use's `Tools` registry alongside (or instead of) the
existing index-based `click` and `input`. Run the same long-horizon
suite. Goal: keep all of browser-use's loop/eval/memory scaffolding,
swap only the action vocabulary.

**Effort: m** (a day; needs careful testing of CDP click vs `tools`'s
own index-click pipeline; needs an `extend_system_message` that
documents the coord actions).

**Decision rule:** if R2's score lifts S1 (8B) past Phase 13's verdict
threshold, this is the lowest-effort win. Adopt and re-run the bake-off.

### R3 — Survey the documented inference recipes

For each Phase 13 candidate, find the model's *documented* inference
contract and compare it to browser-use's contract:

- UI-Venus paper (2508.10833 v1, 2602.09082 v1.5): what action
  vocabulary does the paper assume?
- Holo / Holo2 (Surfer-H-CLI): what's the action set?
- bu-30b (browser-use OSS): which version of browser-use is bu-30b
  trained against? Does the version we're running (0.12.6) match?
- UI-TARS: action set for comparison.

Output: a table of "what the model expects" vs "what browser-use
0.12.6 provides." Gaps are candidates for harness adaptation.

**Effort: s** (research only; ~4 hours of reading + a doc).

### R4 — Build a minimal custom harness

If R1 and R2 both validate the hypothesis but neither approach is
sufficient, build a focused custom harness:

- Keep the agent loop pattern (plan → eval → action → screenshot).
- Action vocabulary is coord-first: `click(x, y)`, `drag(x1,y1,x2,y2)`,
  `type(x, y, text, clear)`, `scroll(direction, amount)`,
  `key(key)`, `done(result)`. No element indices.
- Reuse browser-use's session/CDP wiring if possible (it already does
  the right thing at the browser layer); just rebuild the action
  router and prompt scaffolding.
- Implement loop-detection + stagnation nudges similar to browser-use.

Run the full Phase 13 bake-off (S1-S4) again on this harness. Compare
verified medians.

**Effort: l** (multi-day; new harness module, new prompt scaffolding,
new tests).

**Decision rule:** if any stack on the custom harness clears the
Phase 13 promotion bar, that's the new default (model + harness pair).

### R5 — Stretch: page-state-rooted action contract

If R4 still hits add-to-cart-style failures on dynamic SPAs, the
issue may be that our action contract still re-targets *coordinates*
across page repaints. A more robust contract is to root actions in
visually-stable anchors:

- `click_relative_to(anchor_text, dx, dy)` — find text "$15.99 Add to
  cart" on the page (via OCR or DOM-text search), click at offset
  (dx, dy) from its center.
- `click_within(region_description)` — restrict the click to a
  bounding box derived from the model's natural-language description
  of the target.

These are model-friendly because they let the model express targets
the way it sees them ("click the Add to cart button next to the
$15.99 t-shirt"). But they require a richer page-state representation
than raw coords or DOM indices.

**Effort: l-xl.** Worth scoping only if R4 doesn't close the gap.

## Roadmap

```
R1 (small, decisive)
  ├─ pass → R2 (medium, low-risk uplift)
  │           ├─ pass → adopt; rerun bake-off
  │           └─ fail → R3 + R4
  └─ fail → R3 (research only)
              └─ findings inform whether to do R4 (large) or pivot
```

Total effort if all four happen: ~1-2 weeks of focused work. R1+R2
alone is 1-2 days and probably tells us most of the story.

## What this is NOT

- **Not a browser-use rejection.** browser-use's session/loop/eval
  infrastructure is good. The issue (if confirmed) is one specific
  layer (action vocabulary). R2 tries to fix that without leaving
  browser-use; R4 only happens if R2 isn't enough.
- **Not a custom-agent extension.** `scripts/custom_agent/` was built
  in Phase 11 as a coord-first CDP harness for canvas. R1 tests
  whether *that existing path* is enough for shopping; R4 only
  builds new infrastructure if the existing custom path falls short.
- **Not a model-fine-tuning project.** All experiments use the
  existing model weights. Fine-tuning a model to fit our harness is
  the *opposite* of the hypothesis; we're testing whether the *harness*
  should adapt instead.

## Open questions

1. Does saucedemo's "Add to cart" specifically reject CDP-synthesized
   click events (similar to how Excalidraw's Escape rejected JS
   `KeyboardEvent.dispatch`)? If yes, R1 will fail and we'd need
   trusted-input event sequences. Worth checking before R1.
2. How much of Phase 13's long-horizon failure was confabulation vs.
   genuine harness blocking? The screenshot audit showed agents
   claiming progress they hadn't made. Are we sure browser-use's loop
   is even reaching the action-execution stage on every step? Worth
   instrumenting the harness to log "the action I tried and the actual
   element it landed on."
3. Is there a public benchmark that already isolates "harness fit"?
   The WebVoyager / Online-Mind2Web benchmarks scored frontier models
   on browser-use-shaped tasks. If a frontier API model + browser-use
   gets ~70% on the same kind of long-horizon flow, the harness is
   adequate for that scale; if it also caps at <20%, the harness is
   fundamentally unsuitable.

## Acceptance for this research

- A `findings.md` Phase 14 entry summarizing R1's result.
- A `findings.md` Phase 15 entry summarizing R2's result (if R1 passed)
  OR R3+R4's result (if R1 failed).
- A clear go/no-go on whether to invest in R4 (custom harness build).
- An updated default in `CLAUDE.md` if any combination clears the
  promotion bar.
