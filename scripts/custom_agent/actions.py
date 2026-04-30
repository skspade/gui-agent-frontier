"""Action dispatchers. Add new handlers as the model emits new action kinds."""
from __future__ import annotations
import asyncio

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
    await asyncio.sleep(0.5)  # let the page react


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
    to dispatchKeyEvent so native <select> letter-jump triggers — Phase 14's
    saucedemo sort dropdown was structurally unreachable without this. The
    `text` param on keyDown fires both keydown and input events, which is
    enough for both form fields and selects.
    """
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
