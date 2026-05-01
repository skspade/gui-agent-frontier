#!/usr/bin/env bash
# Sanity-check ~/.ssh/config after edits. Catches the failure mode where an
# orphan indented block (no preceding `Host X`) becomes the global default
# and silently retargets all unmatched hosts — caught on 2026-05-01 when a
# Python regex-based config edit made `git@github.com` resolve to a Thunder
# instance IP, breaking `git push` to gh-pages.
#
# Usage:
#   bash scripts/check_ssh_config.sh
#
# Exits 0 if structure is sane and named hosts resolve to expected
# patterns; non-zero otherwise.
set -uo pipefail

CFG=~/.ssh/config
RC=0

ok()   { printf "  \033[32mOK\033[0m  %s\n" "$1"; }
fail() { printf "  \033[31mFAIL\033[0m %s\n" "$1"; RC=1; }

if [[ ! -f "$CFG" ]]; then
  fail "no ~/.ssh/config"
  exit 1
fi

# Structural check: any indented option line (starting with whitespace) must
# come AFTER a Host directive. Lines before the first Host line that are
# indented are orphan globals — almost always a bug.
first_host_line=$(grep -n "^Host " "$CFG" | head -1 | cut -d: -f1)
if [[ -z "$first_host_line" ]]; then
  fail "no Host directives in ~/.ssh/config"
else
  orphan=$(head -n $((first_host_line - 1)) "$CFG" | grep -nE "^[[:space:]]+[A-Za-z]" || true)
  if [[ -n "$orphan" ]]; then
    fail "orphan indented options before first Host directive (these become global defaults):"
    echo "$orphan" | sed 's/^/      /' >&2
  else
    ok "no orphan indented blocks above first Host directive"
  fi
fi

# Resolution check: `ssh -G <name>` resolves the merged config. Confirm
# github.com still goes to github.com (not an unrelated IP) and confirm
# `thunder` (when defined) doesn't have port 22.
gh_host=$(ssh -G github.com 2>/dev/null | awk '/^hostname / {print $2}' | head -1)
if [[ "$gh_host" == "github.com" ]]; then
  ok "github.com resolves to github.com"
else
  fail "github.com resolves to '$gh_host' (expected: github.com) — likely an orphan-global config bug"
fi

if grep -q "^Host thunder" "$CFG"; then
  th_host=$(ssh -G thunder 2>/dev/null | awk '/^hostname / {print $2}' | head -1)
  th_port=$(ssh -G thunder 2>/dev/null | awk '/^port / {print $2}' | head -1)
  if [[ -n "$th_host" && "$th_port" != "22" ]]; then
    ok "thunder resolves to $th_host:$th_port (non-default port = Thunder pattern)"
  else
    fail "thunder block exists but resolves oddly (host=$th_host port=$th_port)"
  fi
fi

if [[ $RC -eq 0 ]]; then
  echo "ssh config: OK"
else
  echo "ssh config: FAIL — fix issues above before relying on git push or remote deploys" >&2
fi
exit $RC
