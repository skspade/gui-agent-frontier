# Phase 15 — Holo3 native-harness eval

Date: 2026-04-29
Status: **fully unblocked, ready for execution.** Surfer-h-cli source was
cloned and read during planning; all prompts, schemas, image-preprocessing
conventions, and llama-server compatibility verified. See "Resolved during
planning probe" below for the concrete artifacts the executor will paste
into `scripts/custom_agent/holo3.py`.

## TL;DR

Phase 14 found that 4 of 6 candidate models parse-errored at step 4 of
the long-horizon saucedemo task because they emit non-`<action>` output
when our harness forces them through UI-Venus's `<action>` schema.
Verified scores capped at UI-Venus-1.5-8B's 2/9 strict / 4/9 lenient.

Phase 15 builds a **Holo3-native harness path** in
`scripts/custom_agent/` so we can evaluate Hcompany's flagship local
model (Holo3-35B-A3B) on its actual interface. Adds Holo3 as a new
candidate.

**Important framing correction (2026-04-29):** the right harness for Holo3
is **NOT Hermes-style `<tool_call>` tag-calling** that we initially assumed
from Phase 14's parse_error pattern. Holo3 uses **OpenAI-compatible
structured outputs** — the model emits plain JSON in `message.content`
matching a Pydantic schema we define and pass via the OpenAI-standard
`response_format={"type":"json_schema","json_schema":{...,"strict":true}}`
field. (`extra_body={"structured_outputs":...}` is vLLM-only and is
**silently ignored** by llama-server — verified during planning.) The
reference agent loop is **`hcompai/surfer-h-cli`** on GitHub, which uses
a **mandatory two-pass localization + navigation** pattern (the navigator
emits an `element: "<text description>"` and dummy x/y; the localizer
fills in real coordinates). Different temperatures: 0.0 for localization,
0.7 for navigation.

The Phase 14 `<tool_call>` we saw from Holo2/MAI-UI/bu-30b was llama.cpp's
default behavior when tool definitions appear in the chat template — it's
not the model's *native* eval interface. Each of those models likely has
its own native flow (Holo2 is older H-Company, MAI-UI is Tongyi-MAI,
bu-30b is browser-use). **Phase 15 is scoped to Holo3 only.** Other
candidates get their own phases if Holo3's result warrants it.

> **Goal: see whether Holo3 on its native eval harness clears
> UI-Venus-1.5-8B's 2/9 strict baseline on the saucedemo long-horizon
> task.** None of these harnesses get productionalized — minimal eval rig.

## Read these before starting (cold-start orientation)

1. **`CLAUDE.md`** at repo root — non-negotiable operational rules. Pay
   attention to: privileged ops via `/tmp/foo.sh` + absolute paths;
   long-running agent runs must redirect stdout to a log file (the harness
   wraps `tail -200` which buffers everything in memory); independent
   verification screenshots are mandatory; display env vars are
   `DISPLAY=:0 XAUTHORITY=/run/user/1000/xauth_rVYaGJ XDG_RUNTIME_DIR=/run/user/1000`.
2. **`docs/findings.md`**, the **Phase 14** entry and the **Phase 14 follow-up**.
   The follow-up table at the bottom is the baseline this phase compares
   against. UI-Venus-1.5-8B's 2/9 strict / 4/9 lenient is the bar.
3. **`docs/plans/2026-04-29-harness-fit-research.md`** — original R1
   hypothesis and decision tree. Phase 15 lives in the
   "investigate elsewhere" branch of that tree.
4. **`docs/backlog.md`** — for context on what other work is queued.

Also useful (skim only):
- `scripts/custom_agent.py` — the existing run loop, instrumented in Phase 14.
- `scripts/custom_agent/model.py` — UI-Venus prompt + parser (the path Phase 15 forks alongside).
- `scripts/custom_agent/actions.py` — CDP-level dispatcher; model-agnostic; reused by both harness paths.
- `scripts/custom_agent_tasks/saucedemo_full_checkout.py` — the long-horizon 9-checkpoint task that R1 evaluates against.

## What's already done (don't redo)

- **Page-change detector** in `custom_agent.py` (md5 screenshot before/after each dispatch; sets `Action.no_effect`; surfaces a STOP warning to the model after 2 consecutive no-changes).
- **Reject premature `Finished`/`CallUser`** — if the model emits either after 2 no-effect actions, the loop exits with `outcome="stuck_premature_done"` so a stuck run never records a false PASS.
- **Stuck-loop early-out** — 5 consecutive no-effects exit with `outcome="stuck_loop"` (saves ~110s vs running to MAX_STEPS).
- **Keyboard primitives** — `Type` dispatches per-character `Input.dispatchKeyEvent` (so native `<select>` letter-jump works); `PressEnter`/`PressBack`/`PressHome` and `Wait`/`CallUser` (treated as `done`) all dispatch.
- **`MODEL=<alias>` env var** — `scripts/custom_agent/model.py` reads `MODEL` from the environment, default `ui-venus-1.5-8b`. No code edit needed to swap which alias the harness expects.
- **`swap_model.sh` registry** includes ui-venus-1.5-8b / 30b-a3b, mai-ui-8b, holo2-30b-a3b, bu-30b-a3b-preview, holo1.5-7b. Phase 15 just appends `holo3-35b-a3b`.
- **Phase 14 R1 baseline artifacts** at `/tmp/r1_artifacts/<alias>.{log,steps,final.png}` for all six previously-tested stacks. The UI-Venus-1.5-8B run is the bar; the four parse_error logs are reference for what the Hermes parser must accept.

## Hypothesis under test

> Holo3-35B-A3B on its native two-pass surfer-h-cli-style eval harness
> beats UI-Venus-1.5-8B's verified 2/9 strict (4/9 lenient) saucedemo
> score on the same task.

Falsification: Holo3 either (a) parse-errors despite the structured-output
schema, (b) completes login but hits the same coord-precision wall that
pinned UI-Venus, or (c) retries the same action without reasoning about
failures (a documented Holo3-35B failure mode that the API-only 122B
variant doesn't share).

## Resolved during planning probe (2026-04-29)

Surfer-h-cli was cloned to `/tmp/surfer-h-cli` and the relevant skills
were read directly. Everything below is verbatim from the source unless
explicitly noted as adapted. **The executor's job is to port these to
`scripts/custom_agent/holo3.py`, not redesign them.**

### Confirmed: llama-server compatibility

- `response_format={"type":"json_schema","json_schema":{"name":...,"schema":...,"strict":true}}` **works** on the running llama-server build (`b1-7b8443a`). Verified live: returned `{"x":5}` for a tiny test schema.
- `extra_body={"structured_outputs":{"json":...}}` is **silently ignored** — vLLM-only. Do not use.
- Native `<think>` tag and strict `response_format` are **mutually exclusive** at sampling time (the strict schema constrains the entire `content` to match, so the model can't emit a `<think>...</think>` prefix). Surfer-h-cli's design routes reasoning *into* the schema via a top-level `thought: str` field — that's the path we use.
- Disable native thinking via `--chat-template-kwargs '{"enable_thinking":false}'` on the server unit so the chat template emits an empty `<think></think>` block instead of opening one. This avoids any partial-think-tag artifacts at the start of the constrained generation.

### Confirmed: navigation pass

System message is a JSON-encoded blob containing three keys: `guidelines`, `state_format` (the `NavigationState` schema), `answer_format` (the `AbsWebAgentNavigate` schema). Verbatim guidelines text from `navigation_step.py` (NAVIGATION_PROMPT), **with one line stripped for our saucedemo task** — the canonical prompt forbids login, which would tank CP1. Strip exactly:

> `- Never try to login, enter email or password. If there is a need to login, then go back.`

Keep everything else verbatim, including the `current date` line (use `datetime.today().strftime("%A, %B %-d, %Y")`).

User message is JSON `{"task": ..., "previous_actions": ..., "step": "", "notes": ...}` followed by image_url entries. Screenshots resized via Qwen2VL `smart_resize` (factor=28, min_pixels=56², max_pixels=14²·4·1280≈1003520) before JPEG-encoding at quality=90.

Temperature: **0.7**. Pass the last 3 screenshots (matches `n_navigation_screenshots=3` default).

Schema (verbatim from `navigation_models.py`, port to a single Pydantic class union):

```python
class AbsClickElementAction(BaseModel):
    action: Literal["click_element"] = "click_element"
    element: str   # text description of the element
    x: int         # placeholder; localizer overwrites
    y: int         # placeholder; localizer overwrites

class AbsWriteElementAction(BaseModel):
    action: Literal["write_element"] = "write_element"
    content: str
    element: str
    x: int         # placeholder; localizer overwrites
    y: int         # placeholder; localizer overwrites

class ScrollAction(BaseModel):
    action: Literal["scroll"] = "scroll"
    direction: Literal["up","down","left","right"] = "down"

class GoBackAction(BaseModel):
    action: Literal["go_back"] = "go_back"

class RefreshAction(BaseModel):
    action: Literal["refresh"] = "refresh"

class WaitAction(BaseModel):
    action: Literal["wait"] = "wait"

class RestartAction(BaseModel):
    action: Literal["restart"] = "restart"

class AnswerAction(BaseModel):
    action: Literal["answer"] = "answer"
    content: str

WebAgentNavigateAction = (
    AbsClickElementAction | AbsWriteElementAction | ScrollAction |
    GoBackAction | RefreshAction | WaitAction | RestartAction | AnswerAction
)

class AbsWebAgentNavigate(BaseModel):
    thought: str = ""   # reasoning lives here, NOT in <think> tag
    notes: str = ""     # accumulating extracted info; carry forward across turns
    action: WebAgentNavigateAction
```

**Discriminator field is `action`** (string literal). Carry `notes` from each response forward into the next request's user message so the model accumulates context across turns.

### Confirmed: localization pass

Holo3 takes the **modern (Holo1.5-style) localization path** by default: structured `ClickAbsoluteAction` JSON, image resized to fixed **1000×500** LANCZOS. (Decision; if Sean later finds Hcompany docs prescribing a different contract for Holo3 specifically, swap to that.) Verbatim from `localization_1_5.py`:

```python
class ClickAbsoluteAction(BaseModel):
    action: Literal["click_absolute"] = "click_absolute"
    x: int   # pixels from left edge of the resized 1000x500 image
    y: int   # pixels from top edge of the resized 1000x500 image
```

Prompt (verbatim):

```
Localize an element on the GUI image according to the provided target and output a click position.
 * You must output a valid JSON following the format: {ClickAbsoluteAction.model_json_schema()}
 Your target is:

{component}
```

Where `{component}` is the `element` field from the navigator's `click_element` / `write_element` action.

Temperature: **0.0**. Image: simple resize to 1000×500 (NOT smart_resize), JPEG quality=90, base64.

Coordinate rescale to viewport pixels:
```python
scale_x = original_width / 1000
scale_y = original_height / 500
viewport_x = clamp(int(model_x * scale_x), 0, original_width - 1)
viewport_y = clamp(int(model_y * scale_y), 0, original_height - 1)
```

### Confirmed: agent loop wiring

Match `navigation_step.py`'s flow:
1. Run navigation request → parse `AbsWebAgentNavigate` JSON.
2. If action is `click_element` or `write_element`: run localization request with `screenshots[-1]` and `action.element`. Overwrite `action.x`/`action.y` with the rescaled viewport coords.
3. Pass the resolved action to our existing `dispatch()` in `scripts/custom_agent/actions.py`.

The validation/answer-retry pass from surfer-h-cli is **deferred** — single-model eval only.

### Action mapping (surfer-h-cli → our existing dispatcher)

Our `actions.py` already handles `click`, `type`, `scroll`, `press_*`, `wait`, `done`, `call_user`. Map surfer-h-cli action variants to existing `Action` kinds in `parse_holo3()`:

| surfer-h-cli | Our `Action.kind` | Notes |
|---|---|---|
| `click_element` | `click` (xy from localizer) | Native `<select>` letter-jump: click the select first; the saucedemo case (price-sort dropdown) is solved by the navigator emitting a follow-up `write_element` whose content is a single letter — our existing per-key keydown `_type_keys` triggers the option jump. **Dispatcher-only detail; invisible to model.** |
| `write_element` | `click` (xy from localizer) THEN `type` (text=content) | Two dispatched actions per one model action. The navigator's docstring says "Don't Enter at the end" so don't auto-PressEnter. |
| `scroll` | `scroll` (direction; let dispatch synthesize start/end if needed) | |
| `go_back` | `press_back` | Already handled via `_PRESS_SPECS`. |
| `refresh` | (custom) | Page.reload via CDP — small addition to actions.py if needed. Probably never emitted in saucedemo. |
| `wait` | `wait` | Already handled. |
| `restart` | (skip / log) | Returns to start URL. Not needed for saucedemo eval. Treat as no-op + log. |
| `answer` | `done` (text=content) | Existing premature-done rejection still applies. |

The `thought` and `notes` fields are recorded into `Action.conclusion` (and a new `Action.notes` field if useful for the carry-forward). They're not dispatched.

### Reference: image preprocessing helpers (port verbatim from `surfer-h-cli/src/surfer_h_cli/utils.py`)

```python
def smart_resize(height, width, factor=28, min_pixels=56*56, max_pixels=14*14*4*1280):
    # ... (port verbatim; this is the Qwen2VL preprocessor)
```

Localization uses simple `image.resize((1000, 500), LANCZOS)`, no smart_resize.

### Real-world caveat (still applies)

The open 35B is reportedly 10–15pp behind the API-only 122B on practical
tasks and tends to retry the same action instead of reasoning about
failures. Consistent with the confabulation pattern Phase 14 documented
for UI-Venus 8B — the stuck-loop early-out (5 consecutive no-effect →
exit) catches it.

## Scope decisions already made (these are settled — don't relitigate)

- **Holo3 quant: i1-IQ3_XXS (13.62GB) + mmproj-Q8_0 (0.6GB).** Source:
  `mradermacher/Holo3-35B-A3B-i1-GGUF` (LLM) + `mradermacher/Holo3-35B-A3B-GGUF`
  (mmproj — only the non-i1 repo has it; pair the two). Fits 16GB VRAM
  with margin. Phase 13's 30B-A3Bs ran at Q3_K_M=14GB; Holo3 is heavier
  per-param so we drop a step. Don't try Q3_K_M (16.76GB) — it OOMs once
  you add mmproj + 32K KV.
- **Storage: `/mnt/data/models/holo3-35b-a3b/`.** Matches Phase 13 30B-A3B
  placement. `/mnt/data` has ~528GB free; `/home/seans` has ~42GB free
  and should NOT take new models.
- **Phase 15 is scoped to Holo3 only.** Holo2, MAI-UI-8B, bu-30b-a3b-preview,
  and Holo1.5-7B all need their own native harnesses (different schemas,
  different lineages). They each get their own phase if Holo3's result
  warrants the investment. Don't try to roll multiple natives into one
  harness — that's the mistake that pinned us at "Hermes for everyone"
  in the first plan revision.
- **`llama.cpp` already supports `qwen35moe`.** Confirmed in
  `/home/seans/llama.cpp/src/llama-arch.cpp` (`LLM_ARCH_QWEN35MOE`).
  Don't try to rebuild llama.cpp.

## Step-by-step plan

### Step 1 — Add the Holo3 native harness path

Create `scripts/custom_agent/holo3.py`. The structure below is concrete;
prompts/schemas come verbatim from "Resolved during planning probe".

Top-level constants:
- `LLAMA_URL = "http://localhost:8080/v1/chat/completions"`
- `MODEL_NAME = os.environ.get("MODEL", "holo3-35b-a3b")`
- `NAVIGATION_TEMPERATURE = 0.7`, `LOCALIZATION_TEMPERATURE = 0.0`
- `LOCALIZATION_TARGET_SIZE = (1000, 500)`

Pydantic schemas: paste verbatim from "Resolved during planning probe"
above. Both `AbsWebAgentNavigate` and `ClickAbsoluteAction`. Compute
JSON schemas via `Model.model_json_schema()` at import time.

Functions:

- **`step_holo3_navigate(task, history, screenshots_b64, notes, *, timeout=120.0) -> dict`**
  - Builds the system message: `json.dumps({"guidelines": NAV_GUIDELINES, "state_format": NavigationState.model_json_schema(), "answer_format": AbsWebAgentNavigate.model_json_schema()})`.
  - User message: text part is `json.dumps({"task": ..., "previous_actions": render_history(history), "step": "", "notes": notes}, separators=(",",":"))` followed by image_url parts. Use **smart_resize** (port from surfer-h-cli utils) for navigator screenshots; JPEG q=90.
  - Send last 3 screenshots (or fewer if early in run).
  - Payload includes `"response_format": AbsWebAgentNavigate-derived json_schema dict`, `"temperature": 0.7`, `"chat_template_kwargs": {"enable_thinking": false}`.
  - Returns `json.loads(response.choices[0].message.content)` — the parsed dict.

- **`step_holo3_localize(image_b64_original, element_description, *, timeout=60.0) -> tuple[int, int]`**
  - Decode original image, resize to 1000×500 LANCZOS, re-encode JPEG q=90.
  - Build prompt via `create_localization_prompt(element_description)`.
  - Payload: image + text content, `"response_format": ClickAbsoluteAction-derived json_schema`, `"temperature": 0.0`, `"chat_template_kwargs": {"enable_thinking": false}`.
  - Parse response JSON, rescale x/y from 1000×500 → original viewport pixels using the `scale_x = orig_w/1000` formula in "Resolved during planning probe". Clamp to image bounds.

- **`navigate_step_holo3(task, history, screenshots_b64, notes) -> tuple[Action, str]`**
  - Calls `step_holo3_navigate`, gets parsed dict.
  - If `parsed["action"]["action"] in ("click_element","write_element")`: calls `step_holo3_localize(screenshots_b64[-1], parsed["action"]["element"])`, overwrites x/y.
  - Maps to existing `Action` per the table in "Action mapping (surfer-h-cli → our existing dispatcher)". Returns `(Action, parsed["notes"])` — caller carries `notes` forward into next request.

- **`parse_holo3(parsed_dict) -> Action`** (exported for symmetry with the UI-Venus path)
  - Pure mapping function from already-parsed dict to `Action`. No HTTP. Used by the unit test.

History rendering: format as
```
step 1: <json action> -> <thought>
step 2: <json action> -> <thought> [no page change]
```
Matches the format the UI-Venus path uses; surfer-h-cli's reference accepts a free-form `previous_actions` string.

`write_element` requires **two dispatched actions** per one model action: a click at the localized coords, then a `Type(text=content)`. Either return them as a list and update the run loop to accept lists, OR (simpler) dispatch the click+type inline within `navigate_step_holo3` and return a single synthetic `Action` to the run loop. Pick whichever is cleaner — the run loop only cares about page-change tracking.

Wire harness selection in `scripts/custom_agent.py`:

```python
HARNESS = os.environ.get("HARNESS", "uivenus")
if HARNESS == "holo3":
    from scripts.custom_agent.holo3 import navigate_step_holo3
    # Run loop calls navigate_step_holo3 directly — different signature than
    # model_step + parse_action (since localization is interleaved). Keep both
    # branches separate rather than forcing them through one signature.
else:
    from scripts.custom_agent.model import step as model_step, parse_action
```

The two-branch run loop is fine for an eval-only harness. Don't over-abstract — see CLAUDE.md (no premature abstractions).

Carry `notes` across turns: maintain `notes_state: str = ""` in the run loop, pass into `navigate_step_holo3`, overwrite on each return.

The current run loop only keeps the latest screenshot. The Holo3 navigator wants the **last 3 screenshots**. Add a `screens: collections.deque(maxlen=3)` (or simple list) to the loop; append the pre-action screenshot each step; pass `list(screens)` into the navigator. Use the latest entry for the localization pass.

Add a parser unit test at `scripts/custom_agent/test_parse_holo3.py`.
Fixtures: synthetic dicts matching the schemas above, one per action variant.
Verify `parse_holo3` produces the right `Action.kind` + fields.

**Acceptance for step 1:**
- `.venv/bin/python -m scripts.custom_agent.test_parse_holo3` passes.
- One-step probe: with the server already serving Holo3 and a saucedemo screenshot in hand, calling `step_holo3_navigate` returns a valid `AbsWebAgentNavigate` dict (no JSON parse error) and the `action` field decodes to one of the 8 known variants.
- `MODEL=holo3-35b-a3b HARNESS=holo3 .venv/bin/python -u scripts/custom_agent.py saucedemo_headed > /tmp/holo3_smoke.log 2>&1` runs without parse_error and login completes (page reaches inventory). Full task is step 3.

### Step 2 — Download and register Holo3-35B-A3B

```bash
mkdir -p /mnt/data/models/holo3-35b-a3b
cd /mnt/data/models/holo3-35b-a3b
# LLM (i1 imatrix quant)
curl -L -o holo3-35b-a3b.i1-IQ3_XXS.gguf \
  "https://huggingface.co/mradermacher/Holo3-35B-A3B-i1-GGUF/resolve/main/Holo3-35B-A3B.i1-IQ3_XXS.gguf"
# mmproj (only on the non-i1 repo)
curl -L -o mmproj-holo3-35b-a3b-Q8_0.gguf \
  "https://huggingface.co/mradermacher/Holo3-35B-A3B-GGUF/resolve/main/Holo3-35B-A3B.mmproj-Q8_0.gguf"
```

Add a `holo3-35b-a3b` entry to the `MODELS` dict in
`scripts/swap_model.sh`. Match the existing 30B-A3B template exactly:

```bash
# Existing 30B-A3B entry (don't copy verbatim — read it from the file)
holo2-30b-a3b)
    GGUF="/mnt/data/models/holo2-30b-a3b/holo2-30b-a3b-${QUANT}.gguf"
    MMPROJ="/mnt/data/models/holo2-30b-a3b/mmproj-holo2-30b-a3b-f16.gguf"
    DEFAULT_QUANT="Q3_K_M"
    ALIAS="holo2-30b-a3b"
    DESC="Holo2-30B-A3B llama.cpp server (Vulkan)"
    ;;
```

For `holo3-35b-a3b`, use:
- `GGUF=/mnt/data/models/holo3-35b-a3b/holo3-35b-a3b.i1-${QUANT}.gguf` (note the `.i1-` segment — the i1 quants are named differently)
- `MMPROJ=/mnt/data/models/holo3-35b-a3b/mmproj-holo3-35b-a3b-Q8_0.gguf`
- `DEFAULT_QUANT=IQ3_XXS`
- `ALIAS=holo3-35b-a3b`
- `DESC="Holo3-35B-A3B llama.cpp server (Vulkan)"`

**Important:** the unit's `ExecStart` for Holo3 must include `--chat-template-kwargs '{"enable_thinking":false}'`. Strict `response_format` and the chat template's auto-`<think>\n` prefix conflict; disabling thinking at the template level is the path. Reasoning still happens — it's captured in the schema's `thought` field. The current Holo1.5 unit (visible at `/etc/systemd/system/vision-model.service`) is the template to follow for the rest of the flags (`-ngl 99 -c 32768 --flash-attn on --image-min-tokens 1024 --jinja`).

Smoke the swap:
```bash
sudo -n bash /home/seans/Source/vision-model/scripts/swap_model.sh holo3-35b-a3b
```
(Note: `sudo` NOPASSWD requires the **absolute** path to `swap_model.sh`. A relative path triggers a password prompt. This is documented in CLAUDE.md.)

Should print "ready after Ns on holo3-35b-a3b IQ3_XXS" and `curl -s http://localhost:8080/health` returns `{"status":"ok"}`.

**Acceptance for step 2:**
- Server starts cleanly, `/health` returns ok.
- `curl -s http://localhost:8080/v1/models | head -c 300` shows the `holo3-35b-a3b` alias.

### Step 3 — Run R1 on Holo3

```bash
sudo -n bash /home/seans/Source/vision-model/scripts/swap_model.sh holo3-35b-a3b

DISPLAY=:0 XAUTHORITY=/run/user/1000/xauth_rVYaGJ XDG_RUNTIME_DIR=/run/user/1000 \
  PYTHONUNBUFFERED=1 MODEL=holo3-35b-a3b HARNESS=holo3 \
  .venv/bin/python -u scripts/custom_agent.py saucedemo_full_checkout \
  > /tmp/r1_artifacts/holo3-35b-a3b.holo3.log 2>&1

cp -r /tmp/custom_agent_steps /tmp/r1_artifacts/holo3-35b-a3b.holo3.steps
cp /tmp/custom_agent_final.png /tmp/r1_artifacts/holo3-35b-a3b.holo3.final.png
```

**Do not pipe long runs through `tail` or any other buffering wrapper** — the
harness wraps `tail -200` which buffers stdout in memory until EOF. Read the log file directly with `Read` or `cat` after each run.

Expected per-run wall time: ~120s–600s. Holo3 35B-A3B has only 3B active
params (similar to Phase 13's 30B-A3Bs at ~2.5s/step), but: (a) two-pass
localization doubles the per-step wall (one nav + one localize call), and
(b) strict `response_format` may add modest sampling overhead. Plan for
~5s/step worst case, ~200s end-to-end for a clean 40-step ceiling.

Optional comparison run: re-run UI-Venus 8B on the saucedemo_full_checkout
task with the current head to confirm the Phase 14 baseline still
reproduces (the harness instrumentation has changed since then). One run, ~135s.

### Step 4 — Score Holo3 against the UI-Venus 8B baseline

View `/tmp/r1_artifacts/holo3-35b-a3b.holo3.final.png` and the per-step
screenshots, and score against the 9-checkpoint rubric (verbatim from
`scripts/custom_agent_tasks/saucedemo_full_checkout.py`):

1. Login as standard_user
2. Sort by Price low→high
3. Add third-cheapest item
4. Add Sauce Labs Backpack
5. Open cart
6. Remove the item from step 3 in the cart
7. Fill checkout form (Test/User/94000), click Continue
8. Verify item total $29.99 on overview
9. Click Finish and reach "Thank you for your order!"

**Strict scoring:** count consecutive checkpoints from CP1; first break
ends counting.
**Lenient scoring:** count any checkpoint reached at any frame, even if
the model returned to a prior page later.

Comparison:

| Model | Phase 14 (UI-Venus prompt) | Phase 15 (Holo3 native) | Notes |
|---|---|---|---|
| ui-venus-1.5-8b | 2/9 strict, 4/9 lenient | (n/a — keep UI-Venus path) | baseline |
| holo3-35b-a3b | (not tested; UI-Venus prompt would parse-error per Phase 14 sibling pattern) | TBD | this phase's deliverable |

A pass means: Holo3's strict score is **≥ 3/9** OR its lenient score is
**≥ 5/9**. Anything less than that, given the cited 10-15pp gap vs the
122B API model, suggests the open 35B is structurally insufficient for
this class of long-horizon task — independent of harness fit.

### Step 5 — Append findings entry

Add a `## 2026-04-29 — Phase 15: Holo3 native-harness eval` section to
`docs/findings.md` immediately before the `## Open questions for retro`
section. Match the structure of the Phase 13 / 14 entries:

- Setup (what was built, what's new about Holo3, why structured outputs over Hermes tool-calling)
- Result (Holo3 verified score, comparison to UI-Venus 8B baseline)
- Findings (in order of importance — include any structured-outputs-on-llama.cpp gotchas worth remembering)
- Verdict (Holo3 clears the bar / doesn't / needs a different harness shape)
- Caveats (n=1, viewport size, 10-15pp 35B-vs-122B gap)
- Operator-facing changes (the `HARNESS` env var, the `holo3-35b-a3b` registry entry, the new module)

Keep the entry self-contained — match the style of prior entries which can be read without the surrounding context.

## Acceptance criteria for the whole phase

1. `scripts/custom_agent.py` honors `HARNESS=uivenus` (default) and `HARNESS=holo3`. Both paths share the same dispatcher and instrumentation. Other harnesses (Hermes, browser-use-format, Holo) are out of scope; future phases.
2. Holo3-35B-A3B IQ3_XXS is in the swap registry, files pinned at `/mnt/data/models/holo3-35b-a3b/`, and serves on `vision-model.service` via `swap_model.sh`.
3. Holo3 R1 verified score produced. Artifacts archived under `/tmp/r1_artifacts/holo3-35b-a3b.holo3.{log,steps,final.png}`.
4. Phase 15 entry merged into `docs/findings.md`.
5. A clear go/no-go on Holo3: cleared the 3/9 strict bar (or 5/9 lenient) → invest more in this lineage; under the bar → log the finding and move on.

## Known risks / gotchas

- **Structured-outputs path on llama-server: confirmed.** `response_format={"type":"json_schema","json_schema":{"name":...,"schema":...,"strict":true}}` works (probed live during planning). `extra_body={"structured_outputs":...}` is silently ignored — vLLM-only. Use `response_format`. GBNF grammar fallback is unneeded.
- **Schema iteration may be necessary.** The discriminated-union shape might need tweaks based on what Holo3 actually emits. If the model produces structurally-valid JSON but the wrong action variant for a given screenshot (e.g. `wait` when a click is clearly needed), that's model capability, not schema shape. Don't keep iterating the schema to "fix" model judgment.
- **35B retries the same action without reasoning** (per Sean's note — documented Holo3-35B-vs-122B gap). The Phase 14 stuck-loop early-out (5 consecutive no-effect → exit) already catches this. If Holo3 hits stuck_loop on every run, that's the documented capability gap surfacing — log and move on; don't try to engineer around a model-level limitation.
- **Holo3's chat template raises if no user message** — confirmed at `https://huggingface.co/Hcompany/Holo3-35B-A3B/resolve/main/chat_template.jinja`. Always include a user-role message in the request.
- **`<think>` and strict `response_format` conflict at sampling time.** Disable thinking via `--chat-template-kwargs '{"enable_thinking":false}'` on the unit. Reasoning is captured in the schema's top-level `thought` field instead — this is the surfer-h-cli design pattern, not a workaround.
- **VRAM headroom on Holo3 is tight.** If `--cache-type-k q8_0` becomes necessary, plumb it through `swap_model.sh` (the script currently sets KV cache as f16). Phase 13's 30B-A3Bs at 14GB worked without quantized KV; 13.62GB IQ3_XXS should be OK but watch for OOM on first server start.
- **Independent verification screenshots are mandatory.** Agent self-reports cannot be trusted (Phase 14 finding 5: model confabulated 14 steps of "checkout complete" against a frozen inventory page). The custom_agent.py final screenshot at `/tmp/custom_agent_final.png` is ground truth; archive it per-run.
- **Holo3 is downloaded fresh, no prior validation.** First R1 run is also the model's first real test on this system. If output is gibberish, suspect either: (a) chat template mismatch — read `chat_template.jinja` from the source repo and confirm llama-server is using it (`--jinja` flag is already in the unit file), or (b) mmproj mismatch — both LLM and mmproj must come from compatible builds (mradermacher's mmproj-Q8_0 from the non-i1 repo is meant to pair with the i1 LLM quants per the repo README convention; verify if behavior is off).
- **Localization on Holo3 follows the Holo1.5 modern path** (structured `ClickAbsoluteAction` + 1000×500 resize). Hcompany has not yet wired Holo3 into surfer-h-cli's source; if the hai-cookbook later prescribes a different localization contract for Holo3 specifically, switch to that. Default is fine for v0.
- **`--image-min-tokens 1024`** is set in the current unit. Surfer-h-cli's smart_resize uses `min_pixels=56*56=3136` on the client side. The server-side `image-min-tokens` may further constrain; probably benign, but if Holo3 emits weird tile artifacts, try removing or lowering it.
- **Saucedemo `<select>` (price-sort, CP2)** is handled at the dispatcher level, not the schema. The model emits `click_element` then `write_element` with a single-letter content; the existing per-key `_type_keys` triggers native option-jump. No schema extension needed.

## Files of interest (cheat sheet)

```
scripts/custom_agent.py                               # run loop; needs HARNESS env handling
scripts/custom_agent/model.py                         # UI-Venus prompt + parser (don't touch)
scripts/custom_agent/actions.py                       # CDP dispatcher; reused by both paths
scripts/custom_agent/browser.py                       # Chrome launcher; don't touch
scripts/custom_agent/holo3.py                         # NEW: this phase creates it
scripts/custom_agent/test_parse_holo3.py              # NEW: parser unit test
scripts/custom_agent_tasks/saucedemo_full_checkout.py # the R1 task (verbatim from Phase 14)
scripts/swap_model.sh                                 # model registry; needs holo3 entry
docs/findings.md                                      # append Phase 15 entry
docs/backlog.md                                       # for context only
```

External references to clone/read before step 1:

```
github.com/hcompai/surfer-h-cli        # canonical agent loop; has the prompts and schema
github.com/hcompai/hai-cookbook        # quickstart notebooks with schema definitions
huggingface.co/Hcompany/Holo3-35B-A3B  # chat_template.jinja; model card
```

## Estimated effort

- Step 1 (Holo3 harness module + tests): 2–3 hours (down from 3–4 — surfer-h-cli is cloned at `/tmp/surfer-h-cli`, prompts/schemas already pasted into this plan, llama-server compatibility already verified)
- Step 2 (Holo3 download + register + smoke): 30 min (mostly download)
- Step 3 (Holo3 R1 run): 5–10 min
- Step 4 (scoring): 30 min
- Step 5 (findings entry): 30 min
- **Total: ~4–5 hours.**

## Decision log

- Holo3 quant **IQ3_XXS i1** (13.62GB) over Q3_K_M (16.76GB, OOM risk) and Q2_K (12.94GB, lossier than imatrix-IQ3 at similar size). Confirmed by Sean.
- **Phase 15 scope contracted to Holo3 only** after Sean's clarification that "Hermes for everyone" is the wrong framing. Holo2 / MAI-UI / bu-30b each need their own native harness in their own phase if Holo3's outcome warrants the investment.
- **Schema source: surfer-h-cli verbatim** (`navigation_models.py`, `localization_1_5.py`). Pasted into the "Resolved during planning probe" section above.
- **Two-pass mandatory.** Surfer-h-cli's navigator never emits real coordinates — `click_element` carries a `element: <text desc>` description; the localization pass fills in x/y. Single-pass isn't a viable v0 for this stack.
- **NAV_GUIDELINES adapted: drop the "Never try to login" line** so saucedemo CP1 isn't blocked. Everything else verbatim.
- **Native `<think>` disabled at the chat template level** (`enable_thinking=false`). Reasoning lives in the schema's `thought` field — same model behavior, compatible with strict `response_format`.
- **Validation pass deferred.** Single-model eval; surfer-h-cli's optional answer-validator is not used.
- **`<select>` handling is dispatcher-only.** Model emits `click_element` then `write_element` with a single letter; existing per-key keydown triggers native letter-jump. No schema variant needed.
- `bu-30b-a3b-preview`, `holo1.5-7b`, `mai-ui-8b`, and `holo2-30b-a3b` are **out of scope** for Phase 15. Each gets its own follow-up phase only if Holo3 clears the bar.
- This phase is **eval-only**. Nothing here gets productionalized; harnesses are minimum-viable rigs to score R1.
