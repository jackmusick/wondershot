"""Optional local OCR via the tesseract binary — word boxes for AI redact.

Discovery uses shutil.which (no hardcoded paths, per WS-E constraints).
Everything degrades gracefully: no tesseract, OCR failure, or garbage
output all yield an empty word list and the caller falls back to the
LLM-bbox path.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass


@dataclass
class Word:
    text: str
    x: int
    y: int
    w: int
    h: int
    conf: float


def find_tesseract() -> str | None:
    return shutil.which("tesseract")


def parse_tsv(tsv: str) -> list[Word]:
    """Word boxes out of `tesseract ... tsv` output (level-5 rows)."""
    lines = tsv.splitlines()
    if not lines:
        return []
    header = lines[0].split("\t")
    idx = {name: i for i, name in enumerate(header)}
    required = {"left", "top", "width", "height", "conf", "text"}
    if not required <= idx.keys():
        return []
    words: list[Word] = []
    for line in lines[1:]:
        cols = line.split("\t")
        if len(cols) != len(header):
            continue
        text = cols[idx["text"]].strip()
        if not text:
            continue
        try:
            conf = float(cols[idx["conf"]])
            if conf < 0:  # -1 marks structural (non-word) rows
                continue
            words.append(Word(
                text=text,
                x=int(cols[idx["left"]]), y=int(cols[idx["top"]]),
                w=int(cols[idx["width"]]), h=int(cols[idx["height"]]),
                conf=conf))
        except ValueError:
            continue
    return words


def ocr_words(image, binary: str | None = None) -> list[Word]:
    """Run tesseract over a QImage; [] when unavailable or failing."""
    binary = binary or find_tesseract()
    if not binary:
        return []
    from PySide6.QtCore import QBuffer, QIODevice
    buf = QBuffer()
    buf.open(QIODevice.WriteOnly)
    image.save(buf, "PNG")
    try:
        out = subprocess.run([binary, "stdin", "stdout", "tsv"],
                             input=bytes(buf.data()),
                             capture_output=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return []
    if out.returncode != 0:
        return []
    return parse_tsv(out.stdout.decode("utf-8", "replace"))
