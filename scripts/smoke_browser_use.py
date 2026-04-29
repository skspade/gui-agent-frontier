"""
Smoke runner: drive browser-use against the local UI-Venus-1.5-8B llama.cpp
server. Each smoke payload lives in `scripts/smokes/<name>.py` so we keep
a permanent history of probes — never edit a payload in place; copy it to
a new file under `smokes/` instead.

Run:
    cd /home/seans/Source/vision-model
    .venv/bin/python scripts/smoke_browser_use.py [<smoke_name>]

If <smoke_name> is omitted, defaults to DEFAULT_SMOKE below.

Each smoke module may define:
    TASK                  (required) — the agent task string
    MAX_STEPS             (default 40)
    HEADLESS              (default False)
    MAX_ACTIONS_PER_STEP  (default 2)
    EXTEND_SYSTEM_MESSAGE (default None)
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
MODEL = os.environ.get("MODEL", "ui-venus-1.5-8b")
DEFAULT_SMOKE = "excalidraw_toolbar"


def load_smoke(name: str):
    return importlib.import_module(f"smokes.{name}")


async def main(smoke_name: str) -> None:
    smoke = load_smoke(smoke_name)
    task = smoke.TASK
    max_steps = getattr(smoke, "MAX_STEPS", 40)
    headless = getattr(smoke, "HEADLESS", False)
    max_actions_per_step = getattr(smoke, "MAX_ACTIONS_PER_STEP", 2)
    extend_system_message = getattr(smoke, "EXTEND_SYSTEM_MESSAGE", None)

    print(f"===== SMOKE: {smoke_name} =====")
    print(f"max_steps={max_steps} headless={headless} "
          f"max_actions_per_step={max_actions_per_step} "
          f"extend_system_message={'yes' if extend_system_message else 'no'}")

    llm = ChatOpenAI(
        model=MODEL,
        base_url=SERVER_URL,
        api_key="not-needed",
        temperature=0.0,
        frequency_penalty=0.0,
        reasoning_effort="none",
        max_completion_tokens=int(os.environ.get("MAX_TOKENS", "2048")),
        add_schema_to_system_prompt=False,
        dont_force_structured_output=False,
    )

    browser = Browser(
        is_local=True,
        executable_path=CHROME_PATH,
        headless=headless,
        chromium_sandbox=False,
        args=["--no-sandbox", "--disable-dev-shm-usage"],
        keep_alive=True,
    )

    tools = Tools()
    register_drag(tools)

    agent_kwargs = dict(
        task=task,
        llm=llm,
        browser=browser,
        tools=tools,
        use_vision=True,
        max_actions_per_step=max_actions_per_step,
    )
    if extend_system_message:
        agent_kwargs["extend_system_message"] = extend_system_message

    agent = Agent(**agent_kwargs)

    history = await agent.run(max_steps=max_steps)
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
    smoke_name = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SMOKE
    asyncio.run(main(smoke_name))
