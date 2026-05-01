# Backlog

Concrete, hand-offable work items for the `vision-model` project. Each
item is self-contained: an agent picking this up should not need any
context beyond `CLAUDE.md`, `docs/thesis.md`, `docs/findings.md`, and
this file.

**Read `docs/thesis.md` first** — it frames every experiment item below
as a cell-fill on the Pareto frontier (task class × harness profile ×
model). `docs/findings.md` is the running trail of what's been tried;
read the relevant phase before designing a new run.

---

## Item ordering

Items are tagged with effort (`xs` / `s` / `m` / `l`), a one-letter
priority bucket, and (where applicable) a **frontier cell tag** in the
form `[class=X, H=(h1,h2,h3,h4), model=…]` so the work's place on the
frontier is explicit:

- **C — cleanup**: small, safe, no risk
- **E — experiment**: validates an open question (most cell-fills live here)
- **F — feature**: adds capability (often advances a harness axis)
- **S — strategic**: changes direction or architecture (off-frontier or cross-cutting)

Pick by reading the bucket + cell tag + acceptance criteria.

---

## E-7 — Class D first-pass: 5 models × 3 e-commerce smokes
**Effort: m · Priority: E · Cell: `[class=D, H=(1,1,1,1), model=*]`**

The `ikea_search_add`, `ikea_billy`, and `bestbuy_airpods` smokes were
added 2026-04-30 but never run. Class D (novel real-world e-commerce
with overlays) is currently an all-empty row in the frontier table in
`docs/thesis.md`.

### Steps
1. Run each of the 3 D-class smokes against each of the 5
   active-registry models (15 runs). Use `/tmp/r2_bakeoff.sh`-style
   per-model swap + archive pattern from Phase 16.
2. Score: PASS/FAIL on the cart-contains-target-item criterion via
   final-screenshot inspection. Record overlay-dismissal step count
   separately (it's the candidate "new precision wall" from cliff
   hypothesis 4).
3. Append a Phase 18 section to `docs/findings.md` with the table.
4. Add the filled cells to `docs/thesis.md` "Frontier as currently
   known" table.

### Acceptance
- 15 runs completed (n=1 each) with logs + final screenshots archived.
- ≥1 model passes ≥1 D smoke, OR the failure modes are characterized
  (which overlay variant blocked which model).
- Cliff hypothesis 4 ("D will look like B but with overlay-dismissal as
  the new precision wall") confirmed or refuted in writing.

### Don't
- Don't do n=3 yet — that's a Tier-1-prep step. Tier-2 frontier sketch
  first.
- Don't add the BLAHAJ smoke back (`ikea_search_add` covers it; Phase
  17 follow-up showed BLAHAJ search is fragile).

---

## E-8 — Generalize Phase 11's H1=2 win across models on Class C
**Effort: m · Priority: E · Cell: `[class=C, H=(2,1,1,1), model=non-Venus]`**

Phase 11 cut Excalidraw drag from 4 → 3 steps using a custom CDP `drag`
primitive (H1=2) on UI-Venus 8B. We've never run that harness with any
other model, so we can't tell whether the H1=2 lift is model-specific
or general.

### Steps
1. Run `excalidraw_drag` on the custom-agent harness (the H1=2 path)
   against MAI-UI 8B, UI-Venus 30B-A3B, Holo3 35B-A3B, and
   bu-30b-a3b-preview.
2. Compare to each model's H1=1 drag result (where available — MAI-UI
   has Phase 17; others need an H1=1 baseline run alongside).
3. Append a phase section with the matrix; update
   `docs/thesis.md` cells.

### Acceptance
- ≥3 models run on both H1=1 and H1=2 paths.
- Step-count delta recorded per model.
- Cliff hypothesis 2 ("class C is action-vocabulary-bound, not
  parameter-bound at 8B") is supported, refined, or refuted with named
  models.

---

## E-9 — Frontier-API baseline for the Z multiplier
**Effort: m · Priority: E · Cell: `[class=A,B,C,D, model=Sonnet 4.6 computer-use]`**

`docs/thesis.md` defines Z as $/successful-task vs. Claude Sonnet 4.6
computer-use. We have no Sonnet runs, so Z is unanchored — every
"local is N× cheaper" claim is currently hand-wave.

### Steps
1. Run one representative smoke per class (A: `saucedemo_headed`, B:
   `saucedemo_full_checkout`, C: `excalidraw_drag` + `excalidraw_toolbar`,
   D: `ikea_search_add`) through Sonnet 4.6 computer-use, n=3 each.
2. Record: pass rate, mean wall-clock per task, mean tokens per task
   (input + output), API cost per task.
3. Compute $/successful-task. Add a "Frontier-API baseline" section to
   `docs/thesis.md`.

### Acceptance
- Per-class $/successful-task numbers anchored against API rates as of
  the run date.
- Z multiplier computable for any local cell. Cells in
  `docs/thesis.md` get an explicit Z column populated where comparable.

### Don't
- Don't hand-roll a custom Sonnet harness — use Anthropic's reference
  computer-use scaffolding so the comparison is "frontier-as-shipped",
  not "frontier as we'd customize it."

---

## F-4 — URL-progression watchdog for confabulation-against-navigation
**Effort: s · Priority: F · Status: deferred · Cell: `[class=B, H=(1,2,1,1)]`**

Phase 16 finding 27: Holo3-35B-A3B burned 30+ steps alternating between
two coords on the inventory page that each navigated to different
product-detail pages. The model narrated "successfully removed item"
while bouncing between product details. Phase 16's stuck-loop detector
only fires on consecutive *no-effect* steps; real navigation that
doesn't advance the task slips through.

This is a class-B harness advance from H2=1 to H2=2.

### Approach (pick one)
- **Specific**: track URL after each step; if the URL hasn't moved
  through any of the saucedemo flow's expected progression
  (`/inventory.html` → `/cart.html` → `/checkout-step-one.html` →
  `/checkout-step-two.html` → `/checkout-complete.html`) for ≥10
  consecutive steps, exit early as `stuck_no_progress`.
- **General**: count *distinct* URLs visited in the last N steps; if N
  steps yield <3 unique URLs (excluding parametrized item ids), flag
  stagnation.

### Acceptance
- Holo3's Phase 16 trajectory would now exit by step ~15 instead of
  step 39 (replay the saved log against the new detector).
- UI-Venus 8B's Phase 16 trajectory (real progress through cart attempt)
  is NOT falsely flagged.
- The Class-B row in `docs/thesis.md` gains a `(1,2,1,1)` column;
  re-run E-6 trajectories against the new harness to see whether the
  Holo3 / bu-30b strict scores recover.

### Don't generalize prematurely
The Holo3 trajectory is the only known instance. If it doesn't recur
in the next bake-off, this stays deferred.

---

## F-5 — UI-Venus-1.5-30B-A3B dispatch-hang on Best Buy AirPods task
**Effort: s · Priority: F · Status: open · Cell: `[class=D, model=UI-Venus 30B-A3B]`**

Phase 18 (`docs/findings.md`, 2026-04-30): two consecutive `bestbuy_airpods`
runs against UI-Venus-1.5-30B-A3B Q3_K_M wedged mid-run with no log
progress and no further screenshots written. Hang point differed
between runs (step 9 in run 1, step 4 in run 2) but the failure mode
was identical: `[step N] <action> -> ...` printed, then nothing for
49+ minutes; CDP `Runtime.evaluate` calls in `_scroll` /
`_input_probe` apparently stuck waiting on the renderer. `llama.cpp`
`/health` continued to report `{"status":"ok"}` throughout. Same
task ran clean on UI-Venus-1.5-8B Q6_K (PASS in 11 steps, 49.7s),
so the hang is not task-side.

Hypotheses (ranked):
1. **Renderer-side JS pause on Best Buy ad/tracking iframes blocks
   `Runtime.evaluate`.** 30B-A3B is slower per turn (~30-60s/step on
   the 32K-context path), giving the page longer to load heavy ad
   bundles between turns. CDP evaluate is synchronous w.r.t. the
   target's task queue; a long blocking script would stall it.
2. **Context overflow at ~step 4-9.** Each screenshot adds ~17K
   tokens of context. By step 4-9 the prompt may straddle 32K. If
   llama.cpp's behavior under prompt-too-long is to silently stall
   the request (rather than truncate or return an error), we'd see
   exactly this — except the hang is in dispatch *after* model_step
   returned, which weakens this hypothesis.
3. **Headed-Chromium GPU-process fault under mesa/RADV.** Phase 16
   hit unrelated headed-Chromium quirks; 30B-A3B's longer think
   times keep the renderer alive long enough that crashes /
   recoveries land mid-CDP-call.

### Approach
1. Add a Runtime.evaluate timeout in `scripts/custom_agent/browser.py`.
   If a probe / scroll-y read takes >5s, cancel the CDP call and log
   `[dispatcher] CDP evaluate hung after 5s — bailing`. Surfaces
   which call hangs (probe? scrollY? mouseWheel?) without changing
   harness semantics.
2. Capture `Runtime.consoleAPICalled` events for the duration of a
   30B-A3B Best Buy run; correlate hang timestamps with renderer
   console output to confirm/refute hypothesis 1.
3. If hypothesis 1 is confirmed: add `--blink-settings=...` or
   network-level ad-blocking to the launch flags so heavy ad scripts
   don't pause the renderer for the duration of a turn.

### Acceptance
- Cause confirmed (which CDP call hangs and why) with a reproduction
  log.
- 30B-A3B can complete `bestbuy_airpods` end-to-end OR a documented
  workaround exists (ad-block flag, longer timeouts, model-side
  config change).

### Don't
- Don't generalize to "30B-A3B is broken" — the hang is task-specific
  (Best Buy) and dispatch-side, not a model regression. Other Class
  D tasks may not exhibit this.
- Don't fix by switching the default away from 8B — 8B is already the
  default; this is about making 30B-A3B *also* viable for Class D, not
  replacing 8B.

---

## F-6 — Scroll-direction convention mismatch: UI-Venus uses swipe, dispatcher uses wheel
**Effort: xs · Priority: F · Status: open · Cell: `[class=D, H=(2,1,1,1)]`**

Phase 18 (`docs/findings.md`, 2026-04-30): `ikea_billy` regression on
UI-Venus-1.5-8B Q6_K stuck-looped after the model landed on the BILLY
PDP at scrollY=0 and emitted five consecutive `Scroll(direction='up')`
actions while *describing* "scroll down to bring 'Add to bag' into
view" in its conclusion text. The dispatcher follows desktop wheel
convention (`direction='up'` → CDP `mouseWheel` deltaY=-600 →
viewport scrolls UP → can't go above top), so all five scrolls were
no-ops; stuck-loop early-out fired at step 9.

UI-Venus's training is mobile-grounding-heavy and uses *swipe*
convention: `direction='up'` means "swipe up" → content moves up →
user sees content below → colloquially "scroll down". Same word,
opposite meaning.

The mismatch was masked until now because every previously-passing
smoke that needed scrolling either (a) used start/end coords (which
encode direction as a delta sign and were correctly interpreted) or
(b) didn't scroll at all (Excalidraw, search-result-only flows). BILLY
is the first task to land on a PDP at scrollY=0 and need a
no-coords directional scroll.

### Approach (pick one)
1. **Reverse the dispatcher's direction mapping.** Treat `up` as
   "see content below" (dy=+step) and `down` as "see content above"
   (dy=-step). Matches UI-Venus training; risk: breaks any future
   model that uses desktop wheel convention. Likely safe — Holo3 and
   MAI-UI both emit start/end coords, not direction keywords.
2. **Add explicit convention to the prompt** in
   `scripts/custom_agent/model.py:106` — change
   `direction='down/up/right/left'` to
   `direction='down/up' (down=see content below, up=see content above)`.
   Lower-risk but trusts the model to follow the spec under context
   pressure.
3. **Both** for belt-and-suspenders.

### Acceptance
- `ikea_billy` reaches Add-to-bag and PASSes on UI-Venus-1.5-8B Q6_K.
- `bestbuy_airpods` v3 trajectory unchanged (it used start/end coords,
  so neither approach should regress it).
- A short note added to `docs/findings.md` Phase 18 / F-6 record
  showing the BILLY pass after the fix.

### Don't
- Don't conclude UI-Venus is "broken" — the convention mismatch is
  symmetric, and either side could be called wrong. The dispatcher
  is the right place to fix because we control exactly one harness
  serving N models.
- Don't fix this as part of an unrelated phase; it deserves its own
  before/after log.

---

## E-10 — Tier-1 verify state-anchoring lift on `saucedemo_full_checkout`
**Effort: m · Priority: E · Cell: `[class=B, H=(1,1,1,1)+P1, model=Holo3 35B-A3B]` (and UI-Venus 8B if Holo3 confirms)**

Phase 19a (`docs/findings.md`, 2026-04-30): `saucedemo_full_checkout`
moved from 1/9 (Phase 19) to 3/9 (Phase 19a) across 3 models, and Holo3
specifically went 1/3 → 3/3. The hypothesized mechanism is
**state-anchoring** — the cart-state line in the prompt acts as a
working-memory aid across the 9 checkpoints, not just a termination
signal. This is the strongest candidate the project has for a Tier-1
attempt (n≥10, ≥95% pass rate per `docs/thesis.md`).

If Tier-1 confirms the lift, the implication is broader than this one
task: it generalizes "cart-state probe" into "deterministic state
probe" as a long-horizon harness primitive. URL, focused-element,
scroll-position, etc. could each be similar working-memory aids.

### Steps
1. n=10 on `saucedemo_full_checkout` against Holo3-35B-A3B IQ3_XXS at
   harness `(1,1,1,1)+P1`. Use the `PHASE=tier1_e10` env var so rows are
   distinguishable from Phase 19/19a.
2. If pass rate ≥ 95%: file as the project's first Tier-1 cell. Re-run
   the same n=10 against UI-Venus-1.5-8B Q6_K to see if the lift
   generalizes off Holo3.
3. If pass rate < 70%: Phase 19a's 3/3 was upper-tail luck; document and
   close.
4. Append outcome to `docs/findings.md` Phase 20.

### Acceptance
- 10 runs logged under `phase=tier1_e10`. Per-run screenshots archived.
- Pass rate computed and recorded.
- If ≥95%, the cell is marked Tier-1 in `docs/thesis.md`. If between
  70-94%, document as Tier-2 confirmation. If <70%, refute the surprise.

### Don't
- Don't try Tier-1 on bestbuy_airpods or saucedemo_full_checkout for
  MAI-UI — the n=3 numbers (0/3 and 0/3) don't suggest a Tier-1-eligible
  cell exists for those.
- Don't add new harness primitives between this and the Tier-1 attempt
  — confound-free.

---

## S-2 — Reverse proxy + auth (off-frontier; only if needed)
**Effort: m · Priority: S · Trigger: only when exposing beyond `192.168.0.0/24`**

Current deployment is plain HTTP behind ufw, allowed only from
`192.168.0.0/24`. Adequate for LAN. Inadequate for VPN, Tailscale, or
public exposure. Unrelated to the frontier; here to capture the
deployment work if/when it's needed.

### Steps
1. Install Caddy: `sudo pacman -S caddy`.
2. `/etc/caddy/Caddyfile`:
   ```
   ui-venus.example.tld {
       reverse_proxy localhost:8080
       basicauth /v1/* {
           api-user JDJhJDE0...   # bcrypt hash
       }
   }
   ```
3. Tighten ufw to only allow Caddy's port from the wider network, not
   8080 directly.

### Acceptance
- LAN clients still work over `http://192.168.0.159:8080` (unchanged).
- External clients get auth-required from `https://ui-venus.example.tld`.
- HTTPS via Caddy's automatic Let's Encrypt (or Tailscale-internal TLS
  if appropriate).

### Don't do this preemptively
There is no current external exposure requirement.

---

## M-1 — Add UI-Venus-Ground-72B to the parameter-cliff matrix
**Effort: m · Priority: M · Trigger: when next probing 70B-class on Class C**

`inclusionAI/UI-Venus-Ground-72B` (https://huggingface.co/inclusionAI/UI-Venus-Ground-72B)
is the 72B sibling of our default `UI-Venus-1.5-8B`. Same family, same
training distribution — gives a clean parameter-step probe (8B → 72B
within Venus) that's apples-to-apples in a way the cross-family
Holo3 35B-A3B / Qwen2.5-VL-72B comparisons aren't.

### Steps
1. Verify GGUF availability — search HF for converted weights
   (mradermacher, bartowski, unsloth, ggml-org, inclusionAI's own repos).
2. If no public GGUF: convert from the safetensors via llama.cpp's
   `convert_hf_to_gguf.py` + `llama-quantize` on a Thunder instance
   (~150 GB persistent disk needed; bf16 weights ~144 GB).
3. Add registry entry to `scripts/swap_model.sh` and
   `scripts/thunder/swap_model_remote.sh`.
4. Determine harness path. Likely `uivenus` (`<action>`/`<conclusion>`
   tag grammar — same as the 8B), but verify with
   `scripts/thunder/validate_harness.py` after first load.
5. Run on the canonical class-C / class-B / class-D probes for
   apples-to-apples comparison vs UI-Venus-1.5-8B.

### Acceptance
- GGUF on disk (Thunder or local depending on quant + VRAM fit) and
  swap-script entries land cleanly.
- One full pass against `excalidraw_drag` (class C), one against
  `saucedemo_full_checkout` (class B), one against `bestbuy_airpods`
  (class D) — n=1 each. Findings note the new cell on the frontier.

### Why
The current 70B-class data point on the frontier is Qwen2.5-VL-72B,
which is a different family (different RL recipe, different vision
encoder bias). UI-Venus-Ground-72B isolates "what does +9× parameters
do *within the same training distribution*" from the family confound.
Phase 21's saucedemo task-understanding regression on Qwen-72B is
exactly the kind of finding that needs a within-family control.

---

## C-3 — Backfill thumbnails for the findings webapp by re-running smokes with durable summary.json
**Effort: s · Priority: C · Cell: n/a (webapp data quality)**

The findings webapp at `web/index.html` (built by `scripts/build_site.py`)
shows an empty side panel for most runs because their screenshots were
never persisted. Specifically:

- ~118 rows in `data/runs.jsonl` record `final_screenshot=/tmp/custom_agent_final.png`,
  which is overwritten by the next smoke. The build script (post-2026-05-01
  fix in commit `2f5cd74`) correctly skips `/tmp/...` paths because they
  used to silently produce 118 *identical* fake thumbnails.
- The fallback in `build_sweep_index` only reads sweeps that have a
  top-level `summary.json`. Today only the four excalidraw thunder sweeps
  (`20260430-212754`, `20260501-010141`, `20260501-011125`, `20260501-011611`)
  emit one. The two cart-task sweeps (`20260430-cart-qwen72b`,
  `20260501-cart-qwen72b-phase22`) have durable per-run `final.png` files
  under `<sweep_id>/<task>/run-N/final.png` but no `summary.json`, so the
  resolver doesn't see them.

Goal: re-run the smokes whose cells are missing thumbnails, producing
per-run `summary.json` + durable screenshot paths so the webapp's side
panel actually shows useful evidence.

### Steps

1. **Inventory the gaps.** Run `.venv/bin/python scripts/build_site.py`
   and list the (model, test) cells whose runs all have `screenshot: null`
   in `web/index.html`'s embedded payload. This is the backfill target
   set. Today (2026-05-01) that's roughly all 19 non-empty cells —
   Class A/B/D rows.
2. **Pick a runner.** Two paths, in increasing order of cost:
   - **Local re-run via `scripts/smoke_browser_use.py`** (preferred for
     8B models that fit on the AMD 9070 XT). Currently writes
     `/tmp/smoke_final.png` only; needs a small extension to also write
     a `data/sweeps/<run_id>/<task>/<model>_<quant>/run-N/{final.png,summary.json}`
     bundle that mirrors `scripts/thunder/sweep.py`'s output schema. ~30
     LOC plus a `--archive-to <dir>` flag. Once that flag exists, the
     existing smokes can be re-run end-to-end with no other changes.
   - **Thunder sweeps via `scripts/thunder/sweep.py`** (required for
     30B+ models that don't fit local VRAM). Already emits the right
     schema. Cost: ~$1–2 of A100 time per full sweep. Provisioning +
     teardown stay user-confirmable per `CLAUDE.md`.
3. **Run the backfill.** For each gap cell, run n=3 of the smoke and
   archive to `data/sweeps/<run_id>/...` with `summary.json`. Don't
   conflate this with frontier re-measurement — these are *the same
   smokes that already populated `runs.jsonl`*, just with persisted
   screenshots.
4. **Rebuild the site** (`.venv/bin/python scripts/build_site.py`) and
   verify thumbnails populate the side panel for every cell that was
   re-run. The pre-existing `runs.jsonl` rows are left untouched — the
   resolver pairs new sweep entries to them via the existing fallback.
5. **Update `docs/findings.md`** with one short paragraph noting the
   backfill, the cells re-run, and any unexpected score drift (if a
   replay produces a different pass rate, that's frontier-relevant
   noise and worth flagging).

### Acceptance

- `web/index.html` rebuilds with ≥1 thumbnail visible per non-empty
  cell in the backfill target set.
- For any cell whose backfill score disagrees with the original
  `runs.jsonl` score by ≥1 of n, the discrepancy is noted in
  `docs/findings.md`.
- If the local-runner extension was needed (option 2a above), the
  `--archive-to` flag is documented in `CLAUDE.md`'s "Browser-use
  smoke tests" section.

### Don't

- **Don't extend `build_sweep_index` to read sweep layouts that lack
  `summary.json`.** That would add a second, undocumented schema and
  embed a parser for run-log inference. The right fix is to make new
  sweeps write `summary.json`, not to teach the consumer about every
  legacy directory shape.
- **Don't backfill cells you don't intend to keep on the frontier.**
  If a cell is going to be retired (e.g. a model dropped from the
  active registry), skip it — there's no point persisting evidence
  for a row the matrix will eventually delete.
- **Don't re-run sweeps as part of frontier re-measurement.** Backfill
  is operational; cell-fills are experiments. Mixing them muddies
  `findings.md`.

---

## Open questions (not yet sized as work items)

These are explicitly recorded as "things we don't know yet" rather than
backlog items. If one becomes interesting enough to investigate, file a
new item here — most will end up as cell-fill experiments tagged
`[class=…, H=…, model=…]`.

1. **Quant × visual-grounding ablation.** Does grounding accuracy
   degrade on Class C tasks at Q4_K_M vs higher quants? Phase 5
   contributed a Q5 data point on Excalidraw toolbar with an anomaly;
   a focused C-class quant ablation would close this. (Cell:
   `[class=C, H=(1,1,1,1), model=UI-Venus 8B × {Q4,Q5,Q6}]`.)
2. **Context budget ceiling.** 32K worked for a 22-step run. What's
   the ceiling before KV quantization (`--cache-type-k q8_0`) is
   needed to keep VRAM in budget? Most likely binds on Class B/D
   long-horizon runs.
3. **Recovery-from-failed-action: model size, training distribution,
   or prompt?** Phase 6 partially probed prompt-level recovery; the
   size/training-distribution ablation has not been run. Probably a
   harness-axis-H3 question (per-task-class recovery hints).
4. **Saucedemo CP3 ordinal-on-grid: structural cliff or model-specific?**
   `saucedemo_full_checkout`'s CP3 (Add-to-cart precision on a 2-column
   product grid after sort) was a binding wall for 4 of 5 models in
   Phase 16. `saucedemo_backpack_only` is the simpler probe; running it
   across all models would isolate fine spatial precision from
   long-horizon planning.
5. **Tier-1 reliability at any cell.** No cell has n≥10 yet. Once
   E-7/E-8/E-9 land, the strongest Tier-2 cell (currently MAI-UI 8B ×
   class B at 6/9 strict, n=1) is a candidate for first Tier-1
   attempt. The interesting question: does n=10 confirm 6/9 strict, or
   does the variance push it down toward UI-Venus 8B's 4/9?

---

## Conventions for picking up a backlog item

- Read `CLAUDE.md`, `docs/thesis.md`, and the relevant `docs/findings.md`
  section before starting. The lessons there were costly to learn.
- For any privileged step, write a script to `/tmp/foo.sh` and invoke
  as `sudo bash /tmp/foo.sh ARG`. Never inline-quote sudo.
- For any agent run, redirect to a log file. Never pipe long-running
  commands through `head` / `tail`.
- For any visual claim, capture an independent screenshot. Don't
  declare success based on the agent's self-report.
- After completing an item: append a short outcome to
  `docs/findings.md` and update the relevant cell(s) in
  `docs/thesis.md`. Mark this entry as done by deleting it from this
  file (`git rm`) — history is in `findings.md`.
