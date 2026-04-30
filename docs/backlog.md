# Backlog

Concrete, hand-offable work items for the `vision-model` project. Each
item is self-contained: an agent picking this up should not need any
context beyond `CLAUDE.md`, `docs/findings.md`, and this file.

Read `docs/findings.md` first for the *why* behind every item — it has
the trail of what was tried, what worked, and what surprised us. The
backlog references findings sections rather than re-explaining them.

---

## Item ordering

Items are tagged with effort (`xs` / `s` / `m` / `l`) and a one-letter
priority bucket so they can be picked up in any order:

- **C — cleanup**: small, safe, no risk
- **E — experiment**: validates an open question
- **F — feature**: adds capability
- **S — strategic**: changes direction or architecture

Pick by reading the bucket + acceptance criteria — anything in **C** can
be done without reading the whole doc.

---

## E-7 — MAI-UI-8B promotion gate: re-run Phase 12 toolbar smoke
**Effort: xs · Priority: E · Status: pending**

Phase 16 (findings.md, 2026-04-30) found MAI-UI-8B is the new strict-
score leader on `saucedemo_full_checkout` (6/9 vs UI-Venus 8B's 4/9).
Phase 12 had previously concluded MAI-UI is a regression on visual
grounding based on the Excalidraw toolbar smoke; that conclusion was
made on the pre-tooling-audit dispatcher.

Before promoting MAI-UI to default, re-run the Phase 12 smokes
(`smokes/excalidraw_toolbar.py` and `smokes/excalidraw_drag.py`) on
the current dispatcher. If MAI-UI's toolbar regression persists, the
default stays UI-Venus 8B and MAI-UI becomes a per-task model choice.
If MAI-UI ties or exceeds on toolbar/drag, promote to default.

### Acceptance
- ✅ Both Excalidraw smokes run against MAI-UI on current dispatcher.
- ✅ Findings entry with per-smoke verdict.
- ✅ Default-model decision: stay UI-Venus 8B, or promote MAI-UI.

---

## F-4 — URL-progression watchdog for confabulation-against-navigation
**Effort: s · Priority: F · Status: deferred**

Phase 16 finding 27: Holo3-35B-A3B burned 30+ steps alternating
between two coords on the inventory page that each navigated to
different product-detail pages. Each click registered as a real page
change (URL transition), so `no_effect=False` and the
consecutive-no-effect stuck-loop detector reset on every step. The
model narrated "successfully removed item" while bouncing between
product details that have no Remove button.

A complementary watchdog: track the URL after each step. If the URL
hasn't moved through any of the saucedemo flow's expected progression
(`/inventory.html` → `/cart.html` → `/checkout-step-one.html` →
`/checkout-step-two.html` → `/checkout-complete.html`) for ≥10
consecutive steps, exit early as `stuck_no_progress`.

Or, more general: count *distinct* URLs visited in the last N steps;
if N steps yield <3 unique URLs (excluding parametrized item ids),
flag stagnation.

### Acceptance
- ✅ Holo3's Phase 16 trajectory would now exit by step ~15 instead
  of step 39.
- ✅ UI-Venus 8B's Phase 16 trajectory (real progress through cart
  attempt) is NOT falsely flagged.

### Don't generalize prematurely
The Holo3 trajectory is the only known instance. If it doesn't
recur in the next bake-off (E-7-derived), this item stays deferred.

---

## S-2 — Reverse proxy + auth (only if needed)
**Effort: m · Priority: S · Trigger: only when exposing beyond `192.168.0.0/24`**

Current deployment is plain HTTP behind ufw, allowed only from
`192.168.0.0/24`. Adequate for LAN. Inadequate for VPN, Tailscale, or
public exposure.

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
There is no current external exposure requirement. Pick this up only
when there's a concrete need.

---

## Open questions tracked in findings.md (no specific work item yet)

These are explicitly recorded as "things we don't know yet" rather than
backlog items. If one becomes interesting enough to investigate, file a
new item here.

1. Does grounding accuracy degrade on visual tasks at Q4_K_M vs higher
   quants? Phase 5 contributed a Q5 data point on Excalidraw; a
   focused vision benchmark would close this.
2. Context budget: 32K worked for a 22-step run. What's the ceiling
   before KV quantization (`--cache-type-k q8_0`) is needed to keep
   VRAM in budget?
3. Is the model's recovery-from-failed-action weak because of model
   size (8B), training distribution, or prompt? Phase 6 partially
   probed prompt-level recovery; size/training-distribution would
   need ablations.
4. Is `saucedemo_full_checkout`'s CP3 (Add-to-cart precision on a
   2-column product grid) an unreasonably hard target for 8B-class
   models at IQ3/Q3? A simpler precision benchmark — single known
   item, then straight to checkout — would isolate fine spatial
   precision from long-horizon planning. Worth filing as an item if
   E-6's results suggest the wall is structural rather than
   model-specific.

---

## Conventions for picking up a backlog item

- Read `CLAUDE.md` and the relevant `docs/findings.md` section before
  starting. The lessons there were costly to learn; honor them.
- For any privileged step, write a script to `/tmp/foo.sh` and invoke
  as `sudo bash /tmp/foo.sh ARG`. Never inline-quote sudo.
- For any agent run, redirect to a log file. Never pipe long-running
  commands through `head` / `tail`.
- For any visual claim, capture an independent screenshot. Don't
  declare success based on the agent's self-report.
- After completing an item: append a short outcome to
  `docs/findings.md` (Phase 4 or later). Mark this entry in the
  backlog as done by deleting it (`git rm` it from this file —
  history is in `findings.md`).
