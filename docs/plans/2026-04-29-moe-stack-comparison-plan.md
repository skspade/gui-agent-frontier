# MoE Stack Comparison Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Run a five-stack bake-off (S1 8B baseline, S2 UI-Venus-1.5-30B-A3B, S3 Holo2-30B-A3B, S4 bu-30b-a3b-preview, S5 split-design) against the existing smoke suite plus a new long-horizon saucedemo task, and declare a most-reliable-local winner.

**Architecture:** New 30B-A3B GGUFs live on `/mnt/data/models/` (578 GB free). `scripts/swap_model.sh` is extended with a per-entry `MODEL_DIR` so it can serve from either drive. A new long-horizon smoke (`saucedemo_full_checkout`) drives the existing `smoke_browser_use.py` runner with three discriminators baked in (ordinal-by-price, name-grounding, nested-anchor cart removal). Stack S4 uses browser-use's `ChatBrowserUse` adapter; S5 uses a new minimal split-router script. Results are scored with a long-horizon-weighted aggregate.

**Tech Stack:** llama.cpp (Vulkan) + GGUF Q3_K_M for 30B-A3B / Q6_K for 7B-8B; browser-use 0.12 + ChatOpenAI / ChatBrowserUse; Chromium via CDP; systemd `vision-model.service`; saucedemo as the long-horizon target.

---

## Reference: design doc

`docs/plans/2026-04-29-moe-stack-comparison-design.md` — read this first if context is missing. Findings background is in `docs/findings.md` (Phases 1–12).

## Reference: shared definitions

- **Project root**: `/home/seans/Source/vision-model`
- **Venv**: `/home/seans/Source/vision-model/.venv`
- **llama.cpp tree**: `/home/seans/llama.cpp`
- **Convert script**: `/home/seans/llama.cpp/convert_hf_to_gguf.py`
- **Quantize binary**: `/home/seans/llama.cpp/build/bin/llama-quantize`
- **systemd unit**: `/etc/systemd/system/vision-model.service`
- **Server**: `http://localhost:8080/v1/...`
- **New model root**: `/mnt/data/models/` (existing 8B models stay at `~/models/`)
- **Headed Chromium env**: `DISPLAY=:0 XAUTHORITY=/run/user/1000/xauth_rVYaGJ XDG_RUNTIME_DIR=/run/user/1000`
- **Run-with-log idiom**: never pipe long agent runs through `tail`. Always
  `> /tmp/<name>.log 2>&1` and tail the file from another shell.
- **Privileged ops idiom**: write to `/tmp/<name>.sh`, invoke as
  `sudo bash /tmp/<name>.sh ARG`. No inline-quoted multi-step sudo.

---

## Phase A — Harness setup (no GPU, fast)

### Task A1: Install `huggingface_hub` in the project venv

**Files:** none (venv state only)

**Step 1: Install**

```bash
cd /home/seans/Source/vision-model
.venv/bin/pip install -U huggingface_hub
```

**Step 2: Verify**

```bash
.venv/bin/python -c "from huggingface_hub import snapshot_download; print('ok')"
```

Expected: `ok`

**Step 3: Commit**

This is a venv change, not a repo change — nothing to commit. Skip.

---

### Task A2: Create `/mnt/data/models/` and reserve subdirectories

**Files:** none (filesystem state)

**Step 1: Create directories**

```bash
mkdir -p /mnt/data/models/{ui-venus-1.5-30b-a3b,holo2-30b-a3b,bu-30b-a3b-preview,holo1.5-7b}
ls /mnt/data/models/
```

Expected: four directories listed.

**Step 2: Confirm free space**

```bash
df -h /mnt/data
```

Expected: ≥500 GB available. (We need ≈ 80 GB peak per 30B-A3B during conversion; sequential, not concurrent.)

---

### Task A3: Refactor `swap_model.sh` to support per-entry `MODEL_DIR` and add new entries

**Files:**
- Modify: `/home/seans/Source/vision-model/scripts/swap_model.sh`

**Step 1: Read current state to confirm baseline**

Already read in plan-creation step. Current registry: `ui-venus-1.5-8b`, `mai-ui-8b`. Both hardcode `/home/seans/models/<model>`.

**Step 2: Replace the `case` block**

The cleanest change is to factor `MODEL_DIR` out of each case arm so different roots are supported. Replace lines 19–39 with:

```bash
case "$MODEL" in
    ui-venus-1.5-8b)
        MODEL_DIR=/home/seans/models/ui-venus-1.5-8b
        ALIAS=ui-venus-1.5-8b
        DESC="UI-Venus-1.5-8B llama.cpp server (Vulkan)"
        ;;
    mai-ui-8b)
        MODEL_DIR=/home/seans/models/mai-ui-8b
        ALIAS=mai-ui-8b
        DESC="MAI-UI-8B llama.cpp server (Vulkan)"
        ;;
    ui-venus-1.5-30b-a3b)
        MODEL_DIR=/mnt/data/models/ui-venus-1.5-30b-a3b
        ALIAS=ui-venus-1.5-30b-a3b
        DESC="UI-Venus-1.5-30B-A3B llama.cpp server (Vulkan)"
        ;;
    holo2-30b-a3b)
        MODEL_DIR=/mnt/data/models/holo2-30b-a3b
        ALIAS=holo2-30b-a3b
        DESC="Holo2-30B-A3B llama.cpp server (Vulkan)"
        ;;
    bu-30b-a3b-preview)
        MODEL_DIR=/mnt/data/models/bu-30b-a3b-preview
        ALIAS=bu-30b-a3b-preview
        DESC="bu-30b-a3b-preview llama.cpp server (Vulkan)"
        ;;
    holo1.5-7b)
        MODEL_DIR=/mnt/data/models/holo1.5-7b
        ALIAS=holo1.5-7b
        DESC="Holo1.5-7B llama.cpp server (Vulkan)"
        ;;
    *)
        echo "ERROR: unknown model '$MODEL'" >&2
        echo "models: ui-venus-1.5-8b, mai-ui-8b, ui-venus-1.5-30b-a3b, holo2-30b-a3b, bu-30b-a3b-preview, holo1.5-7b" >&2
        exit 1
        ;;
esac

GGUF="${MODEL_DIR}/${MODEL}-${QUANT}.gguf"
MMPROJ="${MODEL_DIR}/mmproj-${MODEL}-f16.gguf"
```

Also update the usage line (line 15) to list all six models, matching the error case.

**Step 3: Sanity-check the script (no actual swap)**

```bash
sudo bash /home/seans/Source/vision-model/scripts/swap_model.sh ui-venus-1.5-8b
```

Expected: model loads, `/health` ready, grep output at end shows `Description=UI-Venus-1.5-8B...`. The unmodified existing model should still serve identically.

**Step 4: Commit**

```bash
cd /home/seans/Source/vision-model
git add scripts/swap_model.sh
git commit -m "feat(swap): per-entry MODEL_DIR + 30B-A3B + holo registry stubs"
```

---

### Task A4: Create the long-horizon smoke `saucedemo_full_checkout.py`

**Files:**
- Create: `/home/seans/Source/vision-model/scripts/smokes/saucedemo_full_checkout.py`

**Step 1: Author the smoke module**

```python
"""
Long-horizon saucedemo flow for the 5-stack MoE bake-off.

Nine checkpoints, three discriminators (ordinal visual reasoning at step 4,
text grounding at step 5, nested-anchor cart manipulation at step 6).
Pass = "Thank you for your order!" page reached with the correct final
cart contents (Sauce Labs Backpack only). Partial-pass = highest
checkpoint number reached.

Use with `MAX_TOKENS=8192` env (matches Phase 12 decision for non-Venus
models with longer thinking blocks).

See docs/plans/2026-04-29-moe-stack-comparison-design.md.
"""

TASK = (
    "Open https://www.saucedemo.com and complete the following checkout flow. "
    "Treat the steps as a checklist; do them in order and verify each "
    "before moving on.\n"
    "1. Login with username 'standard_user' and password 'secret_sauce'.\n"
    "2. Sort the products by 'Price (low to high)' using the dropdown.\n"
    "3. After sorting, identify the THIRD CHEAPEST item (the third product "
    "from the left/top of the sorted grid) and add it to the cart.\n"
    "4. Then add the item literally named 'Sauce Labs Backpack' to the cart "
    "as well.\n"
    "5. Open the cart by clicking the cart icon in the top-right.\n"
    "6. In the cart, REMOVE the item that you added in step 3 (the "
    "third-cheapest one), so only Sauce Labs Backpack remains.\n"
    "7. Click 'Checkout', then fill First Name='Test', Last Name='User', "
    "Postal Code='94000'. Click 'Continue'.\n"
    "8. On the overview page, verify the item total matches Sauce Labs "
    "Backpack's price ($29.99). Report the displayed total in your final "
    "answer.\n"
    "9. Click 'Finish' and verify the page shows 'Thank you for your order!'. "
    "Report 'PASS' or 'FAIL' as the very first word of your final answer.\n"
    "If you cannot complete a step, report which step blocked you and why "
    "rather than pretending to succeed."
)

MAX_STEPS = 40
HEADLESS = False
MAX_ACTIONS_PER_STEP = 2
```

**Step 2: Smoke-test the module imports**

```bash
cd /home/seans/Source/vision-model
.venv/bin/python -c "from scripts.smokes import saucedemo_full_checkout as s; print(s.TASK[:80])"
```

Expected: prints first 80 chars of TASK.

**Step 3: Commit**

```bash
git add scripts/smokes/saucedemo_full_checkout.py
git commit -m "feat(smokes): saucedemo_full_checkout long-horizon task (9 checkpoints)"
```

---

## Phase B — Model deployments (one model per task; sequential)

Each task in this phase follows the same shape: download safetensors → convert to f16 GGUF → quantize → produce mmproj → delete f16 intermediate → register → verify health → grounding probe.

**Common idioms:**
- Always run multi-hour downloads in the background with logs.
- After each long step, `df -h /mnt/data` to confirm we haven't blown disk.
- `vision-model.service` runs as user `seans`; the model files must be readable by that user (default ownership when downloaded by `seans` is fine).

---

### Task B1: Deploy UI-Venus-1.5-30B-A3B at Q3_K_M

**Files:**
- Create: `/mnt/data/models/ui-venus-1.5-30b-a3b/ui-venus-1.5-30b-a3b-Q3_K_M.gguf`
- Create: `/mnt/data/models/ui-venus-1.5-30b-a3b/mmproj-ui-venus-1.5-30b-a3b-f16.gguf`

**Step 1: Download safetensors (background)**

```bash
cd /home/seans/Source/vision-model
mkdir -p /mnt/data/models/ui-venus-1.5-30b-a3b/hf
nohup .venv/bin/python -c "
from huggingface_hub import snapshot_download
snapshot_download('inclusionAI/UI-Venus-1.5-30B-A3B',
                  local_dir='/mnt/data/models/ui-venus-1.5-30b-a3b/hf')
print('DONE')
" > /tmp/dl_uiv30b.log 2>&1 &
echo "pid=$!"
```

Expected: PID printed; multi-hour wall-clock. Tail `/tmp/dl_uiv30b.log` from another shell.

**Step 2: Confirm download completed**

```bash
tail -5 /tmp/dl_uiv30b.log
ls -lh /mnt/data/models/ui-venus-1.5-30b-a3b/hf/ | head -20
df -h /mnt/data
```

Expected: `DONE` in log; ~60 GB of .safetensors files; disk still has ≥350 GB free.

**Step 3: Convert HF → f16 GGUF**

```bash
nohup /home/seans/Source/vision-model/.venv/bin/python \
    /home/seans/llama.cpp/convert_hf_to_gguf.py \
    /mnt/data/models/ui-venus-1.5-30b-a3b/hf \
    --outfile /mnt/data/models/ui-venus-1.5-30b-a3b/ui-venus-1.5-30b-a3b-f16.gguf \
    --outtype f16 \
    > /tmp/conv_uiv30b.log 2>&1 &
echo "pid=$!"
```

Expected: ≈30 min runtime; produces ~60 GB f16 GGUF. Watch for "mmproj" output in the log — Qwen3-VL conversions emit a separate `mmproj-*.gguf` automatically.

**Step 4: Confirm conversion**

```bash
tail -20 /tmp/conv_uiv30b.log
ls -lh /mnt/data/models/ui-venus-1.5-30b-a3b/*.gguf
```

Expected: f16 GGUF and mmproj-f16 GGUF both present. If the mmproj filename is not `mmproj-ui-venus-1.5-30b-a3b-f16.gguf`, rename it to match (the swap script expects this exact pattern).

**Step 5: Quantize to Q3_K_M**

```bash
nohup /home/seans/llama.cpp/build/bin/llama-quantize \
    /mnt/data/models/ui-venus-1.5-30b-a3b/ui-venus-1.5-30b-a3b-f16.gguf \
    /mnt/data/models/ui-venus-1.5-30b-a3b/ui-venus-1.5-30b-a3b-Q3_K_M.gguf \
    Q3_K_M \
    > /tmp/quant_uiv30b.log 2>&1 &
echo "pid=$!"
```

Expected: ≈10 min; produces ~13 GB Q3_K_M GGUF.

**Step 6: Free disk by removing the f16 intermediate**

```bash
ls -lh /mnt/data/models/ui-venus-1.5-30b-a3b/
rm /mnt/data/models/ui-venus-1.5-30b-a3b/ui-venus-1.5-30b-a3b-f16.gguf
df -h /mnt/data
```

Keep the HF safetensors directory for now — only delete it after all four conversions succeed (in case re-quantizing is needed later).

**Step 7: Swap to the new model and verify health**

```bash
sudo bash /home/seans/Source/vision-model/scripts/swap_model.sh ui-venus-1.5-30b-a3b Q3_K_M
```

Expected: `ready after Ns on ui-venus-1.5-30b-a3b Q3_K_M`. If VRAM-OOM at server start (look at `journalctl -u vision-model -n 50`), document this and follow the fallback in step 7a.

**Step 7a (only if step 7 OOMs):** Reduce context to 16K and add Q8 KV. Edit the unit (`sudo systemctl edit --full vision-model.service`) and change `-c 32768` → `-c 16384` and add `--cache-type-k q8_0 --cache-type-v q8_0`. `daemon-reload` and `restart`. Document this deviation in findings.

**Step 8: Grounding probe**

```bash
cd /home/seans/Source/vision-model
DISPLAY=:0 XAUTHORITY=/run/user/1000/xauth_rVYaGJ XDG_RUNTIME_DIR=/run/user/1000 \
    MODEL=ui-venus-1.5-30b-a3b \
    .venv/bin/python scripts/coord_remap_demo.py \
    /tmp/smoke_final.png \
    "the rectangle drawn on the canvas"
```

Expected: returns coords within ~10 px of the 8B baseline `(466, 460)`. (Use the most recent existing `/tmp/smoke_final.png` — generate one first with the 8B if missing.)

If `/tmp/smoke_final.png` doesn't exist, generate it first with:

```bash
sudo bash /home/seans/Source/vision-model/scripts/swap_model.sh ui-venus-1.5-8b
DISPLAY=:0 XAUTHORITY=/run/user/1000/xauth_rVYaGJ XDG_RUNTIME_DIR=/run/user/1000 \
    PYTHONUNBUFFERED=1 .venv/bin/python -u scripts/smoke_browser_use.py excalidraw_drag \
    > /tmp/smoke_warmup.log 2>&1
sudo bash /home/seans/Source/vision-model/scripts/swap_model.sh ui-venus-1.5-30b-a3b Q3_K_M
```

**Step 9: Note any quirks in a scratch file**

```bash
cat >> /tmp/bake_off_notes.md <<'EOF'
## B1: UI-Venus-1.5-30B-A3B
- Quant: Q3_K_M
- VRAM behavior: <fill in: did 32K ctx fit? Q8 KV needed?>
- Grounding probe coord: <fill in>
- Time-to-deploy: <fill in>
EOF
```

**Step 10: Commit notes only (model files are gitignored / unmanaged)**

No repo files changed. Move to B2.

---

### Task B2: Deploy Holo2-30B-A3B at Q3_K_M

**Files:**
- Create: `/mnt/data/models/holo2-30b-a3b/holo2-30b-a3b-Q3_K_M.gguf`
- Create: `/mnt/data/models/holo2-30b-a3b/mmproj-holo2-30b-a3b-f16.gguf`

**Step 1: Check for an existing Q3/Q4 GGUF on HuggingFace before downloading raw weights**

```bash
.venv/bin/python -c "
from huggingface_hub import HfApi
api = HfApi()
for m in api.list_models(search='Holo2-30B-A3B', author=None, limit=10):
    print(m.id)
"
```

Expected: candidates like `Hcompany/Holo2-30B-A3B`, possibly `bartowski/...` or `unsloth/...` GGUF mirrors. **If a pre-built Q3_K_M GGUF + mmproj exists, skip steps 2–6 and download the GGUF directly into `/mnt/data/models/holo2-30b-a3b/`.** Document which path was taken in `/tmp/bake_off_notes.md`.

**Step 2–6: Same as B1 steps 1–6, substituting model id `Hcompany/Holo2-30B-A3B` and paths `/mnt/data/models/holo2-30b-a3b/`.**

**Step 7: Swap and verify health**

```bash
sudo bash /home/seans/Source/vision-model/scripts/swap_model.sh holo2-30b-a3b Q3_K_M
```

**Step 8: Grounding probe** (same shape as B1 step 8, with `MODEL=holo2-30b-a3b`).

**Step 9: Note quirks in `/tmp/bake_off_notes.md` under `## B2`.**

---

### Task B3: Deploy bu-30b-a3b-preview at Q3_K_M

**Files:**
- Create: `/mnt/data/models/bu-30b-a3b-preview/bu-30b-a3b-preview-Q3_K_M.gguf`
- Create: `/mnt/data/models/bu-30b-a3b-preview/mmproj-bu-30b-a3b-preview-f16.gguf`

**Step 1: Check for community GGUF first**

```bash
.venv/bin/python -c "
from huggingface_hub import HfApi
api = HfApi()
for m in api.list_models(search='bu-30b-a3b', limit=10):
    print(m.id)
"
```

Expected: `browser-use/bu-30b-a3b-preview` (safetensors) and possibly community GGUF mirrors (e.g. `cyankiwi/...` AWQ — skip, AMD-AWQ is unstable per design doc). If a Q3_K_M GGUF exists from a known-good quantizer, use it.

**Step 2–6: Same as B1, substituting `browser-use/bu-30b-a3b-preview`.**

**Step 7: Swap and verify health**

```bash
sudo bash /home/seans/Source/vision-model/scripts/swap_model.sh bu-30b-a3b-preview Q3_K_M
```

**Step 8: Grounding probe** (same shape, `MODEL=bu-30b-a3b-preview`).

**Step 9: Note quirks in `/tmp/bake_off_notes.md` under `## B3`.**

---

### Task B4: Deploy Holo1.5-7B at Q6_K

**Files:**
- Create: `/mnt/data/models/holo1.5-7b/holo1.5-7b-Q6_K.gguf`
- Create: `/mnt/data/models/holo1.5-7b/mmproj-holo1.5-7b-f16.gguf`

**Step 1: Pull pre-built GGUF if available**

7B Holo models are widely re-quantized; almost certainly a Q6_K GGUF + mmproj already exists on HF (e.g. `bartowski/Hcompany_Holo1.5-7B-GGUF` or similar). Search:

```bash
.venv/bin/python -c "
from huggingface_hub import HfApi
api = HfApi()
for m in api.list_models(search='Holo1.5-7B', limit=15):
    print(m.id)
"
```

If found, download directly:

```bash
.venv/bin/python -c "
from huggingface_hub import hf_hub_download
hf_hub_download('<repo>', filename='<Q6_K filename>',
                local_dir='/mnt/data/models/holo1.5-7b')
hf_hub_download('<repo>', filename='<mmproj f16 filename>',
                local_dir='/mnt/data/models/holo1.5-7b')
"
```

Otherwise, fall back to safetensors-then-convert (B1 steps 2–6 path).

**Step 2: Rename to canonical pattern**

The swap script expects `holo1.5-7b-Q6_K.gguf` and `mmproj-holo1.5-7b-f16.gguf`. Rename if HF filenames differ.

**Step 3: Swap and verify health**

```bash
sudo bash /home/seans/Source/vision-model/scripts/swap_model.sh holo1.5-7b Q6_K
```

**Step 4: Grounding probe** (same shape, `MODEL=holo1.5-7b`).

---

### Task B5: Free disk

After all four B-tasks pass their grounding probes:

```bash
rm -rf /mnt/data/models/ui-venus-1.5-30b-a3b/hf
rm -rf /mnt/data/models/holo2-30b-a3b/hf
rm -rf /mnt/data/models/bu-30b-a3b-preview/hf
rm -rf /mnt/data/models/holo1.5-7b/hf 2>/dev/null || true
df -h /mnt/data
```

Expected: ≈220 GB recovered (3 × ~60 GB safetensors + various). Final state: only the Q3 GGUFs and f16 mmprojs remain per model.

---

## Phase C — Bake-off runs (S1–S4)

Each task in this phase has the same shape: swap to the model, run the four-task suite (`excalidraw_drag`, `excalidraw_toolbar`, `saucedemo_headed`, `saucedemo_full_checkout`), capture screenshots and logs, record scores. The long-horizon `saucedemo_full_checkout` task is run **n=3**; the others n=1.

**Shared run commands:**

```bash
# Single smoke run (n=1):
DISPLAY=:0 XAUTHORITY=/run/user/1000/xauth_rVYaGJ XDG_RUNTIME_DIR=/run/user/1000 \
    PYTHONUNBUFFERED=1 MODEL=<model_alias> MAX_TOKENS=8192 \
    .venv/bin/python -u scripts/smoke_browser_use.py <smoke_name> \
    > /tmp/<stack>_<smoke>.log 2>&1
cp /tmp/smoke_final.png /tmp/<stack>_<smoke>_final.png
```

**Scoring, captured per run:**
- For smokes: `pass | partial | fail` + step count (visible from log line "Step N").
- For long-horizon: highest checkpoint reached (1–9), final-answer prefix (`PASS`/`FAIL`), step count, recovery loops triggered (count of repeated identical actions in the log).

**Score-recording template:** append a row per run to `/tmp/bake_off_results.md`:

```
| stack | smoke | run | result | steps | notes |
|-------|-------|-----|--------|-------|-------|
| S1    | drag  | 1   | pass   | 4     | -     |
```

---

### Task C1: Run S1 (UI-Venus-1.5-8B baseline)

**Step 1: Swap**

```bash
sudo bash /home/seans/Source/vision-model/scripts/swap_model.sh ui-venus-1.5-8b
```

**Step 2: Run the three regression smokes (n=1 each)**

```bash
cd /home/seans/Source/vision-model
for s in excalidraw_drag excalidraw_toolbar saucedemo_headed; do
    DISPLAY=:0 XAUTHORITY=/run/user/1000/xauth_rVYaGJ XDG_RUNTIME_DIR=/run/user/1000 \
        PYTHONUNBUFFERED=1 MODEL=ui-venus-1.5-8b MAX_TOKENS=8192 \
        .venv/bin/python -u scripts/smoke_browser_use.py $s \
        > /tmp/S1_$s.log 2>&1
    cp /tmp/smoke_final.png /tmp/S1_${s}_final.png
done
```

Expected wall-clock: ~5–15 min total. Watch each log finish before starting the next (the loop is sequential — fine).

**Step 3: Run long-horizon (n=3)**

```bash
for run in 1 2 3; do
    DISPLAY=:0 XAUTHORITY=/run/user/1000/xauth_rVYaGJ XDG_RUNTIME_DIR=/run/user/1000 \
        PYTHONUNBUFFERED=1 MODEL=ui-venus-1.5-8b MAX_TOKENS=8192 \
        .venv/bin/python -u scripts/smoke_browser_use.py saucedemo_full_checkout \
        > /tmp/S1_full_${run}.log 2>&1
    cp /tmp/smoke_final.png /tmp/S1_full_${run}_final.png
done
```

**Step 4: Verify each final screenshot manually**

For each `/tmp/S1_*_final.png`, open it and grade. Append rows to `/tmp/bake_off_results.md`. Record the highest checkpoint reached based on the screenshot + log content.

**Step 5: No commit** — results are scratch until the findings entry in Phase E.

---

### Task C2: Run S2 (UI-Venus-1.5-30B-A3B)

Same shape as C1, but:

```bash
sudo bash /home/seans/Source/vision-model/scripts/swap_model.sh ui-venus-1.5-30b-a3b Q3_K_M
```

`MODEL=ui-venus-1.5-30b-a3b`. Output prefix `/tmp/S2_*`.

---

### Task C3: Run S3 (Holo2-30B-A3B)

Same shape, `MODEL=holo2-30b-a3b`, prefix `/tmp/S3_*`.

---

### Task C4: Run S4 (bu-30b-a3b-preview via `ChatBrowserUse`)

S4 differs from C1–C3 because browser-use exposes a dedicated adapter for this model that uses the harness's native action format. We do NOT route through `ChatOpenAI`.

**Files:**
- Create: `/home/seans/Source/vision-model/scripts/smoke_browser_use_bu.py`

**Step 1: Author a sister runner that wires `ChatBrowserUse`**

```python
"""
Smoke runner variant that uses browser-use's native ChatBrowserUse adapter
against bu-30b-a3b-preview served by llama.cpp. Mirrors smoke_browser_use.py
otherwise. See docs/plans/2026-04-29-moe-stack-comparison-design.md (S4).
"""
import asyncio, importlib, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from drag_action import register_drag  # noqa: E402

from browser_use import Agent, Browser, ChatBrowserUse, Tools  # noqa: E402

CHROME_PATH = "/home/seans/.cache/ms-playwright/chromium-1208/chrome-linux64/chrome"
SERVER_URL = "http://localhost:8080/v1"
MODEL = "bu-30b-a3b-preview"
DEFAULT_SMOKE = "excalidraw_toolbar"


def load_smoke(name):
    return importlib.import_module(f"smokes.{name}")


async def main(smoke_name):
    smoke = load_smoke(smoke_name)
    print(f"===== SMOKE (S4 native): {smoke_name} =====")

    llm = ChatBrowserUse(
        model=MODEL,
        base_url=SERVER_URL,
        api_key="not-needed",
        temperature=0.0,
    )

    browser = Browser(
        is_local=True,
        executable_path=CHROME_PATH,
        headless=getattr(smoke, "HEADLESS", False),
        chromium_sandbox=False,
        args=["--no-sandbox", "--disable-dev-shm-usage"],
        keep_alive=True,
    )

    tools = Tools()
    register_drag(tools)

    agent = Agent(
        task=smoke.TASK,
        llm=llm,
        browser=browser,
        tools=tools,
        use_vision=True,
        max_actions_per_step=getattr(smoke, "MAX_ACTIONS_PER_STEP", 2),
    )

    history = await agent.run(max_steps=getattr(smoke, "MAX_STEPS", 40))
    final = history.final_result() if hasattr(history, "final_result") else None
    print("\n===== FINAL =====")
    print(final or "(no final_result)")

    try:
        cdp = await agent.browser_session.get_or_create_cdp_session()
        res = await cdp.cdp_client.send.Page.captureScreenshot(session_id=cdp.session_id)
        import base64, pathlib
        out = pathlib.Path("/tmp/smoke_final.png")
        out.write_bytes(base64.b64decode(res["data"]))
        print(f"Saved verification screenshot to {out}")
    finally:
        await agent.browser_session.kill()


if __name__ == "__main__":
    os.environ.setdefault("ANONYMIZED_TELEMETRY", "false")
    smoke_name = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SMOKE
    asyncio.run(main(smoke_name))
```

**Step 2: Verify it imports**

```bash
.venv/bin/python -c "from browser_use import ChatBrowserUse; print('ok')"
```

Expected: `ok`. (Already verified during plan creation.)

**Step 3: Commit**

```bash
git add scripts/smoke_browser_use_bu.py
git commit -m "feat(s4): smoke runner using ChatBrowserUse adapter for bu-30b"
```

**Step 4: Swap server**

```bash
sudo bash /home/seans/Source/vision-model/scripts/swap_model.sh bu-30b-a3b-preview Q3_K_M
```

**Step 5: Run smokes (n=1 each, n=3 long-horizon)**

```bash
cd /home/seans/Source/vision-model
for s in excalidraw_drag excalidraw_toolbar saucedemo_headed; do
    DISPLAY=:0 XAUTHORITY=/run/user/1000/xauth_rVYaGJ XDG_RUNTIME_DIR=/run/user/1000 \
        PYTHONUNBUFFERED=1 \
        .venv/bin/python -u scripts/smoke_browser_use_bu.py $s \
        > /tmp/S4_$s.log 2>&1
    cp /tmp/smoke_final.png /tmp/S4_${s}_final.png
done
for run in 1 2 3; do
    DISPLAY=:0 XAUTHORITY=/run/user/1000/xauth_rVYaGJ XDG_RUNTIME_DIR=/run/user/1000 \
        PYTHONUNBUFFERED=1 \
        .venv/bin/python -u scripts/smoke_browser_use_bu.py saucedemo_full_checkout \
        > /tmp/S4_full_${run}.log 2>&1
    cp /tmp/smoke_final.png /tmp/S4_full_${run}_final.png
done
```

**Step 6: Score and append to `/tmp/bake_off_results.md`.**

---

### Task C5: Compute interim scores and pick S5 planner

**Step 1: Tally scores from `/tmp/bake_off_results.md`**

For each of S1–S4, compute the long-horizon-weighted aggregate per the design doc:
```
score = 3 × (long_horizon_median_checkpoints / 9)
      + 1 × normalized(drag)
      + 1 × normalized(toolbar)
      + 1 × normalized(saucedemo_headed)
```

Where `normalized(smoke) ∈ {0.0 fail, 0.5 partial, 1.0 pass}`.

**Step 2: Pick S5 planner**

The S5 planner is the highest-scoring of S2/S3/S4 (the three 30B-A3B candidates). Document the choice in `/tmp/bake_off_notes.md`.

If S2/S3/S4 are all <50% of S1's score, **abort S5** — the split design rests on having a strong planner; with three weak candidates, the experiment can't answer its question. Document and skip to Phase E.

---

## Phase D — Split design (S5)

### Task D1: Build the minimal split harness

**Files:**
- Create: `/home/seans/Source/vision-model/scripts/smoke_split.py`

The split design has two model calls per agent step:
1. **Planner** call (the chosen 30B-A3B) — given screenshot + history, decides "click X" / "type Y" / "done".
2. **Grounder** call (Holo1.5-7B) — given the planner's natural-language target description and the screenshot, returns precise click coordinates.

Both servers cannot run concurrently on a single 16 GB GPU. So the split harness must **swap models between calls**, OR run two separate llama.cpp servers on different ports with offloading. Disk + RAM is fine; VRAM is the bottleneck.

**The simplest working approach: serialize via swap_model.sh.** Each agent step is two server-swap cycles (each ~10–30 s for the 30B-A3B; ~5 s for Holo1.5-7B). Adds ~30 s per step but is the lowest-effort harness. With ~15 steps for the long-horizon task, that's ~7 min of swap overhead per run. Acceptable for a screening.

**Step 1: Author the harness**

```python
"""
Split-design harness: planner (30B-A3B) + grounder (Holo1.5-7B). The two
models swap on the single GPU between calls (slow but simple). The
planner is asked to emit JSON with a `target_description` field instead
of coordinates; the grounder turns that description into a coordinate
via a focused grounding prompt. Coords are then dispatched via the
standard browser-use action set.

See docs/plans/2026-04-29-moe-stack-comparison-design.md (S5).

Usage:
    PLANNER=<alias> GROUNDER=holo1.5-7b ... python scripts/smoke_split.py <smoke>

The script calls swap_model.sh between every model call. This requires
passwordless sudo for swap_model.sh (or run the entire harness via sudo
with --preserve-env).
"""
import asyncio, importlib, os, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from drag_action import register_drag  # noqa: E402

from browser_use import Agent, Browser, ChatOpenAI, Tools  # noqa: E402

CHROME_PATH = "/home/seans/.cache/ms-playwright/chromium-1208/chrome-linux64/chrome"
SERVER_URL = "http://localhost:8080/v1"
PLANNER = os.environ["PLANNER"]
GROUNDER = os.environ["GROUNDER"]
PLANNER_QUANT = os.environ.get("PLANNER_QUANT", "Q3_K_M")
GROUNDER_QUANT = os.environ.get("GROUNDER_QUANT", "Q6_K")
SWAP = "/home/seans/Source/vision-model/scripts/swap_model.sh"
DEFAULT_SMOKE = "saucedemo_full_checkout"


def swap_to(model, quant):
    subprocess.check_call(["sudo", "bash", SWAP, model, quant])


# A custom ChatOpenAI subclass that swaps the served model immediately
# before sending its request. The agent loop sees one logical LLM but
# we re-target it per call.
class SwappingChat(ChatOpenAI):
    def __init__(self, *args, role: str, **kw):
        super().__init__(*args, **kw)
        self._role = role  # "planner" or "grounder"

    async def ainvoke(self, *args, **kw):
        if self._role == "planner":
            swap_to(PLANNER, PLANNER_QUANT)
        else:
            swap_to(GROUNDER, GROUNDER_QUANT)
        return await super().ainvoke(*args, **kw)


# For now: only the planner drives the agent loop; the grounder is used
# implicitly by the planner's prompt (the planner is told to think in
# terms of element descriptions, and we post-process click actions to
# refine via a grounder call). Implementation deferred to step 2.
async def main(smoke_name):
    smoke = importlib.import_module(f"smokes.{smoke_name}")
    print(f"===== SMOKE (S5 split): {smoke_name} =====")

    planner = SwappingChat(
        model=PLANNER,
        base_url=SERVER_URL,
        api_key="not-needed",
        temperature=0.0,
        reasoning_effort="none",
        max_completion_tokens=int(os.environ.get("MAX_TOKENS", "8192")),
        add_schema_to_system_prompt=False,
        dont_force_structured_output=False,
        role="planner",
    )

    browser = Browser(
        is_local=True,
        executable_path=CHROME_PATH,
        headless=getattr(smoke, "HEADLESS", False),
        chromium_sandbox=False,
        args=["--no-sandbox", "--disable-dev-shm-usage"],
        keep_alive=True,
    )

    tools = Tools()
    register_drag(tools)

    agent = Agent(
        task=smoke.TASK,
        llm=planner,
        browser=browser,
        tools=tools,
        use_vision=True,
        max_actions_per_step=getattr(smoke, "MAX_ACTIONS_PER_STEP", 2),
    )

    history = await agent.run(max_steps=getattr(smoke, "MAX_STEPS", 40))
    print("\n===== FINAL =====")
    print(history.final_result() if hasattr(history, "final_result") else "(no final)")

    try:
        cdp = await agent.browser_session.get_or_create_cdp_session()
        res = await cdp.cdp_client.send.Page.captureScreenshot(session_id=cdp.session_id)
        import base64, pathlib
        out = pathlib.Path("/tmp/smoke_final.png")
        out.write_bytes(base64.b64decode(res["data"]))
        print(f"Saved verification screenshot to {out}")
    finally:
        await agent.browser_session.kill()


if __name__ == "__main__":
    os.environ.setdefault("ANONYMIZED_TELEMETRY", "false")
    smoke_name = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SMOKE
    asyncio.run(main(smoke_name))
```

**Step 2: Decide on the grounder's role**

The skeleton above is *planner-only* — it doesn't actually invoke the grounder yet. There are two ways to wire the grounder:

(a) **Refine all click coords** — after the planner emits a click with target description, swap to grounder and re-call with the description to get precise coords. This is essentially the `REFINE_CLICKS=True` path that Phase 11 already tested with the *same* model (and got identical coords because the merged 8B unified its heads). With *different* models (small specialized grounder), the answer may differ.

(b) **Grounder-only for canvas / non-DOM clicks** — DOM clicks already use indices; pure visual clicks go through the grounder.

Implement (a) — simpler, tests the cleanest version of the hypothesis. Add a hook in `scripts/custom_agent/model.py` or a wrapper around `tools.click()` that, when given a click action with a target description, swaps to the grounder and re-coords before dispatch.

This is meaningfully more complex than the rest of this plan. **Stop and check in with the user before implementing step 2 in detail** — the harness design choice has implications (e.g. whether to use the existing `scripts/custom_agent/` CDP path instead of browser-use, since the custom path already separates "planner says target" from "click happens at coords").

**Step 3: Commit the skeleton + design notes**

```bash
git add scripts/smoke_split.py
git commit -m "wip(s5): split-design harness skeleton (planner-only, grounder TODO)"
```

---

### Task D2: Run S5 (gated on Task D1 step 2 decision)

Same shape as C1–C4, but using `scripts/smoke_split.py`. Output prefix `/tmp/S5_*`.

```bash
PLANNER=<chosen_30b> GROUNDER=holo1.5-7b \
    DISPLAY=:0 XAUTHORITY=/run/user/1000/xauth_rVYaGJ XDG_RUNTIME_DIR=/run/user/1000 \
    PYTHONUNBUFFERED=1 \
    .venv/bin/python -u scripts/smoke_split.py saucedemo_full_checkout \
    > /tmp/S5_full_1.log 2>&1
```

Note: passwordless sudo for `swap_model.sh` is required for the swap-per-call path. Set this up either with a sudoers entry (`/etc/sudoers.d/vision-model`):

```
seans ALL=(root) NOPASSWD: /bin/bash /home/seans/Source/vision-model/scripts/swap_model.sh *
```

or run the harness itself under sudo with `--preserve-env`. Document the choice.

---

## Phase E — Findings + winner promotion

### Task E1: Append Phase 13 to `findings.md`

**Files:**
- Modify: `/home/seans/Source/vision-model/docs/findings.md`

**Step 1: Compose the Phase 13 entry**

Use the `/tmp/bake_off_results.md` table and `/tmp/bake_off_notes.md` deployment notes as raw material. Structure mirrors Phase 11/12:

- Goal (1–2 sentences linking back to the design doc)
- Setup (quants, deviations like Q8 KV / 16K ctx, S5 planner choice)
- Per-stack run summaries (one short paragraph each — what passed, what failed, repeat patterns)
- Score table (long-horizon-weighted aggregate, all stacks, sortable)
- Verdict (winner; whether to promote; specific concerns about losers)
- Caveats (n counts, known biases, what wasn't tested)

**Step 2: Commit**

```bash
git add docs/findings.md
git commit -m "docs: phase 13 — 5-stack MoE bake-off findings"
```

---

### Task E2: Promote the winner (or document the no-promote outcome)

**Files (winner case):**
- Modify: `/home/seans/Source/vision-model/CLAUDE.md` (Default model section)
- Possibly modify: `/home/seans/Source/vision-model/scripts/swap_model.sh` (no change, just notes)
- Modify: `/home/seans/Source/vision-model/docs/backlog.md` (mark E-4 done if UI-Venus 30B won)

**Step 1 (winner case): Update CLAUDE.md "Default model" line**

Edit the existing default-model line in CLAUDE.md (currently `ui-venus-1.5-8b at Q6_K`) to point to the winner with its quant. Add a 1-sentence reference back to Phase 13 findings.

**Step 2 (winner case): Reflect in backlog**

If UI-Venus-1.5-30B-A3B won, delete backlog item E-4 (its hypothesis was tested). If it lost, edit E-4 to mark resolved-with-negative-result, pointing at Phase 13.

**Step 3 (no-promote case): Document explicitly**

Add a short note in CLAUDE.md "Model selection" section: "Default remains UI-Venus-1.5-8B per Phase 13 findings; the 30B-A3B candidates did not clear the rubric. See docs/findings.md Phase 13."

**Step 4: Commit**

```bash
git add CLAUDE.md docs/backlog.md
git commit -m "feat: promote <winner> as default per Phase 13 bake-off"
# (or)
git commit -m "docs: keep 8B baseline default; record Phase 13 negative result"
```

---

## Done condition

- All five stacks (S1–S5) have scored runs in `/tmp/bake_off_results.md`, with caveats for any aborted stacks documented.
- `docs/findings.md` has a Phase 13 entry with the full table, verdict, and caveats.
- Either a winner is promoted (CLAUDE.md updated, backlog cleaned) or the no-promote outcome is recorded.
- New files committed: `scripts/smokes/saucedemo_full_checkout.py`, `scripts/smoke_browser_use_bu.py`, `scripts/smoke_split.py`, edits to `scripts/swap_model.sh`.

---

## Important reminders woven through the plan

1. **Independent verification screenshot**: `/tmp/smoke_final.png` is captured by the runner via CDP and is the ground truth — agent self-reports cannot be trusted. The plan copies it per-run for later grading.
2. **Long agent runs to log files, not pipes**: every run command in this plan redirects to `/tmp/<name>.log`. The tail-via-harness antipattern is avoided.
3. **Privileged ops via /tmp script**: not strictly needed here — `swap_model.sh` is already a script — but the principle holds for any new sudo step (e.g. the sudoers entry in D2).
4. **Don't edit existing smokes**: `scripts/smokes/saucedemo_full_checkout.py` is new; existing payloads stay untouched per CLAUDE.md.
5. **Q3_K_M quality is an open risk**: if all three 30B-A3B stacks underperform the 8B baseline on grounding-precision-sensitive tasks, the leading candidate is re-tested at Q4_K_M before declaring a winner (even though Q4 may need 16K ctx + Q8 KV per design doc risk). Document any such retest in Phase 13.
