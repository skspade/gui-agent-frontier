# Handoff: Thunder cloud sweep harness scaffolded, awaiting MCP provisioning

**Snapshot date:** 2026-04-30 evening, after the Phase 1 handoff (`54344b5`).
**Working tree:** three new files in `scripts/thunder/` + this doc, **no commits yet**.
**Branch:** `main`.
**Server state:** local `vision-model.service` still running whatever the prior handoff left (`ui-venus-1.5-30b-a3b` Q3_K_M per `docs/plans/2026-04-30-handoff-after-phase1.md`); local hardware otherwise unchanged.

---

## Why this exists

User wanted to free the local box for the night while continuing thesis work. Aligned on a hybrid: **browser-use stays local**, only `llama-server` moves to a Thunder cloud GPU. The existing OpenAI HTTP surface means the smoke runner needs zero changes — an SSH tunnel makes Thunder appear as `localhost:8080`.

**Thesis framing:** removes the 16 GB local-VRAM ceiling, so model size becomes a *swept axis* rather than a hard constraint. Direct probe of the class-C parameter cliff (visual grounding) — does it hold or collapse when you can step up to 70B at usable quants?

---

## What got built this session

Three scripts under `scripts/thunder/` (all `bash -n` / `py_compile` clean; verified the trickiest case — the `--chat-template-kwargs` JSON quoting — by simulating the local→remote substitution in a real shell):

1. **`bootstrap_instance.sh`** — runs once on a freshly-provisioned instance:
   ```
   scp scripts/thunder/bootstrap_instance.sh thunder:~/
   ssh thunder bash ~/bootstrap_instance.sh
   ```
   Installs apt build deps, builds llama.cpp with `-DGGML_CUDA=ON`, pip-installs `huggingface_hub`, fetches the GGUF ladder. Idempotent — re-runs skip already-built/downloaded artifacts.

2. **`swap_model_remote.sh`** — same role as local `scripts/swap_model.sh`. Locally invoked:
   ```
   bash scripts/thunder/swap_model_remote.sh <ssh_alias> <model> [quant]
   ```
   Writes a `~/run_llama.sh` wrapper on the remote with the chosen args, runs it inside a fixed `llamasrv` tmux session, polls `/health` over SSH up to 180s. Wrapper-file approach (vs. inline tmux command) avoids unescapable JSON-quoting in `--chat-template-kwargs`.

3. **`sweep.py`** — the orchestrator. Pre-flight: refuses to run if local 8080 is occupied. Per cell: remote swap → open per-cell SSH tunnel → run existing `smoke_browser_use.py` unchanged (`MODEL=...`) → archive `swap.log` + `smoke.log` + `final.png` to `data/sweeps/<run_id>/<model>_<quant>/`. Drops a `summary.json` at the end. Tunnel is owned + torn down per-cell to avoid stale state across server restarts.

---

## The ladder (HF sources verified via web fetch this session)

Default `DEFAULT_LADDER` in `sweep.py`. ~110 GB total weights to download.

| Cell | Source | Size |
|---|---|---|
| `holo3-35b-a3b` IQ3_XXS | [`mradermacher/Holo3-35B-A3B-i1-GGUF`](https://huggingface.co/mradermacher/Holo3-35B-A3B-i1-GGUF) | 14 GB |
| `holo3-35b-a3b` Q4_K_M | same i1 repo | 21 GB |
| `holo3-35b-a3b` Q6_K | same i1 repo | 28 GB |
| `qwen2.5-vl-72b-instruct` Q4_K_M | [`ggml-org/Qwen2.5-VL-72B-Instruct-GGUF`](https://huggingface.co/ggml-org/Qwen2.5-VL-72B-Instruct-GGUF) | 47 GB |

**Holo3 mmproj quirk** (easy to miss): weights live in the `-i1-GGUF` repo, but the Q8_0 mmproj lives in the *static* sibling [`mradermacher/Holo3-35B-A3B-GGUF`](https://huggingface.co/mradermacher/Holo3-35B-A3B-GGUF). Bootstrap fetches from both.

**Dropped rung:** `ui-venus-1.5-30b-a3b` Q6_K. Verified no public GGUF on HF (mradermacher / bartowski / unsloth / ggml-org / Mungert all clean). User explicitly chose to skip rather than wire safetensors→GGUF conversion. Comment in `bootstrap_instance.sh` documents the manual path if needed later.

**Disk-constrained instance escape hatch:** `SKIP_72B=1 bash ~/bootstrap_instance.sh` skips the 47 GB Qwen pull, leaving just the 3-rung Holo3 ladder.

**Task:** `excalidraw_drag` (class C, forces visual grounding, no DOM bypass). Smoke already exists at `scripts/smokes/excalidraw_drag.py`. Override with `--task <other>` if redirecting.

---

## GPU selection & expected cost

Priced via Thunder MCP on 2026-04-30. Prototyping mode (auto-stops idle, no 24/7 billing) is the right tier for a one-shot sweep.

**Selected: `a100xl_x1_prototyping`, 8 vCPU, 150 GB persistent disk.**

| Component | Rate | Hourly |
|---|---|---|
| A100 80GB GPU | $0.78/hr | $0.78 |
| 4 additional vCPU (8 total, base is 4) | $0.06/vCPU-hr | $0.24 |
| 150 GB persistent disk | $0.0005/GB-hr | $0.075 |
| **Total** | | **~$1.10/hr** |

Expected sweep cost: **$1.10–$1.65** for 60–90 min wall-clock (the wall-clock estimate is still unmeasured; verify with the first cell). Bootstrap downloads add ~30 min × $1.10 = ~$0.55 one-shot, so first run is **~$1.65–$2.20 end-to-end**.

**Why not A6000 (cheapest at $0.35/hr):** 48 GB VRAM. Qwen2.5-VL-72B Q4_K_M is 47 GB weights alone — OOMs before KV+mmproj+activations. Would force dropping the 72B rung, which is the parameter-cliff probe that motivated going to cloud in the first place.

**Why not H100 (originally preferred):** all H100 prototyping skus were `unavailable` at provisioning time. A100 keeps full ladder coverage; the speed delta is minor since wall-clock is dominated by GGUF mmap + browser-use step latency, not raw inference throughput.

**Disk sizing rationale:** ~110 GB GGUF weights + ~5 GB llama.cpp build + ~5 GB apt/system + ~30 GB headroom = 150 GB. A100 prototyping caps at 300 GB persistent + 200 GB ephemeral. Ephemeral is cheaper ($0.0002/GB-hr) and faster (NVMe), but is wiped on any non-port `modify_instance` call and on delete — fine for a single-shot sweep, but the bootstrap script writes to `~/models/` (persistent) and rerouting it to `/ephemeral/models` saves ~$0.045/hr (~$0.07 over 90 min). Not worth the script change for this run; revisit if doing repeated sweeps.

**vCPU sizing rationale:** llama-server is GPU-bound, but at 4 vCPU the box has 32 GiB RAM which doesn't fully cache the 47 GB Qwen mmap — first-token latency on the 72B cell would page-thrash. 8 vCPU = 64 GiB RAM comfortably caches it.

---

## Where to pick up

Session paused at the moment of provisioning. User granted access to the **Thunder Compute MCP** mid-conversation, but its tools weren't visible to the active session — `ToolSearch` query `thunder` returned no matches. **Reload required to surface it.**

**Fresh-session playbook:**

1. **Verify the Thunder MCP is loaded.** Try `ToolSearch` with query `thunder` (also try `tnr`, `compute`). If absent, the MCP grant didn't propagate — ask user to reconnect.
2. **Provision an instance via the MCP.** Spec decided in the GPU selection section above:
   - `gpu_type=a100xl`, `mode=prototyping`, `num_gpus=1`
   - `num_vcpus=8`, `disk_size_gb=150`, `ephemeral_disk_gb=0`
   - `template=cuda12-9` — `base` only ships PyTorch's CUDA runtime libs, not `nvcc`; we need the full toolkit to build llama.cpp. cuda12-9 has CUDA 12.9 + cuDNN + NCCL pre-installed.
   - Expected cost: ~$1.10/hr → ~$1.65–$2.20 for first sweep including 30 min bootstrap.
3. **Wire SSH.** Two surprises here, both encountered on the 2026-04-30 provisioning run:

   - **SSH user is `ubuntu`, not `root`.** `get_ssh_command` from the MCP returns a `root@…` form — that's for `tnr connect`'s auto-provisioned per-instance key. When you register an org-level SSH public key via `create_ssh_key` and pass `ssh_key_name` to `create_instance`, Thunder lands the key at `/home/ubuntu/.ssh/authorized_keys`. Use `ubuntu@` with your normal `~/.ssh/id_ed25519`.
   - **If `~/.ssh/config` is a home-manager symlink** (Nix users), it's read-only and you can't `>>` to it. Replace the symlink with a real file (copy the original target's contents, prepend the `Host thunder` block). `home-manager switch` will restore the symlink whenever you want to fold the change into Nix config or revert.

   Block to add:
   ```
   Host thunder
     HostName <ip from list_instances>
     Port <port from list_instances>
     User ubuntu
     IdentityFile ~/.ssh/id_ed25519
     StrictHostKeyChecking accept-new
   ```
   Verify: `ssh thunder 'echo ok && nvidia-smi -L'`.
4. **Bootstrap the instance.** Always redirect to a log file (per `CLAUDE.md` long-run rule — the harness buffers piped stdout):
   ```
   scp scripts/thunder/bootstrap_instance.sh thunder:~/
   ssh thunder 'bash ~/bootstrap_instance.sh' > /tmp/thunder-bootstrap.log 2>&1 &
   tail -f /tmp/thunder-bootstrap.log
   ```
   Expect 15-30 min — build ~5 min, GGUF downloads (~110 GB) dominate. `nvcc` is not on PATH inside ubuntu's login shell on cuda12-9, but bootstrap's fallback adds `/usr/local/cuda/bin` to PATH automatically.
5. **Stop the local service** to free port 8080:
   ```
   sudo systemctl stop vision-model.service
   ```
6. **Kick off the sweep:**
   ```
   .venv/bin/python scripts/thunder/sweep.py --ssh thunder --task excalidraw_drag
   ```
7. **Walk away.** ~30-90 min wall-clock for 4 cells. Output: `data/sweeps/<run_id>/`.
8. **Tear down the instance** via the Thunder MCP after copying results back. **No auto-teardown wired into sweep.py** — manual stop is the safety net against runaway billing. (If overnight unattended is desired, add a teardown call to the Thunder MCP at the end of `sweep.py`'s main loop, after the summary is written.)
9. **Restart local inference**: `sudo systemctl start vision-model.service`.

---

## Snapshot recovery (saved 2026-04-30 before teardown)

Took a snapshot before deleting the original Phase 20/21 instance — the 110 GB of GGUFs + llama.cpp build are saved. Restoring is faster than re-bootstrapping (~8.5 min vs ~30 min).

- **Snapshot name**: `vision-model-thunder-2026-04-30`
- **Snapshot ID**: `299aCU2Y5c6uShkkdPEx`
- **Minimum disk size for restore**: 150 GB
- **Storage cost**: ~$0.0073/hr ≈ $0.18/day ≈ $5.30/month for ~106 GB used
- **Durability caveat**: Thunder docs explicitly say snapshots are "for convenience rather than long-term data security" — re-bootstrap is the always-works fallback. Don't treat the snapshot as archival.

**To restore** (when you start the next sweep):
1. `create_instance` with `template=<snapshot-name-or-id>` instead of `cuda12-9`
2. Same other params: `gpu_type=a100xl`, `mode=prototyping`, `num_gpus=1`, `vcpus=8`, `disk_size_gb=150` (must be ≥ snapshot's `minimumDiskSizeGb`).
3. Status will go through `RESTORING` → `RUNNING` (~8.5 min).
4. Skip step 4 (bootstrap) — it's already on disk.
5. Verify: `ssh thunder 'ls /home/ubuntu/llama.cpp/build/bin/llama-server && find /home/ubuntu/models -name "*.gguf" | wc -l'` should show the binary + 6 GGUF files.

**MCP gotcha learned 2026-04-30**: `create_snapshot` requires the **UUID** (`uio4fzd3` for the original instance), not the integer instance_id ("0"), despite the MCP tool description saying "always use the integer ID for tool calls." If you get `instance not found or not supported for snapshot creation`, retry with the UUID from `list_instances`.

---

## Critical context for the fresh session

- **Auto mode** was active in this session. Continue executing autonomously per user preference, but **provisioning and teardown remain user-confirmable** — they're cost-incurring.
- **Browser stays local; only inference moves.** This was an explicit user correction mid-scaffolding (don't reverse). Rationale: full-stack-on-remote needs Xvfb in container, and the headed-Chromium quirks documented in `CLAUDE.md` (saucedemo nested-anchor loop in `--headless`) argue for a real display.
- **`smoke_browser_use.py` is unchanged.** Hardcoded `SERVER_URL = "http://localhost:8080/v1"` works because sweep.py SSH-tunnels remote 8080 → local 8080. **Don't refactor it to take `--base-url`** — the tunnel is the abstraction.
- **Per-model quant defaults are baked into `swap_model_remote.sh`** mirroring the local F-7 fix: Holo3 defaults to IQ3_XXS, Qwen2.5-VL-72B to Q4_K_M. Pass an explicit quant if probing a different rung.
- **Quoting bug history.** First draft of `swap_model_remote.sh` had unescaped quotes in `--chat-template-kwargs` that would have broken tmux's outer quoted command on the remote. Fixed via the wrapper-file approach. Don't try to inline it back.

---

## Files added this session

- `scripts/thunder/bootstrap_instance.sh` (new, executable)
- `scripts/thunder/swap_model_remote.sh` (new, executable)
- `scripts/thunder/sweep.py` (new)
- `docs/plans/2026-04-30-thunder-cloud-handoff.md` (this file)

No existing files modified. No commits. User may want to commit these before reload (`docs:` for the handoff, `feat(harness):` for the scripts) so the working tree state is preserved across sessions, but it's not required.

---

## Active assumptions worth re-checking

- **Thunder's default remote user.** Bootstrap assumes `$HOME` is writable and `sudo apt` works without password. True on most Thunder images; verify on first boot.
- **HF download speed on Thunder.** Sources verified to exist; wall-clock for the 110 GB pull is unmeasured. If <100 MB/s, bootstrap stretches past 30 min — not a blocker, but plan accordingly.
- **Qwen2.5-VL-72B Q4_K_M actually loads in 80 GB VRAM.** Math says yes (47 GB weights + ~750 MB mmproj + KV + activations) but unverified empirically. If it OOMs, drop to a smaller quant (would require an extra `huggingface_hub` fetch — the i1 repo for this model wasn't pulled) or shrink `-c 32768` → `-c 16384`.
- **Holo3 `enable_thinking:false` works under llama.cpp's CUDA backend.** Tested locally on Vulkan only. Should be backend-independent (chat-template-side, not kernel-side), but eyeball the first cell's smoke log for `<think>` blocks leaking into output.
