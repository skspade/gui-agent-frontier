# S-1 Custom CDP Client Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a small Python program that drives Chromium directly via CDP, with UI-Venus-1.5-8B as the planner using its native navigation chat template, and prove (or refute) that it can succeed where browser-use fails on the headless saucedemo cart-click and the Excalidraw toolbar canvas tasks.

**Architecture:** Single-process serial loop. Per step: capture screenshot via CDP, POST to llama.cpp `/v1/chat/completions` with the navigation system prompt + history, regex-parse `<action>...</action>` from the response, remap coordinates via `scripts/coord_remap.py`, dispatch `Input.dispatchMouseEvent` / `Input.insertText`, repeat until `done` or `MAX_STEPS`.

**Tech Stack:** Python 3.14, `cdp-use` (already installed in `.venv`), `httpx` for the llama call, `scripts/coord_remap.py` (existing), Chromium binary at `/home/seans/.cache/ms-playwright/chromium-1208/chrome-linux64/chrome`.

**Reference design:** `docs/plans/2026-04-28-s1-custom-cdp-client-design.md`

---

## Operational ground rules (apply to every task)

1. **Privileged ops via `/tmp` script** — never inline-quote sudo. Not expected for any task here, but keep in mind.
2. **Long agent runs → log file**, never pipe through `tail`. Pattern from `CLAUDE.md`:
   ```
   .venv/bin/python -u scripts/custom_agent.py <task> > /tmp/custom_agent.log 2>&1
   ```
3. **Visual claims need an independent screenshot.** The runner already writes `/tmp/custom_agent_steps/NNN.png` after each action and `/tmp/custom_agent_final.png` at the end. Always inspect these before declaring success.
4. **No backwards-compat scaffolding, no premature abstractions.** Per CLAUDE.md global instructions.
5. **Commit after each task.** Frequent small commits.

---

## Task 0: Skeleton + dependency check

**Files to create:**
- `scripts/custom_agent.py` (placeholder with CLI)
- `scripts/custom_agent/__init__.py` (empty)
- `scripts/custom_agent/browser.py` (placeholder)
- `scripts/custom_agent/model.py` (placeholder)
- `scripts/custom_agent/actions.py` (placeholder)
- `scripts/custom_agent_tasks/__init__.py` (empty)

**Step 1: Create the skeleton.** Each file is a stub: a docstring and `pass`. The runner has just enough to argparse a task name and bail early. Goal is to land the directory layout so subsequent commits are scoped.

**Step 2: Verify dependencies are present.**

Run:
```
.venv/bin/python -c "import cdp_use, httpx, PIL, json; print('ok')"
```
Expected: `ok`. If `httpx` is missing, install with `.venv/bin/pip install httpx`. (PIL is only needed for the Phase 0 verification screenshot annotation — likely already there from `scripts/coord_remap_demo.py`.)

**Step 3: Commit.**
```
git add scripts/custom_agent.py scripts/custom_agent/ scripts/custom_agent_tasks/
git commit -m "feat(s1): skeleton for custom CDP agent"
```

---

## Task 1: Retire the empirical risk — which remapper does the navigation chat template need?

**Why this is task 1:** Phase 10 of `docs/findings.md` only verified the **grounding prompt** path (0–1000 normalized coords → `grounding_remap`). The **navigation chat template's** coordinate convention on the merged 8B is unverified. If we build the whole loop assuming `navigation_remap` and the model actually emits 0–1000 normalized in this mode too, every click lands ~5× off and we waste a day debugging.

**Files:**
- Create: `scripts/custom_agent_probe_nav.py` (one-off investigation script)

**Step 1: Read the model card to find the navigation system prompt.**

Read `~/models/ui-venus-1.5-8b/hf/README.md`. Look for the section that describes how to drive the model in the `<think>/<action>/<conclusion>` format — there is typically a system prompt the upstream code uses verbatim (sometimes called "task instruction" or "navigation prompt"). Copy it exactly into a `NAV_SYSTEM_PROMPT` constant in the probe script. If the README doesn't have it, search the cloned repo (`inclusionAI/UI-Venus@main`, `models/navigation/ui_venus_navi_agent.py`) — the design doc references it.

**Step 2: Write the probe.**

`scripts/custom_agent_probe_nav.py`:
- Loads `/tmp/smoke_final.png` (the F-1 Excalidraw screenshot — has a known rectangle drawn at viewport (700,400)–(1100,600), image is 4800×2708 due to DPR≈2.5).
- Sends a chat-completions request to `http://localhost:8080/v1/chat/completions` with:
  - `system`: `NAV_SYSTEM_PROMPT`
  - `user`: text "Click the rectangle drawn on the canvas." + image content
- Prints the raw response.
- Regex-pulls the coordinate from the `<action>` tag (whatever the format is — `click(box=[x,y])`, `click(start_box='[x,y]')`, etc. — figure out by inspecting the response).
- Computes both `grounding_remap(raw_xy, viewport_size)` and `navigation_remap(raw_xy, viewport_size)` using `scripts/coord_remap.py`. Use viewport_size = (1920, 1080) as a placeholder; for the real screenshot the viewport would be that.
- Annotates the screenshot with both points (lime = grounding, red = navigation), saves to `/tmp/custom_agent_probe_nav.png`. Pattern from `scripts/coord_remap_demo.py`.

**Step 3: Run the probe.**

Run:
```
.venv/bin/python -u scripts/custom_agent_probe_nav.py > /tmp/probe_nav.log 2>&1
```
Inspect `/tmp/custom_agent_probe_nav.png` and `/tmp/probe_nav.log`. Decide: which point lands on the rectangle? **That remapper wins for the navigation chat template.**

**Step 4: Update the design doc with the empirical answer.**

Append to `docs/plans/2026-04-28-s1-custom-cdp-client-design.md` under *Empirical risk*: "Verified 2026-04-28: navigation chat template emits {0–1000 normalized | resized-image pixels} on the merged 8B → `{grounding_remap | navigation_remap}` is correct."

**Step 5: Commit.**
```
git add scripts/custom_agent_probe_nav.py docs/plans/2026-04-28-s1-custom-cdp-client-design.md
git commit -m "feat(s1): empirically verify navigation chat template coord convention"
```

---

## Task 2: `model.py` — `parse_action` (TDD)

**Files:**
- Create: `scripts/custom_agent/model.py`
- Test: `scripts/custom_agent/test_parse_action.py` (pytest-style; we run it directly without a framework)

**Step 1: Write the failing tests.**

`scripts/custom_agent/test_parse_action.py`:
```python
"""Self-test for parse_action. Run directly: python scripts/custom_agent/test_parse_action.py"""
from scripts.custom_agent.model import parse_action

# These three samples are placeholders — REPLACE WITH ACTUAL MODEL OUTPUTS
# captured during Task 1's probe run. Edit before running.
CLICK_SAMPLE = "<think>I see the cart icon.</think><action>click(box=[483,220])</action><conclusion>Clicked cart.</conclusion>"
TYPE_SAMPLE = "<think>...</think><action>type(text='standard_user')</action><conclusion>...</conclusion>"
DONE_SAMPLE = "<think>Task complete.</think><action>done()</action><conclusion>Reached cart page.</conclusion>"

def test_click():
    a = parse_action(CLICK_SAMPLE)
    assert a.kind == "click"
    assert a.xy == (483, 220)
    assert a.conclusion == "Clicked cart."

def test_type():
    a = parse_action(TYPE_SAMPLE)
    assert a.kind == "type"
    assert a.text == "standard_user"

def test_done():
    a = parse_action(DONE_SAMPLE)
    assert a.kind == "done"

if __name__ == "__main__":
    test_click(); test_type(); test_done()
    print("ok")
```

**Note:** if Task 1 revealed the action grammar uses different syntax (e.g. `click(start_box='[483,220]')`), update the samples *before* implementing.

**Step 2: Run test, confirm failure.**

Run: `.venv/bin/python scripts/custom_agent/test_parse_action.py`
Expected: `ImportError` or `AttributeError: parse_action` (module is a stub).

**Step 3: Implement `parse_action`.**

`scripts/custom_agent/model.py`:
```python
"""LLM client + action parser for the custom CDP agent."""
from __future__ import annotations
import re
from dataclasses import dataclass

@dataclass
class Action:
    kind: str            # "click" | "type" | "scroll" | "done" | <unknown>
    xy: tuple[int, int] | None = None
    text: str | None = None
    direction: str | None = None
    raw: str = ""
    conclusion: str = ""

_ACTION_RE = re.compile(r"<action>(.*?)</action>", re.DOTALL)
_CONCLUSION_RE = re.compile(r"<conclusion>(.*?)</conclusion>", re.DOTALL)
_CLICK_RE = re.compile(r"click\s*\(\s*box\s*=\s*\[\s*(\d+)\s*,\s*(\d+)\s*\]")
_TYPE_RE = re.compile(r"type\s*\(\s*text\s*=\s*['\"](.*?)['\"]")
_SCROLL_RE = re.compile(r"scroll\s*\(\s*direction\s*=\s*['\"](\w+)['\"]")
_DONE_RE = re.compile(r"done\s*\(")

class ParseError(Exception):
    pass

def parse_action(raw: str) -> Action:
    """Parse the <action>...</action> tag out of a UI-Venus response.

    Replace the per-action regexes if Task 1 revealed a different grammar
    (e.g. `click(start_box='[x,y]')`).
    """
    m = _ACTION_RE.search(raw)
    if not m:
        raise ParseError(f"no <action> tag in response: {raw!r}")
    body = m.group(1).strip()
    conclusion = ""
    cm = _CONCLUSION_RE.search(raw)
    if cm:
        conclusion = cm.group(1).strip()

    if (cm := _CLICK_RE.search(body)):
        return Action(kind="click", xy=(int(cm.group(1)), int(cm.group(2))), raw=body, conclusion=conclusion)
    if (tm := _TYPE_RE.search(body)):
        return Action(kind="type", text=tm.group(1), raw=body, conclusion=conclusion)
    if (sm := _SCROLL_RE.search(body)):
        return Action(kind="scroll", direction=sm.group(1), raw=body, conclusion=conclusion)
    if _DONE_RE.search(body):
        return Action(kind="done", raw=body, conclusion=conclusion)
    return Action(kind=body.split("(", 1)[0].strip(), raw=body, conclusion=conclusion)
```

**Step 4: Run test, confirm pass.**

Run: `.venv/bin/python scripts/custom_agent/test_parse_action.py`
Expected: `ok`

**Step 5: Commit.**
```
git add scripts/custom_agent/model.py scripts/custom_agent/test_parse_action.py
git commit -m "feat(s1): parse_action for UI-Venus navigation responses"
```

---

## Task 3: `model.py` — llama.cpp HTTP client

**Files:**
- Modify: `scripts/custom_agent/model.py`

**Step 1: Add `step()` that POSTs to llama.cpp and returns raw text.**

Append to `scripts/custom_agent/model.py`:
```python
import base64
import httpx

LLAMA_URL = "http://localhost:8080/v1/chat/completions"
NAV_SYSTEM_PROMPT = """<paste exact prompt from Task 1>"""

def step(task: str, history: list[Action], screenshot_b64: str, *, timeout: float = 120.0) -> str:
    """Send one turn to UI-Venus. Returns raw text response.

    history is appended as a compact action log so the model sees what's been done.
    """
    history_text = "\n".join(
        f"step {i+1}: {a.raw}  → {a.conclusion}" for i, a in enumerate(history)
    ) or "(no prior actions)"
    user_text = f"Task: {task}\n\nHistory:\n{history_text}\n\nWhat is the next action?"

    payload = {
        "model": "ui-venus",
        "messages": [
            {"role": "system", "content": NAV_SYSTEM_PROMPT},
            {"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{screenshot_b64}"}},
                {"type": "text", "text": user_text},
            ]},
        ],
        "max_tokens": 512,
        "temperature": 0.0,
    }
    r = httpx.post(LLAMA_URL, json=payload, timeout=timeout)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]
```

**Step 2: Smoke-test `step()` against the running server.**

Inline test (run from project root):
```
.venv/bin/python -c "
from scripts.custom_agent.model import step, parse_action
import base64
with open('/tmp/smoke_final.png', 'rb') as f:
    b64 = base64.b64encode(f.read()).decode()
out = step('Click the rectangle.', [], b64)
print('raw:', out[:500])
print('parsed:', parse_action(out))
"
```
Expected: prints a `<think>/<action>/<conclusion>` response and a parsed `Action(kind='click', xy=(...), ...)`. **If parse fails, fix the regexes in `parse_action` based on the actual format and re-run Task 2's tests.**

**Step 3: Commit.**
```
git add scripts/custom_agent/model.py
git commit -m "feat(s1): llama.cpp HTTP client for UI-Venus"
```

---

## Task 4: `browser.py` — Chromium launcher

**Files:**
- Modify: `scripts/custom_agent/browser.py`

**Step 1: Add `launch_chromium`.**

```python
"""Chromium launcher + CDP client wrapper."""
from __future__ import annotations
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

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
```

**Step 2: Smoke-test the launcher headless.**

Inline test:
```
.venv/bin/python -c "
from scripts.custom_agent.browser import launch_chromium
import shutil
proc, ws, ud = launch_chromium(headless=True)
print('ws:', ws)
proc.terminate(); proc.wait(5); shutil.rmtree(ud, ignore_errors=True)
print('clean exit')
"
```
Expected: prints a `ws://...` URL and `clean exit`.

**Step 3: Commit.**
```
git add scripts/custom_agent/browser.py
git commit -m "feat(s1): chromium launcher with CDP debug port"
```

---

## Task 5: `browser.py` — CDP attach, navigate, screenshot, viewport

**Files:**
- Modify: `scripts/custom_agent/browser.py`

**Step 1: Add a `Page` helper.**

The CDPClient connects to the *browser* websocket; to drive a tab we attach to its target and use the returned `sessionId` for `Page.*` and `Input.*` calls. `cdp-use` exposes typed wrappers via `client.send.<Domain>.<method>(...)` and a `session_id` argument.

Append to `scripts/custom_agent/browser.py`:
```python
import asyncio
import base64
from cdp_use import CDPClient

class Page:
    def __init__(self, client: CDPClient, target_id: str, session_id: str):
        self.client = client
        self.target_id = target_id
        self.session_id = session_id

    @classmethod
    async def attach(cls, ws_url: str) -> tuple["Page", CDPClient]:
        client = CDPClient(ws_url)
        await client.start()
        targets = await client.send.Target.getTargets({}, session_id=None)
        page_target = next(t for t in targets["targetInfos"] if t["type"] == "page")
        attached = await client.send.Target.attachToTarget(
            {"targetId": page_target["targetId"], "flatten": True}, session_id=None
        )
        sid = attached["sessionId"]
        await client.send.Page.enable({}, session_id=sid)
        await client.send.Runtime.enable({}, session_id=sid)
        return cls(client, page_target["targetId"], sid), client

    async def goto(self, url: str, *, wait_ms: int = 2000) -> None:
        await self.client.send.Page.navigate({"url": url}, session_id=self.session_id)
        await asyncio.sleep(wait_ms / 1000)

    async def screenshot(self) -> str:
        r = await self.client.send.Page.captureScreenshot({"format": "png"}, session_id=self.session_id)
        return r["data"]  # base64

    async def viewport_css(self) -> tuple[int, int]:
        m = await self.client.send.Page.getLayoutMetrics({}, session_id=self.session_id)
        v = m["cssLayoutViewport"]
        return int(v["clientWidth"]), int(v["clientHeight"])
```

**Note:** the `cdp-use` typed library is structured as `client.send.<Domain>.<method>` per its `CDPLibrary` class. If the typed wrappers misbehave or have a different signature, fall back to `client.send_raw("Page.captureScreenshot", {"format": "png"}, session_id=sid)`. Verify the call style with a quick `dir(client.send)` exploration.

**Step 2: Smoke-test attach + screenshot + viewport.**

Inline test:
```
.venv/bin/python -c "
import asyncio, shutil
from scripts.custom_agent.browser import launch_chromium, Page

async def main():
    proc, ws, ud = launch_chromium(headless=True)
    try:
        page, client = await Page.attach(ws)
        await page.goto('https://example.com')
        b64 = await page.screenshot()
        vw, vh = await page.viewport_css()
        print(f'screenshot bytes: {len(b64)}, viewport: {vw}x{vh}')
        await client.stop()
    finally:
        proc.terminate(); proc.wait(5); shutil.rmtree(ud, ignore_errors=True)

asyncio.run(main())
"
```
Expected: prints `screenshot bytes: <number>, viewport: <w>x<h>` with non-trivial values.

**Step 3: Commit.**
```
git add scripts/custom_agent/browser.py
git commit -m "feat(s1): CDP attach, navigate, screenshot, viewport"
```

---

## Task 6: `actions.py` — click, type, scroll, done dispatchers

**Files:**
- Modify: `scripts/custom_agent/actions.py`

**Step 1: Implement dispatchers.**

```python
"""Action dispatchers. Add new handlers as the model emits new action kinds."""
from __future__ import annotations
import asyncio
from scripts.custom_agent.browser import Page
from scripts.custom_agent.model import Action
from scripts.coord_remap import navigation_remap, grounding_remap

# Toggled by Task 1's empirical result.
COORD_MODE = "navigation"  # or "grounding"

def remap(raw_xy, viewport):
    return (navigation_remap if COORD_MODE == "navigation" else grounding_remap)(raw_xy, viewport)

async def dispatch(page: Page, action: Action, viewport_css: tuple[int, int]) -> None:
    if action.kind == "click":
        x, y = remap(action.xy, viewport_css)
        await page.client.send_raw(
            "Input.dispatchMouseEvent",
            {"type": "mousePressed", "x": x, "y": y, "button": "left", "clickCount": 1},
            session_id=page.session_id,
        )
        await page.client.send_raw(
            "Input.dispatchMouseEvent",
            {"type": "mouseReleased", "x": x, "y": y, "button": "left", "clickCount": 1},
            session_id=page.session_id,
        )
        await asyncio.sleep(0.5)  # let the page react

    elif action.kind == "type":
        await page.client.send_raw(
            "Input.insertText", {"text": action.text}, session_id=page.session_id,
        )
        await asyncio.sleep(0.2)

    elif action.kind == "scroll":
        dy = 400 if action.direction == "down" else -400
        await page.client.send_raw(
            "Input.dispatchMouseEvent",
            {"type": "mouseWheel", "x": viewport_css[0] // 2, "y": viewport_css[1] // 2,
             "deltaX": 0, "deltaY": dy},
            session_id=page.session_id,
        )
        await asyncio.sleep(0.4)

    elif action.kind == "done":
        return

    else:
        raise NotImplementedError(f"unhandled action kind: {action.kind!r} (raw: {action.raw!r})")
```

**Step 2: No standalone test — exercised end-to-end in Task 8/9.** New action kinds get added here when the model first emits one we don't handle (NotImplementedError makes this loud and immediate).

**Step 3: Commit.**
```
git add scripts/custom_agent/actions.py
git commit -m "feat(s1): click/type/scroll/done action dispatchers"
```

---

## Task 7: `custom_agent.py` — main loop

**Files:**
- Modify: `scripts/custom_agent.py`

**Step 1: Implement the loop and CLI.**

```python
"""Custom CDP agent runner — pairs UI-Venus with Chromium directly."""
from __future__ import annotations
import argparse
import asyncio
import importlib
import shutil
import sys
import time
from pathlib import Path

from scripts.custom_agent.browser import launch_chromium, Page
from scripts.custom_agent.model import step as model_step, parse_action, ParseError, Action
from scripts.custom_agent.actions import dispatch

STEPS_DIR = Path("/tmp/custom_agent_steps")
FINAL_PNG = Path("/tmp/custom_agent_final.png")

async def run(task_module) -> None:
    STEPS_DIR.mkdir(exist_ok=True)
    for f in STEPS_DIR.glob("*.png"):
        f.unlink()

    proc, ws, ud = launch_chromium(headless=task_module.HEADLESS)
    t0 = time.time()
    try:
        page, client = await Page.attach(ws)
        await page.goto(task_module.START_URL)
        viewport = await page.viewport_css()
        history: list[Action] = []
        outcome = "max_steps_reached"

        for step_idx in range(task_module.MAX_STEPS):
            b64 = await page.screenshot()
            try:
                raw = model_step(task_module.TASK, history, b64)
                action = parse_action(raw)
            except (ParseError, Exception) as e:
                print(f"[step {step_idx}] parse/model error: {e}", file=sys.stderr)
                outcome = "parse_error"
                break

            print(f"[step {step_idx}] {action.kind} {action.xy or action.text or action.direction or ''} → {action.conclusion[:80]}")
            history.append(action)

            if action.kind == "done":
                outcome = "done"
                break

            try:
                await dispatch(page, action, viewport)
            except NotImplementedError as e:
                print(f"[step {step_idx}] {e}", file=sys.stderr)
                outcome = "unhandled_action"
                break

            png_path = STEPS_DIR / f"{step_idx:03d}.png"
            png_path.write_bytes(__import__("base64").b64decode(await page.screenshot()))

        # Final screenshot
        FINAL_PNG.write_bytes(__import__("base64").b64decode(await page.screenshot()))
        elapsed = time.time() - t0
        print(f"\n=== outcome: {outcome} | steps: {len(history)} | elapsed: {elapsed:.1f}s ===")
        print(f"final screenshot: {FINAL_PNG}")
        print(f"per-step screenshots: {STEPS_DIR}")

        await client.stop()
    finally:
        proc.terminate(); proc.wait(5); shutil.rmtree(ud, ignore_errors=True)

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("task", help="module name in scripts/custom_agent_tasks/")
    args = parser.parse_args()
    mod = importlib.import_module(f"scripts.custom_agent_tasks.{args.task}")
    asyncio.run(run(mod))

if __name__ == "__main__":
    main()
```

**Step 2: No standalone test** — runs through Task 8 / 9.

**Step 3: Commit.**
```
git add scripts/custom_agent.py
git commit -m "feat(s1): main agent loop with per-step screenshots"
```

---

## Task 8: Saucedemo headless task — payload + run

**Files:**
- Create: `scripts/custom_agent_tasks/saucedemo_headless.py`

**Step 1: Write the task payload.**

```python
"""Saucedemo headless: log in, add an item, navigate to cart."""
TASK = (
    "Log in to saucedemo.com using username 'standard_user' and password 'secret_sauce'. "
    "Once on the inventory page, add the first item to the cart, then click the cart icon "
    "in the top right to navigate to the cart page. If you cannot complete the task, "
    "report what blocked you rather than pretending to succeed."
)
START_URL = "https://www.saucedemo.com/"
HEADLESS = True
MAX_STEPS = 25
```

**Step 2: Run it.**

```
.venv/bin/python -u scripts/custom_agent.py saucedemo_headless > /tmp/custom_agent_saucedemo.log 2>&1
```

Wait for completion (server is local; ~2-5s per step → ~2 min ceiling). Tail the log file in another terminal if you want progress.

**Step 3: Independent verification.**

Open `/tmp/custom_agent_final.png`. Confirm: is this the saucedemo cart page? If yes, success. If not, scan `/tmp/custom_agent_steps/*.png` to find where it diverged.

**Step 4: Record the result locally** — note step count, wall time, outcome, and the failure mode if it failed. We'll fold this into findings.md in Task 10.

**Step 5: Commit.**
```
git add scripts/custom_agent_tasks/saucedemo_headless.py
git commit -m "feat(s1): saucedemo headless task payload"
```

---

## Task 9: Excalidraw toolbar task — payload + run

**Files:**
- Create: `scripts/custom_agent_tasks/excalidraw_toolbar.py`

**Step 1: Write the task payload.**

```python
"""Excalidraw: identify the rectangle tool by its glyph and draw a rectangle."""
TASK = (
    "On excalidraw.com, identify the rectangle tool in the top toolbar by its visual "
    "appearance (a rectangle glyph), click it, then draw a rectangle in the middle of "
    "the canvas by clicking and dragging from one point to another. If you cannot "
    "complete the task, report what blocked you rather than pretending to succeed. "
    "Do not use the search/help dialog or the keyboard shortcut — identify the tool visually."
)
START_URL = "https://excalidraw.com/"
HEADLESS = False
MAX_STEPS = 25
```

**Step 2: Run it.**

Per the operational rule and CLAUDE.md display env, run *headed* (display env vars are already set inside `launch_chromium`):
```
.venv/bin/python -u scripts/custom_agent.py excalidraw_toolbar > /tmp/custom_agent_excalidraw.log 2>&1
```

**Step 3: Verify.**

Open `/tmp/custom_agent_final.png`. Confirm a rectangle appears on the canvas. Inspect intermediate `/tmp/custom_agent_steps/*.png` to see whether the toolbar click landed on the right tool.

**Step 4: Drag handling.** If the model emits a drag-style action (`drag(...)`, `swipe(...)`) that `actions.py` doesn't handle, you'll get `NotImplementedError`. Add the handler — pattern from `scripts/drag_action.py` (Phase 9): two `Input.dispatchMouseEvent` (`mousePressed` at start, `mouseMoved` intermediate, `mouseReleased` at end) with small `asyncio.sleep` between them.

**Step 5: Record the result locally.**

**Step 6: Commit.**
```
git add scripts/custom_agent_tasks/excalidraw_toolbar.py scripts/custom_agent/actions.py
git commit -m "feat(s1): excalidraw toolbar task payload + drag action if needed"
```

---

## Task 10: findings.md Phase 11 + delete S-1 from backlog

**Files:**
- Modify: `docs/findings.md` (append Phase 11)
- Modify: `docs/backlog.md` (delete S-1)

**Step 1: Append Phase 11 to findings.md.**

Template:
```markdown
## 2026-04-28 — Phase 11: Custom CDP client (backlog S-1)

**Goal**: prove (or refute) that driving UI-Venus directly via CDP with its native navigation chat template can succeed where browser-use fails on canvas / nested-anchor pages.

### What was built
`scripts/custom_agent.py` + `scripts/custom_agent/` + `scripts/custom_agent_tasks/`. ~<actual lines> lines, serial loop, no DOM-indexed protocol. Coordinate convention verified empirically: navigation chat template emits {0–1000 normalized | resized-image pixels} on the merged 8B → `{grounding_remap | navigation_remap}` is correct.

### Test 1 — saucedemo headless
- Steps: <N> · Wall time: <T>s · Outcome: <success | failed at step X with Y>
- Browser-use baseline (Phase 2 smoke 2): looped on cart-icon click in headless, never completed.

### Test 2 — Excalidraw toolbar
- Steps: <N> · Wall time: <T>s · Outcome: <success | failed at step X with Y>
- Browser-use baseline (Phase 2 smoke 4 / Phase 9): completed the toolbar identification headed; canvas drawing required custom drag action.

### Comparison
<one paragraph: where did the custom client win, lose, draw? what's the takeaway?>

### Acceptance
- ✅ Working prototype.
- ✅ Side-by-side comparison entry with at least one divergence.
- <observation about whether the hypothesis was confirmed or refuted>
```

**Step 2: Delete S-1 from backlog.**

`git rm`-equivalent via Edit: open `docs/backlog.md`, remove the entire S-1 section (lines 28–79), leaving the rest intact. Per backlog conventions: "Mark this entry in the backlog as done by deleting it … history is in `findings.md`."

**Step 3: Commit.**
```
git add docs/findings.md docs/backlog.md
git commit -m "docs(s1): findings phase 11 + remove S-1 from backlog"
```

---

## Done criteria

- All ten tasks committed.
- `/tmp/custom_agent_final.png` exists for both tasks and shows the expected page state.
- `docs/findings.md` Phase 11 has actual numbers (not placeholders).
- `docs/backlog.md` no longer mentions S-1.
- `git log --oneline` shows ten focused commits.

## What can go sideways and what to do

| Symptom | First check | If it persists |
|---------|-------------|----------------|
| `parse_action` raises `ParseError` on real model output | grammar in regexes is wrong; print raw response, update regexes, re-run Task 2 tests | If grammar is highly variable, switch to a more permissive parser (e.g. extract any `name(...)` pattern and dispatch by name) |
| Model emits 0–1000 coords but plan assumed resized-pixel | `COORD_MODE = "grounding"` in `actions.py` | Re-run Task 1 probe to be sure; document in findings |
| Headless saucedemo click goes nowhere | `/tmp/custom_agent_steps/*.png` to confirm coords landed on cart | Try headed mode; document the headless click path as still broken |
| `Input.insertText` doesn't trigger the page's input handlers | use `Input.dispatchKeyEvent` per character (per CLAUDE.md operational rule 5: prefer real keyboard events) | replace `type` handler with key-event loop |
| `cdp-use` typed wrapper signatures differ from sketch | use `client.send_raw("Domain.method", params, session_id=sid)` directly | Document the actual API shape in a code comment so we don't re-discover next time |
