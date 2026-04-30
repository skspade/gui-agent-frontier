"""Holo3 native-harness path: surfer-h-cli-style two-pass navigate+localize.

Phase 15 (2026-04-29). Schemas and prompts ported verbatim from
hcompai/surfer-h-cli's src/surfer_h_cli/skills/{navigation_step,
navigation_models, localization_1_5}.py and src/surfer_h_cli/utils.py.

The only edit to upstream prompt text is dropping the
`Never try to login, enter email or password...` guideline, which would
block saucedemo CP1.
"""
from __future__ import annotations

import base64
import io
import json
import math
import os
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

import httpx
from PIL import Image
from pydantic import BaseModel, ConfigDict, Field

from scripts.custom_agent.model import Action

LLAMA_URL = "http://localhost:8080/v1/chat/completions"
MODEL_NAME = os.environ.get("MODEL", "holo3-35b-a3b")

NAVIGATION_TEMPERATURE = 0.7
LOCALIZATION_TEMPERATURE = 0.0
NAVIGATION_SCREENSHOTS = 3

IMAGE_JPEG_QUALITY = 90

# Holo3 localizer coord contract (verified by scripts/holo3_calibrate.py
# against 4 targets on saucedemo login on 2026-04-29):
#
# Holo3-35B-A3B IQ3_XXS emits coordinates in [0, 1000] x [0, 1000]
# NORMALIZED space, not in absolute pixels of the sent image as the schema's
# docstring suggests. Same convention as UI-Venus. Surfer-h-cli's Holo1.5
# contract (resize to 1000x500, treat coords as absolute pixels in that
# resized image) does NOT apply to Holo3 — verified empirically: it produced
# y-values 2x too large because the model normalizes Y to 1000, not 500.
#
# Therefore: send the screenshot at native dims (no resize, since DPR=1
# already makes screenshot pixels == viewport CSS pixels), and rescale the
# returned (x, y) by viewport / 1000.
LOCALIZATION_NORMALIZED_RANGE = 1000


# ---------------------------------------------------------------------------
# Schemas (verbatim from surfer-h-cli skills/navigation_models.py and
# skills/localization_1_5.py). The model is constrained to emit JSON matching
# these via OpenAI-compatible strict response_format — drift here changes
# what Holo3 is allowed to produce.
# ---------------------------------------------------------------------------

class _StructuredOutput(BaseModel):
    """Mirror of surfer-h-cli's StructuredOutput config."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_serialization_defaults_required=True,
        json_schema_mode_override="serialization",
        use_attribute_docstrings=True,
        revalidate_instances="always",
        validate_assignment=True,
        validate_default=True,
    )

    @classmethod
    def get_json_schema(cls) -> dict:
        return {
            "type": "json_schema",
            "json_schema": {
                "name": _snake_case(cls.__name__),
                "schema": cls.model_json_schema(),
                "description": cls.__doc__ or "",
                "strict": True,
            },
        }


def _snake_case(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


class _BaseAction(_StructuredOutput):
    """Base action."""

    action: str


class AbsClickElementAction(_BaseAction):
    """Click at coordinates of a web element identified by its description."""

    action: Literal["click_element"] = "click_element"
    element: str
    """text description of the element"""
    x: int
    """The x coordinate, number of pixels from the left edge."""
    y: int
    """The y coordinate, number of pixels from the top edge."""


class AbsWriteElementAction(_BaseAction):
    """Write content at coordinates of a web element identified by its description. Don't Enter at the end."""

    action: Literal["write_element"] = "write_element"
    content: str
    """Content to write"""
    element: str
    """Text description of the element and the text it contains"""
    x: int
    """The x coordinate, number of pixels from the left edge."""
    y: int
    """The y coordinate, number of pixels from the top edge."""


class ScrollAction(_BaseAction):
    """Scroll in a specified direction."""

    action: Literal["scroll"] = "scroll"
    direction: Literal["up", "down", "left", "right"] = "down"
    """The direction to scroll in"""


class GoBackAction(_BaseAction):
    """Go back to the previous screen."""

    action: Literal["go_back"] = "go_back"


class RefreshAction(_BaseAction):
    """Refresh the current page."""

    action: Literal["refresh"] = "refresh"


class WaitAction(_BaseAction):
    """Wait for screen changes or page load."""

    action: Literal["wait"] = "wait"


class RestartAction(_BaseAction):
    """Restart the task from the beginning."""

    action: Literal["restart"] = "restart"


class AnswerAction(_BaseAction):
    """Return a final answer to the task. This is the last action to call in an episode."""

    action: Literal["answer"] = "answer"
    content: str
    """The answer content"""


WebAgentNavigateAction = (
    AbsClickElementAction
    | AbsWriteElementAction
    | ScrollAction
    | GoBackAction
    | RefreshAction
    | WaitAction
    | RestartAction
    | AnswerAction
)


class AbsWebAgentNavigate(_StructuredOutput):
    """Output of the Web navigation agent."""

    thought: str = ""
    """Brief thoughts, summarizing the reasoning steps that will help answer the task."""
    notes: str = ""
    """Information extracted (i.e. captionned) from the screenshots relevant to the task"""
    action: WebAgentNavigateAction
    """The action to perform"""


class NavigationState(BaseModel):
    """State the navigator sees in the system message's state_format slot."""

    task: str = Field(description="The task to solve")
    previous_actions: str = Field(description="The previous actions taken by the agent")
    step: str = Field(
        description="The current step the agent is trying to achieve to solve the task",
        default="",
    )
    notes: str = Field(description="The previous notes taken by the agent", default="")
    force_answer: bool = False
    screenshots: list[str] = Field(description="The last N screenshots.")


class ClickAbsoluteAction(BaseModel):
    """Click at absolute coordinates."""

    action: Literal["click_absolute"] = "click_absolute"
    x: int = Field(description="The x coordinate, number of pixels from the left edge.")
    y: int = Field(description="The y coordinate, number of pixels from the top edge.")


# ---------------------------------------------------------------------------
# Prompts (verbatim from surfer-h-cli skills/navigation_step.py
# NAVIGATION_PROMPT and skills/localization_1_5.py create_localization_prompt,
# minus the "Never try to login..." guideline). The "the the" typo and the
# odd "last  screenshots" double-space are upstream — preserved so the
# system prompt stays byte-identical to the canonical text.
# ---------------------------------------------------------------------------

NAV_GUIDELINES = f"""Imagine you are a robot browsing the web, just like humans. Now you need to complete a task.
In each iteration, you will receive an Observation that includes the last  screenshots of a web browser and the current memory of the agent.
You have also information about the step that the agent is trying to achieve to solve the task.
Carefully analyze the visual information to identify what to do, then follow the guidelines to choose the following action.
You should detail your thought (i.e. reasoning steps) before taking the action.
Also detail in the notes field of the action the extracted information relevant to solve the task.
Once you have enough information in the notes to answer the task, return an answer action with the detailed answer in the notes field.
This will be evaluated by an evaluator and should match all the criteria or requirements of the task.

Guidelines:
- store in the notes all the relevant information to solve the task that fulfill the task criteria. Be precise
- Use both the task and the step information to decide what to do
- if you want to write in a text field and the text field already has text, designate the text field by the text it contains and its type
- If there is a cookies notice, always accept all the cookies first
- The observation is the screenshot of the current page and the memory of the agent.
- If you see relevant information on the screenshot to answer the task, add it to the notes field of the action.
- If there is no relevant information on the screenshot to answer the task, add an empty string to the notes field of the action.
- If you see buttons that allow to navigate directly to relevant information, like jump to ... or go to ... , use them to navigate faster.
- In the answer action, give as many details a possible relevant to answering the task.
- if you want to write, don't click before. Directly use the write action
- to write, identify the web element which is type and the text it already contains
- If you want to use a search bar, directly write text in the search bar
- Don't scroll too much. Don't scroll if the number of scrolls is greater than 3
- Don't scroll if you are at the end of the webpage
- Only refresh if you identify a rate limit problem
- If you are looking for a single flights, click on round-trip to select 'one way'
- If you are facing a captcha on a website, try to solve it.

- if you have enough information in the screenshot and in the notes to answer the task, return an answer action with the detailed answer in the notes field
- The current date is {datetime.today().strftime("%A, %B %-d, %Y")}."""


def create_localization_prompt(component: str) -> str:
    return f"""Localize an element on the GUI image according to the provided target and output a click position.
 * You must output a valid JSON following the format: {ClickAbsoluteAction.model_json_schema()}
 Your target is:

{component}"""


# ---------------------------------------------------------------------------
# Image helpers
# ---------------------------------------------------------------------------

def smart_resize(
    height: int,
    width: int,
    factor: int = 28,
    min_pixels: int = 56 * 56,
    max_pixels: int = 14 * 14 * 4 * 1280,
) -> tuple[int, int]:
    """Verbatim port of surfer-h-cli/utils.py smart_resize. Returns (h_bar, w_bar)."""
    if height < factor or width < factor:
        raise ValueError(f"height:{height} or width:{width} must be larger than factor:{factor}")
    if max(height, width) / min(height, width) > 200:
        raise ValueError(
            f"absolute aspect ratio must be smaller than 200, got {max(height, width) / min(height, width)}"
        )
    h_bar = round(height / factor) * factor
    w_bar = round(width / factor) * factor
    if h_bar * w_bar > max_pixels:
        beta = math.sqrt((height * width) / max_pixels)
        h_bar = math.floor(height / beta / factor) * factor
        w_bar = math.floor(width / beta / factor) * factor
    elif h_bar * w_bar < min_pixels:
        beta = math.sqrt(min_pixels / (height * width))
        h_bar = math.ceil(height * beta / factor) * factor
        w_bar = math.ceil(width * beta / factor) * factor
    return h_bar, w_bar


def _decode_png_b64(png_b64: str) -> Image.Image:
    return Image.open(io.BytesIO(base64.b64decode(png_b64)))


def _encode_jpeg_b64(image: Image.Image, quality: int = IMAGE_JPEG_QUALITY) -> str:
    buf = io.BytesIO()
    image.convert("RGB").save(buf, format="JPEG", quality=quality)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _navigator_image_url(png_b64: str) -> dict:
    img = _decode_png_b64(png_b64)
    h2, w2 = smart_resize(img.height, img.width)
    resized = img.resize((w2, h2), resample=Image.Resampling.LANCZOS)
    jpeg_b64 = _encode_jpeg_b64(resized)
    return {
        "type": "image_url",
        "image_url": {"detail": "auto", "url": f"data:image/jpeg;base64,{jpeg_b64}"},
    }


def _localizer_image_url(png_b64: str) -> dict:
    """Encode the screenshot as JPEG at native dims for the localizer."""
    img = _decode_png_b64(png_b64)
    jpeg_b64 = _encode_jpeg_b64(img)
    return {
        "type": "image_url",
        "image_url": {"detail": "auto", "url": f"data:image/jpeg;base64,{jpeg_b64}"},
    }


# ---------------------------------------------------------------------------
# HTTP step functions
# ---------------------------------------------------------------------------

def _post(payload: dict, *, timeout: float) -> dict:
    r = httpx.post(LLAMA_URL, json=payload, timeout=timeout)
    r.raise_for_status()
    return r.json()


def step_holo3_navigate(
    task: str,
    history_text: str,
    screenshots_b64: list[str],
    notes: str,
    *,
    timeout: float = 120.0,
) -> dict:
    """One navigation turn. Returns the parsed AbsWebAgentNavigate dict."""
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


def step_holo3_localize(
    screenshot_b64: str,
    element_description: str,
    viewport: tuple[int, int],
    *,
    timeout: float = 60.0,
) -> tuple[int, int]:
    """One localization turn. Returns (x, y) in viewport CSS pixels."""
    image_url = _localizer_image_url(screenshot_b64)
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
    x = max(0, min(int(parsed.x * vw / LOCALIZATION_NORMALIZED_RANGE), vw - 1))
    y = max(0, min(int(parsed.y * vh / LOCALIZATION_NORMALIZED_RANGE), vh - 1))
    return x, y


# ---------------------------------------------------------------------------
# Action mapping
# ---------------------------------------------------------------------------

def parse_holo3(parsed: dict) -> Action:
    """Pure mapper: an already-parsed AbsWebAgentNavigate dict -> our Action.

    Coordinates inside `click_element` / `write_element` are expected to
    already be in viewport pixels (the orchestrator runs the localizer and
    overwrites x/y before calling this).
    """
    inner = parsed["action"]
    kind = inner["action"]
    raw = json.dumps(inner, separators=(",", ":"))
    conclusion = parsed.get("thought", "") or ""

    if kind == "click_element":
        return Action(kind="click", xy=(inner["x"], inner["y"]), raw=raw, conclusion=conclusion)
    if kind == "write_element":
        return Action(
            kind="click_then_type",
            xy=(inner["x"], inner["y"]),
            text=inner.get("content", ""),
            raw=raw,
            conclusion=conclusion,
        )
    if kind == "scroll":
        return Action(
            kind="scroll",
            direction=inner.get("direction", "down"),
            raw=raw,
            conclusion=conclusion,
        )
    if kind == "go_back":
        return Action(kind="press_back", raw=raw, conclusion=conclusion)
    if kind == "refresh":
        return Action(kind="refresh", raw=raw, conclusion=conclusion)
    if kind == "wait":
        return Action(kind="wait", raw=raw, conclusion=conclusion)
    if kind == "restart":
        return Action(kind="restart", raw=raw, conclusion=conclusion)
    if kind == "answer":
        return Action(
            kind="done",
            text=inner.get("content", ""),
            raw=raw,
            conclusion=conclusion,
        )
    raise ValueError(f"unknown holo3 action kind: {kind!r}")


def render_history(history: list[Action]) -> str:
    """Render history as the surfer-h-cli `previous_actions` string field."""
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


def navigate_step_holo3(
    task: str,
    history: list[Action],
    screenshots_b64: list[str],
    notes: str,
    viewport: tuple[int, int],
) -> tuple[Action, str]:
    """One agent turn: navigator → optional localizer → mapped Action.

    `viewport` is required because the localizer rescales coords from Holo3's
    normalized [0, 1000] output space into viewport CSS pixels.

    Returns (action, new_notes). Caller carries new_notes forward into the
    next call so the model accumulates extracted info across turns.
    """
    history_text = render_history(history)
    parsed = step_holo3_navigate(task, history_text, screenshots_b64, notes)
    inner = parsed["action"]
    if inner["action"] in ("click_element", "write_element"):
        if not screenshots_b64:
            raise RuntimeError(
                "holo3 navigator emitted localized action but no screenshot is available"
            )
        x, y = step_holo3_localize(screenshots_b64[-1], inner["element"], viewport)
        inner["x"] = x
        inner["y"] = y
    return parse_holo3(parsed), parsed.get("notes", "") or ""
