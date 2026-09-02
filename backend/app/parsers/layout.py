"""Shared primitives for reading tabular PDFs: money, dates, row clustering and
column mapping from header positions."""
from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from app.parsers.document import Word

MONTHS = {
    "JAN": 1, "ENE": 1, "FEB": 2, "MAR": 3, "APR": 4, "ABR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "AGO": 8, "SEP": 9, "SEPT": 9, "OCT": 10, "NOV": 11,
    "DEC": 12, "DIC": 12,
}

_MONEY_RE = re.compile(r"^[\(\-]?\s*(?:C\$|US\$|\$|NIO|USD|COR)?\s*[\d.,]+\s*\)?$", re.I)
_CURRENCY_PREFIX = re.compile(r"^(C\$|US\$|\$|NIO|USD|COR)\s*", re.I)


def looks_like_money(token: str) -> bool:
    token = token.strip()
    if not token or not any(ch.isdigit() for ch in token):
        return False
    return bool(_MONEY_RE.match(token))


def parse_money(token: str) -> Decimal | None:
    """Handles '14,098.00', 'C$20,000.00', '$460.00', '(1,234.00)' and
    the European '1.234,56' form. Returns None if it is not a number."""
    if token is None:
        return None
    raw = token.strip()
    if not raw:
        return None
    negative = raw.startswith("(") and raw.endswith(")") or raw.startswith("-")
    raw = raw.strip("()").lstrip("-").strip()
    raw = _CURRENCY_PREFIX.sub("", raw).strip()
    raw = raw.replace(" ", "")
    if not raw or not any(ch.isdigit() for ch in raw):
        return None

    if "," in raw and "." in raw:
        # Whichever separator comes last is the decimal point.
        if raw.rfind(",") > raw.rfind("."):
            raw = raw.replace(".", "").replace(",", ".")
        else:
            raw = raw.replace(",", "")
    elif "," in raw:
        parts = raw.split(",")
        # '1,234' is thousands; '1234,56' is a decimal comma.
        if len(parts[-1]) == 3 and len(parts) > 1 and all(p.isdigit() for p in parts):
            raw = raw.replace(",", "")
        else:
            raw = raw.replace(",", ".")
    try:
        value = Decimal(raw)
    except (InvalidOperation, ValueError):
        return None
    return -value if negative else value


def currency_from_token(token: str) -> str | None:
    """BANPRO prints the currency on the amount itself, which is the only place
    it appears per row."""
    t = token.strip().upper()
    if t.startswith("C$") or t.startswith("NIO"):
        return "NIO"
    if t.startswith("US$") or t.startswith("USD") or t.startswith("$"):
        return "USD"
    return None


_DATE_PATTERNS = [
    # 11/AUG/2026, 11-AGO-26
    (re.compile(r"^(\d{1,2})[/\-]([A-Za-z]{3,4})[/\-](\d{2,4})$"), "dmy_name"),
    # 11/08/2026
    (re.compile(r"^(\d{1,2})[/\-](\d{1,2})[/\-](\d{2,4})$"), "numeric"),
    # 2026-08-11
    (re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})$"), "iso"),
]


def parse_date(token: str, *, day_first: bool = True) -> date | None:
    t = (token or "").strip().rstrip(".")
    if not t:
        return None
    for pattern, kind in _DATE_PATTERNS:
        m = pattern.match(t)
        if not m:
            continue
        try:
            if kind == "iso":
                return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            if kind == "dmy_name":
                month = MONTHS.get(m.group(2).upper())
                if not month:
                    return None
                return date(_year(m.group(3)), month, int(m.group(1)))
            a, b = int(m.group(1)), int(m.group(2))
            if day_first:
                day, month = a, b
            else:
                month, day = a, b
            # A value above 12 can only be the day, whatever the configured order.
            if month > 12 and day <= 12:
                day, month = month, day
            return date(_year(m.group(3)), month, day)
        except ValueError:
            return None
    return None


def _year(raw: str) -> int:
    year = int(raw)
    if year < 100:
        return 2000 + year
    return year


def cluster_rows(words: list[Word], tolerance: float = 3.0) -> list[list[Word]]:
    """Group words into visual lines by their vertical position."""
    rows: list[list[Word]] = []
    for word in sorted(words, key=lambda w: (round(w.top, 1), w.x0)):
        if rows and abs(rows[-1][0].top - word.top) <= tolerance:
            rows[-1].append(word)
        else:
            rows.append([word])
    for row in rows:
        row.sort(key=lambda w: w.x0)
    return rows


class ColumnMap:
    """Maps a word to a table column.

    Header positions alone are not enough: LAFISE's description text starts to
    the *left* of the word "Description", while BANPRO's runs far to the right
    of "Descripcion" and would otherwise land in the amount column — which is
    exactly the kind of silent error that turns a description into a payment.

    So the header only seeds the columns. The real boundaries are learned from
    the body: words overlapping a header widen that column's band, and whatever
    is left over joins the band it sits closest to, left to right. Bands are
    never allowed to cross one another."""

    def __init__(
        self,
        headers: list[tuple[str, float, float]],
        body_words: list[Word] | None = None,
    ):
        self.headers = sorted(headers, key=lambda h: h[1])
        self.names = [h[0] for h in self.headers]
        self.bands: list[list[float]] = [[h[1], h[2]] for h in self.headers]
        if body_words:
            self._fit(body_words)

    # ------------------------------------------------------------- fitting
    def _fit(self, words: list[Word]) -> None:
        seeded: list[tuple[int, Word]] = []
        leftover: list[Word] = []
        for word in words:
            index = self._best_overlap(word, self.bands)
            if index is None:
                leftover.append(word)
            else:
                seeded.append((index, word))
        for index, word in seeded:
            self._grow(index, word)
        # Left to right, so a band grows one step at a time toward its content
        # instead of jumping across a gap.
        for word in sorted(leftover, key=lambda w: w.x0):
            self._grow(self._nearest(word), word)

    @staticmethod
    def _best_overlap(word: Word, bands: list[list[float]]) -> int | None:
        best_index, best_overlap = None, 0.0
        for i, (lo, hi) in enumerate(bands):
            overlap = min(word.x1, hi) - max(word.x0, lo)
            if overlap > best_overlap:
                best_index, best_overlap = i, overlap
        return best_index

    def _nearest(self, word: Word) -> int:
        def distance(band: list[float]) -> float:
            if word.x1 < band[0]:
                return band[0] - word.x1
            if word.x0 > band[1]:
                return word.x0 - band[1]
            return 0.0

        return min(range(len(self.bands)), key=lambda i: (distance(self.bands[i]), i))

    def _grow(self, index: int, word: Word) -> None:
        band = self.bands[index]
        left_limit = self.bands[index - 1][1] if index > 0 else float("-inf")
        right_limit = self.bands[index + 1][0] if index + 1 < len(self.bands) else float("inf")
        band[0] = max(min(band[0], word.x0), left_limit)
        band[1] = min(max(band[1], word.x1), right_limit)

    # ------------------------------------------------------------- reading
    def column_for(self, word: Word) -> str | None:
        if not self.names:
            return None
        index = self._best_overlap(word, self.bands)
        if index is None:
            index = self._nearest(word)
        return self.names[index]

    def cells(self, row: list[Word]) -> dict[str, str]:
        buckets: dict[str, list[Word]] = {name: [] for name in self.names}
        for word in row:
            name = self.column_for(word)
            if name:
                buckets[name].append(word)
        return {
            name: " ".join(w.text for w in sorted(words, key=lambda w: w.x0)).strip()
            for name, words in buckets.items()
        }


def find_header(
    rows: list[list[Word]],
    required: list[str],
    *,
    max_rows: int = 40,
    body_words: list[Word] | None = None,
) -> tuple[int, ColumnMap] | None:
    """Locate the row containing every required header label and build a column
    map from it, fitted to the body words when they are supplied."""
    wanted = [r.lower() for r in required]
    for index, row in enumerate(rows[:max_rows]):
        texts = [w.text.lower().strip(":") for w in row]
        if all(any(t == want or t.startswith(want) for t in texts) for want in wanted):
            headers = [(w.text.strip(":"), w.x0, w.x1) for w in row]
            if body_words is None:
                body = [w for r in rows[index + 1:] for w in r]
            else:
                body = body_words
            return index, ColumnMap(headers, body)
    return None


def split_blocks(rows: list[list[Word]], gap_factor: float = 1.45) -> list[list[list[Word]]]:
    """Split consecutive text lines into blocks wherever the vertical gap grows
    noticeably larger than the prevailing line spacing. Used for wrapped
    description cells."""
    if not rows:
        return []
    gaps = [rows[i + 1][0].top - rows[i][0].top for i in range(len(rows) - 1)]
    if not gaps:
        return [[rows[0]]]
    typical = min(g for g in gaps if g > 0) if any(g > 0 for g in gaps) else 1.0
    blocks: list[list[list[Word]]] = [[rows[0]]]
    for i, gap in enumerate(gaps):
        if gap > typical * gap_factor:
            blocks.append([rows[i + 1]])
        else:
            blocks[-1].append(rows[i + 1])
    return blocks
