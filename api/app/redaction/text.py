"""Regex redaction of personal identifiers -> placeholders ([ARC_1], [PHONE_1], ...).

Scope (Keira, Oct 27): the user's own IDs + personal mobile numbers only. Payee bank accounts
(e.g. NHIS 가상계좌), office landlines, amounts and dates stay readable: the explanation needs them.
All patterns run for every locale (a Malaysian in Korea may upload a MyKad).
Separators allow OCR noise: hyphen, en dash, dot or spaces between digit groups.
"""

import re

SEP = r"\s*[-–.]?\s*"
PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    # KR foreign registration no. (7th digit 5-8) and resident no. (1-4); no checksum since Oct 2020
    ("ARC", re.compile(rf"(?<!\d)\d{{6}}{SEP}[5-8]\d{{6}}(?!\d)")),
    ("RRN", re.compile(rf"(?<!\d)\d{{6}}{SEP}[1-4]\d{{6}}(?!\d)")),
    # MY MyKad / i-Kad style YYMMDD-PB-####, hyphenated only (bare 12 digits could be an account)
    ("MYKAD", re.compile(r"(?<!\d)\d{6}\s*[-–]\s*\d{2}\s*[-–]\s*\d{4}(?!\d)")),
    # KR / MY mobiles (landlines like 02-xxx or 1577-xxxx are offices to call -> keep)
    ("PHONE", re.compile(rf"(?<![\d+])(?:\+?82{SEP}1|01)[016789]{SEP}\d{{3,4}}{SEP}\d{{4}}(?!\d)")),
    ("PHONE", re.compile(rf"(?<![\d+])(?:\+?60{SEP}1|01)\d{SEP}\d{{3,4}}{SEP}\d{{4}}(?!\d)")),
    # passports: KR M/S/R/G/D + 8 digits, MY A/H/K + 8 digits, generic 1-2 letters + 7-8 digits
    ("PASSPORT", re.compile(r"(?<![A-Za-z0-9])[A-Z]{1,2}\d{7,8}(?![A-Za-z0-9])")),
]


def find_ids(text: str) -> list[tuple[int, int, str]]:
    """Non-overlapping (start, end, label) spans, earliest pattern wins on overlap."""
    spans: list[tuple[int, int, str]] = []
    for label, pattern in PATTERNS:
        for m in pattern.finditer(text):
            if not any(m.start() < e and s < m.end() for s, e, _ in spans):
                spans.append((m.start(), m.end(), label))
    return sorted(spans)


def redact_text(text: str) -> tuple[str, dict[str, int]]:
    """Replace IDs with numbered placeholders; same value -> same placeholder.

    The value->placeholder mapping is deliberately not returned or stored: KoLife doesn't
    keep ID numbers (consent screen), and the user already sees their original document.
    """
    seen: dict[str, str] = {}
    counts: dict[str, int] = {}
    out, last = [], 0
    for start, end, label in find_ids(text):
        value = re.sub(r"\D", "", text[start:end]) or text[start:end]
        if value not in seen:
            counts[label] = counts.get(label, 0) + 1
            seen[value] = f"[{label}_{counts[label]}]"
        out += [text[last:start], seen[value]]
        last = end
    out.append(text[last:])
    return "".join(out), counts
