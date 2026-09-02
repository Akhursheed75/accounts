"""LAFISE — 'Transacciones' export with a real text layer.

Columns: Date | Confirmation number | Description | Debit | Credit | Balance |
Reference | Movement Type. Both the date and the description wrap onto extra
lines, so rows are assembled from a date anchor rather than from visual lines."""
from __future__ import annotations

import re
from decimal import Decimal

from app.parsers.balance_chain import verify
from app.parsers.base import BaseParser, NormalizedTransaction, ParseResult, ParserError
from app.parsers.document import PdfDocument
from app.parsers.layout import (
    ColumnMap, cluster_rows, find_header, looks_like_money, parse_date, parse_money,
)

DATE_START = re.compile(r"^\d{1,2}[/\-][A-Za-z]{3,4}[/\-]\d{0,4}$")
DATE_TAIL = re.compile(r"^\d{2,4}$")
HEADERS = ["date", "description", "debit", "credit", "balance"]
ZERO = Decimal("0.00")


class LafiseParser(BaseParser):
    key = "LAFISE"
    display_name = "LAFISE (text)"

    def can_parse(self, doc: PdfDocument) -> bool:
        text = doc.text.lower()
        return (
            "confirmation" in text and "movement" in text and "balance" in text
        ) or ("lafise" in text and "balance" in text)

    def parse(self, doc: PdfDocument, *, currency_code: str) -> ParseResult:
        if not doc.has_text_layer:
            raise ParserError(
                "This LAFISE file has no readable text layer. Export it again from "
                "online banking rather than scanning a printout."
            )
        result = ParseResult(extraction_method="TEXT")
        row_index = 0

        for page_no in range(doc.page_count):
            rows = cluster_rows(doc.words(page_no))
            found = find_header(rows, HEADERS)
            if not found:
                continue
            header_index, columns = found
            self._read_period(rows[:header_index], result)

            logical: list[dict[str, list[str]]] = []
            for row in rows[header_index + 1:]:
                cells = columns.cells(row)
                date_cell = cells.get("Date", "").strip()
                if DATE_START.match(date_cell):
                    logical.append({k: [v] for k, v in cells.items()})
                elif logical:
                    # Continuation: a wrapped year fragment or wrapped description.
                    for key, value in cells.items():
                        if value:
                            logical[-1].setdefault(key, []).append(value)
                else:
                    continue

            for parts in logical:
                txn = self._build(parts, columns, currency_code, page_no, row_index)
                if txn is not None:
                    result.transactions.append(txn)
                    row_index += 1

        if not result.transactions:
            raise ParserError(
                "No LAFISE transaction rows were found. The file may be an account "
                "summary rather than a movement listing."
            )

        warnings, _ = verify(result.transactions)
        result.warnings.extend(warnings)
        dates = [t.txn_date for t in result.transactions]
        result.period_start, result.period_end = min(dates), max(dates)
        balances = [t.running_balance for t in result.transactions if t.running_balance is not None]
        if balances:
            result.closing_balance = balances[0] if _is_newest_first(result) else balances[-1]
        return result

    # ------------------------------------------------------------------
    def _read_period(self, rows, result: ParseResult) -> None:
        for row in rows:
            texts = [w.text for w in row]
            if any(t.lower() == "from" for t in texts):
                dates = [parse_date(t) for t in texts]
                dates = [d for d in dates if d]
                if len(dates) >= 2:
                    result.period_start, result.period_end = dates[0], dates[-1]

    def _build(
        self,
        parts: dict[str, list[str]],
        columns: ColumnMap,
        currency_code: str,
        page_no: int,
        row_index: int,
    ) -> NormalizedTransaction | None:
        def joined(name: str, sep: str = " ") -> str:
            return sep.join(p for p in parts.get(name, []) if p).strip()

        # The date is split as '11/AUG/20' + '26'; glue the fragments back together.
        date_fragments = [p for p in parts.get("Date", []) if p]
        date_text = "".join(date_fragments) if len(date_fragments) > 1 else (
            date_fragments[0] if date_fragments else ""
        )
        txn_date = parse_date(date_text)
        if txn_date is None:
            return None

        debit = parse_money(joined("Debit")) or ZERO
        credit = parse_money(joined("Credit")) or ZERO
        balance = parse_money(joined("Balance"))

        if debit == ZERO and credit == ZERO:
            return None
        if credit > ZERO:
            direction, amount = "CREDIT", credit
        else:
            direction, amount = "DEBIT", debit

        confirmation = joined("Confirmation")
        # A confirmation number of literal 0 is LAFISE's placeholder, not an id.
        if confirmation.strip() in {"0", ""}:
            confirmation = ""

        return NormalizedTransaction(
            txn_date=txn_date,
            amount=abs(amount),
            direction=direction,
            currency_code=currency_code,
            description=joined("Description"),
            reference=joined("Reference") or None,
            external_id=confirmation or None,
            debit=abs(debit),
            credit=abs(credit),
            running_balance=balance,
            movement_type=(joined("Movement") or joined("Type") or None),
            page_number=page_no + 1,
            row_index=row_index,
            raw_text=" | ".join(f"{k}={joined(k)}" for k in columns.names if joined(k)),
            confidence=100,
        )


def _is_newest_first(result: ParseResult) -> bool:
    dates = [t.txn_date for t in result.transactions]
    if len(dates) < 2:
        return False
    return dates[0] >= dates[-1]
