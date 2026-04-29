"""LLM client + action parser. Filled in Tasks 2-3."""
import re
from dataclasses import dataclass

import httpx


@dataclass
class Action:
    kind: str
    xy: tuple[int, int] | None = None
    start_xy: tuple[int, int] | None = None
    end_xy: tuple[int, int] | None = None
    text: str | None = None
    direction: str | None = None
    raw: str = ""
    conclusion: str = ""


class ParseError(Exception):
    pass


_ACTION_RE = re.compile(r"<action>\s*(.*?)\s*</action>", re.DOTALL)
_CONCLUSION_RE = re.compile(r"<conclusion>\s*(.*?)\s*</conclusion>", re.DOTALL)
_VERB_RE = re.compile(r"\s*([A-Za-z]+)\s*\((.*)\)\s*", re.DOTALL)
_XY_RE = lambda key: re.compile(rf"{key}\s*=\s*\(\s*(\d+)\s*,\s*(\d+)\s*\)")
_STR_RE = lambda key: re.compile(rf"{key}\s*=\s*['\"]([^'\"]*?)['\"]")

# Upstream verbs -> normalized kinds. Anything missing falls through to
# snake_case (PressBack -> press_back).
_KIND_MAP = {"Finished": "done"}


def parse_action(raw: str) -> Action:
    """Parse a UI-Venus navigation response.

    Maps the upstream grammar to lowercase normalized kinds:
      Click -> "click", Type -> "type", Scroll -> "scroll", Drag -> "drag",
      Finished -> "done". Other verbs (Wait, LongPress, PressBack, ...) are
      returned with kind = snake_case form so the agent loop can dispatch
      or NotImplementedError-out as needed.
    """
    m = _ACTION_RE.search(raw)
    if not m:
        raise ParseError("missing <action> tag")
    body = m.group(1)

    vm = _VERB_RE.fullmatch(body)
    if not vm:
        raise ParseError(f"could not parse action body: {body!r}")
    verb, args = vm.group(1), vm.group(2)

    kind = _KIND_MAP.get(verb) or re.sub(r"(?<!^)(?=[A-Z])", "_", verb).lower()
    action = Action(kind=kind, raw=body)

    cm = _CONCLUSION_RE.search(raw)
    if cm:
        action.conclusion = cm.group(1).strip()

    for attr, key in (("xy", "box"), ("start_xy", "start"), ("end_xy", "end")):
        if pm := _XY_RE(key).search(args):
            setattr(action, attr, (int(pm.group(1)), int(pm.group(2))))

    if sm := _STR_RE("content").search(args):
        action.text = sm.group(1)
    elif sm := _STR_RE("app").search(args):
        action.text = sm.group(1)
    if dm := _STR_RE("direction").search(args):
        action.direction = dm.group(1)

    return action


LLAMA_URL = "http://localhost:8080/v1/chat/completions"
MODEL_NAME = "ui-venus-1.5-8b"

# Lifted verbatim from scripts/custom_agent_probe_nav.py (commit 6332f1c).
# Source: inclusionAI/UI-Venus@main
#   models/navigation/ui_venus_navi_vllm.py::create_message_for_image
#   models/navigation/utils.py::USER_PROMPT
NAV_SYSTEM_PROMPT = "You are a helpful assistant."

NAV_USER_PROMPT = """**You are a GUI Agent.**
Your task is to analyze a given user task, review current screenshot and previous actions, and determine the next action to complete the task.

### User Task
{user_task}

### Previous Actions
{previous_actions}

### Available Actions
You may execute one of the following functions:
Click(box=(x1, y1))
Drag(start=(x1, y1), end=(x2, y2))
Scroll(start=(x1, y1), end=(x2, y2), direction='down/up/right/left')
Type(content='')
Launch(app='')
Wait()
Finished(content='')
CallUser(content='')
LongPress(box=(x1, y1))
PressBack()
PressHome()
PressEnter()
PressRecent()

### Instruction
- Make sure you understand the task goal to avoid wrong actions.
- Make sure you carefully examine the the current screenshot. Sometimes the summarized history might not be reliable, over-claiming some effects.
- For requests that are questions (or chat messages), remember to use the `CallUser` action to reply to user explicitly before finishing! Then, after you have replied, use the Finished action if the goal is achieved.
- Consider exploring the screen by using the `scroll` action with different directions to reveal additional content.
- To copy some text: first select the exact text you want to copy, which usually also brings up the text selection bar, then click the `copy` button in bar.
- To paste text into a text box, first long press the text box, then usually the text selection bar will appear with a `paste` button in it.
- You first thinks about the reasoning process in the mind, then provide the action. The reasoning and action are enclosed in <think></think> and <action></action> tags respectively. After providing action, summarize your action in <conclusion></conclusion> tags
"""


# Grounding prompt (Phase 10 / scripts/coord_remap_demo.py).
GROUNDING_PROMPT = (
    "Output the center point of the position corresponding to the following "
    "instruction: \n{instruction}. \n\nThe output should just be the "
    "coordinates of a point, in the format [x,y]. Additionally, if the task "
    "is infeasible (e.g., the task is not related to the image), the output "
    "should be [-1,-1]."
)
_POINT_RE = re.compile(r"\[\s*(-?\d+)\s*,\s*(-?\d+)\s*\]")


def step_grounding(
    instruction: str, screenshot_b64: str, *, timeout: float = 60.0
) -> tuple[int, int] | None:
    """One-shot grounding lookup: returns (x, y) in 0-1000 normalized space.

    Returns None on parse failure or the model's infeasible marker [-1, -1].
    Caller must remap to viewport pixels via grounding_remap.
    """
    payload = {
        "model": MODEL_NAME,
        "messages": [
            {"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{screenshot_b64}"}},
                {"type": "text", "text": GROUNDING_PROMPT.format(instruction=instruction)},
            ]},
        ],
        "max_tokens": 64,
        "temperature": 0.0,
    }
    r = httpx.post(LLAMA_URL, json=payload, timeout=timeout)
    r.raise_for_status()
    raw = r.json()["choices"][0]["message"]["content"]
    m = _POINT_RE.search(raw)
    if not m:
        return None
    x, y = int(m.group(1)), int(m.group(2))
    if (x, y) == (-1, -1):
        return None
    return (x, y)


def step(task: str, history: list[Action], screenshot_b64: str, *, timeout: float = 120.0) -> str:
    """Send one turn to UI-Venus. Returns raw text response.

    history is rendered as a compact "previous actions" summary so the model
    sees what it's done.
    """
    if history:
        prev = "\n".join(
            f"step {i+1}: {a.raw}" + (f" -> {a.conclusion}" if a.conclusion else "")
            for i, a in enumerate(history)
        )
    else:
        prev = "(none)"

    user_text = NAV_USER_PROMPT.format(user_task=task, previous_actions=prev)

    payload = {
        "model": MODEL_NAME,
        "messages": [
            {"role": "system", "content": NAV_SYSTEM_PROMPT},
            {"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{screenshot_b64}"}},
                {"type": "text", "text": user_text},
            ]},
        ],
        "max_tokens": 512,
        "temperature": 0.0,
    }
    r = httpx.post(LLAMA_URL, json=payload, timeout=timeout)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]
