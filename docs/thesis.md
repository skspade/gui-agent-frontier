# Thesis: A Pareto frontier for local GUI grounding agents

## The question

> For a given **task class X**, what is the minimum **(model size, harness
> sophistication)** pair that achieves **Y% reliability** at **Z× lower
> cost** than a frontier API model?

The contribution is not "model M is good enough for task T" — that's a
single point. It is the **boundary**: the cliff where smaller-model +
smarter-harness stops working and you have to spend parameters or API
dollars instead. Different task classes have different cliffs, and
*where* they sit is the useful output of this work.

This document supersedes the implicit single-point thesis ("can a local
8B GUI grounding model drive a browser?") that has been driving phase
work to date.

---

## Operationalization

### Reliability (Y)

Tier 1 — **production**: ≥95% pass rate at n≥10. Below that, retries
don't save you because tasks compound.
Tier 2 — **frontier sketch** (current): n=1–3, partial-pass scoring
(strict checkpoint count, lenient checkpoint count, or PASS/FAIL on
final state). The frontier mapping uses Tier 2 thresholds — typically
≥70% partial-pass — to find where cliffs sit before driving any cell
to Tier 1.

Pass criterion is task-class-specific (see below); scored mechanically
when possible (PASS/FAIL first-word in the final answer) and from the
post-run verification screenshot otherwise. Agent self-report is never
ground truth — see `docs/findings.md` Phase 2.

### Cost (Z)

Cost is **$/successful-task**, not $/token:

```
$/successful-task = (cost-per-attempt) / pass-rate
```

The Z multiplier is **local-stack cost vs. Claude Sonnet 4.6
computer-use** at current API rates (the most directly comparable
frontier baseline as of 2026-04). Local stack cost is amortized
hardware $/hour × wall-clock-per-task; tokens are free locally.

Below ~70% pass rate, retries amplify cost faster than they help, so
70% is the floor for a "Pareto-meaningful" cell. A cell that needs
retries to clear 95% effectively counts as a higher-cost cell.

### Task classes (X)

| Class | Description | Smokes (this repo) | Key challenge |
|---|---|---|---|
| **A** | Known-site, DOM-traversable, short horizon | `saucedemo_headed` | None significant — baseline. |
| **B** | Known-site, DOM, long horizon + grounding pinches | `saucedemo_full_checkout`, `saucedemo_backpack_only` | Cart-icon precision (~32px target), ordinal reasoning over a grid, state retention across 20+ steps. |
| **C** | Visual-grounding-required (canvas / shadow-DOM / non-indexable) | `excalidraw_drag`, `excalidraw_toolbar` | Pure pixel-coordinate grounding; introspection on screenshot ("did the click activate the right tool?"). |
| **D** | Novel real-world e-commerce | `ikea_search_add`, `ikea_billy`, `bestbuy_airpods` | Overlay/cookie/upsell dismissal, dense PDP layouts, search-result variant disambiguation. |

`saucedemo_headless` is intentionally excluded from frontier mapping —
Phase 2 showed Chromium's headless cart-icon click bug confounds the
model signal.

### Harness axes (H)

A **harness profile** is a tuple `(H1, H2, H3, H4)` over four axes.
Larger numbers = more sophisticated harness:

| Axis | 0 (minimal) | 1 (current default) | 2 (rich) |
|---|---|---|---|
| **H1. Action mode** | DOM-index-only | DOM + CDP coords (`Input.*` w/ JS fallback) | + custom drag / visual primitives (Phase 9 / 11) |
| **H2. Failure recovery** | none | stuck-loop detection (consecutive no-effect) | + URL-progression watchdog (F-4) + state-contradiction check |
| **H3. Prompt scaffolding** | task only | + "report failure honestly" + per-model harness path | + per-task-class recovery hints + few-shot examples |
| **H4. Verification** | model self-report | + post-run screenshot ground truth | + per-step state probe (URL/DOM hash assertion before continuing) |

Current default is `(1, 1, 1, 1)`. The reference frontier baseline
(Sonnet computer-use API) is approximately `(2, 1, 0, 0)` — more
parameters carrying more of the load, simpler harness.

---

## Frontier as currently known (2026-04-30)

Cells filled from Phase 2 → Phase 17. n is per-cell sample size; cells
without explicit n=… are n=1.

| Class | Model | Harness | Result | Source |
|---|---|---|---|---|
| A | UI-Venus 8B Q6_K | (1,1,1,1) | PASS in 22 steps | Phase 2 |
| B | UI-Venus 8B Q6_K | (1,1,1,1) | 4/9 strict | Phase 16 |
| B | MAI-UI 8B Q6_K | (1,1,1,1) | 6/9 strict; 2/3 success-page (n=3) | Phase 16, 17-fu |
| B | UI-Venus 30B-A3B Q3_K_M | (1,1,1,1) | 5/9 strict | Phase 16 |
| B | Holo3 35B-A3B IQ3_XXS | (1,1,1,1) | 3/9 strict | Phase 16 |
| B | bu-30b-a3b-preview Q3_K_M | (1,1,1,1) | 2/9 strict | Phase 16 |
| C-drag | UI-Venus 8B Q6_K | (1,1,1,1) | PASS in 4 steps | Phase 9 |
| C-drag | UI-Venus 8B Q6_K | (2,1,1,1) | PASS in 3 steps / 24s | Phase 11 |
| C-drag | MAI-UI 8B Q6_K | (1,1,1,1) | PASS in 3 steps | Phase 17 |
| C-toolbar | UI-Venus 8B Q6_K | (1,1,1,1) | PASS, clean (12/13 icons) | Phase 3 |
| C-toolbar | MAI-UI 8B Q6_K | (1,1,1,1) | PARTIAL (loop pathology, 30 steps) | Phase 17 |
| D | (any) | (1,1,1,1) | unknown — smokes added 2026-04-30 | Phase 18 (planned) |

---

## Cliffs we believe exist

Hypotheses to test, in decreasing-confidence order:

1. **B → C cliff is steeper than 8B → 35B inside any class.** UI-Venus
   8B beats Holo3 35B on B at the same harness. The cost of clearing C
   reproducibly across models is wider than the spread of model sizes
   we have on B.
2. **Class C is action-vocabulary-bound, not parameter-bound, at 8B.**
   Phase 11 cut Excalidraw drag from 4 steps to 3 steps with the *same*
   model and a richer H1 (custom CDP drag). Indicates the lever for C
   is harness, not parameters — at least for the drag sub-task.
3. **B has a precision sub-cliff at small targets.** Cart-icon (~32px,
   top-right) is the bottleneck for 4 of 5 models in Phase 16. A single
   richer harness primitive ("click element by visual description")
   might collapse the spread between models on this sub-task.
4. **D will look like B but with overlay-dismissal as the new precision
   wall.** The IKEA / Best Buy smokes added 2026-04-30 are the test.
5. **Class-conditional model selection beats a single default.** Phase
   17 already foreshadows this: MAI-UI is best for B (long-horizon
   planning), worse for C-toolbar (introspection / "stop when
   verified"). A per-class default is probably the right operational
   posture once the frontier is mapped.

---

## What's "filling a cell" mean

A cell is `(class, harness, model)`. To call it filled at Tier 2:

- n ≥ 3 runs on the post-2026-04-29 dispatcher (silent-CDP-drop fix
  applied — pre-fix runs are lower bounds, not measurements).
- Strict + lenient pass rates recorded with the same scorer.
- Verification screenshot kept for each run.
- Result appended to `docs/findings.md` under the phase that covered it.

Tier 1 (n ≥ 10, ≥95%) is reserved for cells we want to defend
operationally — not yet attempted.

---

## Anti-goals

- **Not a leaderboard.** Picking "the best model" is the wrong question;
  the right question is which (class, harness, model) cell minimizes
  $/successful-task at the target reliability tier.
- **Not a generic GUI-grounding benchmark.** The corpus is small (≤10
  smokes) and intentional — each smoke is positioned to test a specific
  cliff hypothesis, not to cover a domain.
- **No premature production claims.** n=1 / n=3 results are frontier
  sketches. Tier-1 claims require Tier-1 sample sizes.
