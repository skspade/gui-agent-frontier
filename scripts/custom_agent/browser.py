"""Chromium launcher + CDP client wrapper. Filled in Tasks 4-5."""
from __future__ import annotations
import asyncio
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass

import httpx
from cdp_use import CDPClient

CHROME_BIN = "/home/seans/.cache/ms-playwright/chromium-1208/chrome-linux64/chrome"

DISPLAY_ENV = {
    "DISPLAY": ":0",
    "XAUTHORITY": "/run/user/1000/xauth_rVYaGJ",
    "XDG_RUNTIME_DIR": "/run/user/1000",
}


def launch_chromium(*, headless: bool, port: int = 9222) -> tuple[subprocess.Popen, str, str]:
    """Spawn chromium with --remote-debugging-port. Returns (process, ws_url, user_data_dir).

    Caller must terminate the process and rmtree the user_data_dir.
    """
    user_data_dir = tempfile.mkdtemp(prefix="custom_agent_profile_")
    args = [
        CHROME_BIN,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={user_data_dir}",
        "--disable-blink-features=AutomationControlled",
        "--no-first-run",
        "--no-default-browser-check",
        "about:blank",
    ]
    if headless:
        args.insert(1, "--headless=new")

    env = os.environ.copy()
    if not headless:
        env.update(DISPLAY_ENV)

    proc = subprocess.Popen(args, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # Poll /json/version until the debug port is up.
    deadline = time.time() + 15
    ws_url = None
    while time.time() < deadline:
        try:
            r = httpx.get(f"http://127.0.0.1:{port}/json/version", timeout=1.0)
            if r.status_code == 200:
                ws_url = r.json()["webSocketDebuggerUrl"]
                break
        except httpx.RequestError:
            time.sleep(0.2)
    if ws_url is None:
        proc.terminate()
        shutil.rmtree(user_data_dir, ignore_errors=True)
        raise RuntimeError(f"chromium did not open debug port {port}")
    return proc, ws_url, user_data_dir


@dataclass
class Page:
    client: CDPClient
    target_id: str
    session_id: str

    @classmethod
    async def attach(cls, ws_url: str) -> tuple["Page", CDPClient]:
        client = CDPClient(ws_url)
        await client.start()
        targets = await client.send_raw("Target.getTargets", {})
        page_target = next(t for t in targets["targetInfos"] if t["type"] == "page")
        attached = await client.send_raw(
            "Target.attachToTarget",
            {"targetId": page_target["targetId"], "flatten": True},
        )
        sid = attached["sessionId"]
        await client.send_raw("Page.enable", {}, session_id=sid)
        await client.send_raw("Runtime.enable", {}, session_id=sid)
        return cls(client=client, target_id=page_target["targetId"], session_id=sid), client

    async def goto(self, url: str, *, wait_ms: int = 2000) -> None:
        await self.client.send_raw("Page.navigate", {"url": url}, session_id=self.session_id)
        await asyncio.sleep(wait_ms / 1000)

    async def screenshot(self) -> str:
        r = await self.client.send_raw(
            "Page.captureScreenshot", {"format": "png"}, session_id=self.session_id
        )
        return r["data"]

    async def viewport_css(self) -> tuple[int, int]:
        m = await self.client.send_raw(
            "Page.getLayoutMetrics", {}, session_id=self.session_id
        )
        v = m["cssLayoutViewport"]
        return int(v["clientWidth"]), int(v["clientHeight"])
