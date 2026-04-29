"""Custom CDP agent runner — pairs UI-Venus with Chromium directly.

See docs/plans/2026-04-28-s1-custom-cdp-client-design.md for the design.
"""
from __future__ import annotations
import argparse
import asyncio
import base64
import importlib
import shutil
import subprocess
import sys
import time
from pathlib import Path

# Allow `python scripts/custom_agent.py ...` from the project root by putting
# the project root (parent of scripts/) on sys.path. Required because the
# submodule `scripts.custom_agent.browser` etc. resolve via the project root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.custom_agent.browser import launch_chromium, Page
from scripts.custom_agent.model import (
    Action,
    ParseError,
    parse_action,
    step as model_step,
)
from scripts.custom_agent.actions import dispatch

STEPS_DIR = Path("/tmp/custom_agent_steps")
FINAL_PNG = Path("/tmp/custom_agent_final.png")


async def run(task_module) -> None:
    STEPS_DIR.mkdir(exist_ok=True)
    for f in STEPS_DIR.glob("*.png"):
        f.unlink()

    window_size = getattr(task_module, "WINDOW_SIZE", (1280, 800))
    proc, ws, ud = launch_chromium(headless=task_module.HEADLESS, window_size=window_size)
    t0 = time.time()
    try:
        page, client = await Page.attach(ws)
        await page.goto(task_module.START_URL)
        viewport = await page.viewport_css()
        print(f"[setup] viewport={viewport[0]}x{viewport[1]} headless={task_module.HEADLESS}")
        history: list[Action] = []
        outcome = "max_steps_reached"

        for step_idx in range(task_module.MAX_STEPS):
            b64 = await page.screenshot()
            try:
                raw = model_step(task_module.TASK, history, b64)
                action = parse_action(raw)
            except ParseError as e:
                print(f"[step {step_idx}] parse error: {e}", file=sys.stderr)
                print(f"[step {step_idx}] raw response:\n{raw}", file=sys.stderr)
                outcome = "parse_error"
                break
            except Exception as e:
                print(f"[step {step_idx}] model error: {e!r}", file=sys.stderr)
                outcome = "model_error"
                break

            short = (
                f"{action.kind} "
                + (str(action.xy) if action.xy else "")
                + (f"text={action.text!r}" if action.text else "")
                + (f"dir={action.direction}" if action.direction else "")
            )
            print(f"[step {step_idx}] {short.strip()} -> {action.conclusion[:80]}")
            history.append(action)

            if action.kind == "done":
                outcome = "done"
                break

            try:
                await dispatch(page, action, viewport)
            except NotImplementedError as e:
                print(f"[step {step_idx}] {e}", file=sys.stderr)
                outcome = "unhandled_action"
                break

            png_path = STEPS_DIR / f"{step_idx:03d}.png"
            png_path.write_bytes(base64.b64decode(await page.screenshot()))

        FINAL_PNG.write_bytes(base64.b64decode(await page.screenshot()))
        elapsed = time.time() - t0
        print(f"\n=== outcome: {outcome} | steps: {len(history)} | elapsed: {elapsed:.1f}s ===")
        print(f"final screenshot: {FINAL_PNG}")
        print(f"per-step screenshots: {STEPS_DIR}")

        await client.stop()
    finally:
        proc.terminate()
        try:
            proc.wait(5)
        except subprocess.TimeoutExpired:
            proc.kill()
        shutil.rmtree(ud, ignore_errors=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("task", help="module name in scripts/custom_agent_tasks/")
    args = parser.parse_args()
    try:
        mod = importlib.import_module(f"scripts.custom_agent_tasks.{args.task}")
    except ModuleNotFoundError:
        print(f"no task module: scripts/custom_agent_tasks/{args.task}.py", file=sys.stderr)
        sys.exit(2)
    asyncio.run(run(mod))


if __name__ == "__main__":
    main()
