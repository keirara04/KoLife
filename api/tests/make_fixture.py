"""Generate the synthetic NHIS-style bill used by test_redaction (all values fake).

Run on macOS (needs AppleSDGothicNeo); the PNG is committed so CI/Docker don't need the font:
    cd api && uv run python tests/make_fixture.py
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).parent / "fixtures" / "nhis_bill_synthetic.png"
FONT = "/System/Library/Fonts/AppleSDGothicNeo.ttc"

# Fake values; the test asserts on these exact strings.
FAKE_ARC = "990101-5123456"
FAKE_PHONE = "010-1234-5678"
FAKE_PASSPORT = "M12345678"
VIRTUAL_ACCOUNT = "123-456-789012"  # payee account, must stay readable
AMOUNT = "123,400"

LINES = [
    ("국민건강보험공단 보험료 납부 안내", 40),
    ("", 20),
    ("성명: 홍길동 (HONG GILDONG)", 30),
    (f"외국인등록번호: {FAKE_ARC}", 30),
    (f"여권번호: {FAKE_PASSPORT}", 30),
    (f"연락처: {FAKE_PHONE}", 30),
    ("", 20),
    ("2026년 10월분 지역보험료", 30),
    (f"납부금액: {AMOUNT}원", 30),
    ("납부기한: 2026-11-25", 30),
    (f"가상계좌: 국민은행 {VIRTUAL_ACCOUNT}", 30),
    ("", 20),
    ("미납 시 연체금이 부과될 수 있습니다.", 26),
]


def main() -> None:
    img = Image.new("RGB", (1200, 900), "white")
    d = ImageDraw.Draw(img)
    y = 50
    for text, size in LINES:
        if text:
            d.text((60, y), text, fill="black", font=ImageFont.truetype(FONT, size))
        y += size + 22
    OUT.parent.mkdir(exist_ok=True)
    img.save(OUT)
    print(OUT)


if __name__ == "__main__":
    main()
