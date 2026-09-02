from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.deps import require
from app.core.errors import NotFound
from app.db.session import get_db
from app.models import BankAccount, BankTransaction, User
from app.schemas.banking import IgnoreIn, TransactionOut
from app.schemas.common import Page
from app.services import audit
from app.services import reconciliation as recon

router = APIRouter(tags=["transactions"])


def _out(txn: BankTransaction, status: dict) -> TransactionOut:
    return TransactionOut(
        id=txn.id, statement_id=txn.statement_id, bank_account_id=txn.bank_account_id,
        bank_id=txn.bank_id, bank_code=txn.bank.code if txn.bank else None,
        account_label=txn.statement.account.label if txn.statement and txn.statement.account else None,
        txn_date=txn.txn_date, value_date=txn.value_date, description=txn.description,
        reference=txn.reference, external_id=txn.external_id, movement_type=txn.movement_type,
        debit=txn.debit, credit=txn.credit, amount=txn.amount, direction=txn.direction,
        currency_code=txn.currency_code, running_balance=txn.running_balance,
        extraction_confidence=txn.extraction_confidence, page_number=txn.page_number,
        is_ignored=txn.is_ignored,
        match_status="IGNORED" if txn.is_ignored else status.get("status", "UNMATCHED"),
        matched_transfer_id=status.get("transfer_id"),
        suggestion_count=status.get("suggestions", 0),
    )


@router.get("/bank-transactions", response_model=Page[TransactionOut])
def list_transactions(
    bank_id: int | None = None,
    bank_account_id: int | None = None,
    statement_id: int | None = None,
    currency_code: str | None = None,
    direction: str | None = None,
    match_status: str | None = Query(None, description="MATCHED | POSSIBLE | UNMATCHED | IGNORED"),
    date_from: date | None = None,
    date_to: date | None = None,
    amount_min: Decimal | None = None,
    amount_max: Decimal | None = None,
    search: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
    user: User = Depends(require("transaction.read")),
) -> Page[TransactionOut]:
    stmt = select(BankTransaction)
    if bank_id:
        stmt = stmt.where(BankTransaction.bank_id == bank_id)
    if bank_account_id:
        stmt = stmt.where(BankTransaction.bank_account_id == bank_account_id)
    if statement_id:
        stmt = stmt.where(BankTransaction.statement_id == statement_id)
    if currency_code:
        stmt = stmt.where(BankTransaction.currency_code == currency_code.upper())
    if direction:
        stmt = stmt.where(BankTransaction.direction == direction.upper())
    if date_from:
        stmt = stmt.where(BankTransaction.txn_date >= date_from)
    if date_to:
        stmt = stmt.where(BankTransaction.txn_date <= date_to)
    if amount_min is not None:
        stmt = stmt.where(BankTransaction.amount >= amount_min)
    if amount_max is not None:
        stmt = stmt.where(BankTransaction.amount <= amount_max)
    if search:
        needle = f"%{search.strip()}%"
        stmt = stmt.where(
            or_(
                BankTransaction.description.ilike(needle),
                BankTransaction.reference.ilike(needle),
                BankTransaction.external_id.ilike(needle),
            )
        )

    if match_status:
        wanted = match_status.upper()
        if wanted == "IGNORED":
            stmt = stmt.where(BankTransaction.is_ignored.is_(True))
        else:
            stmt = stmt.where(BankTransaction.is_ignored.is_(False))
            confirmed = recon.confirmed_transaction_ids(db)
            if wanted == "MATCHED":
                stmt = stmt.where(BankTransaction.id.in_(confirmed or [-1]))
            else:
                stmt = stmt.where(BankTransaction.id.notin_(confirmed or [-1]))

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = list(
        db.scalars(
            stmt.order_by(BankTransaction.txn_date.desc(), BankTransaction.id.desc())
            .offset((page - 1) * page_size).limit(page_size)
        )
    )
    statuses = recon.transaction_statuses(db, [t.id for t in rows])
    items = [_out(t, statuses.get(t.id, {})) for t in rows]

    # POSSIBLE and UNMATCHED can only be separated after the status lookup.
    if match_status and match_status.upper() in {"POSSIBLE", "UNMATCHED"}:
        items = [i for i in items if i.match_status == match_status.upper()]
        total = len(items)
    return Page(items=items, total=total, page=page, page_size=page_size)


@router.get("/bank-transactions/{transaction_id}", response_model=TransactionOut)
def get_transaction(
    transaction_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require("transaction.read")),
) -> TransactionOut:
    txn = db.get(BankTransaction, transaction_id)
    if not txn:
        raise NotFound("That transaction does not exist.")
    statuses = recon.transaction_statuses(db, [txn.id])
    return _out(txn, statuses.get(txn.id, {}))


@router.post("/bank-transactions/{transaction_id}/ignore", response_model=TransactionOut)
def ignore_transaction(
    transaction_id: int,
    payload: IgnoreIn,
    db: Session = Depends(get_db),
    user: User = Depends(require("reconciliation.match")),
) -> TransactionOut:
    """Marks a bank line as not expected to have a shop counterpart — bank
    interest, an internal transfer — so it stops appearing as an exception."""
    txn = db.get(BankTransaction, transaction_id)
    if not txn:
        raise NotFound("That transaction does not exist.")
    txn.is_ignored = not payload.undo
    txn.ignored_reason = None if payload.undo else (payload.reason or None)
    audit.record(
        db, action=audit.Actions.IGNORE_ITEM, module="reconciliation", user=user,
        record_type="bank_transaction", record_id=txn.id,
        summary=("Stopped ignoring" if payload.undo else "Ignored")
                + f" bank transaction {txn.currency_code} {txn.amount}"
                + (f" — {payload.reason}" if payload.reason and not payload.undo else ""),
        new_values={"is_ignored": txn.is_ignored, "reason": txn.ignored_reason},
    )
    db.commit()
    db.refresh(txn)
    statuses = recon.transaction_statuses(db, [txn.id])
    return _out(txn, statuses.get(txn.id, {}))
