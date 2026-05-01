from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.iteration_step import strict_improvement, format_suite_delta, render_learnings_block


def _doc(passes: dict[str, bool]) -> dict:
    return {
        "all_green": all(passes.values()),
        "duration_s": 1.0,
        "tests": {k: {"pass": v, "duration_s": 0.1, "log_excerpt": ""} for k, v in passes.items()},
    }


def test_strict_improvement_only_grows_passes():
    before = _doc({"a": False, "b": True})
    after_grew  = _doc({"a": True,  "b": True})
    after_same  = _doc({"a": False, "b": True})
    after_swap  = _doc({"a": True,  "b": False})
    after_lost  = _doc({"a": False, "b": False})
    assert strict_improvement(before, after_grew)  is True
    assert strict_improvement(before, after_same)  is False
    assert strict_improvement(before, after_swap)  is False
    assert strict_improvement(before, after_lost)  is False


def test_strict_improvement_handles_new_test_keys():
    before = _doc({"a": True})
    after  = _doc({"a": True, "b": False})
    # Adding a new failing key is NOT progress.
    assert strict_improvement(before, after) is False


def test_format_suite_delta_renders_per_test_arrows():
    before = _doc({"a": False, "b": True})
    after  = _doc({"a": True, "b": True})
    delta = format_suite_delta(before, after)
    assert "a: fail → pass" in delta
    assert "b: pass → pass" in delta


def test_render_learnings_block_contains_required_sections():
    block = render_learnings_block(
        iteration=3,
        verdict="GREEN",
        hypothesis="bump scroll clamp",
        change_files=["scripts/custom_agent/actions.py"],
        suite_delta_text="ikea_billy: fail → pass",
        outcome_line="committed as abc1234",
        invalidates="iteration 1 hypothesis 'lower clamp' — opposite-direction fix on same lines",
    )
    assert "## Iteration 3" in block
    assert "GREEN" in block
    assert "bump scroll clamp" in block
    assert "scripts/custom_agent/actions.py" in block
    assert "ikea_billy: fail → pass" in block
    assert "abc1234" in block
    assert "iteration 1" in block.lower()


def test_extract_inner_handles_string_envelope():
    """Real claude --print --output-format json puts the model's response
    JSON as a STRING inside `result`."""
    from scripts.iteration_step import _extract_inner
    envelope = {
        "type": "result",
        "result": '{"hypothesis": "fix x", "change_files": ["a.py"]}',
        "session_id": "abc",
    }
    inner = _extract_inner(envelope)
    assert inner == {"hypothesis": "fix x", "change_files": ["a.py"]}


def test_extract_inner_handles_dict_envelope_legacy():
    """Test stubs pass `result` as already-decoded dict; accept this for
    dry-run compatibility."""
    from scripts.iteration_step import _extract_inner
    envelope = {"result": {"hypothesis": "stub", "change_files": []}}
    inner = _extract_inner(envelope)
    assert inner == {"hypothesis": "stub", "change_files": []}


def test_extract_inner_handles_unparseable_string():
    """If the model returned plain text (not JSON), return empty inner so
    the caller falls through to the top-level transcript fields or
    '(not reported)'."""
    from scripts.iteration_step import _extract_inner
    envelope = {"result": "I made a change to actions.py."}
    inner = _extract_inner(envelope)
    assert inner == {}


def test_extract_inner_handles_missing_result():
    from scripts.iteration_step import _extract_inner
    assert _extract_inner({}) == {}
    assert _extract_inner({"type": "result", "session_id": "x"}) == {}
