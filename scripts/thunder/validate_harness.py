"""Pre-sweep sanity check: drive one synthetic step through the configured
harness for whatever model is currently loaded on `localhost:8080`.

The sweep loop is expensive (per-cell swap + per-step inference at A100
hourly rates), so a multi-cell run that parse-errors at step 0 or emits
the wrong coord space wastes real money. This script catches both before
the sweep starts.

Usage (after `swap_model_remote.sh thunder <model> [quant]` and an SSH
tunnel are up, OR pointed at the local `vision-model.service`):

    MODEL=qwen2.5-vl-72b-instruct .venv/bin/python scripts/thunder/validate_harness.py

What it checks:
- Server is healthy and serving the expected model alias.
- The harness module's `navigate_step_*` returns an Action without raising.
- Prints the parsed `kind`, `xy`, `text`, and `raw` fields so the human
  can spot a coord-space mismatch (e.g. xy in pixel space when `kind` is
  `click`, which the dispatcher would 0-1000 remap and miss every target).

Exits 0 on a clean parse, 1 on parse error, 2 on harness misconfig, 3 on
server health failure.
"""
from __future__ import annotations

import base64
import io
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

import httpx
from PIL import Image, ImageDraw

from scripts.custom_agent import harness_for

VIEWPORT = (1280, 800)
LLAMA_BASE = "http://localhost:8080"


def synthetic_screenshot_b64() -> str:
    """A 1280x800 white canvas with a labeled blue button at (650, 400)."""
    img = Image.new("RGB", VIEWPORT, "white")
    d = ImageDraw.Draw(img)
    d.rectangle((550, 360, 750, 440), fill="#0078d4", outline="black", width=2)
    d.text((600, 390), "Click Me", fill="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def health_check(expected_model: str) -> int:
    try:
        r = httpx.get(f"{LLAMA_BASE}/health", timeout=5.0)
        r.raise_for_status()
    except Exception as e:
        print(f"FAIL: /health unreachable: {e}", file=sys.stderr)
        return 3
    try:
        r = httpx.get(f"{LLAMA_BASE}/v1/models", timeout=5.0)
        r.raise_for_status()
        served = r.json()["models"][0]["name"]
    except Exception as e:
        print(f"FAIL: /v1/models unreachable: {e}", file=sys.stderr)
        return 3
    if served != expected_model:
        print(
            f"FAIL: server is serving {served!r}, but MODEL={expected_model!r}.\n"
            f"      Either swap the remote (scripts/thunder/swap_model_remote.sh) "
            f"or change MODEL to match.",
            file=sys.stderr,
        )
        return 3
    print(f"OK   server healthy, alias={served}")
    return 0


def main() -> int:
    model = os.environ.get("MODEL", "ui-venus-1.5-8b")
    harness = harness_for(model, os.environ.get("HARNESS"))
    print(f"model={model}  harness={harness}  viewport={VIEWPORT}")

    rc = health_check(model)
    if rc != 0:
        return rc

    b64 = synthetic_screenshot_b64()
    task = "Click the blue 'Click Me' button in the center of the screen."

    try:
        if harness == "uivenus":
            from scripts.custom_agent.model import step as model_step, parse_action
            raw = model_step(task, [], b64)
            print(f"\n--- raw model output ---\n{raw.strip()}\n")
            action = parse_action(raw)
        elif harness == "holo3":
            from scripts.custom_agent.holo3 import navigate_step_holo3
            action, _ = navigate_step_holo3(task, [], [b64], "", VIEWPORT)
        elif harness == "toolcall":
            from scripts.custom_agent.toolcall import navigate_step_toolcall
            action = navigate_step_toolcall(task, [], b64, VIEWPORT)
        elif harness == "qwenvl":
            from scripts.custom_agent.qwenvl import navigate_step_qwenvl
            action = navigate_step_qwenvl(task, [], b64, VIEWPORT)
        else:
            print(f"FAIL: unknown harness {harness!r}", file=sys.stderr)
            return 2
    except Exception as e:
        print(f"FAIL: harness raised: {type(e).__name__}: {e}", file=sys.stderr)
        return 1

    print("\n--- parsed action ---")
    print(f"  kind  = {action.kind}")
    print(f"  xy    = {action.xy}")
    print(f"  text  = {action.text!r}" if action.text else "  text  = (none)")
    print(f"  raw   = {action.raw[:120]!r}" + ("..." if len(action.raw) > 120 else ""))

    # Sanity hint: if click kind with xy outside [0, 1000], the dispatcher's
    # grounding_remap will rescale and miss. If click_at with xy outside
    # viewport bounds, it'll click off-page.
    if action.kind == "click" and action.xy is not None:
        x, y = action.xy
        if not (0 <= x <= 1000 and 0 <= y <= 1000):
            print(
                f"\nWARN  kind=click but xy=({x}, {y}) is outside [0, 1000]. "
                f"Dispatcher will 0-1000 remap and miss every target. "
                f"Did you mean to emit kind=click_at?"
            )
    if action.kind == "click_at" and action.xy is not None:
        x, y = action.xy
        if not (0 <= x <= VIEWPORT[0] and 0 <= y <= VIEWPORT[1]):
            print(
                f"\nWARN  kind=click_at but xy=({x}, {y}) is outside viewport "
                f"{VIEWPORT}. Click will land off-page."
            )

    print("\nOK   harness produced a parseable action.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
