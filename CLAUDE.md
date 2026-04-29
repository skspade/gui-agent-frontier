# vision-model

Local deployment + agent-stack experimentation around `inclusionAI/UI-Venus-1.5-8B`,
a Qwen3-VL-based GUI grounding model. Served by llama.cpp on Vulkan,
exercised by `browser-use` for browser automation.

Detailed history (every smoke test, every fix, every dead end) lives in
`docs/findings.md`. Read that before designing a new test or changing the
stack — most of the gotchas have already been hit and documented.

Concrete next-up work is in `docs/backlog.md` — each item is hand-offable
with steps, file paths, and acceptance criteria. Pick from there if you're
looking for "what to do next."

## Inference server

- **Service**: `ui-venus.service` (systemd, runs as user `seans`)
- **Endpoint**: `http://localhost:8080/v1/...` (OpenAI-compatible) and
  `http://192.168.0.159:8080/v1/...` from LAN
- **Default quant**: Q6_K. (Q4_K_M was the original deploy; Q6_K won the A/B
  on visual icon ID at no measurable speed cost. See findings phase 3.)
- **Context**: 32K. Browser-use prompts with screenshots eat ~17K, so 16K is
  too small. 32K fits comfortably in 16GB VRAM with Q6_K + f16 mmproj +
  f16 KV.
- **Swap quants**: `sudo bash scripts/swap_quant.sh <Q4_K_M|Q5_K_M|Q6_K|f16>`.
  The script restarts the service and waits for `/health` to come back. The
  mmproj only exists in f16; the script always restores that line.
- **Model files**: `~/models/ui-venus-1.5-8b/`
  - `ui-venus-1.5-8b-Q4_K_M.gguf` (4.7G)
  - `ui-venus-1.5-8b-Q5_K_M.gguf` (5.5G)
  - `ui-venus-1.5-8b-Q6_K.gguf` (6.3G) — default
  - `ui-venus-1.5-8b-f16.gguf` (16G — re-quantize source, can be deleted if disk pressure)
  - `mmproj-ui-venus-1.5-8b-f16.gguf` (1.2G — vision encoder, always f16)

## Browser-use smoke tests

`scripts/smoke_browser_use.py` is the runner; each smoke payload (TASK +
per-test config) lives as its own file in `scripts/smokes/`. **Don't edit
existing smoke payloads in place** — copy to a new file under `smokes/`
and run that, so the history of probes stays intact and referenceable.

A smoke module exposes module-level constants: `TASK` (required),
`MAX_STEPS`, `HEADLESS`, `MAX_ACTIONS_PER_STEP`, `EXTEND_SYSTEM_MESSAGE`
(all optional with defaults in the runner).

- **Run command** (always log to file, never pipe through `tail`):

  ```
  DISPLAY=:0 XAUTHORITY=/run/user/1000/xauth_rVYaGJ XDG_RUNTIME_DIR=/run/user/1000 \
    PYTHONUNBUFFERED=1 .venv/bin/python -u scripts/smoke_browser_use.py <smoke_name> \
    > /tmp/smoke.log 2>&1
  ```

  `<smoke_name>` matches a file in `scripts/smokes/` (e.g.
  `excalidraw_drag`, `excalidraw_toolbar`). Omitting it uses the runner's
  `DEFAULT_SMOKE`.

- **Headed mode (default)** is required for any nontrivial site. Headless
  Chromium has CDP-click quirks on nested anchors (e.g. saucedemo cart icon
  loops forever in headless, works first try in headed).

- **Display env vars** for headed Chromium under Plasma+Wayland:
  - `DISPLAY=:0`
  - `XAUTHORITY=/run/user/1000/xauth_rVYaGJ`
  - `XDG_RUNTIME_DIR=/run/user/1000`

- **Chromium binary**: `/home/seans/.cache/ms-playwright/chromium-1208/chrome-linux64/chrome`
  (browser-use 0.12 speaks CDP via `cdp-use`; no Playwright runtime needed.)

- **ChatOpenAI config gotcha**: pass `dont_force_structured_output=False` so
  llama.cpp's grammar enforcement constrains output to valid JSON. Without
  it, the model emits `<think>...</think>` preambles that break browser-use's
  pydantic strict-JSON parse.

- **Verification screenshot**: the script captures `/tmp/smoke_final.png`
  after the run via CDP `Page.captureScreenshot`. **Always check it** —
  agent self-reports cannot be trusted (we caught a Google Maps confabulation
  this way).

## Operational rules learned the hard way

1. **Privileged operations: write to `/tmp/foo.sh`, invoke as
   `sudo bash /tmp/foo.sh ARG`.** Never inline-quote multi-step sudo commands —
   long chains hang on shell-quoting issues that look like password prompts.
2. **Long-running agent runs: redirect stdout to a file.** The harness
   wraps commands with `tail -200`, which buffers everything in memory until
   EOF. A working agent can look "stuck" for minutes when it's actually
   serving requests fine. Tail the log file separately to monitor.
3. **Independent verification screenshots are mandatory for visual tasks.**
   The agent will confidently report success that doesn't match the page
   state. The post-run CDP screenshot in `smoke_browser_use.py` is the
   ground truth.
4. **For tests that *should* exercise visual grounding, design out the easy
   path.** Browser-use will route around canvas/coord-clicks via DOM-indexed
   elements every time. If the success criterion is "the model identified
   something visually," explicitly forbid the search/DOM bypass.
5. **Prefer `send_keys` over `evaluate` for keyboard input.** Synthetic
   `KeyboardEvent` from page JS doesn't trigger trusted-input handlers (e.g.
   Excalidraw's Escape-to-dismiss). Real CDP keyboard events do.
6. **For agent honesty, hint in the task prompt.** "*If you cannot complete
   the task, report what blocked you rather than pretending to succeed.*"
   This single line moved the Home Depot run from a likely confabulation to
   a clean partial-completion report.

## Stack reference (for setup repro)

- CachyOS, AMD 9070 XT (gfx1201, RADV mesa)
- llama.cpp built with `-DGGML_VULKAN=ON -DLLAMA_CURL=ON`. Requires arch
  package `spirv-headers` — not pulled in transitively by `vulkan-radeon`.
- Python 3.14 in the system. llama.cpp's `requirements.txt` pins
  `torch~=2.6` and `numpy~=1.26` which have no 3.14 wheels — install
  conversion deps with relaxed pins (`torch>=2.9 numpy>=2.0
  transformers>=5.5.0 gguf protobuf accelerate safetensors sentencepiece
  tqdm` against `--extra-index-url https://download.pytorch.org/whl/cpu`).
- LAN-only firewall: `ufw allow from 192.168.0.0/24 to any port 8080`.
