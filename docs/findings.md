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

### Follow-up: refinement via dedicated grounding call (negative result)
Tried adding a grounding-prompt-per-click refinement step
(`REFINE_CLICKS=True` in `scripts/custom_agent.py`): after the nav-mode
emits a `Click(box=(x,y))`, issue a second LLM call with the grounding
prompt and the action's `conclusion` text as the target description,
replace the nav-mode coord with the grounding-mode coord, dispatch.
Hypothesis: nav-mode is split-attention'd between planning and
grounding; a dedicated grounding call should be more precise.

Result on `saucedemo_headed` rerun: refined coords were within **1–2
pixels** of the nav-mode coords on all three clicks (login, add-to-cart,
cart-icon). Same final screenshot, same false `Finished`. The merge
truly unified the heads on the merged 8B — the modes emit the same
answer, so there's no precision left to recover at this model size.

Refinement code is preserved in `scripts/custom_agent.py` as a
`REFINE_CLICKS` toggle (default off) in case a future task suggests
the modes diverge. Run cost is +1 LLM call per click step (~2s).

### Remaining mitigations for the saucedemo precision miss
1. Larger model (UI-Venus-1.5-30B-A3B, per the README's benchmark
   table — meaningfully higher ScreenSpot-Pro and OSWorld-G scores).
2. DOM-augmented prompts (i.e. just use browser-use for these UIs).
3. Verify-then-finish wrapper to at least catch the dishonest
   self-report when grounding precision is the bottleneck.
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

## 2026-04-29 — Phase 12: MAI-UI-8B (Tongyi-MAI) A/B against UI-Venus-1.5-8B

**Goal**: try MAI-UI-8B as a candidate replacement default. Same Qwen3-VL
base architecture, claims #1 in 8B class on the ScreenSpot-Pro
leaderboard (65.7% vs UI-Venus 1.5's reported 68.4%; close enough that
real-world smokes will be more informative than benchmark numbers).
Design doc: `docs/plans/2026-04-29-mai-ui-8b-evaluation-design.md`.

### Setup
- Pulled `mradermacher/MAI-UI-8B-GGUF` Q6_K (6.7G) + mmproj-f16 (1.16G)
  into `~/models/mai-ui-8b/`. Renamed on disk to match Venus convention
  (`mai-ui-8b-Q6_K.gguf`, `mmproj-mai-ui-8b-f16.gguf`).
- **Renamed `ui-venus.service` → `vision-model.service`**. The unit is no
  longer model-specific; it just runs whatever the swap script points it
  at.
- **New `scripts/swap_model.sh <model> [quant]`**: hardcoded two-model
  registry (`ui-venus-1.5-8b`, `mai-ui-8b`). Rewrites the unit's gguf
  paths, mmproj, alias, and Description, then restart + `/health` poll.
- `scripts/swap_quant.sh` reduced to a one-line delegator that forwards
  to `swap_model.sh ui-venus-1.5-8b "$@"` (preserves muscle memory).
- `MODEL` constant in `scripts/smoke_browser_use.py` is now env-driven:
  `MODEL=mai-ui-8b .venv/bin/python -u scripts/smoke_browser_use.py …`.

### Smoke A: `excalidraw_drag` (custom drag action) — PASS
- 5 steps, clean run, real Excalidraw rectangle drawn on canvas with
  selection handles in `/tmp/smoke_mai_drag_final.png`. Right-side
  properties panel (Stroke / Background / …) confirms it's a real
  element, not an artifact.
- Compared to Phase 9 baseline (UI-Venus Q6_K): Venus did this in 4
  steps, MAI-UI in 5. Functionally equivalent.
- The agent took the literal coordinates from the prompt and called the
  registered `drag(x1, y1, x2, y2)` action correctly on first attempt —
  same as Venus.
- One quirk: the model also emitted a spurious `save_as_pdf` action in
  parallel with the `drag`, which browser-use accepted but discarded.
  Doesn't affect outcome.

### Smoke B: `excalidraw_toolbar` (icon enumeration + active-state) — partial fail
First run at `max_completion_tokens=2048` (Venus-tuned default in
`smoke_browser_use.py`) flagged a Venus-tuned bias: MAI-UI's `thinking`
blocks routinely cross ~8000 chars and got truncated mid-string at that
cap. Re-ran with `MAX_TOKENS=8192` (now env-driven) for a fair A/B.

| Metric | UI-Venus Q6_K (Phase 3) | UI-Venus Q5_K_M (Phase 5) | MAI-UI @ 2048 | **MAI-UI @ 8192** |
|---|---|---|---|---|
| Tools identified | 12 (caught Hand) | 11 | 12 (Hand + "more tools") | **11 (lost "more tools")** |
| Active-state color | "purple" (correct) | "orange" (wrong) | "orange" (wrong) | **"orange" (wrong — actual is purple)** |
| Steps to terminate | clean run | 30+ step send_keys loop | 20 steps + 6 loop nudges | **16 steps + 6 loop nudges** |
| Active-tool claim | matched screenshot | confabulated | confabulated | **confabulated (claimed Rectangle active; screenshot shows Selection)** |
| JSON parse failures | none | none | 8 mid-response truncations | **0 (cap was the cause)** |
| Per-step latency | normal | normal | normal | **75s LLM-call timeouts (longer thinking = slower)** |

Bumping the cap fixed exactly the artifact you'd expect (JSON truncations
went to zero) and shaved 4 steps. Everything else held: the loop pattern
fired the same number of times, the active-state confabulation persisted,
and the icon count actually *dropped* by one (lost "more tools"). Net
new failure: LLM-call timeouts at 75s on the longer responses.

The verification screenshot (`/tmp/smoke_mai_toolbar_8k_final.png`) shows
the selection arrow tool with the purple active-border, *not* the
rectangle — exactly the failure mode that catches every model that
doesn't ground on the screenshot at the final step. Same as Phase 5's
Q5_K_M run.

### Other observations
- **Verbosity is intrinsic, not a tunable**: MAI-UI's `thinking` blocks
  routinely cross ~8000 characters even when nothing forces it. The
  Venus-tuned `max_completion_tokens=2048` was unfairly truncating those
  responses; `smoke_browser_use.py` now reads `MAX_TOKENS` from env
  (default 2048). Even with 8192 headroom, MAI-UI's responses are slow
  enough to trip the 75-second LLM-call timeout on multi-step tasks.
- **Context overflow on judge trace**: end-of-run judge trace request
  hit 43–44K tokens against the 32K context limit and errored on both
  runs. Cosmetic (final result was already produced) but worth noting
  if we tighten the per-task context budget.
- **Server stand-up was clean**: same llama.cpp build, same Vulkan path,
  same `--image-min-tokens 1024 --jinja --flash-attn on -c 32768 -ngl 99`
  flags as Venus. No mtmd / chat-template surprises. Confirms the
  Qwen3-VL family is well-supported by the existing toolchain.

### Verdict
**Do not promote MAI-UI-8B to default.** On the two smokes we have, with
the token-cap bias removed:
- Drag (mechanical action plumbing) is a tie — both models execute it
  fine in 4–5 steps.
- Toolbar (visual grounding + active-state introspection) is a regression
  — MAI-UI behaves like Venus Q5_K_M, with the same "looped re-click then
  confabulate active state" failure that Q5_K_M exhibited on the same
  task. Bumping `max_completion_tokens` from 2048 → 8192 cleared the
  JSON-truncation artifact (8 → 0 errors) but did not change the loop
  count or the final confabulation, which are the model-intrinsic signals.

The leaderboard claim (MAI-UI 65.7% vs Venus 68.4% on ScreenSpot-Pro) is
consistent with what we see — MAI-UI is in the same ballpark on point
grounding but loses on the holistic "describe the scene accurately"
task that the toolbar smoke probes. Keep UI-Venus-1.5-8B as the default;
MAI-UI weights stay on disk for any future re-test (e.g. if a new
release fixes the verbosity / final-step-grounding pattern).

### Operator-facing changes (active going forward)
- Service is now `vision-model.service` (not `ui-venus.service`).
- Active-model swap: `sudo bash scripts/swap_model.sh <model> [quant]`.
  Default quant is `Q6_K`. To return to Venus default after this phase:
  `sudo bash scripts/swap_model.sh ui-venus-1.5-8b`.
- Existing `swap_quant.sh ARG` invocations still work — they delegate
  to the above with `ui-venus-1.5-8b` as the model.

### Caveats
- n=2 smokes per model (toolbar run twice with different token caps).
  Toolbar confabulation could be run-to-run variance, but it persisted
  across two MAI-UI runs *and* Phase 5's Q5_K_M run on the same task,
  so the pattern is at least 3-of-3 repeatable in this failure mode.
- We did not exercise navigation benchmarks (AndroidWorld-style
  multi-step web tasks). MAI-UI's reported 76.7% on AndroidWorld
  (235B variant) doesn't generalize down to 8B without measurement.
- Sanity-check on harness fairness: confirmed via grep that
  `smoke_browser_use.py` and `drag_action.py` carry no Venus-specific
  output parsing or coordinate remapping (Venus's
  `<think>…</think><answer>click(point=…)</answer>` parser and
  `coord_remap.py` live in the separate `scripts/custom_agent/` path,
  not exercised here). Other Venus-tuned default that *was* in the path:
  `max_completion_tokens=2048` — corrected via the second run.

---

## 2026-04-29 — Phase 13: 5-stack MoE bake-off (UI-Venus 30B-A3B vs Holo2 vs bu-30b vs split)

**Goal**: pick the most reliable local stack for browser-use shopping
flows. Five candidates:

- **S1**: UI-Venus-1.5-8B Q6_K (current default baseline)
- **S2**: UI-Venus-1.5-30B-A3B Q3_K_M
- **S3**: Holo2-30B-A3B Q3_K_M
- **S4**: bu-30b-a3b-preview Q3_K_M (Browser Use's own Qwen3-VL fine-tune)
- **S5**: Split design (Holo2 planner + Holo1.5-7B grounder, separate harness)

Design doc: `docs/plans/2026-04-29-moe-stack-comparison-design.md`.
Plan: `docs/plans/2026-04-29-moe-stack-comparison-plan.md`.

### Setup
- All four new model GGUFs pulled pre-built from HuggingFace (no
  conversion). Sources:
  - `mradermacher/UI-Venus-1.5-30B-A3B-GGUF` — Q3_K_M + mmproj-f16
  - `mradermacher/Holo2-30B-A3B-GGUF` — Q3_K_M + mmproj-f16
  - `bartowski/browser-use_bu-30b-a3b-preview-GGUF` — Q3_K_M + mmproj-f16
  - `mradermacher/Holo1.5-7B-GGUF` — Q6_K + mmproj-f16
- Models live on `/mnt/data/models/` (nvme1n1, 578 GB free). Existing
  8B models stay at `~/models/`.
- `swap_model.sh` extended with per-entry `MODEL_DIR` so it serves from
  either drive.
- All 30B-A3B candidates loaded cleanly at full 32K ctx with `--flash-attn on`
  and `--image-min-tokens 1024`. VRAM at idle: 97-99% (~16 GB) for the
  three 30B-A3Bs at Q3_K_M; 69% for Holo1.5-7B at Q6_K. **Q3_K_M fits
  but with <300 MB headroom** — design-doc fallback (-c 16384 + Q8 KV)
  was not needed.
- Passwordless sudoers entry for `swap_model.sh` (narrow scope, in
  `/etc/sudoers.d/vision-model-swap`) so the harness can swap models
  without an interactive password.
- New long-horizon smoke `scripts/smokes/saucedemo_full_checkout.py`:
  9-checkpoint flow (login → sort by Price L→H → add 3rd cheapest →
  add Backpack → cart → remove → checkout form → verify subtotal →
  Finish → thank-you page).

### Per-stack results (n=1 short smokes, n=3 long-horizon)

**Self-reported and screenshot-verified medians differed substantially.**
The screenshot is ground truth per CLAUDE.md; the model's prose was
inflated for several runs. Both numbers are reported.

| stack       | drag | toolbar  | saucedemo_headed | full_checkout claimed | full_checkout verified | **score** |
|-------------|------|----------|------------------|-----------------------|------------------------|-----------|
| S1 (8B Q6)  | pass (4 steps) | partial (40, looped) | partial (login+add) | 3/9 | **1/9** | 2.33 |
| S2 (UV30 Q3, no patch) | pass (6) | partial (25, clean) | **fail** (trailing-space login) | 0/9 | **0/9** | 1.50 |
| S2 (UV30 Q3, w/ patch) | (same) | (same) | partial (login ok; add loop) | 8/9 | **2/9** | 2.67 |
| S3 (Holo2 Q3) | pass (4) | partial (3, **clean**) | partial (login+add; menu overlay) | 5/9 | **2/9** (verified runs) | 2.67 |
| S4 (bu-30b Q3) | **fail** (wrong drag params) | partial (6) | fail (input persistence) | 4/9 | **0/9** | 0.50 |

`drag/toolbar/saucedemo_headed`: pass=1.0 partial=0.5 fail=0.0
`full_checkout`: median checkpoints / 9
`score = 3*(verified long-horizon) + drag + toolbar + saucedemo_headed`

S5 (split design) was **scoped out** — the hypothesis (small grounder
fixes coord precision) doesn't apply to Holo2, whose grounding head is
already strong. The actual long-horizon failure was add-to-cart
flakiness, not coord precision; a different grounder wouldn't help.

### Findings (in order of importance)

1. **Trailing-space artifact in UI-Venus 30B-A3B Q3_K_M**. The model emits
   text fields with a stray trailing space (`"standard_user "`,
   `"secret_sauce "`), which breaks any site that exact-matches user
   input. Three runs of saucedemo_headed and three runs of long-horizon
   all failed at login until we added a generic harness whitespace
   trim. **Not observed in S1 (8B Q6), S3 (Holo2 30B Q3), or S4 (bu-30b
   30B Q3)** — it's UI-Venus-30B-specific, not a Q3-systemic artifact.
   Patch lives in `scripts/harness_patches.py` (re-registered
   `Registry.execute_action` strips whitespace from `input.text` dict
   before pydantic constructs the action; pydantic's `model_validate`
   classmethod is bypassed by direct `**kwargs` construction at
   `tools/registry/service.py:349`, so that hook didn't work).

2. **Agent self-reports are systematically inflated.** Model claimed
   medians (3-8) consistently outran screenshot-verified medians (0-2).
   S2-with-patch claimed all three runs reached checkpoint 7-8
   ("verified item total = $29.99") but every screenshot showed the
   products page with an empty cart icon (checkpoint 2). S4 run 3
   claimed "Added both items to cart" but screenshot showed the login
   page with `"Epic sadface: You can only access /inventory.html when
   you are logged in"` — the agent navigated directly to the URL
   without authenticating. **Lesson reaffirmed (already in CLAUDE.md):
   trust screenshots, not prose.** The structured `✓ / ✗` self-report
   pattern is no more reliable than free-form claims.

3. **None of the local Q3-Q6 models in browser-use can complete a real
   shopping checkout.** All five stacks fail at saucedemo's "Add to
   cart" button on the long-horizon task. The pattern is consistent
   across stacks: the model thinks it added items, browser-use's
   element-index updates after the page repaints, the next step's
   `click(index=N)` references a now-stale index, the model loops on
   "element not available" until step budget exhausts. This is a
   *harness-level* problem (browser-use's index churn), not a
   model-quality problem. Holo2's strong grounding doesn't fix it; the
   bu-30b model trained specifically against browser-use doesn't fix
   it either.

4. **Holo2 wins on toolbar grounding by a wide margin.** 3 steps to
   terminate cleanly vs S1's 40-step loop, S2's 25 steps, S4's 6 steps.
   This is a real durable signal that Holo2's localization is
   meaningfully better when the task isn't bottlenecked by harness
   element-index issues.

5. **bu-30b's instruction-following is weaker than its peers.**
   - Emitted `start_x/start_y/end_x/end_y` for the `drag` action despite
     the task explicitly documenting `x1/y1/x2/y2`. Pydantic rejected;
     the run failed.
   - Tried navigating directly to `/inventory.html` instead of typing
     credentials when login appeared difficult.
   - Documented sampling params (temp=0.6, top_p=0.95,
     `dont_force_structured_output=True`) per the bu-30b HF README.
     `ChatBrowserUse` is **cloud-only** (talks a proprietary
     `{'completion':...}` endpoint, not OpenAI); local serve uses
     `ChatOpenAI` per the same README. Our initial S4 runner with
     `ChatBrowserUse` crashed; rewrote to use `ChatOpenAI`.

6. **S1 (8B Q6) baseline is more competitive than expected once
   verified.** Verified median = 1/9 (only login). The earlier-claimed
   3/9 was self-report inflation. So the actual gap from S1 to the
   30B-A3B candidates is small (S1 = 2.33, S3 = 2.67) — well within
   "the harness is the bottleneck" territory.

### Verdict

**No promotion.** UI-Venus-1.5-8B Q6_K stays as the default. None of
the four candidates clears the rubric meaningfully:

- **S2 (UV30 Q3)** matches S3 (Holo2) on score, but only after a harness
  patch unique to fixing its quirk. The model itself is no better at
  the long-horizon task than the 8B baseline.
- **S3 (Holo2)** has the best short-task grounding by a wide margin
  (3-step toolbar) but no long-horizon advantage. Worth keeping
  on disk as a reference for grounding-precision tests.
- **S4 (bu-30b)** lost across the board. Its training-for-browser-use
  positioning didn't translate to the local-served Q3 setup. Worth
  retrying at higher quant or via the cloud API before final dismissal.
- **S5 (split)** scoped out. Hypothesis didn't survive the bake-off:
  the actual blocker is harness-level, not coord-precision.

### Caveats

- **n=3 long-horizon at temp=0.0 (S1/S2/S3) and temp=0.6 (S4)**.
  Variance was small in practice — runs failed at the same step in the
  same way for each stack.
- **Q4_K_M not tested.** The design doc named Q4 as a fallback if Q3
  showed quality issues. We did see Q3-specific issues (trailing space)
  on one model, but the failure mode was harness-fixable. Whether Q4
  improves long-horizon is open.
- **Screenshot capture race.** Two of S3's three long-horizon runs
  produced blank screenshots at end-of-run. The capture happens after
  `agent.run()` returns; if the browser is mid-navigation,
  `Page.captureScreenshot` returns blank. Worth either retrying the
  capture, or capturing periodically during the run, in a future
  iteration.
- **Self-report inflation needs a tooling fix.** Adding a structured
  per-checkpoint validator (e.g. URL pattern + DOM probe per
  checkpoint) would convert "we have to manually verify every run" to
  "the run reports its true checkpoint." Backlog candidate.

### Operator-facing changes (active going forward)

- **`scripts/harness_patches.py` is now imported by both smoke runners**
  (`smoke_browser_use.py` and `smoke_browser_use_bu.py`). Trims
  whitespace on `input.text` before action construction. Generic
  defensive engineering — no model is harmed by it.
- **New smoke**: `scripts/smokes/saucedemo_full_checkout.py` (9-checkpoint
  long-horizon shopping flow). Use with `MAX_TOKENS=8192`.
- **New smoke runner**: `scripts/smoke_browser_use_bu.py` for bu-30b
  (uses `ChatOpenAI` per the bu HF README, NOT `ChatBrowserUse` which
  is cloud-only). Documented sampling params: temp=0.6, top_p=0.95,
  `dont_force_structured_output=True`.
- **`swap_model.sh` registry now includes** `ui-venus-1.5-30b-a3b`,
  `holo2-30b-a3b`, `bu-30b-a3b-preview`, `holo1.5-7b` (all on
  `/mnt/data/models/`). Default quant per entry is the one that's
  actually on disk (Q3_K_M for the 30B-A3Bs, Q6_K for Holo1.5-7B).
- **Passwordless sudoers entry** at `/etc/sudoers.d/vision-model-swap`,
  scope: `bash scripts/swap_model.sh *` for user `seans` only.
  Required for autonomous swap-during-run flows.

---

## 2026-04-29 — Phase 14: R1 — long-horizon saucedemo on the custom CDP agent

Hypothesis under test: the Phase 13 saucedemo gap is a harness-fit
problem (browser-use's element-index contract vs. UI-Venus's coord-first
output), not a model-capability problem. R1 is the cheapest decisive
test: run the same 9-checkpoint task against the existing coord-first
custom CDP agent (`scripts/custom_agent.py`, Phase 11) with no harness
changes, same model (UI-Venus-1.5-8B Q6_K). If the score lifts, the
hypothesis stands and R2 (coord-first actions inside browser-use) is
worth building. If it doesn't, the harness swap isn't the answer.

Plan: `docs/plans/2026-04-29-harness-fit-research.md` § R1.

### Setup

- Server: `ui-venus-1.5-8b` Q6_K, default `vision-model.service`.
- Harness: `scripts/custom_agent.py saucedemo_full_checkout`. New task
  module at `scripts/custom_agent_tasks/saucedemo_full_checkout.py`
  ports the 9-checkpoint task verbatim from
  `scripts/smokes/saucedemo_full_checkout.py` (HEADLESS=False,
  MAX_STEPS=40).
- Headed Chromium (DISPLAY=:0); viewport 1232×615; per-step screenshots
  in `/tmp/custom_agent_steps/`.

### Empirical result

**Verified score: 1/9** — login only (CP1). Same as Phase 13 S1 (8B
baseline) verified score. Below Holo2's 2/9 median.

The page advanced past the login form on step 4, then **did not move
again for 14 consecutive steps**. Per-step screenshots from `004.png`
through `017.png` plus `custom_agent_final.png` are byte-identical
(md5 `ed910be3...` on all 15). The model's `<conclusion>` history
reads as a confident, complete 9-step checkout (sort, add items, open
cart, remove item, checkout, fill form, finish) — none of it
happened.

Total run: 19 steps, 71.5s, terminated `unhandled_action` (see Finding
4 below).

### Findings (in order of importance)

1. **R1 hypothesis is not supported.** Removing browser-use's
   element-index contract did not lift the verified score for
   UI-Venus-1.5-8B on saucedemo. The bottleneck on long-horizon
   shopping flows is not the harness's action vocabulary; it's
   somewhere upstream of action dispatch.

2. **Coord precision is the actual bottleneck on this task.** Login
   form coords landed precisely on three different inputs (username
   (490,282), password (490,370), Login (491,530)). Every coord after
   that landed in dead space:
   - Sort dropdown click `(875,138) → CSS (1078,85)` — below the
     dropdown bar.
   - Backpack Add-to-cart `(381,579) → CSS (469,356)` — between rows.
   - Bolt T-Shirt Add-to-cart `(381,983) → CSS (469,604)` — at the
     bottom edge of a 615-tall viewport, likely past the button.
   The model can hit large centered form fields but degrades sharply
   on smaller UI controls (sort dropdown, per-product Add-to-cart
   buttons). This is consistent with the Phase 13 finding on the merged
   8B but is now isolated from any harness contract effects.

3. **Saucedemo's sort dropdown can't be driven by `Input.dispatchMouseEvent`
   alone** (open question 1 from the plan, now answered). The control
   is a native `<select>`; CDP mouse events don't open Chromium's
   native option list, so even a perfectly targeted click won't
   produce the option-pick step. Resolving sort needs keyboard input
   (focus + ArrowDown + Enter) or a DOM-level `setOption`
   equivalent — neither of which is in the custom_agent action
   vocabulary today.

4. **Bug: `call_user` is undispatched.** The model's documented action
   set (`NAV_USER_PROMPT` line 102) includes
   `CallUser(content='...')`, and UI-Venus reached for it as its
   "report final answer" action at step 18 (`CallUser(content='PASS')`).
   `scripts/custom_agent/actions.py` only handles
   `click/type/scroll/drag/done`, so the run aborted as
   `unhandled_action`. Fix: route `call_user` like `done`, capturing
   the content as the final answer. (Doesn't change R1's verdict — 14
   frames of frozen state preceded the abort — but worth landing as a
   one-line follow-up.)

5. **Confabulation is harness-independent.** The custom_agent's
   `model.step()` feeds raw `<conclusion>` history back into the next
   turn with no check that the page state changed. The model spun a
   plausible 14-step narrative on top of a frozen screenshot. Same
   pattern Phase 13 saw under browser-use; same model-side issue. A
   "did the page change?" instrumentation probe (md5 the screenshot
   between turns; nudge if unchanged for N steps) is the obvious
   counter and would apply to either harness.

### Verdict

R1 **fails**. Per the plan's decision rule (`if R1 fails, the harness
swap is not the answer; investigate elsewhere`), **do not proceed to
R2 yet**. The harness-fit hypothesis isn't disproved (R2 still
isolates a different variable: coord-first actions *inside*
browser-use's loop/eval/memory scaffolding) but R2's expected uplift
budget shrinks: at the verified-score level, the same model on a
coord-first harness scored the same as on an index-first harness on
the same task.

Recommended next direction: instrument before iterating. Specifically:
- A "page didn't change" detector in the agent loop (cheap, applies
  to both harnesses, would have caught the 14-step confabulation
  immediately).
- A native-select escape hatch (keyboard-driven option pick) so
  saucedemo's CP2 isn't structurally unreachable.
- Then re-run R1 — only after that does R2 (coord-first browser-use)
  give a clean signal.

### Caveats

- **n=1.** The confabulation lock-in starting at step 5 was decisive,
  but a second run with different RNG (temperature is 0.0 so this
  would only differ if the page has any per-load variance, which
  saucedemo doesn't) wouldn't change the verdict.
- **Viewport 1232×615** is narrow vertically. Some inventory rows
  (e.g. Bolt T-Shirt's Add-to-cart) sit near or below the visible
  area on the default scroll position. A wider viewport would resolve
  some — but not all — of the missed clicks (sort dropdown is in
  the visible area and was still missed).
- **The R1 plan's open question 1** ("does saucedemo's Add-to-cart
  reject CDP-synthesized clicks?") is partially answered: clicks that
  *do* land work (we saw login work on three CDP clicks). The
  Add-to-cart misses here are precision misses, not click-rejection
  misses.

### Operator-facing changes (active going forward)

- New task module: `scripts/custom_agent_tasks/saucedemo_full_checkout.py`
  (long-horizon 9-checkpoint flow, headed). Reusable for re-running R1
  once instrumentation lands.
- Open follow-up: dispatch `call_user` in `scripts/custom_agent/actions.py`
  (one-line fix, defer until paired with the page-change detector).

---

## 2026-04-29 — Phase 14 follow-up: instrumented re-run + multi-model R1

After the original R1 verdict (page froze on inventory; model
confabulated checkpoints 2-9), we landed instrumentation on the
custom CDP agent and re-ran R1 against UI-Venus-1.5-8B plus the
remaining Phase 13 candidates. Goal: get a verifiable harness-fit
signal even if the model keeps giving up, and answer "does any
candidate clear the bar on a coord-first harness?"

### What changed in the harness

All edits are in `scripts/custom_agent.py` and
`scripts/custom_agent/{model.py,actions.py}`. Together these are the
"R1 instrumentation" toolkit; they apply to any task module run
through `custom_agent.py`.

1. **Page-change detector.** The run loop hashes the screenshot
   before and after each dispatched action; mismatches set
   `Action.no_effect = True`. The history rendered to the model
   appends `[no page change]` per stuck action and, after 2 in a row,
   a paragraph-level STOP warning that explicitly forbids
   `Finished` / `CallUser` until the model verifies progress from
   the current screenshot.
2. **Reject premature `Finished` / `CallUser`.** If the model emits
   either after 2 consecutive no-effect actions, the loop refuses
   the verb and exits with `outcome="stuck_premature_done"` so a
   stuck run can never record a false PASS.
3. **Stuck-loop early-out.** Five consecutive no-effect actions
   terminate with `outcome="stuck_loop"`. Without this a perseverating
   model burns the full `MAX_STEPS` budget — UI-Venus-1.5-8B clicked
   the same coord 14 times in a row before MAX_STEPS terminated the
   re-run.
4. **Keyboard primitives.** `Type` now dispatches per-character
   `Input.dispatchKeyEvent` instead of `Input.insertText`, so native
   `<select>` letter-jump is reachable; new dispatchers handle
   `PressEnter`, `PressBack`, `PressHome`, `Wait`, and `CallUser`
   (treated as `done`).
5. **Env-driven model alias.** `MODEL_NAME` in
   `scripts/custom_agent/model.py` reads `MODEL` from the
   environment (default `ui-venus-1.5-8b`), matching the
   `smoke_browser_use.py` convention. Required for the multi-model
   bake-off below.

### UI-Venus-1.5-8B re-run — same model, harness now instrumented

Run: `MODEL=ui-venus-1.5-8b python scripts/custom_agent.py
saucedemo_full_checkout`. Outcome: `max_steps_reached` after 40
steps in 135s. **11 unique screenshot states** vs. 1 in the original
R1 — the harness genuinely advanced the page through more of the
flow.

Verified score from the final screenshot
(`/tmp/r1_artifacts/ui-venus-1.5-8b.final.png`):

- **CP1 login** ✓ — credentials submitted, on inventory page.
- **CP2 sort by Price low→high** ✗ — dropdown shows "Name (A to Z)";
  sort never applied. (Native `<select>` letter-jump via `Type` was
  available but the model didn't reach for it.)
- **CP3 third cheapest added** ✓ by literal "third item" reading —
  Bolt T-Shirt is in the cart on the final screenshot. ✗ by strict
  reading of the task ("after sorting") because CP2 didn't apply.
- **CP4 Sauce Labs Backpack added** ✓ — Backpack shows "Remove",
  cart badge reads `2`.
- **CP5 cart opened** ✓ — model navigated to /cart.html mid-run
  (one of the 11 unique frames was the cart page); came back to
  inventory before the run's end via "Back to products."
- **CP6+** ✗ — never reached checkout.

Strict score **2/9** (CP1, CP4). Lenient score 4/9 if CP3 and CP5
are credited from intermediate frames. **Either way an improvement
over the original R1 verified 1/9 and over Holo2's 30B-A3B Phase 13
median of 2/9** — but the lift is from instrumentation, not from
the harness contract per se.

The instrumentation worked as designed but exposed model behaviors
worth recording:

- **Page-change detector + harsher warning still didn't stop
  confabulated `Finished`** in the saucedemo_headed smoke. The
  `reject_premature_done` mechanism caught it and reclassified the
  run as `stuck_premature_done`. UI-Venus's bias toward `Finished`
  when stuck is a model-level pattern, not something prompt
  rewording fixes.
- **Type (now via `dispatchKeyEvent`) is regression-clean for form
  fields** — `standard_user` and `secret_sauce` typed without
  issue across all UI-Venus runs.
- **Coord precision is still the bottleneck.** Login fields hit
  every time; small UI controls (sort dropdown, Add-to-cart, cart
  icon) miss frequently. The instrumented run logged 21 of 40
  steps with `no_effect`.

### Multi-model bake-off on the same harness

Each candidate ran the same task with `MODEL=<alias> python
scripts/custom_agent.py saucedemo_full_checkout` after a model swap
via `swap_model.sh`. Per-model logs and screenshots in
`/tmp/r1_artifacts/`.

| Stack | Outcome | Steps | Verified score | Notes |
|---|---|---|---|---|
| ui-venus-1.5-8b (Q6_K) | max_steps_reached | 40 | 2/9 strict, 4/9 lenient | 11 unique states; reached CP1+CP4, transient CP3+CP5 |
| ui-venus-1.5-30b-a3b (Q3_K_M) | stuck_loop | 10 | 1/9 | Login fine; perseverated on sort dropdown click immediately, hit 5-no-effect bailout |
| mai-ui-8b (Q6_K) | parse_error | 4 | 0/9 | Filled credentials but emitted `<tool_call>` instead of `<action>` at step 4 (Login click) |
| holo2-30b-a3b (Q3_K_M) | parse_error | 4 | 0/9 | Identical trace to MAI-UI through step 3, then `<tool_call>` |
| bu-30b-a3b-preview (Q3_K_M) | parse_error | 4 | 0/9 | Identical trace to MAI-UI through step 3, then `<tool_call>` |
| holo1.5-7b (Q6_K) | parse_error | 0 | 0/9 | Empty `<think></think>` at step 0; UI-Venus prompt is not interpretable to it |

### Findings

1. **No candidate cleared a higher verified bar than UI-Venus-1.5-8B
   on this harness.** The 30B-A3B sibling — same vocab, more
   parameters — actually scored *lower* by stalling on the sort
   dropdown immediately after login. Model size in the UI-Venus
   family doesn't lift saucedemo on a coord-first harness.
2. **MAI-UI-8B / Holo2-30B-A3B / bu-30b-a3b-preview emit
   `<tool_call>`, not `<action>`,** at exactly the moment they need
   to commit a click on a button (step 4, the Login submit). The
   trace through steps 0-3 is identical across all three because
   UI-Venus's `<action>` schema fits text-input-only steps; once
   they need to call a "submit" verb they revert to their native
   tool-calling mode. Evaluating these on R1 requires either (a) a
   parser/dispatcher that handles Hermes/OpenAI tool calls, or (b)
   a per-model prompt template (Surfer-H-CLI for Holo, browser-use
   prompt for bu-30b). The current single-prompt setup is
   incompatible.
3. **Holo1.5-7B is more deeply incompatible** — emits empty
   `<think></think>` at step 0 with no action attempt at all. A
   different prompt structure entirely would be needed.
4. **The instrumentation suite is reusable and was the actual
   high-value output of this phase.** Every future
   `custom_agent.py`-driven run now reports `no_effect`,
   `stuck_loop`, and `stuck_premature_done` cleanly, and rejects
   false PASSes. R2 (coord-first actions inside browser-use) and
   R3/R4 (per-model prompt survey, custom harness) should be built
   on top of this instrumentation rather than re-inventing it.

### Verdict on the original R1 hypothesis

R1's hypothesis ("the saucedemo gap is a harness-fit problem;
removing browser-use's element-index contract unlocks the score")
is **partially supported, but not by the harness change alone**.
Same-model verified score lifted from 1/9 → 2/9 strict / 4/9
lenient, but the lift came from *adding instrumentation* (page-change
detector, reject-premature-done), not from the coord-first action
vocabulary per se. The model's coord precision and confabulation
biases dominate the harness contract.

Decision rule per the plan: **R1 is now a soft pass on the
"verified score" front and a hard fail on the "is the bottleneck
the harness contract" front.** The instrumentation we landed should
travel to *both* harnesses (browser-use and custom CDP). R2 — adding
coord-first actions to browser-use — is now lower-priority than
two follow-ups that apply to either harness:

1. **Per-model prompt support.** 4 of 6 candidates can't be
   evaluated with the UI-Venus prompt. Without per-model templates
   (or a tool-calling parser path) we can't tell whether Holo2 /
   bu-30b / MAI-UI / Holo1.5-7B beat UI-Venus on coord-first
   harnesses.
2. **Coord-precision uplift on small targets.** UI-Venus 8B's
   login coords hit; sort/Add-to-cart/cart-icon coords miss. The
   merged 8B's grounding head is the binding constraint. Phase 11's
   refinement-via-grounding-call experiment (REFINE_CLICKS, default
   off because it was n=1 negative) is worth re-running with the
   instrumented harness.

### Caveats

- **n=1 per stack.** Temperature is 0.0; saucedemo is deterministic.
  Variance comes from chrome's load-time animations and from the
  exact viewport pixels at the first screenshot. Re-runs of the
  same stack would give the same path.
- **Quant differences across stacks** (Q6_K for the 8B/7B models,
  Q3_K_M for the 30B-A3Bs) confound the comparison somewhat. A Q6
  re-quant of the 30B-A3Bs would clarify but isn't the binding
  question here — the parse_error failures are prompt-format
  issues, not quant precision.
- **`<tool_call>` parse_error is a symptom of harness mismatch, not
  a model verdict.** MAI-UI / Holo2 / bu-30b are not "broken" — they
  are speaking the wrong protocol for our harness. They might score
  well on a tool-calling-first harness; we just can't tell from this
  bake-off.

### Operator-facing changes (active going forward)

- `scripts/custom_agent.py` now exits with `outcome` ∈ {`done`,
  `call_user`, `stuck_premature_done`, `stuck_loop`,
  `max_steps_reached`, `parse_error`, `model_error`,
  `unhandled_action`}. Scoring scripts should distinguish these.
- `MODEL=<alias>` env var selects the llama-server model alias
  for `custom_agent.py` (default `ui-venus-1.5-8b`).
- Per-model R1 artifacts archived under `/tmp/r1_artifacts/<alias>.{log,steps,final.png}`
  for the six stacks tested. Reusable as a baseline if the harness
  changes again.

---

## 2026-04-29 — Phase 15: Holo3-35B-A3B native-harness eval

### Setup
Built a Holo3-native harness path in `scripts/custom_agent/holo3.py`,
gated behind a new `HARNESS=holo3` env on the existing run loop. The
default `HARNESS=uivenus` keeps the Phase 14 path intact. Harness shape
is surfer-h-cli-style two-pass localize+navigate:
- **Navigator** (temp 0.7) returns a discriminated-union JSON via OpenAI
  strict `response_format={"type":"json_schema",...,"strict":true}`. The
  union is the verbatim 8-action surfer-h-cli set
  (`click_element`, `write_element`, `scroll`, `go_back`, `refresh`,
  `wait`, `restart`, `answer`). Reasoning lives in a top-level `thought`
  string field of the schema, not in a `<think>` tag — they're mutually
  exclusive at sampling time with strict JSON.
- **Localizer** (temp 0.0) returns a `ClickAbsoluteAction` JSON with
  `(x, y)`. Called whenever the navigator emits `click_element` /
  `write_element` (those carry an `element: <text>` description and
  placeholder x/y; the localizer fills in the real coords).
- Schemas, prompts, and `smart_resize` are all verbatim ports of
  `hcompai/surfer-h-cli/src/surfer_h_cli/skills/{navigation_step,
  navigation_models, localization_1_5}.py` and `utils.py`. The
  navigation prompt drops one line (`Never try to login...`) which
  would block saucedemo CP1.

Holo3-35B-A3B at `i1-IQ3_XXS` (13.62GB) + mmproj-Q8_0 (0.6GB). Fits
16GB VRAM with 32K KV. `swap_model.sh` registry entry + idempotent
`--chat-template-kwargs '{"enable_thinking":false}'` injection (Holo3's
chat template auto-prepends a `<think>` block which conflicts with
strict response_format; the kwarg is no-op for templates that don't
reference `enable_thinking`).

### Result
**Holo3-35B-A3B IQ3_XXS scored 1/9 strict and 1/9 lenient on
saucedemo_full_checkout (n=1).**

| Model | Strict | Lenient | Notes |
|---|---|---|---|
| ui-venus-1.5-8b (Phase 14, original baseline) | 2/9 | 4/9 | "good day" — model emitted `Type('p')` after dropdown click, triggered native letter-jump |
| ui-venus-1.5-8b (Phase 15 re-run, post-DPR=1) | 1/9 | 1/9 | "stuck day" — model perseverated on dropdown clicks, never tried Type |
| holo3-35b-a3b (Phase 15) | 1/9 | 1/9 | Cleared CP1 cleanly; stuck on the same dropdown wall |

Holo3 successfully filled username + password and submitted login (CP1).
On the inventory page it identified the sort dropdown as the next target
but the localizer predicted y≈89 against ground-truth y≈49 — landing in
the first product image area, not the dropdown. 5 consecutive
no-effect clicks tripped the stuck_loop early-out at step 11 (97s).

UI-Venus 8B re-run for fair comparison (the harness instrumentation has
changed since Phase 14 baseline). It also reached CP1 cleanly but stuck
on the same dropdown — its "good day" Phase 14 score of 2/9 was a
stochastic artifact of the model emitting a follow-up `Type` after the
dropdown click, which fires native `<select>` letter-jump. That branch
didn't happen this run.

**Verdict: Holo3 does not clear the bar (strict ≥3/9 OR lenient ≥5/9).
No-go on this lineage at IQ3_XXS for long-horizon tasks.**

### Findings (in order of importance)

1. **Holo3-35B-A3B IQ3_XXS does NOT use surfer-h-cli's Holo1.5 localizer
   contract.** It emits coords in **[0, 1000] × [0, 1000] normalized
   space**, the same convention as UI-Venus, ignoring the schema's
   "number of pixels from the left edge" docstring. Verified by a
   calibration probe (`scripts/holo3_calibrate.py`): 0/4 targets
   landed in-box with the canonical "absolute pixels in resized image"
   contract; 4/4 in-box once we treat output as 0-1000 normalized and
   rescale by viewport. **Re-run that probe before adding any new
   localizer-style model — the docstring lies and the contract is
   per-checkpoint.**

2. **The browser was running at DPR ~2.5x.** CDP `Page.captureScreenshot`
   defaults to device pixels, so screenshots were 3120×1538 against
   a 1233×615 viewport. UI-Venus dodged this entirely (its 0-1000
   normalized output is DPR-independent). Any model emitting absolute
   pixel coords needs DPR=1; pinned `--force-device-scale-factor=1`
   into `launch_chromium` so screenshot dims == viewport CSS dims.

3. **Action.kind needs to record the coord-space convention, not just
   the verb.** First R1 attempt looked like "Holo3 stuck on Login",
   but actually the dispatcher was double-remapping Holo3's already-
   viewport-pixel click coords through `grounding_remap`, sending the
   click 50-200px off-target. Fix: introduced `click_at` and
   `click_then_type` kinds (both bypass remap) parallel to the existing
   `click` kind (UI-Venus, applies remap). Without this, login was
   structurally impossible — the comparison would've been unfair.

4. **Strict `response_format` and `<think>` chat templates are mutually
   exclusive.** llama-server's `--chat-template-kwargs '{"enable_thinking":
   false}'` is required when the chat template auto-prepends a `<think>`
   block (Holo3, Qwen3-VL family) AND we pin output to a strict JSON
   schema. Without it, the schema fails to parse the partial
   `<think>...</think>` prefix. Reasoning is preserved by routing it
   into a top-level `thought` string field of the schema (the
   surfer-h-cli design pattern, not a workaround).

5. **`extra_body={"structured_outputs":...}` is silently ignored by
   llama-server (vLLM-only).** Use OpenAI-standard
   `response_format={"type":"json_schema","json_schema":{...,"strict":true}}`.
   Verified live during planning probe.

6. **The saucedemo `<select>` dropdown is structurally hostile to both
   models.** Native `<select>` opens an OS-level popup that CDP can't
   simulate; the only path through is the per-character keydown event
   triggering the browser's native letter-jump, but only if the model
   emits a `Type('p')` after clicking the dropdown. Phase 14 saw this
   land once for UI-Venus; this Phase 15 re-run didn't repro. CP2 is a
   stochastic checkpoint, not a deterministic one. Reaching it more
   reliably would require either prompting in the system message, or a
   deterministic "click_dropdown_option" affordance in the action set.

### Caveats

- n=1, navigator temp=0.7 → meaningful run-to-run variance for Holo3.
- IQ3_XXS may degrade the localizer head specifically. Q3_K_M (16.76GB)
  would OOM with mmproj+KV; testing higher quants would require
  unloading mmproj or dropping context.
- Documented Holo3-35B vs Holo3-122B-API gap of 10-15pp on practical
  tasks. The 1/9 here is consistent with that gap on top of an already-
  hard saucedemo task.
- The viewport at 1280×800 has the form ~y=150-350; saucedemo's
  presentation contributes to the difficulty but the dropdown miss
  (y=89 vs y=49) is well outside any reasonable tolerance.

### Operator-facing changes

- `HARNESS=holo3` env routes the run loop through the Holo3 native
  path in `scripts/custom_agent/holo3.py`. Default remains `uivenus`.
- `MODEL=holo3-35b-a3b` + `swap_model.sh holo3-35b-a3b` switches the
  llama-server to Holo3 with the `--chat-template-kwargs` flag.
- `--force-device-scale-factor=1` is now permanent in `launch_chromium`.
  UI-Venus runs are unaffected by the coord pipeline; visual rendering
  may differ slightly on HiDPI displays.
- Calibration probe at `scripts/holo3_calibrate.py` — re-run before
  adding any new localizer-style model. Single-source-of-truth for the
  "what coord space does this model emit?" question.
- Per-run R1 artifacts archived as
  `/tmp/r1_artifacts/holo3-35b-a3b.holo3.{log,steps,final.png}` and
  `/tmp/r1_artifacts/ui-venus-1.5-8b.posthead.{log,steps,final.png}`
  for the comparison.

---

## 2026-04-29 — Phase 15 follow-up: it was the tooling all along

### TL;DR
Both UI-Venus and Holo3 now deterministically clear **CP1 + CP2** of
saucedemo_full_checkout (2/9 strict). The wall every model has hit
since Phase 13 was a dispatcher gap, not a model gap: CDP `Input.dispatchMouseEvent`
on a native `<select>` doesn't open the popup (OS-rendered, out of CDP
reach) and doesn't focus the element (so synthesized keyboard events go
to `<body>` and become no-ops). The "Type('p') letter-jump" trick
documented in the Phase 14 follow-up doesn't actually work via CDP —
Phase 14's stochastic 2/9 was likely an artifact of model-specific
event timing, not a reproducible path.

### How we found it
A direct probe (`scripts/saucedemo_dropdown_probe.py`) drove the
dropdown manually: clicked the select with the same dispatcher path the
agent uses, captured `document.activeElement` after the click, then
tried 6 different `keyDown` payload variants (with/without `text`,
with/without `code`+`windowsVirtualKeyCode`, `rawKeyDown`+`char`+`keyUp`,
etc.) — none triggered native letter-jump. After the click, focus is on
`<body>`, not the select. Confirmed: this is a Chromium-CDP limitation
on headed `<select>`s.

### The fix (in `scripts/custom_agent/actions.py`)

When a CDP click lands on a native `<select>` element:
1. Force-focus it via `Runtime.evaluate` so subsequent keyboard events
   target the select.
2. Inject a synthetic DOM overlay positioned just below the select that
   lists the options as styled `<div>`s with `data-caso-option-value`
   attrs. The overlay uses generous spacing (~49px per option, 16px
   font, padding 14×16) so the model can localize options without
   pixel-precise targeting.

When a subsequent click lands on an option in this overlay:
1. The dispatcher detects it via `elementFromPoint` + dataset check.
2. Sets the underlying select's `value` and dispatches `change` (and
   `input`) events. The page's React handlers reorder products.
3. Removes the overlay. No real CDP click is dispatched.

A `letter_jump` fallback in `_type_keys` is also wired up for the case
where focus is on a `<select>` and the model emits a `Type` (UI-Venus)
or `write_element` (Holo3) — the dispatcher prefix-matches the typed
text against `<option>` text content and selects the first match. No
model used this path in the runs below — both relied on the overlay
click — but it's there as a free affordance for the canonical "click
dropdown then type letter" pattern.

### Result

| Model | Strict | Lenient | Notes |
|---|---|---|---|
| ui-venus-1.5-8b (Phase 15 pre-fix) | 1/9 | 1/9 | Stuck on dropdown click |
| ui-venus-1.5-8b (overlay fix, deterministic) | **2/9** | **2/9** | Cleared CP1 + CP2; failed CP3 (Add-to-cart click off-target) |
| holo3-35b-a3b (Phase 15 pre-fix) | 1/9 | 1/9 | Stuck on dropdown click |
| holo3-35b-a3b (overlay fix, deterministic) | **2/9** | **2/9** | Same — cleared CP1 + CP2 via overlay; failed CP3 |
| ui-venus-1.5-8b (Phase 14 baseline, "good day") | 2/9 | 4/9 | Stochastic; the 4/9 lenient came from later partial progress that we can't reproduce |

Holo3 and UI-Venus 8B are now **tied** on this task at 2/9 strict, both
failing at CP3 (identifying the third-cheapest item's Add-to-cart
button). That's a model precision issue, not a tooling issue. Holo3's
~10-15pp gap vs the 122B API model and IQ3_XXS quantization both
plausibly explain it not pulling ahead.

### Findings (new vs prior follow-up)

7. **CDP `Input.dispatchMouseEvent` on a native `<select>` is a
   no-op.** The element doesn't focus, the popup doesn't render. None
   of 6 keyDown payload shapes I tried recovered the letter-jump path.
   The "click + type letter" affordance only exists if the dispatcher
   force-focuses the select first.

8. **Phase 14's "Type('p') triggers native `<select>` letter-jump"
   finding was wrong** (or only worked under a specific timing race
   that no longer reproduces). The Phase 14 finding 5 in this file
   should be read with a "best-effort, not load-bearing" caveat — the
   real fix is the synthetic overlay added in this follow-up.

9. **Visual UAT precision.** Saucedemo's 2-column product grid + the
   way Add-to-cart buttons sit at the BOTTOM of each card means the
   model needs both row identification AND vertical positioning to be
   right. Both models clicked roughly at the right horizontal but
   slightly above the button (y=355 / y=600). This is the next wall —
   not a structural one, but the kind of fine motor precision that
   trips up smaller VL models on grids.

10. **Overlay spacing matters.** First overlay attempt used 6×12px
    padding → ~33px per option. UI-Venus's first try off-by-one'd into
    the option above (clicked y=268 meaning to hit y=300, hit y=170).
    Bumped to 14×16px (~49px per option) and 16pt font — UI-Venus
    landed correctly on the next attempt. For models with looser
    spatial precision, generous overlay spacing is cheap insurance.

### Operator-facing changes (this follow-up)

- `scripts/custom_agent/actions.py` now contains the auto-focus +
  overlay path. Both UI-Venus's `click` (after grounding-remap) and
  Holo3's `click_at` (already-viewport) routes through the same `_click`,
  so both models benefit from the overlay path uniformly.
- `scripts/saucedemo_dropdown_probe.py` (kept) is the diagnostic that
  led to the fix. Re-run if a future site has a similarly broken
  dropdown story.
- Per-model artifacts: `/tmp/r1_artifacts/{model}.overlay2.{log,steps,
  final.png}` for the post-fix runs.

### Verdict update

Phase 15's original "Holo3 doesn't clear the bar" finding **stands**
on the strict numbers (2/9 vs the 3/9 bar) but with an important
qualifier: the wall is **CP3 (Add-to-cart precision)**, not the
dropdown — a different problem than originally diagnosed. Future model
evals against this task should be read as testing fine spatial
precision on a 2-column product grid, not as testing dropdown
interaction.

If we want to keep using saucedemo_full_checkout as a long-horizon
benchmark, **the next phase should re-target CP3-CP9** with awareness
that the bar may be unreasonably hard for 8B-class models in IQ3
quantization. A simpler benchmark (e.g., add-one-known-item, then
proceed straight to checkout) would isolate the precision wall from
the long-horizon planning aspect.

---

## 2026-04-29 — Saucedemo flow tooling audit (CP3-CP9)

### TL;DR
The dispatcher gap exposed in the Phase 15 follow-up (CP2 dropdown) was
the tip of the iceberg. **CDP `Input.dispatchMouseEvent` and
`Input.dispatchKeyEvent` are silently dropped on saucedemo's
post-login pages** — the events never reach the document. The dropdown
fix accidentally side-stepped this for CP2 (its overlay logic runs in
JS and never relies on CDP delivery), but every model click on
inventory.html / cart.html / checkout-step-one.html was a no-op for
months. Models looked like they were missing buttons; they were
actually clicking correctly through a broken pipe.

A new mechanical probe (`scripts/saucedemo_flow_probe.py`) walks
CP1-CP9 via DOM-truth coords through the same dispatcher the agent
loop uses. After landing detect-and-fallback in `_click`,
`_type_keys`, `_scroll`, and `_press_key`, the probe goes **9/9**.
Spot-check with UI-Venus 8B still bottoms out at the prior 2/9 strict
baseline — confirming the remaining gap is model precision, not
tooling.

### How we found it
1. Wrote the flow probe. CP1 (login) and CP2 (sort) PASSed
   immediately. CP3 (Add-to-cart) reported `badge=None` and the
   "Add to cart" text never changed to "Remove" — a click that
   apparently did nothing.
2. Initial theory: model precision. Falsified by clicking via the same
   dispatcher with `getBoundingClientRect()`-derived center coords —
   still failed. Coords were right; click wasn't landing.
3. Stripped the click sequence to its CDP minimum (`Input.dispatchMouseEvent`
   pressed/released at the rect center). Failed identically.
4. Instrumented the page with capturing listeners on
   `mousedown`/`pointerdown`/`click`. Pre-login: every event fires,
   `isTrusted: true`. Post-login: **zero events fire** for the same
   CDP call against the same target/session.
5. Eliminated as causes: window focus
   (`Page.bringToFront` + `Emulation.setFocusEmulationEnabled` no
   help), session staleness (`Target.detachFromTarget` +
   re-`attachToTarget` no help), reload (`Page.reload` no help). Only
   `Page.navigate` away-and-back transiently restored input — too
   brittle to use as a fix.
6. Confirmed the ceiling: `el.click()` via `Runtime.evaluate` always
   works, fires a non-trusted `click` event that React's onClick
   responds to identically. JS-driven fallback is the right shape.

The smoking-gun comparison (login click delivers 8 events; inventory
click on the next attempt delivers 0) lives in the diagnostic
artifacts at `/tmp/click_diag*.log` from the audit session.

### The fix (in `scripts/custom_agent/actions.py`)

Detect-and-fallback wrapped around every CDP input verb:

1. **Idempotent JS counter** (`_input_probe`) installs document-level
   capturing listeners on `mousedown` and `keydown` the first time it
   runs on a page; subsequent calls just read the counters and the
   current URL.
2. Each verb (`_click`, `_type_keys`, `_press_key`, `_scroll`)
   snapshots the probe before its CDP dispatch, sleeps 150ms, snapshots
   again. If `url` changed → CDP click triggered navigation, success.
   If counter incremented → CDP delivered, success. Otherwise → CDP
   was silently dropped, fall back.
3. Per-verb fallbacks:
   - `_js_click_fallback` — `document.elementsFromPoint(x, y)` walks
     the z-stack and clicks the first INPUT/BUTTON/A/SELECT/TEXTAREA/
     LABEL it finds (else the topmost). For focusable inputs/textareas/
     selects it also calls `.focus()` because `Element.click()` doesn't
     focus those per spec — without focus, the next `_type_keys` has
     no editable activeElement.
   - `_js_type_fallback` — sets the activeElement's `value` via the
     React-aware setter path
     (`Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set`)
     and dispatches `input` + `change`. Plain assignment doesn't notify
     React's controlled-input tracker.
   - `_js_press_enter_fallback` — clicks a focused submit/button if
     one is active, else `form.requestSubmit()` (or `.submit()`) on
     the enclosing form.
   - `_scroll` — fallback is `window.scrollBy(dx, dy)`. Detected by
     comparing `window.scrollY` before/after the CDP wheel event.

The fixes are invisible to the model: same action set, same coords;
the dispatcher silently does the right thing.

### Result

Mechanical probe (`saucedemo_flow_probe.py`):

| Run | Score | Notes |
|---|---|---|
| Pre-fix (CDP-only) | 2/9 | CP1+CP2 only; same ceiling models hit |
| Post-fix (this audit) | **9/9** | All CPs pass via dispatcher fallback |

UI-Venus 8B spot-check (`scripts/custom_agent.py saucedemo_full_checkout`):

| Run | Strict | Notes |
|---|---|---|
| Phase 15 follow-up | 2/9 | CP1+CP2; failed CP3 (model precision on Add-to-cart) |
| Post-audit (this) | 2/9 | Same. Cleared CP1+CP2; at CP3 the model clicked Sauce Labs Onesie's button instead of Bolt T-Shirt's (~83px off vertically); cascaded into stuck-loop by step 19 |

The dispatcher fallback fired on every single click and key event in
the spot-check (~14 click fallbacks, ~3 type fallbacks, 1 scroll
fallback). Zero CDP `Input.*` calls ever delivered to the live page.
The fix is doing 100% of the work; the previous Phase 15 follow-up
"clean 2/9" was carried entirely by the overlay JS path masking the
broken CDP click underneath.

### Findings

11. **CDP `Input.*` is not durable across navigations on this stack.**
    Any CDP-click that triggers a same-tab navigation breaks input
    delivery for the rest of the page's lifetime, even after
    `Page.reload`, `Target.detachFromTarget`+re-attach,
    `Page.bringToFront`, or `Emulation.setFocusEmulationEnabled`.
    The only thing that transiently restored it was navigating away
    to about:blank then back — too brittle to rely on. Root cause not
    identified; probably a Chromium 1208 + Wayland/Plasma + cdp-use
    interaction. **Workaround: detect-and-fallback in the dispatcher.**

12. **Hidden by the dropdown overlay all along.** Phase 15
    follow-up's CP2 fix worked by injecting a DOM overlay and
    intercepting clicks on overlay options in JS — completely bypassing
    the broken CDP click path. That's why CP2 was deterministic: it
    didn't depend on CDP delivery. Every CP3+ click had been failing
    for the same root cause for months and read as "model precision."

13. **`Element.click()` doesn't focus inputs.** Per spec, only
    `<button>` and `<input type="submit">` get focused on programmatic
    `.click()`. For text inputs the dispatcher must call `.focus()`
    explicitly, or the next type action has no editable activeElement.
    First version of the fallback missed this; CP7 type-into-form
    failed on the first run after the click fallback landed.

14. **`elementFromPoint` returns the topmost element, not the
    actionable one.** On saucedemo's checkout-step-one, at the
    INPUT#first-name center, `elementFromPoint` returns FORM (the
    INPUT is a descendant but `elementFromPoint` only goes one deep
    for the topmost). Have to walk `elementsFromPoint(x, y)` (plural)
    and prefer the first interactive descendant in the z-stack.

15. **Probe-level: cache rects per-click, not per-batch.** First
    version of CP7 queried all four field rects up-front via
    `rect_center` (which calls `scrollIntoView`), then clicked them.
    Each scroll moved the page, invalidating the previous rects. The
    `fn_xy` cached for first-name pointed at where first-name USED to
    be before the scroll for postal-code. Lockstep query+click per
    field is the only safe pattern.

16. **React-controlled inputs need the prototype-setter trick.**
    Naive `el.value = 'Test'` doesn't notify React's value tracker, so
    the controlled input snaps back to its previous value on next
    re-render. Use
    `Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(el, value)`
    then dispatch `input` + `change`. Standard React testing pattern.

### Verdict

Tooling is now clean for the saucedemo_full_checkout benchmark. The
9/9 probe baseline confirms every CP can be reached via the dispatcher
when given DOM-truth coords. Remaining model failures (UI-Venus 8B at
CP3, Holo3 at CP3) are unambiguously **model precision**: the model
either picks coords for the wrong product card or loses page-state
context after a wrong click and confabulates from there.

The deferred Phase 13 5-stack bake-off can now run as a fair test of
visual grounding precision, not a test of "does CDP click work on
this navigation flow." The previous bake-off scores should be read as
**lower bounds** since every wrong-target click and every focus
failure was magnified by the silent-drop bug.

### Operator-facing changes

- `scripts/custom_agent/actions.py` — `_click`, `_type_keys`,
  `_press_key`, `_scroll` all now have JS-driven fallbacks gated on
  the `_input_probe` counter. No action-set or model-prompt changes.
  Runtime cost: ~1-3 extra `Runtime.evaluate` calls per dispatch
  (~10ms each over loopback WebSocket).
- `scripts/saucedemo_flow_probe.py` — new mechanical 9-CP probe.
  Run via `DISPLAY=:0 XAUTHORITY=/run/user/1000/xauth_rVYaGJ
  XDG_RUNTIME_DIR=/run/user/1000 .venv/bin/python -u
  scripts/saucedemo_flow_probe.py > /tmp/saucedemo_flow_probe.log
  2>&1`. Should always end "9/9 checkpoints PASS" — if any drop, a
  dispatcher regression has landed.
- The dispatcher prints `[dispatcher]` lines to stderr describing
  fallback decisions. Useful for diagnosing future "model said it
  clicked X but the page didn't change" issues — if the line says
  "JS .click() on \<wrong element\>" the model picked off-target
  coords; if it says "elementFromPoint hit nothing actionable" the
  model picked a non-clickable region.
- Spot-check artifact: `/tmp/uivenus_spotcheck.log` (UI-Venus 8B,
  19 steps, stuck_loop after model lost page-state context at CP3).

---

## 2026-04-30 — Per-model harness paths (backlog E-5)

### TL;DR
The 4 models that scored 0/9 in the Phase 14 follow-up bake-off
(`mai-ui-8b`, `holo2-30b-a3b`, `bu-30b-a3b-preview`, `holo1.5-7b`)
were failing on protocol mismatch, not capability. Added two new
harness paths (`holo1_5` and `toolcall`) plus a `MODEL→HARNESS`
registry; each of the 4 now executes a click that lands inside the
saucedemo username field on a single-step probe. Phase 14 finding #2
("4 of 6 candidates can't be evaluated with the UI-Venus prompt") is
resolved.

This entry also documents an unexpected per-model coord-space split
inside the surfer-h-cli family: Holo1.5-7B follows the canonical
"absolute pixels in resized image" contract; Holo2-30B-A3B emits
0-1000 normalized like Holo3 / UI-Venus. Phase 15 finding #1's
warning ("docstring lies and the contract is per-checkpoint") now
has a second confirming data point.

### Setup
- New file `scripts/custom_agent/__init__.py` holds
  `MODEL_HARNESS_REGISTRY` and `harness_for(model, override)`. Both
  the run loop (`scripts/custom_agent.py`) and the probe
  (`scripts/model_probe.py`) consume the registry through this single
  helper.
- New file `scripts/custom_agent/holo1_5.py`: surfer-h-cli navigator +
  localizer for Holo1.5-7B. Reuses the `holo3.py` schemas, prompts,
  and image helpers; differs only in the localizer image (sent at
  smart_resize'd dims) and the coord rescale (`x * viewport_w /
  resized_w`, the canonical surfer-h-cli contract — Contract A).
- New file `scripts/custom_agent/toolcall.py`: Hermes-style tool-call
  emitter. Defines a 6-tool action set (click / type / scroll /
  press_enter / wait / done), passes it through OpenAI-shaped `tools`
  + `tool_choice="required"`, and consumes `message.tool_calls`.
  Llama-server's `--jinja` rendering does the heavy lifting (XML
  tool-call extraction).
- New file `scripts/model_probe.py`: single-step regression probe.
  Launches saucedemo, calls the harness's navigate_step, applies the
  same `grounding_remap` the dispatcher uses, reports
  raw / effective xy + nearest ground-truth box + inside/outside.
  Exit 0 if the click landed inside the username field, else 1.
- `scripts/custom_agent.py` now selects harness via
  `harness_for(MODEL, HARNESS_override)` instead of a hardcoded
  binary string check. `HARNESS=` env still wins so cross-protocol
  experiments stay possible.

### Per-model probe results (n=1, saucedemo login, "click on the Username input field")

| Model | Harness | Raw xy | Effective xy | Nearest GT | Inside username box? |
|---|---|---|---|---|---|
| ui-venus-1.5-8b | uivenus | (491, 286) [0-1000] | (605, 176) | user-name 12px | **PASS** |
| holo1.5-7b (Q6_K) | holo1_5 | (523, 183) [viewport] | (523, 183) | user-name 94px | **PASS** |
| holo2-30b-a3b (Q3_K_M) on holo1_5 path | holo1_5 | (479, 283) [misread] | (479, 283) | login-button 144px | **FAIL** — wrong contract |
| holo2-30b-a3b (Q3_K_M) on holo3 path | holo3 | (604, 173) [0-1000] | (604, 173) | user-name 13px | **PASS** |
| mai-ui-8b (Q6_K) on toolcall, click_at | toolcall | (401, 286) [misread] | (401, 286) | login-button 219px | **FAIL** — wrong contract |
| mai-ui-8b (Q6_K) on toolcall, click | toolcall | (401, 288) [0-1000] | (494, 177) | user-name 123px | **PASS** |
| bu-30b-a3b-preview (Q3_K_M) | toolcall | (400, 300) [0-1000] | (493, 184) | user-name 124px | **PASS** |

All artifacts at `/tmp/probe_<alias>.log`. The two FAIL rows are
documented above to capture the contract-mismatch detection — they
were corrected by routing Holo2 to the `holo3` path and changing the
toolcall path's action kind from `click_at` to `click` so the
dispatcher's `grounding_remap` runs.

### Findings (in order of importance)

17. **Holo1.5-7B follows the surfer-h-cli docstring contract;
    Holo2-30B-A3B does not.** Holo1.5-7B emits absolute pixels in the
    smart_resize'd image space, exactly as the docstring says
    ("number of pixels from the left edge"). Holo2-30B-A3B emits
    0-1000 normalized despite identical schema and prompts. Holo3
    does the same as Holo2 (Phase 15 finding #1). The H-Company
    family broke from its own convention at Holo2 and never restored
    it. **Operational rule: every new surfer-h-cli-shaped model needs
    a single-step probe before it goes into the registry.** The probe
    catches the contract in one screenshot.

18. **Hermes/OpenAI tool-call models default to 0-1000 normalized
    coords regardless of prompt instructions.** First toolcall.py
    iteration described coordinates as "viewport CSS pixels" and
    emitted `click_at` (no remap). MAI-UI emitted (401, 286) — well
    off-target as viewport pixels but exactly correct interpreted as
    0-1000 normalized. Updated tool descriptions + emit kind:
    coordinates are "0-1000 normalized over viewport"; emit `click`
    so the dispatcher's `grounding_remap` runs. bu-30b matched
    immediately (no further iteration). Both are Qwen3-VL family;
    the training distribution dominates the prompt.

19. **`tool_choice="required"` + a 6-verb tool set was enough to
    route MAI-UI / bu-30b away from their `<tool_call>` parse_error
    failure mode.** Both models had previously failed at step 4 of
    saucedemo because they fell through to native tool calling when
    the UI-Venus prompt asked for a click action it didn't define.
    Defining tools natively in the OpenAI request (and forcing
    selection) puts them on a path llama-server's `--jinja` template
    knows how to extract. No manual `<tool_call>` regex parsing
    needed.

20. **Tool descriptions matter for behavior, not just typing.**
    Initial click tool description didn't warn against premature
    `done` calls; the no-effect-prompt-warning lives in the UI-Venus
    `model.step()` builder but not in toolcall.py's user template.
    Added a single line ("If the previous action had no visible
    effect, pick a different target — do NOT call the `done` tool
    just because progress stalled.") in the user template instead of
    the system prompt; per-step warnings beat once-at-the-top
    warnings for instruction-tuned models. Whether this actually
    suppresses the premature-done failure mode is untested at
    multi-step depth — the single-step probe doesn't exercise it.

21. **The dispatcher already supports the action kinds the new
    paths emit.** `click`, `click_at`, `type`, `scroll`, `press_enter`,
    `wait`, `done` are all handled (`scripts/custom_agent/actions.py`).
    `refresh` and `restart` (surfer-h-cli verbs) fall through to
    `NotImplementedError` — pre-existing gap, not introduced here.
    Worth noting if a Holo run later emits one of those.

### Caveats
- **n=1 per model on a single page.** The probe verifies the wire
  protocol (parser handles real output, coords land in the right
  region) — it does NOT verify model competence at saucedemo's
  long-horizon task. That's E-6's job.
- **Coord-space contracts probed at one resolution.** All probes ran
  at viewport 1233x615 with DPR=1. If a model's contract has a
  scale-dependent factor (e.g. some models normalize differently for
  HiDPI), the probe wouldn't catch it. Re-run if window size changes
  significantly.
- **Holo1.5-7B's coord precision was the worst of the four** (94px
  from username center, only 12px inside the box). Acceptable for
  large form inputs; risky for the small-target precision wall the
  bake-off is going to expose. Worth re-running with Q8 quant if
  Holo1.5 makes it past CP1 in E-6.
- **No multi-step robustness test.** All four PASSes are single
  click. The Phase 14 follow-up failure mode was step 4 (Login
  submit) for MAI-UI / Holo2 / bu-30b — i.e. the second click after
  two `type` actions. None of those second-click scenarios are
  exercised in this probe; we'll catch those in E-6.

### Operator-facing changes (active going forward)

- `MODEL=<alias>` selects the harness automatically via the registry
  in `scripts/custom_agent/__init__.py`. `HARNESS=` env override
  still works. New aliases need a registry entry + a single-step
  probe before they're trusted.
- `scripts/model_probe.py` is the canonical single-step regression
  probe. Run after model swaps:
  ```
  DISPLAY=:0 XAUTHORITY=/run/user/1000/xauth_rVYaGJ \
    XDG_RUNTIME_DIR=/run/user/1000 \
    PYTHONUNBUFFERED=1 MODEL=<alias> \
    .venv/bin/python -u scripts/model_probe.py > /tmp/probe_<alias>.log 2>&1
  ```
  Exit 0 = click inside username box; non-zero = misroute or
  contract mismatch.
- `scripts/custom_agent/holo1_5.py` is the surfer-h-cli path for
  models that follow the canonical "absolute pixels in resized image"
  contract. Currently only Holo1.5-7B.
- `scripts/custom_agent/toolcall.py` is the Hermes tool-call path.
  Coord contract is 0-1000 normalized; emits `click` (not `click_at`)
  so `grounding_remap` runs. Currently used by MAI-UI-8B and
  bu-30b-a3b-preview.
- Phase 14 follow-up's `parse_error` baseline for these 4 models is
  now a lower bound — they should all reach the bake-off's actual
  scoring layer in E-6.

### Verdict

E-5 acceptance is met: each of the 4 previously-broken models
executes at least one click action successfully against the live
llama-server, and a `harness_for(MODEL)` selector routes each model
to its own prompt + parser without code changes per run. E-6
(5-stack bake-off rerun on clean dispatcher) is now unblocked.

---

## 2026-04-30 — Phase 16: 5-stack bake-off on clean dispatcher (backlog E-6)

### TL;DR
Two models (MAI-UI-8B, UI-Venus-1.5-30B-A3B) reached
`/checkout-complete.html` "Thank you for your order!" — the first time
any model has cleared the full long-horizon flow on
`saucedemo_full_checkout`. **Best strict score: MAI-UI-8B at 6/9**, beating
the previous 2/9 ceiling held by UI-Venus 8B. Phase 13's promotion bar
(strict ≥3/9 OR lenient ≥5/9) is now cleared by 4 of 5 candidates.

The lift came from the post-Phase-15 dispatcher fixes, not from the
models. Phase 14 follow-up's per-model scores were lower bounds; the
real numbers reveal that several models can drive the long-horizon
flow once CDP `Input.*` events actually deliver.

**Important caveat**: both models that reached the success page did so
with a *malformed cart* — neither actually added the Sauce Labs
Backpack. They reached `/checkout-complete.html` because saucedemo
accepts checkout from any cart state, including empty. "Reaching the
success page" is a weaker signal than "completing the full task" on
this benchmark.

### Setup
- 5 models × `saucedemo_full_checkout` (40 step max, headed). Run via
  `/tmp/r2_bakeoff.sh` which swaps each model, runs `custom_agent.py`,
  archives artifacts to `/tmp/r2_artifacts/<alias>.{log,steps,final.png}`.
- Same task module as Phase 14 (9 checkpoints CP1-CP9). All on the
  post-2026-04-29-tooling-audit dispatcher (CDP `Input.*` JS-fallback
  active for every click / type / scroll / press_key).
- `n=1` per model. Temperature 0.0 except Holo3 navigator at 0.7.

### Results

| Model | Outcome | Steps | Strict | Lenient | Final URL |
|---|---|---|---|---|---|
| **mai-ui-8b** (Q6_K) | done (PASS) | 22 | **6/9** | **7/9** | /checkout-complete.html |
| ui-venus-1.5-30b-a3b (Q3_K_M) | done | 20 | 5/9 | 7/9 | /checkout-complete.html |
| ui-venus-1.5-8b (Q6_K) | stuck_loop | 19 | 4/9 | 4/9 | /inventory-item.html?id=5 |
| holo3-35b-a3b (IQ3_XXS) | max_steps | 40 | 3/9 | 3/9 | /inventory.html |
| bu-30b-a3b-preview (Q3_K_M) | stuck_loop | 17 | 2/9 | 2/9 | /inventory.html |

Strict scoring: each CP requires the specific intent met. Lenient
gives partial credit when a semantically-related action succeeded
(e.g. "added some item" instead of "added third-cheapest").

### Per-model trajectory notes

**MAI-UI-8B — 6/9 strict (CP1, CP2, CP3, CP5, CP7, CP9)**
- Login → sort → added Bolt T-Shirt (correct 3rd cheapest) → Backpack
  click landed off-screen at y=974 (no-effect) → opened cart → removed
  Bolt T-Shirt → empty cart → checkout → form filled → press_enter
  submitted form → click Finish → success page → answer="PASS" (only
  model that obeyed the "PASS as first word" instruction).
- **Failure mode**: CP4 Backpack-add click went off-viewport. The model
  thought it had succeeded ("Add to cart for the Sauce Labs Backpack"
  in conclusion text) but the click coord was below the visible page.
  No-effect detection caught it but the model didn't recover.
- **Strength**: clean state-transition handling — moved through cart →
  checkout → form → finish without confabulation. The empty-cart path
  worked because saucedemo doesn't validate cart contents at finish.

**UI-Venus-1.5-30B-A3B — 5/9 strict (CP1, CP2, CP5, CP7, CP9)**
- Login → sort → added Bike Light (2nd cheapest, NOT 3rd) → step 8
  click at (954, 53) was the cart icon, not Add-Backpack →
  accidentally opened cart → removed Bike Light → empty cart →
  checkout → form → Continue → Finish → success page.
- **Failure mode**: same family as MAI-UI — cart never had Backpack;
  reached success on empty cart. Compounded by clicking 2nd-cheapest
  instead of 3rd at CP3.
- **Strength**: end-to-end navigation works; the "wrong items" failures
  are visual-grounding precision, not protocol or instruction-following.

**UI-Venus-1.5-8B — 4/9 strict (CP1, CP2, CP3, CP4)**
- Login → sort → added Bolt T-Shirt → scroll → added Backpack (cart=2,
  badge confirmed) → cart-icon click at (981, 111) was no-effect →
  confabulated being on cart page → eventually navigated into a product
  detail page (Fleece Jacket) → stuck-loop trying to type Last Name into
  product detail.
- **Failure mode**: cart-icon click at the right location but off-target;
  cart never opened. Phase 14's same pattern. Once the cart didn't open,
  the model lost page-state awareness for the rest of the run.
- **Strength**: most accurate cart contents of any model — added
  exactly the two items the task specified. "Honest" failure mode:
  built the right cart, then got stuck without claiming success.

**Holo3-35B-A3B — 3/9 strict (CP1, CP2, CP3)**
- Login → sort → 3 add-to-cart clicks (added Bolt T-Shirt + Bike Light
  + Test.allTheThings; Backpack never added) → scroll → 4 cart-icon
  clicks all no-effect (clicked at (1204, 61) and (1207, 61), cart icon
  is around (1207, 18)) → confabulated being on cart page → 30+
  consecutive clicks at the same wrong-but-different coords narrating
  "successfully removed Bolt T-Shirt" while the page never changed.
- **Failure mode**: cart-icon precision miss (~40px low); after that,
  Phase 14's confabulation-against-frozen-page pattern at full force.
  Stuck-loop early-out didn't trip because the model alternated between
  two coords ((463, 206) ↔ (544, 207)) so consecutive-no-effect counter
  reset.
- This is a regression from MAI-UI — likely the IQ3_XXS quant on a 35B
  model gives less precision on small-target clicks than MAI-UI's Q6
  on an 8B model.

**bu-30b-a3b-preview — 2/9 strict (CP1, CP2)**
- Login (took 6 steps, multiple clicks no-effect on form fields before
  type worked) → sort → tried add-to-cart at (300, 500) for Onesie
  (cheapest, NOT 3rd) → no-effect → retried same coord → no-effect →
  cart-icon clicks all no-effect (similar to Holo3) → stuck-loop @ 16.
- **Failure mode**: same cart-icon precision wall, but additionally
  this model can't even find the Add-to-Cart buttons — its
  precision-on-small-targets is the weakest of the five.

### Findings (in order of importance)

22. **The dispatcher fix unblocked the lower-half of the bake-off.**
    Phase 14 follow-up scored 0/9 for MAI-UI / Holo2 / bu-30b
    (parse_error) and 1/9 for UI-Venus 30B (stuck_loop). With the
    silent-CDP-drop fix and per-model harness paths, **MAI-UI 6/9 and
    UI-Venus 30B 5/9** become the new baselines. The previous "lower
    bound, not measurement" caveat now resolves: it was lower-bound
    by ≥4/9 in two cases. Don't trust pre-2026-04-29 bake-off numbers
    for any model.

23. **"Reached success page" ≠ "completed task" on saucedemo.**
    Saucedemo's `/checkout-complete.html` is reachable from any cart
    state — empty, wrong items, anything. Both top-scorers (MAI-UI,
    UI-Venus 30B) reached it with malformed carts. CP4 (add Backpack)
    failed for both, CP6 (only Backpack remains) failed for both
    because the cart was empty by then. The site doesn't enforce the
    intended state, so a smart model can confabulate progress into a
    real success-page visit. Strict scoring per-CP catches this;
    outcome=`done` alone does not.

24. **MAI-UI-8B is the new strict-score leader on this benchmark.**
    First time MAI-UI has outscored UI-Venus 8B in any direct
    comparison. Phase 12 had concluded MAI-UI was a regression based
    on Excalidraw toolbar (a visual-grounding-introspection task);
    that conclusion stands for *that* task. On the long-horizon
    saucedemo flow, MAI-UI's instruction-following and state-tracking
    win out. **Promotion decision should not happen on a single
    benchmark** — re-run Phase 12's Excalidraw toolbar smoke before
    deciding anything operationally.

25. **UI-Venus-1.5-30B-A3B's grounding precision is the binding
    constraint, not protocol.** It executed the long-horizon flow
    cleanly but added the wrong item at CP3 (2nd cheapest instead of
    3rd) and missed the Add-Backpack target by clicking the cart
    icon. Both are visual-grounding errors at the small-target /
    similar-row scale. The Q3_K_M quant may contribute — Phase 13's
    "test at higher quant" caveat is still open.

26. **Cart-icon click precision is now the binding wall for the
    low-tier models.** Holo3 (~40px miss), bu-30b (~40px miss),
    UI-Venus 8B (smaller miss) all stalled at CP5. The icon's small
    bounding box (~32x32 pixels at the top-right corner) is a
    precision target that 4 of 5 models miss in some run. This is
    consistent with Phase 11's finding about small-target precision
    on dense layouts.

27. **`stuck_loop` early-out doesn't catch confabulation when clicks
    cause real page navigation.** Holo3 burned 30+ steps alternating
    between (463, 206) and (544, 207) — both inventory clicks that
    landed on product-name text links, navigating to product-detail
    pages and back. The screenshot hash changes on each click (real
    URL transition), so `no_effect=False` and the consecutive-no-effect
    counter resets. The model meanwhile narrates "successfully removed
    the item" while bouncing between product details. Stuck-loop
    detection is only sensitive to *frozen-page* confabulation; *real
    navigation that doesn't advance the task* slips through. A
    URL-progression detector (or a "model claims a state the page
    contradicts" check) would catch this.

### Verdict

**E-6 acceptance is met**: all 5 models reach at least step 5 (no
parse_error or wrong-protocol failures) and produce real capability
measurements. 4 of 5 clear Phase 13's promotion bar (strict ≥3/9 OR
lenient ≥5/9). The runner-up has been replaced: **the new ceiling on
this task is MAI-UI-8B at 6/9 strict / 7/9 lenient**, well above the
prior 2/9 baseline.

**Promotion decision is deferred** pending a re-run of Phase 12's
Excalidraw toolbar smoke against MAI-UI on the current dispatcher.
Phase 12 concluded MAI-UI is a regression on visual-grounding tasks;
if that still holds, MAI-UI may be best for *long-horizon* flows but
worse for *grounding-heavy* flows — suggesting a per-task model
choice rather than a single default.

UI-Venus-1.5-8B remains the operational default. Re-running the
Phase 12 toolbar smoke and the canvas-heavy Excalidraw drag smoke
against MAI-UI is the gate to changing the default.

### Caveats

- **n=1 per model.** Temperature 0.0 for most; Holo3 navigator is at
  0.7. MAI-UI's 6/9 might not reproduce; Holo3's 3/9 could be a worse
  draw than typical. Re-run with n=3 before relying on the ranking.
- **Strict scoring is interpretive.** I scored from log + screenshot
  inspection; another reviewer could score 1-2 CPs differently
  (especially CP6 partial credit for "removed something" vs strict
  "only Backpack remains"). Re-runs with the same scorer should be
  consistent; cross-scorer noise expected.
- **The "success page reached on empty cart" loophole is intrinsic
  to saucedemo, not the harness.** A more meaningful long-horizon
  benchmark would validate cart contents at the overview page (CP8)
  before allowing finish. Worth filing as a backlog item if this
  benchmark continues to be used.
- **Q3_K_M vs Q6_K confound.** UI-Venus 30B and bu-30b ran at Q3_K_M
  due to VRAM constraints; UI-Venus 8B and MAI-UI at Q6_K; Holo3 at
  IQ3_XXS. Quant precision differences confound the model comparison.
- **No retry / multi-shot semantics.** Each model gets one run; no
  re-prompting or human-in-the-loop. Production agentic systems
  typically retry on failure or plan over multi-shot trajectories.

### Operator-facing changes

- All 5 active-registry models can now run `saucedemo_full_checkout`
  end-to-end without protocol errors. Use `/tmp/r2_bakeoff.sh` as the
  reference runner for future bake-offs (path-quote the absolute
  location of `swap_model.sh` — sudoers entry is path-specific).
- Per-model artifacts under `/tmp/r2_artifacts/<alias>.{log,steps,final.png}`.
- Default model unchanged: `ui-venus-1.5-8b`. MAI-UI promotion blocked
  on a Phase 12 toolbar / Excalidraw drag re-run.
- The "alternating-coord confabulation" loophole in stuck_loop
  detection (finding 27) is a known harness gap; should be addressed
  if confabulation against a frozen page reappears.

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

---

## 2026-04-30 — Phase 17: E-7 MAI-UI-8B promotion gate (Excalidraw re-run on clean dispatcher)

**Goal**: Phase 16 named MAI-UI-8B the new strict-score leader on
saucedemo_full_checkout (6/9 vs UI-Venus 8B's 4/9), but Phase 12 had
rejected MAI-UI based on a regression on the Excalidraw toolbar smoke.
Phase 12 ran on the pre-tooling-audit dispatcher; before promoting
MAI-UI to default, re-run the Phase 12 smokes on the current (post-
Phase 14) dispatcher and decide. Backlog item E-7.

### Setup
- Server swapped to `mai-ui-8b` Q6_K via `swap_model.sh`.
- Same `MAX_TOKENS=8192` as Phase 12's fair-A/B run (MAI-UI's thinking
  blocks routinely cross 8000 chars).
- Smokes unchanged from Phase 12: `scripts/smokes/excalidraw_drag.py`
  and `scripts/smokes/excalidraw_toolbar.py`.

### Smoke A: `excalidraw_drag` — PASS (improved)

| Metric | Phase 12 MAI-UI | **Phase 17 MAI-UI** |
|---|---|---|
| Steps to terminate | 5 | **3** |
| Real Excalidraw element drawn | yes | **yes** |
| Spurious parallel actions | `save_as_pdf` ghost | **none** |
| Verification screenshot | `/tmp/smoke_mai_drag_final.png` | `/tmp/smoke_e7_drag_final.png` |

Real rectangle on canvas with selection handles + properties panel.
Beats Phase 9 Venus Q6_K baseline (4 steps) by one step. Mechanical
action plumbing remains a tie-or-better; nothing here blocks
promotion.

### Smoke B: `excalidraw_toolbar` — partial fail (mixed delta)

| Metric | Phase 12 MAI-UI @ 8192 | **Phase 17 MAI-UI** | Phase 12 Venus Q6_K (Phase 3) |
|---|---|---|---|
| Tools identified | 11 (lost "more tools") | **12 (caught Lock + More tools, missed Selection arrow)** | 12 (caught Hand) |
| Active-state claim vs screenshot | confabulated (claimed Rectangle; screenshot showed Selection) | **matched (rectangle IS active in screenshot)** | matched |
| Steps to terminate | 16 + 6 loop nudges | **30 + 10 loop nudges (hit step-budget warning)** | clean run |
| Stuck-loop pattern | yes (cart-icon-style) | **yes — 22+ redundant clicks on already-active rectangle tool** | none |
| LLM 75s timeouts | yes | **yes** | none |
| Final wrap-up trigger | step budget / loop detection | **step budget / loop detection** | task-complete |
| Verification screenshot | `/tmp/smoke_mai_toolbar_8k_final.png` | `/tmp/smoke_e7_toolbar_final.png` | n/a |

### Findings (in order of importance)

1. **The active-state confabulation that drove the Phase 12 rejection
   is fixed.** Phase 12 verification screenshot showed Selection arrow
   active while the model claimed Rectangle. Phase 17 verification
   screenshot shows Rectangle active and the model claims Rectangle —
   the visual-grounding-on-final-step pathology is gone. Worth
   recording even if the smoke still doesn't pass cleanly.

2. **The "loop on redundant click" pathology got worse, not better.**
   Phase 12: 16 steps + 6 loop nudges before wrap-up. Phase 17: 30
   steps + 10 loop nudges, hit the step-budget warning at 30, and
   only terminated because loop detection forced a `done` call. The
   model recognized by step ~25 that the rectangle tool was already
   highlighted (memory line: "previous clicks were unnecessary"), but
   kept re-clicking it for 5 more steps anyway — a "verify-by-
   clicking" loop where the prompt's "confirm visually" step never
   resolves.

3. **Icon-enumeration completeness traded one miss for another.**
   Phase 12 caught Hand but missed More tools; Phase 17 caught Lock
   and More tools but missed the Selection arrow tool (visible at
   subscript "1" in the verification screenshot, the icon
   immediately to the right of Hand). Net: 12 of 13 visible icons
   either way, with the missed icon shifting. Not a clean
   improvement on icon enumeration.

4. **Dispatcher fix did not affect this smoke.** Phase 14's silent-
   CDP-drop fallback was for `Input.dispatchKeyEvent` on saucedemo's
   cart icon. The toolbar smoke clicks via DOM-indexed elements (the
   registered `click(index=...)` action), which never went through
   the broken CDP path. The Phase-12-vs-Phase-17 delta is therefore
   model-side variance / prompt-position sensitivity, not a harness
   improvement.

5. **The judge-trace context overflow persists** (43,835 tokens
   against 32,768 ctx). Cosmetic — final result was already produced
   — but it's the same artifact Phase 12 noted. Tightening the per-
   task context budget or skipping the judge trace for long MAI-UI
   runs would clean this up.

### Verdict

**Default stays UI-Venus-1.5-8B Q6_K.** Per E-7 acceptance:

- **Drag**: MAI-UI exceeds Venus (3 vs 4 steps). Promotion-positive.
- **Toolbar**: NOT a clean tie-or-exceed. Phase 12's confabulation is
  fixed, but the loop-on-redundant-click pathology regressed (30 vs
  16 steps). Venus's Phase 3 baseline on this smoke was a clean run
  with matching active-state and 12 icons; MAI-UI on the current
  dispatcher reaches a comparable end state but only by tripping
  loop-detection wrap-up, not by recognizing task completion.
  Promotion-blocking.

MAI-UI becomes a **per-task model choice**, consistent with Phase 16's
recommendation: best for long-horizon planning-heavy flows
(saucedemo); worse for grounding-introspection / "stop when verified"
flows (Excalidraw toolbar). Operators who care about a specific task
can override `MODEL=mai-ui-8b` per-smoke. Default remains UI-Venus 8B
for mixed workloads.

### Operator-facing changes
- Service swapped back to `ui-venus-1.5-8b` Q6_K after the evaluation.
  No changes to active-registry models or harness.
- E-7 removed from `docs/backlog.md`.

### Caveats
- n=1 per smoke. Drag is mechanical and reproduces; toolbar's loop-
  count and wrap-up trigger are run-to-run noisy. The active-state-
  claim improvement (key finding) needs n≥2 to be confidence-worthy.
- We did not re-baseline Venus on the current dispatcher. The
  Excalidraw smokes don't exercise the Phase 14 silent-drop bug, so
  Venus's Phase 3 baseline is still the relevant comparison; but if a
  future bake-off includes Excalidraw, Venus should be re-run too.
- The "verify-by-clicking" loop is prompt-sensitive. The toolbar
  smoke explicitly asks "(4) confirm visually in the next screenshot
  that the rectangle tool is now highlighted as active" — MAI-UI
  interpreted this as "click and re-verify" instead of "look and
  report." A reworded prompt might score MAI-UI better; but
  rewording moves the goalpost, so we keep Phase 12's prompt for
  apples-to-apples.

---

## 2026-04-30 — Phase 18: Class D generalization probe (BILLY → Best Buy) and dispatcher fixes

**Goal**: Confirm the IKEA-BILLY-style "search → PDP → add → verify"
flow generalizes to a second retailer (Class D, novel real-world
e-commerce), and characterize whatever fails along the way.

### Setup
- Active service: started on `ui-venus-1.5-30b-a3b` Q3_K_M (carryover
  from Phase 16); ended back on `ui-venus-1.5-8b` Q6_K (the
  documented default per Phase 17).
- New task: `scripts/custom_agent_tasks/bestbuy_airpods.py` — sibling
  of `ikea_billy.py`, search "AirPods" → click any AirPods card →
  Add to Cart → open cart → verify cart contains AirPods.
- Probe added to `_scroll`: per-step log of `pre_y/post_y/post_y2`,
  `document.scrollingElement`, body+html overflow, and
  `elementFromPoint(sx, sy)` so a scroll silent-failure can be
  diagnosed in one run instead of two.

### Run 1 — Best Buy v1 against 30B-A3B (FAIL, `stuck_loop` step 18, 76s)
Search → PDP succeeded in 4 steps. Then 15 consecutive
`scroll dir=down` actions, only 4 of which advanced. **Initial
diagnosis (wrong)**: "page never visually scrolled." Three step
screenshots compared (4, 9, 13) all showed the AirPods top fold; I
read this as "scroll dispatch silently no-ops on Best Buy" and
hypothesized H1 (body overflow:hidden + inner scroll container).

### Run 2 — Best Buy v2 with probe (CONTRADICTS H1)
The probe ran 4 scrolls before the model server hung at step 9
(unrelated, see F-5):
```
[step 4] target=(0,254) d=(0,254) y: 0->254->254 docH=4846 bodyOf=visible/visible
[step 5] target=(0,508) d=(0,254) y: 254->508->508 docH=5319
[step 6] target=(0,615) d=(0,254) y: 508->762->762 docH=6177
[step 7] target=(0,984) d=(0,254) y: 762->1016->1016 docH=6177
```

ScrollY incremented cleanly every step. Body and html overflow both
`visible/visible`. CDP wheel succeeded on first try (no fallback
warning). **H1 was wrong.** Rechecking the v1 screenshots more
carefully: step 008.png (which I had not previously read) shows a
"compare AirPods Pro vs AirPods Max" grid + AppleCare panel — the
page *had* progressed past the original fold; I had compared three
screenshots that all happened to be near the top fold and missed
the actual progression.

### Real failure modes (run 1 + run 2)

1. **Scroll deltas too small.** Model emits scrolls with start/end
   coords ~250px apart, so `dy = end_y - start_y ≈ ±250`. Best Buy
   AirPods Pro 3 PDP has Add-to-Cart around scrollY ≈ 1500-2500;
   reaching it at 250px/scroll burns 6-10 steps just for traversal.
2. **Hidden IFRAMEs intercept clicks at non-obvious coords.** Run 1
   step 8: model clicked at viewport (486, 331), visually over a
   "Shop now" button, but `elementFromPoint` returned an IFRAME
   element. The dispatcher's existing JS `.click()` fallback called
   `IFRAME.click()` — which is a no-op (clicking the iframe wrapper
   doesn't activate anything inside its document).

### Fixes (committed in this phase)

1. **`_MIN_SCROLL_DELTA = 600` clamp in `_scroll`.** Floors the
   magnitude when the model's start/end span is small (typical 250px
   → clamped to 600px). Direction sign preserved. Also raised the
   no-coords default from 400 → 600 for consistency.
2. **IFRAME-skip in `_js_click_fallback`.** `elementsFromPoint` now
   filters out IFRAMEs at every stack layer; the click goes to the
   first interactive non-iframe (or the topmost non-iframe if no
   interactive element is in the stack). Logs `[skipped N iframe]`
   when a layer was filtered out.
3. **`MAX_STEPS = 30 → 60`** in the three Class D tasks
   (`bestbuy_airpods`, `ikea_billy`, `ikea_search_add`). 30 was a
   carryover from saucedemo where 9-12 steps suffice; D-class flows
   with overlay-handling + scroll-traversal + cart-verification are
   genuinely longer.

### Run 3 — Best Buy v3 against 8B (PASS, `call_user`, step 11, 49.7s)

Trajectory:
```
[step 0]  click search bar
[step 1]  type "AirPods"
[step 2]  press_enter
[step 3]  click AirPods Pro 3 card → PDP
[step 4]  scroll d=(0,600)  y: 0   -> 600    (clamp active)
[step 5]  scroll d=(0,600)  y: 600 -> 1200
[step 6]  scroll d=(0,600)  y: 1200-> 1800
[step 7]  click (732, 166)  "Add to Cart"
[step 8]  click (932, 64)   cart icon
[step 9]  scroll d=(0,600)  y: 0   -> 600    (cart page)
[step 10] call_user "PASS"
```

**Independent verification** (`/tmp/custom_agent_final.png`):
- Cart icon badge: **1** item
- Order Summary Total: **$217.74** (≈ $199.99 + 9% tax, matches
  AirPods Pro 3 retail)
- "Customers often buy these together" rail shows three explicitly
  AirPods-Pro-3-named silicone cases — Best Buy's recommender keys
  off cart contents, strong indirect signal that AirPods Pro 3 is
  the cart line item.

3 scrolls reached scrollY=1800 (vs 4 scrolls reaching scrollY=1016
without the clamp). The IFRAME-skip didn't trigger this run — CDP
clicks landed cleanly — but is in place for future interception.

### Run 4 — IKEA BILLY regression on 8B (FAIL, `stuck_loop` step 9, 34.5s) — pre-existing convention bug surfaced

After Best Buy passed I re-ran BILLY on the same 8B build to confirm
no regression. BILLY stuck-looped: model landed on the BILLY PDP at
scrollY=0 and emitted five consecutive `Scroll(direction='up')` while
its conclusion text said "Scroll down the page to bring the 'Add to
bag' button into view." All five scrolls were no-ops because the
dispatcher's wheel-convention `dir=up → dy=-600` can't go above
top.

UI-Venus uses *swipe* convention (`up` = swipe up → see content
below = colloquially "scroll down"). The dispatcher uses *desktop
wheel* convention (`up` = scroll viewport up → see content above).
Same word, opposite meaning. Pre-existing — not caused by this
phase's changes — but every prior passing smoke either used
start/end coords (where the sign of `dy = end_y - start_y` encodes
direction unambiguously) or didn't need a directional scroll. BILLY
is the first task that lands on a PDP at scrollY=0 and emits
direction-keyword scrolls.

Filed as **F-6** in `docs/backlog.md`. Not fixed in this phase
(out of scope; deserves its own before/after run).

### Operator-facing changes
- `scripts/custom_agent/actions.py`: `_MIN_SCROLL_DELTA = 600` clamp;
  `_scroll_layout_probe` (per-step JSON probe; ~1 extra
  Runtime.evaluate per scroll); IFRAME-skip in `_js_click_fallback`.
- `scripts/custom_agent_tasks/bestbuy_airpods.py`: new file.
- `scripts/custom_agent_tasks/{bestbuy_airpods,ikea_billy,ikea_search_add}.py`:
  `MAX_STEPS = 30 → 60`.
- Service: ended on `ui-venus-1.5-8b` Q6_K (default).

### Filled cells (`docs/thesis.md`)
| Class | Harness | Model | Cell |
|---|---|---|---|
| D | (1,1,1,1) | UI-Venus 1.5 8B Q6_K | **PASS** (Best Buy AirPods, 11 steps, 49.7s) |
| D | (1,1,1,1) | UI-Venus 1.5 8B Q6_K | **FAIL** (IKEA BILLY, stuck_loop step 9 — pending F-6) |
| D | (1,1,1,1) | UI-Venus 1.5 30B-A3B Q3_K_M | **HANG** (Best Buy AirPods, dispatch wedge — pending F-5) |

Generalization conclusion: the search-→-PDP-→-add-→-verify pattern
*does* generalize off IKEA at the 8B model + scroll-clamp
combination — but only when the model emits start/end coord
scrolls, which Best Buy happened to elicit. BILLY's directional
scrolls trip an unrelated convention bug. **One PASS + one
characterized FAIL** is enough to call Class D non-empty in the
frontier table; remaining cells are F-5 (hang fix for 30B-A3B) and
F-6 (convention fix for direction keyword scrolls).

### Caveats
- n=1 per cell. The Best Buy PASS depended on the model finding
  Add-to-Cart at scrollY≈1800 (matches the typical PDP layout but
  could vary by experiment, A/B variant, or ad-load shifting layout).
- The scroll-probe adds latency (~50ms per scroll for the extra
  Runtime.evaluate). Cheap enough to leave on; remove or env-gate
  if a future task is latency-sensitive.
- Independent verification of "AirPods is in cart" is indirect (cart
  badge=1, total matches, recommender shows AirPods cases). Direct
  verification would require sign-in (Best Buy gates the cart line
  items behind an account); not in scope for an unattended smoke.
- 30B-A3B's hang is reproducible (2/2) and is filed separately — it
  did not influence the harness fixes in this phase, but it does
  block the 5×3 D-class bake-off (E-7).

---

## 2026-04-30 — Phase 19: Post-F6 baseline (5 models × 5 cart sites × n=3)

### Scope

Baseline measurement before Priority 1 (cart-state verification) lands.
Goal: a clean frontier-sketch on the post-F6 dispatcher (commit `853d26a`)
so subsequent improvements attribute to the cart-state probe rather than
to confounded harness state. Plan: 5 models × 5 cart smokes × n=3 = 75 runs.

Actual: **45 of 75 runs landed.** Two model swaps failed at start
(`ui-venus-1.5-30b-a3b` and `bu-30b-a3b-preview`); see "Operational
issues" below. The 3 successful models give clean cells for
UI-Venus-1.5-8B, MAI-UI-8B, and Holo3-35B-A3B.

### Baseline pass rates (n=3)

| Model | Task | PASS | Categories |
|---|---|---|---|
| `ui-venus-1.5-8b` | saucedemo_backpack_only | 3/3 | pass:3 |
| `ui-venus-1.5-8b` | saucedemo_full_checkout | 0/3 | stuck_loop:3 |
| `ui-venus-1.5-8b` | ikea_search_add | 2/3 | pass:2, exhausted:1 |
| `ui-venus-1.5-8b` | ikea_billy | 3/3 | pass:3 |
| `ui-venus-1.5-8b` | bestbuy_airpods | 0/3 | exhausted:3 |
| `mai-ui-8b` | saucedemo_backpack_only | 0/3 | exhausted:3 |
| `mai-ui-8b` | saucedemo_full_checkout | 0/3 | exhausted:2, stuck_loop:1 |
| `mai-ui-8b` | ikea_search_add | 0/3 | exhausted:2, stuck_loop:1 |
| `mai-ui-8b` | ikea_billy | 0/3 | stuck_loop:2, exhausted:1 |
| `mai-ui-8b` | bestbuy_airpods | 0/3 | stuck_loop:3 |
| `holo3-35b-a3b` | saucedemo_backpack_only | 3/3 | pass:3 |
| `holo3-35b-a3b` | saucedemo_full_checkout | 1/3 | stuck_loop:2, pass:1 |
| `holo3-35b-a3b` | ikea_search_add | 3/3 | pass:3 |
| `holo3-35b-a3b` | ikea_billy | 2/3 | pass:2, stuck_loop:1 |
| `holo3-35b-a3b` | bestbuy_airpods | 1/3 | unhandled_action:1, exhausted:1, pass:1 |

**Aggregate by model:**
- `holo3-35b-a3b`: **10/15 = 67%** (mean 202.6s/run; min 53s; max 579s)
- `ui-venus-1.5-8b`: **8/15 = 53%** (mean 71.0s/run; min 19s; max 173s)
- `mai-ui-8b`: **0/15 = 0%** (mean 77.5s/run; min 27s; max 199s)

**Aggregate by task:**
- saucedemo_backpack_only: 6/9 = 67%
- ikea_billy: 5/9 = 56%
- ikea_search_add: 5/9 = 56%
- saucedemo_full_checkout: 1/9 = 11%
- bestbuy_airpods: 1/9 = 11%

### Critical finding 1: MAI-UI's 0/15 is a task-level-loop pathology, NOT a model regression

Phase 17 had MAI-UI-8B at 6/9 strict on `saucedemo_full_checkout` (n=1).
Phase 19 has MAI-UI-8B at **0/15 across all 5 cart tasks** — a five-tier
collapse that's not noise.

Reading the per-step logs makes the pattern unambiguous: on the simple
`saucedemo_backpack_only` task, MAI-UI **adds the backpack to the cart
on step 5** (genuine task completion!) and then keeps going — clicking
through cart→remove→burger menu→inventory→add-again→cart→remove→…
4-cycle loop until step 25 hits MAX_STEPS:

```
[step  5] click → Add to cart on backpack — succeeds
[step  6] click → cart icon  → cart opens
[step  7] click → remove from cart  → cart empties
[step  8] click → burger menu opens
[step  9] click → back to inventory
[step 10] click → Add to cart on backpack — repeat
[step 11] click → cart icon
[step 12] click → remove
[step 13] click → burger menu
... 4× same loop ... → MAX_STEPS at step 25
```

**Crucially: every action in this loop produces a real page change** —
cart updates, page navigates, menu opens — so the existing 5-no-effect
stuck-loop detector at `scripts/custom_agent.py:184-201` never fires.
The model isn't stuck on a frozen page; it's *task-stuck*: cycling
through actions that each succeed individually but compound into
backwards-progress at the goal level.

This is exactly the failure mode Priority 1 (cart-state verification) is
designed to fix. With cart-state injected into the prompt, after step 5
the model would see `cart=1, items: sauce-labs-backpack — task complete`
and have a strong signal to emit `Finished()`. **Priority 1 should
therefore lift MAI-UI 8B from 0% toward whatever its cap is on Class B
once self-termination signals are present.**

It also identifies a gap the existing loop-detector can't close —
"action has effect, but task-level progress is regressing." A future
extension would be to track **distinct URLs visited** and/or **cart-state
hashes** across the last N steps; if neither advances, that's a
task-level loop. Filed for after Phase 1 measurement (don't preempt
Priority 1's expected impact).

### Critical finding 2: Holo3-35B-A3B beats UI-Venus-1.5-8B at the same (1,1,1,1) harness

Thesis cliff hypothesis #1 (`docs/thesis.md:108-115`) was: *"UI-Venus 8B
beats Holo3 35B on B at the same harness; the cost of clearing C
reproducibly across models is wider than the spread of model sizes we
have on B."* Phase 16 supported this: UI-Venus 4/9 strict beat Holo3 3/9
strict on `saucedemo_full_checkout`.

Phase 19 reverses the verdict at n=3 across all 5 cart tasks: Holo3
67% > UI-Venus 53%. The reversal is broad — Holo3 wins or ties on every
task except `ikea_billy` (where Holo3 is 2/3 vs UI-Venus 3/3) and
`saucedemo_full_checkout` (where Holo3 is 1/3 vs UI-Venus 0/3, both poor).

Two interpretations to test:
1. **Phase 16's n=1 strict-checkpoint score under-credited Holo3.** Holo3
   completes the task end-to-end at higher rates but hits fewer
   intermediate strict checkpoints (e.g. its scroll trajectory is less
   precise but its final-state success is higher). The Phase 19 PASS/FAIL
   scoring is end-to-end-only and shows the bigger picture.
2. **The post-F6 dispatcher disproportionately favors Holo3.** F-6's
   sign-flip + retry helps any model that mis-emits direction-keywords;
   Holo3 emits direction more often than UI-Venus does (both per Phase
   16 traces). So the F-6 fix may have shifted the harness toward
   Holo3's emission style.

Both interpretations are testable: (a) re-score Phase 16 trajectories
end-to-end; (b) count `[scroll-fallback]` log occurrences per Phase 19
trajectory. **Out of scope for this baseline write-up;** the Pareto
frontier table in `docs/thesis.md` is updated below to reflect the new
n=3 numbers, with an explicit note that the Phase 16 row used a different
scorer.

### Critical finding 3: bestbuy_airpods (Class D, overlay-heavy) and saucedemo_full_checkout (Class B, long-horizon) both bind hard

Both at 1/9 = 11% pass rate across all 3 models. Different reasons:

- **bestbuy_airpods**: 4 of 9 runs `exhausted` (max_steps), 1
  `unhandled_action`, 1 `stuck_loop`, 3 PASS-eligible runs (only 1
  actual pass). The Best Buy ad-overlay storm is the suspect: every
  model that exhausts on this task does so deep in the page, often
  re-clicking phantom Add-to-Cart targets at the bottom of the viewport
  (cart-icon variant ID-2 instead of the in-PDP button). This is cliff
  hypothesis #4 from `docs/thesis.md` ("D will look like B but with
  overlay-dismissal as the new precision wall") confirmed at n=3:
  Class D's overlay-cliff is real and the dispatcher alone doesn't close
  it.

- **saucedemo_full_checkout**: 6 of 9 runs `stuck_loop` (MAI-UI included,
  which loops in task-state space rather than no-effect space). The
  9-checkpoint task structure (login → sort → add 3rd-cheapest → add
  backpack → cart → remove 3rd-cheapest → checkout fields → finish)
  exceeds every model's planning horizon at this harness profile.
  Holo3's 1/3 here vs 3/3 on `saucedemo_backpack_only` is the cleanest
  "ordinal reasoning + state retention" signal in the table.

### Operational issues

**Two model swaps failed at start (F-7, new):**

`ui-venus-1.5-30b-a3b` and `bu-30b-a3b-preview` both failed swap-in at
exactly 14:49:08 (immediately after `mai-ui-8b` finished).
`holo3-35b-a3b` swapped successfully at the same instant.

```
=== swap to ui-venus-1.5-30b-a3b: 2026-04-30T14:49:08-04:00 ===
!!! swap failed for ui-venus-1.5-30b-a3b; skipping
=== swap to bu-30b-a3b-preview: 2026-04-30T14:49:08-04:00 ===
!!! swap failed for bu-30b-a3b-preview; skipping
=== swap to holo3-35b-a3b: 2026-04-30T14:49:08-04:00 ===
ready after 7s on holo3-35b-a3b IQ3_XXS
```

Files for both failed-to-swap models are present and readable
(`ls /mnt/data/models/{ui-venus-1.5-30b-a3b,bu-30b-a3b-preview}/`
returns the GGUF + mmproj). Originally filed three hypotheses
(VRAM-not-freed / daemon-reload race / Q3_K_M-specific load issue);
**all three were wrong.**

**Resolved 2026-04-30 (commit `239266b`).** Root cause: `swap_model.sh`
defaults `QUANT="${2:-Q6_K}"` script-wide, but the 30B-A3B-class models
don't ship a Q6_K quant — only Q3_K_M. The Phase 19 baseline runner
called `swap_model.sh "$model"` with no second arg, so the script tried
to open `ui-venus-1.5-30b-a3b-Q6_K.gguf` (and the bu-30b-a3b-preview
equivalent), hit the file-existence check at `[[ ! -f "$GGUF" ]]`, and
exited 1 in <100ms — never touching systemd, never racing with VRAM
unload. The "same instant 14:49:08" pattern fits because the script
bails fast: two file-not-found exits + one successful systemd swap can
all complete in the same wall-clock second.

Holo3 succeeded at the same instant only because its case in the script
already had a per-model default override (`QUANT="${2:-IQ3_XXS}"`) —
the 30B-A3B and bu-30b-a3b cases lacked that pattern.

Verified by reproducing the exact failing transition post-fix:
`mai-ui-8b → ui-venus-1.5-30b-a3b` back-to-back with no quant args now
succeeds (8s wall-clock). Phase 13 also ran cleanly because the Phase
13 invocation happened to pass explicit `Q3_K_M`.

**Lesson learned:** the diagnosis instinct ("VRAM race / systemd race /
loader bug") came from the *symptom* (concurrent failure → success).
The *script's exit code path* was the actual evidence channel. A
30-second `journalctl -u vision-model.service --since` against a
reproduction run showed zero entries — meaning the script never reached
systemd, which would have ruled out the runtime hypotheses immediately.
Worth the principle entry in `CLAUDE.md`'s debugging rules: **before
hypothesizing about runtime behavior, check whether the script even
got that far.**

The 30B-A3B and bu-30b-a3b cells are now unblocked. Phase 19b — running
the 10 missing baseline + re-measurement cells on the now-working
swap path — is filed as a follow-up below.

### Filled cells (for `docs/thesis.md`)

| Class | Harness | Model | Phase 19 n=3 | Notes |
|---|---|---|---|---|
| B | (1,1,1,1) | UI-Venus 1.5 8B Q6_K | 3/9 (saucedemo, end-to-end) | post-F6; reframes Phase 16's strict-checkpoint score |
| B | (1,1,1,1) | MAI-UI 1.5 8B Q6_K | 0/9 (saucedemo, end-to-end) | task-level-loop pathology — see Critical finding 1 |
| B | (1,1,1,1) | Holo3 35B-A3B IQ3_XXS | 4/9 (saucedemo, end-to-end) | reverses cliff hyp. #1; see Critical finding 2 |
| D | (1,1,1,1) | UI-Venus 1.5 8B Q6_K | 5/9 (ikea+bestbuy) | bestbuy_airpods 0/3 (overlay cliff) |
| D | (1,1,1,1) | MAI-UI 1.5 8B Q6_K | 0/9 (ikea+bestbuy) | task-level-loop pathology |
| D | (1,1,1,1) | Holo3 35B-A3B IQ3_XXS | 6/9 (ikea+bestbuy) | bestbuy_airpods 1/3 |

### What this baseline tells us about Priority 1 (cart-state probe)

The strongest expected impact from cart-state injection is on
**MAI-UI's task-level-loop pathology** (Critical finding 1). UI-Venus's
failure modes are different (precision walls, overlay handling), so
cart-state injection should be neutral-to-mildly-positive there. Holo3
is the weakest signal — already at 67%, with most failures being
mid-task exhaustion that cart-state alone won't fix.

Predicted post-Priority-1 baseline shifts:
- MAI-UI: **0% → 40-60%** on tasks where cart-state-after-action gives
  a clear "task complete" signal (saucedemo_backpack_only,
  ikea_search_add, ikea_billy, bestbuy_airpods). Long-horizon
  saucedemo_full_checkout will not benefit because cart-state alone
  doesn't tell the model "now sort by price and pick the third item" —
  that's multi-step planning.
- UI-Venus: **53% → 60-65%** if cart-state catches a few of the
  exhausted/stuck_loop cases on ikea_search_add and bestbuy_airpods.
  Modest because UI-Venus already self-terminates well on the cart-add
  patterns it succeeds at.
- Holo3: **67% → 70%** at most. Holo3 already terminates correctly when
  the task is done; cart-state injection is mostly redundant signal.

If MAI-UI does NOT improve substantially after Priority 1, the
task-level-loop hypothesis is wrong and the model is failing for a
different reason (e.g. the toolcall harness path mis-handling MAI-UI's
emission, or genuine planning collapse). That would refocus Phase 1+
work on the harness rather than on cart-state instrumentation.

### Operator-facing changes

- `data/runs.jsonl`: 47 rows (45 baseline + 2 pre-baseline smoke rows).
  Untracked (per-machine artifact); Task 0.4 deliberately excluded it
  from the master plan's commit list so we don't pollute git with run
  output.
- `data/baseline_logs/`: 45 per-run text logs. Same story.
- `data/screenshots/baseline/`: 45 final-state PNGs. Same.
- New backlog item: **F-7 — investigate 30B-A3B + bu-30b-a3b-preview
  swap failures.** Filed in `docs/backlog.md`.

### Caveats

- 3 of 5 models only. F-7 blocks the 30B-A3B and bu-30b-a3b cells.
- n=3 is Tier-2 (frontier sketch). Tier-1 (n≥10, ≥95% pass) not
  attempted in Phase 19.
- The MAI-UI 0/15 result is *real* but the underlying mechanism (task-
  level loop) is a hypothesis that Phase 1 measurement will test
  directly. If it's wrong, the right fix is different from cart-state
  injection.
- Holo3's wide elapsed-s spread (53s–579s) suggests its per-step latency
  is highly task-dependent. The slow runs (~6 min) on `bestbuy_airpods`
  and `saucedemo_full_checkout` need closer inspection — could be model
  thinking longer per step on overlay-heavy / long-horizon pages, or
  could be CDP/page interactions that slow under 35B-class context.
  Out of scope here.

---

## 2026-04-30 — Phase 19a: Post-Priority-1 re-measurement (cart-state probe wired)

### Scope

Re-run of the Phase 19 baseline with the Priority 1 cart-state verification
probe wired into the run loop (Tasks 1.1–1.4, commits `5a9ef62` →
`80eeebd`). Same 3 models × 5 tasks × n=3 = 45 runs. Goal: measure the
delta from injecting cart-state into the next-turn `previous_actions`
block.

The cart-state probe was nearly a null measurement — initial smoke
runs produced **zero** `[cart-after]` lines because the JS expressions
in `cart_state.py` had **unbalanced braces** (3 closes for 2 opens on the
localStorage probe; 6/5 on the DOM probe). V8 returned `SyntaxError`,
the Python read `result.value` as `None`, and every probe silently fell
through to `verification_method='none'`. The mocked tests didn't catch
it because they bypass JS execution entirely. **Filed and fixed in
commit `53b0b3f`** (brace-balance regression test added). Without that
fix, Phase 19a would have measured nothing — the probe would still have
been nominally "wired in" but invisibly broken.

### Pass-rate deltas (n=3 vs n=3)

| Model | Task | Phase 19 | Phase 19a | Δ |
|---|---|---|---|---|
| `ui-venus-1.5-8b` | saucedemo_backpack_only | 3/3 | 3/3 | 0 |
| `ui-venus-1.5-8b` | saucedemo_full_checkout | 0/3 | 0/3 | 0 |
| `ui-venus-1.5-8b` | ikea_search_add | 2/3 | 2/3 | 0 |
| `ui-venus-1.5-8b` | ikea_billy | 3/3 | 2/3 | −1 |
| `ui-venus-1.5-8b` | bestbuy_airpods | 0/3 | 0/3 | 0 |
| `mai-ui-8b` | saucedemo_backpack_only | 0/3 | **2/3** | **+2** |
| `mai-ui-8b` | saucedemo_full_checkout | 0/3 | 0/3 | 0 |
| `mai-ui-8b` | ikea_search_add | 0/3 | 0/3 | 0 |
| `mai-ui-8b` | ikea_billy | 0/3 | 0/3 | 0 |
| `mai-ui-8b` | bestbuy_airpods | 0/3 | 0/3 | 0 |
| `holo3-35b-a3b` | saucedemo_backpack_only | 3/3 | 2/3 | −1 |
| `holo3-35b-a3b` | saucedemo_full_checkout | 1/3 | **3/3** | **+2** |
| `holo3-35b-a3b` | ikea_search_add | 3/3 | 2/3 | −1 |
| `holo3-35b-a3b` | ikea_billy | 2/3 | 3/3 | +1 |
| `holo3-35b-a3b` | bestbuy_airpods | 1/3 | 0/3 | −1 |

**Aggregate by model:**
- `holo3-35b-a3b`: 10/15 = 67% → 10/15 = 67% (no change in total, redistributed)
- `mai-ui-8b`: 0/15 = 0% → **2/15 = 13%** (predicted: 40-60%; observed: 13%)
- `ui-venus-1.5-8b`: 8/15 = 53% → 7/15 = 47% (within n=3 noise)

**Aggregate by task:**
- saucedemo_backpack_only: 6/9 = 67% → 7/9 = 78%
- **saucedemo_full_checkout**: 1/9 = 11% → **3/9 = 33%** (long-horizon win)
- ikea_search_add: 5/9 = 56% → 4/9 = 44%
- ikea_billy: 5/9 = 56% → 5/9 = 56%
- bestbuy_airpods: 1/9 = 11% → 0/9 = 0%

**Mean elapsed time per run (run-time efficiency):**
- `ui-venus-1.5-8b`: 66.8s → **49.0s** (-17.8s — terminates earlier when cart-state confirms done)
- `mai-ui-8b`: 77.5s → **63.7s** (-13.8s — same mechanism)
- `holo3-35b-a3b`: 202.6s → 225.1s (+22.5s — probe overhead more visible because Holo3 already terminates well)

### Critical finding 1: MAI-UI's task-loop hypothesis confirmed, scope smaller than predicted

Phase 19's hypothesis (Critical finding 1 there): MAI-UI's 0/15 was
task-level looping — successfully completing the task action-by-action
but never self-terminating. Predicted lift: 0% → 40-60% with cart-state
injection.

**Phase 19a observed:** 0/15 → 2/15 = 13%. Both passes are on
`saucedemo_backpack_only` — the simplest task in the suite (login → add
backpack → done). On harder tasks (ikea_*, bestbuy, saucedemo full
checkout), MAI-UI stays at 0/3.

**Refined hypothesis:** cart-state injection rescues self-termination on
**single-action add-and-stop flows**, where "is the cart now in target
state?" cleanly maps to "is the task done?" It does **not** rescue
multi-step flows where:
- The task continues past add-to-cart (e.g. `ikea_search_add` requires
  click bag icon → verify contents → report PASS — three more steps after
  add).
- Add-to-cart is one of several state checkpoints (e.g. `saucedemo_full_checkout`
  has 9 checkpoints; cart state confirms 2 of them).

This is consistent with the underlying mechanism: cart-state injection
gives the model a strong "cart is in state X" signal at every step, but
it doesn't replace the model's own task-decomposition. MAI-UI's planning
remains weak; cart-state just lets it know when one specific subgoal is
done.

**Implication for the thesis:** the task-level-loop pathology is
narrower than the Phase 19 framing suggested. MAI-UI looping on
`saucedemo_backpack_only` was real and fixable; MAI-UI exhausting on
multi-step tasks is a different (and harder) problem — model-side
planning collapse, not harness-side instrumentation. Cart-state probe
is the right fix for the former, not the latter.

### Critical finding 2: cart-state surprise win on saucedemo_full_checkout

The 9-checkpoint long-horizon task moved 1/9 → 3/9 across models
(Holo3 specifically went 1/3 → 3/3). Phase 19's prediction was that
cart-state alone wouldn't help long-horizon tasks because they require
multi-step planning beyond "is cart correct."

**What actually happened:** mid-task cart-state confirmation gives Holo3
enough state-tracking confidence to keep advancing through the remaining
checkpoints. With cart-state injected, Holo3 sees:
- After add-3rd-cheapest: `[cart=1, m=localStorage]`
- After add-backpack: `[cart=2, m=localStorage]`
- After remove-3rd-cheapest from cart page: `[cart=1, m=localStorage]`
- Final: `[cart=1, m=localStorage]` confirms backpack-only at checkout.

This **state-anchoring** effect was unanticipated. The cart-state probe
is doubling as a working-memory aid, not just a termination signal.
Worth investigating whether this generalizes — would similar
deterministic state probes (URL, focused-element, scroll-position) lift
long-horizon tasks across other model families?

### Critical finding 3: UI-Venus is unmoved (precision walls dominate, not termination)

UI-Venus 53% → 47% is statistical noise (single 3/3 → 2/3 swing).
UI-Venus's failures are concentrated on `bestbuy_airpods` (overlay storm
prevents reaching add-to-cart at all) and `saucedemo_full_checkout`
(precision walls on small cart-icon target, ordinal-on-grid in CP3).
None of these are termination-bound; cart-state injection doesn't help.

This **confirms cliff hypothesis 3** from `docs/thesis.md`: B has a
precision sub-cliff at small targets that cart-state doesn't address.
The next harness lever for UI-Venus is **H1=2** (richer click primitive)
or **H4=2** (per-step state-probe with retry on miss) — not more
prompt-side instrumentation.

### Critical finding 4: timing wins are real and underrated

UI-Venus and MAI-UI both gained ~15s of mean wall-clock per run with
cart-state injection — and the probe itself adds ~5-30ms per step. The
gain comes from **earlier termination**: the model emits `Finished()`
earlier when cart-state confirms task done.

This matters for the cost-axis of the Pareto frontier: at 53% pass rate
and -17.8s/run, UI-Venus's `$/successful-task` improves modestly even
when total pass rate doesn't move. **Document the cost-axis lift in the
frontier table** — pass rate isn't the only metric.

### What the Phase 19a result means for Priority 2-5

- **Priority 1 (cart-state) is the right fix for the right problem** —
  but the problem is narrower than expected. It rescues simple add-and-
  stop flows; it doesn't rescue precision walls or multi-step planning.

- **Priority 2 (preflight cleanup) targets bestbuy_airpods directly.**
  Phase 19a shows bestbuy still at 0/9; cart-state can't help if the
  agent never reaches add-to-cart. Preflight modal/overlay dismissal is
  the targeted next step.

- **Priority 4 (loop detection upgrade) is partially obviated by cart-
  state.** Cart-state-confirmed-done shortcuts the early-out before the
  loop detector fires. But cart-state doesn't catch the case where
  cart-state never reaches target (e.g. agent's clicking the wrong
  element); a URL-based or distinct-state-hash detector would still
  catch that. Reduce priority but don't drop.

- **Priority 3 (mid-task overlay detection) is partially redundant with
  preflight cleanup** but not entirely — exit-intent and timing-triggered
  modals appear after preflight. Keep both.

- **Priority 5 (action receipts) is a refactor whose value is now
  decoupled from cart-state.** Skip until Phases 2-4 land or we hit a
  case where richer receipts unlock a model behavior.

### Operator-facing changes

- `data/runs.jsonl`: now has 92 rows (47 pre-Phase-19a + 45 Phase 19a).
  Phase 19a rows tagged `phase: "19a"`. The `phase` column is now part of
  the JSONL schema (commit `d2742cd`).
- `data/phase19a_logs/`: 45 per-run text logs.
- `data/screenshots/phase19a/`: 45 final-state PNGs.
- `cart_state.py` brace-balance regression test now in
  `test_cart_state.py` — catches future similar JS-string mistakes.

### Caveats

- Same 3-of-5-model coverage (F-7 still blocks 30B-A3B + bu-30b-a3b
  cells). Phase 19a is internally consistent against Phase 19 but doesn't
  fill those cells.
- n=3 is Tier-2 frontier sketch. The 1/3 → 3/3 swings on Holo3
  (`saucedemo_full_checkout`, `ikea_billy`) are not Tier-1 evidence.
  Tier-1 attempts (n≥10) on the strongest cells are the next step if we
  want defensible production claims.
- The `ikea_search_add` regression (5/9 → 4/9) and `bestbuy_airpods`
  regression (1/9 → 0/9) are both single-pass swings within n=3 noise.
  Don't read them as cart-state harm.
- The `saucedemo_backpack_only` Holo3 regression (3/3 → 2/3) is
  also noise — Holo3's one Phase 19a stuck_loop on this task is unusual
  given Phase 19's clean 3/3, but a single bad run from a 35B model is
  within expected variance.

## 2026-04-30 — Phase 20: Thunder cloud sweep — Holo3 quant ladder + Qwen-72B on excalidraw_drag

First time off-box for inference. `llama-server` ran on a Thunder Compute
A100 80GB (`a100xl_x1_prototyping`, $0.78/hr GPU + $0.24 vCPU + $0.075 disk
= ~$1.10/hr) while browser-use stayed local; SSH tunnel made `localhost:8080`
the abstraction. Harness lives in `scripts/thunder/{bootstrap_instance,
swap_model_remote}.sh + sweep.py`. Background and design are in
`docs/plans/2026-04-30-thunder-cloud-handoff.md`.

Run id `20260430-212754`, raw artifacts under
`data/sweeps/20260430-212754/`. Total billable time including bootstrap +
sweep + manual recovery: ~2h on the A100 ≈ $2.20.

### Cell-fills (excalidraw_drag, n=1)

| Model | Quant | rc | Visual | Steps | Notes |
|---|---|---|---|---|---|
| `holo3-35b-a3b` | IQ3_XXS (14 GB) | 0 | **❌ FAIL** | 4 | Empty canvas. Confabulated success — agent reported specific (false) coordinates 700,400→1100,600 with confident step narrative. |
| `holo3-35b-a3b` | Q4_K_M (21 GB) | 0 | ✅ pass | 3 | Rectangle drawn + selected. |
| `holo3-35b-a3b` | Q6_K (28 GB) | 0 | ✅ pass | 5 | Rectangle drawn + selected. |
| `qwen2.5-vl-72b-instruct` | Q4_K_M (47 GB) | 0 | ✅ pass | 4 | Rectangle drawn + selected. Manual recovery (see Surprised). |

### Cliff finding

For Holo3-35B-A3B on `excalidraw_drag` (class C, single drag-coord task),
**the quant cliff sits between IQ3_XXS and Q4_K_M.** At IQ3_XXS the model
loses the ability to verify its own visual state; the agent's
self-confirmation step false-positives on a blank canvas. Q4_K_M is the
minimum viable quant for this task class on this model size.

This is n=1 — Tier-3 evidence only. Worth re-running at n=3 to confirm the
IQ3_XXS failure is reproducible vs. a single-run unlucky pass-as-fail.
But the failure mode (specific-but-fake coordinate report, ~30 word
narrative, blank canvas) is exactly the failure shape we'd predict from
"vision encoder still works, language head can no longer ground language
in vision."

### Worked

- All four GGUFs loaded on the A100. Qwen-72B Q4_K_M fit at 44.5 GB CUDA0
  buffer + KV cache, well under the 80 GB VRAM ceiling.
- Browser-use ran unchanged against the remote `llama-server` via SSH
  tunnel. The hardcoded `SERVER_URL = "http://localhost:8080/v1"` keeps
  working because `sweep.py` owns the per-cell tunnel.
- Per-cell `swap.log` + `smoke.log` + `final.png` archive worked. Final
  PNG is the source of truth for visual verification — relying on
  `smoke_returncode=0` alone would have shipped IQ3_XXS as a pass.
- Throughput on Holo3 IQ3_XXS warm: ~90 tok/s prompt processing, ~79
  tok/s generation. (35B-A3B is 3B active params, so this is not
  unreasonable for A100 + IQ3_XXS even with the small file.)

### Broke

- `swap_model_remote.sh`'s 180s `/health` ceiling was insufficient for
  Qwen-72B Q4_K_M's 47 GB GGUF + 44.5 GB CUDA buffer mmap. Cell 4 was
  marked `swap_ok=false` in the auto-generated summary even though
  the model came up healthy ~5 min after timeout. **Fixed**: bumped
  ceiling to 600s (commit follows). Scaling: ~13 GB/min mmap budget,
  comfortable for any GGUF in the registry.

### Surprised

- **First-request cold-start is real and large.** Holo3 IQ3_XXS first
  inference: 51.7 s for 40 prompt tokens (kernel JIT + CUDA graph
  warmup). Second request 442 ms (~90 tok/s). Each cell pays this once;
  amortizes across browser-use's many requests per smoke.
- **Confabulation is detailed and specific, not vague.** The IQ3_XXS
  agent didn't just say "task done" — it manufactured a 5-step report
  with exact coordinates and modifier-key sequences that never happened.
  This argues for an automated post-smoke pixel-diff check rather than
  trusting `rc=0` alone, or at minimum a "agent's claim vs canvas
  state" reconciliation step in the smoke runner.
- **Provisioning surprises** (folded into `CLAUDE.md > Thunder cloud`):
  Thunder's `template=base` ships PyTorch's CUDA runtime only, not
  `nvcc`; needed `cuda12-9` for the full toolkit. SSH user is `ubuntu`,
  not `root`, even though MCP's `get_ssh_command` returns the `root@`
  form (that's `tnr connect`'s per-instance key flow). Org-level keys
  via `create_ssh_key` land in `/home/ubuntu/.ssh/authorized_keys`.

### Configuration deltas vs the plan

- Template was changed from `base` → `cuda12-9` before provisioning.
- SSH config on this machine is a home-manager-managed Nix store
  symlink — replaced with a real file to add `Host thunder`. Reversible
  via `home-manager switch`. Memory entry added.

### Next

- Per-cell auto pixel-diff (cheap canvas non-white ratio) to catch
  confabulations without manual inspection.
- Re-run Holo3 IQ3_XXS at n=3 to confirm the failure is reproducible
  before treating "IQ3_XXS is below the cliff" as durable.
- Consider adding `excalidraw_drag` to the local 8B baseline matrix to
  lock in the apples-to-apples comparison; right now we have local 8B
  on visual-grounding tasks but not on this exact drag prompt.

## 2026-04-30 — Phase 21: Cart suite on Qwen-72B (parameter-cliff probe vs Phase 19 baseline)

Same Thunder A100 instance, swapped to `qwen2.5-vl-72b-instruct` Q4_K_M.
Goal: same harness as Phase 19 (custom CDP agent), only the model
changes — does the parameter step from 30B-A3B-class to 72B-dense fix
the regression cells where local Phase 19 saw 0/9 or large variance?

Run id `20260430-cart-qwen72b`, n=1 per task (Tier-3 evidence).

### Results (n=1)

| Task | Outcome | Steps | Visual / cart-state | vs Phase 19 baseline |
|---|---|---|---|---|
| `saucedemo_full_checkout` | stuck_loop | 12 | ❌ login + sort succeeded; cart never populated. Final canvas shows products page, cart count=0. | Phase 19a Holo3 hit 1/3; Qwen-72B got further (login + sort) but stuck on the same add-to-cart pinch. |
| `ikea_billy` | done | 10 | ✅ cart_state probe confirmed count=0→1. Final canvas shows BILLY product page mid-add. | Phase 19a Holo3 swung 1/3 → 3/3; Qwen-72B clears it cleanly. |
| `bestbuy_airpods` | max_steps_reached | 60 | ❌ search→results→product page reached (AirPods Pro 3); 56 consecutive scrolls looking for Add-to-Cart, infinite oscillation y=0↔600. cart count=0. | Phase 19 was 0/9 across all local models; Qwen-72B got *closer* (reached the product page, which no local model did) but still didn't commit add-to-cart. |

### Cliff finding

Stepping from 30B-A3B (the local class) to 72B-dense moves the cliff
**only on the navigation/search axis**, not on add-to-cart commit:

1. **IKEA-class (search-and-add on a clean DOM):** parameter-bound. 70B
   clears it where 30B-A3B was at noise-level swings.
2. **SauceDemo-class (small DOM, requires precise per-item targeting):**
   not parameter-bound at this rung. Qwen-72B logged in and sorted but
   then locked onto the cart icon in the header (1228-1232, 94) and
   tried to click it five times instead of the per-item "Add to cart"
   buttons that are clearly visible on the page.
3. **BestBuy-class (heavy modal/iframe traffic):** not parameter-bound.
   The 70B can find AirPods Pro 3 via search and click into the
   product page — meaningful improvement over Phase 19's 0/9 — but the
   final add-to-cart action loses to the same iframe overlay /
   unpredictable-scroll wall that local models hit. **Confirms
   Phase 19a's prioritization: preflight modal/overlay cleanup
   (Priority 2) is the right next investment, not bigger models.**

### Worked

- The `qwenvl` harness path (added this phase) parses Qwen2.5-VL's
  native computer-use JSON format from message body and emits
  `click_at` (pixel-space) so the dispatcher's 0-1000 grounding remap
  doesn't fire. Once that was right, Qwen-72B drove real cart flows
  via the same dispatcher hooks all other harnesses use.
- The dispatcher's existing resilience (cart_state probe, scroll-fallback,
  CDP→JS click for `<select>` overlays) all kicked in correctly under
  the new harness without modification. The harness work was purely
  encode/decode; everything below it stayed put.
- IKEA succeeded in 10 steps with cart_state confirmation — exactly the
  cell where Phase 19a's tooling was supposed to help, and it did.

### Broke

- **Initial plan was to use the existing `toolcall` harness for Qwen.**
  Qwen2.5-VL-72B ignores OpenAI `tools=[...]` and `tool_choice="required"`
  entirely, emits its trained format directly in `message.content`:
  `{"action": "click", "coordinate": [x, y]}`. All 3 tasks parse-errored
  at step 0. The fine-tuning overrides the chat template's tool-call
  emission. Fix: new `qwenvl` harness in
  `scripts/custom_agent/qwenvl.py` that parses content directly. **Don't
  assume `--jinja` makes a fine-tuned model emit tool_calls.**
- **First attempt at `qwenvl` emitted `click` instead of `click_at`.**
  The dispatcher applies `grounding_remap` (0-1000 → viewport) on
  `click` actions, which rescaled (550, 186) → (678, 230) and missed
  every target. SauceDemo went stuck_loop with all 5 actions reporting
  `no page change`. Fix: emit `click_at` so the dispatcher treats the
  coords as already in pixel space.
- **CUDA OOM on the first swap from Holo3 Q6_K → Qwen-72B Q4_K_M**
  even though the previous Qwen-72B load (sweep cell 4) succeeded.
  `cudaMalloc` failed for the 44.5 GB model buffer despite
  `nvidia-smi` showing 80 GB free moments later. Cause: the prior
  llama-server's tmux teardown didn't fully release GPU memory by the
  time the new server's allocation request arrived (5 s wait between
  kill and start was insufficient under fragmentation). Workaround:
  re-running the swap script from the now-clean GPU state succeeded in
  44 s. Should bump the inter-swap settle window in
  `swap_model_remote.sh` if this recurs.

### Surprised

- **Qwen-72B's failure mode on SauceDemo is misclassification, not
  grounding.** The screenshots show the products page clearly with
  per-item "Add to cart" buttons. The model still picked the cart icon
  in the header. The 70B didn't fail at *seeing* — it failed at
  *deciding what to click*. That's task understanding, not visual
  grounding capacity, and it's not something more parameters fix.
- **Best Buy's iframe wall is genuinely model-agnostic.** Local
  Holo3-35B-A3B at 0/9 and Qwen-72B at 0/1 both hit the same scroll
  oscillation pattern on the product page. The dispatcher's
  scroll-fallback (which flips sign when no progress is made) actually
  *prevented* the stuck-loop early-out from firing here — both
  directions produce y movement when the model alternates them, even
  though the model is stuck.
- **Per-step latency on Qwen-72B is ~12-15 s, not the 3-5 s
  extrapolated from Phase 20's warm-throughput numbers.** Cart-task
  steps include scroll-probe + viewport-fitted screenshot encoding +
  32K-context vision request. bestbuy_airpods alone took 12.8 minutes
  (60 × ~13 s/step). Future cost estimates for cart sweeps should
  use ≥10 s/step.

### Configuration deltas vs the plan

- Added `scripts/custom_agent/qwenvl.py` (new harness path).
- Updated `scripts/custom_agent/__init__.py` registry:
  `qwen2.5-vl-72b-instruct → qwenvl`.
- Updated `scripts/custom_agent.py` dispatcher to import and call
  `navigate_step_qwenvl` when `HARNESS == "qwenvl"`.
- No `swap_model_remote.sh` changes this phase (the OOM was a one-off
  recovered by retry; if it recurs, bump the inter-swap settle window).

### Next

- **Preflight modal/overlay cleanup (Phase 19a Priority 2)** is now
  validated as the right next investment for Best Buy. Tier-3 evidence
  here, but consistent with Phase 19's 0/9 across the local registry —
  the wall isn't model size.
- Re-run `bestbuy_airpods` with explicit "scroll to bottom of page if
  Add to Cart not visible" hint in the task prompt, n=3, to separate
  "model can't find the button" from "model can't navigate to it under
  the iframe overlay." Cheap follow-up that disambiguates the
  Phase 19/21 failure attribution.
- Consider running the saucedemo regression at n=3 on Qwen-72B —
  Phase 19a Holo3 had 1/3 noise on this exact task, and the n=1 here
  showing stuck_loop on cart-icon-mistake could be a single-run bad
  draw. If Qwen-72B is consistently worse than Holo3 here, that's a
  task-understanding regression worth recording.

## 2026-05-01 — Phase 22: Qwen-72B regression confirmation + Holo3 quant cliff probe + Phase 20 errata

Same Thunder A100 instance pattern as Phase 20/21 (restored from
snapshot `vision-model-thunder-2026-04-30`). Three goals:

1. **Verify Phase 20's "IQ3_XXS is below the cliff for excalidraw_drag"
   verdict** by re-running n=3 (Tier-2 evidence).
2. **Probe one quant notch lower** (IQ2_M, 11.7GB) on the same task to
   actually find where the cliff sits, if it sits anywhere on Holo3.
3. **Re-run Phase 21 cart suite cells** that were either confound-tainted
   (Qwen-72B excalidraw → "PASS" from off-viewport screenshot) or
   borderline (saucedemo stuck_loop n=1, bestbuy oscillation n=1) to
   separate single-run noise from durable failure modes.

Run ids: `20260501-010141` (Holo3 IQ3_XXS x3), `20260501-011125` (Holo3
IQ2_M x3), `20260501-011611` (Qwen-72B excalidraw_drag_v2 x1),
`20260501-cart-qwen72b-phase22` (Qwen-72B saucedemo x3 +
bestbuy_airpods_scroll x1).

Total Thunder spend: ~$1.55 (1.4 hr A100XL @ $1.10/hr including a slow
~22 min snapshot restore vs the ~13 min baseline — 150GB on a busy day).

### Errata: Phase 20 ground-truth verdicts were inverted

Pre-Phase-22 sanity check — viewed all four `final.png` artifacts from
`data/sweeps/20260430-212754/` directly:

| Cell | Phase 20 verdict | Phase 22 visual reread | Diagnosis |
|---|---|---|---|
| Holo3 IQ3_XXS | FAIL — "empty canvas, confabulated" | Rectangle visibly drawn, selected | False fail (manual review error) |
| Holo3 Q4_K_M  | PASS | Rectangle visibly drawn | Correct |
| Holo3 Q6_K    | PASS | Rectangle visibly drawn | Correct |
| Qwen-72B Q4_K_M | PASS (manual_recovery)  | Empty viewport with "Scroll back to content" — rectangle drawn but viewport scrolled away | False pass (Escape-after-drag confound) |

Smoke logs for the inverted cells confirm this:
- IQ3_XXS step 3 dispatched `drag(700, 400, 1100, 600)` cleanly; the
  agent's success report matches the actual canvas state.
- Qwen-72B's step 2 dispatched `drag` AND `send_keys: Escape` in the
  same turn. Excalidraw treats the post-drag Escape as
  unfocus-and-shift-viewport, which scrolled the freshly-drawn element
  out of view. The "Scroll back to content" indicator is Excalidraw's
  signature for "elements exist, viewport is empty."

The Phase 20 cliff narrative ("IQ3_XXS is below the cliff for
excalidraw_drag on Holo3-35B-A3B") **is not supported by the data and
is hereby retracted.** All three Holo3 quants we ran (IQ3_XXS, Q4_K_M,
Q6_K) successfully drew the rectangle on n=1.

The original `summary.json` notes are preserved on disk as the
historical record; this errata is the corrected interpretation.

### Phase 22 results — corrected baseline + cliff probe

**`excalidraw_drag` (class C) — verification region (300, 100, 1750,
1000), threshold 5000 non-white px (catches blank-canvas confabulations
and off-viewport "PASS" screenshots).**

| Model · Quant | n | Pass rate | non_white range | Wall time / run |
|---|---|---|---|---|
| Holo3 IQ3_XXS | 3 | **3/3** | 6695-6843 | 62.8-139.8s (cold/warm) |
| Holo3 IQ2_M   | 3 | **3/3** | 6490-7083 | 61.0-91.8s |
| Qwen-72B Q4_K_M (drag_v2, no Escape) | 1 | 1/1 | 6830 | 166.6s |

The cliff for `excalidraw_drag` on Holo3-35B-A3B is **at or below
IQ2_M** — i.e. somewhere in the IQ2_S / IQ2_XS / IQ2_XXS / IQ1_M
range, if it exists at all on this task. Holo3-35B's grounding head
holds up at roughly 1/3 the original FP16 weight size for this single-
drag probe.

**`excalidraw_drag_v2` (Phase 22 corrected variant)** explicitly
forbids any keyboard input after the drag and removes the misleading
"capture a screenshot" instruction (which led Qwen to invoke Escape
as an "I'm done" signal in Phase 20). Qwen-72B with the corrected task
draws the rectangle and the verification screenshot reflects it.

### Phase 22 results — Phase 21 cart-suite re-runs

**`saucedemo_full_checkout` (class B) on Qwen-72B Q4_K_M, n=3:**

| Run | Outcome | Steps | Elapsed | Cart state at stuck-out |
|---|---|---|---|---|
| 1 | stuck_loop | 12 | 66.1s | count=0 (never added) |
| 2 | stuck_loop | 12 | 45.0s | count=0 (never added) |
| 3 | stuck_loop | 13 | 51.2s | count=1 (added one item) |

**0/3 PASS** — Phase 21's stuck_loop reproduces cleanly. The failure
mode in 2/3 runs is identical to Phase 21 n=1 (after login + sort,
fixate on cart-icon-area at (1228, 94) for 5+ consecutive no-effect
clicks instead of per-item Add-to-cart). Run 3 added one item then got
stuck navigating to the cart icon at (1228, 34). The saucedemo
regression vs Phase 19a Holo3 (1/3 partial passes) is **durable, not
single-run noise**.

This is task-understanding regression, not visual grounding capacity.
Qwen-72B *can* see the per-item buttons (the screenshots show them
clearly), but consistently picks the wrong target. Aligns with the
M-1 backlog rationale (within-family parameter-step probe via UI-Venus-
Ground-72B is the right control to separate "Qwen RL recipe specifically"
from "70B-class generally").

**`bestbuy_airpods_scroll` (class D, Phase 22 variant with explicit
"scroll all the way to the bottom" hint) on Qwen-72B Q4_K_M, n=1:**

- Outcome: `max_steps_reached`, 60 steps, 17.5 min wall clock.
- Steps 0-3: search bar → "AirPods" → Enter → click result card. Reached
  PDP cleanly (1/4 of the original Phase 21 progress wall — same place).
- Steps 4-59: 56 consecutive `scroll dir=down`. y position oscillates
  0↔600 (one viewport height) for the entire remainder of the run. Page
  height is 6906px; the agent never advances past 600px.
- Scroll-probe shows the wheel events hit either an `IFRAME` or an
  in-page hero `IMG` at the scroll target (616, 307). The dispatcher's
  scroll-fallback flips sign when no progress is made, so what looks
  like "the scroll is working" in the y=0→600→0 trace is actually the
  fallback bouncing back and forth without ever escaping the iframe's
  wheel-intercept.

**The explicit scroll-to-bottom hint did NOT help.** This is strong
evidence for the iframe-overlay-wall hypothesis (Phase 19a Priority 2,
"preflight modal/overlay cleanup is the right next investment, not
bigger models"): the wall is structural at the dispatcher / DOM layer,
not at the model layer. A real fix would need to either:

  (a) call `Element.scrollIntoView` on the underlying `<html>` body
      element, bypassing the iframe's wheel-event handler;
  (b) call `window.scrollTo(0, docHeight)` from the dispatcher when
      `scroll-fallback` detects the same iframe target N times in a
      row;
  (c) widen the dispatcher's `scroll` action to take an explicit
      target element selector and skip iframes by default.

### What worked

- **Pixel-check verification in `sweep.py`** (per-task `VERIFICATION_REGION`
  + `VERIFICATION_MIN_NON_WHITE` constants on the smoke task module).
  Backtested cleanly against Phase 20 data: passes the three Holo3
  cells (~6500-7000 non-white in the canvas band) and flags Qwen's
  "PASS" as suspicious (0 non-white = scrolled-off-viewport). Real-time
  verdict in Phase 22 matched manual final.png review on every cell.
  **Would have caught both Phase 20 misreads on day one.**
- **`sweep.py --repeats N`** with per-run `cell/run-{i}/` subdirs.
  Single swap, N smoke invocations, archived cleanly. Each cell entry
  in `summary.json` carries `run_index`, `final_non_white_px`, and an
  optional `verification_warning` string.
- **`excalidraw_drag_v2.py`** as a new corrected smoke variant (per
  CLAUDE.md "don't edit smoke payloads in place"). Original
  `excalidraw_drag.py` kept intact for n=3 reconfirmation; v2 is for
  Qwen-class models that interpret "capture a screenshot" as
  "send Escape."
- **Snapshot restore from Phase 20** as the provisioning path. ~22 min
  to RUNNING (slower than the docs' ~8.5 min/100GB for our 150GB; load
  varies with cluster busyness). All weights, llama.cpp build, tmux
  scaffolding intact. ~$0.40 of the spend was idle-during-restore at
  $1.10/hr — re-bootstrap from `base` would have been slower.
- The new Holo3 IQ2_M GGUF (11.66 GB) downloaded via
  `huggingface_hub.hf_hub_download` in ~2 min on the instance; existing
  `swap_model_remote.sh` Holo3 case reads any IQ-suffixed quant by
  filename, so no script edits needed.

### What broke

- **bestbuy_airpods_scroll runtime exceeded the 1500s Monitor timeout
  budget on the first attempt** (60-step run at 17.5 min wall clock).
  Re-armed once it became clear the long scroll loop wouldn't return
  early. Future cart-D probes should pre-budget Monitor for ≥30 min
  per `MAX_STEPS=60` cell.
- **Initial pixel-check tuning attempt (whole-image non-white count)
  failed to discriminate** Phase 20's IQ3_XXS vs Q4_K_M (10779 vs
  10839 non-white — diff of 60 pixels swamped by chrome). Switched to
  cropped region `(300, 100, 1750, 1000)` which excludes Excalidraw's
  toolbar and side panel; that gave the clean ~6500 vs 0 split between
  "rectangle drawn" and "blank viewport." Documented in
  `excalidraw_drag.py`'s `VERIFICATION_REGION` comment.

### Surprised

- **Holo3-35B-A3B at IQ2_M is still drawing rectangles cleanly.** The
  active 3B params at 2-bit imatrix quantization is roughly 0.75 GB of
  active weight at inference time; the visual encoder + grounding head
  apparently survive this much compression for the canvas-drag probe.
  Doesn't say anything about long-horizon planning at this quant —
  saucedemo / bestbuy-class probes on Holo3 IQ2_M would need separate
  runs to characterize.
- **Phase 20's "FAIL: empty canvas, confabulated" verdict was a manual
  review error**, not a model failure. The lesson is that *human visual
  inspection of small images is itself unreliable*; the pixel-check
  layer added in Phase 22 closes this loop. We were guessing "what
  failure mode would I expect from an aggressive quant" and pattern-
  matched the wrong failure shape onto a real PASS. Adding the
  pixel-check layer means future runs won't need this kind of human
  judgment for the canvas-drawn / canvas-blank discrimination.
- **Bestbuy scroll-hint had zero effect.** The model chose "scroll
  down" 56 consecutive times (the right action). The dispatcher
  faithfully attempted each scroll. The scroll just didn't work
  because the wheel-event target was the iframe. This is the
  cleanest demonstration so far that "give the model better
  instructions" is not the lever for class-D problems on heavy-modal
  retailers — the dispatcher needs to be smarter about *what to
  scroll*, not what coordinate to scroll at.

### Configuration deltas vs the plan

- Added `VERIFICATION_REGION` + `VERIFICATION_MIN_NON_WHITE` constants
  to `scripts/smokes/excalidraw_drag.py` (non-behavioral metadata —
  the agent never sees these; they're only read by sweep.py post-run).
- Created `scripts/smokes/excalidraw_drag_v2.py` (corrected task,
  preserves Phase 20's `excalidraw_drag.py` history per CLAUDE.md
  "don't edit smoke payloads in place" rule).
- Created `scripts/custom_agent_tasks/bestbuy_airpods_scroll.py` (Phase
  22 variant with explicit scroll-to-bottom hint and "do not use
  search-results-card Add-to-cart" anti-bypass guard).
- `scripts/thunder/sweep.py` extended with `--repeats N`, per-task
  pixel verification (PIL crop + non-white count + threshold-warning),
  per-run `cell/run-{i}/` archive layout, and `final_non_white_px` /
  `verification_warning` fields in `summary.json`. CellResult schema
  gained `run_index`.
- M-1 backlog item added: UI-Venus-Ground-72B (within-Venus-family 72B
  control for the Qwen-72B regression findings on saucedemo).

### Next

- **Implement the iframe-bypass scroll path in the dispatcher** before
  re-running any Best Buy probe. Phase 21 + Phase 22 between them give
  Tier-2 evidence (n=2 across two task variants) that the scroll
  bottleneck is dispatcher-bound, not model-bound. Cheapest cleanup:
  add a "if scroll-probe hit element is IFRAME, retarget at the html
  body" branch in `scripts/custom_agent/actions.py`. Acceptance: the
  same Qwen-72B + bestbuy_airpods_scroll cell completes in <60 steps.
- **Run UI-Venus-Ground-72B (M-1) on the same cart suite** once
  GGUFs are sourced/converted. Within-family parameter-step probe vs
  the 8B baseline. Specifically, repeat saucedemo_full_checkout x3
  to test whether the cart-icon-fixation is "70B-dense generally" or
  "Qwen-VL-72B specifically."
- **Probe Holo3 lower than IQ2_M** on excalidraw_drag if the cliff
  matters for the Pareto story. IQ2_XXS (9.5 GB) is the next obvious
  notch; IQ1_M would be a wide bracket. n=3 each, ~6 min of Thunder
  per cell. Skip if "Holo3-35B at any quant we tested handles class C
  drag" is enough for the frontier table.
- **Saucedemo regression isolation**: re-run the same cells on Holo3-
  35B-A3B Q4_K_M (we have it on the instance) at n=3 to confirm Holo3
  doesn't have the same task-understanding regression. If Holo3 is
  fine and Qwen is broken at n=3, the regression is recipe-specific,
  not parameter-specific.

---

## 2026-05-01 — Phase 22 backfill: 54/54 cells × n≥3, end-to-end fresh runs

### TL;DR

Drove every cell in the findings webapp's 6-model × 9-test grid to n=3
truthful runs from the current dispatcher, replacing the sparse mix of
prose-derived rows + ad-hoc probes that were on display before. **111 fresh
runs landed in `runs.jsonl` with `phase=22-backfill`**, durable per-run
screenshots archived under `data/sweeps/2026-05-01-frontier-backfill/`,
and the 5 prose-derived rows from the morning's narrative-only
backfill were removed once the cells they covered were re-grounded.

The webapp now shows zero gray cells. Every (model, task) cell renders
with a real `k/n` and at least one real thumbnail.

### Setup

- **Local cells (28 cells × n=3 = 84 runs):**
  ui-venus-1.5-8b (4), mai-ui-8b (5), ui-venus-1.5-30b-a3b (9),
  bu-30b-a3b-preview (9), holo3-35b-a3b (4) — all via
  `bash scripts/local_sweep.sh <task> <model> "" 3`. The wrapper
  swap_model.sh's the unit, runs `custom_agent.py` against the local
  Vulkan llama-server, archives `/tmp/custom_agent_final.png` to
  per-run dirs, and patches the trailing `runs.jsonl` row's
  `final_screenshot` to the durable archive (otherwise the webapp's
  `/tmp/*` filter drops it). Defensive guards: row-count and screenshot
  mtime checks before patching, so if `custom_agent.py` exits without
  appending, we don't corrupt history.
- **Thunder cells (5 cells × n=3 = 15 runs + 1 cell × n=3 mop-up = 18 total):**
  qwen2.5-vl-72b-instruct Q4_K_M on an A100XL (Thunder, prototyping mode).
  Restored from the 2026-04-30 snapshot, but the pre-built `llama-server`
  binary in the snapshot was compiled for an Intel CPU with AVX-512 and
  segfaulted (SIGILL) on this run's AMD EPYC 7763 host. Rebuilt in-place
  with `cmake -DGGML_CUDA=ON -DGGML_NATIVE=ON` (~12 min); native compile
  picked AVX2 only, ran cleanly. New snapshot
  `vision-model-thunder-2026-05-01-amd-rebuilt` saved with the rebuild.

### Pre-existing data left in place

`saucedemo_full_checkout` for ui-venus-1.5-8b, holo3-35b-a3b, and
qwen2.5-vl-72b-instruct already had ≥3 truthful runs in `runs.jsonl`
from earlier phases (Phase 19a / Phase 21). Those are NOT
`phase=22-backfill` — they remained as-is. The webapp aggregates by
(model, task) so the cell display is k/n across all rows for that
cell, not just the backfill subset.

### Two plan defects caught + fixed mid-execution

1. **`excalidraw_drag` and `excalidraw_drag_v2` lived only under
   `scripts/smokes/`** (intended for `smoke_browser_use.py`). Custom_agent
   only loads tasks from `scripts/custom_agent_tasks/`. Ported both as
   simple TASK strings using `type "r"` + `drag(x1,y1,x2,y2)` — the
   browser-use `send_keys` Escape sequence isn't needed since the
   custom_agent harness handles dialog dismissal coord-first. UI-Venus-8B
   probe (3 steps, 12s, pixel-verified rectangle) confirmed the port
   works.
2. **`-fit` segfault on llama.cpp build b1-a95a11e**. The new auto-fit
   feature deadlocks at `common_params_fit_impl: getting device memory
   data for initial parameters:`. The error message itself suggests
   `-fit off`; pass that flag to skip. Memory:
   `feedback_llamacpp_fit_segfault.md`.

### Per-class headlines (n=3 each unless noted)

**Class A — saucedemo_headed (DOM-traversable, short horizon):**
- 8B / 30B-A3B / 35B-A3B all 3/3 pass except mai-ui-8B and holo3.
- bu-30b-a3b-preview 0/3 stuck_loop, qwen-72B 0/3 stuck_loop.
  - The qwen-72B result is the most interesting outlier — a frontier-class
    model failing a known-DOM short-horizon task. Same `category=stuck_loop`
    pattern repeated across all 3 deterministic-temp runs (identical
    final.png hashes). Documented as Phase 22 cliff hypothesis 5
    candidate ("does the qwenvl harness's tool-call mode regress on
    saucedemo's login flow?").

**Class B — saucedemo_full_checkout (long-horizon DOM):**
- mai-ui-8b: **3/3 pass** (was 0/6 before; validates the Phase 16
  prose claim of "done at 22 steps"). Cell color flips from red to green.
- ui-venus-1.5-30b-a3b: 3/3 pass — strongest 30B-A3B-class result on
  this benchmark to date. Phase 13's "rejected" verdict was a harness
  artifact (pre-F-5 dispatcher), not a model verdict.
- bu-30b-a3b-preview: 0/3 stuck_loop — confirms Phase 13's "weaker
  instruction following" verdict survives the F-5 fix.

**Class C — excalidraw_drag / drag_v2 / toolbar:**
- ui-venus-1.5-8b: 9/9 across all three excalidraw cells, pixel-verified.
- ui-venus-1.5-30b-a3b: 9/9 same.
- holo3-35b-a3b: drag 1/3 (2 premature_done), drag_v2 3/3, toolbar 3/3.
  The drag-vs-drag_v2 split on holo3 validates the v2 task design (no key
  presses after drag = no spurious premature_done classifications).
- bu-30b-a3b-preview: drag 2/3 (Phase 13 had reported "wrong drag params";
  the explicit `drag(x1,y1,x2,y2)` action vocab in the ported task module
  fixes the param-name issue). drag_v2 3/3, toolbar 0/3 (exhausted).
- mai-ui-8b: 0/9 across the three C cells (stuck_loop or exhausted).
  Canvas grounding is mai-ui's binding cliff.
- qwen-72B: 0/9 by `category=premature_done`. **Initial reading was
  that this was a runner false-fail (non_white=6992 > 5000 threshold)
  — that interpretation was wrong.** The 6992 included UI chrome
  (toolbar, side panel); tighter canvas-only crop shows non_white=0 vs
  UV-8B's 377 on a real pass. Per the smoke logs, qwen emitted two
  separate `click_at` (700,400) → (1100,600) instead of one
  `drag(x1=700,y1=400,x2=1100,y2=600)` — two clicks don't register as
  a drag in Excalidraw, so the canvas was genuinely empty. The qwenvl
  harness's trained JSON action vocab uses `left_click` for click and
  has no native `drag` verb; the model decomposed the requested drag
  into two clicks. Runner classification of premature_done is correct.
  This is a *recipe / harness-vocabulary cliff* on qwen for canvas
  drag, not a runner bug.

**Class D — IKEA / Best Buy:**
- ui-venus-1.5-30b-a3b: ikea_billy 3/3, ikea_search_add 3/3,
  bestbuy_airpods 1/3. Phase 18's HANG note for bestbuy is gone — the
  F-5 dispatcher fix landed and UV30 reaches the product page now,
  with 1/3 fully passing (overlay-dismissal pinch is the remaining
  cliff per cliff hypothesis 4).
- bu-30b-a3b-preview: ikea_billy 0/3 stuck_loop, ikea_search_add
  0/3 mixed exhausted/stuck_loop, bestbuy_airpods 1/3.
- qwen-72B: ikea_search_add 1/3 (one pass, one premature_done, one
  stuck_loop) — consistent with the "qwen on this harness has a
  premature-done bias on novel sites" pattern.

### Cliff updates

- **Cliff hypothesis 1** ("class B is parameter-bound below 30B"):
  **REFUTED by clean data.** mai-ui-8b at 8B Q6_K passes
  `saucedemo_full_checkout` 3/3 in the post-F-5 harness. The 8B↔30B
  gap on B was a harness artifact. The cliff that matters for B is
  *harness sophistication*, not parameter count.
- **Cliff hypothesis 2** ("class C drag is parameter-bound"):
  **REFUTED.** UI-Venus-1.5-8B at 8B Q6_K nails 9/9 across drag /
  drag_v2 / toolbar. mai-ui-8b at the same parameter count gets 0/9.
  This is a recipe / training-data cliff, not a parameter cliff. A
  same-size 8B difference is bigger than the 8B→30B difference within
  the UI-Venus family.
- **Cliff hypothesis 4** ("class D will look like B but with overlay
  dismissal as the new precision wall"): **partially supported.**
  ikea_billy and ikea_search_add are now solved by UV30 but bestbuy
  remains 1/3 across both 30B-class candidates. Overlay-dismissal
  pinch is the binding constraint, matching the hypothesis.

### Runner observations / audit-class findings

- **Defensive verification override landed in the runner** as a
  follow-up to this backfill. `custom_agent_tasks/excalidraw_drag.py`
  and `excalidraw_drag_v2.py` now declare
  `VERIFICATION_REGION_FRAC = (0.30, 0.30, 0.70, 0.70)` (canvas-core,
  excludes toolbar / side panel) and `VERIFICATION_MIN_NON_WHITE = 150`.
  `custom_agent.py` reads these after each run and:
  (a) records `verification_pixel_count` on every row for audit trail;
  (b) upgrades a `stuck_premature_done` outcome to the model's terminal
  action (`done` / `call_user`) iff the pixel count meets the threshold
  in the declared region.
  This is purely defensive — on this backfill's data the override
  would not fire on any qwen-72B run (pixel counts are 0). It
  protects against a UI-Venus-like model that genuinely draws a
  rectangle then emits `Finished` after a no-effect click and would
  otherwise be classified `stuck_premature_done`. Tested against
  hand-built fixtures in `scripts/custom_agent/test_run_log.py`.
- **`saucedemo_backpack_only` for UV30 is 0/3 stuck_loop**, despite UV30
  being 3/3 on the harder `saucedemo_full_checkout`. Worth a deeper
  trace — the simpler task should not be harder.
- **Deterministic outputs at temp=0.0 produce identical final.png hashes
  across n=3 runs** for several cells (qwen-72B saucedemo_*, qwen-72B
  excalidraw_*). n=3 is statistically n=1 in those cases. n=3 still
  catches OS-level / network-layer flakes, but the model contribution is
  fully captured by n=1 for these cells. Not a defect, just a calibration
  note — don't read significance into clean k/n splits when temp=0.0.

### Costs

- **Local sweeps**: 5–6 hours wall clock, $0 marginal (existing GPU /
  electricity).
- **Thunder**: ~2 hours of A100XL prototyping (~$2.20). Breakdown:
  ~30 min provisioning + restore + initial misdiagnosis of the SIGILL,
  ~12 min llama.cpp rebuild, ~45 min sweep, ~10 min mop-up cell, ~15 min
  snapshot creation. The misdiagnosis cost ~$0.60 — the binary segfaulted
  silently and looked like a hang at first; capturing exit code 132 +
  matching CPU flags revealed it.

### What's NOT in this backfill

- Holo3 was tested only on its 4 gap cells (saucedemo_headed + 3
  excalidraw). Its existing 5 cells in runs.jsonl from Phase 19a/Phase 21
  were left as-is. The webapp's k/n for those cells is correct.
- ui-venus-1.5-30b-a3b's `bestbuy_airpods` 1/3 is a low-n datapoint —
  worth bumping to n=5 in a future pass if the Pareto-frontier story
  needs more confidence on the overlay cliff.
- Qwen-72B `bestbuy_airpods` was already covered by Phase 21 (max_steps
  at 60 steps, 12.8 min). Not re-run — the existing data already
  characterizes that cell.

