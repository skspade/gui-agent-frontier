#!/usr/bin/env bash
# Run one Thunder-backed smoke cell with durable artifact archiving.
#
# Mirror of scripts/local_sweep.sh but for a remote llama-server via SSH
# tunnel. Caller handles tunnel lifecycle and remote-server lifecycle:
# this script assumes the SSH tunnel from local 8080 -> remote 8080 is
# already open and the remote server is serving $MODEL.
#
# Usage:
#   bash scripts/thunder_sweep.sh <task> <model_alias> <quant> [n_runs]
#
# Effect:
#   - runs custom_agent.py <task> N times against localhost:8080 (tunneled)
#   - archives /tmp/custom_agent_final.png into
#     data/sweeps/2026-05-01-frontier-backfill/<task>/<model>_<quant>/run-<i>/
#   - patches the trailing N rows of data/runs.jsonl so final_screenshot
#     points at the durable archive, adds phase=22-backfill, sweep_id, and
#     a thunder=1 marker.
#
# Safety: only patches a runs.jsonl row when custom_agent.py actually
# appended one (compares row count before/after). On failure, leaves
# runs.jsonl untouched.
set -euo pipefail

TASK="$1"
MODEL="$2"
QUANT="$3"
N_RUNS="${4:-3}"
SWEEP_ID="2026-05-01-frontier-backfill"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RUNS_FILE="$REPO_ROOT/data/runs.jsonl"

# Pre-flight: tunnel must be up and the remote server must answer /health.
if ! curl -fsS --max-time 5 http://localhost:8080/health >/dev/null 2>&1; then
  echo "ERROR: localhost:8080 not responding. Open the SSH tunnel and load \$MODEL on Thunder first." >&2
  exit 2
fi

ALIAS_FOR_DIR="${MODEL}_${QUANT}"
CELL_DIR="$REPO_ROOT/data/sweeps/$SWEEP_ID/$TASK/$ALIAS_FOR_DIR"
mkdir -p "$CELL_DIR"

for i in $(seq 1 "$N_RUNS"); do
  RUN_DIR="$CELL_DIR/run-$i"
  mkdir -p "$RUN_DIR"
  echo ">>> $TASK / $MODEL ($QUANT) / run $i (thunder)" | tee -a "$RUN_DIR/smoke.log"

  ROWS_BEFORE=$(wc -l <"$RUNS_FILE" 2>/dev/null || echo 0)
  SHOT_MTIME_BEFORE=$(stat -c %Y /tmp/custom_agent_final.png 2>/dev/null || echo 0)

  PYTHONUNBUFFERED=1 MODEL="$MODEL" \
    "$REPO_ROOT/.venv/bin/python" -u "$REPO_ROOT/scripts/custom_agent.py" "$TASK" \
    >>"$RUN_DIR/smoke.log" 2>&1 || true

  ROWS_AFTER=$(wc -l <"$RUNS_FILE" 2>/dev/null || echo 0)
  SHOT_MTIME_AFTER=$(stat -c %Y /tmp/custom_agent_final.png 2>/dev/null || echo 0)

  if [[ -f /tmp/custom_agent_final.png && "$SHOT_MTIME_AFTER" -gt "$SHOT_MTIME_BEFORE" ]]; then
    cp /tmp/custom_agent_final.png "$RUN_DIR/final.png"
  fi

  if [[ "$ROWS_AFTER" -eq $((ROWS_BEFORE + 1)) ]]; then
    ARCHIVED="$RUN_DIR/final.png"
    "$REPO_ROOT/.venv/bin/python" - "$ARCHIVED" "$SWEEP_ID" "$QUANT" <<'PY'
import json, sys
from pathlib import Path
archived, sweep_id, quant = sys.argv[1], sys.argv[2], sys.argv[3]
p = Path('data/runs.jsonl')
lines = p.read_text().splitlines()
if not lines:
    raise SystemExit("runs.jsonl unexpectedly empty")
last = json.loads(lines[-1])
if Path(archived).is_file():
    last['final_screenshot'] = archived
last['phase'] = '22-backfill'
last['sweep_id'] = sweep_id
last['quant'] = quant
last['thunder'] = True
lines[-1] = json.dumps(last)
p.write_text('\n'.join(lines) + '\n')
PY
  else
    echo "WARN: custom_agent.py did not append a new row (rows: $ROWS_BEFORE -> $ROWS_AFTER); skipping patch" \
      | tee -a "$RUN_DIR/smoke.log"
  fi
done
