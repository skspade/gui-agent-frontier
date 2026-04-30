"""Single-step probe: exercise the active model's harness on saucedemo login.

Reads `MODEL=<alias>` env, dispatches via the same MODEL_HARNESS_REGISTRY
that scripts/custom_agent.py uses, and asks the model to take ONE step
toward logging in to saucedemo. Reports:
  - Raw response (when available)
  - Parsed Action
  - Distance from the click target to the closest sensible login element
    (username input center, password input center, or login button center)

Use to verify a per-model harness path is wired correctly without paying
for a full saucedemo_full_checkout run. Re-run on each model after adding
or modifying a harness.

Usage:
  MODEL=holo3-35b-a3b .venv/bin/python -u scripts/model_probe.py
  MODEL=mai-ui-8b     .venv/bin/python -u scripts/model_probe.py
"""
from __future__ import annotations

import asyncio
import collections
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.coord_remap import grounding_remap
from scripts.custom_agent import harness_for
from scripts.custom_agent.browser import launch_chromium, Page
from scripts.custom_agent.model import Action

START_URL = "https://www.saucedemo.com"
WINDOW_SIZE = (1280, 800)
TASK = (
    "Log in to saucedemo with username 'standard_user' and password "
    "'secret_sauce'. On this very first step, click on the Username input "
    "field so we can start typing into it."
)


async def _ground_truth(page: Page) -> dict[str, dict]:
    js = (
        "(() => {"
        "const ids = ['user-name','password','login-button'];"
        "const out = {};"
        "for (const id of ids) {"
        "  const el = document.getElementById(id);"
        "  if (!el) continue;"
        "  const r = el.getBoundingClientRect();"
        "  out[id] = {x:r.x,y:r.y,w:r.width,h:r.height,cx:r.x+r.width/2,cy:r.y+r.height/2};"
        "}"
        "return JSON.stringify(out);"
        "})()"
    )
    res = await page.client.send_raw(
        "Runtime.evaluate",
        {"expression": js, "returnByValue": True},
        session_id=page.session_id,
    )
    return json.loads(res["result"]["value"])


def _effective_xy(action: Action, viewport: tuple[int, int]) -> tuple[int, int] | None:
    """Apply the same coord transform the dispatcher will apply.

    `click` (UI-Venus, toolcall) goes through grounding_remap
    (0-1000 -> viewport). `click_at` (Holo3) is already viewport pixels.
    """
    if action.xy is None:
        return None
    if action.kind == "click":
        return grounding_remap(action.xy, viewport)
    return action.xy


def _summarize_action(action: Action, gt: dict[str, dict], viewport: tuple[int, int]) -> str:
    parts = [f"kind={action.kind}"]
    if action.xy is not None:
        rx, ry = action.xy
        parts.append(f"raw_xy=({rx},{ry})")
        eff = _effective_xy(action, viewport)
        if eff is not None and eff != action.xy:
            parts.append(f"effective_xy={eff}")
        x, y = eff if eff is not None else (rx, ry)
        nearest_id, nearest_dist = None, float("inf")
        for tid, box in gt.items():
            d = ((x - box["cx"]) ** 2 + (y - box["cy"]) ** 2) ** 0.5
            if d < nearest_dist:
                nearest_dist, nearest_id = d, tid
        if nearest_id:
            box = gt[nearest_id]
            inside = box["x"] <= x <= box["x"] + box["w"] and box["y"] <= y <= box["y"] + box["h"]
            parts.append(f"nearest=#{nearest_id} dist={nearest_dist:.0f}px inside={inside}")
    if action.text:
        parts.append(f"text={action.text!r}")
    if action.direction:
        parts.append(f"direction={action.direction}")
    if action.conclusion:
        parts.append(f"conclusion={action.conclusion[:80]!r}")
    return " ".join(parts)


async def main() -> int:
    model = os.environ.get("MODEL", "ui-venus-1.5-8b")
    harness = harness_for(model, os.environ.get("HARNESS"))
    print(f"=== probe: model={model} harness={harness} ===")

    proc, ws, ud = launch_chromium(headless=False, window_size=WINDOW_SIZE)
    try:
        page, client = await Page.attach(ws)
        await page.goto(START_URL)
        await asyncio.sleep(1.0)
        viewport = await page.viewport_css()
        b64 = await page.screenshot()
        gt = await _ground_truth(page)
        print(f"viewport={viewport[0]}x{viewport[1]}")
        for tid, box in gt.items():
            print(f"  ground truth #{tid:13} center=({box['cx']:.0f},{box['cy']:.0f}) "
                  f"box=[{box['x']:.0f},{box['y']:.0f},{box['w']:.0f},{box['h']:.0f}]")

        history: list[Action] = []
        notes_state = ""
        try:
            if harness == "holo3":
                from scripts.custom_agent.holo3 import navigate_step_holo3
                screens = collections.deque([b64], maxlen=3)
                action, notes_state = navigate_step_holo3(
                    TASK, history, list(screens), notes_state, viewport
                )
            elif harness == "toolcall":
                from scripts.custom_agent.toolcall import navigate_step_toolcall
                action = navigate_step_toolcall(TASK, history, b64, viewport)
            elif harness == "uivenus":
                from scripts.custom_agent.model import step as model_step, parse_action
                raw = model_step(TASK, history, b64)
                print(f"--- raw response ---\n{raw}\n--- end raw ---")
                action = parse_action(raw)
            else:
                print(f"unknown harness: {harness!r}", file=sys.stderr)
                return 2
        except Exception as e:
            print(f"\nFAIL: {type(e).__name__}: {e}", file=sys.stderr)
            return 1

        print(f"\nparsed: {_summarize_action(action, gt, viewport)}")
        if action.kind in ("click", "click_at") and action.xy is not None:
            eff = _effective_xy(action, viewport)
            ux = gt.get("user-name", {})
            if eff and ux:
                cx, cy = eff
                inside_username = ux["x"] <= cx <= ux["x"] + ux["w"] and ux["y"] <= cy <= ux["y"] + ux["h"]
                print(f"\nverdict: clicked-on-username = {inside_username}")
                return 0 if inside_username else 1
        return 0
    finally:
        proc.terminate()
        try:
            proc.wait(5)
        except subprocess.TimeoutExpired:
            proc.kill()
        shutil.rmtree(ud, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
