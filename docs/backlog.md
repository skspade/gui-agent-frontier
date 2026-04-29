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

## S-1 — Custom CDP client prototype
**Effort: l · Priority: S**

(F-2 done — remappers are in `scripts/coord_remap.py`. The merged 8B
model emits **0–1000 normalized** coordinates for grounding prompts; use
`grounding_remap(raw, css_viewport_size)` for that path. `navigation_remap`
is for the `<think>/<action>/<conclusion>` chat-template mode if/when this
prototype needs multi-step reasoning. See findings Phase 10.)

The Phase-2 findings show browser-use's DOM-indexed protocol leaves
UI-Venus's visual training mostly unused. A 200–300 line custom client
that does `screenshot → model → parsed action → CDP dispatch` — using
the model's *native* `<think>/<action>/<conclusion>` format — could
substantially outperform browser-use on canvas / shadow-DOM /
anti-bot-fingerprint sites.

### Steps
1. Read the UI-Venus model card for the exact prompt template and
   action grammar (`<click>x,y</click>`, `<type>text</type>`, etc.).
2. Use `cdp-use` directly (already installed; browser-use uses it).
   Skeleton:
   ```python
   from cdp_use import CDPSession  # or whatever the actual API is
   async def step(session, screenshot_b64, task_so_far):
       resp = await call_llama_server(screenshot_b64, task_so_far)
       action = parse_native_action(resp)  # <click>...</click> etc.
       if action.kind == "click":
           x, y = remap_coord(action.xy, model_size, viewport)
           await send.Input.dispatchMouseEvent(...)
       elif action.kind == "type": ...
       elif action.kind == "done": return resp
   ```
3. Pick one test case from findings where browser-use struggled —
   probably the headless saucedemo cart-icon click — and prove the
   custom client handles it.
4. Compare: same task, same model server, browser-use vs custom. Steps,
   wall-clock time, success/failure.

### Acceptance
- Working prototype in `scripts/custom_client/` (or a separate Python
  module).
- A side-by-side comparison entry in `docs/findings.md` Phase 4 with at
  least one task where the custom client succeeds and browser-use fails
  (or vice versa — negative result is also a valid outcome).

### Why the "vice versa" matters
If browser-use's DOM-augmented prompts beat the model's native format
even on visual tasks, that's a *strong* signal that we should keep
using browser-use and just prompt-engineer harder. Don't default to
"custom is better."

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
