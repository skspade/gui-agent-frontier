"""Excalidraw: identify the rectangle tool by its glyph and draw a rectangle."""
TASK = (
    "On excalidraw.com, identify the rectangle tool in the top toolbar by its visual "
    "appearance (a rectangle glyph), click it, then draw a rectangle in the middle of "
    "the canvas by clicking and dragging from one point to another. If you cannot "
    "complete the task, report what blocked you rather than pretending to succeed. "
    "Do not use the search/help dialog or the keyboard shortcut — identify the tool visually."
)
START_URL = "https://excalidraw.com/"
HEADLESS = False
MAX_STEPS = 25

# Task class (see docs/thesis.md): C — visual-grounding-required (toolbar enumeration + introspection)
TASK_CLASS = "C"
