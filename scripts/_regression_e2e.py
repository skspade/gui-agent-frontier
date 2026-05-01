"""E2E + mechanical-probe runners for regression_suite.py. Kept in a
separate module so importing the wrapper for unit-only mode does not
drag in browser/Chromium dependencies."""
from __future__ import annotations
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


def run_mechanical_probe(log_path: Path) -> tuple[bool, float]:
    """saucedemo_flow_probe walks CP1-CP9 with DOM-truth coords through the
    dispatcher. Pass = the script's last line says '9/9 checkpoints PASS'."""
    t0 = time.time()
    env = {**os.environ, **DISPLAY_ENV}
    proc = subprocess.run(
        [_venv_python(), "-u", str(ROOT / "scripts" / "saucedemo_flow_probe.py")],
        env=env, capture_output=True, text=True, timeout=180,
    )
    dur = time.time() - t0
    log_path.write_text(proc.stdout + "\n--- STDERR ---\n" + proc.stderr)
    ok = False
    for line in proc.stdout.splitlines():
        m = re.match(r"\s*(\d+)/(\d+) checkpoints PASS\s*$", line)
        if m and m.group(1) == m.group(2):
            ok = True
            break
    return ok, dur


def run_saucedemo_e2e(log_path: Path) -> tuple[bool, float]:
    """Placeholder — implemented in Task 7."""
    raise NotImplementedError


def run_billy_e2e(log_path: Path) -> tuple[bool, float]:
    """Placeholder — implemented in Task 7."""
    raise NotImplementedError
