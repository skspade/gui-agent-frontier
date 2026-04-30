"""CP1-CP9 dispatcher probe for the saucedemo full-checkout task.

Drives each checkpoint with DOM-truth coords through the same dispatcher
the agent loop uses (`_click`, `_type_keys`, `_scroll`, `_press_key`).
No model in the loop. The point is to separate model precision failures
(model clicks the wrong pixel) from dispatcher gaps (CDP press+release
at the right pixel doesn't fire the right event).

For each CP:
  * Look up target rect via getBoundingClientRect()
  * Dispatch the action(s) at the rect center
  * Verify post-state via DOM/URL/text query
  * Save annotated screenshot to /tmp/saucedemo_flow_probe.cpN.png
  * Print one PASS|FAIL line with evidence

Run:
  DISPLAY=:0 XAUTHORITY=/run/user/1000/xauth_rVYaGJ XDG_RUNTIME_DIR=/run/user/1000 \\
    PYTHONUNBUFFERED=1 .venv/bin/python -u scripts/saucedemo_flow_probe.py \\
    > /tmp/saucedemo_flow_probe.log 2>&1
"""
from __future__ import annotations

import asyncio
import base64
import io
import json
import shutil
import sys
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.custom_agent.browser import launch_chromium, Page
from scripts.custom_agent.actions import _click, _type_keys, _press_key, _scroll
from scripts.custom_agent.model import Action

START_URL = "https://www.saucedemo.com"
WINDOW_SIZE = (1280, 800)
ARTIFACT_DIR = Path("/tmp")


def annotate(png_b64: str, click_xy: tuple[int, int] | None, label: str, out: Path) -> None:
    img = Image.open(io.BytesIO(base64.b64decode(png_b64))).convert("RGB")
    draw = ImageDraw.Draw(img)
    if click_xy is not None:
        x, y = click_xy
        r = 10
        draw.ellipse([x - r, y - r, x + r, y + r], outline="red", width=3)
        draw.line([x - r * 2, y, x + r * 2, y], fill="red", width=2)
        draw.line([x, y - r * 2, x, y + r * 2], fill="red", width=2)
    draw.text((10, 10), label, fill="red")
    img.save(out)


async def eval_js(page: Page, js: str):
    r = await page.client.send_raw(
        "Runtime.evaluate", {"expression": js, "returnByValue": True},
        session_id=page.session_id,
    )
    return r["result"].get("value")


async def rect_center(page: Page, selector: str) -> tuple[int, int] | None:
    """Return (cx, cy) for the first element matching selector, or None.
    Scrolls the element into view first (centered) so the returned coords
    are guaranteed to be inside the viewport — matching what a model would
    see and click in a real run."""
    js = (
        "(()=>{const e=document.querySelector(" + json.dumps(selector) + ");"
        "if(!e)return null;"
        "e.scrollIntoView({block:'center',inline:'center',behavior:'instant'});"
        "const r=e.getBoundingClientRect();"
        "return {x:r.x,y:r.y,w:r.width,h:r.height};})()"
    )
    box = await eval_js(page, js)
    if not box:
        return None
    return int(box["x"] + box["w"] / 2), int(box["y"] + box["h"] / 2)


async def in_viewport(page: Page, selector: str) -> bool:
    js = (
        "(()=>{const e=document.querySelector(" + json.dumps(selector) + ");"
        "if(!e)return false;const r=e.getBoundingClientRect();"
        "return r.top>=0 && r.bottom<=window.innerHeight;})()"
    )
    return bool(await eval_js(page, js))


def record(results: list, cp: int, label: str, ok: bool, evidence: str) -> None:
    tag = "PASS" if ok else "FAIL"
    line = f"CP{cp}: {label:40} -> {tag}  {evidence}"
    print(line)
    results.append((cp, label, ok, evidence))


async def cp1_login(page: Page, results: list) -> None:
    user_xy = await rect_center(page, "#user-name")
    pass_xy = await rect_center(page, "#password")
    btn_xy = await rect_center(page, "#login-button")
    assert user_xy and pass_xy and btn_xy, "login fields not found"
    await _click(page, *user_xy)
    await _type_keys(page, "standard_user")
    await _click(page, *pass_xy)
    await _type_keys(page, "secret_sauce")
    await _click(page, *btn_xy)
    await asyncio.sleep(1.5)
    url = await eval_js(page, "location.href")
    ok = "/inventory.html" in (url or "")
    annotate(await page.screenshot(), btn_xy, f"CP1 login url={url}",
             ARTIFACT_DIR / "saucedemo_flow_probe.cp1.png")
    record(results, 1, "login -> inventory", ok, f"url={url!r}")


async def cp2_sort_low_to_high(page: Page, results: list) -> None:
    sel_xy = await rect_center(page, ".product_sort_container")
    assert sel_xy, "sort select not found"
    await _click(page, *sel_xy)  # opens synthetic overlay
    await asyncio.sleep(0.4)
    # Find the lohi option's coords inside the overlay.
    opt_xy = await rect_center(page, '.__custom_agent_select_overlay__ [data-caso-option-value="lohi"]')
    assert opt_xy, "overlay 'lohi' option not found after click"
    await _click(page, *opt_xy)
    await asyncio.sleep(0.6)
    val = await eval_js(page, "document.querySelector('.product_sort_container').value")
    first = await eval_js(page, "document.querySelector('.inventory_item_name').textContent")
    ok = val == "lohi" and first == "Sauce Labs Onesie"
    annotate(await page.screenshot(), opt_xy,
             f"CP2 sort val={val} first={first}",
             ARTIFACT_DIR / "saucedemo_flow_probe.cp2.png")
    record(results, 2, "sort price low->high", ok,
           f"select.value={val!r} first={first!r}")


async def cp3_add_third_cheapest(page: Page, results: list) -> None:
    # Third-cheapest after lohi sort = Sauce Labs Bolt T-Shirt ($15.99).
    sel = "[data-test=add-to-cart-sauce-labs-bolt-t-shirt]"
    btn_xy = await rect_center(page, sel)
    assert btn_xy, f"{sel} not found pre-click"
    await _click(page, *btn_xy)
    await asyncio.sleep(0.5)
    badge = await eval_js(page, "(document.querySelector('.shopping_cart_badge')||{}).textContent")
    remove_present = await eval_js(
        page, "!!document.querySelector('[data-test=remove-sauce-labs-bolt-t-shirt]')")
    ok = badge == "1" and bool(remove_present)
    annotate(await page.screenshot(), btn_xy,
             f"CP3 badge={badge} remove={remove_present}",
             ARTIFACT_DIR / "saucedemo_flow_probe.cp3.png")
    record(results, 3, "add Bolt T-Shirt to cart", ok,
           f"badge={badge!r} remove_btn_present={remove_present}")


async def cp4_add_backpack(page: Page, results: list) -> None:
    sel = "[data-test=add-to-cart-sauce-labs-backpack]"
    # Scroll into view if needed. After lohi sort, backpack is row 2 of grid;
    # at 1280x800 it's likely visible, but the canonical task allows scroll.
    viewport = await page.viewport_css()
    scrolls = 0
    while not await in_viewport(page, sel) and scrolls < 5:
        await _scroll(page, Action(kind="scroll", direction="down"), viewport)
        scrolls += 1
        await asyncio.sleep(0.3)
    btn_xy = await rect_center(page, sel)
    assert btn_xy, f"{sel} not found"
    await _click(page, *btn_xy)
    await asyncio.sleep(0.5)
    badge = await eval_js(page, "(document.querySelector('.shopping_cart_badge')||{}).textContent")
    ok = badge == "2"
    annotate(await page.screenshot(), btn_xy,
             f"CP4 badge={badge} scrolls={scrolls}",
             ARTIFACT_DIR / "saucedemo_flow_probe.cp4.png")
    record(results, 4, "add Backpack to cart", ok,
           f"badge={badge!r} scrolls_used={scrolls}")


async def cp5_open_cart(page: Page, results: list) -> None:
    sel = ".shopping_cart_link"
    link_xy = await rect_center(page, sel)
    assert link_xy, f"{sel} not found"
    await _click(page, *link_xy)
    await asyncio.sleep(1.0)
    url = await eval_js(page, "location.href")
    ok = "/cart.html" in (url or "")
    annotate(await page.screenshot(), link_xy, f"CP5 url={url}",
             ARTIFACT_DIR / "saucedemo_flow_probe.cp5.png")
    record(results, 5, "open cart", ok, f"url={url!r}")


async def cp6_remove_bolt(page: Page, results: list) -> None:
    sel = "[data-test=remove-sauce-labs-bolt-t-shirt]"
    btn_xy = await rect_center(page, sel)
    assert btn_xy, f"{sel} not found pre-click"
    await _click(page, *btn_xy)
    await asyncio.sleep(0.5)
    still_there = await eval_js(page, f"!!document.querySelector('{sel}')")
    cart_count = await eval_js(page, "document.querySelectorAll('.cart_item').length")
    ok = (not still_there) and cart_count == 1
    annotate(await page.screenshot(), btn_xy,
             f"CP6 still={still_there} count={cart_count}",
             ARTIFACT_DIR / "saucedemo_flow_probe.cp6.png")
    record(results, 6, "remove Bolt from cart", ok,
           f"remove_btn_still_there={still_there} cart_items={cart_count}")


async def cp7_checkout_form(page: Page, results: list) -> None:
    # Query rect + click per field in lockstep: rect_center scrolls into
    # view, so caching all four rects up-front leaves three of them
    # pointing at where their target USED to be before the next scroll.
    async def click_field(sel, text=None):
        xy = await rect_center(page, sel)
        assert xy, f"{sel} not found"
        await _click(page, *xy)
        if text is not None:
            await _type_keys(page, text)
        return xy
    await click_field("[data-test=checkout]")
    await asyncio.sleep(0.8)
    await click_field("#first-name", "Test")
    await click_field("#last-name", "User")
    await click_field("#postal-code", "94000")
    cont_xy = await click_field("[data-test=continue]")
    await asyncio.sleep(1.0)
    url = await eval_js(page, "location.href")
    ok = "/checkout-step-two.html" in (url or "")
    annotate(await page.screenshot(), cont_xy, f"CP7 url={url}",
             ARTIFACT_DIR / "saucedemo_flow_probe.cp7.png")
    record(results, 7, "checkout form -> step two", ok, f"url={url!r}")


async def cp8_verify_total(page: Page, results: list) -> None:
    text = await eval_js(
        page,
        "(document.querySelector('.summary_subtotal_label')||{}).textContent")
    ok = "$29.99" in (text or "")
    annotate(await page.screenshot(), None,
             f"CP8 subtotal={text}",
             ARTIFACT_DIR / "saucedemo_flow_probe.cp8.png")
    record(results, 8, "subtotal includes $29.99", ok, f"subtotal_text={text!r}")


async def cp9_finish(page: Page, results: list) -> None:
    btn_xy = await rect_center(page, "[data-test=finish]")
    assert btn_xy, "finish button not found"
    await _click(page, *btn_xy)
    await asyncio.sleep(1.0)
    url = await eval_js(page, "location.href")
    body_text = await eval_js(page, "document.body.innerText")
    ok = ("/checkout-complete.html" in (url or "")) and \
         ("Thank you for your order!" in (body_text or ""))
    annotate(await page.screenshot(), btn_xy, f"CP9 url={url}",
             ARTIFACT_DIR / "saucedemo_flow_probe.cp9.png")
    snippet = (body_text or "").strip().splitlines()[:3]
    record(results, 9, "finish -> complete page", ok,
           f"url={url!r} body_head={snippet!r}")


CHECKPOINTS = [
    cp1_login, cp2_sort_low_to_high, cp3_add_third_cheapest, cp4_add_backpack,
    cp5_open_cart, cp6_remove_bolt, cp7_checkout_form, cp8_verify_total, cp9_finish,
]


async def main() -> int:
    proc, ws, ud = launch_chromium(headless=False, window_size=WINDOW_SIZE)
    results: list = []
    try:
        page, _ = await Page.attach(ws)
        await page.goto(START_URL)
        await asyncio.sleep(1.0)
        viewport = await page.viewport_css()
        print(f"viewport CSS = {viewport[0]}x{viewport[1]}")
        for fn in CHECKPOINTS:
            try:
                await fn(page, results)
            except Exception as e:
                cp = int(fn.__name__.split("_")[0][2:])
                record(results, cp, fn.__name__, False, f"exception: {e!r}")
        print("\n=== summary ===")
        for cp, label, ok, ev in results:
            tag = "PASS" if ok else "FAIL"
            print(f"  CP{cp}: {tag}  {label}  -- {ev}")
        passed = sum(1 for _, _, ok, _ in results if ok)
        print(f"\n{passed}/{len(results)} checkpoints PASS")
        return 0 if passed == len(CHECKPOINTS) else 1
    finally:
        proc.terminate()
        try: proc.wait(5)
        except Exception: proc.kill()
        shutil.rmtree(ud, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
