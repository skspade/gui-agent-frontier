"""Unit tests for downgrade_outcome_if_cart_short.

Locks the cart-state-based downgrade rule used by the runner's final-check
verification (custom_agent.py). Mirror of the existing visual-pixel upgrade
pattern: the upgrade promotes premature_done to done when the canvas has
signal; this downgrade demotes done to premature_done when the cart hasn't
filled.
"""
from __future__ import annotations

from scripts.custom_agent.run_log import downgrade_outcome_if_cart_short


def test_no_threshold_means_no_downgrade():
    """Tasks without MIN_FINAL_CART_COUNT pass through unchanged."""
    assert downgrade_outcome_if_cart_short(
        outcome="done", min_final=None, cart_count=0,
    ) == ("done", False)


def test_done_with_full_cart_passes_through():
    assert downgrade_outcome_if_cart_short(
        outcome="done", min_final=1, cart_count=1,
    ) == ("done", False)


def test_call_user_with_full_cart_passes_through():
    assert downgrade_outcome_if_cart_short(
        outcome="call_user", min_final=2, cart_count=3,
    ) == ("call_user", False)


def test_done_with_empty_cart_downgrades():
    assert downgrade_outcome_if_cart_short(
        outcome="done", min_final=1, cart_count=0,
    ) == ("stuck_premature_done", True)


def test_done_with_cart_below_threshold_downgrades():
    assert downgrade_outcome_if_cart_short(
        outcome="done", min_final=2, cart_count=1,
    ) == ("stuck_premature_done", True)


def test_done_with_unknown_cart_downgrades():
    """cart_count=None (probe failed / no cart-state on page) is treated as
    'below threshold' — the agent claimed success but no evidence corroborates."""
    assert downgrade_outcome_if_cart_short(
        outcome="done", min_final=1, cart_count=None,
    ) == ("stuck_premature_done", True)


def test_non_terminal_outcomes_pass_through():
    """Only done/call_user are eligible for downgrade. Other outcomes are
    already failures and shouldn't be touched."""
    for non_terminal in ("stuck_loop", "stuck_premature_done", "parse_error",
                         "max_steps_reached", "model_error", "unhandled_action"):
        assert downgrade_outcome_if_cart_short(
            outcome=non_terminal, min_final=1, cart_count=0,
        ) == (non_terminal, False), f"{non_terminal} should not be downgraded"
