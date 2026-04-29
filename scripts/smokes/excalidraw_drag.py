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
