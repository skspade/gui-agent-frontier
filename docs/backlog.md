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
   quants? (Item C-2 contributes a Q5 data point but a focused vision
   benchmark would close this.)
2. Context budget: 32K worked for a 22-step run. What's the ceiling
   before KV quantization (`--cache-type-k q8_0`) is needed to keep
   VRAM in budget?
3. Is the model's recovery-from-failed-action weak because of model
   size (8B), training distribution, or prompt? (E-1 partially probes
   this for prompt; the others would need ablations.)

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
