"""
Excalidraw rectangle-drawing — Phase 22 corrected variant of excalidraw_drag.

Phase 20's Qwen2.5-VL-72B run on excalidraw_drag drew the rectangle but
then sent `Escape` after the drag, which Excalidraw treats as an
unfocus/blur and which (combined with the model's separate keyboard input)
shifted the viewport so the drawn element ended up off-screen. The final
screenshot showed "Scroll back to content" with a blank viewport, masking
the actual success as a perceived failure.

This variant explicitly forbids any keyboard input after the drag and
removes the misleading "capture a screenshot" instruction (the smoke
runner captures the verification screenshot via CDP — the agent does not
need to invoke any screenshot tool).
"""

TASK = (
    "Open https://excalidraw.com and dismiss any welcome dialog by sending "
    "Escape via send_keys (do NOT use evaluate). "
    "Then activate the rectangle tool by sending the key 'r' via send_keys. "
    "Then call the `drag` action with x1=700, y1=400, x2=1100, y2=600 to draw "
    "a rectangle on the canvas. "
    "After the drag completes, IMMEDIATELY call `done` with success=true. "
    "Do NOT send any further keyboard input (no Escape, no other keys), do "
    "NOT scroll, and do NOT call any screenshot tool — the verification "
    "screenshot is captured externally. "
    "If you cannot complete the task, report what blocked you rather than "
    "pretending to succeed."
)

TASK_CLASS = "C"

VERIFICATION_REGION = (300, 100, 1750, 1000)
VERIFICATION_MIN_NON_WHITE = 5000
