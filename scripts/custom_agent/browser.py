"""Chromium launcher + CDP client wrapper. Filled in Tasks 4-5."""
from __future__ import annotations
import os
import shutil
import subprocess
import tempfile
import time

import httpx

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
