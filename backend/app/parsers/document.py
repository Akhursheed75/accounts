"""A PDF opened once and shared by whichever parser handles it.

Text extraction and OCR are both lazy: a statement with a real text layer never
pays for rendering, and one without it renders each page only once."""
from __future__ import annotations

import io
import logging
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

import pdfplumber

from app.core.config import settings

log = logging.getLogger(__name__)

# Below this many characters per page, a "text layer" is really just a header or
# a stray watermark and the page needs OCR. BAC's statements land at 0.
MIN_CHARS_PER_PAGE_FOR_TEXT = 40


@dataclass(slots=True)
class Word:
    text: str
    x0: float
    x1: float
    top: float
    bottom: float

    @property
    def center_x(self) -> float:
        return (self.x0 + self.x1) / 2


class OcrUnavailable(RuntimeError):
    pass


class PdfDocument:
    def __init__(self, data: bytes, filename: str = "statement.pdf"):
        self.data = data
        self.filename = filename
        self._plumber = pdfplumber.open(io.BytesIO(data))
        self._ocr_cache: dict[int, str] = {}
        self._ocr_words_cache: dict[int, list[Word]] = {}
        self._ocr_conf: dict[int, int] = {}

    def close(self) -> None:
        try:
            self._plumber.close()
        except Exception:
            pass

    def __enter__(self) -> "PdfDocument":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ------------------------------------------------------------------ text
    @property
    def page_count(self) -> int:
        return len(self._plumber.pages)

    @cached_property
    def page_texts(self) -> list[str]:
        out = []
        for page in self._plumber.pages:
            try:
                out.append(page.extract_text() or "")
            except Exception:
                out.append("")
        return out

    @cached_property
    def text(self) -> str:
        return "\n".join(self.page_texts)

    def words(self, page_number: int) -> list[Word]:
        page = self._plumber.pages[page_number]
        raw = page.extract_words(use_text_flow=False, keep_blank_chars=False)
        return [
            Word(w["text"], w["x0"], w["x1"], w["top"], w["bottom"]) for w in raw
        ]

    @property
    def has_text_layer(self) -> bool:
        if self.page_count == 0:
            return False
        chars = sum(len(t.strip()) for t in self.page_texts)
        return chars / self.page_count >= MIN_CHARS_PER_PAGE_FOR_TEXT

    # ------------------------------------------------------------------- ocr
    @staticmethod
    def ocr_available() -> bool:
        return bool(shutil.which(settings.tesseract_cmd or "tesseract")) and bool(
            shutil.which("pdftoppm")
        )

    def _run_ocr(self, page_number: int, *args: str) -> str:
        """Render one page at OCR dpi and run Tesseract over it with `args`."""
        if not self.ocr_available():
            raise OcrUnavailable(
                "This statement has no readable text and OCR is not installed on the server."
            )
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "in.pdf"
            src.write_bytes(self.data)
            prefix = Path(tmp) / "page"
            cmd = [
                "pdftoppm", "-r", str(settings.ocr_dpi), "-gray", "-png",
                "-f", str(page_number + 1), "-l", str(page_number + 1),
                str(src), str(prefix),
            ]
            if settings.poppler_path:
                cmd[0] = str(Path(settings.poppler_path) / "pdftoppm")
            subprocess.run(cmd, check=True, capture_output=True, timeout=180)
            images = sorted(Path(tmp).glob("page*.png"))
            if not images:
                raise OcrUnavailable("The page could not be rendered for OCR.")
            tess = settings.tesseract_cmd or "tesseract"
            langs = settings.ocr_languages
            proc = subprocess.run(
                [tess, str(images[0]), "stdout", *args, "-l", langs],
                capture_output=True, timeout=300,
            )
            if proc.returncode != 0:
                # A missing language pack is the usual cause; fall back to English.
                proc = subprocess.run(
                    [tess, str(images[0]), "stdout", *args, "-l", "eng"],
                    capture_output=True, timeout=300,
                )
            if proc.returncode != 0:
                raise OcrUnavailable(
                    "OCR failed: " + proc.stderr.decode("utf-8", "ignore")[:300]
                )
            return proc.stdout.decode("utf-8", "ignore")

    def ocr_page(self, page_number: int) -> str:
        """Plain OCR text of one page, read as a single block (BAC's layout)."""
        if page_number not in self._ocr_cache:
            self._ocr_cache[page_number] = self._run_ocr(page_number, "--psm", "6")
        return self._ocr_cache[page_number]

    def ocr_words(self, page_number: int) -> list[Word]:
        """OCR'd words with their positions, in the same units (PDF points) as
        words(), so a parser that reads columns from a text layer can read a
        scan of the same page without knowing the difference."""
        if page_number in self._ocr_words_cache:
            return self._ocr_words_cache[page_number]
        tsv = self._run_ocr(page_number, "--psm", "4", "tsv")
        scale = 72.0 / float(settings.ocr_dpi)
        words: list[Word] = []
        for line in tsv.splitlines()[1:]:
            parts = line.split("\t")
            if len(parts) < 12 or not parts[11].strip():
                continue
            try:
                conf = float(parts[10])
                left, top, width, height = (int(parts[i]) for i in (6, 7, 8, 9))
            except ValueError:
                continue
            if conf < 0:
                continue
            words.append(
                Word(
                    parts[11].strip(),
                    left * scale, (left + width) * scale,
                    top * scale, (top + height) * scale,
                )
            )
        self._ocr_words_cache[page_number] = words
        return words

    @cached_property
    def ocr_text(self) -> str:
        return "\n".join(self.ocr_page(i) for i in range(self.page_count))
