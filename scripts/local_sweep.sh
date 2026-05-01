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
#
# Safety: only patches a runs.jsonl row when custom_agent.py actually
# appended one (compares row count before/after). On failure, leaves
# runs.jsonl untouched so unrelated history can't be corrupted.
set -euo pipefail

TASK="$1"
MODEL="$2"
QUANT="${3:-}"
N_RUNS="${4:-3}"
SWEEP_ID="2026-05-01-frontier-backfill"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RUNS_FILE="$REPO_ROOT/data/runs.jsonl"

# Pre-flight: fail fast if the task module doesn't exist for the runner this
# wrapper drives (custom_agent.py loads from scripts/custom_agent_tasks/).
# Without this, custom_agent.py fails per-run but the wrapper still loops
# through n attempts — wastes time and clutters logs.
TASK_FILE="$REPO_ROOT/scripts/custom_agent_tasks/${TASK}.py"
if [[ ! -f "$TASK_FILE" ]]; then
  echo "ERROR: task module not found: $TASK_FILE" >&2
  echo "Available custom_agent tasks:" >&2
  ls "$REPO_ROOT/scripts/custom_agent_tasks/"*.py 2>&1 | xargs -n1 basename | sed 's/\.py$//' >&2
  exit 2
fi

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

  # row count and screenshot mtime BEFORE the run, so we can detect whether
  # custom_agent.py actually produced new artifacts.
  ROWS_BEFORE=$(wc -l <"$RUNS_FILE" 2>/dev/null || echo 0)
  SHOT_MTIME_BEFORE=$(stat -c %Y /tmp/custom_agent_final.png 2>/dev/null || echo 0)

  DISPLAY=:0 XAUTHORITY=/run/user/1000/xauth_rVYaGJ XDG_RUNTIME_DIR=/run/user/1000 \
    PYTHONUNBUFFERED=1 MODEL="$MODEL" \
    "$REPO_ROOT/.venv/bin/python" -u "$REPO_ROOT/scripts/custom_agent.py" "$TASK" \
    >>"$RUN_DIR/smoke.log" 2>&1 || true

  ROWS_AFTER=$(wc -l <"$RUNS_FILE" 2>/dev/null || echo 0)
  SHOT_MTIME_AFTER=$(stat -c %Y /tmp/custom_agent_final.png 2>/dev/null || echo 0)

  # Only archive screenshot if it was freshly written by this run.
  if [[ -f /tmp/custom_agent_final.png && "$SHOT_MTIME_AFTER" -gt "$SHOT_MTIME_BEFORE" ]]; then
    cp /tmp/custom_agent_final.png "$RUN_DIR/final.png"
  fi

  # Only patch runs.jsonl if custom_agent.py appended exactly one new row.
  if [[ "$ROWS_AFTER" -eq $((ROWS_BEFORE + 1)) ]]; then
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
  else
    echo "WARN: custom_agent.py did not append a new row (rows: $ROWS_BEFORE -> $ROWS_AFTER); skipping patch" \
      | tee -a "$RUN_DIR/smoke.log"
  fi
done
