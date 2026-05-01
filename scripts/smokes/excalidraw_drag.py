"""
Excalidraw rectangle-drawing via the custom `drag` action (F-1 acceptance).

Validates the CDP-mouse-event drag plumbing — keys 'r' to activate the
rectangle tool, then drags from (700,400) to (1100,600) on the canvas.
A real Excalidraw element should appear in /tmp/smoke_final.png with
selection handles. See findings Phase 9.
"""

TASK = (
    "Open https://excalidraw.com and dismiss any welcome dialog by sending "
    "Escape via send_keys (do NOT use evaluate). "
    "Then activate the rectangle tool by sending the key 'r' via send_keys. "
    "Then call the `drag` action with x1=700, y1=400, x2=1100, y2=600 to draw "
    "a rectangle on the canvas. "
    "Capture a screenshot afterwards and report whether a rectangle is "
    "visible on the canvas. If you cannot complete the task, report what "
    "blocked you rather than pretending to succeed."
)

# Task class (see docs/thesis.md): C — visual-grounding-required (canvas drag)
TASK_CLASS = "C"

# Pixel-check verification region (Phase 22): a generous canvas-area crop on
# the 1887x1070 final.png that excludes the toolbar and side panel. A drawn
# Excalidraw rectangle plus chrome leaves ~6500-7000 non-white pixels here;
# a blank or scrolled-away viewport leaves <100. Phase 20 cross-check:
# - Holo3 IQ3_XXS/Q4_K_M/Q6_K final.png: 6491-6999 non-white in this region
# - Qwen-72B Q4_K_M final.png (rectangle drawn but Escape scrolled it away):
#   0 non-white. Threshold 5000 catches the scrolled-away case cleanly.
VERIFICATION_REGION = (300, 100, 1750, 1000)
VERIFICATION_MIN_NON_WHITE = 5000
