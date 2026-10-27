import io
import uuid
from typing import Literal

import httpx
from fastapi import APIRouter, HTTPException, Request, Response
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel

from app.core.crypto import decrypt, encrypt, key_configured
from app.core.spend import SpendCapExceeded
from app.db import SessionLocal
from app.redaction import RedactionError, redact_document
from app.tables import Document

router = APIRouter()
MAX_BYTES = 20 * 1024 * 1024
# No auth yet: the uuid4 hex id is the capability token for its document.


class DocumentOut(BaseModel):
    id: str
    status: Literal["pending", "confirmed"]
    counts: dict[str, int]
    payload_hash: str


def out(doc: Document) -> DocumentOut:
    return DocumentOut(id=doc.id, status=doc.status, counts=doc.counts, payload_hash=doc.payload_hash)


async def get_doc(doc_id: str) -> Document:
    async with SessionLocal() as s:
        doc = await s.get(Document, doc_id)
    if doc is None:
        raise HTTPException(404, "document not found")
    return doc


@router.post("/documents", response_model=DocumentOut)
async def upload(request: Request) -> DocumentOut:
    """Raw image bytes as the body (no multipart). Redacts in-request (~8 s), stores only the
    redacted result, returns counts for the preview. The raw image is never persisted."""
    # ponytail: redaction runs in the request; move to the ARQ worker if uploads queue up
    if not key_configured():  # check before any SAM spend
        raise HTTPException(503, "Uploads are not configured on this server yet.")
    if int(request.headers.get("content-length") or 0) > MAX_BYTES:
        raise HTTPException(413, "image too large (max 20 MB)")
    raw = await request.body()
    if not raw or len(raw) > MAX_BYTES:
        raise HTTPException(413 if raw else 400, "image too large (max 20 MB)" if raw else "empty body")
    try:
        Image.open(io.BytesIO(raw)).verify()
    except (UnidentifiedImageError, OSError):
        raise HTTPException(415, "not an image (JPEG, PNG or WebP)")

    doc_id = uuid.uuid4().hex
    try:
        red = await redact_document(raw, doc_id)
    except RedactionError:
        raise HTTPException(422, "Couldn't redact this safely. Please retake the photo, flat and well lit.")
    except SpendCapExceeded:
        raise HTTPException(503, "Daily AI budget reached. Please try again tomorrow.")
    except httpx.HTTPError:  # SAM 429/5xx/timeout; retries come with the Oct 29 model-call wrapper
        raise HTTPException(502, "AI service is busy, please try again in a moment.")
    doc = Document(id=doc_id, image_enc=encrypt(red.image_png, doc_id), text_enc=encrypt(red.text.encode(), doc_id),
                   counts=red.counts,
                   payload_hash=red.payload_hash, status="pending")
    async with SessionLocal() as s:
        s.add(doc)
        await s.commit()
    return out(doc)


@router.get("/documents/{doc_id}", response_model=DocumentOut)
async def get(doc_id: str) -> DocumentOut:
    return out(await get_doc(doc_id))


@router.get("/documents/{doc_id}/image")
async def image(doc_id: str) -> Response:
    doc = await get_doc(doc_id)
    return Response(decrypt(doc.image_enc, doc.id), media_type="image/png", headers={"Cache-Control": "private, no-store"})


@router.post("/documents/{doc_id}/confirm", response_model=DocumentOut)
async def confirm(doc_id: str) -> DocumentOut:
    async with SessionLocal() as s:
        doc = await s.get(Document, doc_id)
        if doc is None:
            raise HTTPException(404, "document not found")
        doc.status = "confirmed"
        await s.commit()
        return out(doc)


@router.delete("/documents/{doc_id}", status_code=204)
async def delete(doc_id: str) -> None:
    """Retake: drop the redacted copy too."""
    async with SessionLocal() as s:
        doc = await s.get(Document, doc_id)
        if doc is not None:
            await s.delete(doc)
            await s.commit()
