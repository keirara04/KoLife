"""Local OCR (Tesseract kor+eng) so printed IDs are found before any model sees the document."""

import csv
import io
import subprocess
from dataclasses import dataclass, field

Box = tuple[int, int, int, int]  # x1, y1, x2, y2


@dataclass
class Line:
    text: str = ""
    words: list[tuple[int, int, Box]] = field(default_factory=list)  # (start, end, box) into text

    def boxes_for(self, start: int, end: int) -> list[Box]:
        return [b for s, e, b in self.words if s < end and start < e]


def ocr_lines(image: bytes, langs: str = "kor+eng") -> list[Line]:
    """Run tesseract (TSV output) and group words into lines with character offsets."""
    # ponytail: subprocess per page; a long-lived tesserocr binding if throughput ever matters
    tsv = subprocess.run(["tesseract", "stdin", "stdout", "-l", langs, "--psm", "6", "tsv"],
                         input=image, capture_output=True, check=True, timeout=60).stdout.decode()
    lines: dict[tuple[str, ...], Line] = {}
    for row in csv.DictReader(io.StringIO(tsv), delimiter="\t", quoting=csv.QUOTE_NONE):
        word = (row.get("text") or "").strip()
        if row["level"] != "5" or not word:
            continue
        line = lines.setdefault((row["page_num"], row["block_num"], row["par_num"], row["line_num"]), Line())
        if line.text:
            line.text += " "
        x, y, w, h = (int(row[k]) for k in ("left", "top", "width", "height"))
        line.words.append((len(line.text), len(line.text) + len(word), (x, y, x + w, y + h)))
        line.text += word
    return list(lines.values())
