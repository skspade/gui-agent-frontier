from . import SiteConfig

# Calibrated 2026-04-30 (Task 1.4) by direct probe against bestbuy.com.
# Best Buy stores cart state in HttpOnly cookies (`CartItemCount`,
# `basketTimestamp`) — not in localStorage — so the storage strategy is
# skipped here. The DOM has a clean `[data-testid='cart-count']` element
# (a small dot-badge inside the cart icon) whose textContent is the bare
# count (e.g. "1"), which the probe's parseInt path handles directly. The
# seed selectors (`.cart-icon-count` and `[data-track='cartIcon'] .count`)
# didn't exist in the actual DOM. Cookie-based strategy is a future
# extension if the DOM selector ever stales — out of scope for Phase 1.
CONFIG = SiteConfig(
    name="bestbuy",
    host_patterns=("bestbuy.com",),
    cart_storage_keys=(),
    cart_count_selectors=(
        "[data-testid='cart-count']",
    ),
)
