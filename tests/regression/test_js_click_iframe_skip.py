"""Regression lock for the iframe-skip fix in _js_click_fallback.

Best Buy stacks invisible analytics iframes over interactive areas.
elementsFromPoint returned the IFRAME element first, and the JS
fallback's `IFRAME.click()` is a no-op (clicking the iframe wrapper
doesn't activate the document inside). Fix: filter IFRAMEs from the
elementsFromPoint stack at every layer.

We can't easily exercise the fallback without a real Chromium; instead,
we lock the JS template's filter clause so it can't drift via
string-edit regressions.
"""
from __future__ import annotations
import asyncio
import re
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.custom_agent.actions import _js_click_fallback


def _captured_js_for_call(x: int, y: int) -> str:
    page = MagicMock()
    page.session_id = "x"
    page.client.send_raw = AsyncMock(
        return_value={"result": {"value": {"tag": "BUTTON", "skipped": 0}}}
    )
    asyncio.run(_js_click_fallback(page, x, y))
    return page.client.send_raw.await_args.args[1]["expression"]


def test_fallback_filters_iframe_from_elements_from_point():
    js = _captured_js_for_call(100, 200)
    # Must read the full stack (not just topmost), then filter IFRAMEs.
    assert "elementsFromPoint(100,200)" in js, "must use elementsFromPoint, not elementFromPoint"
    assert re.search(r"filter\s*\(\s*[a-z]\s*=>\s*[a-z]\.tagName\s*!==\s*['\"]IFRAME['\"]\s*\)", js), (
        "iframe filter clause missing from _js_click_fallback JS — Phase 18 regression"
    )
    # Must surface the count of skipped iframes for diagnostic logging.
    assert "skipped" in js, "must report `skipped` count for [skipped N iframe] log line"


def test_fallback_handles_iframe_only_stack():
    js = _captured_js_for_call(50, 50)
    # If post-filter list is empty, must return a {dropped:'iframe-only',...}
    # marker so the dispatcher logs the no-op rather than silently clicking.
    assert re.search(r"dropped\s*:\s*['\"]iframe-only['\"]", js), (
        "iframe-only stack handler missing — without it the fallback "
        "silently no-ops on Best Buy ad-frame stacks."
    )
