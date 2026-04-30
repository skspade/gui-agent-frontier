"""Custom CDP agent runner — pairs UI-Venus with Chromium directly.

See docs/plans/2026-04-28-s1-custom-cdp-client-design.md for the design.
"""
from __future__ import annotations
import argparse
import asyncio
import base64
import collections
import hashlib
import importlib
import os
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
    step_grounding,
)
from scripts.custom_agent.actions import dispatch
from scripts.custom_agent.cart_state import verify_cart_state
from scripts.custom_agent.run_log import append_run, classify_failure, DEFAULT_LOG
from scripts.custom_agent.site_configs import match_site_config

# Harness paths:
#   uivenus  - <action>/<conclusion> tag grammar (UI-Venus 8B + 30B-A3B)
#   holo3    - surfer-h-cli two-pass navigate+localize, 0-1000 normalized
#              coords (Holo3-35B-A3B)
#   toolcall - Hermes-style <tool_call> emitter; covers models that ignore
#              UI-Venus's <action> schema and revert to native tool calling
#              when asked to commit a click (MAI-UI-8B, bu-30b-a3b-preview).
#
# `HARNESS=` env overrides the registry so cross-protocol experiments stay
# possible.
from scripts.custom_agent import harness_for

HARNESS = harness_for(os.environ.get("MODEL", "ui-venus-1.5-8b"), os.environ.get("HARNESS"))

STEPS_DIR = Path("/tmp/custom_agent_steps")
FINAL_PNG = Path("/tmp/custom_agent_final.png")

# When True, every parsed Click action gets a follow-up grounding-prompt
# lookup using its conclusion text; the refined coord replaces the
# nav-mode coord before dispatch. Hypothesis (Phase 11 follow-up): if
# nav-mode is split-attention'd between planning and grounding, a
# dedicated grounding call should be more precise. Default False because
# the n=1 saucedemo_headed test showed the merged 8B emits IDENTICAL
# coords (within 1-2 px) in both modes -- the model merge unified the
# heads, so there's no precision left to recover. Toggle if a future
# task suggests the modes diverge.
REFINE_CLICKS = False


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
        print(f"[setup] viewport={viewport[0]}x{viewport[1]} headless={task_module.HEADLESS} harness={HARNESS}")
        history: list[Action] = []
        outcome = "max_steps_reached"

        # Holo3 path needs the last 3 screenshots (navigator) + accumulating
        # `notes` carried across turns. Initialized always so the holo3
        # branch in-loop has a stable place to push to.
        screens: collections.deque[str] = collections.deque(maxlen=3)
        notes_state = ""

        navigate_step_holo3 = None
        navigate_step_toolcall = None
        if HARNESS == "holo3":
            from scripts.custom_agent.holo3 import navigate_step_holo3
        elif HARNESS == "toolcall":
            from scripts.custom_agent.toolcall import navigate_step_toolcall
        elif HARNESS != "uivenus":
            raise SystemExit(
                f"unknown HARNESS={HARNESS!r}; expected one of "
                "uivenus / holo3 / toolcall"
            )

        for step_idx in range(task_module.MAX_STEPS):
            b64 = await page.screenshot()
            pre_hash = hashlib.md5(b64.encode()).hexdigest()
            screens.append(b64)
            raw = ""
            try:
                if HARNESS == "holo3":
                    action, notes_state = navigate_step_holo3(
                        task_module.TASK, history, list(screens), notes_state, viewport
                    )
                elif HARNESS == "toolcall":
                    action = navigate_step_toolcall(
                        task_module.TASK, history, b64, viewport
                    )
                else:
                    raw = model_step(task_module.TASK, history, b64)
                    action = parse_action(raw)
            except ParseError as e:
                print(f"[step {step_idx}] parse error: {e}", file=sys.stderr)
                print(f"[step {step_idx}] raw response:\n{raw}", file=sys.stderr)
                outcome = "parse_error"
                break
            except ValueError as e:
                # Holo3 mapper raises ValueError on unknown variant. Surface
                # it the same as a parse error from the UI-Venus path.
                print(f"[step {step_idx}] parse error: {e}", file=sys.stderr)
                outcome = "parse_error"
                break
            except Exception as e:
                print(f"[step {step_idx}] model error: {e!r}", file=sys.stderr)
                outcome = "model_error"
                break

            if HARNESS == "uivenus" and REFINE_CLICKS and action.kind == "click" and action.xy is not None:
                target = action.conclusion or action.raw
                refined = step_grounding(target, b64)
                if refined is not None and refined != action.xy:
                    print(f"[step {step_idx}] refine: {action.xy} -> {refined} ({target[:60]!r})")
                    action.xy = refined

            short = (
                f"{action.kind} "
                + (str(action.xy) if action.xy else "")
                + (f"text={action.text!r}" if action.text else "")
                + (f"dir={action.direction}" if action.direction else "")
            )
            print(f"[step {step_idx}] {short.strip()} -> {action.conclusion[:80]}")
            history.append(action)

            if action.kind in ("done", "call_user"):
                # Phase 14 follow-up: UI-Venus-1.5-8B falsely emits Finished
                # right after consecutive failed clicks (model treats "no
                # progress" as "task done"). Reject when the prior 2 actions
                # had no visible page change so we don't record a false PASS.
                if (
                    len(history) >= 3
                    and history[-2].no_effect
                    and history[-3].no_effect
                ):
                    print(
                        f"[step {step_idx}] rejecting premature {action.kind}: "
                        "prior 2 actions had no page change",
                        file=sys.stderr,
                    )
                    outcome = "stuck_premature_done"
                    break
                outcome = action.kind
                break

            try:
                await dispatch(page, action, viewport)
            except NotImplementedError as e:
                print(f"[step {step_idx}] {e}", file=sys.stderr)
                outcome = "unhandled_action"
                break

            await page.wait_for_load()

            # Cart-state probe (Phase 1 / Priority 1). Cheap (~10-30ms in practice; <500ms
            # budget) so runs every step. The result is attached to the action and rendered
            # in the next-turn prompt's previous_actions block by _render_history_block;
            # steps where the probe sees no signal don't pollute the prompt (the rendering
            # layer drops verification_method=='none' silently).
            current_url = await page.url()
            site_cfg = match_site_config(current_url)
            action.cart_after = await verify_cart_state(page, site_cfg, current_url)
            ca = action.cart_after
            if ca and ca.verification_method != "none":
                print(f"  [cart-after] {ca.verification_method}: count={ca.cart_items} elapsed={ca.elapsed_ms}ms")

            post_b64 = await page.screenshot()
            post_hash = hashlib.md5(post_b64.encode()).hexdigest()
            if post_hash == pre_hash:
                action.no_effect = True
                print(f"[step {step_idx}] no page change", file=sys.stderr)

            png_path = STEPS_DIR / f"{step_idx:03d}.png"
            png_path.write_bytes(base64.b64decode(post_b64))

            # Stuck-loop early-out: 5 consecutive no-effect actions means the
            # model is perseverating against a frozen page (Phase 14 saw 14
            # in a row before MAX_STEPS). Stop early so a stuck run costs
            # ~15s instead of ~2 minutes.
            streak = 0
            for a in reversed(history):
                if a.no_effect:
                    streak += 1
                else:
                    break
            if streak >= 5:
                print(
                    f"[step {step_idx}] stuck-loop early-out: {streak} "
                    "consecutive no-effect actions",
                    file=sys.stderr,
                )
                outcome = "stuck_loop"
                break

        FINAL_PNG.write_bytes(base64.b64decode(await page.screenshot()))
        elapsed = time.time() - t0
        print(f"\n=== outcome: {outcome} | steps: {len(history)} | elapsed: {elapsed:.1f}s ===")
        append_run(DEFAULT_LOG, {
            "task": task_module.__name__.rsplit(".", 1)[-1],
            "task_class": getattr(task_module, "TASK_CLASS", None),
            "model": os.environ.get("MODEL", "ui-venus-1.5-8b"),
            "harness": HARNESS,
            "phase": os.environ.get("PHASE", "untagged"),
            "outcome": outcome,
            "category": classify_failure(outcome=outcome, steps=len(history)),
            "steps": len(history),
            "elapsed_s": round(elapsed, 1),
            "final_screenshot": str(FINAL_PNG),
        })
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
