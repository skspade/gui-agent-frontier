"""S-1 Task 1 probe: which coordinate convention does the navigation chat
template emit on the merged UI-Venus-1.5-8B?

Loads /tmp/smoke_final.png (the F-1 Excalidraw screenshot — known rectangle
drawn at viewport (700,400)–(1100,600), image is 4800x2708 due to DPR≈2.5),
sends the upstream UI-Venus navigation prompt, parses the (x, y) out of the
<action>...</action>, and annotates both grounding_remap and navigation_remap
interpretations on the image so we can eyeball which one lands on the
rectangle.

Run:  .venv/bin/python -u scripts/custom_agent_probe_nav.py > /tmp/probe_nav.log 2>&1
"""

from __future__ import annotations

import base64
import json
import re
import sys
import urllib.request
from pathlib import Path

from PIL import Image, ImageDraw

from coord_remap import grounding_remap, navigation_remap, smart_resize

SERVER_URL = "http://localhost:8080/v1/chat/completions"
MODEL = "ui-venus-1.5-8b"

# The upstream nav agent uses "You are a helpful assistant." as the system
# prompt and puts the GUI-Agent task instruction in the *user* message. We
# mirror that exactly. Source: inclusionAI/UI-Venus@main
#   models/navigation/ui_venus_navi_vllm.py::create_message_for_image
#   models/navigation/utils.py::USER_PROMPT
NAV_SYSTEM_PROMPT = "You are a helpful assistant."

NAV_USER_PROMPT = """**You are a GUI Agent.**
Your task is to analyze a given user task, review current screenshot and previous actions, and determine the next action to complete the task.

### User Task
{user_task}

### Previous Actions
{previous_actions}

### Available Actions
You may execute one of the following functions:
Click(box=(x1, y1))
Drag(start=(x1, y1), end=(x2, y2))
Scroll(start=(x1, y1), end=(x2, y2), direction='down/up/right/left')
Type(content='')
Launch(app='')
Wait()
Finished(content='')
CallUser(content='')
LongPress(box=(x1, y1))
PressBack()
PressHome()
PressEnter()
PressRecent()

### Instruction
- Make sure you understand the task goal to avoid wrong actions.
- Make sure you carefully examine the the current screenshot. Sometimes the summarized history might not be reliable, over-claiming some effects.
- For requests that are questions (or chat messages), remember to use the `CallUser` action to reply to user explicitly before finishing! Then, after you have replied, use the Finished action if the goal is achieved.
- Consider exploring the screen by using the `scroll` action with different directions to reveal additional content.
- To copy some text: first select the exact text you want to copy, which usually also brings up the text selection bar, then click the `copy` button in bar.
- To paste text into a text box, first long press the text box, then usually the text selection bar will appear with a `paste` button in it.
- You first thinks about the reasoning process in the mind, then provide the action. The reasoning and action are enclosed in <think></think> and <action></action> tags respectively. After providing action, summarize your action in <conclusion></conclusion> tags
"""

USER_TASK = "Click the rectangle drawn on the canvas."

# F-1 viewport that produced /tmp/smoke_final.png (browser-use default,
# DPR≈2.5 → 4800x2708 image).
VIEWPORT = (1920, 1080)

IMAGE_PATH = Path("/tmp/smoke_final.png")
OUT_PATH = Path("/tmp/custom_agent_probe_nav.png")


def query_model(image_path: Path) -> str:
    img_b64 = base64.b64encode(image_path.read_bytes()).decode()
    user_text = NAV_USER_PROMPT.format(
        user_task=USER_TASK, previous_actions="(no prior actions)"
    )
    body = {
        "model": MODEL,
        "temperature": 0.0,
        "max_tokens": 1024,
        "messages": [
            {"role": "system", "content": NAV_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{img_b64}"},
                    },
                    {"type": "text", "text": user_text},
                ],
            },
        ],
    }
    req = urllib.request.Request(
        SERVER_URL,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=600) as resp:
        return json.loads(resp.read())["choices"][0]["message"]["content"]


# Match Click(box=(x, y)) — also tolerate brackets / spaces / floats just in case.
_CLICK_RE = re.compile(
    r"[Cc]lick\s*\(\s*box\s*=\s*[\(\[]\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*[\)\]]"
)
_ACTION_RE = re.compile(r"<action>(.*?)</action>", re.DOTALL)


def parse_click(text: str) -> tuple[float, float] | None:
    am = _ACTION_RE.search(text)
    body = am.group(1) if am else text
    cm = _CLICK_RE.search(body)
    if not cm:
        return None
    return (float(cm.group(1)), float(cm.group(2)))


def main() -> None:
    img = Image.open(IMAGE_PATH).convert("RGB")
    img_w, img_h = img.size
    print(f"Image: {IMAGE_PATH} ({img_w} x {img_h})")
    print(f"Viewport (CSS): {VIEWPORT}")
    rh, rw = smart_resize(VIEWPORT[1], VIEWPORT[0])
    print(f"smart_resize({VIEWPORT[1]}, {VIEWPORT[0]}) → resized (h, w) = ({rh}, {rw})")
    print(f"User task: {USER_TASK}")
    print()

    raw = query_model(IMAGE_PATH)
    print("=== RAW MODEL RESPONSE ===")
    print(raw)
    print("=== END RAW ===")
    print()

    point = parse_click(raw)
    if point is None:
        print("ERROR: could not parse Click(box=(x,y)) from response.")
        sys.exit(1)
    print(f"Parsed click coord: {point}")

    grounding_xy = grounding_remap(point, VIEWPORT)
    navigation_xy = navigation_remap(point, VIEWPORT)
    print()
    print(f"Grounding interpretation (raw / 1000 * viewport):")
    print(f"  → viewport-pixel coord: {grounding_xy}")
    print(f"Navigation interpretation (raw is in resized {rw}x{rh} space):")
    print(f"  → viewport-pixel coord: {navigation_xy}")
    print()

    # Convert viewport-pixel coords to image-pixel coords for annotation.
    sx = img_w / VIEWPORT[0]
    sy = img_h / VIEWPORT[1]
    grounding_img = (round(grounding_xy[0] * sx), round(grounding_xy[1] * sy))
    navigation_img = (round(navigation_xy[0] * sx), round(navigation_xy[1] * sy))
    print(f"Grounding (image-pixel): {grounding_img}")
    print(f"Navigation (image-pixel): {navigation_img}")
    # Known target rectangle on this image: viewport (700,400)–(1100,600)
    # → image-pixel ~(1750,1000)–(2750,1500), centroid ≈ (2250, 1250).
    print("Known rectangle target image-pixel centroid ≈ (2250, 1250).")
    print()

    annotated = img.copy()
    draw = ImageDraw.Draw(annotated)
    r = max(20, img_w // 120)
    draw.ellipse(
        [
            grounding_img[0] - r,
            grounding_img[1] - r,
            grounding_img[0] + r,
            grounding_img[1] + r,
        ],
        outline="lime",
        width=max(4, r // 3),
    )
    draw.text((grounding_img[0] + r + 6, grounding_img[1] - r), "G", fill="lime")
    draw.ellipse(
        [
            navigation_img[0] - r,
            navigation_img[1] - r,
            navigation_img[0] + r,
            navigation_img[1] + r,
        ],
        outline="red",
        width=max(4, r // 3),
    )
    draw.text((navigation_img[0] + r + 6, navigation_img[1] + r), "N", fill="red")

    annotated.save(OUT_PATH)
    print(f"Annotated image saved: {OUT_PATH}  (G=lime grounding, N=red navigation)")


if __name__ == "__main__":
    main()
