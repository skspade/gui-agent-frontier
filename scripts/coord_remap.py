"""
UI-Venus 1.5 coordinate remappers.

UI-Venus emits coordinates in two different conventions depending on which
prompt is used (verified against inclusionAI/UI-Venus repo, commit on main
2026-04-28):

1. Grounding prompt
   ("Output the center point of the position corresponding to ...")
   → emits `[x, y]` in a **0-1000 normalized space**, regardless of input
     image dimensions. Source: `models/grounding/ui_venus1_5_gd.py`
     `_parse_point` divides by 1000 to get [0,1] proportions.

2. Navigation prompt (web/mobile chat-template with <think>/<action>/<conclusion>)
   → emits actions like `Click(box=(x,y))`, `Drag(start=(x1,y1), end=(x2,y2))`
     where coordinates are in the model's **resized image pixel space**
     (post Qwen3-VL smart_resize). Source:
     `models/navigation/ui_venus_navi_agent.py` `_rescale_coordinate`.

The merged 8B model we run supports both prompt formats; pick the remapper
that matches the prompt you used.

Smart-resize parameters for UI-Venus-1.5-8B come from
~/models/ui-venus-1.5-8b/hf/preprocessor_config.json:
  patch_size = 16, merge_size = 2 → factor = 32
  shortest_edge (= min_pixels) = 65536
  longest_edge  (= max_pixels) = 16777216
"""

from __future__ import annotations

import math

# UI-Venus-1.5-8B preprocessor constants (preprocessor_config.json).
PATCH_SIZE = 16
MERGE_SIZE = 2
FACTOR = PATCH_SIZE * MERGE_SIZE  # 32
MIN_PIXELS = 65536
MAX_PIXELS = 16777216


def smart_resize(
    height: int,
    width: int,
    factor: int = FACTOR,
    min_pixels: int = MIN_PIXELS,
    max_pixels: int = MAX_PIXELS,
) -> tuple[int, int]:
    """Replicates Qwen3-VL `smart_resize` policy. Returns (resized_h, resized_w).

    Mirrors transformers.models.qwen2_vl.image_processing_qwen2_vl.smart_resize
    so we don't depend on the transformers package at runtime.
    """
    h_bar = round(height / factor) * factor
    w_bar = round(width / factor) * factor
    if h_bar * w_bar > max_pixels:
        beta = math.sqrt((height * width) / max_pixels)
        h_bar = max(factor, math.floor(height / beta / factor) * factor)
        w_bar = max(factor, math.floor(width / beta / factor) * factor)
    elif h_bar * w_bar < min_pixels:
        beta = math.sqrt(min_pixels / (height * width))
        h_bar = math.ceil(height * beta / factor) * factor
        w_bar = math.ceil(width * beta / factor) * factor
    return h_bar, w_bar


def grounding_remap(
    model_xy: tuple[float, float],
    viewport_size: tuple[int, int],
) -> tuple[int, int]:
    """Map a 0-1000-normalized grounding-head coord to viewport pixel space.

    `viewport_size` is (width, height) in CSS pixels.
    """
    vw, vh = viewport_size
    return (round(model_xy[0] / 1000 * vw), round(model_xy[1] / 1000 * vh))


def navigation_remap(
    model_xy: tuple[float, float],
    viewport_size: tuple[int, int],
    *,
    factor: int = FACTOR,
    min_pixels: int = MIN_PIXELS,
    max_pixels: int = MAX_PIXELS,
) -> tuple[int, int]:
    """Map a navigation-head coord (in resized image pixel space) to viewport pixels.

    `viewport_size` is (width, height) in CSS pixels — also used as the
    pre-resize image size. Mirrors `_rescale_coordinate` in UI-Venus's
    navigation agent.
    """
    vw, vh = viewport_size
    rh, rw = smart_resize(vh, vw, factor=factor, min_pixels=min_pixels, max_pixels=max_pixels)
    return (round(model_xy[0] * vw / rw), round(model_xy[1] * vh / rh))


def _self_test() -> None:
    # Grounding: 0-1000 normalized → viewport pixels.
    # Landscape 1920x1080 — center.
    assert grounding_remap((500, 500), (1920, 1080)) == (960, 540), "grounding landscape center"
    # Portrait 720x1280 — center.
    assert grounding_remap((500, 500), (720, 1280)) == (360, 640), "grounding portrait center"
    # Square 1024x1024 — bottom-right edge.
    assert grounding_remap((999, 999), (1024, 1024)) == (1023, 1023), "grounding square BR"

    # Navigation: resized-image-pixel → viewport pixels.
    # 1920x1080 → smart_resize(h=1080, w=1920, factor=32) = (1088, 1920).
    rh, rw = smart_resize(1080, 1920)
    assert (rh, rw) == (1088, 1920), f"smart_resize 1920x1080 expected (1088,1920) got ({rh},{rw})"
    # Center of resized = (960, 544) → viewport center (960, 540).
    assert navigation_remap((960, 544), (1920, 1080)) == (960, 540), "navigation landscape center"
    # Square viewport stays identity.
    assert navigation_remap((400, 400), (800, 800)) == (400, 400), "navigation square identity"
    # Portrait 720x1280 → smart_resize(h=1280, w=720, factor=32) = (1280, 704).
    rh2, rw2 = smart_resize(1280, 720)
    assert (rh2, rw2) == (1280, 704), f"smart_resize 720x1280 expected (1280,704) got ({rh2},{rw2})"
    # Center of resized = (352, 640) → viewport center (360, 640).
    assert navigation_remap((352, 640), (720, 1280)) == (360, 640), "navigation portrait center"

    print("coord_remap self-test passed")


if __name__ == "__main__":
    _self_test()
