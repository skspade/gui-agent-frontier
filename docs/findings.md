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

## Open questions for retro
1. Are we leaving UI-Venus's grounding capability on the table by using
   browser-use? Worth a custom client for canvas-heavy use cases?
2. Recovery prompt: would `extend_system_message` with "if action didn't
   change page, try X, Y, Z" fix the loop-on-failed-click pattern?
3. Q4_K_M vs Q5_K_M / Q6_K — does grounding accuracy degrade on visual tasks?
   We have the f16 intermediate and can requantize cheaply.
4. Headed mode is a hard requirement for sites with nested-anchor cart
   patterns. For unattended runs, do we need `xvfb-run` or `--ozone-platform=
   headless`? (Untested.)
5. Context budget: 32K worked for a 22-step run. What's the ceiling before
   we need KV quantization (`--cache-type-k q8_0`) to keep VRAM in budget?
