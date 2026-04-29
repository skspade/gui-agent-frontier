"""
Excalidraw toolbar identification.

Probes the model's visual grounding on a non-trivial icon row. Forbids the
DOM bypass implicitly by asking the model to enumerate icons "using ONLY
the screenshot." Originally exercised in Phase 2 / Phase 3 (Q4 vs Q6 A/B)
and Phase 5 (Q5_K_M data point).
"""

TASK = (
    "Open https://excalidraw.com and dismiss any welcome dialog by sending "
    "Escape via send_keys (do NOT use evaluate). Then, using ONLY the "
    "screenshot, do all of the following: "
    "(1) describe what is currently drawn on the canvas (or say 'empty' if "
    "nothing is drawn), "
    "(2) list every tool icon you can see in the top toolbar in order from "
    "left to right - include EVERY icon you see, even if you are not sure "
    "what it represents (give your best guess for each), "
    "(3) click the rectangle tool, "
    "(4) confirm visually in the next screenshot that the rectangle tool is "
    "now highlighted as active in the toolbar, "
    "(5) report a final summary listing the toolbar tools and the active "
    "tool. Be thorough about counting toolbar icons - do not stop at 'eraser'."
)
