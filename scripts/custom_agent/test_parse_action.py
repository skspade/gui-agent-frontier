"""Self-test for parse_action. Run directly:
    .venv/bin/python -m scripts.custom_agent.test_parse_action
"""
from scripts.custom_agent.model import parse_action, ParseError

CLICK_SAMPLE = (
    "<think>I see the cart icon.</think>\n"
    "<action>Click(box=(483, 220))</action>\n"
    "<conclusion>Clicked cart.</conclusion>"
)
TYPE_SAMPLE = (
    "<think>type the username.</think>"
    "<action>Type(content='standard_user')</action>"
    "<conclusion>Typed username.</conclusion>"
)
SCROLL_SAMPLE = (
    "<think>need more.</think>"
    "<action>Scroll(start=(500, 500), end=(500, 200), direction='down')</action>"
    "<conclusion>Scrolled down.</conclusion>"
)
DRAG_SAMPLE = (
    "<action>Drag(start=(100, 200), end=(400, 600))</action>"
    "<conclusion>Drew rectangle.</conclusion>"
)
DONE_SAMPLE = (
    "<think>Task complete.</think>"
    "<action>Finished(content='reached cart')</action>"
    "<conclusion>Done.</conclusion>"
)

def test_click():
    a = parse_action(CLICK_SAMPLE)
    assert a.kind == "click", a
    assert a.xy == (483, 220), a
    assert a.conclusion == "Clicked cart.", a

def test_type():
    a = parse_action(TYPE_SAMPLE)
    assert a.kind == "type", a
    assert a.text == "standard_user", a

def test_scroll():
    a = parse_action(SCROLL_SAMPLE)
    assert a.kind == "scroll", a
    assert a.direction == "down", a
    assert a.start_xy == (500, 500), a
    assert a.end_xy == (500, 200), a

def test_drag():
    a = parse_action(DRAG_SAMPLE)
    assert a.kind == "drag", a
    assert a.start_xy == (100, 200), a
    assert a.end_xy == (400, 600), a

def test_done():
    a = parse_action(DONE_SAMPLE)
    assert a.kind == "done", a
    # content is optional but if extracted, fine to expose as `text`
    # (don't over-spec)

def test_unknown_action_kind_is_returned_verbatim():
    raw = "<action>PressBack()</action>"
    a = parse_action(raw)
    assert a.kind == "press_back" or a.kind == "PressBack", a
    # whichever convention you pick, document it inline

def test_missing_action_tag_raises():
    try:
        parse_action("<think>nope</think>")
    except ParseError:
        return
    raise AssertionError("expected ParseError")

def main():
    test_click()
    test_type()
    test_scroll()
    test_drag()
    test_done()
    test_unknown_action_kind_is_returned_verbatim()
    test_missing_action_tag_raises()
    print("ok")

if __name__ == "__main__":
    main()
