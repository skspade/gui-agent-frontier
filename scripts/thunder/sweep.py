"""
sweep.py — drive a (model, quant) ladder against a remote llama-server on
Thunder while running the existing local smoke harness. Each cell:
  1. swap_model_remote.sh -> swap remote llama-server to next (model, quant)
  2. open SSH tunnel local:8080 -> remote:8080 (sweep.py owns its own tunnel)
  3. run scripts/smoke_browser_use.py <task>
  4. archive log + /tmp/smoke_final.png to data/sweeps/<run_id>/<cell>/

Pre-flight refuses to run if the local vision-model.service is occupying
port 8080 (the tunnel needs that port free).

Usage:
    .venv/bin/python scripts/thunder/sweep.py \
        --ssh thunder \
        --task excalidraw_drag

Run id format: YYYYMMDD-HHMMSS. Output schema is intentionally simple — the
caller can post-process into docs/findings.md format afterwards.
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import json
import os
import pathlib
import shutil
import socket
import subprocess
import sys
import time

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SMOKE_RUNNER = REPO_ROOT / "scripts" / "smoke_browser_use.py"
SWAP_SCRIPT = REPO_ROOT / "scripts" / "thunder" / "swap_model_remote.sh"
SWEEPS_DIR = REPO_ROOT / "data" / "sweeps"
VENV_PY = REPO_ROOT / ".venv" / "bin" / "python"
SMOKE_FINAL_PNG = pathlib.Path("/tmp/smoke_final.png")

DEFAULT_LADDER: list[tuple[str, str]] = [
    ("holo3-35b-a3b", "IQ3_XXS"),
    ("holo3-35b-a3b", "Q4_K_M"),
    ("holo3-35b-a3b", "Q6_K"),
    ("qwen2.5-vl-72b-instruct", "Q4_K_M"),
]


@dataclasses.dataclass
class CellResult:
    model: str
    quant: str
    swap_ok: bool
    smoke_returncode: int | None
    duration_s: float
    log_path: str
    screenshot_path: str | None


def port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def open_tunnel(ssh_alias: str, local_port: int = 8080) -> subprocess.Popen[bytes]:
    cmd = [
        "ssh", "-N",
        "-o", "ExitOnForwardFailure=yes",
        "-o", "ServerAliveInterval=30",
        "-L", f"{local_port}:localhost:8080",
        ssh_alias,
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    for _ in range(20):
        if port_in_use(local_port):
            return proc
        if proc.poll() is not None:
            err = proc.stderr.read().decode() if proc.stderr else ""
            raise RuntimeError(f"SSH tunnel failed to open: {err}")
        time.sleep(0.25)
    proc.terminate()
    raise RuntimeError("SSH tunnel did not open within 5s")


def run_swap(ssh_alias: str, model: str, quant: str, log_path: pathlib.Path) -> bool:
    with log_path.open("wb") as f:
        proc = subprocess.run(
            ["bash", str(SWAP_SCRIPT), ssh_alias, model, quant],
            stdout=f, stderr=subprocess.STDOUT,
        )
    return proc.returncode == 0


def run_smoke(task: str, model_alias: str, log_path: pathlib.Path) -> int:
    env = os.environ.copy()
    env["MODEL"] = model_alias
    env.setdefault("PYTHONUNBUFFERED", "1")
    py = str(VENV_PY) if VENV_PY.exists() else sys.executable
    with log_path.open("wb") as f:
        proc = subprocess.run(
            [py, "-u", str(SMOKE_RUNNER), task],
            stdout=f, stderr=subprocess.STDOUT, env=env,
        )
    return proc.returncode


def archive_screenshot(dst_dir: pathlib.Path) -> str | None:
    if not SMOKE_FINAL_PNG.exists():
        return None
    dst = dst_dir / "final.png"
    shutil.copy2(SMOKE_FINAL_PNG, dst)
    return str(dst)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ssh", required=True, help="SSH alias for the Thunder instance")
    ap.add_argument("--task", default="excalidraw_drag",
                    help="smoke name under scripts/smokes/ (default: excalidraw_drag)")
    ap.add_argument("--ladder", default=None,
                    help="optional path to JSON file with [[model, quant], ...]; "
                         "defaults to the class-C Holo3 ladder")
    args = ap.parse_args()

    if port_in_use(8080):
        print("ERROR: local port 8080 is in use. Stop the local service first:",
              file=sys.stderr)
        print("  sudo systemctl stop vision-model.service", file=sys.stderr)
        return 2

    ladder = DEFAULT_LADDER
    if args.ladder:
        ladder = [tuple(x) for x in json.loads(pathlib.Path(args.ladder).read_text())]

    run_id = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = SWEEPS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    print(f"sweep run_id: {run_id}")
    print(f"output dir:   {run_dir}")
    print(f"ladder:       {ladder}")
    print(f"task:         {args.task}")

    results: list[CellResult] = []
    for model, quant in ladder:
        cell_dir = run_dir / f"{model}_{quant}"
        cell_dir.mkdir(exist_ok=True)
        swap_log = cell_dir / "swap.log"
        smoke_log = cell_dir / "smoke.log"

        print(f"\n===== cell: {model} {quant} =====")
        t0 = time.monotonic()

        swap_ok = run_swap(args.ssh, model, quant, swap_log)
        if not swap_ok:
            print(f"  swap FAILED (see {swap_log})")
            results.append(CellResult(model, quant, False, None,
                                      time.monotonic() - t0,
                                      str(swap_log), None))
            continue

        # Open a fresh tunnel per cell — cheap, and avoids stale state if the
        # remote server restart momentarily breaks the existing tunnel.
        tunnel = open_tunnel(args.ssh)
        try:
            rc = run_smoke(args.task, model, smoke_log)
        finally:
            tunnel.terminate()
            try:
                tunnel.wait(timeout=5)
            except subprocess.TimeoutExpired:
                tunnel.kill()

        screenshot = archive_screenshot(cell_dir)
        duration = time.monotonic() - t0
        print(f"  smoke rc={rc}  duration={duration:.1f}s  screenshot={'yes' if screenshot else 'NO'}")
        results.append(CellResult(model, quant, True, rc, duration,
                                  str(smoke_log), screenshot))

    summary = run_dir / "summary.json"
    summary.write_text(json.dumps(
        {"run_id": run_id, "task": args.task, "ssh": args.ssh,
         "results": [dataclasses.asdict(r) for r in results]},
        indent=2,
    ))
    print(f"\nsummary: {summary}")

    return 0 if all(r.swap_ok and r.smoke_returncode == 0 for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
