from . import SiteConfig

# Calibrated 2026-04-30 (Task 1.4) by direct probe against ikea.com/us/en/.
# `cart-state-us` is a JSON array of items — `_count_from_storage` parses it via
# the str -> json.loads -> list branch, so an empty cart = 0 and a populated
# cart returns the item count. `cart-data-us` is a richer object whose
# `cartItems` key our helper doesn't recognize today; kept as a fallback in
# case `cart-state-us` is ever renamed. The DOM bag link uses kebab-case
# `data-tracking-label='shopping-bag'` (NOT the seed's camelCase `shoppingBag`
# — that was a typo on the original guess).
CONFIG = SiteConfig(
    name="ikea",
    host_patterns=("ikea.com",),
    cart_storage_keys=("cart-state-us", "cart-data-us"),
    cart_count_selectors=(
        "[data-tracking-label='shopping-bag'] [class*='badge']",
        "a[aria-label='Shopping bag'] [class*='count']",
        "[data-cart-count]",
    ),
)
