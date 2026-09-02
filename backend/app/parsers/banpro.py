"""BANPRO — 'Todas Mis Transferencias' printed from online banking.

Only three columns: Fechas, Descripción, Monto. There is no debit/credit split
and no running balance, so direction cannot be checked against the document and
the parser says so rather than guessing silently. The currency is printed on
each amount (C$ or $), which lets us refuse a file uploaded to the wrong account."""
from __future__ import annotations

from decimal import Decimal

from app.parsers.base import BaseParser, NormalizedTransaction, ParseResult, ParserError
from app.parsers.document import PdfDocument, Word
from app.parsers.layout import (
    cluster_rows, currency_from_token, find_header, looks_like_money, parse_date, parse_money,
)

HEADERS = ["fechas", "descripción", "monto"]
HEADERS_ALT = ["fecha", "descripcion", "monto"]
ZERO = Decimal("0.00")


class BanproParser(BaseParser):
    key = "BANPRO"
    display_name = "BANPRO (text)"

    def can_parse(self, doc: PdfDocument) -> bool:
        text = doc.text.lower()
        return "banpro" in text or ("transferencias" in text and "monto" in text)

    def parse(self, doc: PdfDocument, *, currency_code: str) -> ParseResult:
        if not doc.has_text_layer:
            raise ParserError(
                "This BANPRO file has no readable text. Print the movement list to PDF "
                "from online banking instead of photographing the screen."
            )
        result = ParseResult(extraction_method="TEXT")
        row_index = 0
        detected_currencies: set[str] = set()

        for page_no in range(doc.page_count):
            rows = cluster_rows(doc.words(page_no))
            found = find_header(rows, HEADERS) or find_header(rows, HEADERS_ALT)
            if not found:
                continue
            header_index, columns = found
            body = rows[header_index + 1:]

            date_col, desc_col, amount_col = columns.names[0], columns.names[1], columns.names[-1]

            # One amount per transaction: those rows are the anchors. A wrapped
            # description and a vertically centred date are then attached to
            # whichever anchor they sit closest to.
            anchors: list[dict] = []
            for row in body:
                cells = columns.cells(row)
                token = cells.get(amount_col, "")
                if token and looks_like_money(token):
                    anchors.append(
                        {"top": row[0].top, "amount_text": token, "dates": [], "desc": []}
                    )
            if not anchors:
                continue

            def nearest(top: float) -> dict:
                return min(anchors, key=lambda a: abs(a["top"] - top))

            for row in body:
                cells = columns.cells(row)
                top = row[0].top
                date_text = cells.get(date_col, "").strip().rstrip(",")
                if date_text and parse_date(date_text):
                    nearest(top)["dates"].append((top, date_text))
                desc_text = cells.get(desc_col, "").strip()
                if desc_text:
                    nearest(top)["desc"].append((top, desc_text))

            for anchor in anchors:
                txn = self._build(anchor, currency_code, page_no, row_index, detected_currencies)
                if txn is not None:
                    result.transactions.append(txn)
                    row_index += 1

        if not result.transactions:
            raise ParserError(
                "No BANPRO transaction rows were found. Check that the PDF is the "
                "movement list and not a receipt or a balance screen."
            )

        wrong = {c for c in detected_currencies if c != currency_code}
        if wrong:
            raise ParserError(
                f"This statement's amounts are in {', '.join(sorted(wrong))} but the "
                f"selected account is in {currency_code}. Choose the matching account "
                f"and upload it again."
            )

        result.warnings.append(
            "BANPRO's export has no debit/credit column and no running balance, so "
            "direction cannot be verified from the document. Amounts without a minus "
            "sign are recorded as money received."
        )
        dates = [t.txn_date for t in result.transactions]
        result.period_start, result.period_end = min(dates), max(dates)
        return result

    def _build(
        self,
        anchor: dict,
        currency_code: str,
        page_no: int,
        row_index: int,
        detected: set[str],
    ) -> NormalizedTransaction | None:
        amount = parse_money(anchor["amount_text"])
        if amount is None or amount == ZERO:
            return None
        found_currency = currency_from_token(anchor["amount_text"])
        if found_currency:
            detected.add(found_currency)

        if not anchor["dates"]:
            return None
        txn_date = parse_date(sorted(anchor["dates"])[0][1])
        if txn_date is None:
            return None

        description = " ".join(text for _, text in sorted(anchor["desc"])).strip()
        direction = "DEBIT" if amount < ZERO else "CREDIT"
        amount = abs(amount)

        return NormalizedTransaction(
            txn_date=txn_date,
            amount=amount,
            direction=direction,
            currency_code=currency_code,
            description=description,
            reference=_reference_from(description),
            external_id=_reference_from(description),
            debit=amount if direction == "DEBIT" else ZERO,
            credit=amount if direction == "CREDIT" else ZERO,
            page_number=page_no + 1,
            row_index=row_index,
            raw_text=f"{txn_date} | {description} | {anchor['amount_text']}",
            # No balance column means nothing independently confirms the row.
            confidence=90,
        )


def _reference_from(description: str) -> str | None:
    """BANPRO hides the reference inside the description as 'Ref#:48366907'."""
    marker = "ref#:"
    lowered = description.lower()
    if marker in lowered:
        tail = description[lowered.index(marker) + len(marker):]
        digits = "".join(ch for ch in tail if ch.isalnum())
        return digits[:40] or None
    return None
