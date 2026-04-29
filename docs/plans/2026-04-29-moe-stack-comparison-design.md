# MoE stack comparison — five-way local VLM bake-off

Date: 2026-04-29

## Goal

Determine which locally-deployable stack is the most reliable agent for
browser tasks on the 9070 XT (16 GB VRAM) + 64 GB DDR5 box. Test five
candidate stacks against a shared smoke suite plus a new long-horizon
saucedemo task, then pick a winner using a documented scoring rubric.

This subsumes backlog item E-4 (UI-Venus-1.5-30B-A3B deploy) and extends
it to four additional candidates.

## Stacks under test

| # | Stack | Grounder | Planner | Harness |
|---|-------|----------|---------|---------|
| S1 | 8B baseline (current) | UI-Venus-1.5-8B Q6_K | (same) | browser-use |
| S2 | UI-Venus 30B-A3B end-to-end | UI-Venus-1.5-30B-A3B | (same) | browser-use |
| S3 | Holo2-30B-A3B end-to-end | Holo2-30B-A3B | (same) | browser-use |
| S4 | bu-30b native | bu-30b-a3b-preview | (same) | browser-use `ChatBrowserUse` |
| S5 | Split design | Holo1.5-7B | one of the 30B-A3B above | new harness |

S5's planner choice is decided after S2/S3/S4 scores are in: pick the
strongest 30B-A3B end-to-end runner as S5's planner. Rationale: the
split design is most defensible when the planner is independently the
best, otherwise we're stacking two unknowns.

## Constraints

- **VRAM**: 16 GB. 30B-A3B at Q4_K_M ≈ 17 GB weights — too tight with
  f16 mmproj + 32K KV. Plan for **Q3_K_M as the working quant** for all
  three 30B-A3B candidates; only attempt Q4_K_M if Q3 reveals quality
  issues. Document quant per stack in the results.
- **Disk**: `/mnt/data` (nvme1n1, 578 GB free) hosts the new models.
  `swap_model.sh` registry needs a configurable model root, or symlinks.
- **Speed is not a goal**. Per-step latency is informational, not a
  selection criterion.
- **Headed Chromium only** for the screening run. Headless rerun on the
  winner only.

## File layout

```
/mnt/data/models/
├── ui-venus-1.5-30b-a3b/
│   ├── ui-venus-1.5-30b-a3b-Q3_K_M.gguf       (~13 GB)
│   └── mmproj-ui-venus-1.5-30b-a3b-f16.gguf   (~1.2 GB)
├── holo2-30b-a3b/
│   ├── holo2-30b-a3b-Q3_K_M.gguf
│   └── mmproj-holo2-30b-a3b-f16.gguf
├── bu-30b-a3b-preview/
│   ├── bu-30b-a3b-preview-Q3_K_M.gguf
│   └── mmproj-bu-30b-a3b-preview-f16.gguf
└── holo1.5-7b/
    ├── holo1.5-7b-Q6_K.gguf                   (~5 GB)
    └── mmproj-holo1.5-7b-f16.gguf

~/models/                                       (existing 8B stays here)
├── ui-venus-1.5-8b/
└── mai-ui-8b/
```

`swap_model.sh` gains a `MODEL_ROOT` lookup per registry entry so it can
serve from either `~/models/` or `/mnt/data/models/` transparently.

## Test suite

### Existing smokes (regression guard, n=1 per stack)

- `excalidraw_drag` — canvas drag plumbing (mechanical action, baseline pass for both 8B variants)
- `excalidraw_toolbar` — visual grounding + active-state introspection (baseline confabulation hazard)
- `saucedemo_headed` — dense-DOM clickability (baseline cart-icon failure on 8B)
- `saucedemo_headless` — *skip in screening; rerun on winner*

### New long-horizon task (n=3 per stack)

`scripts/smokes/saucedemo_full_checkout.py` — single canonical 9-checkpoint
flow:

| # | Action | Discriminator |
|---|--------|---------------|
| 1 | Open https://www.saucedemo.com | trivial |
| 2 | Login as `standard_user` / `secret_sauce` | form fill |
| 3 | Sort products by "Price (low to high)" | dropdown interaction |
| 4 | Add the **third-cheapest** item to cart | ordinal visual reasoning |
| 5 | Add **"Sauce Labs Backpack"** by name | text grounding |
| 6 | Open cart, **remove the first item** | nested-anchor click (Phase 11 failure mode) |
| 7 | Checkout → fill First Name / Last Name / Postal Code | multi-field form |
| 8 | Continue → verify subtotal matches remaining item | numeric self-check |
| 9 | Finish → assert "Thank you for your order" page | terminal state |

Pass = checkpoint 9 reached with the correct final cart contents.
Partial-pass = highest checkpoint reached. Three discriminators are
intentionally sequenced early (steps 3–6) so a stack that fails on
ordinal reasoning still yields a graded score rather than a blanket fail.

## Scoring rubric

### Per-task

- **Long-horizon saucedemo (per run)**: `{checkpoints reached 0–9}`,
  `{steps used}`, `{recoveries triggered}` (count of "action did not
  change page → retry" loops). n=3 → report median + range.
- **Existing smokes**: `{pass | partial | fail}` + `{steps used}`. n=1.

### Aggregate winner: long-horizon-weighted

```
score(stack) = 3 × normalized(long_horizon_median)
             + 1 × normalized(drag)
             + 1 × normalized(toolbar)
             + 1 × normalized(saucedemo_headed)
```

`normalized(smoke) ∈ {0.0 fail, 0.5 partial, 1.0 pass}`.
`normalized(long_horizon) = checkpoints_reached / 9`.

Tiebreaker order: (1) higher score, (2) fewer recoveries triggered on
the long-horizon task, (3) fewer steps used.

The aggregate score is a tool for ranking, not for absolute claims —
the actual writeup in `findings.md` reports the underlying numbers and
the qualitative observations.

## Risks and mitigations

- **VRAM exhaustion at Q3**: if even Q3_K_M won't fit with f16 mmproj +
  32K KV, drop context to 16K (saucedemo prompts fit comfortably) or
  enable Q8 KV via `--cache-type-k q8_0`. Document any deviation as a
  caveat in the findings entry.
- **Bot detection on saucedemo**: low risk; saucedemo is purpose-built
  for automation and has no anti-bot layer. The Phase 11 cart-icon
  failure was a Chromium headless issue, not bot detection.
- **Run-to-run variance**: addressed by n=3 on the discriminating task.
  Smokes use n=1 because Phase 11 already established their failure
  modes are repeatable across runs.
- **Q3_K_M may quietly degrade grounding precision**: open question
  from existing findings. If three Q3 stacks all underperform the 8B
  Q6 baseline on grounding-precision-sensitive tasks (toolbar
  active-state, saucedemo cart icon), test the leading candidate at
  Q4_K_M as a follow-up before declaring a winner.
- **bu-30b license**: Browser Use OSS license has commercial-use
  restrictions. Read it before promotion to default; for the bake-off
  itself (research use), it's fine.
- **S5 planner selection bias**: deferring the choice of S5's planner
  until after S2/S3/S4 means S5 always uses the strongest available
  30B-A3B as planner. Documented bias.

## Phasing

The work fits into three sequential phases. Each phase ends with a
`findings.md` entry, and S5 is gated on S2–S4 results (per "S5 planner
selection" above).

1. **Setup**: free disk; configure `swap_model.sh` for `/mnt/data` root;
   download + convert + quantize all four new models; verify each
   serves cleanly via `vision-model.service` and `/health`.
2. **End-to-end runs (S1–S4)**: existing smokes (n=1) and long-horizon
   saucedemo (n=3) against each of the four single-model stacks. Score
   per rubric. Pick S5's planner from the winner of S2/S3/S4.
3. **Split-design run (S5)**: build minimal split harness (Surfer-H-CLI
   reference or custom router); run the same suite; score; declare
   overall winner.

## Acceptance

- ✅ All five stacks produce scores on the long-horizon saucedemo task
  (n=3) and the three regression smokes.
- ✅ A `findings.md` Phase 13 entry with the full scoring table, the
  declared winner, and qualitative observations per stack.
- ✅ A clear next-step recommendation: promote winner to default
  (update `swap_model.sh` registry + `CLAUDE.md`), or keep 8B baseline
  if no candidate clears the rubric.

## Out of scope

- Shopping-site smokes (Instacart, Home Depot, etc.) and bot-detection
  bypass (patchright, CloakBrowser). The research recommends these but
  they introduce too much uncontrolled variance for a 5-way screening.
  Schedule as a follow-up after a winner is named.
- WebVoyager benchmark reproduction. Same reason — over-budget for a
  screening run.
- FP8 / vLLM-ROCm / native-RDNA-4 kernel paths. The Vulkan + GGUF path
  is the proven runner; FP8 is a separate optimization track.
- `problem_user` resilience probe — winner-only follow-up.
