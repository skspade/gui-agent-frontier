"""Regression suite wrapper for the custom CDP harness.

Composes:
  - 4 unit-test regression locks under tests/regression/
  - 1 mechanical CDP probe (saucedemo_flow_probe.py)
  - 2 E2E custom-agent runs (saucedemo_full_checkout, ikea_billy)

Emits a JSON document the iteration_loop driver consumes:
  {
    "all_green": bool,
    "duration_s": float,
    "tests": {
      "<test_id>": {"pass": bool, "duration_s": float, "log_excerpt": str},
      ...
    }
  }

Per-test log files land in <log_dir>/<test_id>.log (default
/tmp/regression_suite/<run_id>/).

Run:
  .venv/bin/python -u scripts/regression_suite.py [--unit-only] [--out PATH] [--log-dir DIR]

Exit codes: 0 if all_green, 1 otherwise.
"""
from __future__ import annotations
import argparse
import json
import subprocess
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

UNIT_TESTS = {
    "regression_quant_default":  "tests/regression/test_swap_model_quant_defaults.py",
    "regression_coord_remap":    "tests/regression/test_action_kind_coord_space.py",
    "regression_scroll_clamp":   "tests/regression/test_scroll_min_delta.py",
    "regression_iframe_skip":    "tests/regression/test_js_click_iframe_skip.py",
}


def _run_pytest(test_file: str, log_path: Path) -> tuple[bool, float]:
    t0 = time.time()
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", str(ROOT / test_file), "-v", "--tb=short"],
            capture_output=True, text=True, timeout=120,
        )
    except subprocess.TimeoutExpired as e:
        # Write a structured marker so the iteration driver sees a clean fail row.
        stdout = e.stdout.decode() if isinstance(e.stdout, bytes) else (e.stdout or "")
        stderr = e.stderr.decode() if isinstance(e.stderr, bytes) else (e.stderr or "")
        log_path.write_text(f"TIMEOUT after 120s\n{stdout}\n--- STDERR ---\n{stderr}")
        return False, time.time() - t0
    dur = time.time() - t0
    log_path.write_text(proc.stdout + "\n--- STDERR ---\n" + proc.stderr)
    return proc.returncode == 0, dur


def _excerpt(log_path: Path, max_chars: int = 2000) -> str:
    try:
        text = log_path.read_text()
    except FileNotFoundError:
        return ""
    if len(text) <= max_chars:
        return text
    return text[:max_chars // 2] + "\n...[truncated]...\n" + text[-max_chars // 2:]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--unit-only", action="store_true")
    parser.add_argument("--out", default=None, help="JSON output path; default stdout")
    parser.add_argument("--log-dir", default=None)
    args = parser.parse_args()

    run_id = uuid.uuid4().hex[:8]
    log_dir = Path(args.log_dir) if args.log_dir else Path(f"/tmp/regression_suite/{run_id}")
    log_dir.mkdir(parents=True, exist_ok=True)

    results: dict[str, dict] = {}
    suite_t0 = time.time()

    for test_id, rel_path in UNIT_TESTS.items():
        log_path = log_dir / f"{test_id}.log"
        ok, dur = _run_pytest(rel_path, log_path)
        results[test_id] = {
            "pass": ok,
            "duration_s": round(dur, 2),
            "log_excerpt": _excerpt(log_path),
        }

    # Phase 2 Task 6, 7 will plug mechanical probe + E2E here.
    if not args.unit_only:
        from scripts._regression_e2e import run_mechanical_probe, run_saucedemo_e2e, run_billy_e2e  # type: ignore
        for fn, key in [(run_mechanical_probe, "saucedemo_probe"),
                        (run_saucedemo_e2e,    "saucedemo_full_checkout"),
                        (run_billy_e2e,        "ikea_billy")]:
            log_path = log_dir / f"{key}.log"
            ok, dur = fn(log_path)
            results[key] = {"pass": ok, "duration_s": round(dur, 2),
                            "log_excerpt": _excerpt(log_path)}

    doc = {
        "all_green": all(r["pass"] for r in results.values()),
        "duration_s": round(time.time() - suite_t0, 2),
        "run_id": run_id,
        "log_dir": str(log_dir),
        "tests": results,
    }
    out_text = json.dumps(doc, indent=2)
    if args.out:
        Path(args.out).write_text(out_text)
    else:
        sys.stdout.write(out_text + "\n")
    return 0 if doc["all_green"] else 1


if __name__ == "__main__":
    sys.exit(main())
