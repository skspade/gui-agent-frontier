# MAI-UI-8B evaluation against UI-Venus-1.5-8B

Date: 2026-04-29

## Goal

Stand up MAI-UI-8B (Tongyi-MAI, Qwen3-VL-based) as a swappable alternative to
the current UI-Venus-1.5-8B baseline, run the existing browser-use smokes
against it, and decide whether it deserves promotion to default.

## Why MAI-UI-8B

- Same base architecture as UI-Venus (Qwen3-VL) — current llama.cpp Vulkan
  build runs it without changes.
- Tongyi-MAI claim #1 in the 8B class on the ScreenSpot-Pro leaderboard
  (65.7% vs UI-Venus 1.5's reported 68.4%; close enough that real-world
  smokes will be more informative than benchmark numbers).
- GGUF + mmproj available on HuggingFace (mradermacher/MAI-UI-8B-GGUF).

## Constraints

- 16 GB VRAM (AMD 9070 XT). Q6_K + f16 mmproj + 32K KV ≈ 13.5 GB — only one
  model at a time, must swap.
- 49 GB free disk; download is ~7.9 GB. Tight but fits.
- Same inference endpoint (`localhost:8080/v1/...`) so browser-use config
  stays identical.

## Design

### File layout

```
~/models/
├── ui-venus-1.5-8b/                                       (existing)
└── mai-ui-8b/                                             (new)
    ├── mai-ui-8b-Q6_K.gguf                                (~6.7 GB)
    └── mmproj-mai-ui-8b-f16.gguf                          (~1.2 GB)
```

Filename normalization: HF ships these as `MAI-UI-8B.Q6_K.gguf` and
`MAI-UI-8B.mmproj-f16.gguf`. Renaming on disk to lowercase / hyphenated
matches the UI-Venus convention and lets `swap_model.sh` treat both models
uniformly.

### systemd

Rename `/etc/systemd/system/ui-venus.service` → `vision-model.service`.
The unit is no longer model-specific; `swap_model.sh` rewrites the gguf
paths, the `Description=`, and the `--alias` per active model.

### scripts/swap_model.sh

```
sudo bash scripts/swap_model.sh <model-name> [quant]
```

- Hardcoded registry of two models: `ui-venus-1.5-8b`, `mai-ui-8b`.
- Default quant per model: `Q6_K`.
- For each model, registry holds: dir, gguf basename pattern, mmproj
  filename, alias, description.
- Edits the unit, `daemon-reload`, restarts `vision-model.service`, polls
  `/health` for up to 30s.

### scripts/swap_quant.sh (deprecated alias)

Replaced with a one-line delegator that forwards to swap_model.sh with
`ui-venus-1.5-8b` hardcoded — preserves muscle memory and doc references.

## Verification

1. `excalidraw_drag` + `excalidraw_toolbar` smokes against MAI-UI Q6_K.
2. Capture `/tmp/smoke_final.png` for each (visual ground truth — agent
   self-reports cannot be trusted, per findings.md).
3. Append a phase to `docs/findings.md` with: setup notes, VRAM/timing
   observations, smoke outcomes, side-by-side verdict vs Venus.
4. Update `CLAUDE.md`:
   - Service name `ui-venus.service` → `vision-model.service`.
   - Document the two-model registry + `swap_model.sh` command.

## Out of scope

- Additional quants (Q4_K_M, Q5_K_M) — only if Q6_K is interesting enough
  to merit a quant ladder.
- Auto-downloader inside the script — manual `curl` once per model is fine.
- browser-use ChatOpenAI config changes — `--alias` keeps the call identical.
- Promoting MAI-UI to default (separate decision after smoke results).
