# Frontier Gap Backfill Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace every gray, single-datapoint, and prose-derived cell on the
findings webapp with clean per-run data (n≥3) sourced from real smoke runs,
covering both the local 16 GB GPU and a Thunder Compute A100 for the 72B cells.

**Architecture:** Local sweep drives 5 of the 6 grid models against the 9
canonical smokes via `scripts/custom_agent.py`, archiving artifacts under a
fresh `data/sweeps/2026-05-01-frontier-backfill/` tree. Thunder sweep drives
`qwen2.5-vl-72b-instruct` via `scripts/thunder/sweep.py`. All runs auto-append
clean rows to `data/runs.jsonl`; a post-step relinks `final_screenshot` to the
durable archive path so the webapp side panel populates. The 5 prose-derived
rows added on 2026-05-01 are removed once their cells have ≥3 truthful runs.

**Tech stack:** llama.cpp (Vulkan local / CUDA Thunder), CDP via
`custom_agent.py`, browser-use (where applicable), Thunder Compute MCP, GitHub
Pages deploy via `scripts/deploy_site.sh`.

**Pre-read:** `docs/findings.md` Phase 13 (lines 953–1083), Phase 15–16 (lines
~1900–2150), Phase 19a (lines 2865–2972), and Phase 20–22 (lines 3140–3431).
Cliff hypotheses are in `docs/thesis.md`.

---

## Cell inventory (33 cells × n=3 = 99 runs)

### Local — 28 cells
| Class | Test | Models needing runs |
|---|---|---|
| A | saucedemo_headed | ui-venus-1.5-8b (n=1 → bring to n=3), mai-ui-8b, ui-venus-1.5-30b-a3b, bu-30b-a3b-preview, holo3-35b-a3b |
| B | saucedemo_backpack_only | ui-venus-1.5-30b-a3b, bu-30b-a3b-preview |
| B | saucedemo_full_checkout | ui-venus-1.5-30b-a3b (prose-cleanup), bu-30b-a3b-preview (prose-cleanup), mai-ui-8b (prose-cleanup) |
| C | excalidraw_drag | ui-venus-1.5-8b, mai-ui-8b, ui-venus-1.5-30b-a3b, bu-30b-a3b-preview, holo3-35b-a3b |
| C | excalidraw_drag_v2 | ui-venus-1.5-8b, mai-ui-8b, ui-venus-1.5-30b-a3b, bu-30b-a3b-preview, holo3-35b-a3b |
| C | excalidraw_toolbar | ui-venus-1.5-8b, mai-ui-8b, ui-venus-1.5-30b-a3b, bu-30b-a3b-preview, holo3-35b-a3b |
| D | ikea_billy | ui-venus-1.5-30b-a3b, bu-30b-a3b-preview |
| D | ikea_search_add | ui-venus-1.5-30b-a3b, bu-30b-a3b-preview |
| D | bestbuy_airpods | ui-venus-1.5-30b-a3b, bu-30b-a3b-preview |

### Thunder — 5 cells (Qwen-72B Q4_K_M)
| Class | Test |
|---|---|
| A | saucedemo_headed |
| B | saucedemo_backpack_only |
| C | excalidraw_drag |
| C | excalidraw_drag_v2 |
| D | ikea_search_add |

(`qwen2.5-vl-72b-instruct` already has clean data for `saucedemo_full_checkout`,
`ikea_billy`, `bestbuy_airpods`. `excalidraw_toolbar` is deferred — Phase 22
showed visual-grounding cliff is already characterized via `drag_v2`.)

---

## Conventions for every cell

- **Sweep id:** `2026-05-01-frontier-backfill`. Per-cell artifacts under
  `data/sweeps/2026-05-01-frontier-backfill/<task>/<model>_<quant>/run-<N>/`
  containing `smoke.log`, `final.png`, `summary.json` (one entry).
- **n=3 per cell.** Three sequential invocations of `custom_agent.py`.
- **Durable screenshot:** after each run, copy `/tmp/custom_agent_final.png`
  into the run dir, then patch the trailing row of `data/runs.jsonl` so
  `final_screenshot` points at the archived copy. The aggregator skips
  `/tmp/*` paths, so without this step the webapp side panel stays empty.
- **Phase tag:** `phase=22-backfill` on every new row, so post-hoc filtering
  can isolate this batch.
- **Model swap:** `sudo bash scripts/swap_model.sh <model> [quant]` between
  models. Wait for `/health` before launching the smoke.
- **Headed Chromium env (local only):**
  ```
  DISPLAY=:0 XAUTHORITY=/run/user/1000/xauth_rVYaGJ XDG_RUNTIME_DIR=/run/user/1000
  ```
- **Logging discipline:** redirect smoke stdout to a file under the run dir,
  never pipe through `tail` (CLAUDE.md operational rule 2).

A small helper, `scripts/local_sweep.sh`, is added in Task 0.3 so individual
cells become a one-line invocation. The same helper is used by every local
task.

---

## Phase 0 — Pre-flight (local, no billing)

### Task 0.1: Snapshot baseline grid coverage

**Files:** none modified. Read-only.

**Step 1:** Capture pre-backfill cell counts to a one-off report.
```
.venv/bin/python - <<'PY'
import json, yaml
from pathlib import Path
from collections import defaultdict
config = yaml.safe_load(Path('web/config.yaml').read_text())
runs = [json.loads(l) for l in Path('data/runs.jsonl').read_text().splitlines() if l.strip()]
print(f'baseline rows: {len(runs)}')
populated = {(r['model'],r['task']) for r in runs if r.get('model') and r.get('task')}
total = len(config['models']) * sum(len(v) for v in config['tests'].values())
print(f'populated cells: {len(populated)} / {total}')
PY
```

**Expected:** baseline rows: 123, populated cells: 21 / 54.

**Commit:** none (read-only).

---

### Task 0.2: Verify dispatcher + harness patches are active

**Files:** read `scripts/harness_patches.py`, `scripts/custom_agent/__init__.py`.

**Step 1:** Confirm whitespace strip is wired.
```
grep -n "strip\|whitespace" scripts/harness_patches.py
```
Expected: at least one match referencing `input.text` or `Registry.execute_action`.

**Step 2:** Confirm per-model harness selector exists.
```
grep -rn "harness_for\|HARNESS_FOR" scripts/custom_agent/
```
Expected: function `harness_for(MODEL)` returning one of `uivenus|toolcall|holo3|qwenvl`.

**Step 3:** Smoke the local server is healthy before any run.
```
curl -fsS http://localhost:8080/health
```
Expected: HTTP 200.

**Commit:** none.

---

### Task 0.3: Add `scripts/local_sweep.sh` (one-cell wrapper)

**Files:**
- Create: `scripts/local_sweep.sh`

**Step 1:** Write the wrapper.

```bash
#!/usr/bin/env bash
# Run one local smoke cell with durable artifact archiving.
#
# Usage:
#   bash scripts/local_sweep.sh <task> <model_alias> [quant] [n_runs]
#
# Effect:
#   - swaps model
#   - runs custom_agent.py <task> N times (default N=3)
#   - archives /tmp/custom_agent_final.png into data/sweeps/2026-05-01-frontier-backfill/...
#   - patches the last N rows of data/runs.jsonl so final_screenshot points
#     at the archived files (overwriting the ephemeral /tmp path) and adds
#     phase=22-backfill.
set -euo pipefail

TASK="$1"
MODEL="$2"
QUANT="${3:-}"
N_RUNS="${4:-3}"
SWEEP_ID="2026-05-01-frontier-backfill"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

if [[ -n "$QUANT" ]]; then
  sudo bash "$REPO_ROOT/scripts/swap_model.sh" "$MODEL" "$QUANT"
else
  sudo bash "$REPO_ROOT/scripts/swap_model.sh" "$MODEL"
fi

# wait for /health
for _ in $(seq 1 60); do
  if curl -fsS http://localhost:8080/health >/dev/null 2>&1; then break; fi
  sleep 2
done

ALIAS_FOR_DIR="${MODEL}${QUANT:+_$QUANT}"
CELL_DIR="$REPO_ROOT/data/sweeps/$SWEEP_ID/$TASK/$ALIAS_FOR_DIR"
mkdir -p "$CELL_DIR"

for i in $(seq 1 "$N_RUNS"); do
  RUN_DIR="$CELL_DIR/run-$i"
  mkdir -p "$RUN_DIR"
  echo ">>> $TASK / $MODEL${QUANT:+ ($QUANT)} / run $i" | tee -a "$RUN_DIR/smoke.log"
  DISPLAY=:0 XAUTHORITY=/run/user/1000/xauth_rVYaGJ XDG_RUNTIME_DIR=/run/user/1000 \
    PYTHONUNBUFFERED=1 MODEL="$MODEL" \
    "$REPO_ROOT/.venv/bin/python" -u "$REPO_ROOT/scripts/custom_agent.py" "$TASK" \
    >>"$RUN_DIR/smoke.log" 2>&1 || true
  if [[ -f /tmp/custom_agent_final.png ]]; then
    cp /tmp/custom_agent_final.png "$RUN_DIR/final.png"
  fi

  # patch the last row of runs.jsonl: final_screenshot -> archived path,
  # phase -> 22-backfill, sweep_id -> $SWEEP_ID
  ARCHIVED="$RUN_DIR/final.png"
  "$REPO_ROOT/.venv/bin/python" - "$ARCHIVED" "$SWEEP_ID" <<'PY'
import json, sys
from pathlib import Path
archived, sweep_id = sys.argv[1], sys.argv[2]
p = Path('data/runs.jsonl')
lines = p.read_text().splitlines()
if not lines:
    raise SystemExit("runs.jsonl unexpectedly empty")
last = json.loads(lines[-1])
if Path(archived).is_file():
    last['final_screenshot'] = archived
last['phase'] = '22-backfill'
last['sweep_id'] = sweep_id
lines[-1] = json.dumps(last)
p.write_text('\n'.join(lines) + '\n')
PY
done
```

**Step 2:** Make executable.
```
chmod +x scripts/local_sweep.sh
```

**Step 3:** Smoke-test on a fast cell (no commit yet — verify behavior).
```
bash scripts/local_sweep.sh excalidraw_drag ui-venus-1.5-8b "" 1
```
Expected:
- model swap completes within 60 s
- one new row appended to `data/runs.jsonl` with `phase=22-backfill`,
  `sweep_id=2026-05-01-frontier-backfill`, `final_screenshot=data/sweeps/.../run-1/final.png`
- `data/sweeps/2026-05-01-frontier-backfill/excalidraw_drag/ui-venus-1.5-8b/run-1/{smoke.log,final.png}` exist.

If the smoke run fails (no row appended, screenshot missing), fix the wrapper before proceeding — every later task depends on this contract.

**Step 4:** Roll back the smoke-test row + dir before committing.
```
sed -i '$d' data/runs.jsonl
rm -rf data/sweeps/2026-05-01-frontier-backfill/excalidraw_drag/ui-venus-1.5-8b/
```

**Step 5:** Commit.
```
git add scripts/local_sweep.sh
git commit -m "feat(sweep): scripts/local_sweep.sh — one-cell archiving wrapper"
```

---

## Phase 1 — Local sweep, ui-venus-1.5-8b row (4 cells)

Existing data: A (n=1), C (3 gaps). Goal: bring all 4 cells to n=3 truthful.

### Task 1.1: Run all 4 cells

**Files:** appends to `data/runs.jsonl`; new dirs under
`data/sweeps/2026-05-01-frontier-backfill/`.

**Step 1:** Run each smoke n=3.
```
for TASK in saucedemo_headed excalidraw_drag excalidraw_drag_v2 excalidraw_toolbar; do
  bash scripts/local_sweep.sh "$TASK" ui-venus-1.5-8b "" 3
done
```

**Step 2:** Verify 12 new rows landed.
```
.venv/bin/python -c "
import json
from pathlib import Path
runs = [json.loads(l) for l in Path('data/runs.jsonl').read_text().splitlines() if l.strip()]
new = [r for r in runs if r.get('phase')=='22-backfill' and r.get('model')=='ui-venus-1.5-8b']
print(len(new))
"
```
Expected: 12.

**Step 3:** Spot-check final.png for one excalidraw run (not all — sample).
```
ls data/sweeps/2026-05-01-frontier-backfill/excalidraw_drag/ui-venus-1.5-8b/run-1/final.png
```

**Step 4:** Commit.
```
git add data/runs.jsonl data/sweeps/2026-05-01-frontier-backfill/
git commit -m "data(backfill): ui-venus-1.5-8b — 4 cells × n=3 (Phase 22-backfill)"
```

---

## Phase 2 — Local sweep, mai-ui-8b row (5 cells)

Existing: 5/9 covered. Gaps: saucedemo_headed + 3 excalidraw + saucedemo_full_checkout (prose-cleanup).

### Task 2.1: Run all 5 cells

**Step 1:**
```
for TASK in saucedemo_headed saucedemo_full_checkout excalidraw_drag excalidraw_drag_v2 excalidraw_toolbar; do
  bash scripts/local_sweep.sh "$TASK" mai-ui-8b "" 3
done
```

**Step 2:** Verify 15 new rows for `mai-ui-8b` with `phase=22-backfill`.

**Step 3:** Commit.
```
git commit -am "data(backfill): mai-ui-8b — 5 cells × n=3 (Phase 22-backfill)"
```

---

## Phase 3 — Local sweep, ui-venus-1.5-30b-a3b row (8 cells)

Existing: 1/9 (prose-only). Gaps: 8 (everything except saucedemo_full_checkout-prose, which gets re-run too).

⚠ Whitespace-strip patch must be active (Task 0.2 confirmed). Without it,
saucedemo runs will fail at login due to the trailing-space bug.

### Task 3.1: Pre-swap probe

Run the validation harness against UV30 to catch coord-space regressions before spending an hour of runs.
```
sudo bash scripts/swap_model.sh ui-venus-1.5-30b-a3b
.venv/bin/python scripts/thunder/validate_harness.py --model ui-venus-1.5-30b-a3b
```
Expected: parses one synthetic step, prints Action, exits 0.

### Task 3.2: Run all 9 cells (8 gaps + 1 prose-cleanup)

```
for TASK in saucedemo_headed saucedemo_backpack_only saucedemo_full_checkout \
            excalidraw_drag excalidraw_drag_v2 excalidraw_toolbar \
            ikea_billy ikea_search_add bestbuy_airpods; do
  bash scripts/local_sweep.sh "$TASK" ui-venus-1.5-30b-a3b "" 3
done
```

⚠ `bestbuy_airpods` may take 5–10 min/run on a 30B-A3B. Total wall clock for
this task: ~1.5 h.

### Task 3.3: Commit
```
git commit -am "data(backfill): ui-venus-1.5-30b-a3b — 9 cells × n=3"
```

---

## Phase 4 — Local sweep, bu-30b-a3b-preview row (8 cells)

Same shape as Phase 3, harness=toolcall path.

### Task 4.1: Pre-swap probe
```
sudo bash scripts/swap_model.sh bu-30b-a3b-preview
.venv/bin/python scripts/thunder/validate_harness.py --model bu-30b-a3b-preview
```

### Task 4.2: Run all 9 cells
```
for TASK in saucedemo_headed saucedemo_backpack_only saucedemo_full_checkout \
            excalidraw_drag excalidraw_drag_v2 excalidraw_toolbar \
            ikea_billy ikea_search_add bestbuy_airpods; do
  bash scripts/local_sweep.sh "$TASK" bu-30b-a3b-preview "" 3
done
```

⚠ Phase 13 (`findings.md:1059–1062`) noted bu-30b emits wrong drag params
(`start_x` instead of `x1`). Expect excalidraw_drag fails. That's truthful data.

### Task 4.3: Commit
```
git commit -am "data(backfill): bu-30b-a3b-preview — 9 cells × n=3"
```

---

## Phase 5 — Local sweep, holo3-35b-a3b row (4 cells)

Existing: 5/9 covered. Gaps: saucedemo_headed + 3 excalidraw.

### Task 5.1: Run all 4 cells
```
sudo bash scripts/swap_model.sh holo3-35b-a3b
for TASK in saucedemo_headed excalidraw_drag excalidraw_drag_v2 excalidraw_toolbar; do
  bash scripts/local_sweep.sh "$TASK" holo3-35b-a3b "" 3
done
```

⚠ Existing `data/sweeps/20260501-010141/` already has 3 holo3 IQ3_XXS
excalidraw_drag runs. The Phase 22 visual reread (`findings.md:3380`)
reclassified them PASS. Re-running with the smoke runner gets us clean
runs.jsonl rows; the older sweep can be left in place as historical record.

### Task 5.2: Commit
```
git commit -am "data(backfill): holo3-35b-a3b — 4 cells × n=3"
```

---

## Phase 6 — Thunder provisioning

⚠ **PAUSE here for user confirmation before any of Phase 6/7.** Provisioning
starts the meter (~$1.10/hr A100). Per CLAUDE.md, provisioning + teardown
stay user-confirmable under auto mode.

### Task 6.1: Choose provision path

Two options. The agent should call `mcp__thunder-compute__list_snapshots` and
present the result, then ask the user which path:

- **A. Restore from snapshot.** If a recent (≤2 weeks) snapshot of a
  bootstrapped instance exists, restore it. Faster (~8.5 min) and cheaper.
- **B. Cold provision.** No usable snapshot → call `create_instance` with
  `gpu_type=a100xl_x1`, `mode=prototyping`, `template=cuda12-9`, vcpu=8,
  disk=150 GB. Then run `scripts/thunder/bootstrap_instance.sh` (~30 min).

### Task 6.2: After RUNNING, validate path

```
ssh thunder 'nvidia-smi --query-gpu=name --format=csv,noheader'
ssh thunder 'ls /ephemeral/models/qwen2.5-vl-72b-instruct/ | head'
```
Expected: A100, GGUF + mmproj-f16 visible.

If GGUF missing (cold instance), `bash scripts/thunder/bootstrap_instance.sh`
to fetch.

### Task 6.3: Open SSH tunnel + serve

```
ssh -fN -L 8080:localhost:8080 thunder
bash scripts/thunder/swap_model_remote.sh thunder qwen2.5-vl-72b-instruct Q4_K_M
curl -fsS http://localhost:8080/health
```

⚠ Phase 21 (`findings.md` lessons) burned $0.50 on a misaligned harness.
Always run `validate_harness.py` after the remote swap and BEFORE starting
any sweep:
```
.venv/bin/python scripts/thunder/validate_harness.py --model qwen2.5-vl-72b-instruct
```
If parse error or coord-space mismatch, stop and fix before sweeping.

---

## Phase 7 — Thunder sweep, qwen-72B (5 cells)

### Task 7.1: Run sweep via `scripts/thunder/sweep.py`

`sweep.py` already does swap → tunnel-check → smoke → archive
`{swap.log, smoke.log, final.png}` to
`data/sweeps/<run_id>/qwen2.5-vl-72b-instruct_Q4_K_M/`. It also drops a
proper `summary.json`.

```
for TASK in saucedemo_headed saucedemo_backpack_only \
            excalidraw_drag excalidraw_drag_v2 \
            ikea_search_add; do
  .venv/bin/python scripts/thunder/sweep.py \
    --ssh thunder \
    --task "$TASK" \
    --model qwen2.5-vl-72b-instruct \
    --quant Q4_K_M \
    --n-runs 3 \
    --sweep-id 2026-05-01-frontier-backfill
done
```

⚠ `bestbuy_airpods`-style cart tasks are *not* in this list — Phase 21 already
covered the qwen-72B class-D cart cells with clean data.

### Task 7.2: Confirm runs.jsonl has 15 new qwen rows

```
.venv/bin/python -c "
import json
from pathlib import Path
runs = [json.loads(l) for l in Path('data/runs.jsonl').read_text().splitlines() if l.strip()]
new = [r for r in runs if r.get('phase')=='22-backfill' and r.get('model')=='qwen2.5-vl-72b-instruct']
print(len(new))
"
```
Expected: 15.

If `sweep.py` archives summary.json but doesn't append to runs.jsonl directly,
add a one-shot step to translate the summary into runs.jsonl rows (matching
the existing `harness=qwenvl` schema, with `final_screenshot` pointing at the
archived path). Specifically:
```
.venv/bin/python - <<'PY'
import json, datetime as dt
from pathlib import Path

SWEEP_ID = '2026-05-01-frontier-backfill'
sweep_root = Path(f'data/sweeps/{SWEEP_ID}')
out = Path('data/runs.jsonl')
TASK_CLASS = {
    'saucedemo_headed': 'A', 'saucedemo_backpack_only': 'B',
    'saucedemo_full_checkout': 'B',
    'excalidraw_drag': 'C', 'excalidraw_drag_v2': 'C', 'excalidraw_toolbar': 'C',
    'ikea_billy': 'D', 'ikea_search_add': 'D', 'bestbuy_airpods': 'D',
}

added = 0
with out.open('a') as f:
    for summary_path in sorted(sweep_root.glob('*/summary.json')):
        s = json.loads(summary_path.read_text())
        task = s['task']
        for r in s.get('results', []):
            row = {
                'task': task,
                'task_class': TASK_CLASS[task],
                'model': r['model'],
                'harness': 'qwenvl',
                'outcome': r.get('outcome'),
                'category': r.get('category', r.get('outcome')),
                'steps': r.get('agent_steps', r.get('steps')),
                'elapsed_s': r.get('duration_s'),
                'final_screenshot': r.get('screenshot_path'),
                'ts': r.get('ts', dt.datetime.utcnow().isoformat(timespec='seconds')),
                'phase': '22-backfill',
                'sweep_id': SWEEP_ID,
            }
            f.write(json.dumps(row) + '\n')
            added += 1
print(f'added {added} rows from sweep summaries')
PY
```

### Task 7.3: Commit
```
git commit -am "data(backfill): qwen2.5-vl-72b-instruct — 5 cells × n=3 (Thunder)"
```

### Task 7.4: Teardown (REQUIRES USER CONFIRMATION)

⚠ Per CLAUDE.md: snapshot-then-delete is the default teardown. Snapshot
**requires the UUID, not the integer instance_id**.

Sequence (after user confirms):
1. `mcp__thunder-compute__list_instances` → grab the `uuid` of the running
   instance.
2. `mcp__thunder-compute__create_snapshot` with that UUID. Wait for ready.
3. `mcp__thunder-compute__delete_instance` with the integer ID.

---

## Phase 8 — Data hygiene + deploy

### Task 8.1: Remove the 5 prose-derived rows

The 2026-05-01 prose backfill is now superseded by clean re-runs. Drop those
rows so each cell tells a single, consistent story.

```
.venv/bin/python - <<'PY'
import json
from pathlib import Path
p = Path('data/runs.jsonl')
kept, dropped = [], 0
for line in p.read_text().splitlines():
    if not line.strip():
        continue
    r = json.loads(line)
    if 'source' in r and r.get('source','').startswith('docs/findings.md:'):
        dropped += 1
        continue
    kept.append(line)
p.write_text('\n'.join(kept) + '\n')
print(f'dropped {dropped} prose rows; kept {len(kept)}')
PY
```
Expected: dropped 5; kept 213 (123 baseline – 5 prose + 84 local-Phase 22-backfill + 15 thunder).

### Task 8.2: Rebuild webapp + verify
```
.venv/bin/python scripts/build_site.py
```
Expected: `Wrote .../web/index.html — 54 cells` (every grid cell now populated).

Spot-check locally:
```
.venv/bin/python -m http.server --directory web 8000
# open http://localhost:8000 — every cell should be colored, side panel should
# show real thumbnails (not the gray "no screenshot" placeholder).
```

### Task 8.3: Commit + deploy
```
git commit -am "data(hygiene): drop 5 prose-derived rows; webapp now n≥3 every cell"
bash scripts/deploy_site.sh
```

### Task 8.4: Update findings.md

Append a Phase 22-backfill section to `docs/findings.md` recording:
- date, sweep id, n=99 runs total
- per-cell summary table (k/n) — generated from runs.jsonl
- which cliff hypotheses were confirmed/refuted by the new data

This is per the project's "maintain a progressive findings trail" rule.

```
git commit -am "docs(findings): Phase 22-backfill summary"
git push origin main
```

---

## Cost + time estimate

| Phase | Wall clock | $ |
|---|---|---|
| 0 — pre-flight | 15 min | 0 |
| 1 — ui-venus-1.5-8b (4 cells × 3) | ~30 min | 0 |
| 2 — mai-ui-8b (5 × 3) | ~45 min | 0 |
| 3 — ui-venus-1.5-30b-a3b (9 × 3) | ~90 min | 0 |
| 4 — bu-30b-a3b-preview (9 × 3) | ~90 min | 0 |
| 5 — holo3-35b-a3b (4 × 3) | ~45 min | 0 |
| 6 — Thunder provision | 15–30 min (snapshot) / ~45 min (cold) | $0.30–0.85 |
| 7 — Thunder sweep (5 × 3 × ~3 min) | ~60 min | $1.10 |
| 8 — hygiene + deploy | 15 min | 0 |
| **Total** | **~6.5 h** | **~$1.50–2.00** |

The local portion is the dominant time cost. It can be left running
overnight (each phase is independent — interruption between phases just
means resuming at the next model swap).

---

## Don'ts

- **Don't skip `validate_harness.py` after a model swap.** Phase 21 lost
  $0.50 and several iterations on this exact mistake.
- **Don't use snapshot integer ID with `create_snapshot`.** Use the UUID;
  see memory `feedback_thunder_snapshot_uuid.md`.
- **Don't push --no-verify.** Hooks must pass. If they fail, fix the
  issue and create a new commit (not amend).
- **Don't tear down Thunder before Task 7.2 confirms 15 rows.** If the
  ingestion failed silently, you'll have to re-provision.
- **Don't leave the Thunder instance running past Phase 7.** Prototyping
  mode auto-stops on idle but billing continues until snapshot+delete.
- **Don't claim cells are filled without rebuilding the webapp.** Task 8.2
  is mandatory verification — `runs.jsonl` having rows ≠ webapp showing
  the cell.
