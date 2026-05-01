"""Excalidraw: activate the rectangle tool and drag to draw a rectangle."""
TASK = (
    "On excalidraw.com, activate the rectangle tool by typing the key 'r' "
    "(use the type action with text='r'), then call the drag action with "
    "x1=700, y1=400, x2=1100, y2=600 to draw a rectangle on the canvas. "
    "After the drag completes, call done with success=true. If you cannot "
    "complete the task, report what blocked you rather than pretending to "
    "succeed."
)
START_URL = "https://excalidraw.com/"
HEADLESS = False
MAX_STEPS = 25

# Task class (see docs/thesis.md): C — visual-grounding-required (canvas drag)
TASK_CLASS = "C"

# Visual verification: count non-white pixels in the canvas-core region of
# the final screenshot. UV-Venus-1.5-8B genuine passes leave ~370+ non-white
# pixels here (a drawn rectangle); Qwen-72B premature-done runs (which
# emitted two click_at instead of drag) leave 0. Threshold 150 cleanly
# separates "rectangle drawn" from "empty canvas". Region is normalized
# (left, top, right, bottom) as fractions of the screenshot's width/height
# so it works at any viewport size.
VERIFICATION_REGION_FRAC = (0.30, 0.30, 0.70, 0.70)
VERIFICATION_MIN_NON_WHITE = 150
