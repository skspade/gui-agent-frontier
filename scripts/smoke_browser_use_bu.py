"""
S4 smoke runner for bu-30b-a3b-preview served by llama.cpp.

Per the bu-30b HF README, the local-serve recipe uses ChatOpenAI (NOT
ChatBrowserUse, which is cloud-only) with bu-specific sampling params:
  - temperature=0.6, top_p=0.95
  - dont_force_structured_output=True (disable grammar; bu-30b emits its
    own JSON natively)
  - model="browser-use/bu-30b-a3b-preview" (pattern; llama.cpp ignores
    the model field when only one model is loaded)

See docs/plans/2026-04-29-moe-stack-comparison-design.md (S4) and the
upstream README at huggingface.co/browser-use/bu-30b-a3b-preview.
"""
import asyncio
import importlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness_patches  # noqa: F401 - side effects (defensive whitespace trim)
from drag_action import register_drag  # noqa: E402

from browser_use import Agent, Browser, ChatOpenAI, Tools  # noqa: E402

CHROME_PATH = "/home/seans/.cache/ms-playwright/chromium-1208/chrome-linux64/chrome"
SERVER_URL = "http://localhost:8080/v1"
MODEL = "browser-use/bu-30b-a3b-preview"
DEFAULT_SMOKE = "excalidraw_toolbar"


def load_smoke(name: str):
    return importlib.import_module(f"smokes.{name}")


async def main(smoke_name: str) -> None:
    smoke = load_smoke(smoke_name)
    print(f"===== SMOKE (S4 bu-30b): {smoke_name} =====")

    llm = ChatOpenAI(
        model=MODEL,
        base_url=SERVER_URL,
        api_key="not-needed",
        temperature=0.6,
        top_p=0.95,
        max_completion_tokens=int(os.environ.get("MAX_TOKENS", "8192")),
        dont_force_structured_output=True,
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
