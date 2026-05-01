"""Regression lock for F-7: swap_model.sh per-model quant defaults.

Phase 19 baseline failed because swap_quant.sh's script-wide Q6_K default
didn't exist for 30B-A3B class models — the gguf-existence check exited 1
without ever touching systemd. Fix: per-model `QUANT="${2:-…}"` overrides
in swap_model.sh's `case` block. Test pins those defaults so a refactor
that drops them fails loudly.
"""
from __future__ import annotations
import re
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "swap_model.sh"
EXPECTED_DEFAULTS = {
    "ui-venus-1.5-8b":      "Q6_K",      # script-wide default
    "mai-ui-8b":            "Q6_K",      # script-wide default
    "ui-venus-1.5-30b-a3b": "Q3_K_M",
    "bu-30b-a3b-preview":   "Q3_K_M",
    "holo3-35b-a3b":        "IQ3_XXS",
}


def _parse_per_model_overrides(text: str) -> dict[str, str]:
    """Return {model_name: per-model quant default} for cases that override
    QUANT, falling back to the top-level QUANT="${2:-Q6_K}" default for the
    rest."""
    top_default_match = re.search(r'^QUANT="\$\{2:-([A-Z0-9_]+)\}"', text, re.M)
    assert top_default_match, "top-level QUANT default not found in swap_model.sh"
    top_default = top_default_match.group(1)

    out: dict[str, str] = {}
    case_block = re.search(r"case \"\$MODEL\" in\n(.+?)\n\s*esac", text, re.S)
    assert case_block, "case block not found in swap_model.sh"
    for arm in re.finditer(
        r"\n\s*([a-z0-9.\-]+)\)\n(.+?);;",
        "\n" + case_block.group(1),
        re.S,
    ):
        name, body = arm.group(1), arm.group(2)
        if name == "*":
            continue
        per_model = re.search(r'QUANT="\$\{2:-([A-Z0-9_]+)\}"', body)
        out[name] = per_model.group(1) if per_model else top_default
    return out


def test_per_model_quant_defaults_match_expected():
    text = SCRIPT.read_text()
    defaults = _parse_per_model_overrides(text)
    assert defaults == EXPECTED_DEFAULTS, (
        f"swap_model.sh per-model quant defaults drifted.\n"
        f"  expected: {EXPECTED_DEFAULTS}\n"
        f"  got:      {defaults}"
    )
