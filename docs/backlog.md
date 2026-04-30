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
