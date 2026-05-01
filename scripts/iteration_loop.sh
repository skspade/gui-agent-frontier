#!/usr/bin/env bash
# Autonomous harness-hardening loop. Spawns one `claude --print` per
# iteration with a restricted tool whitelist; the deterministic driver
# (scripts/iteration_step.py) decides commit-or-revert based on the
# regression suite's before/after delta.
#
# Usage:
#   bash scripts/iteration_loop.sh [--max N] [--branch NAME]
#
# Defaults: --max 20, branch=harness-loop/<timestamp>.
set -euo pipefail

MAX=20
BRANCH=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --max)
            [[ $# -ge 2 ]] || { echo "--max requires a value" >&2; exit 1; }
            MAX="$2"; shift 2;;
        --branch)
            [[ $# -ge 2 ]] || { echo "--branch requires a value" >&2; exit 1; }
            BRANCH="$2"; shift 2;;
        *) echo "unknown flag: $1" >&2; exit 1;;
    esac
done

if ! [[ "$MAX" =~ ^[1-9][0-9]*$ ]]; then
    echo "--max must be a positive integer; got: $MAX" >&2
    exit 1
fi

REPO_ROOT="$(git rev-parse --show-toplevel)"
TS="$(date -u +%Y%m%dT%H%M%SZ)"
BRANCH="${BRANCH:-harness-loop/${TS}}"
WORKTREE="${REPO_ROOT}/../vision-model-harness-loop-${TS}"

cleanup() {
    local rc=$?
    if [[ -n "${WORKTREE:-}" && -d "$WORKTREE" && $rc -ne 0 ]]; then
        echo "loop aborted (rc=$rc); worktree preserved at $WORKTREE for inspection" >&2
        echo "to remove: git -C $REPO_ROOT worktree remove --force $WORKTREE && git -C $REPO_ROOT branch -D $BRANCH" >&2
    fi
}
trap cleanup EXIT
LEARNINGS="${WORKTREE}/learnings.md"
REPORT="${WORKTREE}/reports/iteration_loop_${TS}.md"
PROMPT_USER_TMPL="${REPO_ROOT}/prompts/loop_user.md.tmpl"
PROMPT_SYSTEM="${REPO_ROOT}/prompts/loop_system.md"

# Pre-flight
command -v claude >/dev/null 2>&1 || { echo "claude CLI missing" >&2; exit 1; }
[[ -f "$PROMPT_SYSTEM" ]] || { echo "prompts/loop_system.md missing" >&2; exit 1; }
[[ -f "$PROMPT_USER_TMPL" ]] || { echo "prompts/loop_user.md.tmpl missing" >&2; exit 1; }
[[ -x "${REPO_ROOT}/.venv/bin/python" ]] || { echo ".venv/bin/python missing in REPO_ROOT" >&2; exit 1; }

# Worktree on a fresh branch
git -C "$REPO_ROOT" worktree add -b "$BRANCH" "$WORKTREE" HEAD
mkdir -p "${WORKTREE}/reports"

# .venv is gitignored, so the fresh worktree has no virtualenv. Symlink the
# main repo's so ${WORKTREE}/.venv/bin/python resolves transparently.
ln -s "${REPO_ROOT}/.venv" "${WORKTREE}/.venv"

{
    echo "# Harness Iteration Loop — Run ${TS}"
    echo "Branch: ${BRANCH}"
    echo "Max iterations: ${MAX}"
    echo
} > "$LEARNINGS"

ALLOWED_TOOLS='Read,Grep,Glob,Edit,Bash(.venv/bin/python -u scripts/regression_suite.py:*),Bash(.venv/bin/python -u scripts/regression_suite.py *:*),Bash(git diff:*),Bash(git status:*)'

prev_all_green=0

for ((i=1; i<=MAX; i++)); do
    echo "=== Iteration $i / $MAX ===" | tee -a "$LEARNINGS" >&2
    BEFORE="${WORKTREE}/.iter/${i}_before.json"
    AFTER="${WORKTREE}/.iter/${i}_after.json"
    TRANSCRIPT="${WORKTREE}/.iter/${i}_transcript.json"
    mkdir -p "$(dirname "$BEFORE")"

    # Snapshot suite BEFORE
    set +e
    "${WORKTREE}/.venv/bin/python" -u "${WORKTREE}/scripts/regression_suite.py" --out "$BEFORE"
    before_rc=$?
    set -e

    if [[ $before_rc -eq 0 && $prev_all_green -eq 1 ]]; then
        echo "Two consecutive green iterations — stopping early." | tee -a "$LEARNINGS"
        break
    fi
    if [[ $before_rc -eq 0 ]]; then
        prev_all_green=1
    else
        prev_all_green=0
    fi

    # Read log_dir from BEFORE for the prompt
    LOG_DIR=$("${WORKTREE}/.venv/bin/python" -c "import json,sys; print(json.load(open(sys.argv[1]))['log_dir'])" "$BEFORE")

    # Render user prompt
    USER_PROMPT="${WORKTREE}/.iter/${i}_user.md"
    ITERATION="$i" \
    MAX_ITERATIONS="$MAX" \
    BEFORE_PATH="$BEFORE" \
    LOG_DIR_VAL="$LOG_DIR" \
    LEARNINGS_PATH="$LEARNINGS" \
    TMPL_PATH="$PROMPT_USER_TMPL" \
    "${WORKTREE}/.venv/bin/python" - > "$USER_PROMPT" <<'PY'
import os
from pathlib import Path
tmpl = Path(os.environ["TMPL_PATH"]).read_text()
before = Path(os.environ["BEFORE_PATH"]).read_text()
print(tmpl.format(
    iteration=int(os.environ["ITERATION"]),
    max_iterations=int(os.environ["MAX_ITERATIONS"]),
    before_json=before,
    log_dir=os.environ["LOG_DIR_VAL"],
    learnings_path=os.environ["LEARNINGS_PATH"],
))
PY

    # Spawn claude with restricted whitelist; 60-min hard timeout.
    # `claude` has no --cwd flag, so cd into the worktree in a subshell.
    set +e
    (
        cd "$WORKTREE" && \
        timeout 3600 claude --print \
            --output-format json \
            --append-system-prompt "$(cat "$PROMPT_SYSTEM")" \
            --allowed-tools "$ALLOWED_TOOLS" \
            < "$USER_PROMPT" > "$TRANSCRIPT" 2>"${TRANSCRIPT}.stderr"
    )
    claude_rc=$?
    set -e
    if [[ $claude_rc -ne 0 ]]; then
        echo "  claude exited rc=$claude_rc (timeout or error); recording as TIMEOUT/ERROR" >&2
        echo "{}" > "$TRANSCRIPT"
    fi

    # Snapshot suite AFTER (re-run; ground truth)
    set +e
    "${WORKTREE}/.venv/bin/python" -u "${WORKTREE}/scripts/regression_suite.py" --out "$AFTER"
    set -e

    if [[ ! -s "$AFTER" ]]; then
        echo "  AFTER snapshot missing or empty (suite wrapper crashed); logging and continuing" >&2
        {
            echo
            echo "## Iteration $i — SUITE-ERROR"
            echo
            echo "**Outcome**: regression_suite.py did not produce a valid AFTER snapshot."
            echo
        } >> "$LEARNINGS"
        continue
    fi

    # Driver decides + commits or reverts
    set +e
    "${WORKTREE}/.venv/bin/python" "${WORKTREE}/scripts/iteration_step.py" decide \
        --iteration "$i" \
        --before "$BEFORE" --after "$AFTER" --transcript "$TRANSCRIPT" \
        --learnings "$LEARNINGS" --workdir "$WORKTREE"
    decide_rc=$?
    set -e
    if [[ $decide_rc -ne 0 ]]; then
        echo "  iteration_step.py decide failed rc=$decide_rc; logging and continuing" >&2
        {
            echo
            echo "## Iteration $i — DRIVER-ERROR (rc=$decide_rc)"
            echo
            echo "**Outcome**: iteration_step.py decide exited rc=$decide_rc; loop continued."
            echo
        } >> "$LEARNINGS"
    fi
done

# Finalize report
"${WORKTREE}/.venv/bin/python" "${WORKTREE}/scripts/iteration_step.py" finalize \
    --learnings "$LEARNINGS" --report "$REPORT"
echo "Final report: $REPORT"
echo "Worktree:     $WORKTREE"
echo "Branch:       $BRANCH"
