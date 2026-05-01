# Harness Iteration Loop — Design

**Date**: 2026-05-01
**Status**: Approved (design phase). Implementation plan pending via `writing-plans`.

## Purpose

The custom CDP harness (`scripts/custom_agent/`, `scripts/coord_remap.py`,
`scripts/harness_patches.py`) keeps producing long-tail bugs. Four are
already documented and fixed (wrong quant default, coordinate
double-remap, scroll clamp, iframe skip). There is no reason to think
that's the full set. Every undiscovered harness defect pollutes the
Pareto-frontier signal: when a smoke fails on BILLY or saucedemo CP3, we
cannot cleanly attribute the failure to model precision vs. another
harness gap we have not found yet. That is a problem for the project's
central question — *where do the cliffs sit, model-bound or
harness-bound?* — because the answer is only meaningful when the
apparatus is trustworthy.

This design produces:

1. A **regression suite** that pins what the harness must keep doing
   right (mechanical probe, two end-to-end trajectories, four targeted
   regression locks).
2. An **autonomous iteration loop** that uses the user's Claude Max
   subscription via the headless `claude` CLI as a hypothesis-driven
   debugger, capped at 20 iterations.
3. A **deterministic driver** that owns commit decisions, so safety
   logic stays in code rather than in the LLM's prompt.

## Out of scope

- Model evaluation, model swaps, quant changes, Thunder cloud sweeps.
- Browser-use harness changes (`scripts/smoke_browser_use.py`,
  `scripts/smokes/`). The custom CDP path is the harness under test.
- Any change to `web/`, `scripts/build_site.py`, `data/runs.jsonl`.

## Test suite

Lives under `tests/regression/` (new directory) with one wrapper at
`scripts/regression_suite.py`. Seven tests:

| # | Test | File / target | Cost | Initial state |
|---|------|---------------|------|---------------|
| 1 | 9/9 mechanical CDP probe | `scripts/saucedemo_flow_probe.py` (existing) | ~30 s | green |
| 2 | saucedemo full-flow E2E (custom CDP) | `scripts/custom_agent_tasks/saucedemo_full_checkout.py` driven via `scripts/custom_agent.py` | ~3-5 min | partial — CP1-CP2 reliable, CP3+ flaky on UI-Venus 8B |
| 3 | BILLY add-to-cart | `scripts/custom_agent_tasks/ikea_billy.py` driven via `scripts/custom_agent.py` | ~3-8 min | red on local 8B |
| 4 | Regression: wrong quant default | `tests/regression/test_swap_model_quant_defaults.py` — asserts each model's default quant in `scripts/swap_model.sh` matches the documented F-7 fix | <1 s | green |
| 5 | Regression: coordinate double-remap | `tests/regression/test_action_kind_coord_space.py` — asserts `dispatch` calls `grounding_remap` for `kind="click"` (UI-Venus 0-1000 norm) and bypasses it for `kind="click_at"` / `kind="click_then_type"` (Holo3 viewport-pixel) | <1 s | green |
| 6 | Regression: scroll clamp | `tests/regression/test_scroll_min_delta.py` — asserts `_scroll` produces a wheel delta with magnitude ≥ `_MIN_SCROLL_DELTA` (600) when the model emits a smaller span; sign preserved | <1 s | green |
| 7 | Regression: iframe skip | `tests/regression/test_js_click_iframe_skip.py` — asserts `_js_click_fallback` filters `IFRAME` from the `elementsFromPoint` stack and clicks the first interactive non-iframe; logs `[skipped N iframe]` | <1 s | green |

Tests 4-7 are **regression locks**, not net-new bug surfaces. They
currently pass; reverting any of the four documented fixes makes them
fail.

### Suite wrapper

`scripts/regression_suite.py` runs all seven, reports a JSON document:

```json
{
  "all_green": false,
  "duration_s": 312.4,
  "tests": {
    "saucedemo_probe":         {"pass": true,  "duration_s": 28.1, "log_excerpt": "..."},
    "saucedemo_full_checkout": {"pass": false, "duration_s": 184.0,"log_excerpt": "...CP3 timeout..."},
    "ikea_billy":              {"pass": false, "duration_s": 92.0, "log_excerpt": "..."},
    "regression_quant_default":{"pass": true,  "duration_s": 0.04, "log_excerpt": ""},
    "regression_coord_remap":  {"pass": true,  "duration_s": 0.05, "log_excerpt": ""},
    "regression_scroll_clamp": {"pass": true,  "duration_s": 0.03, "log_excerpt": ""},
    "regression_iframe_skip":  {"pass": true,  "duration_s": 0.04, "log_excerpt": ""}
  }
}
```

The wrapper:
- Runs E2E tests with `MAX_STEPS` capped (20 for saucedemo, 30 for
  BILLY) so a hung agent cannot stall the suite.
- Parses E2E pass/fail from the run-log JSON the custom-agent run
  produces (`category == "pass"` first, then `outcome ∈ {"done",
  "call_user"}` — same rule the findings webapp uses, encoded in
  `web/build_site._is_pass`).
- Writes per-test logs to `/tmp/regression_suite/<run_id>/<test>.log`
  for the driver to attach to `learnings.md`.
- Exits 0 if `all_green`, 1 otherwise.

## Driver

`scripts/iteration_loop.sh` (orchestrator) + `scripts/iteration_step.py`
(decision logic). The `claude` CLI is invoked once per iteration as a
subprocess. State across iterations lives in `learnings.md` and the git
history.

### Iteration step

Pseudocode:

```
for i in 1..20:
  before = run regression_suite.py             # JSON before any change
  if before.all_green and prev_iteration.all_green: break    # stable green → halt

  transcript = spawn `claude --print` with:
    --output-format json
    --append-system-prompt prompts/loop_system.md
    --allowed-tools "Read,Grep,Glob,Edit,Bash(.venv/bin/python -u scripts/regression_suite.py:*),Bash(git diff:*),Bash(git status:*)"
    stdin = prompts/loop_user.md.tmpl rendered with {iteration: i, learnings: <file>, before: <json>}

  after = run regression_suite.py              # driver re-runs, ground truth
  delta = compare(before, after)

  if after.all_green and not before.all_green:
    git add -A; git commit -m "iter <i>: <hypothesis> [+suite green]"
    append GREEN block to learnings.md
  elif strict_improvement(delta):              # more passes, no new fails
    git add -A; git commit -m "iter <i>: <hypothesis> [+partial]"
    append PARTIAL block to learnings.md
  else:                                        # regression or no-op
    git checkout -- .; git clean -fd tests/ scripts/ docs/  # revert iter's edits
    append REGRESSION or NO-IMPROVEMENT block to learnings.md
```

`strict_improvement(delta)` is `(after.passes ⊋ before.passes) ∧ (after.fails ⊆ before.fails)` — the iteration only counts as progress if it strictly grew the green set without reintroducing a red. This rule is the safety story for tests 4-7: a "fix" that breaks any regression lock is reverted, not committed.

### `learnings.md` schema

One block per iteration, append-only. Driver writes it; Claude reads
the running file but never mutates it directly.

```markdown
## Iteration N — 2026-05-01T03:14:22Z — VERDICT

**Hypothesis**: <one sentence Claude returned in its structured output>
**Change**: <files touched, line counts; full diff in commit `<sha>` or in /tmp/regression_suite/<run_id>/iter_N.diff if reverted>
**Suite delta**:
  - saucedemo_probe:         pass → pass
  - saucedemo_full_checkout: fail → pass
  - ikea_billy:              fail → fail (CP not reached: scroll past results)
  - regression_*:            all pass → all pass
**Outcome**: committed as `abc1234` | reverted (regression on `regression_iframe_skip`)
**Invalidates**: iteration <M> hypothesis "<...>" — <one-line explanation>
```

`Invalidates` is filled when the current iteration's diff overlaps a
prior iteration's reverted change in a way that contradicts the prior
hypothesis. Heuristic: file overlap + opposite-direction edit on the
same lines. Best-effort; missing it is acceptable.

### Claude's contract per iteration

System prompt (canonical text in `prompts/loop_system.md`):

- You are iteration N of 20 in an autonomous harness-hardening loop.
- Read `learnings.md` first. Do not repeat a hypothesis already marked
  REGRESSION or NO-IMPROVEMENT unless you have a substantive new reason.
- Read the failing test logs in `/tmp/regression_suite/<run_id>/`.
- Propose **exactly one** focused change. Edit the minimum set of
  files. Do not run `git add` or `git commit` — the driver does that.
- After editing, run `.venv/bin/python -u scripts/regression_suite.py`
  yourself once to sanity-check; if it goes green you can stop. Do not
  retry on failure within an iteration.
- Return a JSON summary on stdout (the `--output-format json`
  envelope already wraps it) with: `hypothesis`, `change_files`,
  `pre_run_suite_result`. The driver re-runs the suite as ground truth.

User prompt (canonical text in `prompts/loop_user.md.tmpl`): rendered
each iteration with the current `learnings.md` content, the most
recent `before` suite JSON, and the iteration index.

### Tool whitelist (claude CLI `--allowed-tools`)

```
Read, Grep, Glob, Edit
Bash(.venv/bin/python -u scripts/regression_suite.py:*)
Bash(.venv/bin/python -u scripts/regression_suite.py *:*)
Bash(git diff:*)
Bash(git status:*)
```

Explicitly **not** allowed: `Write` to outside the harness scope, `git
add`, `git commit`, `git push`, `rm`, model-swap scripts,
`scripts/thunder/*`, network egress beyond what the suite already
performs.

### Commit & safety policy

- Loop runs in a worktree at `~/Source/vision-model-harness-loop/<ts>`
  on branch `harness-loop/<ts>`. Never on `main`. Wraps `git worktree
  add` so the operator can `cd` into it and inspect mid-run.
- Per-iteration timeout: 60 min wall (kills the `claude` subprocess
  via `timeout(1)`). Records as `TIMEOUT` verdict.
- Loop wall budget: ~3 hours upper bound. Driver does no autonomous
  retry on `TIMEOUT`; counts as the iteration's outcome.
- Stop early if two consecutive iterations report `all_green`.
- The driver writes a final report regardless of how it terminated —
  early stop, exhaustion, or operator `Ctrl-C`.

### Final report (`reports/iteration_loop_<timestamp>.md`)

Generated by `iteration_step.py --finalize`. Contains:

- **Summary table**: iteration → verdict → suite delta → commit sha or
  revert reason.
- **What changed**: green / partial commits with diffs inline.
- **Still red**: tests that never passed and the unique hypotheses
  tried against them.
- **Invalidations chain**: explicit list of which fixes contradicted
  earlier hypotheses.
- **Cost estimate**: total wall clock, total `claude` invocations,
  approximate Max-subscription tokens (best-effort from CLI output).

## Operational notes

- The loop assumes UI-Venus-1.5-8B Q6_K is loaded on
  `vision-model.service` — the default. The driver does **not** swap
  models; if the suite needs a different model the operator does it
  out-of-band.
- Headed Chromium is required (CLAUDE.md operational rule). The
  driver inherits the operator's `DISPLAY`/`XAUTHORITY`/`XDG_RUNTIME_DIR`
  env, but it does **not** auto-launch Plasma — operator runs the loop
  from a logged-in session.
- All tests are deterministic given a fixed model; flake on saucedemo
  CP3 / BILLY is model precision, not test infrastructure. The driver
  records E2E results as recorded; the `strict_improvement` rule
  protects against accidentally committing a "fix" that just got
  lucky on one run because tests 4-7 will catch a real regression
  even if test 2 or 3 is flaky.

## Open risks

- **E2E flake masquerading as progress.** Mitigation: tests 4-7
  (regression locks) catch most "lucky" diffs. Residual risk: the
  loop converges on a hack that improves saucedemo CP3 by chance and
  is committed. Acceptable — the operator reviews the final PR.
- **Claude proposes the same hypothesis class repeatedly.** Mitigation:
  the system prompt forbids repeats absent a substantive new reason;
  prior `learnings.md` blocks are visible. Not foolproof.
- **The whole loop converges on nothing useful.** That's a fine
  outcome: you keep the regression suite, drop the loop, the
  overnight cost was one wall-clock window of a Max subscription that
  was already paid for.
- **Worktree state divergence.** If the operator works on `main` while
  the loop runs on its branch, normal git mechanics apply. The loop
  never touches `main`.

## File inventory (new and modified)

New:
- `scripts/regression_suite.py`
- `scripts/iteration_loop.sh`
- `scripts/iteration_step.py`
- `prompts/loop_system.md`
- `prompts/loop_user.md.tmpl`
- `tests/regression/__init__.py`
- `tests/regression/test_swap_model_quant_defaults.py`
- `tests/regression/test_action_kind_coord_space.py`
- `tests/regression/test_scroll_min_delta.py`
- `tests/regression/test_js_click_iframe_skip.py`

Modified:
- `CLAUDE.md` — short paragraph on running the regression suite.

Generated artifacts (gitignored):
- `learnings.md` (per-run; copied into the report)
- `reports/iteration_loop_<ts>.md`
- `/tmp/regression_suite/<run_id>/`

## Acceptance criteria for the design phase

- All four historical bugs map to a concrete regression test file path.
- The suite wrapper has a defined input/output contract (JSON shape
  above) consumable by both the driver and any future CI hook.
- The loop's safety story (driver owns commits, strict_improvement
  rule, worktree isolation, tool whitelist) is explicit.
- `learnings.md` schema is fixed before implementation so iterations
  produced from day one are comparable.
