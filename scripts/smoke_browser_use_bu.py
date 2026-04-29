"""
Smoke runner variant that uses browser-use's native ChatBrowserUse adapter
against bu-30b-a3b-preview served by llama.cpp. Mirrors smoke_browser_use.py
otherwise. See docs/plans/2026-04-29-moe-stack-comparison-design.md (S4).

Run:
    cd /home/seans/Source/vision-model
    .venv/bin/python scripts/smoke_browser_use_bu.py [<smoke_name>]
"""
import asyncio
import importlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from drag_action import register_drag  # noqa: E402

from browser_use import Agent, Browser, ChatBrowserUse, Tools  # noqa: E402

CHROME_PATH = "/home/seans/.cache/ms-playwright/chromium-1208/chrome-linux64/chrome"
SERVER_URL = "http://localhost:8080/v1"
MODEL = os.environ.get("MODEL", "bu-30b-a3b-preview")
DEFAULT_SMOKE = "excalidraw_toolbar"


def load_smoke(name: str):
    return importlib.import_module(f"smokes.{name}")


async def main(smoke_name: str) -> None:
    smoke = load_smoke(smoke_name)
    print(f"===== SMOKE (S4 native): {smoke_name} =====")

    llm = ChatBrowserUse(
        model=MODEL,
        base_url=SERVER_URL,
        api_key="not-needed",
        temperature=0.0,
    )

    browser = Browser(
        is_local=True,
        executable_path=CHROME_PATH,
        headless=getattr(smoke, "HEADLESS", False),
        chromium_sandbox=False,
        args=["--no-sandbox", "--disable-dev-shm-usage"],
        keep_alive=True,
    )

    tools = Tools()
    register_drag(tools)

    agent = Agent(
        task=smoke.TASK,
        llm=llm,
        browser=browser,
        tools=tools,
        use_vision=True,
        max_actions_per_step=getattr(smoke, "MAX_ACTIONS_PER_STEP", 2),
    )

    history = await agent.run(max_steps=getattr(smoke, "MAX_STEPS", 40))
    final = history.final_result() if hasattr(history, "final_result") else None
    print("\n===== FINAL =====")
    print(final or "(no final_result)")

    try:
        cdp = await agent.browser_session.get_or_create_cdp_session()
        res = await cdp.cdp_client.send.Page.captureScreenshot(session_id=cdp.session_id)
        import base64
        import pathlib
        out = pathlib.Path("/tmp/smoke_final.png")
        out.write_bytes(base64.b64decode(res["data"]))
        print(f"Saved verification screenshot to {out}")
    finally:
        await agent.browser_session.kill()


if __name__ == "__main__":
    os.environ.setdefault("ANONYMIZED_TELEMETRY", "false")
    smoke_name = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SMOKE
    asyncio.run(main(smoke_name))
