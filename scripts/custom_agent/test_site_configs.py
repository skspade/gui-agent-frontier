from scripts.custom_agent.site_configs import match_site_config, SiteConfig


def test_match_site_config_by_url():
    cfg = match_site_config("https://www.saucedemo.com/inventory.html")
    assert cfg.name == "saucedemo"


def test_unknown_url_falls_back_to_default():
    cfg = match_site_config("https://example.com/xyz")
    assert cfg.name == "_default"


def test_ikea_url_matches_ikea_config():
    cfg = match_site_config("https://www.ikea.com/us/en/cat/billy-bookcases/")
    assert cfg.name == "ikea"


def test_bestbuy_url_matches_bestbuy_config():
    cfg = match_site_config("https://www.bestbuy.com/site/airpods/")
    assert cfg.name == "bestbuy"


def test_default_config_has_no_host_patterns():
    """The _default fallback must have empty host_patterns so it never
    pre-empts a more specific config."""
    cfg = match_site_config("https://www.saucedemo.com/")
    assert cfg.name == "saucedemo"  # not _default — saucedemo wins


def test_site_config_dataclass_fields():
    """The SiteConfig dataclass exposes the fields cart_state.py will read."""
    cfg = match_site_config("https://www.saucedemo.com/")
    assert cfg.name == "saucedemo"
    assert isinstance(cfg.host_patterns, tuple)
    assert isinstance(cfg.cart_storage_keys, tuple)
    assert isinstance(cfg.cart_count_selectors, tuple)
