from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.deps import require
from app.db.session import get_db
from app.models import (
    Bank, BankTransaction, ReconciliationMatch, Shop, ShopDailyRecord, ShopTransfer, User,
)
from app.services import reconciliation as recon

router = APIRouter(tags=["dashboard"])
ZERO = Decimal("0.00")


def _pair(rows) -> dict[str, str]:
    out = {"USD": ZERO, "NIO": ZERO}
    for currency, total in rows:
        if currency in out:
            out[currency] = total or ZERO
    return {k: str(v.quantize(Decimal("0.01"))) for k, v in out.items()}


@router.get("/dashboard")
def dashboard(
    date_from: date | None = None,
    date_to: date | None = None,
    shop_id: int | None = None,
    bank_id: int | None = None,
    db: Session = Depends(get_db),
    # The company-wide view is deliberately gated: a shop user must not be able
    # to read another shop's takings by loading the dashboard.
    user: User = Depends(require("dashboard.view")),
) -> dict:
    today = date.today()
    start = date_from or today
    end = date_to or today

    record_filter = [
        ShopDailyRecord.deleted_at.is_(None),
        ShopDailyRecord.business_date >= start,
        ShopDailyRecord.business_date <= end,
    ]
    if shop_id:
        record_filter.append(ShopDailyRecord.shop_id == shop_id)

    sales = db.execute(
        select(
            func.coalesce(func.sum(ShopDailyRecord.total_sales_usd), 0),
            func.coalesce(func.sum(ShopDailyRecord.total_sales_nio), 0),
            func.coalesce(func.sum(ShopDailyRecord.bale_count), 0),
            func.coalesce(func.sum(ShopDailyRecord.invoice_count), 0),
            func.count(ShopDailyRecord.id),
        ).where(*record_filter)
    ).one()

    transfer_stmt = (
        select(ShopTransfer.currency_code, func.sum(ShopTransfer.amount))
        .join(ShopDailyRecord, ShopTransfer.daily_record_id == ShopDailyRecord.id)
        .where(*record_filter, ShopTransfer.deleted_at.is_(None))
        .group_by(ShopTransfer.currency_code)
    )
    if bank_id:
        transfer_stmt = transfer_stmt.where(ShopTransfer.bank_id == bank_id)
    transfers = _pair(db.execute(transfer_stmt).all())

    bank_stmt = (
        select(BankTransaction.currency_code, func.sum(BankTransaction.amount))
        .where(
            BankTransaction.direction == "CREDIT",
            BankTransaction.is_ignored.is_(False),
            BankTransaction.txn_date >= start,
            BankTransaction.txn_date <= end,
        )
        .group_by(BankTransaction.currency_code)
    )
    if bank_id:
        bank_stmt = bank_stmt.where(BankTransaction.bank_id == bank_id)
    received = _pair(db.execute(bank_stmt).all())

    # Reconciliation state for the transfers in range.
    pairs = list(
        db.execute(
            select(ShopTransfer, ShopDailyRecord)
            .join(ShopDailyRecord, ShopTransfer.daily_record_id == ShopDailyRecord.id)
            .where(*record_filter, ShopTransfer.deleted_at.is_(None))
        )
    )
    statuses = recon.transfer_statuses(db, [t.id for t, _ in pairs])
    counts = {"MATCHED": 0, "POSSIBLE": 0, "UNMATCHED": 0, "IGNORED": 0}
    amounts = {k: {"USD": ZERO, "NIO": ZERO} for k in counts}
    for transfer, _record in pairs:
        state = "IGNORED" if transfer.is_ignored else statuses.get(
            transfer.id, {}
        ).get("status", "UNMATCHED")
        counts[state] += 1
        amounts[state][transfer.currency_code] += transfer.amount

    # Per-shop and per-bank breakdowns, each split by currency.
    shop_rows = db.execute(
        select(
            Shop.id, Shop.name, Shop.code,
            func.coalesce(func.sum(ShopDailyRecord.total_sales_usd), 0),
            func.coalesce(func.sum(ShopDailyRecord.total_sales_nio), 0),
            func.count(ShopDailyRecord.id),
        )
        .join(ShopDailyRecord, ShopDailyRecord.shop_id == Shop.id, isouter=True)
        .where(
            ShopDailyRecord.deleted_at.is_(None),
            ShopDailyRecord.business_date >= start,
            ShopDailyRecord.business_date <= end,
        )
        .group_by(Shop.id, Shop.name, Shop.code)
        .order_by(Shop.code)
    ).all()

    bank_rows = db.execute(
        select(
            Bank.id, Bank.code, Bank.name, ShopTransfer.currency_code,
            func.sum(ShopTransfer.amount), func.count(ShopTransfer.id),
        )
        .join(ShopTransfer, ShopTransfer.bank_id == Bank.id)
        .join(ShopDailyRecord, ShopTransfer.daily_record_id == ShopDailyRecord.id)
        .where(*record_filter, ShopTransfer.deleted_at.is_(None))
        .group_by(Bank.id, Bank.code, Bank.name, ShopTransfer.currency_code)
        .order_by(Bank.code)
    ).all()

    banks: dict[int, dict] = {}
    for bid, code, name, currency, total, count in bank_rows:
        entry = banks.setdefault(
            bid, {"bank_id": bid, "code": code, "name": name,
                  "USD": "0.00", "NIO": "0.00", "transfer_count": 0}
        )
        entry[currency] = str((total or ZERO).quantize(Decimal("0.01")))
        entry["transfer_count"] += count

    # One point per day across exactly the range that is being shown, so the
    # chart can never disagree with the totals above it.
    trend = db.execute(
        select(
            ShopDailyRecord.business_date,
            func.coalesce(func.sum(ShopDailyRecord.total_sales_usd), 0),
            func.coalesce(func.sum(ShopDailyRecord.total_sales_nio), 0),
        )
        .where(
            ShopDailyRecord.deleted_at.is_(None),
            ShopDailyRecord.business_date >= start,
            ShopDailyRecord.business_date <= end,
        )
        .group_by(ShopDailyRecord.business_date)
        .order_by(ShopDailyRecord.business_date)
    ).all()

    return {
        "range": {"from": start.isoformat(), "to": end.isoformat()},
        "sales": {
            "USD": str(Decimal(sales[0]).quantize(Decimal("0.01"))),
            "NIO": str(Decimal(sales[1]).quantize(Decimal("0.01"))),
            "bales": int(sales[2]), "invoices": int(sales[3]), "records": int(sales[4]),
        },
        "shop_transfers": transfers,
        "bank_received": received,
        "reconciliation": {
            "counts": counts,
            "amounts": {
                state: {c: str(v.quantize(Decimal("0.01"))) for c, v in by_currency.items()}
                for state, by_currency in amounts.items()
            },
        },
        "shops": [
            {"shop_id": sid, "name": name, "code": code,
             "USD": str(Decimal(usd).quantize(Decimal("0.01"))),
             "NIO": str(Decimal(nio).quantize(Decimal("0.01"))),
             "records": int(rec)}
            for sid, name, code, usd, nio, rec in shop_rows
        ],
        "banks": list(banks.values()),
        "trend": [
            {"date": d.isoformat(),
             "USD": str(Decimal(usd).quantize(Decimal("0.01"))),
             "NIO": str(Decimal(nio).quantize(Decimal("0.01")))}
            for d, usd, nio in trend
        ],
    }
