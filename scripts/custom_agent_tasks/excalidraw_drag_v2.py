"""Excalidraw rectangle drag — v2 forbids any keyboard input after the drag.

Phase 20's Qwen2.5-VL-72B run on excalidraw_drag drew the rectangle but
then sent further keys, which scrolled the viewport so the drawn element
ended up off-screen. This variant explicitly forbids any post-drag input.
"""
TASK = (
    "On excalidraw.com, activate the rectangle tool by typing the key 'r' "
    "(use the type action with text='r'), then call the drag action with "
    "x1=700, y1=400, x2=1100, y2=600 to draw a rectangle on the canvas. "
    "Immediately after the drag completes, call done with success=true. "
    "Do NOT type any further characters or press any keys after the drag, "
    "and do NOT scroll — the verification screenshot is captured externally. "
    "If you cannot complete the task, report what blocked you rather than "
    "pretending to succeed."
)
START_URL = "https://excalidraw.com/"
HEADLESS = False
MAX_STEPS = 25

# Task class (see docs/thesis.md): C — visual-grounding-required (canvas drag)
TASK_CLASS = "C"
