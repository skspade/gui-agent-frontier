"""Regression lock for Phase 18 scroll-clamp fix.

Best Buy AirPods Pro 3 Add-to-Cart sits ~2500-3500px down a long PDP. The
model's start->end coords typically span 250-300px. Without the clamp,
the agent burned its step budget at 254px/scroll. Fix: floor the magnitude
at _MIN_SCROLL_DELTA = 600 while preserving direction sign.
"""
from __future__ import annotations
import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.custom_agent.actions import _scroll, _MIN_SCROLL_DELTA
from scripts.custom_agent.model import Action

VIEWPORT = (1280, 800)
_run = asyncio.run


def test_min_scroll_delta_constant():
    assert _MIN_SCROLL_DELTA >= 600, (
        f"_MIN_SCROLL_DELTA dropped below 600 (got {_MIN_SCROLL_DELTA}). "
        f"Phase 18 found 600 was the floor that kept BestBuy AirPods PDP "
        f"reachable in the step budget."
    )


def _make_page_with_dispatch_capture():
    """Returns (page, send_raw mock). page.client.send_raw is an AsyncMock
    that records each invocation."""
    page = MagicMock()
    page.session_id = "x"
    page.client.send_raw = AsyncMock(return_value={"result": {"value": {"clicks": 0, "keys": 0, "url": "http://x"}}})
    return page, page.client.send_raw


def test_small_span_clamped_to_floor_down():
    """start (500, 500) → end (500, 813) is a 250-ish-px-down span (after
    grounding_remap of 0-1000 norm coords); deltaY must be clamped to
    _MIN_SCROLL_DELTA, sign preserved (down → positive in F-6 wheel
    convention since end_y > start_y after remap)."""
    action = Action(kind="scroll", start_xy=(500, 500), end_xy=(500, 813),
                    raw="scroll(start=(500,500),end=(500,813))")
    page, send_raw = _make_page_with_dispatch_capture()
    with patch("scripts.custom_agent.actions._input_probe", new=AsyncMock(return_value={"clicks": 0, "keys": 0, "url": "http://x"})), \
         patch("scripts.custom_agent.actions._scroll_y", new=AsyncMock(return_value=0)), \
         patch("scripts.custom_agent.actions._scroll_layout_probe", new=AsyncMock(return_value={"docH": 5000, "innerH": 800})):
        _run(_scroll(page, action, VIEWPORT))

    wheel_calls = [c for c in send_raw.await_args_list
                   if c.args[0] == "Input.dispatchMouseEvent"
                   and c.args[1].get("type") == "mouseWheel"]
    assert wheel_calls, "expected at least one mouseWheel dispatch"
    dy = wheel_calls[0].args[1]["deltaY"]
    assert abs(dy) >= _MIN_SCROLL_DELTA, (
        f"deltaY={dy} not clamped to floor {_MIN_SCROLL_DELTA}. "
        f"Phase 18 regression."
    )
    assert dy > 0, f"sign must be preserved (down→positive); got {dy}"


def test_direction_only_uses_floor_magnitude():
    """direction='down' with no start/end → must produce a wheel dispatch
    with magnitude == _MIN_SCROLL_DELTA. Per actions.py:429 (F-6 inversion),
    direction='down' → dy_sign = -1 → deltaY = -_MIN_SCROLL_DELTA."""
    action = Action(kind="scroll", direction="down", raw="scroll('down')")
    page, send_raw = _make_page_with_dispatch_capture()
    with patch("scripts.custom_agent.actions._input_probe", new=AsyncMock(return_value={"clicks": 0, "keys": 0, "url": "http://x"})), \
         patch("scripts.custom_agent.actions._scroll_y", new=AsyncMock(return_value=0)), \
         patch("scripts.custom_agent.actions._scroll_layout_probe", new=AsyncMock(return_value={"docH": 5000, "innerH": 800})):
        _run(_scroll(page, action, VIEWPORT))

    wheel_calls = [c for c in send_raw.await_args_list
                   if c.args[0] == "Input.dispatchMouseEvent"
                   and c.args[1].get("type") == "mouseWheel"]
    dy = wheel_calls[0].args[1]["deltaY"]
    assert abs(dy) == _MIN_SCROLL_DELTA
    assert dy < 0, f"direction='down' must produce negative deltaY (F-6 convention); got {dy}"


def test_micro_span_clamped_regardless_of_floor():
    """start=(500,500) → end=(500,520): post-remap dy ≈ 16px, smaller
    than any reasonable floor. Catches clamp-branch removal even if
    _MIN_SCROLL_DELTA is independently lowered.

    Math: round(520/1000 * 800) - round(500/1000 * 800) = 416 - 400 = 16.
    """
    action = Action(kind="scroll", start_xy=(500, 500), end_xy=(500, 520),
                    raw="scroll(start=(500,500),end=(500,520))")
    page, send_raw = _make_page_with_dispatch_capture()
    with patch("scripts.custom_agent.actions._input_probe", new=AsyncMock(return_value={"clicks": 0, "keys": 0, "url": "http://x"})), \
         patch("scripts.custom_agent.actions._scroll_y", new=AsyncMock(return_value=0)), \
         patch("scripts.custom_agent.actions._scroll_layout_probe", new=AsyncMock(return_value={"docH": 5000, "innerH": 800})):
        _run(_scroll(page, action, VIEWPORT))
    wheel_calls = [c for c in send_raw.await_args_list
                   if c.args[0] == "Input.dispatchMouseEvent"
                   and c.args[1].get("type") == "mouseWheel"]
    assert wheel_calls, "expected at least one mouseWheel dispatch"
    dy = wheel_calls[0].args[1]["deltaY"]
    # Raw computed dy is ~16; this assertion only holds if the clamp
    # branch executed.
    assert abs(dy) >= _MIN_SCROLL_DELTA, (
        f"micro-span dy={dy} not clamped — clamp branch likely removed."
    )
    assert dy > 0
