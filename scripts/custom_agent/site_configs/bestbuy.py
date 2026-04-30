from . import SiteConfig

CONFIG = SiteConfig(
    name="bestbuy",
    host_patterns=("bestbuy.com",),
    cart_storage_keys=("cart", "BBYCart"),
    cart_count_selectors=(
        ".cart-icon-count",
        "[data-track='cartIcon'] .count",
    ),
)
