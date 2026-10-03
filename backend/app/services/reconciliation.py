"""The matching engine.

A shop transfer says "we deposited this much, into this bank, on this day". A
bank transaction says what actually arrived. Matching them is the point of the
whole system, so the rules here are deliberately few, explicit, and reported
back to the user rather than hidden behind a score.

Three things are hard requirements, never traded off against a good score:
currency, bank, and amount. Only the date is allowed to be approximate, because
a deposit made at 5pm can land on the next banking day.

Cash is the one exception to "bank": a cash payment has no bank until someone
takes it to one. It may match a deposit in any bank, but only on or after the
day it was taken, and it is never confirmed automatically — with the bank
requirement gone there is too little evidence for a machine to decide alone."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.core.errors import Conflict, NotFound, ValidationFailed
from app.models import (
    BankTransaction, MatchSetting, ReconciliationMatch, ShopDailyRecord, ShopTransfer, User,
)
from app.services import audit

MAX_SUGGESTIONS = 5

SCORE_AMOUNT_EXACT = 50
SCORE_AMOUNT_NEAR = 38
SCORE_BANK = 15
SCORE_DATE = {0: 30, 1: 22, 2: 16}
SCORE_DATE_FAR = 10
SCORE_REFERENCE = 10
SCORE_DESCRIPTION = 5


@dataclass
class Candidate:
    transaction: BankTransaction
    score: int
    amount_delta: Decimal
    date_delta_days: int
    breakdown: list[dict] = field(default_factory=list)


def _digits(value: str | None) -> str:
    return "".join(ch for ch in (value or "") if ch.isalnum()).upper()


def score_pair(
    transfer: ShopTransfer,
    txn: BankTransaction,
    record_date: date,
    settings: MatchSetting,
) -> Candidate | None:
    """Returns None when the pair fails a hard requirement."""
    cash = transfer.is_cash
    if transfer.currency_code != txn.currency_code:
        return None
    if not cash and transfer.bank_id != txn.bank_id:
        return None
    if transfer.bank_account_id and transfer.bank_account_id != txn.bank_account_id:
        return None
    if txn.direction != "CREDIT" and not settings.match_debit_transactions:
        return None

    amount_delta = (txn.amount - transfer.amount).copy_abs()
    if amount_delta > settings.amount_tolerance:
        return None

    date_delta = (txn.txn_date - record_date).days
    if cash:
        # Cash cannot be banked before it was received.
        if date_delta < 0 or date_delta > settings.cash_deposit_window_days:
            return None
    elif abs(date_delta) > settings.date_window_days:
        return None

    breakdown: list[dict] = []
    score = 0

    if amount_delta == 0:
        score += SCORE_AMOUNT_EXACT
        breakdown.append(
            {"signal": "amount", "points": SCORE_AMOUNT_EXACT,
             "detail": f"Amount matches exactly ({transfer.amount})"}
        )
    else:
        score += SCORE_AMOUNT_NEAR
        breakdown.append(
            {"signal": "amount", "points": SCORE_AMOUNT_NEAR,
             "detail": f"Amount differs by {amount_delta}, within the allowed tolerance"}
        )

    breakdown.append(
        {"signal": "currency", "points": 0,
         "detail": f"Both are {transfer.currency_code} — required, never assumed"}
    )

    bank_label = txn.bank.code if txn.bank else txn.bank_id
    if cash:
        breakdown.append(
            {"signal": "cash", "points": 0,
             "detail": f"Cash payment — deposited at {bank_label}; needs a person to confirm"}
        )
    else:
        score += SCORE_BANK
        breakdown.append(
            {"signal": "bank", "points": SCORE_BANK, "detail": f"Same bank ({bank_label})"}
        )

    date_points = SCORE_DATE.get(abs(date_delta), SCORE_DATE_FAR)
    score += date_points
    if date_delta == 0:
        detail = "Same date"
    else:
        direction = "later" if date_delta > 0 else "earlier"
        plural = "" if abs(date_delta) == 1 else "s"
        detail = f"Bank date is {abs(date_delta)} day{plural} {direction}"
    breakdown.append({"signal": "date", "points": date_points, "detail": detail})

    transfer_ref = _digits(transfer.reference)
    txn_refs = {_digits(txn.reference), _digits(txn.external_id)} - {""}
    if transfer_ref and any(
        transfer_ref == r or transfer_ref in r or r in transfer_ref for r in txn_refs
    ):
        score += SCORE_REFERENCE
        breakdown.append(
            {"signal": "reference", "points": SCORE_REFERENCE,
             "detail": f"Reference {transfer.reference} appears on the bank line"}
        )

    note = (transfer.note or "").strip().lower()
    if len(note) >= 4 and note in (txn.description or "").lower():
        score += SCORE_DESCRIPTION
        breakdown.append(
            {"signal": "description", "points": SCORE_DESCRIPTION,
             "detail": "The note appears in the bank description"}
        )

    return Candidate(
        transaction=txn,
        score=min(score, 100),
        amount_delta=amount_delta,
        date_delta_days=date_delta,
        breakdown=breakdown,
    )


def confirmed_transaction_ids(db: Session) -> set[int]:
    rows = db.scalars(
        select(ReconciliationMatch.bank_transaction_id).where(
            ReconciliationMatch.is_active.is_(True),
            ReconciliationMatch.status == "CONFIRMED",
        )
    )
    return set(rows)


def find_candidates(
    db: Session, transfer: ShopTransfer, settings: MatchSetting
) -> list[Candidate]:
    record = transfer.daily_record or db.get(ShopDailyRecord, transfer.daily_record_id)
    record_date = record.business_date

    stmt = select(BankTransaction).where(
        BankTransaction.currency_code == transfer.currency_code,
        BankTransaction.is_ignored.is_(False),
        BankTransaction.amount >= transfer.amount - settings.amount_tolerance,
        BankTransaction.amount <= transfer.amount + settings.amount_tolerance,
    )
    if transfer.is_cash:
        stmt = stmt.where(
            BankTransaction.txn_date >= record_date,
            BankTransaction.txn_date
            <= record_date + timedelta(days=settings.cash_deposit_window_days),
        )
    else:
        window = timedelta(days=settings.date_window_days)
        stmt = stmt.where(
            BankTransaction.bank_id == transfer.bank_id,
            BankTransaction.txn_date >= record_date - window,
            BankTransaction.txn_date <= record_date + window,
        )
    if not settings.match_debit_transactions:
        stmt = stmt.where(BankTransaction.direction == "CREDIT")
    if transfer.bank_account_id:
        stmt = stmt.where(BankTransaction.bank_account_id == transfer.bank_account_id)

    taken = confirmed_transaction_ids(db)
    candidates = []
    for txn in db.scalars(stmt):
        if txn.id in taken:
            continue
        scored = score_pair(transfer, txn, record_date, settings)
        if scored:
            candidates.append(scored)
    candidates.sort(key=lambda c: (-c.score, abs(c.date_delta_days), c.transaction.id))
    return candidates


def _clear_suggestions(db: Session, transfer: ShopTransfer) -> None:
    existing = db.scalars(
        select(ReconciliationMatch).where(
            ReconciliationMatch.shop_transfer_id == transfer.id,
            ReconciliationMatch.status == "SUGGESTED",
            ReconciliationMatch.is_active.is_(True),
        )
    )
    for row in existing:
        db.delete(row)
    db.flush()


def run_for_transfer(
    db: Session,
    transfer: ShopTransfer,
    settings: MatchSetting,
    *,
    user: User | None = None,
    allow_auto_confirm: bool = True,
) -> dict:
    """Score one transfer against the bank data and record the outcome."""
    already = db.scalar(
        select(ReconciliationMatch).where(
            ReconciliationMatch.shop_transfer_id == transfer.id,
            ReconciliationMatch.status == "CONFIRMED",
            ReconciliationMatch.is_active.is_(True),
        )
    )
    if already or transfer.is_ignored:
        return {"transfer_id": transfer.id, "outcome": "skipped", "suggestions": 0}

    _clear_suggestions(db, transfer)
    candidates = find_candidates(db, transfer, settings)
    if not candidates:
        return {"transfer_id": transfer.id, "outcome": "unmatched", "suggestions": 0}

    best = candidates[0]
    top_tier = [c for c in candidates if c.score >= settings.auto_confirm_score]
    unique_enough = len(top_tier) == 1 or not settings.auto_confirm_requires_unique

    if transfer.is_cash:
        allow_auto_confirm = False

    if allow_auto_confirm and best.score >= settings.auto_confirm_score and unique_enough:
        match = ReconciliationMatch(
            shop_transfer_id=transfer.id,
            bank_transaction_id=best.transaction.id,
            status="CONFIRMED",
            match_type="EXACT",
            confidence=best.score,
            amount_delta=best.amount_delta,
            date_delta_days=best.date_delta_days,
            score_breakdown=best.breakdown,
            matched_by_id=user.id if user else None,
            matched_at=datetime.now(UTC),
            note="Matched automatically",
        )
        db.add(match)
        db.flush()
        return {
            "transfer_id": transfer.id,
            "outcome": "matched",
            "match_id": match.id,
            "confidence": best.score,
            "suggestions": 0,
        }

    # More than one equally good candidate is precisely when a machine should
    # stop and let a person decide.
    kept = [c for c in candidates if c.score >= settings.suggest_score][:MAX_SUGGESTIONS]
    for candidate in kept:
        db.add(
            ReconciliationMatch(
                shop_transfer_id=transfer.id,
                bank_transaction_id=candidate.transaction.id,
                status="SUGGESTED",
                match_type="POSSIBLE",
                confidence=candidate.score,
                amount_delta=candidate.amount_delta,
                date_delta_days=candidate.date_delta_days,
                score_breakdown=candidate.breakdown,
            )
        )
    db.flush()
    outcome = "possible" if kept else "unmatched"
    if kept and len(top_tier) > 1:
        outcome = "ambiguous"
    return {"transfer_id": transfer.id, "outcome": outcome, "suggestions": len(kept)}


def run_batch(
    db: Session,
    settings: MatchSetting,
    *,
    shop_ids: list[int] | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    bank_id: int | None = None,
    user: User | None = None,
) -> dict:
    stmt = (
        select(ShopTransfer)
        .join(ShopDailyRecord, ShopTransfer.daily_record_id == ShopDailyRecord.id)
        .where(
            ShopTransfer.deleted_at.is_(None),
            ShopTransfer.is_ignored.is_(False),
            ShopDailyRecord.deleted_at.is_(None),
        )
    )
    if shop_ids is not None:
        stmt = stmt.where(ShopDailyRecord.shop_id.in_(shop_ids or [-1]))
    if date_from:
        stmt = stmt.where(ShopDailyRecord.business_date >= date_from)
    if date_to:
        stmt = stmt.where(ShopDailyRecord.business_date <= date_to)
    if bank_id:
        stmt = stmt.where(ShopTransfer.bank_id == bank_id)

    summary = {"examined": 0, "matched": 0, "possible": 0, "ambiguous": 0,
               "unmatched": 0, "skipped": 0}
    for transfer in db.scalars(stmt):
        result = run_for_transfer(db, transfer, settings, user=user)
        summary["examined"] += 1
        summary[result["outcome"]] = summary.get(result["outcome"], 0) + 1
    return summary


# ----------------------------------------------------------------- statuses
PENDING_DEPOSIT = "PENDING_DEPOSIT"


def display_status(transfer: ShopTransfer, entry: dict | None) -> str:
    """What the UI shows. Unmatched cash is not a discrepancy yet — it is money
    still waiting to be taken to the bank — so it gets its own word."""
    if transfer.is_ignored:
        return "IGNORED"
    status = (entry or {}).get("status", "UNMATCHED")
    if status == "UNMATCHED" and transfer.is_cash:
        return PENDING_DEPOSIT
    return status


def transfer_statuses(db: Session, transfer_ids: list[int]) -> dict[int, dict]:
    """MATCHED / POSSIBLE / UNMATCHED for each transfer, in one query."""
    if not transfer_ids:
        return {}
    out = {tid: {"status": "UNMATCHED", "transaction_id": None, "suggestions": 0}
           for tid in transfer_ids}
    rows = db.scalars(
        select(ReconciliationMatch).where(
            ReconciliationMatch.shop_transfer_id.in_(transfer_ids),
            ReconciliationMatch.is_active.is_(True),
            ReconciliationMatch.status.in_(["CONFIRMED", "SUGGESTED"]),
        )
    )
    for row in rows:
        entry = out[row.shop_transfer_id]
        if row.status == "CONFIRMED":
            entry["status"] = "MATCHED"
            entry["transaction_id"] = row.bank_transaction_id
            entry["match_id"] = row.id
        elif entry["status"] != "MATCHED":
            entry["status"] = "POSSIBLE"
            entry["suggestions"] += 1
    return out


def transaction_statuses(db: Session, transaction_ids: list[int]) -> dict[int, dict]:
    if not transaction_ids:
        return {}
    out = {tid: {"status": "UNMATCHED", "transfer_id": None, "suggestions": 0}
           for tid in transaction_ids}
    rows = db.scalars(
        select(ReconciliationMatch).where(
            ReconciliationMatch.bank_transaction_id.in_(transaction_ids),
            ReconciliationMatch.is_active.is_(True),
            ReconciliationMatch.status.in_(["CONFIRMED", "SUGGESTED"]),
        )
    )
    for row in rows:
        entry = out[row.bank_transaction_id]
        if row.status == "CONFIRMED":
            entry["status"] = "MATCHED"
            entry["transfer_id"] = row.shop_transfer_id
            entry["match_id"] = row.id
        elif entry["status"] != "MATCHED":
            entry["status"] = "POSSIBLE"
            entry["suggestions"] += 1
    return out


# ------------------------------------------------------------------ actions
def _guard_available(db: Session, transfer: ShopTransfer, txn: BankTransaction) -> None:
    if transfer.currency_code != txn.currency_code:
        raise ValidationFailed(
            f"Currency mismatch: the shop payment is in {transfer.currency_code} and the "
            f"bank transaction is in {txn.currency_code}. These can never be the same money."
        )
    taken = db.scalar(
        select(ReconciliationMatch).where(
            ReconciliationMatch.bank_transaction_id == txn.id,
            ReconciliationMatch.status == "CONFIRMED",
            ReconciliationMatch.is_active.is_(True),
        )
    )
    if taken:
        raise Conflict(
            "This transaction is already reconciled. Unmatch it first if it belongs "
            "to a different shop payment."
        )
    held = db.scalar(
        select(ReconciliationMatch).where(
            ReconciliationMatch.shop_transfer_id == transfer.id,
            ReconciliationMatch.status == "CONFIRMED",
            ReconciliationMatch.is_active.is_(True),
        )
    )
    if held:
        raise Conflict("This shop payment is already matched to a bank transaction.")


def manual_match(
    db: Session, transfer_id: int, transaction_id: int, user: User, note: str | None
) -> ReconciliationMatch:
    transfer = db.get(ShopTransfer, transfer_id)
    txn = db.get(BankTransaction, transaction_id)
    if not transfer or transfer.deleted_at:
        raise NotFound("That shop payment no longer exists.")
    if not txn:
        raise NotFound("That bank transaction no longer exists.")
    _guard_available(db, transfer, txn)

    settings = db.get(MatchSetting, 1)
    record = db.get(ShopDailyRecord, transfer.daily_record_id)
    scored = score_pair(transfer, txn, record.business_date, settings) if settings else None

    _clear_suggestions(db, transfer)
    match = ReconciliationMatch(
        shop_transfer_id=transfer.id,
        bank_transaction_id=txn.id,
        status="CONFIRMED",
        match_type="MANUAL",
        confidence=scored.score if scored else 0,
        amount_delta=(txn.amount - transfer.amount).copy_abs(),
        date_delta_days=(txn.txn_date - record.business_date).days,
        score_breakdown=(scored.breakdown if scored else
                         [{"signal": "manual", "points": 0,
                           "detail": "Matched by hand, outside the automatic rules"}]),
        matched_by_id=user.id,
        matched_at=datetime.now(UTC),
        note=note,
    )
    db.add(match)
    db.flush()
    audit.record(
        db, action=audit.Actions.MANUAL_MATCH, module="reconciliation", user=user,
        record_type="reconciliation_match", record_id=match.id,
        summary=(f"Manually matched {transfer.currency_code} {transfer.amount} "
                 f"to bank transaction {txn.id}" + (f" — {note}" if note else "")),
        new_values={"transfer_id": transfer.id, "transaction_id": txn.id,
                    "confidence": match.confidence, "reason": note},
    )
    return match


def confirm_suggestion(db: Session, match_id: int, user: User, note: str | None) -> ReconciliationMatch:
    match = db.get(ReconciliationMatch, match_id)
    if not match or not match.is_active:
        raise NotFound("That suggested match no longer exists.")
    if match.status == "CONFIRMED":
        return match
    transfer = db.get(ShopTransfer, match.shop_transfer_id)
    txn = db.get(BankTransaction, match.bank_transaction_id)
    _guard_available(db, transfer, txn)

    siblings = db.scalars(
        select(ReconciliationMatch).where(
            ReconciliationMatch.shop_transfer_id == match.shop_transfer_id,
            ReconciliationMatch.id != match.id,
            ReconciliationMatch.status == "SUGGESTED",
        )
    )
    for sibling in siblings:
        db.delete(sibling)

    match.status = "CONFIRMED"
    match.match_type = "MANUAL" if match.confidence < 95 else "EXACT"
    match.matched_by_id = user.id
    match.matched_at = datetime.now(UTC)
    if note:
        match.note = note
    db.flush()
    audit.record(
        db, action=audit.Actions.MATCH_TRANSACTION, module="reconciliation", user=user,
        record_type="reconciliation_match", record_id=match.id,
        summary=f"Confirmed match at {match.confidence}% confidence",
        new_values={"status": "CONFIRMED", "reason": note},
    )
    return match


def release_matches(db: Session, transfer: ShopTransfer, *, reason: str) -> None:
    """Undo whatever this payment is matched to, keeping the history."""
    for match in db.scalars(
        select(ReconciliationMatch).where(
            ReconciliationMatch.shop_transfer_id == transfer.id,
            ReconciliationMatch.is_active.is_(True),
        )
    ):
        if match.status == "SUGGESTED":
            db.delete(match)
            continue
        match.is_active = False
        match.unmatched_at = datetime.now(UTC)
        match.note = reason
    db.flush()


def unmatch(db: Session, match_id: int, user: User, reason: str | None) -> ReconciliationMatch:
    match = db.get(ReconciliationMatch, match_id)
    if not match:
        raise NotFound("That match no longer exists.")
    if not match.is_active:
        raise Conflict("That match has already been undone.")
    # The row stays; only its active flag changes, so the history of what was
    # once reconciled against what is never lost.
    match.is_active = False
    match.unmatched_by_id = user.id
    match.unmatched_at = datetime.now(UTC)
    match.note = reason or match.note
    db.flush()
    audit.record(
        db, action=audit.Actions.UNMATCH_TRANSACTION, module="reconciliation", user=user,
        record_type="reconciliation_match", record_id=match.id,
        summary=f"Unmatched payment {match.shop_transfer_id} from transaction "
                f"{match.bank_transaction_id}" + (f" — {reason}" if reason else ""),
        old_values={"status": match.status, "is_active": True},
        new_values={"is_active": False, "reason": reason},
    )
    return match
