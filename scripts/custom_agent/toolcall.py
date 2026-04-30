"""Hermes-style tool-call path: MAI-UI-8B and bu-30b-a3b-preview.

Phase 14 follow-up bake-off found these two models (and Holo2-30B-A3B,
which is handled separately on the holo1_5 surfer-h-cli path) emit
`<tool_call>{...}</tool_call>` blocks instead of UI-Venus's `<action>`
tag whenever they need to commit a click. They share Qwen3-family
chat templates whose `--jinja` rendering injects tool definitions and
extracts `tool_calls` from the response automatically.

We pass our action set as OpenAI-style `tools=[...]` and consume
`message.tool_calls` — no manual `<tool_call>` regex parsing needed
when the server is started with `--jinja`.

Coord-space contract is **0-1000 normalized**, the Qwen3-VL family default.
Verified by `scripts/model_probe.py` on 2026-04-30: MAI-UI-8B emits coords
in [0, 1000] x [0, 1000] regardless of the prompt's stated unit. We emit
`click` (not `click_at`) so the dispatcher's `grounding_remap` rescales
into viewport CSS pixels — same path UI-Venus uses.
"""
from __future__ import annotations

import json
import os

from scripts.custom_agent.holo3 import LLAMA_URL, _post
from scripts.custom_agent.holo3 import _navigator_image_url
from scripts.custom_agent.model import Action

MODEL_NAME = os.environ.get("MODEL", "mai-ui-8b")
TEMPERATURE = float(os.environ.get("TOOLCALL_TEMPERATURE", "0.0"))


SYSTEM_PROMPT = """You are a GUI agent driving a web browser to complete a user task.
Each turn you receive a screenshot of the browser viewport. Examine the
screenshot, then call exactly one tool from the provided set.
Coordinates are normalized to [0, 1000] x [0, 1000] over the viewport
(top-left origin). Emit tools, not free text — your textual output is
ignored except inside tool arguments.
"""

USER_TEMPLATE = """### User Task
{task}

### Previous Actions
{previous_actions}

### Current screenshot

Examine the screenshot and call exactly one tool to make progress on the
task. If the previous action had no visible effect, pick a different
target — do NOT call the `done` tool just because progress stalled.
"""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "click",
            "description": "Click once at a point in the viewport. Use for buttons, links, form fields you intend to type into next, dropdowns, and anchor regions.",
            "parameters": {
                "type": "object",
                "properties": {
                    "x": {"type": "integer", "description": "x coordinate, 0-1000 normalized over viewport width"},
                    "y": {"type": "integer", "description": "y coordinate, 0-1000 normalized over viewport height"},
                    "purpose": {"type": "string", "description": "short text description of the element being clicked"},
                },
                "required": ["x", "y"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "type",
            "description": "Type text into the currently focused element. Call `click` first to focus the target field.",
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "text to type"},
                },
                "required": ["content"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "scroll",
            "description": "Scroll the viewport in a direction.",
            "parameters": {
                "type": "object",
                "properties": {
                    "direction": {"type": "string", "enum": ["up", "down", "left", "right"]},
                },
                "required": ["direction"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "press_enter",
            "description": "Press the Enter key.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "wait",
            "description": "Wait for the page to settle (e.g. after a navigation).",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "done",
            "description": "Call only when the task is fully complete and verified in the current screenshot.",
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {"type": "string"},
                },
                "additionalProperties": False,
            },
        },
    },
]


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


def _parse_tool_call(call: dict) -> Action:
    """Map an OpenAI-style tool_call dict to our Action."""
    fn = call.get("function") or {}
    name = fn.get("name") or ""
    args_raw = fn.get("arguments") or "{}"
    try:
        args = json.loads(args_raw) if isinstance(args_raw, str) else args_raw
    except json.JSONDecodeError as e:
        raise ValueError(f"toolcall: arguments not valid JSON: {args_raw!r}") from e

    raw = json.dumps({"name": name, "arguments": args}, separators=(",", ":"))
    purpose = args.get("purpose") or args.get("element") or ""

    if name == "click":
        if "x" not in args or "y" not in args:
            raise ValueError(f"toolcall click missing x/y: {args!r}")
        return Action(kind="click", xy=(int(args["x"]), int(args["y"])), raw=raw, conclusion=purpose)
    if name == "type":
        return Action(kind="type", text=args.get("content", ""), raw=raw, conclusion=purpose)
    if name == "scroll":
        return Action(kind="scroll", direction=args.get("direction", "down"), raw=raw, conclusion=purpose)
    if name == "press_enter":
        return Action(kind="press_enter", raw=raw, conclusion=purpose)
    if name == "wait":
        return Action(kind="wait", raw=raw, conclusion=purpose)
    if name == "done":
        return Action(kind="done", text=args.get("summary", ""), raw=raw, conclusion=purpose)
    raise ValueError(f"unknown toolcall function: {name!r}")


def navigate_step_toolcall(
    task: str,
    history: list[Action],
    screenshot_b64: str,
    viewport: tuple[int, int],
    *,
    timeout: float = 120.0,
) -> Action:
    """One agent turn for a Hermes-tool-call model.

    The viewport arg is unused at the model layer (coords are already
    viewport CSS pixels) but kept in the signature so the run loop can
    swap harnesses without branching on `viewport`.
    """
    del viewport  # API-uniform, unused on this path

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
        "tools": TOOLS,
        "tool_choice": "required",
        "temperature": TEMPERATURE,
        "chat_template_kwargs": {"enable_thinking": False},
        "max_tokens": 1024,
    }
    data = _post(payload, timeout=timeout)
    msg = data["choices"][0]["message"]
    tool_calls = msg.get("tool_calls") or []
    if not tool_calls:
        raise ValueError(
            f"toolcall: no tool_calls in response. content={msg.get('content')!r}"
        )
    return _parse_tool_call(tool_calls[0])
