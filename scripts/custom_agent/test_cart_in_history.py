"""Task 1.3: cart-state-after-action must appear in the rendered history
block of the next turn's prompt. This is the channel the model 'sees'
cart state — the existing 'previous_actions' rendering at model.py
already handles no_effect; cart_after is added to that surface.
"""
from scripts.custom_agent.model import Action, _render_history_block
from scripts.custom_agent.cart_state import CartState


def test_cart_state_renders_in_history_block_when_method_is_localStorage():
    a = Action(kind="click", raw="Click(box=(500,400))", conclusion="add to cart")
    a.cart_after = CartState(
        cart_items=1,
        confidence="high",
        verification_method="localStorage",
        raw='["sauce-labs-backpack"]',
        elapsed_ms=12,
    )
    out = _render_history_block([a])
    assert "cart=1" in out, f"missing cart count in: {out!r}"
    assert "localStorage" in out, f"missing verification method in: {out!r}"


def test_cart_state_renders_when_method_is_dom():
    a = Action(kind="click", raw="Click(box=(500,400))", conclusion="add to cart")
    a.cart_after = CartState(cart_items=2, confidence="medium", verification_method="dom",
                              raw="2", elapsed_ms=8)
    out = _render_history_block([a])
    assert "cart=2" in out
    assert "dom" in out


def test_cart_state_NOT_rendered_when_method_is_none():
    """When the probe gets no signal, don't pollute the prompt with
    '[cart=None, m=none]' lines — the model already sees the screenshot
    so a 'we don't know' message is just noise."""
    a = Action(kind="click", raw="Click(box=(500,400))", conclusion="click something")
    a.cart_after = CartState(cart_items=None, confidence="low", verification_method="none",
                              raw=None, elapsed_ms=5)
    out = _render_history_block([a])
    assert "cart=" not in out, f"unexpected cart info in: {out!r}"
    assert "none" not in out.lower() or "no page change" in out.lower()  # 'no_effect' uses the word 'no'; allow that


def test_cart_state_absent_when_cart_after_is_None():
    """Steps before the cart probe runs (or steps with parse errors) won't
    have cart_after set. They must render cleanly without 'cart=' info."""
    a = Action(kind="click", raw="Click(box=(500,400))", conclusion="click")
    out = _render_history_block([a])
    assert "cart=" not in out


def test_action_cart_after_field_default_is_None():
    """The Action dataclass extension must default cart_after to None
    so existing callers / parse paths don't break."""
    a = Action(kind="click", raw="Click(box=(0,0))")
    assert a.cart_after is None


def test_cart_state_renders_alongside_no_effect():
    """The two harness signals must be combinable in one history line —
    a cart probe that fired AND the action having no_effect should both
    show. (Pathological case: the probe ran successfully but the model's
    action did nothing.)"""
    a = Action(kind="click", raw="Click(box=(500,400))", conclusion="click")
    a.no_effect = True
    a.cart_after = CartState(cart_items=0, confidence="high",
                              verification_method="localStorage",
                              raw="[]", elapsed_ms=3)
    out = _render_history_block([a])
    assert "no page change" in out
    assert "cart=0" in out
    assert "localStorage" in out
