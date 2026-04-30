"""Heuristic fallback for any site we don't have explicit config for. The
_default has empty host_patterns so it never pre-empts a more specific config.
Cart-state probe iterates `_all_configs()` and falls back to this entry."""
from . import SiteConfig

CONFIG = SiteConfig(
    name="_default",
    host_patterns=(),
    cart_storage_keys=("cart", "shopping_cart", "basket", "bag"),
    cart_count_selectors=(
        "[class*='cart-count']",
        "[data-cart-count]",
        "[aria-label*='cart' i]",
        "[class*='basket']",
    ),
)
