#!/usr/bin/env bash
# Pre-flight check for a sweep run. Verifies the local env is in a state
# where local_sweep.sh / thunder_sweep.sh / sweep_orchestrator.py can
# proceed without surprises.
#
# Usage:
#   bash scripts/preflight.sh
#
# Exits 0 with a summary if everything is in order; non-zero if a check
# failed (with a one-line reason on stderr).
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RC=0

ok()   { printf "  \033[32mOK\033[0m  %s\n" "$1"; }
fail() { printf "  \033[31mFAIL\033[0m %s\n" "$1"; RC=1; }
warn() { printf "  \033[33mWARN\033[0m %s\n" "$1"; }

echo "== local server =="
if curl -fsS --max-time 3 http://localhost:8080/health >/dev/null 2>&1; then
  alias=$(curl -fsS --max-time 3 http://localhost:8080/v1/models 2>/dev/null \
          | "$REPO_ROOT/.venv/bin/python" -c \
            "import json,sys; print(json.load(sys.stdin)['models'][0]['name'])" 2>/dev/null \
          || echo unknown)
  ok "vision-model.service responds at :8080 (alias=$alias)"
else
  warn "vision-model.service not responding at :8080 (start with: sudo bash scripts/swap_model.sh <model>)"
fi

echo
echo "== dispatcher patches =="
if grep -q "params\[\"text\"\].strip()" "$REPO_ROOT/scripts/harness_patches.py" 2>/dev/null; then
  ok "whitespace strip patch wired (UI-Venus 30B-A3B trailing-space fix)"
else
  fail "whitespace strip patch missing in scripts/harness_patches.py"
fi

if grep -qn "def harness_for" "$REPO_ROOT/scripts/custom_agent/__init__.py" 2>/dev/null; then
  ok "harness_for() selector present"
else
  fail "harness_for() not found in scripts/custom_agent/__init__.py"
fi

echo
echo "== task module inventory =="
echo "  scripts/custom_agent_tasks/ (custom_agent.py runner):"
ls "$REPO_ROOT/scripts/custom_agent_tasks/"*.py 2>/dev/null \
  | xargs -n1 basename | sed 's/\.py$//' | grep -v "^__" | sed 's/^/    /'
echo "  scripts/smokes/ (smoke_browser_use.py runner):"
ls "$REPO_ROOT/scripts/smokes/"*.py 2>/dev/null \
  | xargs -n1 basename | sed 's/\.py$//' | grep -v "^__" | sed 's/^/    /'

echo
echo "== runs.jsonl baseline =="
if [[ -f "$REPO_ROOT/data/runs.jsonl" ]]; then
  rows=$(wc -l <"$REPO_ROOT/data/runs.jsonl" 2>/dev/null || echo 0)
  ok "runs.jsonl present ($rows rows)"
else
  warn "runs.jsonl missing — first sweep will create it"
fi

echo
echo "== webapp grid coverage (current) =="
"$REPO_ROOT/.venv/bin/python" - <<PY
import json, yaml
from pathlib import Path
config = yaml.safe_load(Path("$REPO_ROOT/web/config.yaml").read_text())
model_ids = {m['id'] for m in config['models']}
test_ids = {t['id'] for tests in config['tests'].values() for t in tests}
runs = []
p = Path("$REPO_ROOT/data/runs.jsonl")
if p.is_file():
    runs = [json.loads(l) for l in p.read_text().splitlines() if l.strip()]
in_grid = {(r['model'],r['task']) for r in runs if r.get('model') in model_ids and r.get('task') in test_ids}
total = len(model_ids) * len(test_ids)
print(f"  {len(in_grid)}/{total} cells populated")
gaps = {(m,t) for m in model_ids for t in test_ids} - in_grid
if gaps:
    print(f"  gaps:")
    for m,t in sorted(gaps):
        print(f"    {m} / {t}")
PY

echo
echo "== /tmp ephemeral state =="
if [[ -f /tmp/custom_agent_final.png ]]; then
  age=$(( $(date +%s) - $(stat -c %Y /tmp/custom_agent_final.png) ))
  ok "/tmp/custom_agent_final.png present (${age}s old)"
else
  ok "/tmp/custom_agent_final.png absent (no stale screenshot)"
fi

echo
if [[ $RC -eq 0 ]]; then
  echo "preflight: OK — sweep is safe to start"
else
  echo "preflight: FAIL — fix the items above before sweeping" >&2
fi
exit $RC
