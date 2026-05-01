"""Regression lock for the coord double-remap bug.

The R1 / Phase 14 bug: Holo3 emits viewport-pixel click coords (its own
localizer rescales). The dispatcher was passing those through
`grounding_remap`, which assumes 0-1000 normalized coords, sending the
click 50-200px off-target. Fix: split `kind="click"` (UI-Venus norm,
remap) from `kind="click_at"` / `kind="click_then_type"` (Holo3 viewport
pixels, no remap). Test pins both branches.
"""
from __future__ import annotations
import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.custom_agent.actions import dispatch
from scripts.custom_agent.model import Action

VIEWPORT = (1280, 800)


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def test_click_kind_applies_grounding_remap():
    """UI-Venus 'click' coords are 0-1000 normalized → must be remapped."""
    action = Action(kind="click", xy=(500, 500), raw="click(point=(500,500))")
    page = object()  # never touched; _click is mocked
    with patch("scripts.custom_agent.actions._click", new=AsyncMock()) as mck:
        _run(dispatch(page, action, VIEWPORT))
        assert mck.await_count == 1
        _, x, y = mck.await_args.args
        # grounding_remap((500,500), (1280,800)) → (640, 400)
        assert (x, y) == (640, 400), (
            f"'click' kind must go through grounding_remap; got ({x},{y}) "
            f"— a regression to the double-remap bug or a remap removal."
        )


def test_click_at_kind_bypasses_grounding_remap():
    """Holo3 'click_at' coords are viewport pixels → must NOT be remapped."""
    action = Action(kind="click_at", xy=(640, 400), raw="click_element(640,400)")
    page = object()
    with patch("scripts.custom_agent.actions._click", new=AsyncMock()) as mck:
        _run(dispatch(page, action, VIEWPORT))
        assert mck.await_count == 1
        _, x, y = mck.await_args.args
        assert (x, y) == (640, 400), (
            f"'click_at' kind must bypass grounding_remap (Holo3 already "
            f"emits viewport-pixel coords); got ({x},{y}). "
            f"This is the double-remap bug — see findings.md L1551."
        )


def test_click_then_type_bypasses_grounding_remap():
    """Holo3 'click_then_type' compounds click+type; click coords still raw."""
    action = Action(kind="click_then_type", xy=(640, 400), text="hello",
                    raw="write_element(640,400,'hello')")
    page = object()
    with patch("scripts.custom_agent.actions._click", new=AsyncMock()) as mck_click, \
         patch("scripts.custom_agent.actions._type_keys", new=AsyncMock()):
        _run(dispatch(page, action, VIEWPORT))
        _, x, y = mck_click.await_args.args
        assert (x, y) == (640, 400), \
            f"'click_then_type' must bypass remap (same reason as click_at); got ({x},{y})"
