# vision-model

## Goal

Map the **Pareto frontier of (task class, harness sophistication, model
size)** for local GUI grounding agents. The question is not "is local
8B good enough?" but:

> For task class X, what is the minimum (model size, harness
> sophistication) that achieves Y% reliability at Z× lower cost than a
> frontier API model?

Different task classes — known-site DOM short-horizon (A), known-site
DOM long-horizon with grounding pinches (B), visual-grounding-required
(C), novel real-world e-commerce (D) — sit on different parts of the
frontier. The contribution is identifying *where the cliffs are* — for
example, whether class C is parameter-bound or harness-bound, or
whether overlay-handling on class D collapses the spread between
models.

**Read `docs/thesis.md` first** for the framing (task classes, harness
axes, cost model, currently-known frontier, cliff hypotheses).

## Concrete state and history

The stack is the apparatus for filling cells on the frontier:
`inclusionAI/UI-Venus-1.5-8B` (and friends — see Models below) served
by llama.cpp on Vulkan, exercised by `browser-use` for richly-DOM'd
pages and a custom CDP agent (`scripts/custom_agent.py`) for canvas /
grounding-heavy work.

- Detailed history (every smoke test, every fix, every dead end) lives
  in `docs/findings.md`. Read the relevant phase before designing a
  new test or changing the stack — most of the gotchas have already
  been hit and documented.
- Concrete next-up work is in `docs/backlog.md`, organized as
  cell-fills `[class=…, H=…, model=…]` plus tactical items. Each item
  is hand-offable with steps, file paths, and acceptance criteria.
- Smoke / task modules carry a `TASK_CLASS` constant ("A" / "B" / "C"
  / "D") matching the taxonomy in `docs/thesis.md`.

## Inference server

- **Service**: `vision-model.service` (systemd, runs as user `seans`).
  Renamed from `ui-venus.service` in Phase 12 — the unit is no longer
  model-specific, it just runs whatever the active swap target is.
- **Endpoint**: `http://localhost:8080/v1/...` (OpenAI-compatible) and
  `http://192.168.0.159:8080/v1/...` from LAN
- **Default model**: `ui-venus-1.5-8b` at Q6_K. MAI-UI-8B was evaluated in
  Phase 12 and rejected as default (regression on visual grounding); its
  weights stay on disk for re-test. Phase 13 evaluated four 30B-A3B-class
  candidates — none cleared the rubric. Holo1.5-7B and Holo2-30B-A3B were
  retired from the active registry on 2026-04-30 (Holo3-35B-A3B is the
  H-Company family entry going forward); their weights remain on disk.
- **Context**: 32K. Browser-use prompts with screenshots eat ~17K, so 16K is
  too small. 32K fits comfortably in 16GB VRAM with Q6_K + f16 mmproj +
  f16 KV.
- **Swap models / quants**: `sudo bash scripts/swap_model.sh <model> [quant]`.
  Models in the registry: `ui-venus-1.5-8b`, `mai-ui-8b`,
  `ui-venus-1.5-30b-a3b`, `bu-30b-a3b-preview`, `holo3-35b-a3b`. The
  30B-A3B / Holo3 entries live on `/mnt/data/models/`; the 8B entries
  stay on `/home/seans/models/`. Script rewrites the unit,
  daemon-reloads, restarts, and waits for `/health`. Passwordless sudoers
  entry at `/etc/sudoers.d/vision-model-swap` lets `seans` run
  `swap_model.sh` without a password — required for autonomous
  swap-during-run flows. Legacy `swap_quant.sh ARG` still works as a
  thin delegator that fixes the model to `ui-venus-1.5-8b`.
- **Model files**:
  - `~/models/ui-venus-1.5-8b/`
    - `ui-venus-1.5-8b-Q4_K_M.gguf` (5.0G)
    - `ui-venus-1.5-8b-Q5_K_M.gguf` (5.9G)
    - `ui-venus-1.5-8b-Q6_K.gguf` (6.7G) — default
    - `mmproj-ui-venus-1.5-8b-f16.gguf` (1.2G — vision encoder, always f16)
  - `~/models/mai-ui-8b/`
    - `mai-ui-8b-Q6_K.gguf` (6.7G)
    - `mmproj-mai-ui-8b-f16.gguf` (1.2G)
  - `/mnt/data/models/ui-venus-1.5-30b-a3b/` (Phase 13 — Q3_K_M, ~14GB)
  - `/mnt/data/models/bu-30b-a3b-preview/` (Phase 13 — Q3_K_M, ~14GB)
  - `/mnt/data/models/holo3-35b-a3b/` (Phase 15 — IQ3_XXS, ~14GB)
  - `/mnt/data/models/holo2-30b-a3b/` (Phase 13 — Q3_K_M, ~14GB; retired
    from registry 2026-04-30, weights kept)
  - `/mnt/data/models/holo1.5-7b/` (Phase 13 — Q6_K, ~6GB; retired from
    registry 2026-04-30, weights kept)

## Thunder cloud (alternate inference path)

When the local 16 GB VRAM ceiling is the binding constraint (parameter-cliff
probes into 30B/70B), `llama-server` runs on a Thunder Compute GPU instead.
**Browser-use stays local**; an SSH tunnel (`localhost:8080` ←
`thunder:8080`) makes the smoke runner agnostic — `smoke_browser_use.py`
needs no changes and `MODEL=<alias>` still parameterizes which remote model
it talks to.

- **Harness**: `scripts/thunder/`
  - `bootstrap_instance.sh` — one-shot setup on a fresh instance (apt +
    llama.cpp CUDA build + GGUF downloads). Idempotent; safe to interrupt
    and resume. `SKIP_72B=1` skips the 47 GB Qwen pull.
  - `swap_model_remote.sh <ssh_alias> <model> [quant]` — remote analogue of
    `scripts/swap_model.sh`. Writes a wrapper script then (re)starts in a
    fixed `llamasrv` tmux session; polls `/health` over SSH up to 180 s.
    Per-model quant defaults mirror the local F-7 fix.
  - `sweep.py --ssh <alias> --task <smoke>` — orchestrator. Pre-flight
    refuses if local 8080 is occupied. Per cell: swap → tunnel → smoke →
    archive `swap.log` + `smoke.log` + `final.png` to
    `data/sweeps/<run_id>/<model>_<quant>/`. Drops `summary.json`.
  - `validate_harness.py` — pre-sweep sanity check. Drives one synthetic
    step through the configured harness against whatever model is
    currently loaded, prints the parsed Action, exits non-zero on parse
    error or coord-space mismatch. **Run this after every swap before
    starting a multi-cell sweep** — Phase 21 wasted ~$0.50 of A100 time
    on three iterations because we shipped a new harness without dry-run
    verification.
- **Default GPU class**: `a100xl_x1_prototyping`, 8 vCPU, 150 GB persistent
  disk, template `cuda12-9`. ~$1.10/hr → ~$1.65–$2.20 per full-ladder
  sweep including bootstrap. A6000 ($0.35/hr) OOMs Qwen-72B Q4_K_M (47 GB
  weights, 48 GB VRAM); H100 typically `unavailable` in the prototyping
  pool. Live cost/spec decisions live in
  `docs/plans/*-thunder-cloud-handoff.md`.
- **Provisioning gotchas** (from the 2026-04-30 first-run):
  - `template=base` ships PyTorch's CUDA *runtime* only — `nvcc` is
    missing. Use `cuda12-9` for the full toolkit. Even on cuda12-9, `nvcc`
    is not on `ubuntu`'s default PATH; bootstrap auto-prepends
    `/usr/local/cuda/bin`.
  - **SSH user is `ubuntu`, not `root`.** The MCP's `get_ssh_command`
    returns `root@…` (that's `tnr connect`'s per-instance key flow).
    Org-level keys registered via `create_ssh_key` and passed as
    `ssh_key_name` to `create_instance` land in
    `/home/ubuntu/.ssh/authorized_keys`.
- **Provisioning + teardown stay user-confirmable** under auto mode —
  billing starts at RUNNING and no auto-teardown is wired into `sweep.py`.
  After a sweep, restart the local service: `sudo systemctl start
  vision-model.service`.
- **Snapshot-then-delete is the default teardown.** Snapshot storage runs
  ~$0.18/day for a 106 GB disk; restore takes ~8.5 min vs ~30 min to
  re-bootstrap from scratch. `create_snapshot` requires the **UUID**, not
  the integer instance_id (MCP tool description is wrong about this) —
  see memory `feedback_thunder_snapshot_uuid.md`. Delete the snapshot
  with `delete_snapshot` once you're sure no follow-up sweep is coming.
- **Measured per-step latencies** (Phase 20/21, A100 80GB, Q4_K_M-ish
  quants — use these for cost estimates, don't extrapolate from probe-
  warmup throughput numbers):
  - Cold-start (first request after a swap): ~50 s for kernel JIT +
    CUDA graph warmup, regardless of model size.
  - Holo3-35B-A3B IQ3_XXS warm: ~90 tok/s prompt, ~79 tok/s gen.
  - Cart-task step on Qwen-72B Q4_K_M (screenshot + scroll-probe + 32K
    context): **~10–15 s/step** end-to-end. `bestbuy_airpods` at
    `MAX_STEPS=60` took 12.8 min wall-clock.
  - Swap latency, cold disk: 100 s (14 GB Holo3 IQ3_XXS) → 300+ s (47 GB
    Qwen-72B). Warm OS page cache: ~44 s for the same Qwen-72B.
- **When `swap_model_remote.sh` reports timeout**, tail
  `ssh thunder 'tail -40 /tmp/llama.log'` *first* before retrying. The
  failure mode might be "still loading past the ceiling" (just bump the
  timeout or wait) vs "cudaMalloc failed: out of memory" (real OOM, often
  fragmentation from a prior model — wait for nvidia-smi to show clean
  state, then retry). Don't redo the swap blind.

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
  `DEFAULT_SMOKE`. The runner reads `MODEL=<alias>` from the environment
  (default `ui-venus-1.5-8b`); set it to match whatever the
  `vision-model.service` is currently serving (e.g. `MODEL=mai-ui-8b ...`
  after `swap_model.sh mai-ui-8b`).

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
