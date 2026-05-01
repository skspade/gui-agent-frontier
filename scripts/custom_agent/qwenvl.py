"""Qwen2.5-VL native-action path: parses computer-use JSON from `content`.

Phase 21 (2026-04-30). Built after observing that Qwen2.5-VL-72B-Instruct
ignores OpenAI `tools=[...]` and `tool_choice="required"` and emits its
trained computer-use format directly in the assistant message body, e.g.

    {"action": "click", "coordinate": [548, 186]}
    {"action": "left_click", "coordinate": [402, 84]}
    click{"action": "left_click", "coordinate": [1045, 560]}   <- stray prefix

The fine-tuning overrides the chat template's tool-call emission. So we
abandon `tools` and parse the message body directly.

Coord space: **viewport pixels**, not 0-1000 normalized. The Qwen-VL
computer-use fine-tune emits absolute coordinates over the rendered image,
so no rescale is needed when the screenshot is sent at native viewport
dims (DPR=1 makes screenshot pixels == viewport CSS pixels).
"""
from __future__ import annotations

import json
import os
import re

from scripts.custom_agent.holo3 import LLAMA_URL, _post, _navigator_image_url
from scripts.custom_agent.model import Action

MODEL_NAME = os.environ.get("MODEL", "qwen2.5-vl-72b-instruct")
TEMPERATURE = float(os.environ.get("QWENVL_TEMPERATURE", "0.0"))


SYSTEM_PROMPT = """You are a GUI agent driving a web browser to complete a user task.
Each turn you receive a screenshot of the browser viewport. Examine it,
then output exactly one action as a JSON object with shape:

  {"action": <verb>, "coordinate": [x, y]}            // for click-likes
  {"action": "type", "text": <string>}                 // typing
  {"action": "scroll", "direction": "up|down|left|right"}
  {"action": "key", "text": "Return"}                  // key press
  {"action": "wait"}                                   // page settle
  {"action": "terminate", "status": "success|failure"} // done

Verbs for click-likes: click, left_click, double_click, right_click.
Coordinates are absolute pixel offsets from the top-left of the viewport.
Output ONLY the JSON object. No prose, no markdown fences, no comments.
"""

USER_TEMPLATE = """### Task
{task}

### Previous actions
{previous_actions}

### Current screenshot

Look at the screenshot and emit exactly one action JSON object. If the
previous action had no visible effect, pick a different target — do NOT
emit a `terminate` just because progress stalled.
"""


def _render_history(history: list[Action]) -> str:
    if not history:
        return "(none)"
    lines = []
    for i, a in enumerate(history):
        suffix = ""
        if a.conclusion:
            suffix = f" -> {a.conclusion}"
        if a.no_effect:
            suffix += " [no page change]"
        lines.append(f"step {i+1}: {a.raw}{suffix}")
    return "\n".join(lines)


# Match either a clean JSON object at the start, or one with a stray
# prefix like "click" before the brace (observed in the wild on ikea_billy).
_JSON_RE = re.compile(r"\{[\s\S]*\}")


def _extract_json(content: str) -> dict:
    """Pull the action JSON out of an assistant message body."""
    m = _JSON_RE.search(content)
    if not m:
        raise ValueError(f"qwenvl: no JSON object in content: {content!r}")
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError as e:
        raise ValueError(f"qwenvl: JSON parse failed: {content!r}") from e


_CLICK_VERBS = {"click", "left_click", "double_click", "right_click", "mouse_click"}


def _parse_qwenvl(parsed: dict, raw: str) -> Action:
    verb = parsed.get("action") or ""
    coord = parsed.get("coordinate") or parsed.get("coord") or None
    text = parsed.get("text") or parsed.get("content") or ""
    direction = parsed.get("direction", "down")
    purpose = parsed.get("purpose") or parsed.get("element") or ""

    if verb in _CLICK_VERBS:
        if not (isinstance(coord, list) and len(coord) == 2):
            raise ValueError(f"qwenvl: click missing coordinate: {parsed!r}")
        # Qwen-VL emits viewport-pixel coords (verified Phase 21). Use
        # `click_at` so the dispatcher bypasses its 0-1000 grounding_remap;
        # `click` would rescale (550 -> 678) and miss every target.
        return Action(kind="click_at", xy=(int(coord[0]), int(coord[1])), raw=raw, conclusion=purpose)
    if verb == "type":
        return Action(kind="type", text=text, raw=raw, conclusion=purpose)
    if verb == "key":
        # Translate common key names to our key actions.
        key_text = text.strip().lower()
        if key_text in {"return", "enter"}:
            return Action(kind="press_enter", raw=raw, conclusion=purpose)
        # Anything else falls back to a wait so we don't crash; future
        # work could add a generic press_key kind.
        return Action(kind="wait", raw=raw, conclusion=f"unhandled key: {text}")
    if verb == "scroll":
        return Action(kind="scroll", direction=direction, raw=raw, conclusion=purpose)
    if verb == "wait":
        return Action(kind="wait", raw=raw, conclusion=purpose)
    if verb in {"terminate", "done", "answer"}:
        status = parsed.get("status", "")
        return Action(kind="done", text=f"{status}: {text}".strip(": "), raw=raw, conclusion=purpose)
    raise ValueError(f"qwenvl: unknown action verb {verb!r} in {parsed!r}")


def navigate_step_qwenvl(
    task: str,
    history: list[Action],
    screenshot_b64: str,
    viewport: tuple[int, int],
    *,
    timeout: float = 120.0,
) -> Action:
    """One agent turn for Qwen2.5-VL-style native computer-use emit.

    `viewport` is unused at the model layer (coords are already pixel-space)
    but kept for API uniformity with the toolcall path.
    """
    del viewport

    user_text = USER_TEMPLATE.format(
        task=task,
        previous_actions=_render_history(history),
    )

    payload = {
        "model": MODEL_NAME,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    _navigator_image_url(screenshot_b64),
                    {"type": "text", "text": user_text},
                ],
            },
        ],
        "temperature": TEMPERATURE,
        "max_tokens": 512,
    }
    data = _post(payload, timeout=timeout)
    content = data["choices"][0]["message"]["content"] or ""
    parsed = _extract_json(content)
    return _parse_qwenvl(parsed, content)
