import asyncio
from unittest.mock import AsyncMock, MagicMock

from scripts.custom_agent.cart_state import verify_cart_state, CartState
from scripts.custom_agent.site_configs.saucedemo import CONFIG as SAUCEDEMO
from scripts.custom_agent.site_configs._default import CONFIG as DEFAULT


def test_localStorage_strategy_returns_count_and_method():
    page = MagicMock()
    page.session_id = "sid"
    page.client = MagicMock()

    async def send_raw(method, params, session_id=None):
        if "localStorage" in params.get("expression", ""):
            return {"result": {"value": '["sauce-labs-backpack","sauce-labs-bike-light"]'}}
        return {"result": {"value": None}}

    page.client.send_raw = AsyncMock(side_effect=send_raw)
    state = asyncio.run(verify_cart_state(page, SAUCEDEMO, "https://www.saucedemo.com/inventory.html"))
    assert state.cart_items == 2
    assert state.confidence == "high"
    assert state.verification_method == "localStorage"


def test_no_signals_returns_none_method_and_low_confidence():
    page = MagicMock()
    page.session_id = "sid"
    page.client = MagicMock()

    async def send_raw(method, params, session_id=None):
        return {"result": {"value": None}}

    page.client.send_raw = AsyncMock(side_effect=send_raw)
    state = asyncio.run(verify_cart_state(page, DEFAULT, "https://unknown.example/"))
    assert state.cart_items is None
    assert state.confidence == "low"
    assert state.verification_method == "none"


def test_dom_strategy_used_when_localStorage_empty():
    page = MagicMock()
    page.session_id = "sid"
    page.client = MagicMock()

    async def send_raw(method, params, session_id=None):
        e = params.get("expression", "")
        if "localStorage" in e:
            return {"result": {"value": None}}
        if "querySelector" in e:
            return {"result": {"value": "3"}}
        return {"result": {"value": None}}

    page.client.send_raw = AsyncMock(side_effect=send_raw)
    state = asyncio.run(verify_cart_state(page, SAUCEDEMO, "https://www.saucedemo.com/inventory.html"))
    assert state.cart_items == 3
    assert state.verification_method == "dom"
    assert state.confidence == "medium"


def test_localStorage_integer_value_returns_int_directly():
    """The _count_from_storage helper must handle plain integer values
    (some sites store cart count, not the cart array)."""
    page = MagicMock()
    page.session_id = "sid"
    page.client = MagicMock()

    async def send_raw(method, params, session_id=None):
        if "localStorage" in params.get("expression", ""):
            return {"result": {"value": "5"}}
        return {"result": {"value": None}}

    page.client.send_raw = AsyncMock(side_effect=send_raw)
    state = asyncio.run(verify_cart_state(page, SAUCEDEMO, "https://www.saucedemo.com/inventory.html"))
    assert state.cart_items == 5
    assert state.verification_method == "localStorage"


def test_localStorage_dict_with_items_key():
    """Dict-shaped cart with an 'items' list is common."""
    page = MagicMock()
    page.session_id = "sid"
    page.client = MagicMock()

    async def send_raw(method, params, session_id=None):
        if "localStorage" in params.get("expression", ""):
            return {"result": {"value": '{"items":[{"sku":"a"},{"sku":"b"},{"sku":"c"}],"total":99.99}'}}
        return {"result": {"value": None}}

    page.client.send_raw = AsyncMock(side_effect=send_raw)
    state = asyncio.run(verify_cart_state(page, SAUCEDEMO, "https://www.saucedemo.com/inventory.html"))
    assert state.cart_items == 3
    assert state.verification_method == "localStorage"
