"""F-6 regression test: 'up' direction must move viewport DOWN (UI-Venus
mobile/swipe convention: up = swipe content up = see content below).
"""
from unittest.mock import AsyncMock, MagicMock
import asyncio
from scripts.custom_agent.actions import _scroll, _MIN_SCROLL_DELTA
from scripts.custom_agent.model import Action


def test_scroll_up_means_see_content_below():
    page = MagicMock()
    page.session_id = "sid"
    page.client = MagicMock()
    sent = []

    async def send_raw(method, params, session_id=None):
        sent.append((method, params))
        if method == "Runtime.evaluate" and "scrollY" in params.get("expression", ""):
            return {"result": {"value": 0}}
        return {"result": {"value": ""}}

    page.client.send_raw = AsyncMock(side_effect=send_raw)
    action = Action(kind="scroll", direction="up", raw="Scroll(direction='up')")
    asyncio.run(_scroll(page, action, (1280, 800)))

    wheel_calls = [p for m, p in sent if m == "Input.dispatchMouseEvent" and p.get("type") == "mouseWheel"]
    assert wheel_calls, "no mouseWheel dispatched"
    assert wheel_calls[0]["deltaY"] == _MIN_SCROLL_DELTA, (
        f"direction='up' should produce positive deltaY (viewport scrolls DOWN to reveal content below), "
        f"got deltaY={wheel_calls[0]['deltaY']}"
    )


def test_scroll_down_means_see_content_above():
    """Happy-path sign mapping for direction='down'. The mock advances
    scrollY after the first wheel so the retry guard sees progress
    (post != pre) and stays out — keeping this test focused purely on
    the sign-mapping contract.
    """
    page = MagicMock()
    page.session_id = "sid"
    page.client = MagicMock()
    sent = []
    state = {"scrollY": 100, "wheel_count": 0}

    async def send_raw(method, params, session_id=None):
        sent.append((method, params))
        if method == "Input.dispatchMouseEvent" and params.get("type") == "mouseWheel":
            state["wheel_count"] += 1
            # First (and only) wheel actually moves the page so retry doesn't fire.
            state["scrollY"] = -500
            return {"result": {}}
        if method == "Runtime.evaluate" and "scrollY" in params.get("expression", ""):
            return {"result": {"value": state["scrollY"]}}
        return {"result": {"value": ""}}

    page.client.send_raw = AsyncMock(side_effect=send_raw)
    action = Action(kind="scroll", direction="down", raw="Scroll(direction='down')")
    asyncio.run(_scroll(page, action, (1280, 800)))

    wheel_calls = [p for m, p in sent if m == "Input.dispatchMouseEvent" and p.get("type") == "mouseWheel"]
    assert len(wheel_calls) == 1, f"happy-path scroll should not retry; got {len(wheel_calls)} wheels"
    assert wheel_calls[0]["deltaY"] == -_MIN_SCROLL_DELTA


def test_no_progress_at_top_retries_with_flipped_sign():
    """Direction-only scroll at scrollY=0 that makes no progress should retry
    with the opposite sign before giving up. Model's direction-word
    convention is unstable across runs, so the dispatcher empirically
    flips on no-progress rather than picking a side.
    """
    page = MagicMock()
    page.session_id = "sid"
    page.client = MagicMock()
    sent = []
    state = {"scrollY": 0, "wheel_count": 0}

    async def send_raw(method, params, session_id=None):
        sent.append((method, params))
        if method == "Input.dispatchMouseEvent" and params.get("type") == "mouseWheel":
            state["wheel_count"] += 1
            # Second wheel (the retry) actually scrolls the page
            if state["wheel_count"] >= 2:
                state["scrollY"] = 600
            return {"result": {}}
        if method == "Runtime.evaluate" and "scrollY" in params.get("expression", ""):
            return {"result": {"value": state["scrollY"]}}
        # JS scrollBy fallback path — keep returning the same scrollY so the
        # _scroll's existing JS-fallback branch doesn't claim success on its own
        return {"result": {"value": ""}}

    page.client.send_raw = AsyncMock(side_effect=send_raw)
    action = Action(kind="scroll", direction="down", raw="Scroll(direction='down')")
    asyncio.run(_scroll(page, action, (1280, 800)))

    wheel_calls = [p for m, p in sent if m == "Input.dispatchMouseEvent" and p.get("type") == "mouseWheel"]
    assert len(wheel_calls) == 2, f"expected 2 wheel calls (one retry), got {len(wheel_calls)}"
    assert wheel_calls[0]["deltaY"] == -_MIN_SCROLL_DELTA  # first attempt: down convention
    assert wheel_calls[1]["deltaY"] == +_MIN_SCROLL_DELTA  # retry: flipped sign


def test_coord_based_scroll_does_not_retry():
    """When start/end coords are given, the model is being explicit about
    direction — don't second-guess by retrying with a flipped sign.
    """
    page = MagicMock()
    page.session_id = "sid"
    page.client = MagicMock()
    sent = []

    async def send_raw(method, params, session_id=None):
        sent.append((method, params))
        if method == "Runtime.evaluate" and "scrollY" in params.get("expression", ""):
            return {"result": {"value": 0}}
        return {"result": {"value": ""}}

    page.client.send_raw = AsyncMock(side_effect=send_raw)
    action = Action(
        kind="scroll",
        start_xy=(500, 500), end_xy=(500, 800),
        raw="Scroll(start=(500,500),end=(500,800))",
    )
    asyncio.run(_scroll(page, action, (1280, 800)))

    wheel_calls = [p for m, p in sent if m == "Input.dispatchMouseEvent" and p.get("type") == "mouseWheel"]
    assert len(wheel_calls) == 1, f"coord-based scroll should not retry; got {len(wheel_calls)} wheels"


def test_horizontal_direction_does_not_retry():
    """Horizontal direction-keyword scrolls must NOT retry on no-progress.
    `_scroll_y` only reads window.scrollY, so a working left/right scroll
    leaves scrollY unchanged and would trip the retry guard. The retry
    would then dispatch a flipped-sign wheel that reverses the intended
    horizontal motion. F-6's convention-instability story is vertical-only.
    """
    page = MagicMock()
    page.session_id = "sid"
    page.client = MagicMock()
    sent = []

    async def send_raw(method, params, session_id=None):
        sent.append((method, params))
        if method == "Runtime.evaluate" and "scrollY" in params.get("expression", ""):
            # scrollY pinned at 100 pre and post — exactly the trap that
            # caught a working horizontal scroll under the old guard.
            return {"result": {"value": 100}}
        return {"result": {"value": ""}}

    page.client.send_raw = AsyncMock(side_effect=send_raw)
    action = Action(kind="scroll", direction="left", raw="Scroll(direction='left')")
    asyncio.run(_scroll(page, action, (1280, 800)))

    wheel_calls = [p for m, p in sent if m == "Input.dispatchMouseEvent" and p.get("type") == "mouseWheel"]
    assert len(wheel_calls) == 1, f"horizontal direction scroll should not retry; got {len(wheel_calls)} wheels"
    assert wheel_calls[0]["deltaX"] == _MIN_SCROLL_DELTA
    assert wheel_calls[0]["deltaY"] == 0
