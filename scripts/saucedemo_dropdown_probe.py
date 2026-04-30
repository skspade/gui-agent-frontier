"""Probe what the agent CAN and CANNOT perceive/operate on saucedemo's
sort <select> dropdown.

Runs no model — just drives the browser with CDP from a hardcoded script
to answer "is this our tooling or the model?":

  1. Log in as standard_user (typed via the same CDP path the agent uses).
  2. Capture the inventory page (this is what the model sees on its first
     post-login turn).
  3. Click the sort <select> at its DOM-truth coordinates.
  4. Capture again — does the dropdown popup appear in the screenshot?
  5. Try the per-character letter-jump (Type('p')) the way the dispatcher
     does — does it select 'Price (low to high)'?
  6. Try direct DOM .value = 'lohi' + change event — does the page reorder?
  7. Print first product card visible after each step so we can verify the
     sort actually applied.

Saves screenshots to /tmp/saucedemo_dropdown.{0..6}.png with overlays
showing the click point.
"""
from __future__ import annotations

import asyncio
import base64
import json
import shutil
import sys
import time
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.custom_agent.browser import launch_chromium, Page
from scripts.custom_agent.actions import _click, _type_keys, _press_key

START_URL = "https://www.saucedemo.com"
WINDOW_SIZE = (1280, 800)


def annotate(png_b64: str, click_xy: tuple[int, int] | None, label: str, out: Path) -> None:
    img = Image.open(__import__("io").BytesIO(base64.b64decode(png_b64))).convert("RGB")
    draw = ImageDraw.Draw(img)
    if click_xy is not None:
        x, y = click_xy
        r = 10
        draw.ellipse([x - r, y - r, x + r, y + r], outline="red", width=3)
        draw.line([x - r * 2, y, x + r * 2, y], fill="red", width=2)
        draw.line([x, y - r * 2, x, y + r * 2], fill="red", width=2)
    draw.text((10, 10), label, fill="red")
    img.save(out)


async def eval_js(page: Page, js: str) -> str:
    r = await page.client.send_raw(
        "Runtime.evaluate", {"expression": js, "returnByValue": True},
        session_id=page.session_id,
    )
    return r["result"].get("value", "")


async def main() -> int:
    proc, ws, ud = launch_chromium(headless=False, window_size=WINDOW_SIZE)
    try:
        page, _ = await Page.attach(ws)
        await page.goto(START_URL)
        await asyncio.sleep(1.0)
        viewport = await page.viewport_css()
        print(f"viewport CSS = {viewport[0]}x{viewport[1]}")

        # --- 1. Log in
        # username field via known DOM coords (calibrated earlier).
        await _click(page, 600, 174)
        await _type_keys(page, "standard_user")
        await _click(page, 600, 228)
        await _type_keys(page, "secret_sauce")
        await _click(page, 616, 326)  # Login button center
        await asyncio.sleep(1.5)
        b64 = await page.screenshot()
        annotate(b64, None, "step 1: post-login", Path("/tmp/saucedemo_dropdown.1.png"))
        url = await eval_js(page, "location.href")
        first = await eval_js(page, "document.querySelector('.inventory_item_name').textContent")
        print(f"step 1 url={url}  first product={first!r}")

        # --- 2. Get the dropdown's DOM-truth coords and visible state
        sel_box = await eval_js(
            page,
            "(()=>{const s=document.querySelector('.product_sort_container');"
            "const r=s.getBoundingClientRect();"
            "return JSON.stringify({x:r.x,y:r.y,w:r.width,h:r.height,"
            "value:s.value,outerHTML:s.outerHTML.slice(0,200)});})()",
        )
        sel = json.loads(sel_box)
        cx = int(sel["x"] + sel["w"] / 2)
        cy = int(sel["y"] + sel["h"] / 2)
        print(f"step 2 dropdown box: x={sel['x']:.0f} y={sel['y']:.0f} "
              f"w={sel['w']:.0f} h={sel['h']:.0f}  center=({cx},{cy})  "
              f"current value={sel['value']!r}")
        print(f"step 2 outerHTML[:200]={sel['outerHTML']!r}")
        annotate(b64, (cx, cy), f"step 2: dropdown rect center=({cx},{cy})",
                 Path("/tmp/saucedemo_dropdown.2.png"))

        # --- 3. Click the dropdown center (CDP press+release)
        await _click(page, cx, cy)
        await asyncio.sleep(0.6)
        b64_after_click = await page.screenshot()
        # Did anything change?
        same_as_before = (b64_after_click == b64)
        print(f"step 3 click-only: page identical to pre-click? {same_as_before}")
        active = await eval_js(page, "document.activeElement.outerHTML.slice(0,150)")
        print(f"step 3 activeElement after click: {active!r}")
        annotate(b64_after_click, (cx, cy),
                 f"step 3: after CDP click on dropdown (identical={same_as_before})",
                 Path("/tmp/saucedemo_dropdown.3.png"))

        # --- 4. Try the Type('p') letter-jump trick (per-char keydown via dispatcher)
        await _type_keys(page, "p")
        await asyncio.sleep(0.6)
        b64_after_p = await page.screenshot()
        first_after_p = await eval_js(page, "document.querySelector('.inventory_item_name').textContent")
        val_after_p = await eval_js(page, "document.querySelector('.product_sort_container').value")
        print(f"step 4 after Type('p'):  first product={first_after_p!r}  "
              f"select.value={val_after_p!r}  page changed={b64_after_p != b64_after_click}")
        annotate(b64_after_p, None,
                 f"step 4: after Type('p') first={first_after_p}",
                 Path("/tmp/saucedemo_dropdown.4.png"))

        # Reset value before testing direct DOM path so steps don't compound.
        await eval_js(
            page,
            "(()=>{const s=document.querySelector('.product_sort_container');"
            "s.value='az';s.dispatchEvent(new Event('change',{bubbles:true}));})()",
        )
        await asyncio.sleep(0.6)
        first_reset = await eval_js(page, "document.querySelector('.inventory_item_name').textContent")
        print(f"step 5 reset to az: first product={first_reset!r}")

        # --- 6. Direct-DOM affordance: set value + dispatch change event
        await eval_js(
            page,
            "(()=>{const s=document.querySelector('.product_sort_container');"
            "s.value='lohi';s.dispatchEvent(new Event('change',{bubbles:true}));})()",
        )
        await asyncio.sleep(0.6)
        b64_dom = await page.screenshot()
        first_dom = await eval_js(page, "document.querySelector('.inventory_item_name').textContent")
        val_dom = await eval_js(page, "document.querySelector('.product_sort_container').value")
        print(f"step 6 after direct DOM .value='lohi':  first product={first_dom!r}  "
              f"select.value={val_dom!r}")
        annotate(b64_dom, None,
                 f"step 6: after DOM .value=lohi first={first_dom}",
                 Path("/tmp/saucedemo_dropdown.6.png"))

        return 0
    finally:
        proc.terminate()
        try: proc.wait(5)
        except: proc.kill()
        shutil.rmtree(ud, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
