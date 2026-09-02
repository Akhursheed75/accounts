"""Cross-checks extracted rows against the statement's own running balance.

Every bank prints a balance after each movement. That column is a checksum the
statement gives us for free: if a row's amount and direction are right, the
balance must move by exactly that amount. This catches a mis-assigned
debit/credit column and, on OCR'd statements, a misread digit — the difference
between reconciling a payment and quietly inventing one."""
from __future__ import annotations

from decimal import Decimal

from app.parsers.base import NormalizedTransaction

TOLERANCE = Decimal("0.01")


def _signed(txn: NormalizedTransaction) -> Decimal:
    return txn.amount if txn.direction == "CREDIT" else -txn.amount


def verify(transactions: list[NormalizedTransaction]) -> tuple[list[str], int]:
    """Returns (warnings, rows_confirmed).

    Directions are corrected in place where the balance column is unambiguous.
    Rows the chain cannot vouch for keep their parsed direction but have their
    confidence reduced, so the UI can flag them."""
    rows = [t for t in transactions if t.running_balance is not None]
    if len(rows) < 2:
        return ([], 0)

    balances = [t.running_balance for t in rows]

    # Two possible orderings: oldest-first (balance grows down the page) or
    # newest-first (LAFISE prints it this way).
    asc_hits = desc_hits = 0
    for i in range(len(rows) - 1):
        delta_asc = balances[i + 1] - balances[i]      # amount of row i+1
        delta_desc = balances[i] - balances[i + 1]     # amount of row i
        if abs(abs(delta_asc) - rows[i + 1].amount) <= TOLERANCE:
            asc_hits += 1
        if abs(abs(delta_desc) - rows[i].amount) <= TOLERANCE:
            desc_hits += 1

    warnings: list[str] = []
    confirmed = 0

    if asc_hits == 0 and desc_hits == 0:
        warnings.append(
            "The running balance column does not agree with any of the extracted "
            "amounts, so the debit/credit direction could not be verified."
        )
        for txn in rows:
            txn.confidence = min(txn.confidence, 70)
        return (warnings, 0)

    ascending = asc_hits >= desc_hits
    for i in range(len(rows) - 1):
        if ascending:
            target, delta = rows[i + 1], balances[i + 1] - balances[i]
        else:
            target, delta = rows[i], balances[i] - balances[i + 1]
        if abs(abs(delta) - target.amount) > TOLERANCE:
            warnings.append(
                f"Row {target.row_index + 1} ({target.description[:40] or 'no description'}) "
                f"shows {target.amount} but the balance moves by {abs(delta)}."
            )
            target.confidence = min(target.confidence, 55)
            continue
        expected = "CREDIT" if delta > 0 else "DEBIT"
        if target.direction != expected:
            warnings.append(
                f"Row {target.row_index + 1} was read as a {target.direction.lower()} but the "
                f"running balance shows it as a {expected.lower()}; corrected."
            )
            target.direction = expected
            if expected == "CREDIT":
                target.credit, target.debit = target.amount, Decimal("0.00")
            else:
                target.debit, target.credit = target.amount, Decimal("0.00")
        target.chain_verified = True
        confirmed += 1

    # The row at the far end of the page has no neighbour to check it against.
    unchecked = rows[0] if ascending else rows[-1]
    if unchecked.confidence == 100 and len(rows) > 1:
        unchecked.confidence = 95

    return (warnings, confirmed)
