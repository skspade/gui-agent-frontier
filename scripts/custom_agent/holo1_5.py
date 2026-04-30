"""Surfer-h-cli holo1_5 path: Holo1.5-7B and Holo2-30B-A3B.

Same navigator + two-pass localize shape as holo3.py, with the canonical
surfer-h-cli localizer contract: the model receives the smart_resize'd
image and emits coords in **absolute pixels of that resized image**, which
the orchestrator rescales to viewport CSS pixels.

Phase 15 finding #1 documented that Holo3 IGNORES this contract and emits
0-1000 normalized coords instead. We treat the canonical contract as the
default for the surfer-h-cli family because surfer-h-cli was built around
Holo1.5; Holo3 was the deviation. `scripts/model_calibrate.py` should be
run against any new model added to this path to verify empirically.

Schemas, prompts, image encoding, and history rendering are imported from
`holo3.py` so the navigator side is byte-identical.
"""
from __future__ import annotations

import json
import os

from scripts.custom_agent.holo3 import (
    AbsWebAgentNavigate,
    ClickAbsoluteAction,
    NAVIGATION_TEMPERATURE,
    NavigationState,
    NAV_GUIDELINES,
    LOCALIZATION_TEMPERATURE,
    create_localization_prompt,
    parse_holo3,
    render_history,
    smart_resize,
    _decode_png_b64,
    _encode_jpeg_b64,
    _navigator_image_url,
    _post,
)
from scripts.custom_agent.model import Action

MODEL_NAME = os.environ.get("MODEL", "holo1.5-7b")


def _localizer_resized_image_url(png_b64: str) -> tuple[dict, tuple[int, int]]:
    """Encode the screenshot as JPEG at smart_resize'd dims for the localizer.

    Returns (image_url_message, (resized_w, resized_h)). The resized dims
    are returned because the localizer's coords are absolute pixels in
    that resized image; the orchestrator needs them to rescale to viewport.
    """
    img = _decode_png_b64(png_b64)
    h2, w2 = smart_resize(img.height, img.width)
    resized = img.resize((w2, h2))
    jpeg_b64 = _encode_jpeg_b64(resized)
    return (
        {
            "type": "image_url",
            "image_url": {"detail": "auto", "url": f"data:image/jpeg;base64,{jpeg_b64}"},
        },
        (w2, h2),
    )


def step_holo1_5_navigate(
    task: str,
    history_text: str,
    screenshots_b64: list[str],
    notes: str,
    *,
    timeout: float = 120.0,
) -> dict:
    """Same navigator turn as holo3 — the surfer-h-cli prompt is identical."""
    system_payload = {
        "guidelines": NAV_GUIDELINES,
        "state_format": NavigationState.model_json_schema(),
        "answer_format": AbsWebAgentNavigate.model_json_schema(),
    }
    user_text = json.dumps(
        {"task": task, "previous_actions": history_text, "step": "", "notes": notes},
        separators=(",", ":"),
    )
    user_content: list[dict] = [{"type": "text", "text": user_text}]
    user_content.extend(_navigator_image_url(b64) for b64 in screenshots_b64)

    payload = {
        "model": MODEL_NAME,
        "messages": [
            {"role": "system", "content": json.dumps(system_payload)},
            {"role": "user", "content": user_content},
        ],
        "temperature": NAVIGATION_TEMPERATURE,
        "response_format": AbsWebAgentNavigate.get_json_schema(),
        "chat_template_kwargs": {"enable_thinking": False},
        "max_tokens": 1024,
    }
    data = _post(payload, timeout=timeout)
    return json.loads(data["choices"][0]["message"]["content"])


def step_holo1_5_localize(
    screenshot_b64: str,
    element_description: str,
    viewport: tuple[int, int],
    *,
    timeout: float = 60.0,
) -> tuple[int, int]:
    """One localization turn. Returns (x, y) in viewport CSS pixels.

    Surfer-h-cli contract: model sees smart_resize'd image, emits absolute
    pixels in that resized space. We rescale by viewport / resized_dims.
    """
    image_url, (rw, rh) = _localizer_resized_image_url(screenshot_b64)
    payload = {
        "model": MODEL_NAME,
        "messages": [
            {
                "role": "user",
                "content": [
                    image_url,
                    {"type": "text", "text": create_localization_prompt(element_description)},
                ],
            }
        ],
        "temperature": LOCALIZATION_TEMPERATURE,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "click_absolute_action",
                "schema": ClickAbsoluteAction.model_json_schema(),
                "strict": True,
            },
        },
        "chat_template_kwargs": {"enable_thinking": False},
        "max_tokens": 256,
    }
    data = _post(payload, timeout=timeout)
    content = data["choices"][0]["message"]["content"]
    parsed = ClickAbsoluteAction.model_validate_json(content)

    vw, vh = viewport
    x = max(0, min(int(parsed.x * vw / rw), vw - 1))
    y = max(0, min(int(parsed.y * vh / rh), vh - 1))
    return x, y


def navigate_step_holo1_5(
    task: str,
    history: list[Action],
    screenshots_b64: list[str],
    notes: str,
    viewport: tuple[int, int],
) -> tuple[Action, str]:
    """One agent turn for the holo1_5 family.

    Returns (action, new_notes). Caller carries new_notes forward.
    """
    history_text = render_history(history)
    parsed = step_holo1_5_navigate(task, history_text, screenshots_b64, notes)
    inner = parsed["action"]
    if inner["action"] in ("click_element", "write_element"):
        if not screenshots_b64:
            raise RuntimeError(
                "holo1_5 navigator emitted localized action but no screenshot is available"
            )
        x, y = step_holo1_5_localize(screenshots_b64[-1], inner["element"], viewport)
        inner["x"] = x
        inner["y"] = y
    return parse_holo3(parsed), parsed.get("notes", "") or ""
