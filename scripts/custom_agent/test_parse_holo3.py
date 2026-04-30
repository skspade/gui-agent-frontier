"""Unit test for parse_holo3: maps surfer-h-cli action variants to Action."""
from __future__ import annotations

import sys
import traceback

from scripts.custom_agent.holo3 import parse_holo3


def _check(label: str, parsed: dict, *, want_kind: str, **want_attrs):
    got = parse_holo3(parsed)
    assert got.kind == want_kind, f"{label}: kind {got.kind!r} != {want_kind!r}"
    for attr, expected in want_attrs.items():
        actual = getattr(got, attr)
        assert actual == expected, f"{label}: {attr} {actual!r} != {expected!r}"
    print(f"OK  {label}")


def main() -> int:
    cases = [
        (
            "click_element",
            {
                "thought": "click the login button",
                "notes": "",
                "action": {
                    "action": "click_element",
                    "element": "Login button",
                    "x": 100,
                    "y": 200,
                },
            },
            {"want_kind": "click", "xy": (100, 200), "conclusion": "click the login button"},
        ),
        (
            "write_element",
            {
                "thought": "fill username field",
                "notes": "",
                "action": {
                    "action": "write_element",
                    "content": "standard_user",
                    "element": "Username input",
                    "x": 50,
                    "y": 80,
                },
            },
            {
                "want_kind": "click_then_type",
                "xy": (50, 80),
                "text": "standard_user",
            },
        ),
        (
            "scroll-down",
            {
                "thought": "see more",
                "notes": "",
                "action": {"action": "scroll", "direction": "down"},
            },
            {"want_kind": "scroll", "direction": "down"},
        ),
        (
            "scroll-default-direction-when-missing",
            {
                "thought": "",
                "notes": "",
                "action": {"action": "scroll"},
            },
            {"want_kind": "scroll", "direction": "down"},
        ),
        (
            "go_back",
            {
                "thought": "back",
                "notes": "",
                "action": {"action": "go_back"},
            },
            {"want_kind": "press_back"},
        ),
        (
            "refresh",
            {
                "thought": "rate-limited, refreshing",
                "notes": "",
                "action": {"action": "refresh"},
            },
            {"want_kind": "refresh"},
        ),
        (
            "wait",
            {
                "thought": "page is loading",
                "notes": "",
                "action": {"action": "wait"},
            },
            {"want_kind": "wait"},
        ),
        (
            "restart",
            {
                "thought": "starting over",
                "notes": "",
                "action": {"action": "restart"},
            },
            {"want_kind": "restart"},
        ),
        (
            "answer",
            {
                "thought": "done",
                "notes": "Total was $29.99.",
                "action": {"action": "answer", "content": "$29.99"},
            },
            {"want_kind": "done", "text": "$29.99"},
        ),
    ]

    failures = 0
    for label, parsed, want in cases:
        try:
            _check(label, parsed, **want)
        except AssertionError as e:
            print(f"FAIL {label}: {e}")
            failures += 1

    # Unknown variant should raise.
    try:
        parse_holo3({"thought": "", "notes": "", "action": {"action": "explode"}})
    except ValueError:
        print("OK  unknown-variant-raises")
    else:
        print("FAIL unknown-variant-raises: did not raise")
        failures += 1

    return failures


if __name__ == "__main__":
    try:
        rc = main()
    except Exception:
        traceback.print_exc()
        sys.exit(2)
    sys.exit(0 if rc == 0 else 1)
