"""
Smoke test: drive browser-use against the local UI-Venus-1.5-8B llama.cpp server.

Run:
    cd /home/seans/Source/vision-model
    .venv/bin/python scripts/smoke_browser_use.py
"""

import asyncio
import os

from browser_use import Agent, Browser, ChatOpenAI

CHROME_PATH = "/home/seans/.cache/ms-playwright/chromium-1208/chrome-linux64/chrome"
SERVER_URL = "http://localhost:8080/v1"
MODEL = "ui-venus-1.5-8b"
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


async def main() -> None:
    llm = ChatOpenAI(
        model=MODEL,
        base_url=SERVER_URL,
        api_key="not-needed",
        temperature=0.0,
        frequency_penalty=0.0,
        reasoning_effort="none",
        max_completion_tokens=2048,
        add_schema_to_system_prompt=False,
        dont_force_structured_output=False,
    )

    browser = Browser(
        is_local=True,
        executable_path=CHROME_PATH,
        headless=False,
        chromium_sandbox=False,
        args=["--no-sandbox", "--disable-dev-shm-usage"],
        keep_alive=True,
    )

    agent = Agent(
        task=TASK,
        llm=llm,
        browser=browser,
        use_vision=True,
        max_actions_per_step=2,
    )

    history = await agent.run(max_steps=40)
    final = history.final_result() if hasattr(history, "final_result") else None
    print("\n===== FINAL =====")
    print(final or "(no final_result)")

    # Independent ground-truth screenshot for human verification.
    try:
        cdp = await agent.browser_session.get_or_create_cdp_session()
        res = await cdp.cdp_client.send.Page.captureScreenshot(session_id=cdp.session_id)
        import base64, pathlib
        out = pathlib.Path("/tmp/smoke_final.png")
        out.write_bytes(base64.b64decode(res["data"]))
        print(f"Saved verification screenshot to {out}")
    finally:
        await agent.browser_session.kill()


if __name__ == "__main__":
    os.environ.setdefault("ANONYMIZED_TELEMETRY", "false")
    asyncio.run(main())
