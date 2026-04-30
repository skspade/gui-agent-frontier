"""Deterministic cart-state probe (Phase 1 / Priority 1).

Strategies in priority order:
  1. localStorage / sessionStorage — most reliable when the site uses it
  2. cart-count DOM selectors — works on most ecommerce sites
  3. (forward-declared, not implemented in Phase 1) GET /cart or /api/cart

Returns a CartState with verification_method recorded so callers (and the
model, via the previous_actions block) can judge confidence. Phase 1
budget: <500ms; in practice <30ms because both strategies are single
Runtime.evaluate calls.
"""
from __future__ import annotations
import json
import time
from dataclasses import dataclass
from typing import Optional

from scripts.custom_agent.browser import Page
from scripts.custom_agent.site_configs import SiteConfig


@dataclass
class CartState:
    cart_items: Optional[int]
    confidence: str  # "high" | "medium" | "low"
    verification_method: str  # "localStorage" | "dom" | "api" | "none"
    raw: Optional[str] = None
    elapsed_ms: int = 0


async def verify_cart_state(page: Page, cfg: SiteConfig, url: str) -> CartState:
    """Probe the page for cart state using the strategies declared in cfg."""
    t0 = time.time()

    if cfg.cart_storage_keys:
        keys_js = json.dumps(list(cfg.cart_storage_keys))
        expr = (
            f"(()=>{{const keys={keys_js};"
            "for(const k of keys){"
            "const v=localStorage.getItem(k)||sessionStorage.getItem(k);"
            "if(v)return v;}return null;}})()"
        )
        r = await page.client.send_raw(
            "Runtime.evaluate", {"expression": expr, "returnByValue": True},
            session_id=page.session_id,
        )
        raw = r["result"].get("value")
        if raw:
            count = _count_from_storage(raw)
            return CartState(
                count, "high", "localStorage",
                raw=str(raw)[:200],
                elapsed_ms=int((time.time() - t0) * 1000),
            )

    if cfg.cart_count_selectors:
        sel_js = json.dumps(list(cfg.cart_count_selectors))
        expr = (
            f"(()=>{{const sels={sel_js};"
            "for(const s of sels){const e=document.querySelector(s);"
            "if(e&&e.textContent){const n=parseInt(e.textContent.trim(),10);"
            "if(!isNaN(n))return String(n);}}return null;}})()"
        )
        r = await page.client.send_raw(
            "Runtime.evaluate", {"expression": expr, "returnByValue": True},
            session_id=page.session_id,
        )
        raw = r["result"].get("value")
        if raw is not None:
            return CartState(
                int(raw), "medium", "dom",
                raw=str(raw),
                elapsed_ms=int((time.time() - t0) * 1000),
            )

    return CartState(
        None, "low", "none",
        elapsed_ms=int((time.time() - t0) * 1000),
    )


def _count_from_storage(raw):
    """Heuristic: parse common cart shapes (int, list, dict, JSON string) into an item count.

    Returns None if the shape isn't recognized — the caller treats that as 'no count'
    but still records the method as 'localStorage' (the storage HAD a value, we just
    can't extract a count from it). That distinction matters for selector calibration
    in Task 1.4.
    """
    if isinstance(raw, int):
        return raw
    if isinstance(raw, list):
        return len(raw)
    if isinstance(raw, dict):
        for k in ("count", "items", "lines", "products"):
            if k in raw:
                v = raw[k]
                if isinstance(v, int):
                    return v
                if isinstance(v, list):
                    return len(v)
        return None
    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            return None
        try:
            return _count_from_storage(json.loads(s))
        except json.JSONDecodeError:
            return None
    return None
