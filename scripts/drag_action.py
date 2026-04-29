"""
Custom `drag` action for browser-use 0.12.

browser-use ships only `click(index)` and coordinate-click; no drag primitive.
This blocks any test that requires actual canvas-coordinate manipulation
(Excalidraw drawing, Figma node move, drag-to-reorder UIs).

The action issues a real CDP `Input.dispatchMouseEvent` sequence
(mousePressed → mouseMoved×N → mouseReleased), so the events are *trusted*
input and reach handlers like Excalidraw's pointer pipeline.

Usage:

    from browser_use import Agent, Tools
    from drag_action import register_drag

    tools = Tools()
    register_drag(tools)
    agent = Agent(task=..., llm=..., browser=..., tools=tools)
"""

from browser_use.browser import BrowserSession
from browser_use.tools.service import Tools


def register_drag(tools: Tools) -> None:
    """Register a `drag(x1,y1,x2,y2)` action on the given Tools instance."""

    @tools.registry.action(
        "Click and drag from (x1,y1) to (x2,y2) on the page in CSS pixel "
        "coordinates relative to the viewport. Uses real CDP mouse input so "
        "canvases (Excalidraw, Figma, etc.) and pointer-event handlers see a "
        "trusted drag. Smooth path with intermediate moves."
    )
    async def drag(x1: int, y1: int, x2: int, y2: int, browser_session: BrowserSession):
        cdp = await browser_session.get_or_create_cdp_session()
        send = cdp.cdp_client.send.Input.dispatchMouseEvent
        sid = cdp.session_id

        await send(
            params={"type": "mousePressed", "x": float(x1), "y": float(y1),
                    "button": "left", "buttons": 1, "clickCount": 1},
            session_id=sid,
        )
        steps = 10
        for i in range(1, steps + 1):
            mx = x1 + (x2 - x1) * i / steps
            my = y1 + (y2 - y1) * i / steps
            await send(
                params={"type": "mouseMoved", "x": float(mx), "y": float(my),
                        "button": "left", "buttons": 1},
                session_id=sid,
            )
        await send(
            params={"type": "mouseReleased", "x": float(x2), "y": float(y2),
                    "button": "left", "buttons": 0, "clickCount": 1},
            session_id=sid,
        )

        from browser_use.agent.views import ActionResult
        memory = f"Dragged from ({x1},{y1}) to ({x2},{y2})"
        return ActionResult(extracted_content=memory, long_term_memory=memory)
