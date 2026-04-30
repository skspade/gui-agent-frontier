# Handoff: end of Phase 1 (cart-state verification)

**Snapshot date:** 2026-04-30 evening, after commits `3264c16..aae3df9` (17 commits).
**Working tree:** clean. **Branch:** `main`. **Server state:** on `ui-venus-1.5-30b-a3b` Q3_K_M (left over from F-7 verification — swap freely; the project default per `CLAUDE.md` is `ui-venus-1.5-8b`).

---

## What got done

The master plan at `docs/plans/2026-04-30-harness-environmental-noise-reduction.md` was executed end-to-end through Phase 1. Phases 2–5 are stubbed in the plan and intentionally NOT expanded — re-expand each one after the prior phase's measurement.

**Phase 0 (baseline scaffolding):**
- F-6 scroll-direction fix with empirical retry on no-progress (`f61feea`, `853d26a`)
- JSONL run logger at `data/runs.jsonl` (`eed106f`)
- Failure-category classifier (`d9c460c`)
- Phase 19 baseline: 45 of 75 runs (3 of 5 models — F-7 blocked the other 2; F-7 is now fixed)
- Phase 19 findings + frontier-table refresh + F-7 backlog (`7c2144f`)

**Phase 1 (Priority 1: cart-state verification):**
- Per-site cart-state config registry (`5a9ef62`)
- `verify_cart_state` probe with localStorage → DOM strategy chain (`a078f0b`, `578bc20`)
- Wired into the run loop via the `previous_actions` block (`204354f`)
- **JS unbalanced-brace bugfix** that unblocked the entire probe (`53b0b3f`) — the probe was nominally wired but actually returning `verification_method='none'` on every page because the f-string built JS with 3 closing braces for 2 opens. Mocked tests bypassed the V8 parser and missed it.
- Calibrated IKEA + Best Buy selectors against live sites (`80eeebd`)
- `PHASE` env var for distinguishing baseline vs re-measurement rows (`d2742cd`)
- Phase 19a re-measurement: 45/45 runs, findings + thesis update (`1609eec`)
- Final code review with non-blocking follow-ups: `.gitignore data/`, file E-10 (`2847b05`)

**F-7 (resolved separately):**
- Root cause was a **missing per-model `QUANT` default** in `swap_model.sh`, not a runtime issue. Hypothesized as VRAM-race / daemon-reload-race / loader-bug; all three were wrong. Script bailed at file-not-found in <100ms, never touched systemd. Fix at `239266b`; corrected docs at `aae3df9`.

---

## Three thesis-grade findings to remember

These shape what's worth doing next. Full discussion in `docs/findings.md` Phase 19/19a sections.

1. **MAI-UI-8B's 0/15 baseline was task-level looping**, not model regression. Cart-state injection lifted it to 2/15 — the two passes are on `saucedemo_backpack_only` (the simplest task). On longer flows MAI-UI still 0/3, because cart-state alone doesn't replace task decomposition. **Refined hypothesis: cart-state rescues self-termination on single-action add-and-stop flows, not multi-step planning.**

2. **Holo3-35B-A3B (67%) beats UI-Venus-1.5-8B (53%)** at the same `(1,1,1,1)` harness — reverses cliff hypothesis #1 from `docs/thesis.md`. Two interpretations to test: (a) Phase 16's strict-checkpoint scorer under-credited Holo3, vs (b) the post-F6 dispatcher disproportionately favors Holo3. Both testable; out of scope without n>3.

3. **`saucedemo_full_checkout` lifted 1/9 → 3/9 at Phase 19a** (Holo3 specifically 1/3 → 3/3). This is the **state-anchoring effect**: cart-state in the prompt acts as a working-memory aid across the 9 checkpoints, not just a termination signal. **Strongest Tier-1 candidate the project has.** Filed as E-10 in the backlog.

Plus one operational finding: cart-state injection saves UI-Venus and MAI-UI ~15s of wall-clock per run (earlier termination). The cost-axis lift matters even when pass rate doesn't move — the Pareto frontier metric is `$/successful-task`, not pass rate alone.

---

## Where to pick up

Three high-value entry points, ordered by my read of value-per-hour:

### Option A — E-10 Tier-1 verification (~2 hours)
Run `saucedemo_full_checkout` × Holo3-35B-A3B at n=10 with `PHASE=tier1_e10`. If pass rate ≥95%, this becomes the project's **first Tier-1 cell** AND the state-anchoring hypothesis from Phase 19a graduates from "n=3 anomaly" to "real harness primitive worth generalizing." If <70%, refute and close. Steps spelled out in `docs/backlog.md` E-10.

### Option B — Phase 19b (now-unblocked cells) (~3 hours)
F-7 unblocked 30B-A3B and bu-30b-a3b-preview. The 10 missing frontier cells (2 models × 5 tasks at `(1,1,1,1)+P1`) can now be filled — 30 runs total at ~3 min/run for the MoE class. Note: only Phase 19a-equivalent cells are recoverable (Phase 19 baseline is permanently empty for those models since the probe is wired in now). Use the existing `/tmp/baseline_phase19a.sh` template, adjust the `MODELS=` array to `(ui-venus-1.5-30b-a3b bu-30b-a3b-preview)`, set `PHASE=19b`. Outcome would tell us whether the MoE class **escapes** MAI-UI's task-loop pathology by virtue of having more parameters.

### Option C — Phase 2 (Priority 2: pre-flight DOM cleanup) (~6-8 hours)
Targets `bestbuy_airpods` 0/9 directly — the agent never reaches add-to-cart under the BB ad-overlay storm. Pre-flight modal/overlay dismissal before the model sees the first screenshot. Stub already in the plan; needs expansion to bite-sized tasks. **Don't expand Phase 2 in detail until Option A or B's measurement is in** — both could shift Phase 2's expected impact.

My recommendation: **A first**, since it's the smallest experiment with the most thesis-shifting potential. B second if you want frontier completion. C only after A or B.

---

## Files of importance (for context recovery)

- **Master plan**: `docs/plans/2026-04-30-harness-environmental-noise-reduction.md` — Phase 0/1 detailed, Phases 2–5 stubbed.
- **Findings trail**: `docs/findings.md` last ~400 lines = Phase 19 + Phase 19a + F-7 resolution. Read these before changing the harness.
- **Frontier table**: `docs/thesis.md` lines 86–124. The `(1,1,1,1)+P1` rows are Phase 19a; the `(1,1,1,1)` rows are Phase 19. **Notation note documented inline** at the bottom of the table.
- **Backlog**: `docs/backlog.md` — E-10 (Tier-1), F-5 (UI-Venus 30B-A3B Best Buy hang, still open). F-7 has been removed (resolved).
- **Run data**: `data/runs.jsonl` — gitignored. 105 rows: ~60 untagged (Phase 19 baseline + ad-hoc smoke runs from tasks 0.2/0.3/1.3/1.4 calibration) + 45 tagged `phase: "19a"`. The phase-tag was added mid-project at `d2742cd`; pre-tag rows are disambiguated by timestamp:
  - 14:01–14:07 = Tasks 0.2/0.3 smokes (ui-venus-1.5-8b only)
  - 14:11–15:40 = Phase 19 baseline (3 models × 5 tasks × n=3 = 45 rows)
  - 15:50–16:30 = Task 1.3/1.4 calibration smokes (mostly ui-venus-1.5-8b)
  - 16:39–18:04 = Phase 19a re-measurement (45 rows tagged `phase: "19a"`)
- **Plan-execution memory**: `/home/seans/.claude/projects/-home-seans-Source-vision-model/memory/MEMORY.md` — has the project framing + the user's feedback memories.

---

## Operational state to know

- **Inference server**: `vision-model.service` is up. Currently serving `ui-venus-1.5-30b-a3b` Q3_K_M (left over from my F-7 verification). Swap to whatever you need:
  - `sudo bash scripts/swap_model.sh ui-venus-1.5-8b` (default for most work)
  - `sudo bash scripts/swap_model.sh holo3-35b-a3b` (E-10 Tier-1)
  - The Q3_K_M default is now baked in for the 30B-A3B and bu-30b-a3b-preview cases (F-7 fix), so no quant arg needed.
- **Display env vars**: required for any headed-Chromium smoke run.
  ```
  DISPLAY=:0 XAUTHORITY=/run/user/1000/xauth_rVYaGJ XDG_RUNTIME_DIR=/run/user/1000
  ```
- **Sudoers**: `/etc/sudoers.d/vision-model-swap` makes `swap_model.sh` passwordless for `seans`. `journalctl -u vision-model.service` is readable without sudo.
- **Baseline screenshots + per-run logs**: `data/screenshots/baseline/` and `data/screenshots/phase19a/` (gitignored). Each (model, task, run) has its own PNG and `.log`.

---

## Active assumptions worth re-checking before resuming

These were correct as of 2026-04-30 but could drift:

- **The 5 cart smokes are the right corpus** for the "cart task" framing. If the task class moves (e.g. checkout flows beyond add-to-cart, or class C visual-grounding gets layered in), the corpus needs to grow. Currently scoped to: `saucedemo_full_checkout`, `saucedemo_backpack_only`, `ikea_search_add`, `ikea_billy`, `bestbuy_airpods`.
- **3 of 5 models are the active baseline**. F-7 unblocks the other 2 but the Phase 19/19a numbers don't include them yet. Phase 19b would fix this.
- **Cart-state seed selectors are calibrated for the live sites as of 2026-04-30**. Sites change; if a future run shows `[cart-after]` lines disappearing on a previously-working site, re-run the calibration probe (template at `/tmp/probe_*` from this session — those got cleaned up; recreate from the patterns described in Task 1.4).

---

## How to resume in a fresh session

1. Read this handoff doc (you're doing it).
2. Read the Phase 19 + Phase 19a sections of `docs/findings.md` — that's the thesis context.
3. Skim the frontier table in `docs/thesis.md`.
4. Pick A, B, or C from the "Where to pick up" section.
5. If picking Option C (Phase 2), expand the stub in `docs/plans/2026-04-30-harness-environmental-noise-reduction.md` to bite-sized tasks first — don't dispatch implementers against a stub.

If anything in this handoff doesn't match what you observe (e.g., file paths shifted, models on disk changed, server not up), trust the current state and update this doc rather than working against stale assumptions.
