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
