"""Upload -> redacted preview -> confirm -> gate. SAM mocked; needs tesseract + a Postgres DATABASE_URL.

    cd api && DATABASE_URL=postgresql+asyncpg://localhost/kolife uv run pytest
"""

import io
import os
import shutil
from pathlib import Path

import httpx
import pytest
from PIL import Image

import app.redaction as redaction
from app.main import app
from app.redaction.ocr import ocr_lines
from app.redaction.text import find_ids

FIXTURE = Path(__file__).parent / "fixtures" / "nhis_bill_synthetic.png"
pytestmark = pytest.mark.skipif(
    not shutil.which("tesseract") or "localhost" not in os.environ.get("DATABASE_URL", ""),
    reason="needs tesseract and a local DATABASE_URL")


@pytest.fixture
async def client(monkeypatch):
    async def no_sam(client, jpeg, concept, request_id):
        return []

    monkeypatch.setattr(redaction, "sam_boxes", no_sam)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        yield c


async def test_upload_preview_confirm_gate(client):
    raw = FIXTURE.read_bytes()
    r = await client.post("/api/documents", content=raw, headers={"Content-Type": "image/png"})
    assert r.status_code == 200, r.text
    doc = r.json()
    assert doc["status"] == "pending" and {"ARC", "PHONE", "PASSPORT"} <= doc["counts"].keys()

    with pytest.raises(redaction.NotConfirmed):  # unconfirmed docs never reach a model
        await redaction.require_confirmed(doc["id"])

    img = await client.get(f"/api/documents/{doc['id']}/image")
    assert img.headers["content-type"] == "image/png" and "no-store" in img.headers["cache-control"]
    line = next(ln for ln in ocr_lines(raw) if "5123456" in ln.text)
    x1, y1, x2, y2 = line.boxes_for(*find_ids(line.text)[0][:2])[0]
    assert Image.open(io.BytesIO(img.content)).convert("L").getpixel(((x1 + x2) // 2, (y1 + y2) // 2)) == 0

    assert (await client.post(f"/api/documents/{doc['id']}/confirm")).json()["status"] == "confirmed"
    red = await redaction.require_confirmed(doc["id"])
    assert redaction.audit_meta(doc["id"], red) == {
        "doc_id": doc["id"], "payload_hash": doc["payload_hash"], "redaction_counts": doc["counts"]}

    assert (await client.delete(f"/api/documents/{doc['id']}")).status_code == 204
    with pytest.raises(redaction.NotConfirmed):
        await redaction.require_confirmed(doc["id"])


async def test_rejects_non_images(client):
    r = await client.post("/api/documents", content=b"not an image", headers={"Content-Type": "image/png"})
    assert r.status_code == 415
