import asyncio
from unittest.mock import AsyncMock, MagicMock

from scripts.custom_agent.cart_state import verify_cart_state, CartState, _count_from_storage
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


def test_dom_invalid_selector_does_not_abort_loop():
    """Verifies the DOM probe JS includes try/catch so a malformed selector
    doesn't silently skip later selectors. We test by checking that the
    constructed JS expression contains 'catch' — a behavioral assertion at
    the harness level. (Real CDP eval would simulate the page error path.)
    """
    page = MagicMock()
    page.session_id = "sid"
    page.client = MagicMock()
    sent_exprs = []

    async def send_raw(method, params, session_id=None):
        if method == "Runtime.evaluate":
            sent_exprs.append(params.get("expression", ""))
        return {"result": {"value": None}}

    page.client.send_raw = AsyncMock(side_effect=send_raw)
    asyncio.run(verify_cart_state(page, SAUCEDEMO, "https://www.saucedemo.com/"))

    dom_exprs = [e for e in sent_exprs if "querySelector" in e]
    assert dom_exprs, "DOM strategy never ran"
    assert "catch" in dom_exprs[0], (
        f"DOM JS must include try/catch so a bad selector doesn't abort the loop; "
        f"got expr={dom_exprs[0]!r}"
    )


def test_count_from_storage_edge_cases():
    assert _count_from_storage(None) is None
    assert _count_from_storage("") is None
    assert _count_from_storage([]) == 0  # empty list = 0 items
    assert _count_from_storage({}) is None  # dict without recognized keys
    assert _count_from_storage({"unrelated_key": 5}) is None
    assert _count_from_storage({"count": 7}) == 7
    assert _count_from_storage({"items": [1, 2, 3]}) == 3
    assert _count_from_storage([1, 2, 3]) == 3
    assert _count_from_storage(42) == 42
    assert _count_from_storage('not json at all{') is None


def test_localStorage_wins_when_both_have_signal():
    """If localStorage has a hit, the DOM probe must NOT fire — locks
    the strategy ordering invariant against future refactors."""
    page = MagicMock()
    page.session_id = "sid"
    page.client = MagicMock()
    queries = []

    async def send_raw(method, params, session_id=None):
        e = params.get("expression", "")
        queries.append(e)
        if "localStorage" in e:
            return {"result": {"value": '["item-a","item-b"]'}}
        if "querySelector" in e:
            # Would return a hit if asked, but should never be asked.
            return {"result": {"value": "999"}}
        return {"result": {"value": None}}

    page.client.send_raw = AsyncMock(side_effect=send_raw)
    state = asyncio.run(verify_cart_state(page, SAUCEDEMO, "https://www.saucedemo.com/inventory.html"))
    assert state.cart_items == 2
    assert state.verification_method == "localStorage"
    assert not any("querySelector" in q for q in queries), (
        "DOM probe ran even though localStorage had a hit; strategy ordering broken"
    )
