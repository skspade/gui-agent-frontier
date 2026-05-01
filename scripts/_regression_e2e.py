"""E2E + mechanical-probe runners for regression_suite.py. Kept in a
separate module so importing the wrapper for unit-only mode does not
drag in browser/Chromium dependencies."""
from __future__ import annotations
import json
import os
import re
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DISPLAY_ENV = {
    "DISPLAY": ":0",
    "XAUTHORITY": os.environ.get("XAUTHORITY", "/run/user/1000/xauth_rVYaGJ"),
    "XDG_RUNTIME_DIR": "/run/user/1000",
    "PYTHONUNBUFFERED": "1",
}


def _venv_python() -> str:
    return str(ROOT / ".venv" / "bin" / "python")


def _run_subprocess_with_timeout(cmd: list[str], env: dict, timeout_s: int, log_path: Path, t0: float) -> tuple[str, str, float, bool]:
    """Run a subprocess with timeout, write a combined log, return (stdout, stderr, dur, timed_out)."""
    try:
        proc = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=timeout_s)
    except subprocess.TimeoutExpired as e:
        stdout = e.stdout.decode() if isinstance(e.stdout, bytes) else (e.stdout or "")
        stderr = e.stderr.decode() if isinstance(e.stderr, bytes) else (e.stderr or "")
        log_path.write_text(f"TIMEOUT after {timeout_s}s\n{stdout}\n--- STDERR ---\n{stderr}")
        return stdout, stderr, time.time() - t0, True
    dur = time.time() - t0
    log_path.write_text(proc.stdout + "\n--- STDERR ---\n" + proc.stderr)
    return proc.stdout, proc.stderr, dur, False


def run_mechanical_probe(log_path: Path) -> tuple[bool, float]:
    """saucedemo_flow_probe walks CP1-CP9 with DOM-truth coords through the
    dispatcher. Pass iff the script prints 'N/N checkpoints PASS' for some
    N (count-agnostic so adding a CP later doesn't silently break the test)."""
    t0 = time.time()
    env = {**os.environ, **DISPLAY_ENV}
    stdout, _stderr, dur, timed_out = _run_subprocess_with_timeout(
        [_venv_python(), "-u", str(ROOT / "scripts" / "saucedemo_flow_probe.py")],
        env, 180, log_path, t0,
    )
    if timed_out:
        return False, dur
    ok = False
    for line in stdout.splitlines():
        m = re.match(r"\s*(\d+)/(\d+) checkpoints PASS\s*$", line)
        if m and m.group(1) == m.group(2):
            ok = True
            break
    return ok, dur


def _run_custom_agent(task: str, log_path: Path, timeout_s: int) -> tuple[bool, float]:
    t0 = time.time()
    env = {**os.environ, **DISPLAY_ENV, "MODEL": os.environ.get("MODEL", "ui-venus-1.5-8b")}
    stdout, _stderr, dur, timed_out = _run_subprocess_with_timeout(
        [_venv_python(), "-u", str(ROOT / "scripts" / "custom_agent.py"), task],
        env, timeout_s, log_path, t0,
    )
    if timed_out:
        return False, dur
    return _parse_pass_from_runlog(stdout), dur


def _parse_pass_from_runlog(stdout: str) -> bool:
    """Find the last JSON-shaped run-log block on stdout and apply the
    same pass rule as web/build_site._is_pass: category == 'pass' first,
    fallback to outcome in {done, call_user}."""
    # Naive {...}-with-"outcome" matcher. Sufficient for the run-log shape.
    matches = re.findall(r"\{[^{}]*\"outcome\"[^{}]*\}", stdout)
    if not matches:
        return False
    try:
        last = json.loads(matches[-1])
    except json.JSONDecodeError:
        return False
    if "category" in last:
        return last["category"] == "pass"
    return last.get("outcome") in ("done", "call_user")


def run_saucedemo_e2e(log_path: Path) -> tuple[bool, float]:
    return _run_custom_agent("saucedemo_full_checkout", log_path, timeout_s=600)


def run_billy_e2e(log_path: Path) -> tuple[bool, float]:
    return _run_custom_agent("ikea_billy", log_path, timeout_s=900)
