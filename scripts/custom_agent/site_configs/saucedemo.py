from . import SiteConfig

CONFIG = SiteConfig(
    name="saucedemo",
    host_patterns=("saucedemo.com",),
    cart_storage_keys=("cart-contents",),
    cart_count_selectors=(".shopping_cart_badge",),
)
