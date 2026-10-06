"""BAC Credomatic — 'Monthly Transactions'.

These files are produced by "Microsoft: Print To PDF" and contain no embedded
fonts at all: the text is drawn as vector outlines, so a text-layer extraction
returns nothing even though the page looks perfect on screen. They therefore go
through OCR, and every OCR'd amount is then checked against the statement's own
running balance before it is allowed anywhere near reconciliation."""
from __future__ import annotations

import re
from decimal import Decimal

from app.parsers.balance_chain import verify
from app.parsers.base import BaseParser, NormalizedTransaction, ParseResult, ParserError
from app.parsers.document import OcrUnavailable, PdfDocument
from app.parsers.layout import parse_date, parse_money

ZERO = Decimal("0.00")

# 11/08/2026 301030479 DP PAGO DE ROPA 0.00 4,452.00 92,220.86
ROW = re.compile(
    r"^(?P<date>\d{1,2}/\d{1,2}/\d{2,4})\s+"
    r"(?P<reference>[0-9OoIl]{4,20})\s+"
    # Mostly letters (DP, TF, WD, DC) but BAC also prints codes like "3V".
    r"(?P<code>(?=[A-Z0-9]*[A-Z])[A-Z0-9]{2,4})\s+"
    r"(?P<description>.*?)\s+"
    r"(?P<debit>[\d.,]+)\s+"
    r"(?P<credit>[\d.,]+)\s+"
    r"(?P<balance>[\d.,]+)\s*$"
)
ACCOUNT = re.compile(r"Account:?\s*([A-Z0-9]{10,40})", re.I)
CURRENCY_LINE = re.compile(r"^\s*Currency:?\s*([A-Z]{3})\s*$", re.I | re.M)
DATE_FROM = re.compile(r"Date\s*from:?\s*(\d{1,2}/\d{1,2}/\d{2,4})", re.I)
DATE_TO = re.compile(r"Date\s*to:?\s*(\d{1,2}/\d{1,2}/\d{2,4})", re.I)

# BAC labels cordobas "COR"; the rest of the system uses the ISO code.
BANK_CURRENCY_ALIASES = {"COR": "NIO", "CS": "NIO", "NIO": "NIO", "USD": "USD", "DOL": "USD"}


class BacParser(BaseParser):
    key = "BAC"
    display_name = "BAC Credomatic (OCR)"

    def can_parse(self, doc: PdfDocument) -> bool:
        haystack = doc.text.lower()
        if "bac" in haystack or "credomatic" in haystack:
            return True
        # No text layer at all is BAC's signature among the configured banks,
        # but only confirm it by actually reading a page.
        if not doc.has_text_layer and doc.ocr_available():
            try:
                sample = doc.ocr_page(0).lower()
            except Exception:
                return False
            return "monthly transactions" in sample or "credomatic" in sample
        return False

    def parse(self, doc: PdfDocument, *, currency_code: str) -> ParseResult:
        use_ocr = not doc.has_text_layer
        result = ParseResult(extraction_method="OCR" if use_ocr else "TEXT")

        pages: list[str] = []
        for page_no in range(doc.page_count):
            if use_ocr:
                try:
                    pages.append(doc.ocr_page(page_no))
                except OcrUnavailable as exc:
                    raise ParserError(str(exc)) from exc
            else:
                pages.append(doc.page_texts[page_no])

        whole = "\n".join(pages)
        account_match = ACCOUNT.search(whole)
        if account_match:
            result.account_number = account_match.group(1)
        currency_match = CURRENCY_LINE.search(whole)
        if currency_match:
            detected = BANK_CURRENCY_ALIASES.get(currency_match.group(1).upper())
            result.statement_currency = detected
            if detected and detected != currency_code:
                raise ParserError(
                    f"This statement is for a {detected} account (BAC prints it as "
                    f"'{currency_match.group(1).upper()}') but you selected a "
                    f"{currency_code} account. Pick the matching account and try again."
                )
        from_match, to_match = DATE_FROM.search(whole), DATE_TO.search(whole)
        if from_match:
            result.period_start = parse_date(from_match.group(1))
        if to_match:
            result.period_end = parse_date(to_match.group(1))

        row_index = 0
        skipped: list[str] = []
        for page_no, text in enumerate(pages):
            for line in text.splitlines():
                line = line.strip()
                if not line or _is_noise(line):
                    continue
                match = ROW.match(line)
                if not match:
                    if _looks_like_a_lost_row(line):
                        skipped.append(line)
                    continue
                txn = self._build(match, currency_code, page_no, row_index, line)
                if txn is not None:
                    result.transactions.append(txn)
                    row_index += 1

        if not result.transactions:
            raise ParserError(
                "No BAC transaction rows could be read from this file. If it is a "
                "scan, make sure the page is straight and at least 200 dpi."
            )

        warnings, _ = verify(result.transactions)
        result.warnings.extend(warnings)

        for txn in result.transactions:
            if txn.chain_verified:
                # The running balance independently confirms the amount, which is
                # a stronger guarantee than OCR alone can give.
                txn.confidence = max(txn.confidence, 97) if use_ocr else txn.confidence
            elif use_ocr:
                txn.confidence = min(txn.confidence, 80)

        if skipped:
            result.partial = True
            result.warnings.append(
                f"{len(skipped)} line(s) looked like transactions but could not be read: "
                + "; ".join(s[:80] for s in skipped[:5])
            )

        dates = [t.txn_date for t in result.transactions]
        result.period_start = result.period_start or min(dates)
        result.period_end = result.period_end or max(dates)
        balances = [t.running_balance for t in result.transactions if t.running_balance]
        if balances:
            result.closing_balance = balances[-1]
        return result

    def _build(
        self, match: re.Match, currency_code: str, page_no: int, row_index: int, line: str
    ) -> NormalizedTransaction | None:
        txn_date = parse_date(match.group("date"))
        if txn_date is None:
            return None
        debit = parse_money(match.group("debit")) or ZERO
        credit = parse_money(match.group("credit")) or ZERO
        balance = parse_money(match.group("balance"))
        if debit == ZERO and credit == ZERO:
            return None
        direction, amount = ("CREDIT", credit) if credit > ZERO else ("DEBIT", debit)

        # OCR sometimes reads O for 0 inside the reference column.
        reference = match.group("reference").translate(str.maketrans("OoIl", "0011"))

        return NormalizedTransaction(
            txn_date=txn_date,
            amount=abs(amount),
            direction=direction,
            currency_code=currency_code,
            description=match.group("description").strip(),
            reference=reference,
            external_id=reference,
            debit=abs(debit),
            credit=abs(credit),
            running_balance=balance,
            movement_type=match.group("code"),
            page_number=page_no + 1,
            row_index=row_index,
            raw_text=line,
            confidence=85,
        )


_NOISE = (
    "monthly transactions", "account balance", "total balance", "generation date",
    "date reference code description", "the information in this document",
    "pending confirmation", "currency total balance", "witheld and deferred",
    "withheld and deferred", "about:blank", "date from",
)


def _is_noise(line: str) -> bool:
    lowered = line.lower()
    return any(marker in lowered for marker in _NOISE)


def _looks_like_a_lost_row(line: str) -> bool:
    """A line that starts with a date and carries several numbers was almost
    certainly a transaction; losing it silently is the one outcome to avoid."""
    if not re.match(r"^\d{1,2}/\d{1,2}/\d{2,4}\b", line):
        return False
    return len(re.findall(r"[\d.,]{3,}", line)) >= 3
