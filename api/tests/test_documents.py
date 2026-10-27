"""Upload -> redacted preview -> confirm -> gate. SAM mocked; needs tesseract + a Postgres DATABASE_URL.

    cd api && DATABASE_URL=postgresql+asyncpg://localhost/kolife uv run pytest
"""

import io
import os
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from cryptography.exceptions import InvalidTag
from PIL import Image
from sqlalchemy import update

import app.redaction as redaction
from app.config import settings
from app.core.crypto import decrypt
from app.db import SessionLocal
from app.main import app
from app.redaction.ocr import ocr_lines
from app.redaction.text import find_ids
from app.tables import Document
from app.worker import purge_documents

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


async def test_heic_upload_and_encrypted_at_rest(client):
    buf = io.BytesIO()
    Image.open(FIXTURE).save(buf, "HEIF")  # iPhone Photos format
    r = await client.post("/api/documents", content=buf.getvalue(), headers={"Content-Type": "image/heic"})
    assert r.status_code == 200, r.text
    doc_id = r.json()["id"]
    async with SessionLocal() as s:
        row = await s.get(Document, doc_id)
    assert not row.image_enc.startswith(b"\x89PNG") and b"[ARC_1]" not in row.text_enc  # ciphertext at rest
    with pytest.raises(InvalidTag):  # blob is bound to its row id
        decrypt(row.image_enc, "some-other-id")
    await client.delete(f"/api/documents/{doc_id}")


async def test_purge_drops_documents_older_than_7_days(client):
    r = await client.post("/api/documents", content=FIXTURE.read_bytes(), headers={"Content-Type": "image/png"})
    doc_id = r.json()["id"]
    async with SessionLocal() as s:
        await s.execute(update(Document).where(Document.id == doc_id)
                        .values(created_at=datetime.now(timezone.utc) - timedelta(days=8)))
        await s.commit()
    assert await purge_documents() >= 1
    assert (await client.get(f"/api/documents/{doc_id}")).status_code == 404


async def test_upload_refused_without_key_before_any_spend(client, monkeypatch):
    monkeypatch.setattr(settings, "master_key", "")
    r = await client.post("/api/documents", content=FIXTURE.read_bytes(), headers={"Content-Type": "image/png"})
    assert r.status_code == 503
