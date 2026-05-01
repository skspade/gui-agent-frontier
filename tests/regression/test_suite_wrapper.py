"""Tests the regression_suite.py wrapper produces a stable JSON document
that the iteration driver can rely on. Tests the shape, not the values."""
from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_suite_wrapper_emits_valid_json_with_expected_keys(tmp_path):
    # --unit-only short-circuits the E2E + mechanical-probe runs so this
    # test is fast. Full mode is exercised end-to-end manually before Phase 4.
    proc = subprocess.run(
        [sys.executable, "-u", str(ROOT / "scripts" / "regression_suite.py"),
         "--unit-only", "--out", str(tmp_path / "suite.json")],
        capture_output=True, text=True,
    )
    assert proc.returncode in (0, 1), f"unexpected exit {proc.returncode}: {proc.stderr}"
    doc = json.loads((tmp_path / "suite.json").read_text())
    assert set(doc.keys()) >= {"all_green", "duration_s", "tests"}
    assert isinstance(doc["all_green"], bool)
    assert isinstance(doc["duration_s"], (int, float))
    expected_unit_keys = {
        "regression_quant_default",
        "regression_coord_remap",
        "regression_scroll_clamp",
        "regression_iframe_skip",
    }
    assert expected_unit_keys.issubset(doc["tests"].keys())
    for k, v in doc["tests"].items():
        assert {"pass", "duration_s", "log_excerpt"}.issubset(v.keys())
        assert isinstance(v["pass"], bool)
