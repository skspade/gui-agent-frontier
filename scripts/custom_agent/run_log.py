"""JSONL run logger for harness baseline + ablation runs.

One row per (task, model, run) for offline analysis. Schema is flat-and-cheap;
add fields freely as new probes come online.
"""
from __future__ import annotations
import json
from datetime import datetime
from pathlib import Path

DEFAULT_LOG = Path("/home/seans/Source/vision-model/data/runs.jsonl")


def count_non_white_in_region(
    png_path: Path | str,
    region_frac: tuple[float, float, float, float],
    threshold: int = 245,
) -> int:
    """Count near-non-white pixels in a normalized fractional region of a PNG.

    region_frac = (left, top, right, bottom) as fractions in [0,1] of the
    full image dimensions. A pixel counts when any RGB channel < threshold
    (i.e. "not effectively white"). Used by the runner to upgrade a
    stuck_premature_done verdict to pass when the task supplies a
    canvas-success region and the canvas is non-empty.
    """
    from PIL import Image
    im = Image.open(png_path).convert("RGB")
    w, h = im.size
    l, t, r, b = region_frac
    box = (int(w * l), int(h * t), int(w * r), int(h * b))
    region = im.crop(box)
    return sum(
        1 for px in region.getdata()
        if px[0] < threshold or px[1] < threshold or px[2] < threshold
    )


def append_run(path: Path, row: dict) -> None:
    """Append one JSON object as a single line. Creates parent dirs."""
    path.parent.mkdir(parents=True, exist_ok=True)
    row.setdefault("ts", datetime.now().isoformat(timespec="seconds"))
    with path.open("a") as f:
        f.write(json.dumps(row) + "\n")


_OUTCOME_MAP = {
    "done": "pass",
    "call_user": "pass",
    "stuck_loop": "stuck_loop",
    "stuck_premature_done": "premature_done",
    "parse_error": "parse_error",
    "model_error": "model_error",
    "unhandled_action": "unhandled_action",
    "max_steps_reached": "exhausted",
    "dispatch_hang": "dispatch_hang",
}


def classify_failure(*, outcome: str, steps: int = 0, history_summary: str = "") -> str:
    return _OUTCOME_MAP.get(outcome, f"unknown:{outcome}")


def downgrade_outcome_if_cart_short(
    *,
    outcome: str,
    min_final: int | None,
    cart_count: int | None,
) -> tuple[str, bool]:
    """Decide whether a done/call_user outcome should be downgraded to
    stuck_premature_done because the final cart-state didn't reach the
    task's MIN_FINAL_CART_COUNT threshold.

    Returns (new_outcome, was_downgraded). Inverse of the visual-pixel
    upgrade pattern in the runner: that one promotes premature_done to
    done when the canvas has signal; this one demotes done to
    premature_done when the cart hasn't filled.

    `cart_count is None` (probe failed or no cart-state on the page)
    counts as "below threshold" — the agent claimed success but we have
    no evidence to corroborate it.
    """
    if min_final is None or outcome not in ("done", "call_user"):
        return outcome, False
    if cart_count is None or cart_count < min_final:
        return "stuck_premature_done", True
    return outcome, False
