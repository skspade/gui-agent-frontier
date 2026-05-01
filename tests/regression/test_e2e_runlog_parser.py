"""Tests the runs.jsonl pass-rule parser used by E2E runners.

Locks the same precedence as web/build_site._is_pass: 'category' key wins
when present; fallback to 'outcome' for legacy rows.
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts._regression_e2e import _is_pass_runlog_row


def test_pass_with_category():
    assert _is_pass_runlog_row({"outcome": "done", "category": "pass"}) is True


def test_fail_with_category():
    assert _is_pass_runlog_row({"outcome": "abort", "category": "fail_dispatcher"}) is False


def test_legacy_done_no_category():
    assert _is_pass_runlog_row({"outcome": "done"}) is True


def test_legacy_call_user_no_category():
    assert _is_pass_runlog_row({"outcome": "call_user"}) is True


def test_legacy_other_outcome():
    assert _is_pass_runlog_row({"outcome": "stuck_loop"}) is False


def test_category_takes_precedence_over_outcome():
    # If a future row claimed outcome=done but category=premature_done,
    # category wins (and we score fail).
    assert _is_pass_runlog_row({"outcome": "done", "category": "premature_done"}) is False
