"""Monthly Records: one month of daily sheets, day by day, with USD totals.

Two rules carry over from the rest of the system and one is new:

- Every figure is still kept in its own currency. The USD columns are a
  *presentation*: USD amount + C$ amount ÷ the month's rate. Matching never
  reads the rate, so a C$ payment is still only ever matched to a C$ bank line.
- Nothing is deleted. Only the current month and the three before it are
  *offered* here; older sheets stay in the database and in Reports.
- The rate is one figure per month, set by an administrator. With no rate set,
  the USD columns are empty rather than guessed.
"""
from __future__ import annotations

import calendar
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ValidationFailed
from app.models import BankTransaction, ExchangeRate, Shop, ShopDailyRecord, User
from app.services import reconciliation as recon

PREVIOUS_MONTHS = 3
ZERO = Decimal("0.00")
CENT = Decimal("0.01")


def month_start(value: date) -> date:
    return value.replace(day=1)


def add_months(value: date, months: int) -> date:
    index = value.year * 12 + (value.month - 1) + months
    return date(index // 12, index % 12 + 1, 1)


def month_end(month: date) -> date:
    return month.replace(day=calendar.monthrange(month.year, month.month)[1])


def month_key(month: date) -> str:
    return f"{month:%Y-%m}"


def month_label(month: date) -> str:
    return f"{calendar.month_name[month.month]} {month.year}"


def available_months(today: date | None = None) -> list[date]:
    """The current month first, then the three before it."""
    current = month_start(today or date.today())
    return [add_months(current, -offset) for offset in range(PREVIOUS_MONTHS + 1)]


def parse_month(raw: str, today: date | None = None) -> date:
    try:
        year, month = (int(part) for part in raw.split("-"))
        parsed = date(year, month, 1)
    except (ValueError, TypeError):
        raise ValidationFailed(f"'{raw}' is not a month. Use the form 2026-10.") from None
    window = available_months(today)
    if parsed not in window:
        oldest = window[-1]
        raise ValidationFailed(
            f"Monthly Records keeps the current month and the {PREVIOUS_MONTHS} before it "
            f"({month_label(oldest)} to {month_label(window[0])}). Older sheets are not "
            f"deleted — use Reports with a date range to see {month_label(parsed)}."
        )
    return parsed


def money(value: Decimal) -> Decimal:
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def to_usd(usd: Decimal, nio: Decimal, rate: Decimal | None) -> Decimal | None:
    if not rate:
        return None
    return money(Decimal(usd) + Decimal(nio) / rate)


def get_rate(db: Session, month: date) -> ExchangeRate | None:
    return db.scalar(select(ExchangeRate).where(ExchangeRate.month == month_start(month)))


def set_rate(db: Session, month: date, nio_per_usd: Decimal, user: User) -> ExchangeRate:
    row = get_rate(db, month)
    if row is None:
        row = ExchangeRate(month=month_start(month), nio_per_usd=nio_per_usd, set_by_id=user.id)
        db.add(row)
    else:
        row.nio_per_usd = nio_per_usd
        row.set_by_id = user.id
        row.updated_at = datetime.now(UTC)
    db.flush()
    return row


# ------------------------------------------------------------------ the month
@dataclass
class Bucket:
    sheets: int = 0
    shops: set[str] = field(default_factory=set)
    sales: dict[str, Decimal] = field(default_factory=lambda: {"USD": ZERO, "NIO": ZERO})
    bank: dict[str, Decimal] = field(default_factory=lambda: {"USD": ZERO, "NIO": ZERO})
    cash: dict[str, Decimal] = field(default_factory=lambda: {"USD": ZERO, "NIO": ZERO})
    expenses: dict[str, Decimal] = field(default_factory=lambda: {"USD": ZERO, "NIO": ZERO})
    status: dict[str, int] = field(default_factory=lambda: defaultdict(int))

    def add(self, other: "Bucket") -> None:
        self.sheets += other.sheets
        self.shops |= other.shops
        for name in ("sales", "bank", "cash", "expenses"):
            mine, theirs = getattr(self, name), getattr(other, name)
            for code in ("USD", "NIO"):
                mine[code] += theirs[code]
        for key, value in other.status.items():
            self.status[key] += value

    def as_dict(self, rate: Decimal | None) -> dict:
        received_usd = self.bank["USD"] + self.cash["USD"]
        received_nio = self.bank["NIO"] + self.cash["NIO"]
        return {
            "sheets": self.sheets,
            "shops": sorted(self.shops),
            "sales_usd": str(money(self.sales["USD"])),
            "sales_nio": str(money(self.sales["NIO"])),
            "bank_usd": str(money(self.bank["USD"])),
            "bank_nio": str(money(self.bank["NIO"])),
            "cash_usd": str(money(self.cash["USD"])),
            "cash_nio": str(money(self.cash["NIO"])),
            "expenses_usd": str(money(self.expenses["USD"])),
            "expenses_nio": str(money(self.expenses["NIO"])),
            # The USD view the business asked for. None when no rate is set.
            "sales_in_usd": _s(to_usd(self.sales["USD"], self.sales["NIO"], rate)),
            "bank_in_usd": _s(to_usd(self.bank["USD"], self.bank["NIO"], rate)),
            "cash_in_usd": _s(to_usd(self.cash["USD"], self.cash["NIO"], rate)),
            "received_in_usd": _s(to_usd(received_usd, received_nio, rate)),
            "expenses_in_usd": _s(to_usd(self.expenses["USD"], self.expenses["NIO"], rate)),
            "matched": self.status.get("MATCHED", 0),
            "possible": self.status.get("POSSIBLE", 0),
            "unmatched": self.status.get("UNMATCHED", 0),
            "pending_cash": self.status.get(recon.PENDING_DEPOSIT, 0),
        }


def _s(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


@dataclass
class PaymentLine:
    business_date: date
    shop: str
    method: str
    bank: str
    currency: str
    amount: Decimal
    reference: str
    note: str
    status: str
    bank_date: date | None
    bank_description: str


@dataclass
class MonthData:
    month: date
    rate: ExchangeRate | None
    shop: Shop | None
    days: list[tuple[date, Bucket]]
    total: Bucket
    by_shop: list[tuple[str, Bucket]]
    payments: list[PaymentLine]


def _records(db: Session, month: date, allowed: list[int] | None, shop_id: int | None):
    stmt = select(ShopDailyRecord).where(
        ShopDailyRecord.deleted_at.is_(None),
        ShopDailyRecord.business_date >= month,
        ShopDailyRecord.business_date <= month_end(month),
    )
    if allowed is not None:
        stmt = stmt.where(ShopDailyRecord.shop_id.in_(allowed or [-1]))
    if shop_id:
        stmt = stmt.where(ShopDailyRecord.shop_id == shop_id)
    return list(db.scalars(stmt.order_by(ShopDailyRecord.business_date, ShopDailyRecord.shop_id)))


def collect(
    db: Session, month: date, *, allowed: list[int] | None, shop_id: int | None = None
) -> MonthData:
    records = _records(db, month, allowed, shop_id)
    live = [t for r in records for t in r.transfers if t.deleted_at is None]
    statuses = recon.transfer_statuses(db, [t.id for t in live])

    matched_txn_ids = {s["transaction_id"] for s in statuses.values() if s.get("transaction_id")}
    txns = {
        t.id: t for t in db.scalars(
            select(BankTransaction).where(BankTransaction.id.in_(matched_txn_ids or [-1]))
        )
    }

    per_day: dict[date, Bucket] = defaultdict(Bucket)
    per_shop: dict[str, Bucket] = defaultdict(Bucket)
    payments: list[PaymentLine] = []

    for record in records:
        shop_name = record.shop.name if record.shop else str(record.shop_id)
        bucket = Bucket(sheets=1, shops={shop_name})
        bucket.sales["USD"] += record.total_sales_usd
        bucket.sales["NIO"] += record.total_sales_nio
        for expense in record.expenses:
            bucket.expenses[expense.currency_code] += expense.amount
        for transfer in record.transfers:
            if transfer.deleted_at is not None:
                continue
            side = bucket.cash if transfer.is_cash else bucket.bank
            side[transfer.currency_code] += transfer.amount
            entry = statuses.get(transfer.id, {})
            state = recon.display_status(transfer, entry)
            bucket.status[state] += 1
            txn = txns.get(entry.get("transaction_id")) if state == "MATCHED" else None
            payments.append(
                PaymentLine(
                    business_date=record.business_date, shop=shop_name,
                    method="Cash" if transfer.is_cash else "Bank",
                    bank=(txn.bank.code if txn and txn.bank else "") if transfer.is_cash
                    else (transfer.bank.code if transfer.bank else ""),
                    currency=transfer.currency_code, amount=transfer.amount,
                    reference=transfer.reference or "", note=transfer.note or "",
                    status=state, bank_date=txn.txn_date if txn else None,
                    bank_description=txn.description if txn else "",
                )
            )
        per_day[record.business_date].add(bucket)
        per_shop[shop_name].add(bucket)

    days = []
    total = Bucket()
    for day in range(1, month_end(month).day + 1):
        current = month.replace(day=day)
        bucket = per_day.get(current, Bucket())
        days.append((current, bucket))
        total.add(bucket)

    return MonthData(
        month=month, rate=get_rate(db, month),
        shop=db.get(Shop, shop_id) if shop_id else None,
        days=days, total=total, by_shop=sorted(per_shop.items()), payments=payments,
    )


def as_json(data: MonthData, today: date | None = None) -> dict:
    today = today or date.today()
    rate = data.rate.nio_per_usd if data.rate else None
    return {
        "month": month_key(data.month),
        "label": month_label(data.month),
        "shop_id": data.shop.id if data.shop else None,
        "shop_name": data.shop.name if data.shop else None,
        "rate": str(rate) if rate is not None else None,
        "rate_updated_at": data.rate.updated_at.isoformat() if data.rate else None,
        "days": [
            {
                "date": day.isoformat(),
                "day": day.day,
                "weekday": calendar.day_abbr[day.weekday()],
                "is_future": day > today,
                **bucket.as_dict(rate),
            }
            for day, bucket in data.days
        ],
        "totals": data.total.as_dict(rate),
    }


def month_summaries(
    db: Session, *, allowed: list[int] | None, today: date | None = None
) -> list[dict]:
    out = []
    for index, month in enumerate(available_months(today)):
        stmt = select(ShopDailyRecord.id).where(
            ShopDailyRecord.deleted_at.is_(None),
            ShopDailyRecord.business_date >= month,
            ShopDailyRecord.business_date <= month_end(month),
        )
        if allowed is not None:
            stmt = stmt.where(ShopDailyRecord.shop_id.in_(allowed or [-1]))
        rate = get_rate(db, month)
        out.append(
            {
                "month": month_key(month),
                "label": month_label(month),
                "is_current": index == 0,
                "sheet_count": len(list(db.scalars(stmt))),
                "rate": str(rate.nio_per_usd) if rate else None,
            }
        )
    return out

