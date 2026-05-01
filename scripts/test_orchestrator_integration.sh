#!/usr/bin/env bash
# Integration test for sweep_orchestrator.py — drives BOTH the local and
# thunder branches end-to-end against the already-running local
# llama-server. No remote SSH, no Thunder billing.
#
# Run BEFORE the next Thunder sweep to confirm the orchestrator behavior
# matches expectations. Cleans up after itself (rolls back appended rows
# and removes test sweep dirs).
#
# Exits 0 on green; non-zero on any failed assertion.
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

SWEEP_ID="orchestrator-integration-$(date +%Y%m%d-%H%M%S)"
RC=0

ok()   { printf "  \033[32mOK\033[0m  %s\n" "$1"; }
fail() { printf "  \033[31mFAIL\033[0m %s\n" "$1"; RC=1; }

cleanup() {
  echo
  echo "== cleanup =="
  .venv/bin/python - "$SWEEP_ID" <<'PY'
import json, sys
from pathlib import Path
sweep_id_prefix = sys.argv[1]
p = Path('data/runs.jsonl')
lines = [l for l in p.read_text().splitlines() if l.strip()]
kept = [l for l in lines if not str(json.loads(l).get('sweep_id', '')).startswith(sweep_id_prefix)]
p.write_text('\n'.join(kept) + '\n')
print(f"  removed {len(lines) - len(kept)} test rows from runs.jsonl")
PY
  rm -rf "data/sweeps/$SWEEP_ID-local" "data/sweeps/$SWEEP_ID-thunder" "data/sweeps/$SWEEP_ID-failfast"
  echo "  removed test sweep dirs"
}
trap cleanup EXIT

echo "== preflight =="
if ! curl -fsS --max-time 3 http://localhost:8080/health >/dev/null 2>&1; then
  fail "localhost:8080 not responding — start vision-model.service first"
  exit 1
fi
ok "local llama-server healthy"

echo
echo "== test 1: --target local end-to-end =="
.venv/bin/python scripts/sweep_orchestrator.py \
    --target local --skip-swap \
    --task excalidraw_drag \
    --model ui-venus-1.5-8b \
    --n 1 \
    --sweep-id "$SWEEP_ID-local" \
    > /tmp/orch_test_local.log 2>&1
LOCAL_RC=$?
if [[ $LOCAL_RC -ne 0 ]]; then
  fail "local orchestrator exit=$LOCAL_RC; see /tmp/orch_test_local.log"
else
  ok "local orchestrator exit 0"
fi

# Validate the row landed correctly
.venv/bin/python - "$SWEEP_ID-local" <<'PY' || RC=1
import json, sys
from pathlib import Path
sweep_id = sys.argv[1]
runs = [json.loads(l) for l in Path('data/runs.jsonl').read_text().splitlines() if l.strip()]
row = next((r for r in reversed(runs) if r.get('sweep_id') == sweep_id), None)
assert row is not None, "no row with this sweep_id"
assert row['model'] == 'ui-venus-1.5-8b', f"wrong model: {row['model']}"
assert row['task'] == 'excalidraw_drag', f"wrong task: {row['task']}"
assert row['sweep_id'] == sweep_id
assert 'thunder' not in row, "local row should NOT have thunder marker"
assert not row['final_screenshot'].startswith('/tmp/'), "screenshot path should be durable"
assert Path(row['final_screenshot']).is_file(), "archived screenshot missing"
print(f"  row OK: cat={row['category']} verif_px={row.get('verification_pixel_count')}")
PY
[[ $? -eq 0 ]] && ok "local row validated (thunder marker absent, durable screenshot)"

echo
echo "== test 2: --target thunder dry-run end-to-end =="
.venv/bin/python scripts/sweep_orchestrator.py \
    --target thunder --skip-swap \
    --task excalidraw_drag \
    --model ui-venus-1.5-8b \
    --quant Q6_K \
    --ssh-alias dummy-not-used \
    --n 1 \
    --sweep-id "$SWEEP_ID-thunder" \
    > /tmp/orch_test_thunder.log 2>&1
THUNDER_RC=$?
if [[ $THUNDER_RC -ne 0 ]]; then
  fail "thunder orchestrator exit=$THUNDER_RC; see /tmp/orch_test_thunder.log"
else
  ok "thunder orchestrator exit 0"
fi

# Validate the thunder marker landed
.venv/bin/python - "$SWEEP_ID-thunder" <<'PY' || RC=1
import json, sys
from pathlib import Path
sweep_id = sys.argv[1]
runs = [json.loads(l) for l in Path('data/runs.jsonl').read_text().splitlines() if l.strip()]
row = next((r for r in reversed(runs) if r.get('sweep_id') == sweep_id), None)
assert row is not None, "no row with this sweep_id"
assert row.get('thunder') is True, "thunder row MUST have thunder=True marker"
assert row.get('quant') == 'Q6_K', f"thunder row should record quant: {row.get('quant')}"
assert not row['final_screenshot'].startswith('/tmp/'), "screenshot path should be durable"
assert Path(row['final_screenshot']).is_file(), "archived screenshot missing"
print(f"  row OK: thunder=True quant={row['quant']} cat={row['category']}")
PY
[[ $? -eq 0 ]] && ok "thunder row validated (thunder=True, quant recorded, durable screenshot)"

echo
echo "== test 3: fail-fast on missing task (no swap, no run) =="
.venv/bin/python scripts/sweep_orchestrator.py \
    --target thunder --skip-swap \
    --task definitely_not_a_real_task \
    --model ui-venus-1.5-8b \
    --quant Q6_K \
    --ssh-alias dummy \
    --n 1 \
    --sweep-id "$SWEEP_ID-failfast" \
    > /tmp/orch_test_failfast.log 2>&1
FF_RC=$?
if [[ $FF_RC -eq 1 ]]; then
  ok "missing task exits 1 cleanly"
else
  fail "missing task should exit 1, got $FF_RC"
fi
if grep -q "task module not found" /tmp/orch_test_failfast.log; then
  ok "error message helpful"
else
  fail "fail-fast did not produce expected error message"
fi

echo
if [[ $RC -eq 0 ]]; then
  echo "integration: ALL GREEN — orchestrator safe to drive Thunder"
else
  echo "integration: FAILURES — fix before running Thunder" >&2
fi
exit $RC
