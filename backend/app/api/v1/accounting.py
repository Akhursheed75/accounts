from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.deps import accessible_shop_ids, assert_shop_access, require
from app.core.errors import Conflict, Forbidden, NotFound, ValidationFailed
from app.db.session import get_db
from app.models import (
    BaleRecord, BaleType, Bank, BankAccount, Currency, Expense, Shop, ShopDailyRecord,
    ShopTransfer, User,
)
from app.schemas.accounting import (
    BaleTypeOut, DailyRecordIn, DailyRecordOut, DailyRecordRow, DailyRecordUpdate,
    ExpenseOut, TransferOut,
)
from app.schemas.common import Message, Page
from app.services import accounting as calc
from app.services import audit
from app.services import reconciliation as recon
from app.services.settings_store import match_settings, system_settings

router = APIRouter(tags=["accounting"])


# --------------------------------------------------------------- serialising
def _transfer_out(transfer: ShopTransfer, status: dict) -> TransferOut:
    return TransferOut(
        id=transfer.id, bank_id=transfer.bank_id,
        bank_code=transfer.bank.code if transfer.bank else None,
        bank_name=transfer.bank.name if transfer.bank else None,
        bank_account_id=transfer.bank_account_id,
        currency_code=transfer.currency_code, amount=transfer.amount,
        reference=transfer.reference, deposit_time=transfer.deposit_time,
        note=transfer.note, is_ignored=transfer.is_ignored,
        ignored_reason=transfer.ignored_reason,
        match_status="IGNORED" if transfer.is_ignored else status.get("status", "UNMATCHED"),
        matched_transaction_id=status.get("transaction_id"),
        suggestion_count=status.get("suggestions", 0),
    )


def _record_out(db: Session, record: ShopDailyRecord) -> DailyRecordOut:
    live = [t for t in record.transfers if t.deleted_at is None]
    statuses = recon.transfer_statuses(db, [t.id for t in live])
    components = system_settings(db).balance_components
    return DailyRecordOut(
        id=record.id, shop_id=record.shop_id,
        shop_name=record.shop.name if record.shop else None,
        shop_code=record.shop.code if record.shop else None,
        business_date=record.business_date, status=record.status,
        bale_count=record.bale_count, invoice_count=record.invoice_count,
        total_sales_usd=record.total_sales_usd, total_sales_nio=record.total_sales_nio,
        delivery_usd=record.delivery_usd, delivery_nio=record.delivery_nio,
        commercial_invoice_usd=record.commercial_invoice_usd,
        commercial_invoice_nio=record.commercial_invoice_nio,
        credit_usd=record.credit_usd, credit_nio=record.credit_nio,
        opening_balance_usd=record.opening_balance_usd,
        opening_balance_nio=record.opening_balance_nio,
        closing_balance_usd=record.closing_balance_usd,
        closing_balance_nio=record.closing_balance_nio,
        closing_balance_source=record.closing_balance_source,
        observations=record.observations,
        created_at=record.created_at, updated_at=record.updated_at,
        submitted_at=record.submitted_at, locked_at=record.locked_at,
        is_demo=record.is_demo,
        transfers=[_transfer_out(t, statuses.get(t.id, {})) for t in live],
        expenses=[ExpenseOut.model_validate(e) for e in record.expenses],
        bale_records=[
            {
                "id": b.id, "bale_type_id": b.bale_type_id,
                "bale_type_code": b.bale_type.code if b.bale_type else None,
                "bale_type_name": b.bale_type.name if b.bale_type else None,
                "opening_qty": b.opening_qty, "received_qty": b.received_qty,
                "sold_qty": b.sold_qty, "closing_qty": b.closing_qty,
            }
            for b in record.bale_records
        ],
        transfer_totals=calc.transfer_totals(record),
        expense_totals=calc.expense_totals(record),
        balance=calc.balance_breakdown(record, components),
    )


# ------------------------------------------------------------------ writing
def _validate_children(db: Session, payload: DailyRecordIn | DailyRecordUpdate) -> None:
    currencies = {c.code for c in db.scalars(select(Currency))}
    bank_ids = {b.id for b in db.scalars(select(Bank))}
    for transfer in payload.transfers:
        if transfer.bank_id not in bank_ids:
            raise NotFound(f"Bank {transfer.bank_id} does not exist.")
        if transfer.currency_code not in currencies:
            raise ValidationFailed(f"Currency '{transfer.currency_code}' is not configured.")
        if transfer.bank_account_id:
            account = db.get(BankAccount, transfer.bank_account_id)
            if not account:
                raise NotFound(f"Bank account {transfer.bank_account_id} does not exist.")
            if account.bank_id != transfer.bank_id:
                raise ValidationFailed("That account does not belong to the selected bank.")
            if account.currency_code != transfer.currency_code:
                raise ValidationFailed(
                    f"The account {account.label} is in {account.currency_code}, but the "
                    f"transfer is in {transfer.currency_code}."
                )
    for expense in payload.expenses:
        if expense.currency_code not in currencies:
            raise ValidationFailed(f"Currency '{expense.currency_code}' is not configured.")
    type_ids = {t.id for t in db.scalars(select(BaleType))}
    for bale in payload.bale_records:
        if bale.bale_type_id not in type_ids:
            raise NotFound(f"Bale type {bale.bale_type_id} does not exist.")


def _apply(db: Session, record: ShopDailyRecord, payload, *, creating: bool) -> None:
    scalar_fields = [
        "bale_count", "invoice_count", "total_sales_usd", "total_sales_nio",
        "delivery_usd", "delivery_nio", "commercial_invoice_usd", "commercial_invoice_nio",
        "credit_usd", "credit_nio", "opening_balance_usd", "opening_balance_nio",
        "observations", "status",
    ]
    data = payload.model_dump(exclude_unset=not creating)
    for field in scalar_fields:
        if field in data and data[field] is not None:
            setattr(record, field, data[field])

    if payload.closing_balance_source == "MANUAL":
        record.closing_balance_source = "MANUAL"
        if payload.closing_balance_usd is not None:
            record.closing_balance_usd = payload.closing_balance_usd
        if payload.closing_balance_nio is not None:
            record.closing_balance_nio = payload.closing_balance_nio
    else:
        record.closing_balance_source = "COMPUTED"

    if "transfers" in data:
        _sync_transfers(db, record, payload)
    if "expenses" in data:
        _sync_expenses(db, record, payload)
    if "bale_records" in data:
        _sync_bales(db, record, payload)


def _sync_transfers(db: Session, record: ShopDailyRecord, payload) -> None:
    existing = {t.id: t for t in record.transfers if t.deleted_at is None}
    seen: set[int] = set()
    for item in payload.transfers:
        if item.id and item.id in existing:
            transfer = existing[item.id]
            for field, value in item.model_dump(exclude={"id"}).items():
                setattr(transfer, field, value)
            seen.add(item.id)
        else:
            record.transfers.append(
                ShopTransfer(**item.model_dump(exclude={"id"}))
            )
    for tid, transfer in existing.items():
        if tid not in seen:
            # Soft delete: a payment that was once reconciled must stay traceable.
            transfer.deleted_at = datetime.now(UTC)


def _sync_expenses(db: Session, record: ShopDailyRecord, payload) -> None:
    existing = {e.id: e for e in record.expenses}
    seen: set[int] = set()
    for item in payload.expenses:
        if item.id and item.id in existing:
            expense = existing[item.id]
            for field, value in item.model_dump(exclude={"id"}).items():
                setattr(expense, field, value)
            seen.add(item.id)
        else:
            record.expenses.append(Expense(**item.model_dump(exclude={"id"})))
    for eid, expense in existing.items():
        if eid not in seen:
            db.delete(expense)


def _sync_bales(db: Session, record: ShopDailyRecord, payload) -> None:
    existing = {b.id: b for b in record.bale_records}
    seen: set[int] = set()
    for item in payload.bale_records:
        if item.id and item.id in existing:
            bale = existing[item.id]
            for field, value in item.model_dump(exclude={"id"}).items():
                setattr(bale, field, value)
            seen.add(item.id)
        else:
            record.bale_records.append(BaleRecord(**item.model_dump(exclude={"id"})))
    for bid, bale in existing.items():
        if bid not in seen:
            db.delete(bale)


def _snapshot(record: ShopDailyRecord) -> dict:
    return {
        "business_date": record.business_date,
        "status": record.status,
        "bale_count": record.bale_count,
        "invoice_count": record.invoice_count,
        "total_sales_usd": record.total_sales_usd,
        "total_sales_nio": record.total_sales_nio,
        "opening_balance_usd": record.opening_balance_usd,
        "opening_balance_nio": record.opening_balance_nio,
        "closing_balance_usd": record.closing_balance_usd,
        "closing_balance_nio": record.closing_balance_nio,
        "observations": record.observations,
        "transfers": sorted(
            f"{t.bank_id}:{t.currency_code}:{t.amount}"
            for t in record.transfers if t.deleted_at is None
        ),
        "expenses": sorted(f"{e.category}:{e.currency_code}:{e.amount}" for e in record.expenses),
    }


# ----------------------------------------------------------------- endpoints
@router.get("/accounting/bale-types", response_model=list[BaleTypeOut])
def bale_types(
    db: Session = Depends(get_db), user: User = Depends(require("accounting.read"))
) -> list[BaleTypeOut]:
    return list(
        db.scalars(select(BaleType).where(BaleType.is_active.is_(True))
                   .order_by(BaleType.sort_order, BaleType.code))
    )


@router.get("/accounting/daily", response_model=Page[DailyRecordRow])
def list_records(
    shop_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    status: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
    user: User = Depends(require("accounting.read")),
) -> Page[DailyRecordRow]:
    stmt = select(ShopDailyRecord).where(ShopDailyRecord.deleted_at.is_(None))
    allowed = accessible_shop_ids(user)
    if allowed is not None:
        stmt = stmt.where(ShopDailyRecord.shop_id.in_(allowed or [-1]))
    if shop_id:
        assert_shop_access(user, shop_id)
        stmt = stmt.where(ShopDailyRecord.shop_id == shop_id)
    if date_from:
        stmt = stmt.where(ShopDailyRecord.business_date >= date_from)
    if date_to:
        stmt = stmt.where(ShopDailyRecord.business_date <= date_to)
    if status:
        stmt = stmt.where(ShopDailyRecord.status == status.upper())

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = list(
        db.scalars(
            stmt.order_by(ShopDailyRecord.business_date.desc(), ShopDailyRecord.shop_id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )

    transfer_ids = [t.id for r in rows for t in r.transfers if t.deleted_at is None]
    statuses = recon.transfer_statuses(db, transfer_ids)

    items = []
    for record in rows:
        live = [t for t in record.transfers if t.deleted_at is None]
        totals = calc.transfer_totals(record)
        counts = {"MATCHED": 0, "POSSIBLE": 0, "UNMATCHED": 0}
        for transfer in live:
            if transfer.is_ignored:
                continue
            state = statuses.get(transfer.id, {}).get("status", "UNMATCHED")
            counts[state] = counts.get(state, 0) + 1
        items.append(
            DailyRecordRow(
                id=record.id, shop_id=record.shop_id,
                shop_name=record.shop.name if record.shop else None,
                business_date=record.business_date, status=record.status,
                bale_count=record.bale_count, invoice_count=record.invoice_count,
                total_sales_usd=record.total_sales_usd,
                total_sales_nio=record.total_sales_nio,
                transfer_total_usd=totals["USD"], transfer_total_nio=totals["NIO"],
                matched_count=counts["MATCHED"], possible_count=counts["POSSIBLE"],
                unmatched_count=counts["UNMATCHED"],
            )
        )
    return Page(items=items, total=total, page=page, page_size=page_size)


@router.get("/accounting/daily/{record_id}", response_model=DailyRecordOut)
def get_record(
    record_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require("accounting.read")),
) -> DailyRecordOut:
    record = db.get(ShopDailyRecord, record_id)
    if not record or record.deleted_at:
        raise NotFound("That accounting record does not exist.")
    assert_shop_access(user, record.shop_id)
    return _record_out(db, record)


@router.post("/accounting/daily", response_model=DailyRecordOut, status_code=201)
def create_record(
    payload: DailyRecordIn,
    run_matching: bool = True,
    db: Session = Depends(get_db),
    user: User = Depends(require("accounting.create")),
) -> DailyRecordOut:
    assert_shop_access(user, payload.shop_id)
    if not db.get(Shop, payload.shop_id):
        raise NotFound("That shop does not exist.")
    duplicate = db.scalar(
        select(ShopDailyRecord).where(
            ShopDailyRecord.shop_id == payload.shop_id,
            ShopDailyRecord.business_date == payload.business_date,
            ShopDailyRecord.deleted_at.is_(None),
        )
    )
    if duplicate:
        raise Conflict(
            f"A record for this shop on {payload.business_date} already exists. "
            f"Open record #{duplicate.id} to edit it."
        )
    _validate_children(db, payload)

    record = ShopDailyRecord(
        shop_id=payload.shop_id,
        business_date=payload.business_date,
        created_by_id=user.id,
        updated_by_id=user.id,
    )
    db.add(record)
    _apply(db, record, payload, creating=True)
    if payload.status == "SUBMITTED":
        record.submitted_at = datetime.now(UTC)
    db.flush()
    calc.apply_computed_closing(record, system_settings(db).balance_components)

    audit.record(
        db, action=audit.Actions.CREATE_ACCOUNTING, module="accounting", user=user,
        record_type="shop_daily_record", record_id=record.id,
        summary=f"Created the sheet for {record.shop.name if record.shop else record.shop_id} "
                f"on {record.business_date}",
        new_values=_snapshot(record),
    )
    db.flush()
    if run_matching:
        settings = match_settings(db)
        for transfer in record.transfers:
            recon.run_for_transfer(db, transfer, settings, user=user)
    db.commit()
    db.refresh(record)
    return _record_out(db, record)


@router.put("/accounting/daily/{record_id}", response_model=DailyRecordOut)
def update_record(
    record_id: int,
    payload: DailyRecordUpdate,
    run_matching: bool = True,
    db: Session = Depends(get_db),
    user: User = Depends(require("accounting.update")),
) -> DailyRecordOut:
    record = db.get(ShopDailyRecord, record_id)
    if not record or record.deleted_at:
        raise NotFound("That accounting record does not exist.")
    assert_shop_access(user, record.shop_id)
    if record.status == "LOCKED" and not user.has_permission("accounting.lock"):
        raise Forbidden("This record is locked. An administrator must unlock it first.")
    _validate_children(db, payload)

    before = _snapshot(record)
    _apply(db, record, payload, creating=False)
    record.updated_by_id = user.id
    if payload.status == "SUBMITTED" and record.submitted_at is None:
        record.submitted_at = datetime.now(UTC)
    db.flush()
    calc.apply_computed_closing(record, system_settings(db).balance_components)
    db.flush()
    after = _snapshot(record)
    old, new = audit.diff(before, after)
    audit.record(
        db, action=audit.Actions.EDIT_ACCOUNTING, module="accounting", user=user,
        record_type="shop_daily_record", record_id=record.id,
        summary=f"Edited the sheet for {record.business_date}",
        old_values=old, new_values=new,
    )
    if run_matching:
        settings = match_settings(db)
        for transfer in record.transfers:
            if transfer.deleted_at is None:
                recon.run_for_transfer(db, transfer, settings, user=user)
    db.commit()
    db.refresh(record)
    return _record_out(db, record)


@router.post("/accounting/daily/{record_id}/lock", response_model=DailyRecordOut)
def lock_record(
    record_id: int,
    unlock: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(require("accounting.lock")),
) -> DailyRecordOut:
    record = db.get(ShopDailyRecord, record_id)
    if not record or record.deleted_at:
        raise NotFound("That accounting record does not exist.")
    record.status = "SUBMITTED" if unlock else "LOCKED"
    record.locked_at = None if unlock else datetime.now(UTC)
    audit.record(
        db, action=audit.Actions.LOCK_ACCOUNTING, module="accounting", user=user,
        record_type="shop_daily_record", record_id=record.id,
        summary=("Unlocked" if unlock else "Locked") + f" the sheet for {record.business_date}",
    )
    db.commit()
    db.refresh(record)
    return _record_out(db, record)


@router.delete("/accounting/daily/{record_id}", response_model=Message)
def delete_record(
    record_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require("accounting.delete")),
) -> Message:
    record = db.get(ShopDailyRecord, record_id)
    if not record or record.deleted_at:
        raise NotFound("That accounting record does not exist.")
    assert_shop_access(user, record.shop_id)
    # Financial history is archived, never destroyed.
    record.deleted_at = datetime.now(UTC)
    for transfer in record.transfers:
        transfer.deleted_at = transfer.deleted_at or datetime.now(UTC)
    audit.record(
        db, action=audit.Actions.DELETE_ACCOUNTING, module="accounting", user=user,
        record_type="shop_daily_record", record_id=record.id,
        summary=f"Archived the sheet for {record.business_date}",
        old_values=_snapshot(record),
    )
    db.commit()
    return Message(message="Record archived. It no longer appears in reports but is kept for audit.")
