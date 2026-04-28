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

## C-1 — Delete the f16 LLM intermediate
**Effort: xs · Priority: C · Risk: none if Q4/Q5/Q6 GGUFs verified present**

The 16 GB `~/models/ui-venus-1.5-8b/ui-venus-1.5-8b-f16.gguf` is the
re-quantize source. We have Q4_K_M, Q5_K_M, Q6_K already on disk, and the
mmproj (separate file, also f16) stays. The intermediate is only useful
if we want to add a new quant scheme later — re-downloading and
re-converting from safetensors would take ~15 minutes if we ever need to.

### Steps
1. Verify the three quants exist:
   `stat -c "%s %n" ~/models/ui-venus-1.5-8b/ui-venus-1.5-8b-{Q4_K_M,Q5_K_M,Q6_K}.gguf`
2. Confirm `mmproj-ui-venus-1.5-8b-f16.gguf` exists (this is **not** the
   one to delete — it's the vision encoder).
3. Delete only `ui-venus-1.5-8b-f16.gguf`.

### Acceptance
- 16 GB freed.
- `systemctl restart ui-venus.service` still loads cleanly (Q6_K is the
  current default; service should not depend on f16).

---

## C-2 — Test Q5_K_M
**Effort: s · Priority: C · Depends on: nothing**

Q5_K_M (5.5 G) was quantized during the A/B but never tested. The
question is whether the Q4 → Q6 quality jump is linear (Q5 ≈ midpoint) or
whether one of the endpoints is "enough." Useful data point for anyone
later asking "do we *need* Q6_K's VRAM cost?"

### Steps
1. `sudo bash scripts/swap_quant.sh Q5_K_M` — service should restart.
2. Re-run the Excalidraw toolbar identification test (same task as
   findings Smoke 4 / Phase-3 A/B). The exact `TASK` string is in
   `scripts/smoke_browser_use.py` history; the relevant version was the
   "list every tool icon ... be thorough about counting" variant.
3. Compare the tool list and active-state color description to the
   Q4_K_M and Q6_K results recorded in `docs/findings.md` Phase 3 table.
4. After testing, restore: `sudo bash scripts/swap_quant.sh Q6_K`.

### Acceptance
- A new section appended to `docs/findings.md` Phase 3 with the Q5_K_M
  row added to the comparison table. Three data points: tools
  identified, active color correct, generation tok/s.
- Recommendation: keep Q6_K, switch to Q5_K_M, or no measurable
  difference.

---

## E-1 — Recovery-hint prompt experiment
**Effort: s · Priority: E · Risk: low**

The headless saucedemo run (findings Smoke 2) failed because the agent
clicked the cart-icon `<div>` 16 times without ever trying a different
strategy. Hypothesis: a single sentence in the system message
("if a click does not change the page, try a child element / direct URL
/ keyboard navigation") is enough to break the loop and make headless
usable for nested-anchor sites.

### Steps
1. Edit `scripts/smoke_browser_use.py`:
   - Add `extend_system_message=("If clicking an element does not "
     "change the page state, try clicking a different child element, "
     "navigating directly to a URL, or using send_keys to activate via "
     "keyboard.")` to the `Agent(...)` constructor.
2. Set `headless=True` on the `Browser(...)` constructor.
3. Set the `TASK` string to the saucedemo full-flow task (same as
   findings Smoke 2/3 — login → cart → checkout → confirmation).
4. Run with the project standard invocation:
   ```
   PYTHONUNBUFFERED=1 .venv/bin/python -u scripts/smoke_browser_use.py \
     > /tmp/smoke_recovery.log 2>&1
   ```
   *(no DISPLAY env vars needed — headless mode)*
5. Read `/tmp/smoke_recovery.log` and `/tmp/smoke_final.png`.

### Acceptance
- Agent reaches the saucedemo confirmation page (`Thank you for your
  order!`) **without** the 16-click loop on the cart icon.
- New entry in `docs/findings.md` Phase 2: did the prompt fix work, did
  it introduce new failure modes, and what was the step count vs the
  headed run (22 steps).

### If it fails
Don't iterate prompt phrasing more than 2 attempts. If two reasonable
phrasings don't break the loop, conclude the issue is deeper than a
prompt fix and document that — that's a useful negative result.

---

## E-2 — `xvfb-run` for unattended headed runs
**Effort: s · Priority: E · Risk: low**

Headed mode is a hard requirement on this stack (Smoke 2 vs 3 — same
script, only headless/headed differs, totally different outcomes).
`xvfb-run` lets headed Chromium run against a virtual X display without a
real Plasma session, which would let smoke tests run from cron / systemd
timer / SSH session.

Open question: does Xvfb's synthetic input path have the same
nested-anchor click bug as headless? Or does it inherit headed behavior?
We don't know.

### Steps
1. Install xvfb if missing: `pacman -Qi xorg-server-xvfb || sudo pacman -S xorg-server-xvfb`.
2. Set the `TASK` in `scripts/smoke_browser_use.py` to the saucedemo full
   flow (same as Smoke 2/3, the canonical "does click-on-anchor-in-div
   work" probe).
3. Set `headless=False` on the `Browser(...)` constructor (we want
   headed semantics, just on a virtual display).
4. Run without any DISPLAY env vars from the parent — let xvfb-run
   provide them:
   ```
   PYTHONUNBUFFERED=1 xvfb-run -a -s "-screen 0 1920x1080x24" \
     .venv/bin/python -u scripts/smoke_browser_use.py \
     > /tmp/smoke_xvfb.log 2>&1
   ```

### Acceptance
- Agent completes saucedemo end-to-end (or fails identically to a real
  headed run — either is a clear answer).
- `docs/findings.md` updated with the result. If xvfb works, this is the
  recommended unattended-run path.

---

## E-3 — Add cart-verification step to shopping task template
**Effort: xs · Priority: E**

The Home Depot run (findings Smoke 7) reported "2 items added" using
cart-icon badge readings, but never navigated to the cart page itself.
We can't 100% verify the badge readings without an independent ground
truth.

### Steps
1. Re-run the Home Depot 3-item task (`TASK` text is in
   `docs/findings.md` Smoke 7), but extend the prompt:
   *"After all items are added, navigate to https://www.homedepot.com/mycart/home
   and capture a screenshot. Report the cart subtotal and the name of
   each item visible on the cart page itself, not from memory of earlier
   steps."*
2. Use Q6_K (current default), headed mode, project-standard invocation.
3. Read `/tmp/smoke_final.png` — it should show the cart page with
   visible items.

### Acceptance
- Verification screenshot shows the cart page with at least 2 distinct
  items.
- Agent's reported item names match what's actually visible on the cart
  page (cross-check against the screenshot).
- `docs/findings.md` Smoke 7 updated with the cart-page evidence.

---

## F-1 — Custom `drag` action for browser-use
**Effort: m · Priority: F · Risk: medium (requires extending a vendor library)**

browser-use 0.12 has no native drag primitive — only `click(index)`. This
blocks any test that requires actual canvas-coordinate manipulation
(Excalidraw drawing, Figma node move, drag-to-reorder UIs). The model is
trained for this; the framework just doesn't expose it.

### Steps
1. Inspect `browser_use.tools.service.Tools` and find how existing
   actions are registered (the `click` action source is the canonical
   reference). The action receives a `BrowserSession` with a CDP client.
2. Implement a new tool registered on `Tools.registry`:
   ```python
   @Tools.action("drag", "Click and drag from (x1,y1) to (x2,y2) on the page in CSS pixels.")
   async def drag(browser: BrowserSession, x1: int, y1: int, x2: int, y2: int):
       cdp = await browser.get_or_create_cdp_session()
       send = cdp.cdp_client.send
       sid = cdp.session_id
       await send.Input.dispatchMouseEvent(type="mousePressed", x=x1, y=y1, button="left", clickCount=1, session_id=sid)
       # Smooth path: 10 intermediate moves so JS pointermove handlers fire.
       steps = 10
       for i in range(1, steps + 1):
           await send.Input.dispatchMouseEvent(type="mouseMoved", x=x1 + (x2-x1)*i//steps, y=y1 + (y2-y1)*i//steps, button="left", session_id=sid)
       await send.Input.dispatchMouseEvent(type="mouseReleased", x=x2, y=y2, button="left", clickCount=1, session_id=sid)
   ```
   (Exact API may need adjustment after reading the existing `click`
   implementation — this is illustrative.)
3. Add `from <wherever-it-was-defined>` import to
   `scripts/smoke_browser_use.py` so the action is registered when the
   script runs.
4. Smoke-test it: Excalidraw rectangle drawing.
   - Task: `"Open https://excalidraw.com, dismiss welcome with send_keys
     Escape, press 'r' for rectangle tool, then drag from (700, 400) to
     (1100, 600) on the canvas to draw a rectangle. Capture a screenshot
     to verify."`
   - Verify a rectangle is actually drawn in `/tmp/smoke_final.png`.

### Acceptance
- A rectangle is visible on the Excalidraw canvas in the post-run
  screenshot.
- New `docs/findings.md` Phase 4 entry with the drag-action experiment
  results, including any model failures (the model may not figure out
  what coordinates to use without a hint).

### Failure mode to watch for
Synthetic CDP mouse events are *trusted* (unlike `dispatchEvent` from
page JS), so this should work in principle. If Excalidraw still doesn't
register the drag, the issue is more likely the model picking wrong
coordinates than the action plumbing.

---

## F-2 — Coordinate remapper for native UI-Venus output
**Effort: m · Priority: F · Depends on: F-1 if you want to test it**

UI-Venus's native action format returns click coordinates in the model's
**resized internal image space**, not the browser viewport. The original
deployment plan flagged this as a "client-side concern" and we
sidestepped it by using browser-use's element-index protocol. To test
the model's native grounding directly we need a remapper.

### Steps
1. Read the model card on HuggingFace
   (https://huggingface.co/inclusionAI/UI-Venus-1.5-8B) for the exact
   resize formula. Likely uses `min_pixels` / `max_pixels` constants
   from `preprocessor_config.json`
   (`~/models/ui-venus-1.5-8b/hf/preprocessor_config.json` —
   `shortest_edge: 65536`, `longest_edge: 16777216`, `merge_size: 2`,
   `patch_size: 16`).
2. Implement a function:
   ```python
   def remap_coord(model_xy: tuple[int, int],
                   model_image_size: tuple[int, int],
                   viewport_size: tuple[int, int]) -> tuple[int, int]:
       """Given a coord the model emits in its resized image space,
       return the corresponding viewport pixel coord."""
   ```
   The exact math is `viewport_xy = model_xy * viewport_size /
   model_image_size`, but `model_image_size` itself depends on the
   resize policy (longest-edge / patch-aligned) — get that right.
3. Place the helper in `scripts/coord_remap.py` with a small test
   harness: known input → known output.

### Acceptance
- Helper exists with at least 3 test cases (covers landscape, portrait,
  square viewports).
- A demo script that takes a real screenshot, asks the model "click the
  X button," and prints both the model's raw coord and the remapped
  viewport coord.

### Strategic note
This unlocks **S-1** (custom client) — without the remapper, a custom
client can't accurately convert model output to actual clicks.

---

## S-1 — Custom CDP client prototype
**Effort: l · Priority: S · Depends on: F-2**

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
