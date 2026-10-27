"""SAM 3.1 visual identifier detection + black-box compositing."""

import base64
import io
import re
import time

import httpx
from PIL import Image, ImageDraw

from app.config import settings
from app.core import models as m
from app.core.spend import check_spend_cap, record_call
from app.redaction.ocr import Box

# One concept per SAM call (comma lists return nothing). "ID card" left out on purpose:
# it can match a whole bill and black out the content the user needs explained.
SAM_CONCEPTS = ["face", "QR code", "barcode", "signature", "seal stamp"]
BOX_RE = re.compile(r"<\|box;x1=(\d+);y1=(\d+);x2=(\d+);y2=(\d+)")
PAD = 4


async def sam_boxes(client: httpx.AsyncClient, image_jpeg: bytes, concept: str, request_id: str) -> list[Box]:
    """Boxes for one concept; zero detections (empty output) is a normal result."""
    await check_spend_cap()
    url = "data:image/jpeg;base64," + base64.b64encode(image_jpeg).decode()
    body = {"model": m.SAM, "store": False, "input": [{"type": "message", "role": "user", "content": [
        {"type": "input_text", "text": concept}, {"type": "input_image", "image_url": url}]}]}
    t = time.monotonic()
    r = await client.post(f"{settings.meta_base_url}/responses", json=body,
                          headers={"Authorization": f"Bearer {settings.meta_api_key}"}, timeout=60)
    latency = int((time.monotonic() - t) * 1000)
    if r.status_code != 200:
        await record_call(request_id, m.SAM, "sam", latency, cost_usd=0, status="error",
                          meta={"concept": concept, "http": r.status_code, "error": r.text[:300]})
        r.raise_for_status()
    text = "".join(c.get("text", "") for o in r.json().get("output", []) if o.get("type") == "message"
                   for c in o.get("content", []))
    boxes = [tuple(map(int, g)) for g in BOX_RE.findall(text)]
    await record_call(request_id, m.SAM, "sam", latency, cost_usd=m.SAM_PER_IMAGE,
                      meta={"concept": concept, "detections": len(boxes)})
    return boxes  # type: ignore[return-value]


def black_out(image_png: bytes, boxes: list[Box]) -> bytes:
    """Fill each box (padded) with solid black; boxes are enough, masks are for the walkthrough."""
    img = Image.open(io.BytesIO(image_png)).convert("RGB")
    draw = ImageDraw.Draw(img)
    for x1, y1, x2, y2 in boxes:
        draw.rectangle((max(0, x1 - PAD), max(0, y1 - PAD), x2 + PAD, y2 + PAD), fill="black")
    out = io.BytesIO()
    img.save(out, "PNG")
    return out.getvalue()
