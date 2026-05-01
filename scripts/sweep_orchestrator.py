"""Unified sweep entry point — collapses local_sweep.sh + thunder_sweep.sh.

One Python script that drives a (target, model, task) sweep with durable
artifact archiving and `runs.jsonl` row patching, regardless of whether the
llama-server is running locally or on a Thunder instance reached via SSH.

Usage
-----
Local sweep:
    .venv/bin/python scripts/sweep_orchestrator.py \\
        --target local \\
        --task excalidraw_drag \\
        --model ui-venus-1.5-8b \\
        --n 3

Thunder sweep:
    .venv/bin/python scripts/sweep_orchestrator.py \\
        --target thunder \\
        --task ikea_search_add \\
        --model qwen2.5-vl-72b-instruct \\
        --quant Q4_K_M \\
        --ssh-alias thunder \\
        --n 3

Multi-task batch (one model, several tasks):
    .venv/bin/python scripts/sweep_orchestrator.py \\
        --target local \\
        --tasks saucedemo_headed,excalidraw_drag,excalidraw_toolbar \\
        --model ui-venus-1.5-8b \\
        --n 3

Effect (per cell)
-----------------
1. Verify task module exists in scripts/custom_agent_tasks/ (fail fast).
2. Local: `sudo bash scripts/swap_model.sh <model> [quant]`.
   Thunder: `bash scripts/thunder/swap_model_remote.sh <ssh> <model> [quant]`,
            then ensure ssh tunnel local:8080 -> remote:8080 is open.
3. For run in 1..N:
     run scripts/custom_agent.py <task> with MODEL=<model> against localhost:8080
     copy /tmp/custom_agent_final.png to data/sweeps/<sweep-id>/<task>/<dir>/run-<i>/final.png
     patch the trailing runs.jsonl row's final_screenshot field
4. Print structured summary.

Safety guards (mirror local_sweep.sh / thunder_sweep.sh)
-------------------------------------------------------
- runs.jsonl is patched only if custom_agent.py appended exactly one new
  row (compares row count before/after).
- Screenshot is archived only if /tmp/custom_agent_final.png mtime advanced
  past the run's start (no stale carry-over from the previous run).
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CUSTOM_AGENT_PY = REPO_ROOT / "scripts" / "custom_agent.py"
SWAP_LOCAL = REPO_ROOT / "scripts" / "swap_model.sh"
SWAP_REMOTE = REPO_ROOT / "scripts" / "thunder" / "swap_model_remote.sh"
TASKS_DIR = REPO_ROOT / "scripts" / "custom_agent_tasks"
RUNS_JSONL = REPO_ROOT / "data" / "runs.jsonl"
TMP_FINAL = Path("/tmp/custom_agent_final.png")
VENV_PY = REPO_ROOT / ".venv" / "bin" / "python"

LOCAL_DISPLAY_ENV = {
    "DISPLAY": ":0",
    "XAUTHORITY": "/run/user/1000/xauth_rVYaGJ",
    "XDG_RUNTIME_DIR": "/run/user/1000",
}


def port_in_use(port: int = 8080) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def health_check(timeout_s: int = 60) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            r = subprocess.run(
                ["curl", "-fsS", "--max-time", "3", "http://localhost:8080/health"],
                capture_output=True, timeout=5,
            )
            if r.returncode == 0:
                return True
        except subprocess.TimeoutExpired:
            pass
        time.sleep(2)
    return False


def ensure_task_exists(task: str) -> None:
    p = TASKS_DIR / f"{task}.py"
    if not p.is_file():
        avail = sorted(
            f.stem for f in TASKS_DIR.glob("*.py")
            if not f.name.startswith("_")
        )
        sys.exit(
            f"ERROR: task module not found: {p}\n"
            f"available tasks: {', '.join(avail)}"
        )


def swap_local(model: str, quant: str | None) -> None:
    cmd = ["sudo", "bash", str(SWAP_LOCAL), model]
    if quant:
        cmd.append(quant)
    print(f"[swap-local] {' '.join(cmd)}")
    subprocess.run(cmd, check=True)
    if not health_check(60):
        sys.exit("ERROR: localhost:8080 did not respond /health within 60s after swap")


def swap_thunder(ssh_alias: str, model: str, quant: str) -> None:
    cmd = ["bash", str(SWAP_REMOTE), ssh_alias, model, quant]
    print(f"[swap-thunder] {' '.join(cmd)}")
    subprocess.run(cmd, check=True)


def open_tunnel(ssh_alias: str) -> subprocess.Popen[bytes] | None:
    """Open ssh -fN -L 8080:localhost:8080 <alias>. Returns None if already open."""
    if port_in_use(8080):
        print("[tunnel] localhost:8080 already in use — assuming tunnel is open")
        return None
    proc = subprocess.Popen(
        ["ssh", "-fN", "-L", "8080:localhost:8080", ssh_alias],
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )
    proc.wait(timeout=15)
    if not port_in_use(8080):
        sys.exit(f"ERROR: SSH tunnel to {ssh_alias} did not bind localhost:8080")
    print(f"[tunnel] opened SSH tunnel to {ssh_alias}")
    return proc


def run_one(task: str, model: str, run_dir: Path) -> tuple[bool, int | None, int | None]:
    """Run custom_agent.py once. Returns (row_appended, mtime_before, mtime_after)."""
    rows_before = sum(1 for _ in RUNS_JSONL.read_text().splitlines() if _.strip()) \
                  if RUNS_JSONL.is_file() else 0
    mtime_before = TMP_FINAL.stat().st_mtime_ns if TMP_FINAL.is_file() else 0

    log_path = run_dir / "smoke.log"
    env = {**os.environ, "PYTHONUNBUFFERED": "1", "MODEL": model, **LOCAL_DISPLAY_ENV}
    py = str(VENV_PY) if VENV_PY.exists() else sys.executable
    with log_path.open("wb") as f:
        subprocess.run(
            [py, "-u", str(CUSTOM_AGENT_PY), task],
            stdout=f, stderr=subprocess.STDOUT, env=env,
        )

    rows_after = sum(1 for _ in RUNS_JSONL.read_text().splitlines() if _.strip()) \
                 if RUNS_JSONL.is_file() else 0
    mtime_after = TMP_FINAL.stat().st_mtime_ns if TMP_FINAL.is_file() else 0
    return rows_after == rows_before + 1, mtime_before, mtime_after


def archive_and_patch(
    run_dir: Path, mtime_before: int, mtime_after: int,
    sweep_id: str, target: str, quant: str | None,
) -> None:
    """Copy /tmp/custom_agent_final.png if fresh; patch trailing runs.jsonl row."""
    archived: Path | None = None
    if TMP_FINAL.is_file() and mtime_after > mtime_before:
        archived = run_dir / "final.png"
        shutil.copy2(TMP_FINAL, archived)

    lines = RUNS_JSONL.read_text().splitlines()
    if not lines:
        return  # no row to patch
    last = json.loads(lines[-1])
    if archived is not None and archived.is_file():
        last["final_screenshot"] = str(archived)
    last["phase"] = os.environ.get("SWEEP_PHASE", last.get("phase", "untagged"))
    last["sweep_id"] = sweep_id
    if quant:
        last["quant"] = quant
    if target == "thunder":
        last["thunder"] = True
    lines[-1] = json.dumps(last)
    RUNS_JSONL.write_text("\n".join(lines) + "\n")


def sweep_cell(
    target: str, task: str, model: str, quant: str | None,
    n: int, sweep_id: str, ssh_alias: str | None,
) -> dict:
    """Run one (task, model) cell n times. Returns a dict summary."""
    ensure_task_exists(task)

    alias_for_dir = f"{model}_{quant}" if quant else model
    cell_dir = REPO_ROOT / "data" / "sweeps" / sweep_id / task / alias_for_dir
    cell_dir.mkdir(parents=True, exist_ok=True)

    results = []
    for i in range(1, n + 1):
        run_dir = cell_dir / f"run-{i}"
        run_dir.mkdir(exist_ok=True)
        print(f"  [run {i}/{n}] {task} / {model}{f' ({quant})' if quant else ''}")
        appended, mb, ma = run_one(task, model, run_dir)
        if appended:
            archive_and_patch(run_dir, mb, ma, sweep_id, target, quant)
            results.append({"run": i, "appended": True})
        else:
            print(f"    WARN: custom_agent.py did not append a new row; skipping patch")
            results.append({"run": i, "appended": False})
    return {"task": task, "model": model, "quant": quant, "results": results}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--target", choices=["local", "thunder"], required=True)
    ap.add_argument("--task", help="single task name (under scripts/custom_agent_tasks/)")
    ap.add_argument("--tasks", help="comma-separated tasks for a multi-cell batch")
    ap.add_argument("--model", required=True)
    ap.add_argument("--quant", default=None, help="model quant (required for thunder)")
    ap.add_argument("--n", type=int, default=3, help="runs per cell (default: 3)")
    ap.add_argument("--sweep-id", default=_dt.date.today().isoformat() + "-sweep")
    ap.add_argument("--ssh-alias", default="thunder",
                    help="SSH alias for thunder target (default: thunder)")
    ap.add_argument("--skip-swap", action="store_true",
                    help="skip the swap step (assumes server is already serving "
                         "the requested model). Useful for dry-running the thunder "
                         "branch against a local llama-server before paying for "
                         "Thunder compute.")
    args = ap.parse_args()

    if not args.task and not args.tasks:
        sys.exit("ERROR: must provide --task or --tasks")
    tasks = [args.task] if args.task else [t.strip() for t in args.tasks.split(",") if t.strip()]

    if args.target == "thunder" and not args.quant:
        sys.exit("ERROR: --quant is required for --target thunder")

    # Fail-fast on task existence BEFORE any state mutation (model swap,
    # sudo invocation). Catches plan defects without spending a swap.
    for task in tasks:
        ensure_task_exists(task)

    print(f"sweep_id: {args.sweep_id}")
    print(f"target:   {args.target}")
    print(f"model:    {args.model}{f' ({args.quant})' if args.quant else ''}")
    print(f"tasks:    {tasks}")
    print(f"n:        {args.n}")

    if args.skip_swap:
        print("[skip-swap] verifying server already healthy at localhost:8080")
        if not health_check(10):
            sys.exit("ERROR: --skip-swap given but localhost:8080 not responding /health")
    elif args.target == "local":
        swap_local(args.model, args.quant)
    else:
        swap_thunder(args.ssh_alias, args.model, args.quant)
        open_tunnel(args.ssh_alias)
        if not health_check(30):
            sys.exit("ERROR: tunneled localhost:8080 not responding /health")

    summaries = []
    for task in tasks:
        print(f"\n=== {task} ===")
        summaries.append(
            sweep_cell(args.target, task, args.model, args.quant, args.n,
                       args.sweep_id, args.ssh_alias)
        )

    print("\n== summary ==")
    for s in summaries:
        passed = sum(1 for r in s["results"] if r["appended"])
        print(f"  {s['task']:25s} {s['model']:35s} appended={passed}/{len(s['results'])}")
    print(f"\nartifacts: data/sweeps/{args.sweep_id}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
