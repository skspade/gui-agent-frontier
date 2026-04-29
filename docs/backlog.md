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

## E-4 — UI-Venus-1.5-30B-A3B deploy + saucedemo precision rerun
**Effort: l · Priority: E**

Phase 11 found that the merged 8B's visual grounding mis-targets small
elements in dense layouts (saucedemo product-card buttons, top-right
cart icon) by 20–50+ px in BOTH headed and headless modes, AND that the
in-loop refinement trick (separate grounding-prompt call per click,
backlog F-3 hypothesis tested in Phase 11 as `REFINE_CLICKS`) emits
identical coords (within 1–2 px). The merge unified the model's heads,
so there is no precision left to recover at this model size.

The README's benchmark table claims meaningful uplift on the 30B-A3B
variant (ScreenSpot-Pro 69.6 vs 8B's 68.4; OSWorld-G 70.6 vs lower
8B). 30B-A3B is a Mixture-of-Experts: 30B total params, 3B active per
token — so compute on the 9070 XT is comparable to running the 8B,
provided the *weights* fit in 16GB VRAM at an aggressive quant.

The hypothesis to validate: **does 30B-A3B grounding precision close
the saucedemo gap?** If yes, the custom CDP agent (S-1) becomes
production-viable for richly-DOM'd small-target UIs and not just
canvas. If no, the precision ceiling is not a model-size issue.

### Prerequisites (do these first or the rest is wasted)
1. **Free disk.** Currently 49GB free, 95% used. Need ~80GB for the
   safetensors download + GGUF conversion intermediate + final quants.
   - Delete unused 8B quants per CLAUDE.md (Q4_K_M, Q5_K_M, f16
     intermediate). Keep Q6_K. That recovers ~26GB.
   - Audit `/home/seans/.cache/` and `/home/seans/.venv/` for
     unrelated bloat. Probably another 5–10GB recoverable.
2. **Confirm llama.cpp Vulkan supports MoE expert dispatch in the
   current build.** Check `git log` of the cloned llama.cpp tree —
   MoE expert routing on Vulkan landed in late 2024 / early 2025;
   ensure the build is recent enough. If not, `git pull && cmake
   --build` first.
3. **Check VRAM headroom.** 30B params at Q4_K_M ≈ 15GB; at Q3_K_M ≈
   12GB. The 9070 XT is 16GB. With f16 mmproj (1–2GB) and KV cache
   for 32K context (a few GB even with Q8 KV), Q4 may be tight or
   impossible. Plan for Q3_K_M as the working quant; Q4 as the upper
   bound to attempt only after Q3 succeeds.

### Steps
1. Free disk per Prereq 1. Verify with `df -h /home`.
2. Download safetensors:
   ```
   .venv/bin/huggingface-cli download inclusionAI/UI-Venus-1.5-30B-A3B \
       --local-dir ~/models/ui-venus-1.5-30b-a3b/hf
   ```
   (Multi-hour. Run with `nohup` and a log file; never tail-pipe.)
3. Convert to GGUF:
   ```
   .venv/bin/python <llama.cpp>/convert_hf_to_gguf.py \
       ~/models/ui-venus-1.5-30b-a3b/hf \
       --outfile ~/models/ui-venus-1.5-30b-a3b/ui-venus-1.5-30b-a3b-f16.gguf \
       --outtype f16
   ```
   ~30 min. Will produce a ~60GB f16 GGUF — disk needs to absorb this
   before the quants compress it down.
4. Quantize down to Q3_K_M and (if disk allows) Q4_K_M:
   ```
   <llama.cpp>/build/bin/llama-quantize \
       ~/models/ui-venus-1.5-30b-a3b/ui-venus-1.5-30b-a3b-f16.gguf \
       ~/models/ui-venus-1.5-30b-a3b/ui-venus-1.5-30b-a3b-Q3_K_M.gguf Q3_K_M
   ```
5. Generate / locate the f16 mmproj (vision encoder). The 30B-A3B has
   the same Qwen3-VL backbone family as the 8B; conversion script
   should produce a separate mmproj from the safetensors. Verify the
   mmproj name matches the model and that it's f16 (not quantized).
6. After conversion succeeds: delete the f16 GGUF intermediate to
   free disk (per CLAUDE.md "f16 can be deleted if disk pressure").
7. Update `~/models/ui-venus-1.5-30b-a3b/` and the systemd service
   (`/etc/systemd/system/ui-venus.service` per CLAUDE.md) to point at
   the new model + mmproj. Use `scripts/swap_quant.sh` as the
   reference for systemd reload + `/health` poll. Likely needs a new
   `swap_model.sh` rather than a quant swap inside one model dir.
8. Confirm endpoint works:
   ```
   curl -s http://localhost:8080/health
   ```
   Then send a one-shot grounding probe (lift `scripts/coord_remap_demo.py`):
   ```
   .venv/bin/python scripts/coord_remap_demo.py /tmp/smoke_final.png \
       "the rectangle drawn on the canvas"
   ```
   Should return coords within ~5 px of the 8B's `(466, 460)` baseline.
9. **Rerun the saucedemo head-to-head**: same task payloads from
   Phase 11. Use the existing `scripts/custom_agent.py` runner — no
   code changes needed; the model name is the only difference.
   ```
   .venv/bin/python -u scripts/custom_agent.py saucedemo_headed \
       > /tmp/custom_agent_30b_saucedemo.log 2>&1
   ```
10. Visually verify `/tmp/custom_agent_final.png`. The cart icon
    should now show a "1" badge after Add-to-cart, and the cart-icon
    click should navigate to `/cart.html`.
11. Run Excalidraw too (`scripts/custom_agent.py excalidraw_toolbar`)
    to confirm the 30B variant doesn't regress on the case the 8B
    already solved.
12. Append a Phase 12 entry to `docs/findings.md` with: precision
    delta on saucedemo (number of px the 30B differs from the 8B per
    click), success/failure on cart-icon navigation, wall-clock per
    step (will be slower; 3B active params is more compute than the
    8B's dense run despite being "smaller"-feeling), and a verdict on
    whether 30B closes the gap.

### Acceptance
- ✅ 30B-A3B GGUF deployed and serving via llama.cpp on the same
  endpoint shape (OpenAI-compatible, port 8080, `/health`).
- ✅ Phase 12 entry in `docs/findings.md` with side-by-side numbers
  (8B vs 30B-A3B) on the same saucedemo and Excalidraw payloads.
- ✅ A clear verdict — either "30B closes the gap, custom CDP agent
  is now production-viable for dense UIs" or "30B does not help, the
  precision ceiling is below model size — defer to browser-use's
  DOM-augmented prompts for these UIs."

### Why this is *experiment*, not *strategic*
Strategic items change direction. This is a yes/no question that has
a definite answer once we have data. The downstream consequence
(stick with custom CDP for canvas, fall back to browser-use for dense
UIs vs commit fully to the custom client) is strategic, but THAT
decision is a separate item that depends on this experiment's result.

### Risk: VRAM exhaustion at Q3
If even Q3_K_M won't fit in 16GB with f16 mmproj + KV cache, options
are: (a) try Q2_K (significant accuracy hit, may invalidate the
test), (b) drop context window to 8K (saucedemo's prompt + history is
small enough), (c) Q8 KV via `--cache-type-k q8_0` per CLAUDE.md
note. Document any of these in Phase 12 as caveats on the result.

### Don't pivot to this prematurely
S-1 produced a clean canvas win and a clean dense-UI loss. Both are
useful. If the project doesn't currently *need* the dense-UI case
working with the custom client (browser-use already handles those
fine), this experiment is curiosity-driven, not need-driven —
schedule it accordingly.

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
