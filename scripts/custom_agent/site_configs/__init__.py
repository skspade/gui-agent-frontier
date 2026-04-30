"""Per-site config registry for cart-state verification (Phase 1 / Priority 1).

Each site config declares the storage keys / DOM selectors used by
`scripts/custom_agent/cart_state.py:verify_cart_state` (Task 1.2). Adding a
new site = one file under this package.
"""
from __future__ import annotations
from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass
class SiteConfig:
    name: str
    host_patterns: tuple[str, ...]
    cart_storage_keys: tuple[str, ...] = ()
    cart_count_selectors: tuple[str, ...] = ()
    cart_api: str | None = None  # GET path for future API-based probe (Task 1.2 doesn't wire this yet)


def _all_configs() -> list[SiteConfig]:
    # Lazy import so each per-site file stays a leaf module (no circular deps).
    from . import saucedemo, ikea, bestbuy, _default
    return [saucedemo.CONFIG, ikea.CONFIG, bestbuy.CONFIG, _default.CONFIG]


def match_site_config(url: str) -> SiteConfig:
    """Return the first config whose host_patterns substring-match the URL's
    host. Falls back to _default when nothing matches."""
    host = (urlparse(url).hostname or "").lower()
    for cfg in _all_configs():
        if any(p in host for p in cfg.host_patterns):
            return cfg
    return _all_configs()[-1]  # _default
