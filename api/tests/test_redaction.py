"""Redaction gate checks. SAM is mocked (no spend); OCR is real (needs `tesseract` with kor)."""

import io
import shutil
from pathlib import Path

import pytest
from PIL import Image

import app.redaction as redaction
from app.redaction.ocr import ocr_lines
from app.redaction.text import find_ids, redact_text
from tests.make_fixture import AMOUNT, FAKE_ARC, FAKE_PASSPORT, FAKE_PHONE, VIRTUAL_ACCOUNT

FIXTURE = Path(__file__).parent / "fixtures" / "nhis_bill_synthetic.png"
needs_tesseract = pytest.mark.skipif(not shutil.which("tesseract"), reason="tesseract not installed")


def test_text_redaction_keeps_what_the_user_needs():
    text = (f"외국인등록번호 {FAKE_ARC} / 990101 5123456\n연락처 {FAKE_PHONE} +82 10 9876 5432\n"
            f"MyKad 900101-14-5678 여권 {FAKE_PASSPORT}\n"
            f"가상계좌 {VIRTUAL_ACCOUNT} 금액 {AMOUNT}원 기한 2026-11-25 고객센터 1577-1000 02-123-4567")
    out, counts = redact_text(text)
    assert counts == {"ARC": 1, "PHONE": 2, "MYKAD": 1, "PASSPORT": 1}
    assert out.count("[ARC_1]") == 2  # same number, OCR spacing differs -> same placeholder
    for kept in (VIRTUAL_ACCOUNT, AMOUNT, "2026-11-25", "1577-1000", "02-123-4567"):
        assert kept in out
    assert not find_ids(out)


@needs_tesseract
async def test_document_redaction(monkeypatch):
    async def no_sam(client, png, concept, request_id):
        return []

    monkeypatch.setattr(redaction, "sam_boxes", no_sam)
    raw = FIXTURE.read_bytes()
    doc = await redaction.redact_document(raw, "test")

    for secret in (FAKE_ARC, FAKE_PHONE, FAKE_PASSPORT):
        assert secret not in doc.text
    assert {"ARC", "PHONE", "PASSPORT"} <= doc.counts.keys()
    assert VIRTUAL_ACCOUNT in doc.text and "2026-11-25" in doc.text

    # pixels where the ARC was printed are now black
    line = next(ln for ln in ocr_lines(raw) if find_ids(ln.text) and "5123456" in ln.text)
    start, end, _ = find_ids(line.text)[0]
    x1, y1, x2, y2 = line.boxes_for(start, end)[0]
    img = Image.open(io.BytesIO(doc.image_png)).convert("L")
    assert img.getpixel(((x1 + x2) // 2, (y1 + y2) // 2)) == 0
