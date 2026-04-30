from . import SiteConfig

CONFIG = SiteConfig(
    name="ikea",
    host_patterns=("ikea.com",),
    cart_storage_keys=("ikea-cart", "shoppingBag"),
    cart_count_selectors=(
        "[data-tracking-label='shoppingBag'] .hnf-badge",
        "[data-cart-count]",
    ),
)
