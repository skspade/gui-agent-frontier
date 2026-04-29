"""LLM client + action parser. Filled in Tasks 2-3."""
import re
from dataclasses import dataclass


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
