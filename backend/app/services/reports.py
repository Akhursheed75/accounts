"""Report definitions.

Each report returns the same shape — title, columns, rows, per-currency totals —
so the Excel and PDF exporters stay generic and a new report is a query plus a
column list. Totals are always split by currency; there is no line anywhere in
this file that adds dollars to cordobas."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    Bank, BankTransaction, ReconciliationMatch, Shop, ShopDailyRecord, ShopTransfer,
)
from app.services import reconciliation as recon

ZERO = Decimal("0.00")


@dataclass
class Column:
    key: str
    label: str
    kind: str = "text"       # text | money | number | date | status
    currency_key: str | None = None


@dataclass
class ReportResult:
    key: str
    title: str
    description: str
    columns: list[Column]
    rows: list[dict]
    totals: dict = field(default_factory=dict)
    filters: dict = field(default_factory=dict)
    generated_at: str = ""


@dataclass
class Filters:
    date_from: date | None = None
    date_to: date | None = None
    shop_ids: list[int] | None = None
    shop_id: int | None = None
    bank_id: int | None = None
    currency_code: str | None = None
    match_status: str | None = None
    city_id: int | None = None


def _record_scope(stmt, f: Filters):
    stmt = stmt.where(ShopDailyRecord.deleted_at.is_(None))
    if f.shop_ids is not None:
        stmt = stmt.where(ShopDailyRecord.shop_id.in_(f.shop_ids or [-1]))
    if f.shop_id:
        stmt = stmt.where(ShopDailyRecord.shop_id == f.shop_id)
    if f.date_from:
        stmt = stmt.where(ShopDailyRecord.business_date >= f.date_from)
    if f.date_to:
        stmt = stmt.where(ShopDailyRecord.business_date <= f.date_to)
    return stmt


def _money(value) -> str:
    return str(Decimal(value or 0).quantize(Decimal("0.01")))


def _currency_totals(rows: list[dict], amount_key: str, currency_key: str = "currency") -> dict:
    totals: dict[str, Decimal] = {}
    for row in rows:
        code = row.get(currency_key) or "?"
        totals[code] = totals.get(code, ZERO) + Decimal(row.get(amount_key) or 0)
    return {k: _money(v) for k, v in totals.items()}


# --------------------------------------------------------------------------
def daily_accounting(db: Session, f: Filters) -> ReportResult:
    stmt = _record_scope(
        select(ShopDailyRecord).join(Shop, Shop.id == ShopDailyRecord.shop_id), f
    ).order_by(ShopDailyRecord.business_date.desc(), Shop.code)
    rows = []
    for record in db.scalars(stmt):
        transfers = {"USD": ZERO, "NIO": ZERO}
        for transfer in record.transfers:
            if transfer.deleted_at is None:
                transfers[transfer.currency_code] += transfer.amount
        expenses = {"USD": ZERO, "NIO": ZERO}
        for expense in record.expenses:
            expenses[expense.currency_code] += expense.amount
        rows.append(
            {
                "date": record.business_date.isoformat(),
                "shop": record.shop.name if record.shop else "",
                "status": record.status,
                "bales": record.bale_count,
                "invoices": record.invoice_count,
                "sales_usd": _money(record.total_sales_usd),
                "sales_nio": _money(record.total_sales_nio),
                "transfers_usd": _money(transfers["USD"]),
                "transfers_nio": _money(transfers["NIO"]),
                "expenses_usd": _money(expenses["USD"]),
                "expenses_nio": _money(expenses["NIO"]),
                "closing_usd": _money(record.closing_balance_usd),
                "closing_nio": _money(record.closing_balance_nio),
            }
        )
    columns = [
        Column("date", "Date", "date"), Column("shop", "Shop"),
        Column("status", "Status", "status"),
        Column("bales", "Bales", "number"), Column("invoices", "Invoices", "number"),
        Column("sales_usd", "Sales USD", "money"), Column("sales_nio", "Sales C$", "money"),
        Column("transfers_usd", "Banked USD", "money"),
        Column("transfers_nio", "Banked C$", "money"),
        Column("expenses_usd", "Expenses USD", "money"),
        Column("expenses_nio", "Expenses C$", "money"),
        Column("closing_usd", "Closing USD", "money"),
        Column("closing_nio", "Closing C$", "money"),
    ]
    totals = {
        "USD": {
            "sales": _money(sum(Decimal(r["sales_usd"]) for r in rows)),
            "banked": _money(sum(Decimal(r["transfers_usd"]) for r in rows)),
            "expenses": _money(sum(Decimal(r["expenses_usd"]) for r in rows)),
        },
        "NIO": {
            "sales": _money(sum(Decimal(r["sales_nio"]) for r in rows)),
            "banked": _money(sum(Decimal(r["transfers_nio"]) for r in rows)),
            "expenses": _money(sum(Decimal(r["expenses_nio"]) for r in rows)),
        },
    }
    return ReportResult(
        "daily-accounting", "Daily accounting",
        "One row per shop per day, with sales, deposits and expenses kept separate by currency.",
        columns, rows, totals,
    )


def monthly_accounting(db: Session, f: Filters) -> ReportResult:
    month = func.to_char(ShopDailyRecord.business_date, "YYYY-MM")
    stmt = _record_scope(
        select(
            month.label("month"), Shop.name.label("shop"),
            func.sum(ShopDailyRecord.total_sales_usd),
            func.sum(ShopDailyRecord.total_sales_nio),
            func.sum(ShopDailyRecord.bale_count),
            func.sum(ShopDailyRecord.invoice_count),
            func.count(ShopDailyRecord.id),
        ).join(Shop, Shop.id == ShopDailyRecord.shop_id),
        f,
    ).group_by(month, Shop.name).order_by(month.desc(), Shop.name)
    rows = [
        {
            "month": m, "shop": shop, "sales_usd": _money(usd), "sales_nio": _money(nio),
            "bales": int(bales or 0), "invoices": int(invoices or 0), "days": int(days or 0),
        }
        for m, shop, usd, nio, bales, invoices, days in db.execute(stmt)
    ]
    columns = [
        Column("month", "Month"), Column("shop", "Shop"),
        Column("days", "Days recorded", "number"),
        Column("bales", "Bales", "number"), Column("invoices", "Invoices", "number"),
        Column("sales_usd", "Sales USD", "money"), Column("sales_nio", "Sales C$", "money"),
    ]
    totals = {
        "USD": {"sales": _money(sum(Decimal(r["sales_usd"]) for r in rows))},
        "NIO": {"sales": _money(sum(Decimal(r["sales_nio"]) for r in rows))},
    }
    return ReportResult(
        "monthly-accounting", "Monthly accounting",
        "Sales by shop and month.", columns, rows, totals,
    )


def shop_sales(db: Session, f: Filters) -> ReportResult:
    stmt = _record_scope(
        select(
            Shop.code, Shop.name,
            func.sum(ShopDailyRecord.total_sales_usd),
            func.sum(ShopDailyRecord.total_sales_nio),
            func.sum(ShopDailyRecord.bale_count),
            func.count(ShopDailyRecord.id),
        ).join(Shop, Shop.id == ShopDailyRecord.shop_id),
        f,
    ).group_by(Shop.code, Shop.name).order_by(Shop.code)
    rows = [
        {"code": code, "shop": name, "sales_usd": _money(usd), "sales_nio": _money(nio),
         "bales": int(bales or 0), "days": int(days or 0)}
        for code, name, usd, nio, bales, days in db.execute(stmt)
    ]
    columns = [
        Column("code", "Code"), Column("shop", "Shop"),
        Column("days", "Days", "number"), Column("bales", "Bales", "number"),
        Column("sales_usd", "Sales USD", "money"), Column("sales_nio", "Sales C$", "money"),
    ]
    totals = {
        "USD": {"sales": _money(sum(Decimal(r["sales_usd"]) for r in rows))},
        "NIO": {"sales": _money(sum(Decimal(r["sales_nio"]) for r in rows))},
    }
    return ReportResult("shop-sales", "Shop sales", "Totals per shop for the period.",
                        columns, rows, totals)


def _transaction_rows(db: Session, f: Filters, *, currency: str | None = None) -> list[dict]:
    stmt = select(BankTransaction).join(Bank, Bank.id == BankTransaction.bank_id)
    if f.date_from:
        stmt = stmt.where(BankTransaction.txn_date >= f.date_from)
    if f.date_to:
        stmt = stmt.where(BankTransaction.txn_date <= f.date_to)
    if f.bank_id:
        stmt = stmt.where(BankTransaction.bank_id == f.bank_id)
    code = currency or f.currency_code
    if code:
        stmt = stmt.where(BankTransaction.currency_code == code.upper())
    rows = list(db.scalars(stmt.order_by(BankTransaction.txn_date.desc(), BankTransaction.id)))
    statuses = recon.transaction_statuses(db, [t.id for t in rows])
    return [
        {
            "date": t.txn_date.isoformat(),
            "bank": t.bank.code if t.bank else "",
            "description": t.description,
            "reference": t.reference or t.external_id or "",
            "debit": _money(t.debit), "credit": _money(t.credit),
            "amount": _money(t.amount), "currency": t.currency_code,
            "direction": t.direction,
            "status": "IGNORED" if t.is_ignored else statuses.get(t.id, {}).get(
                "status", "UNMATCHED"
            ),
            "confidence": t.extraction_confidence,
        }
        for t in rows
    ]


TXN_COLUMNS = [
    Column("date", "Date", "date"), Column("bank", "Bank"),
    Column("description", "Description"), Column("reference", "Reference"),
    Column("debit", "Debit", "money"), Column("credit", "Credit", "money"),
    Column("currency", "Currency"), Column("status", "Match status", "status"),
]


def bank_transactions(db: Session, f: Filters) -> ReportResult:
    rows = _transaction_rows(db, f)
    return ReportResult(
        "bank-transactions", "Bank transactions",
        "Every line extracted from the uploaded statements.",
        TXN_COLUMNS, rows, {"received": _currency_totals(
            [r for r in rows if r["direction"] == "CREDIT"], "amount"
        )},
    )


def usd_transactions(db: Session, f: Filters) -> ReportResult:
    rows = _transaction_rows(db, f, currency="USD")
    return ReportResult(
        "usd-transactions", "USD transactions", "Bank movements in US dollars only.",
        TXN_COLUMNS, rows, {"received": _currency_totals(
            [r for r in rows if r["direction"] == "CREDIT"], "amount"
        )},
    )


def nio_transactions(db: Session, f: Filters) -> ReportResult:
    rows = _transaction_rows(db, f, currency="NIO")
    return ReportResult(
        "nio-transactions", "Cordoba transactions", "Bank movements in cordobas only.",
        TXN_COLUMNS, rows, {"received": _currency_totals(
            [r for r in rows if r["direction"] == "CREDIT"], "amount"
        )},
    )


def _match_rows(db: Session, f: Filters, statuses: list[str]) -> list[dict]:
    stmt = (
        select(ReconciliationMatch, ShopTransfer, ShopDailyRecord, BankTransaction)
        .join(ShopTransfer, ReconciliationMatch.shop_transfer_id == ShopTransfer.id)
        .join(ShopDailyRecord, ShopTransfer.daily_record_id == ShopDailyRecord.id)
        .join(BankTransaction, ReconciliationMatch.bank_transaction_id == BankTransaction.id)
        .where(
            ReconciliationMatch.is_active.is_(True),
            ReconciliationMatch.status.in_(statuses),
            ShopTransfer.deleted_at.is_(None),
            ShopDailyRecord.deleted_at.is_(None),
        )
    )
    stmt = _record_scope(stmt, f)
    if f.bank_id:
        stmt = stmt.where(ShopTransfer.bank_id == f.bank_id)
    if f.currency_code:
        stmt = stmt.where(ShopTransfer.currency_code == f.currency_code.upper())
    out = []
    for match, transfer, record, txn in db.execute(
        stmt.order_by(ShopDailyRecord.business_date.desc())
    ):
        out.append(
            {
                "date": record.business_date.isoformat(),
                "shop": record.shop.name if record.shop else "",
                "bank": transfer.bank.code if transfer.bank else "",
                "currency": transfer.currency_code,
                "amount": _money(transfer.amount),
                "bank_date": txn.txn_date.isoformat(),
                "bank_description": txn.description,
                "bank_reference": txn.reference or txn.external_id or "",
                "match_type": match.match_type,
                "confidence": match.confidence,
                "day_gap": match.date_delta_days,
            }
        )
    return out


MATCH_COLUMNS = [
    Column("date", "Shop date", "date"), Column("shop", "Shop"), Column("bank", "Bank"),
    Column("currency", "Currency"), Column("amount", "Amount", "money"),
    Column("bank_date", "Bank date", "date"), Column("bank_description", "Bank description"),
    Column("bank_reference", "Reference"), Column("match_type", "Match type", "status"),
    Column("confidence", "Confidence", "number"), Column("day_gap", "Day gap", "number"),
]


def matched_transactions(db: Session, f: Filters) -> ReportResult:
    rows = _match_rows(db, f, ["CONFIRMED"])
    return ReportResult(
        "matched-transactions", "Matched transactions",
        "Shop payments confirmed against a bank line.",
        MATCH_COLUMNS, rows, {"matched": _currency_totals(rows, "amount")},
    )


def possible_matches(db: Session, f: Filters) -> ReportResult:
    rows = _match_rows(db, f, ["SUGGESTED"])
    return ReportResult(
        "possible-matches", "Possible matches",
        "Suggestions waiting for a person to accept or reject.",
        MATCH_COLUMNS, rows, {"pending": _currency_totals(rows, "amount")},
    )


def unmatched(db: Session, f: Filters) -> ReportResult:
    stmt = _record_scope(
        select(ShopTransfer, ShopDailyRecord)
        .join(ShopDailyRecord, ShopTransfer.daily_record_id == ShopDailyRecord.id)
        .where(ShopTransfer.deleted_at.is_(None)),
        f,
    )
    if f.bank_id:
        stmt = stmt.where(ShopTransfer.bank_id == f.bank_id)
    if f.currency_code:
        stmt = stmt.where(ShopTransfer.currency_code == f.currency_code.upper())
    pairs = list(db.execute(stmt))
    statuses = recon.transfer_statuses(db, [t.id for t, _ in pairs])

    rows = []
    for transfer, record in pairs:
        state = "IGNORED" if transfer.is_ignored else statuses.get(
            transfer.id, {}
        ).get("status", "UNMATCHED")
        if state == "MATCHED" or state == "IGNORED":
            continue
        rows.append(
            {
                "side": "Shop payment not found in bank",
                "date": record.business_date.isoformat(),
                "shop": record.shop.name if record.shop else "",
                "bank": transfer.bank.code if transfer.bank else "",
                "currency": transfer.currency_code,
                "amount": _money(transfer.amount),
                "description": transfer.note or transfer.reference or "",
                "status": state,
            }
        )

    txn_stmt = select(BankTransaction).where(
        BankTransaction.direction == "CREDIT", BankTransaction.is_ignored.is_(False)
    )
    if f.date_from:
        txn_stmt = txn_stmt.where(BankTransaction.txn_date >= f.date_from)
    if f.date_to:
        txn_stmt = txn_stmt.where(BankTransaction.txn_date <= f.date_to)
    if f.bank_id:
        txn_stmt = txn_stmt.where(BankTransaction.bank_id == f.bank_id)
    if f.currency_code:
        txn_stmt = txn_stmt.where(BankTransaction.currency_code == f.currency_code.upper())
    confirmed = recon.confirmed_transaction_ids(db)
    for txn in db.scalars(txn_stmt.order_by(BankTransaction.txn_date.desc())):
        if txn.id in confirmed:
            continue
        rows.append(
            {
                "side": "Bank receipt not found in shop records",
                "date": txn.txn_date.isoformat(),
                "shop": "",
                "bank": txn.bank.code if txn.bank else "",
                "currency": txn.currency_code,
                "amount": _money(txn.amount),
                "description": txn.description,
                "status": "UNMATCHED",
            }
        )

    columns = [
        Column("side", "Exception"), Column("date", "Date", "date"), Column("shop", "Shop"),
        Column("bank", "Bank"), Column("currency", "Currency"),
        Column("amount", "Amount", "money"), Column("description", "Detail"),
        Column("status", "Status", "status"),
    ]
    shop_side = [r for r in rows if r["side"].startswith("Shop")]
    bank_side = [r for r in rows if r["side"].startswith("Bank")]
    totals = {
        "shop_payments_missing_from_bank": _currency_totals(shop_side, "amount"),
        "bank_receipts_missing_from_shops": _currency_totals(bank_side, "amount"),
    }
    return ReportResult(
        "unmatched-transactions", "Unmatched transactions",
        "The two exception lists side by side: what the shops banked that the bank "
        "has no record of, and what the bank received that no shop claimed.",
        columns, rows, totals,
    )


def reconciliation_summary(db: Session, f: Filters) -> ReportResult:
    stmt = _record_scope(
        select(ShopTransfer, ShopDailyRecord)
        .join(ShopDailyRecord, ShopTransfer.daily_record_id == ShopDailyRecord.id)
        .where(ShopTransfer.deleted_at.is_(None)),
        f,
    )
    if f.bank_id:
        stmt = stmt.where(ShopTransfer.bank_id == f.bank_id)
    pairs = list(db.execute(stmt))
    statuses = recon.transfer_statuses(db, [t.id for t, _ in pairs])

    buckets: dict[tuple, dict] = {}
    for transfer, record in pairs:
        state = "IGNORED" if transfer.is_ignored else statuses.get(
            transfer.id, {}
        ).get("status", "UNMATCHED")
        key = (
            record.shop.name if record.shop else "",
            transfer.bank.code if transfer.bank else "",
            transfer.currency_code,
        )
        bucket = buckets.setdefault(
            key,
            {"shop": key[0], "bank": key[1], "currency": key[2],
             "matched": ZERO, "possible": ZERO, "unmatched": ZERO, "ignored": ZERO,
             "count": 0},
        )
        bucket[state.lower()] += transfer.amount
        bucket["count"] += 1

    rows = []
    for bucket in buckets.values():
        total = bucket["matched"] + bucket["possible"] + bucket["unmatched"]
        rows.append(
            {
                "shop": bucket["shop"], "bank": bucket["bank"], "currency": bucket["currency"],
                "count": bucket["count"],
                "matched": _money(bucket["matched"]),
                "possible": _money(bucket["possible"]),
                "unmatched": _money(bucket["unmatched"]),
                "ignored": _money(bucket["ignored"]),
                "matched_pct": (
                    f"{(bucket['matched'] / total * 100):.0f}%" if total else "—"
                ),
            }
        )
    rows.sort(key=lambda r: (r["shop"], r["bank"], r["currency"]))
    columns = [
        Column("shop", "Shop"), Column("bank", "Bank"), Column("currency", "Currency"),
        Column("count", "Payments", "number"),
        Column("matched", "Matched", "money"), Column("possible", "Possible", "money"),
        Column("unmatched", "Unmatched", "money"), Column("ignored", "Ignored", "money"),
        Column("matched_pct", "Matched %"),
    ]
    totals = {
        currency: {
            "matched": _money(sum(Decimal(r["matched"]) for r in rows if r["currency"] == currency)),
            "possible": _money(sum(Decimal(r["possible"]) for r in rows if r["currency"] == currency)),
            "unmatched": _money(sum(Decimal(r["unmatched"]) for r in rows if r["currency"] == currency)),
        }
        for currency in {r["currency"] for r in rows}
    }
    return ReportResult(
        "reconciliation-summary", "Reconciliation summary",
        "How much of each shop's banking has been accounted for, by bank and currency.",
        columns, rows, totals,
    )


REPORTS = {
    "daily-accounting": daily_accounting,
    "monthly-accounting": monthly_accounting,
    "shop-sales": shop_sales,
    "bank-transactions": bank_transactions,
    "matched-transactions": matched_transactions,
    "unmatched-transactions": unmatched,
    "possible-matches": possible_matches,
    "usd-transactions": usd_transactions,
    "nio-transactions": nio_transactions,
    "reconciliation-summary": reconciliation_summary,
}

REPORT_INDEX = [
    {"key": "daily-accounting", "title": "Daily accounting"},
    {"key": "monthly-accounting", "title": "Monthly accounting"},
    {"key": "shop-sales", "title": "Shop sales"},
    {"key": "bank-transactions", "title": "Bank transactions"},
    {"key": "matched-transactions", "title": "Matched transactions"},
    {"key": "unmatched-transactions", "title": "Unmatched transactions"},
    {"key": "possible-matches", "title": "Possible matches"},
    {"key": "usd-transactions", "title": "USD transactions"},
    {"key": "nio-transactions", "title": "Cordoba transactions"},
    {"key": "reconciliation-summary", "title": "Reconciliation summary"},
]
