"""Redaction gate: nothing reaches a text/vision model except a RedactedDoc (AGENTS.md §3)."""

import asyncio
import hashlib
import io
from dataclasses import dataclass

import httpx
from PIL import Image, ImageOps

from app.db import SessionLocal
from app.redaction.image import SAM_CONCEPTS, black_out, sam_boxes
from app.redaction.ocr import ocr_lines
from app.redaction.text import find_ids, redact_text
from app.tables import Document


MAX_SIDE = 2000


class RedactionError(RuntimeError):
    pass


@dataclass(frozen=True)
class RedactedDoc:
    image_png: bytes          # identifiers blacked out
    text: str                 # OCR text with [ARC_1]-style placeholders
    counts: dict[str, int]    # e.g. {"ARC": 1, "PHONE": 1, "face": 1}
    payload_hash: str         # sha256 of what may leave the server (for the audit trail)


async def redact_document(image: bytes, request_id: str) -> RedactedDoc:
    """OCR (local) and SAM (one call per concept) run concurrently on the raw image, then all
    ID boxes are blacked out. Fails closed: any SAM/OCR error raises instead of passing raw data."""
    img = ImageOps.exif_transpose(Image.open(io.BytesIO(image))).convert("RGB")  # upright, EXIF dropped
    img.thumbnail((MAX_SIDE, MAX_SIDE))  # phone photos (~4000 px) make SAM calls 5-10x slower
    buf = io.BytesIO()
    img.save(buf, "PNG")
    png = buf.getvalue()
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=90)  # SAM payload: photos as PNG are MBs of base64 and slow
    jpeg = buf.getvalue()

    async with httpx.AsyncClient() as client:
        lines, *sam_results = await asyncio.gather(
            asyncio.to_thread(ocr_lines, png),
            *(sam_boxes(client, jpeg, c, request_id) for c in SAM_CONCEPTS))

    boxes, counts = [], {}
    for line in lines:
        for start, end, _ in find_ids(line.text):
            boxes += line.boxes_for(start, end)
    for concept, found in zip(SAM_CONCEPTS, sam_results):
        boxes += found
        if found:
            counts[concept] = len(found)

    text, text_counts = redact_text("\n".join(line.text for line in lines))
    counts = {**text_counts, **counts}
    redacted = black_out(png, boxes)
    # second local OCR pass on the output: an ID split across lines or boxed wrong must not leak
    leftover = [label for line in await asyncio.to_thread(ocr_lines, redacted)
                for _, _, label in find_ids(line.text)]
    if leftover:
        raise RedactionError(f"identifiers still readable after redaction: {leftover}")
    digest = hashlib.sha256(redacted + text.encode()).hexdigest()
    return RedactedDoc(redacted, text, counts, digest)


class NotConfirmed(RuntimeError):
    pass


async def require_confirmed(doc_id: str) -> RedactedDoc:
    """The only way a document reaches a model: the user has confirmed its redacted preview."""
    async with SessionLocal() as s:
        doc = await s.get(Document, doc_id)
    if doc is None or doc.status != "confirmed":
        raise NotConfirmed(f"document {doc_id} is not confirmed")
    return RedactedDoc(doc.image_png, doc.text, doc.counts, doc.payload_hash)


def audit_meta(doc_id: str, doc: RedactedDoc) -> dict:
    """Pass as record_call(meta=...) on every model call that consumes the document."""
    return {"doc_id": doc_id, "payload_hash": doc.payload_hash, "redaction_counts": doc.counts}
