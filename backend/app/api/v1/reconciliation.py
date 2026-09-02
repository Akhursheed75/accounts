from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import accessible_shop_ids, assert_shop_access, require
from app.core.errors import NotFound
from app.db.session import get_db
from app.models import (
    BankTransaction, ReconciliationMatch, ShopDailyRecord, ShopTransfer, User,
)
from app.schemas.banking import TransactionOut
from app.schemas.common import Message, Page
from app.schemas.reconciliation import (
    ConfirmIn, MatchIn, MatchOut, ReconciliationRow, RunIn, TransferSide, UnmatchIn,
    UnmatchedSummary,
)
from app.api.v1.transactions import _out as txn_out
from app.services import audit
from app.services import reconciliation as recon
from app.services.settings_store import match_settings

router = APIRouter(tags=["reconciliation"])


def _match_out(match: ReconciliationMatch, db: Session) -> MatchOut:
    from app.models import User as U

    def name(uid: int | None) -> str | None:
        return db.get(U, uid).full_name if uid else None

    return MatchOut(
        id=match.id, shop_transfer_id=match.shop_transfer_id,
        bank_transaction_id=match.bank_transaction_id, status=match.status,
        match_type=match.match_type, confidence=match.confidence,
        amount_delta=match.amount_delta, date_delta_days=match.date_delta_days,
        score_breakdown=match.score_breakdown, is_active=match.is_active,
        matched_by_name=name(match.matched_by_id), matched_at=match.matched_at,
        unmatched_by_name=name(match.unmatched_by_id), unmatched_at=match.unmatched_at,
        note=match.note,
    )


def _transfer_side(transfer: ShopTransfer, record: ShopDailyRecord) -> TransferSide:
    return TransferSide(
        id=transfer.id, shop_id=record.shop_id,
        shop_name=record.shop.name if record.shop else None,
        business_date=record.business_date, bank_id=transfer.bank_id,
        bank_code=transfer.bank.code if transfer.bank else None,
        currency_code=transfer.currency_code, amount=transfer.amount,
        reference=transfer.reference, note=transfer.note, is_ignored=transfer.is_ignored,
    )


def _scoped_transfers(db: Session, user: User, **filters):
    stmt = (
        select(ShopTransfer, ShopDailyRecord)
        .join(ShopDailyRecord, ShopTransfer.daily_record_id == ShopDailyRecord.id)
        .where(ShopTransfer.deleted_at.is_(None), ShopDailyRecord.deleted_at.is_(None))
    )
    allowed = accessible_shop_ids(user)
    if allowed is not None:
        stmt = stmt.where(ShopDailyRecord.shop_id.in_(allowed or [-1]))
    if filters.get("shop_id"):
        assert_shop_access(user, filters["shop_id"])
        stmt = stmt.where(ShopDailyRecord.shop_id == filters["shop_id"])
    if filters.get("bank_id"):
        stmt = stmt.where(ShopTransfer.bank_id == filters["bank_id"])
    if filters.get("currency_code"):
        stmt = stmt.where(ShopTransfer.currency_code == filters["currency_code"].upper())
    if filters.get("date_from"):
        stmt = stmt.where(ShopDailyRecord.business_date >= filters["date_from"])
    if filters.get("date_to"):
        stmt = stmt.where(ShopDailyRecord.business_date <= filters["date_to"])
    return stmt.order_by(ShopDailyRecord.business_date.desc(), ShopTransfer.id)


@router.get("/reconciliation", response_model=Page[ReconciliationRow])
def reconciliation_view(
    shop_id: int | None = None,
    bank_id: int | None = None,
    currency_code: str | None = None,
    status: str | None = Query(None, description="MATCHED | POSSIBLE | UNMATCHED | IGNORED"),
    date_from: date | None = None,
    date_to: date | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(require("reconciliation.read")),
) -> Page[ReconciliationRow]:
    pairs = list(
        db.execute(
            _scoped_transfers(
                db, user, shop_id=shop_id, bank_id=bank_id, currency_code=currency_code,
                date_from=date_from, date_to=date_to,
            )
        )
    )
    transfer_ids = [t.id for t, _ in pairs]
    statuses = recon.transfer_statuses(db, transfer_ids)

    matches: dict[int, list[ReconciliationMatch]] = {}
    if transfer_ids:
        for match in db.scalars(
            select(ReconciliationMatch).where(
                ReconciliationMatch.shop_transfer_id.in_(transfer_ids)
            ).order_by(ReconciliationMatch.confidence.desc(), ReconciliationMatch.id)
        ):
            matches.setdefault(match.shop_transfer_id, []).append(match)

    txn_ids = {m.bank_transaction_id for group in matches.values() for m in group}
    txns = {
        t.id: t for t in db.scalars(
            select(BankTransaction).where(BankTransaction.id.in_(txn_ids or [-1]))
        )
    }
    txn_statuses = recon.transaction_statuses(db, list(txns))

    rows: list[ReconciliationRow] = []
    for transfer, record in pairs:
        state = "IGNORED" if transfer.is_ignored else statuses.get(transfer.id, {}).get(
            "status", "UNMATCHED"
        )
        group = matches.get(transfer.id, [])
        confirmed = next(
            (m for m in group if m.status == "CONFIRMED" and m.is_active), None
        )
        suggestions = [m for m in group if m.status == "SUGGESTED" and m.is_active]
        history = [m for m in group if not m.is_active]
        rows.append(
            ReconciliationRow(
                transfer=_transfer_side(transfer, record),
                status=state,
                confirmed=_match_out(confirmed, db) if confirmed else None,
                confirmed_transaction=(
                    txn_out(txns[confirmed.bank_transaction_id],
                            txn_statuses.get(confirmed.bank_transaction_id, {}))
                    if confirmed and confirmed.bank_transaction_id in txns else None
                ),
                suggestions=[_match_out(m, db) for m in suggestions],
                suggested_transactions=[
                    txn_out(txns[m.bank_transaction_id],
                            txn_statuses.get(m.bank_transaction_id, {}))
                    for m in suggestions if m.bank_transaction_id in txns
                ],
                history=[_match_out(m, db) for m in history],
            )
        )

    if status:
        rows = [r for r in rows if r.status == status.upper()]
    total = len(rows)
    start = (page - 1) * page_size
    return Page(items=rows[start:start + page_size], total=total, page=page, page_size=page_size)


@router.post("/reconciliation/run", response_model=dict)
def run_matching(
    payload: RunIn,
    db: Session = Depends(get_db),
    user: User = Depends(require("reconciliation.match")),
) -> dict:
    allowed = accessible_shop_ids(user)
    shop_ids = allowed
    if payload.shop_id:
        assert_shop_access(user, payload.shop_id)
        shop_ids = [payload.shop_id]
    settings = match_settings(db)
    summary = recon.run_batch(
        db, settings, shop_ids=shop_ids, date_from=payload.date_from,
        date_to=payload.date_to, bank_id=payload.bank_id, user=user,
    )
    audit.record(
        db, action=audit.Actions.AUTO_MATCH, module="reconciliation", user=user,
        summary=(f"Ran automatic matching: {summary['matched']} matched, "
                 f"{summary.get('possible', 0)} possible, {summary['unmatched']} unmatched"),
        new_values=summary,
    )
    db.commit()
    return summary


@router.post("/reconciliation/match", response_model=MatchOut)
def create_match(
    payload: MatchIn,
    db: Session = Depends(get_db),
    user: User = Depends(require("reconciliation.match")),
) -> MatchOut:
    transfer = db.get(ShopTransfer, payload.shop_transfer_id)
    if not transfer:
        raise NotFound("That shop payment does not exist.")
    record = db.get(ShopDailyRecord, transfer.daily_record_id)
    assert_shop_access(user, record.shop_id)
    match = recon.manual_match(
        db, payload.shop_transfer_id, payload.bank_transaction_id, user, payload.note
    )
    db.commit()
    db.refresh(match)
    return _match_out(match, db)


@router.post("/reconciliation/confirm", response_model=MatchOut)
def confirm_match(
    payload: ConfirmIn,
    db: Session = Depends(get_db),
    user: User = Depends(require("reconciliation.match")),
) -> MatchOut:
    match = recon.confirm_suggestion(db, payload.match_id, user, payload.note)
    db.commit()
    db.refresh(match)
    return _match_out(match, db)


@router.post("/reconciliation/unmatch", response_model=MatchOut)
def undo_match(
    payload: UnmatchIn,
    db: Session = Depends(get_db),
    user: User = Depends(require("reconciliation.unmatch")),
) -> MatchOut:
    match = recon.unmatch(db, payload.match_id, user, payload.reason)
    db.commit()
    db.refresh(match)
    return _match_out(match, db)


@router.get("/reconciliation/candidates/{transfer_id}", response_model=list[TransactionOut])
def candidates_for(
    transfer_id: int,
    include_matched: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(require("reconciliation.read")),
) -> list[TransactionOut]:
    """Every bank line a person could reasonably attach to this payment — used by
    the manual-match picker, which deliberately shows more than the engine would
    accept on its own."""
    transfer = db.get(ShopTransfer, transfer_id)
    if not transfer:
        raise NotFound("That shop payment does not exist.")
    record = db.get(ShopDailyRecord, transfer.daily_record_id)
    assert_shop_access(user, record.shop_id)

    settings = match_settings(db)
    from datetime import timedelta

    window = timedelta(days=max(settings.date_window_days, 7))
    stmt = select(BankTransaction).where(
        BankTransaction.currency_code == transfer.currency_code,
        BankTransaction.txn_date >= record.business_date - window,
        BankTransaction.txn_date <= record.business_date + window,
    ).order_by(BankTransaction.txn_date.desc())

    taken = set() if include_matched else recon.confirmed_transaction_ids(db)
    rows = [t for t in db.scalars(stmt) if t.id not in taken]
    statuses = recon.transaction_statuses(db, [t.id for t in rows])
    return [txn_out(t, statuses.get(t.id, {})) for t in rows]


@router.get("/reconciliation/unmatched", response_model=UnmatchedSummary)
def unmatched(
    shop_id: int | None = None,
    bank_id: int | None = None,
    currency_code: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require("reconciliation.read")),
) -> UnmatchedSummary:
    """The two exception lists: money the shops say they banked that the bank has
    no record of, and money the bank received that no shop claimed."""
    pairs = list(
        db.execute(
            _scoped_transfers(
                db, user, shop_id=shop_id, bank_id=bank_id, currency_code=currency_code,
                date_from=date_from, date_to=date_to,
            )
        )
    )
    statuses = recon.transfer_statuses(db, [t.id for t, _ in pairs])
    open_transfers = [
        _transfer_side(t, r) for t, r in pairs
        if not t.is_ignored and statuses.get(t.id, {}).get("status") != "MATCHED"
    ]

    stmt = select(BankTransaction).where(
        BankTransaction.direction == "CREDIT", BankTransaction.is_ignored.is_(False)
    )
    if bank_id:
        stmt = stmt.where(BankTransaction.bank_id == bank_id)
    if currency_code:
        stmt = stmt.where(BankTransaction.currency_code == currency_code.upper())
    if date_from:
        stmt = stmt.where(BankTransaction.txn_date >= date_from)
    if date_to:
        stmt = stmt.where(BankTransaction.txn_date <= date_to)
    confirmed = recon.confirmed_transaction_ids(db)
    rows = [t for t in db.scalars(stmt.order_by(BankTransaction.txn_date.desc()))
            if t.id not in confirmed]
    txn_statuses = recon.transaction_statuses(db, [t.id for t in rows])

    totals = {
        "shop_payments": {
            "count": len(open_transfers),
            "USD": str(sum((t.amount for t in open_transfers if t.currency_code == "USD"),
                           Decimal("0.00"))),
            "NIO": str(sum((t.amount for t in open_transfers if t.currency_code == "NIO"),
                           Decimal("0.00"))),
        },
        "bank_transactions": {
            "count": len(rows),
            "USD": str(sum((t.amount for t in rows if t.currency_code == "USD"),
                           Decimal("0.00"))),
            "NIO": str(sum((t.amount for t in rows if t.currency_code == "NIO"),
                           Decimal("0.00"))),
        },
    }
    return UnmatchedSummary(
        shop_payments=open_transfers,
        bank_transactions=[txn_out(t, txn_statuses.get(t.id, {})) for t in rows],
        totals=totals,
    )


@router.post("/reconciliation/transfers/{transfer_id}/ignore", response_model=Message)
def ignore_transfer(
    transfer_id: int,
    reason: str = "",
    undo: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(require("reconciliation.match")),
) -> Message:
    transfer = db.get(ShopTransfer, transfer_id)
    if not transfer or transfer.deleted_at:
        raise NotFound("That shop payment does not exist.")
    record = db.get(ShopDailyRecord, transfer.daily_record_id)
    assert_shop_access(user, record.shop_id)
    transfer.is_ignored = not undo
    transfer.ignored_reason = None if undo else (reason or None)
    audit.record(
        db, action=audit.Actions.IGNORE_ITEM, module="reconciliation", user=user,
        record_type="shop_transfer", record_id=transfer.id,
        summary=("Stopped ignoring" if undo else "Ignored")
                + f" shop payment {transfer.currency_code} {transfer.amount}"
                + (f" — {reason}" if reason and not undo else ""),
    )
    db.commit()
    return Message(message="Updated.")
