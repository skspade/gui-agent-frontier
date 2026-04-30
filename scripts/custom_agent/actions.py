"""Action dispatchers. Add new handlers as the model emits new action kinds."""
from __future__ import annotations
import asyncio
import json
import sys

from scripts.custom_agent.browser import Page
from scripts.custom_agent.model import Action
from scripts.coord_remap import grounding_remap

# Empirically verified in Task 1 (commit 6332f1c): the merged UI-Venus-1.5-8B
# emits 0-1000 normalized coords in the navigation chat template too. So
# grounding_remap is correct for both modes here.
COORD_MODE = "grounding"
remap = grounding_remap


async def dispatch(page: Page, action: Action, viewport_css: tuple[int, int]) -> None:
    """Translate one parsed Action into CDP Input.* events.

    Raises NotImplementedError for unhandled kinds — Task 7 catches and aborts.
    """
    if action.kind == "click":
        x, y = remap(action.xy, viewport_css)
        await _click(page, x, y)
    elif action.kind == "type":
        await _type_keys(page, action.text or "")
    elif action.kind == "click_at":
        # Holo3 click_element: coords already in viewport pixels (the holo3
        # localizer rescaled). Bypass the 0-1000 grounding remap that the
        # plain "click" kind applies for UI-Venus.
        await _click(page, action.xy[0], action.xy[1])
    elif action.kind == "click_then_type":
        # Holo3 write_element compounds a click + a type into one model
        # action (the dispatcher unfolds them). Coords are viewport pixels
        # (same reason as click_at), so we bypass remap here too.
        x, y = action.xy
        await _click(page, x, y)
        await _type_keys(page, action.text or "")
    elif action.kind == "scroll":
        await _scroll(page, action, viewport_css)
    elif action.kind == "drag":
        await _drag(page, action, viewport_css)
    elif action.kind in ("done", "call_user"):
        # CallUser is the model's "report final answer" verb; treat it like
        # done so a "PASS"/"FAIL" report cleanly terminates the run instead
        # of aborting as unhandled (Phase 14 finding 4).
        return
    elif action.kind in _PRESS_SPECS:
        await _press_key(page, action.kind)
    elif action.kind == "wait":
        await asyncio.sleep(1.0)
    else:
        raise NotImplementedError(f"unhandled action kind: {action.kind!r} (raw: {action.raw!r})")


async def _click(page: Page, x: int, y: int) -> None:
    # Phase 15 follow-up: if (x, y) hits an option inside a synthetic
    # <select> popup overlay, finalize that option directly — no real CDP
    # click. The overlay was injected on a prior click that landed on a
    # native <select> (headed Chromium <select> popups are OS-rendered and
    # invisible to CDP, so the model can't see or click options without a
    # synthetic stand-in).
    if await _try_overlay_click(page, x, y):
        return

    common = {"x": x, "y": y, "button": "left", "clickCount": 1}
    await page.client.send_raw(
        "Input.dispatchMouseEvent",
        {"type": "mousePressed", **common},
        session_id=page.session_id,
    )
    await page.client.send_raw(
        "Input.dispatchMouseEvent",
        {"type": "mouseReleased", **common},
        session_id=page.session_id,
    )
    # If the click landed on a native <select>, replace its OS-popup with
    # a DOM overlay so the model can see the options on the next turn and
    # click one.
    await _maybe_open_select_overlay(page, x, y)
    await asyncio.sleep(0.5)  # let the page react


_OVERLAY_CLASS = "__custom_agent_select_overlay__"

# Idempotent JS helpers stored as module-level strings so each call only
# ships the (x, y) numbers, not the full implementation.

_OPEN_OVERLAY_JS = """
(()=>{const x=__X__,y=__Y__;
const el=document.elementFromPoint(x,y);
if(!el||el.tagName!=='SELECT')return null;
el.focus();
document.querySelectorAll('.__OVERLAY_CLASS__').forEach(o=>o.remove());
const rect=el.getBoundingClientRect();
const overlay=document.createElement('div');
overlay.className='__OVERLAY_CLASS__';
const id='__caso_'+Date.now()+'_'+Math.random().toString(36).slice(2,8);
overlay.id=id;
el.dataset.casoOverlayId=id;
overlay.dataset.selectQuery=el.id?'#'+el.id:(el.getAttribute('data-test')?'[data-test='+JSON.stringify(el.getAttribute('data-test'))+']':'.'+el.className.trim().split(/\\s+/)[0]);
overlay.style.cssText='position:fixed;left:'+rect.left+'px;top:'+(rect.bottom+4)+'px;width:'+Math.max(rect.width,260)+'px;background:white;border:2px solid #4a4a4a;z-index:2147483647;font-family:sans-serif;font-size:16px;color:#222;box-shadow:0 4px 12px rgba(0,0,0,0.25);';
for(let i=0;i<el.options.length;i++){
  const o=el.options[i];
  const item=document.createElement('div');
  item.textContent=o.text;
  item.dataset.casoOptionValue=o.value;
  item.dataset.casoOptionIndex=String(i);
  const sel=(i===el.selectedIndex);
  item.style.cssText='padding:14px 16px;border-bottom:1px solid #ccc;background:'+(sel?'#cce5ff':'white')+';font-weight:'+(sel?'600':'400')+';';
  overlay.appendChild(item);
}
document.body.appendChild(overlay);
return el.getAttribute('data-test')||el.name||el.className||'select';})()
""".replace("__OVERLAY_CLASS__", _OVERLAY_CLASS).strip()


_OVERLAY_CLICK_JS = """
(()=>{const x=__X__,y=__Y__;
const el=document.elementFromPoint(x,y);
if(!el||!el.dataset||el.dataset.casoOptionValue===undefined)return null;
const overlay=el.closest('.__OVERLAY_CLASS__');
if(!overlay)return null;
const sel=document.querySelector(overlay.dataset.selectQuery);
if(!sel)return null;
sel.value=el.dataset.casoOptionValue;
sel.dispatchEvent(new Event('change',{bubbles:true}));
sel.dispatchEvent(new Event('input',{bubbles:true}));
overlay.remove();
return el.textContent;})()
""".replace("__OVERLAY_CLASS__", _OVERLAY_CLASS).strip()


async def _maybe_open_select_overlay(page: Page, x: int, y: int) -> None:
    js = _OPEN_OVERLAY_JS.replace("__X__", str(x)).replace("__Y__", str(y))
    r = await page.client.send_raw(
        "Runtime.evaluate", {"expression": js, "returnByValue": True},
        session_id=page.session_id,
    )
    label = r["result"].get("value")
    if label:
        print(f"  [dispatcher] opened <select> overlay: {label}", file=sys.stderr)


async def _try_overlay_click(page: Page, x: int, y: int) -> bool:
    """If (x, y) is on an overlay option, set the select's value and return True."""
    js = _OVERLAY_CLICK_JS.replace("__X__", str(x)).replace("__Y__", str(y))
    r = await page.client.send_raw(
        "Runtime.evaluate", {"expression": js, "returnByValue": True},
        session_id=page.session_id,
    )
    val = r["result"].get("value")
    if val:
        print(f"  [dispatcher] overlay option selected: {val!r}", file=sys.stderr)
        await asyncio.sleep(0.5)
        return True
    return False


# CDP key-event specs for the navigation-prompt's Press<X> verbs. Mobile-only
# verbs (PressRecent) intentionally absent — there's no desktop equivalent
# and we'd rather raise NotImplementedError than silently no-op.
_PRESS_SPECS = {
    "press_enter": {"key": "Enter", "code": "Enter", "windowsVirtualKeyCode": 13},
    "press_back": {"key": "Backspace", "code": "Backspace", "windowsVirtualKeyCode": 8},
    "press_home": {"key": "Home", "code": "Home", "windowsVirtualKeyCode": 36},
}


async def _press_key(page: Page, kind: str) -> None:
    spec = _PRESS_SPECS[kind]
    await page.client.send_raw(
        "Input.dispatchKeyEvent",
        {"type": "keyDown", **spec},
        session_id=page.session_id,
    )
    await page.client.send_raw(
        "Input.dispatchKeyEvent",
        {"type": "keyUp", **spec},
        session_id=page.session_id,
    )
    await asyncio.sleep(0.3)


async def _type_keys(page: Page, text: str) -> None:
    """Send text as real keyboard events, character by character.

    Was Input.insertText (faster, but only writes to focused inputs). Switched
    to dispatchKeyEvent so the events drive both form fields and other
    focused controls. The `text` param on keyDown fires both keydown and
    input events, which is enough for text inputs.

    Special case: a focused <select>. CDP keyDown events do NOT trigger
    Chromium's native letter-jump (the popup is OS-rendered and out of CDP
    reach; verified empirically with all 6 keyDown payload variants in
    Phase 15 follow-up). Detect this and apply a prefix-match programmatic
    option-set instead, so the model's "click dropdown → type 'p'" mental
    model continues to work end-to-end.
    """
    if await _maybe_select_letter_jump(page, text):
        return
    for ch in text:
        await page.client.send_raw(
            "Input.dispatchKeyEvent",
            {"type": "keyDown", "key": ch, "text": ch},
            session_id=page.session_id,
        )
        await page.client.send_raw(
            "Input.dispatchKeyEvent",
            {"type": "keyUp", "key": ch},
            session_id=page.session_id,
        )
    await asyncio.sleep(0.3)


async def _maybe_select_letter_jump(page: Page, text: str) -> bool:
    """If focus is on a <select>, set value to the first option whose text
    starts with `text` (case-insensitive). Returns True if applied.

    Also clears any open select overlay (we're going via the keyboard path).
    """
    if not text:
        return False
    js = (
        "(()=>{const s=document.activeElement;"
        "if(!s||s.tagName!=='SELECT')return null;"
        f"const t={json.dumps(text.lower())};"
        "for(const o of s.options){"
        "if(o.text.toLowerCase().startsWith(t)){"
        "s.value=o.value;s.dispatchEvent(new Event('change',{bubbles:true}));"
        f"document.querySelectorAll('.{_OVERLAY_CLASS}').forEach(x=>x.remove());"
        "return o.text;}}"
        "return false;})()"
    )
    r = await page.client.send_raw(
        "Runtime.evaluate", {"expression": js, "returnByValue": True},
        session_id=page.session_id,
    )
    val = r["result"].get("value")
    if val is None:
        return False  # focus not on a select
    if val is False:
        print(f"  [dispatcher] focused <select> has no option starting with {text!r}", file=sys.stderr)
        return False
    print(f"  [dispatcher] select letter-jump: typed {text!r} -> selected {val!r}", file=sys.stderr)
    return True


async def _scroll(page: Page, action: Action, viewport_css: tuple[int, int]) -> None:
    # Prefer model-provided start; fall back to viewport center.
    if action.start_xy is not None:
        sx, sy = remap(action.start_xy, viewport_css)
    else:
        sx, sy = viewport_css[0] // 2, viewport_css[1] // 2
    # Compute deltaY from start->end if both present, else fall back to direction.
    if action.start_xy is not None and action.end_xy is not None:
        ex, ey = remap(action.end_xy, viewport_css)
        dx, dy = ex - sx, ey - sy
    else:
        step = 400
        d = action.direction or "down"
        dx, dy = 0, (step if d == "down" else -step if d == "up" else 0)
        if d in ("left", "right"):
            dx = -step if d == "left" else step
    await page.client.send_raw(
        "Input.dispatchMouseEvent",
        {"type": "mouseWheel", "x": sx, "y": sy, "deltaX": dx, "deltaY": dy},
        session_id=page.session_id,
    )
    await asyncio.sleep(0.4)


async def _drag(page: Page, action: Action, viewport_css: tuple[int, int]) -> None:
    sx, sy = remap(action.start_xy, viewport_css)
    ex, ey = remap(action.end_xy, viewport_css)
    common_press = {"button": "left", "clickCount": 1, "x": sx, "y": sy}
    common_move = {"button": "left", "clickCount": 0}
    await page.client.send_raw(
        "Input.dispatchMouseEvent",
        {"type": "mousePressed", **common_press},
        session_id=page.session_id,
    )
    # Interpolate a few intermediate moves so canvas elements register the drag.
    steps = 8
    for i in range(1, steps + 1):
        ix = sx + (ex - sx) * i // steps
        iy = sy + (ey - sy) * i // steps
        await page.client.send_raw(
            "Input.dispatchMouseEvent",
            {"type": "mouseMoved", "x": ix, "y": iy, **common_move},
            session_id=page.session_id,
        )
        await asyncio.sleep(0.02)
    await page.client.send_raw(
        "Input.dispatchMouseEvent",
        {"type": "mouseReleased", "button": "left", "clickCount": 1, "x": ex, "y": ey},
        session_id=page.session_id,
    )
    await asyncio.sleep(0.4)
