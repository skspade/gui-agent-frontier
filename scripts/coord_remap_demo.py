"""
F-2 demo: ask UI-Venus-1.5-8B to ground an instruction in a screenshot and
print both possible interpretations of the model's coordinate output.

Usage:
    .venv/bin/python scripts/coord_remap_demo.py <screenshot.png> "<instruction>"

Examples:
    # Excalidraw smoke screenshot from the F-1 run
    .venv/bin/python scripts/coord_remap_demo.py /tmp/smoke_final.png \\
        "the rectangle drawn on the canvas"

The script:
  1. Loads the screenshot and reads its pixel dimensions (the model sees
     the PNG bytes verbatim, so image dims are also the "viewport" for
     pre-resize purposes).
  2. POSTs to the local llama.cpp OpenAI-compatible endpoint with the
     UI-Venus grounding prompt + image.
  3. Parses any `[x, y]` from the response.
  4. Prints the raw coord plus both interpretations:
       - **grounding** (0-1000 normalized → image-pixel)
       - **navigation** (resized-image pixel space → image-pixel via inverse
         smart_resize)
  5. Saves an annotated PNG to /tmp/coord_remap_demo.png with both points
     marked so we can eyeball which convention the merged 8B model uses.
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

GROUNDING_PROMPT = (
    "Output the center point of the position corresponding to the following "
    "instruction: \n{instruction}. \n\nThe output should just be the "
    "coordinates of a point, in the format [x,y]. Additionally, if the task "
    "is infeasible (e.g., the task is not related to the image), the output "
    "should be [-1,-1]."
)


def query_model(image_path: Path, instruction: str) -> str:
    img_b64 = base64.b64encode(image_path.read_bytes()).decode()
    body = {
        "model": MODEL,
        "temperature": 0.0,
        "max_tokens": 64,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "image_url",
                     "image_url": {"url": f"data:image/png;base64,{img_b64}"}},
                    {"type": "text",
                     "text": GROUNDING_PROMPT.format(instruction=instruction)},
                ],
            }
        ],
    }
    req = urllib.request.Request(
        SERVER_URL,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=300) as resp:
        return json.loads(resp.read())["choices"][0]["message"]["content"]


_POINT_RE = re.compile(r"\[\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*\]")


def parse_point(text: str) -> tuple[float, float] | None:
    m = _POINT_RE.search(text)
    if not m:
        return None
    return (float(m.group(1)), float(m.group(2)))


def main() -> None:
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(2)

    image_path = Path(sys.argv[1])
    instruction = sys.argv[2]

    img = Image.open(image_path).convert("RGB")
    img_w, img_h = img.size
    print(f"Image: {image_path} ({img_w} x {img_h})")
    print(f"Instruction: {instruction}")
    print()

    raw_response = query_model(image_path, instruction)
    print(f"Raw model response: {raw_response!r}")
    point = parse_point(raw_response)
    if point is None:
        print("Could not parse [x,y] from response.")
        sys.exit(1)
    print(f"Parsed coord: ({point[0]}, {point[1]})")

    if point == (-1, -1):
        print("Model declined (infeasible marker).")
        return

    grounding_xy = grounding_remap(point, (img_w, img_h))
    navigation_xy = navigation_remap(point, (img_w, img_h))
    rh, rw = smart_resize(img_h, img_w)

    print()
    print(f"Grounding interpretation (raw / 1000 * imgsize):")
    print(f"  → image-pixel coord: {grounding_xy}")
    print(f"Navigation interpretation (raw is in resized-image space {rw}x{rh}):")
    print(f"  → image-pixel coord: {navigation_xy}")
    print()

    annotated = img.copy()
    draw = ImageDraw.Draw(annotated)
    r = max(8, img_w // 200)
    # Green = grounding, Red = navigation
    draw.ellipse(
        [grounding_xy[0] - r, grounding_xy[1] - r,
         grounding_xy[0] + r, grounding_xy[1] + r],
        outline="lime", width=max(3, r // 3),
    )
    draw.text((grounding_xy[0] + r + 4, grounding_xy[1] - r), "G", fill="lime")
    draw.ellipse(
        [navigation_xy[0] - r, navigation_xy[1] - r,
         navigation_xy[0] + r, navigation_xy[1] + r],
        outline="red", width=max(3, r // 3),
    )
    draw.text((navigation_xy[0] + r + 4, navigation_xy[1] + r), "N", fill="red")

    out_path = Path("/tmp/coord_remap_demo.png")
    annotated.save(out_path)
    print(f"Annotated image saved: {out_path}  (G=lime grounding, N=red navigation)")


if __name__ == "__main__":
    main()
