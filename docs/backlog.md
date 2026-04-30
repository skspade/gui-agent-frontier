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

## E-6 — 5-stack bake-off rerun on clean dispatcher
**Effort: s · Priority: E · Status: ready — E-5 landed 2026-04-30**

The Phase 14 follow-up bake-off ran on a dispatcher that silently
dropped CDP `Input.*` events on saucedemo's post-login pages
(documented in the 2026-04-29 saucedemo flow tooling audit). Every
wrong-target click was magnified by the bug; previous scores are
**lower bounds, not measurements**.

The dispatcher is now clean (`scripts/saucedemo_flow_probe.py` goes
9/9 with DOM-truth coords). But the per-model prompt mismatch (E-5)
means 4 of 6 models still can't actually reach the dispatcher with a
valid action. Rerunning before E-5 just reproduces the parse_error
failures.

Once E-5 lands: rerun `saucedemo_full_checkout` on UI-Venus 8B,
UI-Venus 30B-A3B, MAI-UI-8B, Holo2-30B-A3B, bu-30b-a3b-preview,
Holo1.5-7B, Holo3-35B-A3B. Compare against Phase 14 follow-up table
(findings.md). UI-Venus 8B's clean baseline is currently 2/9 strict;
that's the bar.

### Acceptance
- ✅ All 7 models reach at least step 5 of saucedemo (i.e. no
  parse_error or wrong-protocol failures — every score is a real
  capability measurement).
- ✅ Findings entry comparing pre-fix / post-fix scores per model.
- ✅ Verdict on whether any model promotes to default — the bar from
  Phase 13 is strict ≥3/9 OR lenient ≥5/9.

### Why this is *experiment*, not *strategic*
Same as E-5: yes/no question with a definite answer once the data is
clean. Strategic decisions (which model to default to, whether to
keep saucedemo as a benchmark) follow from the result.

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
