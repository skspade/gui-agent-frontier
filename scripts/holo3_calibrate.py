"""Localizer coord-contract calibration probe (Phase 15, kept for re-runs).

Established 2026-04-29 that Holo3-35B-A3B IQ3_XXS emits coords in
[0, 1000] x [0, 1000] normalized space (Contract C below). The other
two contracts (A: 1000x500 absolute pixels per surfer-h-cli's Holo1.5
convention; B: native dims as CSS pixels per Zak El Fassi's writeup)
both miss every probe target. Re-run this script before adding any new
localizer-style model so we don't ship a wrong contract again.

Probes a handful of known-id targets on the saucedemo login page,
calls the localizer for each via the production holo3.step_holo3_localize
(which uses Contract C), and reports per-target distance + inside-box.
"""
from __future__ import annotations

import asyncio
import base64
import io
import json
import sys
import time
from pathlib import Path

import httpx
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.custom_agent.browser import launch_chromium, Page
from scripts.custom_agent.holo3 import (
    LLAMA_URL, MODEL_NAME, ClickAbsoluteAction, create_localization_prompt,
    LOCALIZATION_TEMPERATURE, LOCALIZATION_NORMALIZED_RANGE,
    step_holo3_localize, _decode_png_b64, _encode_jpeg_b64,
)

START_URL = "https://www.saucedemo.com"
WINDOW_SIZE = (1280, 800)

# Test multiple descriptions against multiple ground-truth selectors so we can
# distinguish "wrong contract" from "wrong description" from "model just bad
# at this scale". A description that scores well across targets is contract-
# correct; one that misses every target points at the model.
PROBES = [
    ("Username input field", "user-name"),
    ("Username text box at the top of the login form", "user-name"),
    ("Login button (green button at the bottom)", "login-button"),
    ("Password input field", "password"),
]


def _localize_raw(screenshot_b64: str, element: str, *, timeout: float = 60.0) -> tuple[int, int]:
    """Send screenshot at native size, return RAW model coords (no rescale)."""
    img = _decode_png_b64(screenshot_b64)
    jpeg_b64 = _encode_jpeg_b64(img)
    payload = {
        "model": MODEL_NAME,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"detail": "auto", "url": f"data:image/jpeg;base64,{jpeg_b64}"}},
                    {"type": "text", "text": create_localization_prompt(element)},
                ],
            }
        ],
        "temperature": LOCALIZATION_TEMPERATURE,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "click_absolute_action",
                "schema": ClickAbsoluteAction.model_json_schema(),
                "strict": True,
            },
        },
        "chat_template_kwargs": {"enable_thinking": False},
        "max_tokens": 256,
    }
    r = httpx.post(LLAMA_URL, json=payload, timeout=timeout)
    r.raise_for_status()
    parsed = ClickAbsoluteAction.model_validate_json(r.json()["choices"][0]["message"]["content"])
    return parsed.x, parsed.y




def overlay(screenshot_b64: str, hit_xy: tuple[int, int], gt_box: dict, out: Path, label: str) -> None:
    img = _decode_png_b64(screenshot_b64).convert("RGB")
    draw = ImageDraw.Draw(img)
    # ground-truth box (green rectangle)
    x1, y1 = int(gt_box["x"]), int(gt_box["y"])
    x2 = x1 + int(gt_box["w"])
    y2 = y1 + int(gt_box["h"])
    draw.rectangle([x1, y1, x2, y2], outline="lime", width=3)
    # hit point (red crosshair)
    hx, hy = hit_xy
    r = 12
    draw.ellipse([hx - r, hy - r, hx + r, hy + r], outline="red", width=3)
    draw.line([hx - r * 2, hy, hx + r * 2, hy], fill="red", width=2)
    draw.line([hx, hy - r * 2, hx, hy + r * 2], fill="red", width=2)
    draw.text((10, 10), label, fill="red")
    img.save(out)


async def main() -> int:
    proc, ws, ud = launch_chromium(headless=False, window_size=WINDOW_SIZE)
    rows: list[dict] = []
    try:
        page, client = await Page.attach(ws)
        await page.goto(START_URL)
        await asyncio.sleep(1.0)  # let the form paint
        viewport = await page.viewport_css()
        print(f"viewport CSS = {viewport[0]}x{viewport[1]}")

        b64 = await page.screenshot()
        img = _decode_png_b64(b64)
        print(f"screenshot dims = {img.size[0]}x{img.size[1]}")

        for desc, target_id in PROBES:
            result = await page.client.send_raw(
                "Runtime.evaluate",
                {
                    "expression": (
                        "(()=>{const r=document.getElementById('"
                        + target_id
                        + "').getBoundingClientRect();return JSON.stringify({x:r.x,y:r.y,w:r.width,h:r.height});})()"
                    ),
                    "returnByValue": True,
                },
                session_id=page.session_id,
            )
            gt_box = json.loads(result["result"]["value"])
            gt_cx = gt_box["x"] + gt_box["w"] / 2
            gt_cy = gt_box["y"] + gt_box["h"] / 2
            print(f"\n=== probe: {desc!r} → #{target_id}")
            print(f"ground truth: x={gt_box['x']:.0f} y={gt_box['y']:.0f} "
                  f"w={gt_box['w']:.0f} h={gt_box['h']:.0f} center=({gt_cx:.0f},{gt_cy:.0f})")

            cx, cy = step_holo3_localize(b64, desc, viewport)
            c_dist = ((cx - gt_cx) ** 2 + (cy - gt_cy) ** 2) ** 0.5
            c_inside = (gt_box["x"] <= cx <= gt_box["x"] + gt_box["w"]
                        and gt_box["y"] <= cy <= gt_box["y"] + gt_box["h"])
            print(f"[Contract C: 0-1000 normalized] ({cx},{cy})  dist={c_dist:.0f}px  inside={c_inside}")

            slug = target_id.replace("-", "_") + "_" + desc[:12].replace(" ", "_")
            overlay(b64, (cx, cy), gt_box, Path(f"/tmp/holo3_calibrate.{slug}.png"),
                    f"'{desc[:40]}': ({cx},{cy}) d={c_dist:.0f}")
            rows.append({
                "desc": desc, "target": target_id,
                "c": (cx, cy), "c_dist": c_dist, "c_inside": c_inside,
            })

        print("\n=== Summary ===")
        print(f"{'desc':50} {'hit':12} {'dist':>7} {'inside':6}")
        for r in rows:
            print(f"{r['desc'][:50]:50} {str(r['c']):12} {r['c_dist']:7.0f} {str(r['c_inside']):6}")

        hits = sum(1 for r in rows if r["c_inside"])
        print(f"\n{hits}/{len(rows)} probes landed inside-box (Contract C, 0-1000 normalized)")
        return 0 if hits == len(rows) else 1
    finally:
        proc.terminate()
        try:
            proc.wait(5)
        except Exception:
            proc.kill()
        import shutil
        shutil.rmtree(ud, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
