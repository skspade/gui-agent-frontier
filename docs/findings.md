# UI-Venus + browser-use: Findings Trail

A running log of what worked, what broke, and what surprised us while standing
up `UI-Venus-1.5-8B` on llama.cpp (Vulkan) and driving a browser with
`browser-use`. Append new sections as we go; keep them short and concrete so a
retro can pull patterns out at the end.

---

## 2026-04-28 — Phase 1: Server stand-up

### Worked
- **Hardware**: 9070 XT (gfx1201, RADV) is fine for llama.cpp Vulkan. No ROCm
  needed.
- **Build**: `cmake -DGGML_VULKAN=ON -DLLAMA_CURL=ON` → ~3 min build.
- **Conversion**: `convert_hf_to_gguf.py` recognized `qwen3_vl` natively. Two
  passes (default + `--mmproj`) produced 16G LLM + 1.2G mmproj.
- **Quantize**: 15.6G f16 → 4.79G Q4_K_M (4.9 BPW) in ~46s.
- **Inference**: ~256 tok/s prompt, ~101 tok/s gen at Q4_K_M on Vulkan. Higher
  than the plan's 40–60 estimate.

### Broke
- **`spirv-headers` missing** at build time (`spirv/unified1/spirv.hpp` not
  found). Required `sudo pacman -S spirv-headers`. Should have been a listed
  prerequisite alongside `vulkan-radeon`.
- **Python 3.14 vs llama.cpp `requirements.txt`**: pinned `torch~=2.6.0` and
  `numpy~=1.26.4` have no Python 3.14 wheels. Workaround: install
  `torch>=2.9 numpy>=2.0 transformers>=5.5.0 gguf protobuf accelerate
  safetensors sentencepiece tqdm` directly, ignore the `-r` file.

### Surprised
- The `huggingface-cli` command is gone in `huggingface_hub` 1.12 — replaced by
  `hf`. Plan said `huggingface-cli download`; works under the new name.
- llama.cpp emits a `WARN: This is an experimental CLI` for `llama-mtmd-cli`,
  but the smoke test was already production-quality output.
- Model returns `<think>...</think><answer>...</answer>` framing on its own —
  no special prompting needed.

### Configuration deltas vs the original plan
- `--c 16384` → `--c 32768` (browser-use prompt + screenshot is ~17K tokens;
  16K isn't enough for any agentic use).
- Added `--image-min-tokens 1024` (per llama.cpp's load-time warning for
  Qwen-VL grounding tasks).
- Added `--jinja` to use the embedded chat template.

---

## 2026-04-28 — Phase 2: browser-use smoke tests

### Setup
- `browser-use==0.12.6` in a project venv.
- Chromium binary already in `~/.cache/ms-playwright/chromium-1208/chrome-linux64/chrome`
  (Playwright was previously installed). browser-use 0.12 speaks CDP directly
  via `cdp-use`; no Playwright runtime needed.

### Smoke 1: Wikipedia/Lisbon — passed
- 2-step run: navigate → extract → done.
- Returned correct population.
- Required: `dont_force_structured_output=False` so llama.cpp's grammar
  enforcement constrains output to valid JSON (otherwise the model's
  `<think>...</think>` preamble breaks pydantic's strict JSON parse).

### Smoke 2: saucedemo, headless — failed at cart click
- Login: ✅
- Add to cart: ✅
- **Open cart icon: ❌** — 16 consecutive CDP clicks on
  `div#shopping_cart_container` reported success but page state never changed.
- Diagnosis: synthetic CDP click on a `<div>` whose only nav behavior is via a
  child `<a>` doesn't reliably trigger the anchor in headless Chromium.
- **Side finding: the agent has no recovery strategy.** When the page didn't
  change, it kept clicking the same element instead of trying child elements,
  direct URL, or keyboard. browser-use's loop-detection nudge fired but didn't
  push the model to a different action.

### Smoke 3: saucedemo, headed via Xwayland — passed
- Same script, `headless=False`, env: `DISPLAY=:0
  XAUTHORITY=/run/user/1000/xauth_rVYaGJ XDG_RUNTIME_DIR=/run/user/1000`.
- Full flow in 22 steps: login → cart → checkout → form fill → continue →
  finish → reported the confirmation message.
- Confirmed: the headless click failure was a Chromium quirk, not the model.

### Surprised
- The 8B local model handled multi-field form fill, multi-page checkout, and
  state tracking ("First Name has 'Test', Last Name has 'User', Postal Code is
  empty") cleanly via DOM-indexed elements. Visual grounding (UI-Venus's
  trained strength) was unused on this task.
- browser-use's element-index trick is the dominant interaction mode; pixel
  coordinates only come up when DOM is unhelpful.

---

### Smoke 4: Excalidraw visual grounding, headed — passed
- Task: dismiss welcome dialog, describe canvas state, list all toolbar tool
  icons in order, click the rectangle tool, verify the change visually.
- 8 steps total. Final output:
  - Canvas state: "empty" ✓
  - Toolbar order (icons identified by shape, not text):
    `lock, selection, rectangle, diamond, ellipse, arrow, line, draw, text,
    insert image, eraser` — correct
  - Visually confirmed the active-tool highlight: *"rectangle tool is now
    highlighted with an orange border"*
- This is the first task where UI-Venus's visual grounding training was
  actually load-bearing. browser-use's element-index trick can locate the
  toolbar buttons, but only the model can name them by icon shape and verify a
  visual highlight change.

### Surprised
- The model burned 4 steps trying to dismiss the welcome dialog using
  `evaluate` to dispatch synthetic `KeyboardEvent('keydown', {key:'Escape'})`.
  Synthetic events from page JS don't trigger most listeners (security/trust
  flag). `send_keys` via CDP `Input.dispatchKeyEvent` would have worked first
  try — the model didn't pick it. **Pattern:** when the task says "press
  Escape," prefer `send_keys` over `evaluate`-with-synthetic-event.
- The agent spontaneously used `write_file` to maintain its own todo list mid
  task. Harmless but added steps. Worth a system-message hint to skip
  scratch-file plans for short tasks.

### Smoke 5: Excalidraw canvas text, headed — passed (user-verified)
- Task: select text tool, click canvas, type "hello UI-Venus", commit.
- 5 steps. User confirmed visually that the text appeared on the canvas.
- Notable: the model used `send_keys` correctly this time (after the explicit
  hint in the task prompt), avoiding the synthetic-event trap from Smoke 4.
- The agent tried to "verify" via `evaluate('canvas.toDataURL()')` which does
  nothing visible — it returns a data URL string but is not a real screenshot
  capture. **Pattern:** when asking for visual verification, prefer the
  `screenshot` action over `evaluate`-with-canvas-tricks.

### Smoke 6: Google Maps marker click, headed — passed-with-caveats
- Task: search "Eiffel Tower Paris France", click the rendered red pin marker
  on the map, report address from the side info panel.
- 4 steps. Reported address: `Av. Gustave Eiffel, 75007 Paris, France` —
  factually correct.
- **The visual test was bypassed.** Google Maps auto-opens the result panel
  after a search; the agent never had to identify or click a marker on the
  canvas. The task design didn't force visual grounding because the search
  flow does the work.
- **Possible hallucination signal.** The verification screenshot
  (`/tmp/smoke_final.png`) showed the *photo gallery* view, not the side info
  panel. The agent reported the address as currently shown, but at capture
  time it wasn't on screen. Two readings:
  1. The agent saw the address mid-flow and reported it from prior step
     memory (legitimate but mis-attributed).
  2. The agent confabulated — "Eiffel Tower address" is in the LLM's parametric
     knowledge regardless of what was on screen.
  Either way: **don't trust agent self-reports as ground truth without an
  independent screenshot check.**

### Tooling improvement during this run
- Added a verification screenshot save in `smoke_browser_use.py` post-run via
  CDP `Page.captureScreenshot`. Required `keep_alive=True` on `Browser` to
  prevent teardown before capture, and explicit `await session.kill()` at the
  end. **Pattern:** for any test where the success criterion is visual,
  capture an independent screenshot — agent self-reports are not enough.

### Smoke 7: Home Depot — add 3 items, headed — partial (2/3)
- Task: add three different items to cart on homedepot.com, then report cart
  contents.
- 40 steps (max). Result: 2 items added (Milwaukee M18 trimmer $349.00, Costa
  Farms ZZ Plant $19.97). Failed on the third when the search-suggestion
  dropdown for "paint can" wouldn't close/select reliably.
- **Strong visual-grounding signal.** The agent used the cart-icon badge as
  ground truth after each add: *"the cart icon shows '1'"*, then *"cart now
  shows 2 items with the confirmation popup visible"*. That badge is a
  rendered glyph + number — the model read it visually. This is the cleanest
  example so far of UI-Venus's training paying off in a real-world DOM-heavy
  site.
- **Honest partial-completion reporting.** The agent explicitly said "task
  cannot be completed as requested within the step limit" rather than
  claiming success. Big improvement on the Maps confabulation incident — the
  hint *"if you cannot complete the task, report what blocked you rather than
  pretending to succeed"* in the task prompt mattered.
- Verification gap: the agent never navigated to `/mycart/home` to confirm
  cart contents from the cart page itself. Final screenshot was the homepage
  mid-paint-can search, so we can only trust the badge readings, not an
  independent cart view.
- No anti-bot block from Home Depot for this session (Akamai is normally
  aggressive — possibly didn't fire because the browser launched headed with
  a normal Chromium fingerprint and no obvious automation tells).

### Tooling lesson learned: stdout buffering
- First run appeared "stuck" with 0-byte output. Diagnosis: the wrapping
  `... | tail -200` in the harness invocation buffers all of stdout in
  memory until EOF before printing anything. With a long-running agent, that
  means *no logs visible until the script exits or is killed*. In reality the
  agent was making real requests against llama-server the whole time (the
  systemd journal confirmed it).
- **Fix:** for long-running agent runs, redirect to a log file with
  `PYTHONUNBUFFERED=1 python -u ... > /tmp/log 2>&1` and tail the file
  separately. Don't pipe through `tail` or `head` for live monitoring.

## 2026-04-28 — Phase 3: Quantization A/B (Q4_K_M vs Q6_K)

### Quantizing
- Re-quantized the existing f16 intermediate to Q5_K_M (5.5G) and Q6_K
  (6.3G) in parallel. Each took ~60s on CPU.
- mmproj stays f16 (1.2G) for both — only the LLM is swapped.
- VRAM math at 32K KV (f16): Q4_K_M ~10.7G, Q5_K_M ~11.4G, Q6_K ~12.2G,
  Q8_0 ~14.4G. All fit in 16G but Q8_0 is uncomfortably tight.

### A/B on Excalidraw toolbar identification
| Metric | Q4_K_M | Q6_K |
|---|---|---|
| Tools identified | 11 | **12** (caught "Hand") |
| Active-state color | "orange" (wrong - actual color is purple) | "purple" (correct) |
| Annotation detail | bare names | parenthetical context ("Hand (panning)", "Rectangle (active)") |
| Generation speed | ~65 tok/s | ~67 tok/s |
| Prompt eval | ~1230 tok/s | ~1430 tok/s |

- The A/B-relevant signal: Q6_K caught the **Hand (panning) tool** between
  Lock and Selection that Q4_K_M missed, and got the active-state color
  *right* (purple, not orange). Both still missed the rightmost
  "shapes/library" grid icon.
- **Speed is essentially identical.** The 33% file-size bump from Q4_K_M to
  Q6_K cost ~2 tok/s on generation — within noise. For a workload dominated
  by prompt processing (browser-use sends ~17K-token prompts with
  screenshots), both quants behave the same.
- VRAM under load was comfortably below the 16G ceiling for Q6_K, so
  there's no operational reason not to run Q6_K by default.

### Recommendation
- **Default to Q6_K going forward** for this workload. Quality gain on icon
  identification and color discrimination is real; speed and VRAM costs are
  negligible.
- Don't bother with Q5_K_M — the gap from Q4_K_M to Q6_K is small enough
  that a halfway point isn't worth a separate evaluation.
- Q8_0 is probably overkill given Q6_K's quality and the tight VRAM
  margin (would need KV quantization to fit comfortably, which trades the
  win back).

### Tooling lessons
- The `/tmp/swap_quant.sh` script bricked the unit on first run because the
  regex matched both the LLM line *and* the mmproj line, leaving
  `mmproj-ui-venus-1.5-8b-Q6_K.gguf` (which doesn't exist - mmproj is f16
  only). Lesson: when sed-ing related-but-different filenames, anchor the
  pattern to disambiguate. The fix added a leading `/` to anchor against
  the LLM path's directory separator (the mmproj path has `mmproj-` directly
  before the version, no `/`).
- Sed delimiter collision: my first cut used `|` as the `s` delimiter while
  the regex contained `|` for alternation. Always pick a delimiter that
  doesn't appear in either side of the substitution.

---

## 2026-04-28 — Phase 4: Disk cleanup (backlog C-1)

Deleted `~/models/ui-venus-1.5-8b/ui-venus-1.5-8b-f16.gguf` (16 GB).
The three quants (Q4_K_M, Q5_K_M, Q6_K) and the f16 mmproj remain.
`ui-venus.service` restarted cleanly on Q6_K; `/health` returns `{"status":"ok"}`.
Confirms the service has no runtime dependency on the f16 LLM weight —
it was purely a re-quantize source. Re-creating it later would require
re-downloading safetensors and re-running the convert step (~15 min).

---

## 2026-04-28 — Phase 5: Q5_K_M data point (backlog C-2)

Phase 3 deferred Q5_K_M ("not worth a separate eval"). Ran the same
Excalidraw toolbar identification task to fill the gap.

| Metric | Q4_K_M | **Q5_K_M** | Q6_K |
|---|---|---|---|
| Tools identified | 11 | **11** (caught Hand, missed Selection) | 12 (caught Hand) |
| Active-state color | "orange" (wrong) | **"orange" (wrong)** | "purple" (correct) |
| Annotation detail | bare names | **parenthetical** ("Hand (panning)") | parenthetical |
| Behavior | clean run | **30+ step send_keys loop** | clean run |
| Active-tool claim | matched screenshot | **confabulated** (claimed rectangle active; screenshot showed Selection) | matched screenshot |

Q5_K_M lands closer to Q4 than Q6 on the things that matter:
- Same tool count as Q4 (11), and missed the Selection arrow that Q4
  also missed despite Q5 catching the Hand tool that Q4 missed — net,
  the same total.
- Same wrong color call as Q4 ("orange" vs actual purple).
- Hit a behavior failure neither Q4 nor Q6 hit: looped on `send_keys: esc`
  for ~30 steps after the first activation, lost the rectangle's
  active state, then claimed in the final summary that rectangle was
  highlighted with an orange border — confabulation contradicted by
  the verification screenshot, which shows Selection arrow active and
  rectangle inactive.

The annotation detail (parenthetical descriptions like "Hand (panning)")
is the only Q6-like quality on Q5. Everything else is Q4-like or worse.

**Updated recommendation**: Q5_K_M is *not* a midpoint — on this task
it behaved as Q4-with-extra-instability. Keep Q6_K as default.
The 800 MB VRAM saving from Q5 is not worth the quality regression
and the new failure mode (loop-then-confabulate). If VRAM pressure
ever forces a downgrade, go straight to Q4_K_M; Q5 has no clear win
over either neighbor.

**Caveat**: n=1 task. The confabulation behavior in particular could be
run-to-run variance rather than a quant-induced regression. A second
run on a different visual task would harden the conclusion. Not chasing
that today — the ranking is clear enough to decide quant policy.

---

## 2026-04-28 — Phase 6: Recovery-hint prompt (backlog E-1) — negative result

Tested whether a system-message addition could break the headless
saucedemo loop-on-failed-click pattern from Smoke 2. Three runs on Q6_K,
headless, max_steps=40, same task (login → cart → checkout → confirmation):

| Run | Prompt addition | Login | Add-to-cart | Open cart | Steps used |
|---|---|---|---|---|---|
| Baseline | none | ✅ | ❌ looped 30+ steps | (didn't reach) | 40/40 |
| Hint v1 | "if click does not change page state, try child / URL / send_keys" | ✅ | ✅ first try | ❌ looped 35+ steps on cart icon | 40/40 |
| Hint v2 | aggressive: "next action MUST NOT be the same click ... never repeat" | ✅ | ✅ first try | ❌ looped 30+ steps on cart icon (tried sibling element [107] once) | 40/40 |

### What v1 changed
The hint *did* break the easier loop: in baseline the model couldn't get
past the Add-to-cart button click (silent failure on a `<button>` —
clicks were going through but state didn't update visibly). With v1 it
cleared Add-to-cart on first try and reached the cart-icon stage —
exactly Smoke 2's original failure point.

### What neither version fixed
The cart icon at saucedemo (`<div>#shopping_cart_container` whose only
nav is via a child `<a>`) — both v1 and v2 looped 30+ times on the same
DOM index. v2 was much more explicit:
- "MUST NOT be the same click on the same element"
- "never repeat a click on an element that just failed"
- listed all three alternatives by name (child element / `go_to_url` / `send_keys`)

In v2: **0 `go_to_url` calls, 0 `send_keys` calls** across 40 steps.
The agent's own self-eval stated "Previous attempts to click the
shopping cart icon failed to navigate to the cart page" while its next
emitted action was still `click index: 104`. The model sees the failure
and acknowledges it in text, then plans the same action anyway.

### Conclusion
The recovery-hint approach has a real but partial effect — it can break
loops where the model's planning was just stuck on one option, but it
cannot break loops where the model is genuinely confident in an action
that's silently failing under the hood. The cart-icon case is the
latter: from the model's screenshot view, clicking the icon is the
right thing to do, and no amount of system-message prodding overrides
that. The fix needs to be either:
1. Framework-level: detect "click succeeded but no DOM mutation" and
   force a different action (browser-use's loop-detection nudge is
   close but evidently not strong enough — fired 35+ times in v2 and
   the model kept clicking).
2. Stack-level: don't run headless on sites with nested-anchor cart
   patterns. CLAUDE.md already encodes this as a hard requirement.
3. Action-level: add a `navigate_relative_url` action and a stronger
   prior toward URL-direct navigation when a click fails — i.e. the
   model needs *fewer* options to choose from when stuck, not the
   same option re-emphasized.

The original open question ("would extend_system_message with 'if
action didn't change page, try X, Y, Z' fix the loop?") has its
answer: **partial yes** for stuck-planning loops, **no** for
silent-action-failure loops. Headed mode remains the operational
recommendation for any nested-anchor-cart site.

---

## 2026-04-28 — Phase 7: Xvfb for unattended headed (backlog E-2) — negative result

Tested whether `xvfb-run` (virtual X display) gives real-headed click
semantics or inherits the headless click-failure bug. The
distinguishing test is the saucedemo full-flow:

- **Real headed** (Smoke 3): completes in 22 steps, no loops.
- **Headless** (Smoke 2 / E-1 baseline): silent click failure on
  Add-to-cart and/or cart icon, loops to step budget.
- **Xvfb-headed** (this run): expected one of the two.

### Run

```
xvfb-run -a -s "-screen 0 1920x1080x24" .venv/bin/python -u \
  scripts/smoke_browser_use.py > /tmp/smoke_xvfb.log 2>&1
```

`headless=False`, no parent `DISPLAY`/`XAUTHORITY` set.

### Result: Xvfb behaves like headless

- Login: ✅ on first try
- Add-to-cart: ❌ 34 consecutive failed clicks on the Sauce Labs Backpack
  button before the agent gave up. Same silent-click pattern as the
  E-1 baseline.
- 30 loop-detection nudges fired across the 40-step budget.
- Verification screenshot: inventory page, all "Add to cart" buttons
  still visible (none flipped to "Remove"), cart icon empty.
- Agent honestly reported the failure rather than confabulating success.

### What this means

The nested-anchor / silent-click failure mode is **not** specific to
Chromium's `--headless` flag — it reproduces under headed-Chromium
running against a virtual X display. The bug appears to be tied to
the *kind* of display surface, not the headless mode itself: a real
compositor (Plasma+Wayland via Xwayland, in the Smoke-3 setup) lets
clicks propagate correctly through nested DOM, while a synthetic
Xvfb display does not.

This is a stronger negative result than expected — `xvfb-run` is the
standard "headless headed" trick for CI/cron. It works for a lot of
browser automation but evidently not for this stack's specific click
issue.

### Operational consequences

- **No xvfb-based unattended path.** Cron / systemd timer / SSH-only
  hosts cannot run these smoke tests without a real X session.
- Possible alternatives, not yet tested:
  1. Run a persistent Plasma session as the user under
     `systemd --user`, run smoke tests against its `:0` from cron.
     Heavyweight but matches Smoke 3 exactly.
  2. Try `--ozone-platform=headless` (Chromium's newer headless mode,
     different code path from Playwright's default headless).
  3. Try a dedicated VNC server (Xvnc) instead of Xvfb — different
     synthetic input path.
- For now: **headed mode requires the user to be logged in to Plasma.**
  Document and accept the limitation rather than chase fixes.

### Caveat

n=1. The failure could be xvfb-specific *or* could be reproduce-able
on any synthetic-X display. Not chasing further unless an unattended
path becomes a hard requirement.

---

## 2026-04-28 — Phase 8: Cart-page verification on Home Depot (backlog E-3)

Closed the Smoke 7 verification gap by extending the task to navigate
to `/mycart/home` and report cart contents from the cart page itself,
not from agent memory.

### First run (max_steps=40) — instructive partial

- 40-step ceiling hit before reaching `/mycart/home`.
- Agent reported 2/3 items added: MetalTech Mobile Baker Scaffolding
  ($1,236.65) + Werner Multi-Position Ladder ($174.00).
- Verification screenshot: Home Depot's "Added to Cart" side panel
  showing **only Fakro Attic Ladder, Qty 2, $1,720.00**. Neither
  scaffolding nor Werner ladder visible.
- Couldn't fully resolve the contradiction without the cart page.
  Two readings: (a) side panel only displays the most recent add,
  others might still be in cart; (b) agent confabulated item names
  from its `Memory:` log when its retried Add-to-Cart clicks were
  actually adding the same Fakro item multiple times.
- Bumped `max_steps` from 40 to 60 and re-ran.

### Second run (max_steps=60) — successful, with a new finding

Completed in 49 steps. Reached `/mycart/home`. Agent reported:

- Subtotal: **$4,833.00**
- Savings: **-$898.80**
- Total: **$3,934.20**
- 3 distinct items: Fakro Attic Ladder, MetalTech Saferstack Scaffold
  Section, Werner 5-in-1 Multi-Position Ladder.

Verification screenshot: cart page in view. Subtotal, savings, total
and the visible item (Fakro at $576) match the report exactly. The
"Pickup, Western Hills (3 items)" indicator confirms 3 distinct SKUs.
Other two items would require scrolling.

### New finding: Add-to-Cart retries silently inflate quantity

Cart header in the run-2 screenshot reads `CART (15)` — the count of
total units, not distinct SKUs. With only 3 distinct items, that's
12 redundant additions. The "element index issues" the agent
hand-waved during retry attempts in run 1 were *not* failures —
the clicks were succeeding and bumping qty each time. The agent
mis-classified successful adds as failures because the page state
change didn't match its expectation of a navigation, when in fact
the change was a +1 to the cart icon badge it didn't notice.

This is the inverse of the E-1 silent-failure pattern: there, clicks
silently *failed* and the agent kept retrying. Here, clicks silently
*succeeded* and the agent kept retrying. Both are state-feedback
problems — the agent's mental model of "did my click do anything"
is unreliable on Home Depot specifically.

### Operational consequences

- Step budget: 40 was sufficient for Smoke 7's report-from-memory;
  60 is needed if you also want cart-page verification. Default the
  workbench to 40 (already is) but bump for tasks that explicitly
  add a verification step.
- For real shopping automation: between each Add-to-Cart, navigate
  to /mycart/home (or read the cart-icon badge into the prompt) to
  prevent unintended duplicate adds. Don't trust the
  click-then-evaluate-page-state heuristic on Home Depot.

### Smoke 7 status

The original Smoke-7 report ("2 items added: Milwaukee M18 trimmer
$349.00, Costa Farms ZZ Plant $19.97") was likely accurate for the
items it named, but the cart probably contained quantity > 1 of one
or both items due to the same retry-inflation pattern. We can't
re-verify retroactively; treat the original cart count as a lower
bound on units, not an exact figure.

### Acceptance

- ✅ Verification screenshot shows the cart page with at least 2
  distinct items confirmed via the "(3 items)" indicator.
- ✅ Agent's reported subtotal, savings, total, and visible item name
  all match the screenshot.
- ✅ This phase entry serves as the Smoke-7-lineage update.

---

## 2026-04-28 — Phase 9: Custom `drag` action (backlog F-1)

**Goal**: give browser-use a real drag primitive so canvas tasks (Excalidraw,
Figma, drag-to-reorder) become reachable. browser-use 0.12.6 ships only
index-click and coordinate-click; `send_keys` is keyboard-only. There is no
mouse-drag event, and the `evaluate`-injected `dispatchEvent` path doesn't
trigger trusted pointer pipelines.

### What was built
`scripts/drag_action.py` — a registrable action that issues raw CDP
`Input.dispatchMouseEvent` events (mousePressed → 10 mouseMoved
intermediates → mouseReleased) via the same `cdp_use` client browser-use
already uses internally. Wired into `scripts/smoke_browser_use.py` by
constructing a `Tools()` explicitly, calling `register_drag(tools)`, and
passing `tools=tools` to `Agent(...)`.

The action signature is `drag(x1, y1, x2, y2)` taking CSS-pixel viewport
coordinates. `BrowserSession` is auto-injected by browser-use's
`Tools.registry.action` decorator (special-named param).

### Smoke test
- TASK: open https://excalidraw.com, send Escape, send 'r' to activate
  rectangle tool, drag from (700,400) to (1100,600), screenshot.
- 4 steps, agent reported success.
- Independent verification screenshot (`/tmp/smoke_final.png`): a
  rectangle is clearly rendered on the canvas, selected with eight resize
  handles, and Excalidraw's right-side properties panel is showing
  Stroke / Background / Stroke width / Sloppiness / Edges — confirming
  the shape is a real Excalidraw element, not a visual artifact.
- Rectangle position matches the drag coordinates (right half of canvas,
  upper-middle vertical region).

### What worked
- CDP synthetic mouse events are *trusted* (matches the failure-mode
  prediction in F-1): Excalidraw's pointerdown/pointermove/pointerup
  pipeline registers them and creates a real shape.
- Required exactly the parameters listed in the F-1 stub plus
  `buttons: 1` on press/move (without it, some pointer pipelines treat
  the mouseMoved as a passive hover). The release uses `buttons: 0`.
- Including `clickCount: 1` on press and release (clickCount: 0 on the
  intermediate moves, by virtue of CDP defaults) avoided any
  click-handler firing simultaneously with the drag.
- Smooth path of 10 intermediate moves was sufficient — Excalidraw's
  pointermove handler fires per move event and assembles the shape
  geometry; no visible artifact from sub-pixel rounding.

### Model-side observation
The model used the `drag` action correctly on first attempt — it took the
literal coordinates from the prompt (`x1=700, y1=400, x2=1100, y2=600`)
without trying to remap them to internal model space or re-derive them
from the screenshot. This was intentional in the prompt design (we
wanted to validate the action plumbing, not grounding). For F-2 / S-1
work where the model emits its own coordinates, the remapper still
matters — see backlog F-2.

### Acceptance
- ✅ Rectangle visible on canvas in post-run screenshot.
- ✅ Action registers cleanly via `Tools.registry.action(...)` decorator
  without modifying browser-use source.
- ✅ Reusable: any future smoke test can `from drag_action import
  register_drag` and gain the capability without ceremony.

### Caveats / what to watch
- Action takes raw viewport pixels. If the agent (in a future test)
  sources coordinates from a screenshot rendered at a different scale
  than the live viewport, results will be off. browser-use already
  handles a similar concern for its coordinate-click via
  `_convert_llm_coordinates_to_viewport`; we do *not* call that here
  because the prompt supplied viewport coordinates directly. F-2's
  remapper is the right place to centralize that logic.
- Drag is emitted at left-button only. Right-drag, middle-drag,
  modifier-key drag (e.g. Shift to constrain Excalidraw to a square) are
  not exposed. Add params if a future task needs them — don't preemptively
  generalize.

---

## 2026-04-28 — Phase 10: Coordinate remapper (backlog F-2)

**Goal**: build the helper that converts UI-Venus's emitted coordinates
back to actionable viewport pixels, so we can drive the model's *native*
grounding output (instead of always going through browser-use's DOM index
protocol). Prerequisite for S-1 (custom CDP client).

### What the upstream code says
Cloned-by-eye from `inclusionAI/UI-Venus@main` (commit on 2026-04-28):

- `models/grounding/ui_venus1_5_gd.py` `_parse_point` — the grounding-head
  emits `[x, y]` and the upstream code divides each by **1000** to get
  [0,1] proportions. Coordinates are 0-1000 normalized regardless of
  input image dimensions.
- `models/navigation/ui_venus_navi_agent.py` `_rescale_coordinate` — the
  navigation head (used with the `<think>/<action>/<conclusion>` chat
  template) emits coordinates in the model's **resized-image pixel space**
  after Qwen3-VL `smart_resize`. Inverse-remap is
  `viewport_xy = model_xy * orig_size / resized_size`.

So there are *two* coordinate conventions, picked by which prompt format
is used. The merged 8B model supports both prompts.

Smart-resize parameters from `~/models/ui-venus-1.5-8b/hf/preprocessor_config.json`:
`patch_size=16, merge_size=2 → factor=32`, `min_pixels=65536`,
`max_pixels=16777216`.

### What was built
`scripts/coord_remap.py` — pure-Python (no transformers dep at runtime):
- `smart_resize(h, w, ...)` — replicates Qwen3-VL's resize policy.
- `grounding_remap(model_xy, viewport_size)` — for 0-1000 normalized.
- `navigation_remap(model_xy, viewport_size)` — for resized-pixel space.
- 6-case self-test (landscape, portrait, square × both conventions),
  passing.

`scripts/coord_remap_demo.py` — POSTs a screenshot + grounding instruction
to the local llama.cpp endpoint, parses `[x, y]`, prints both
interpretations, and saves an annotated PNG with both points marked
(lime = grounding, red = navigation).

### Empirical result on the merged 8B
Demo run against `/tmp/smoke_final.png` (the F-1 Excalidraw screenshot
with a rectangle drawn at viewport (700,400)–(1100,600); image is
4800×2708 because browser-use ran at DPR≈2.5):

```
Instruction: the rectangle drawn on the canvas
Raw model response: '[466, 460]'
Grounding interpretation:  (2237, 1246)   ← image-pixel
Navigation interpretation: (466,  458)    ← image-pixel
```

Independent visual verification (`/tmp/coord_remap_demo.png`):
- **Lime ring at (2237, 1246)** — dead center of the drawn rectangle.
  The rectangle spans roughly (1750,1000)–(2750,1500) in image pixels;
  (2237, 1246) is the geometric centroid.
- **Red ring at (466, 458)** — lands inside the white background-color
  swatch in the left sidebar. Off by ~5×.

**Conclusion**: with the grounding prompt, the merged 8B model emits
0-1000 normalized coordinates. `grounding_remap` is the right helper for
this inference mode. `navigation_remap` is preserved for the `<think>/
<action>/<conclusion>` chat-template mode (which we'd use in S-1 for
multi-step navigation), but is not what to apply here.

### Acceptance
- ✅ Helper has 6 test cases covering landscape/portrait/square viewports
  for *both* coordinate conventions (3 each).
- ✅ Demo prints raw + remapped coords; the annotated PNG provides
  immediate visual ground truth.
- ✅ Bonus: settled the question of which convention the merged 8B uses
  (grounding-prompt → 0-1000 normalized). The backlog F-2 stub had
  assumed only the resized-pixel-space convention; turns out the
  simpler one is what's used in practice for grounding prompts.

### Implications for S-1
S-1's "custom CDP client" should use the grounding prompt for single-shot
clicks (one screenshot → one coordinate) and only switch to the
navigation chat template if multi-step `<think>/<action>` reasoning
becomes necessary. Coord conversion to viewport CSS pixels is then
`grounding_remap(raw, css_viewport_size)` — note `css_viewport_size`,
not screenshot pixel size, because CDP `Input.dispatchMouseEvent`
expects CSS pixels and screenshots are at DPR-scaled device pixels.

---

## 2026-04-28 — Phase 11: Custom CDP client (backlog S-1)

**Goal**: prove (or refute) that driving UI-Venus directly via CDP with
its native navigation chat template can succeed where browser-use fails
on canvas / nested-anchor pages.

### What was built
`scripts/custom_agent.py` (runner) + `scripts/custom_agent/` (browser,
model, actions) + `scripts/custom_agent_tasks/` (per-task payloads).
Total ~580 lines of agent code (excluding the throwaway probe script
and the parse_action self-test). Serial loop, no DOM-indexed protocol,
model is the planner end-to-end via the navigation chat template.

Design: `docs/plans/2026-04-28-s1-custom-cdp-client-design.md`.
Implementation plan: `docs/plans/2026-04-28-s1-custom-cdp-client-plan.md`.

### Empirical findings retired on day one (Task 1 of the plan)
- **Coordinate convention** (Phase 10 only verified the grounding prompt
  path): the merged 8B emits 0–1000 normalized coords in **both** prompt
  modes. Use `grounding_remap` for the navigation chat template too.
  Upstream `models/navigation/ui_venus_navi_agent.py::_rescale_coordinate`
  is from the pre-merge specialist checkpoint and does not apply to the
  merged model. Probe: `scripts/custom_agent_probe_nav.py` against
  `/tmp/smoke_final.png` (commit 6332f1c).
- **System prompt is just `"You are a helpful assistant."`** — the
  GUI-Agent task instruction (the long template with `### User Task`,
  `### Previous Actions`, etc.) goes in the **user message**, not the
  system message. Source: upstream
  `models/navigation/ui_venus_navi_vllm.py::create_message_for_image`.
- **Action grammar uses capitalized verbs and parens**, not the
  lowercase/brackets the original plan sketched: `Click(box=(x, y))`,
  `Type(content='...')`, `Scroll(start=..., end=..., direction='...')`,
  `Drag(start=(x1, y1), end=(x2, y2))`, `Finished(content='...')`,
  `Wait()`, `LongPress(box=(x, y))`, `PressBack/Home/Enter/Recent()`,
  `Launch(app='...')`, `CallUser(content='...')`. Coords are 0–1000
  integers.

### Test 1 — saucedemo, both modes
**Headless run** (`saucedemo_headless`): 8 steps · 21.9s · `done`
self-reported, **visually failed**.
- Login flow (4 steps) worked perfectly. Inventory page reached.
- Add-to-cart click coord (384, 542) → viewport (~491, 356), landed in
  dead space between product cards.
- Cart-icon click coord (952, 40) → viewport (1218, 26), in the icon's
  rough vicinity. Page stayed on `/inventory.html`.
- Model emitted `Finished(...)` without verifying.

**Disambiguation: headed run** (`saucedemo_headed`, follow-up after the
initial Phase 11 write-up): 8 steps · 43.1s · `done` self-reported,
**also visually failed**.
- Same login success, same Add-to-cart miss (coord (381, 579) →
  viewport (469, 356)), same cart-icon miss (coord (945, 44) → viewport
  (1164, 27), ~20 px left of the icon center).
- Cart badge never appeared in any post-Add-to-cart screenshot in
  either mode → Add-to-cart click also missed in both runs.

**Conclusion**: the Phase 11 initial hedge ("either coord precision, or
`--headless=new` nested-anchor rendering bug") collapses to **coord
precision**. The same misses happen in headed mode, so the headless
rendering theory is ruled out. The model mis-grounds small UI targets
in dense layouts by 20–50+ px regardless of mode. Large well-spaced
targets (login form fields, the Excalidraw rectangle-tool glyph in a
sparse toolbar) ground accurately; product-card buttons (~80 px wide
in a 4×2 grid) and the cart icon (~30×30 px in the corner) do not.

- Browser-use baseline (Phase 2 Smoke 2): looped infinitely on the cart
  icon in `--headless`, never completed.
- **Comparison**: divergent failure modes, neither succeeds.
  Browser-use loops; the custom client reports false success in 22-43s.
  Custom client trivially beats browser-use on wall-clock-to-give-up
  but neither user-visibly succeeds. The bottleneck is the model's
  visual grounding precision on small targets, not framework choice.

### Test 2 — Excalidraw toolbar (canvas-heavy, headed)
- Steps: 3 · Wall: 23.9s · Outcome: `done` and **visually verified**.
- Step 0: `Click(box=(405, 62))` → rectangle tool selected (visual glyph
  identification, no keyboard shortcut, no help-dialog bypass).
- Step 1: `Drag(start=(412, 350), end=(512, 450))` → ~150×80 css-px
  rectangle drawn near canvas center (8-step interpolated `mouseMoved`,
  no need to bump step count).
- Step 2: `Finished(...)`.
- Browser-use baseline: Phase 2 Smoke 4 / Phase 4 / Phase 5 each took
  6–14 steps to identify the rectangle tool with screenshots embedded as
  DOM-augmented prompts; Phase 9 needed a custom drag action because
  browser-use's primitive set didn't include canvas drag.
- **Comparison**: clear win for the custom client. Canvas-heavy task
  with no useful DOM is exactly the regime the design hypothesized —
  the model's native pixel grounding handled both glyph identification
  and the canvas drag in one shot each. Step count dropped 2-4×, and
  the drag is a built-in primitive rather than a bolt-on action.

### Acceptance (per backlog S-1)
- ✅ Working prototype: `scripts/custom_agent.py` + supporting modules
  (~580 lines of agent code, ~200 lines of probe).
- ✅ Side-by-side comparison entry with at least one task where the
  results diverge: Excalidraw is a clear win for the custom client;
  saucedemo is a clear divergence in failure mode (loop vs false
  success) even though the user-visible outcome is "neither succeeds."
- The S-1 hypothesis ("UI-Venus's native format unlocks capability that
  browser-use's DOM-augmented prompts leave on the table on canvas /
  nested-anchor pages") is **partially confirmed**: yes for canvas
  (Excalidraw), no for nested-anchor headless (saucedemo) — that
  failure is below the framework layer.

### Implications
- For canvas-heavy tasks with sparse, well-spaced targets, the custom
  client is the right tool. Step count and code-size both drop sharply
  vs. browser-use.
- For dense small-target UIs (saucedemo product grid, top-right cart
  icon), the merged 8B's visual grounding is not precise enough — both
  headless AND headed runs miss by 20–50+ px on the same targets.
  Larger model (UI-Venus-1.5-30B-A3B, per the README's benchmark
  table), grounding-prompt single-shot mode for individual click
  decisions instead of full navigation chat template, or DOM-augmented
  prompts (i.e. just use browser-use for these UIs) are the three
  obvious mitigations.
- Honesty prompting ("report what blocked you rather than pretending to
  succeed") was insufficient — the model emitted `Finished` on a
  failed cart click in both modes. A verify-then-finish wrapper (take
  screenshot after `Finished`, ask the model "does this satisfy the
  task?") would have caught it; deferred as future work.

### Caveats
- Three runs total, n=1 each (saucedemo headless, saucedemo headed,
  Excalidraw headed). Replication on different runs / different sites
  would harden the conclusions. Excalidraw in particular benefits from
  a clean, static page; sites with popups, A/B tests, or shadow-DOM
  may behave differently.
- Run artifacts preserved at `/tmp/custom_agent_*_saucedemo*`,
  `/tmp/custom_agent_*_saucedemo_headed*`, and
  `/tmp/custom_agent_*_excalidraw*` — they will be cleared next reboot
  (tmpfs).

---

## Open questions for retro
1. ~~Are we leaving UI-Venus's grounding capability on the table by using
   browser-use? Worth a custom client for canvas-heavy use cases?~~
   **Answered in Phase 11**: yes for canvas (Excalidraw 3 steps / 24s
   vs browser-use's multi-step F-1+F-2 setup). No for nested-anchor
   headless DOM traps (saucedemo cart-icon failed both ways). Use the
   custom client for canvas / shadow-DOM / heavy-visual UIs; stick with
   browser-use for richly-DOM'd pages.
2. ~~Recovery prompt: would `extend_system_message` with "if action didn't
   change page, try X, Y, Z" fix the loop-on-failed-click pattern?~~
   **Answered in Phase 6**: partial yes for stuck-planning loops, no for
   silent-action-failure loops (saucedemo cart icon). Fix needs framework
   or action-level changes, not prompt-level.
3. Q4_K_M vs Q5_K_M / Q6_K — does grounding accuracy degrade on visual tasks?
   Phase 5 added a Q5_K_M data point on the Excalidraw toolbar task; Q5
   came out closer to Q4 than Q6 with an additional behavior anomaly. A
   second visual task would harden the n=1 conclusion. f16 intermediate
   has been deleted (see Phase 4); re-quantizing now means re-download +
   re-convert from safetensors (~15 min).
4. ~~Headed mode is a hard requirement for sites with nested-anchor cart
   patterns. For unattended runs, do we need `xvfb-run` or `--ozone-platform=
   headless`?~~ **Partially answered in Phase 7**: `xvfb-run` reproduces
   the headless click-failure bug. `--ozone-platform=headless` and Xvnc
   remain untested but are tier-2 options if an unattended path becomes
   required.
5. Context budget: 32K worked for a 22-step run. What's the ceiling before
   we need KV quantization (`--cache-type-k q8_0`) to keep VRAM in budget?
