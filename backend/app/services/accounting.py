"""Daily-sheet arithmetic.

Two rules run through all of it: USD and cordobas are never added together, and
the closing balance is always returned with the steps that produced it, so the
figure on screen can be checked against the paper sheet line by line."""
from __future__ import annotations

from decimal import Decimal

from app.models import ShopDailyRecord

ZERO = Decimal("0.00")
CURRENCIES = ("USD", "NIO")


def money(value: Decimal | None) -> Decimal:
    return Decimal(value if value is not None else 0).quantize(Decimal("0.01"))


def transfer_totals(record: ShopDailyRecord) -> dict[str, Decimal]:
    totals = {code: ZERO for code in CURRENCIES}
    for transfer in record.transfers:
        if transfer.deleted_at is not None:
            continue
        totals[transfer.currency_code] = totals.get(transfer.currency_code, ZERO) + transfer.amount
    return {k: money(v) for k, v in totals.items()}


def transfer_totals_by_bank(record: ShopDailyRecord) -> dict[int, dict[str, Decimal]]:
    out: dict[int, dict[str, Decimal]] = {}
    for transfer in record.transfers:
        if transfer.deleted_at is not None:
            continue
        bucket = out.setdefault(transfer.bank_id, {c: ZERO for c in CURRENCIES})
        bucket[transfer.currency_code] = bucket.get(transfer.currency_code, ZERO) + transfer.amount
    return out


def expense_totals(record: ShopDailyRecord) -> dict[str, Decimal]:
    totals = {code: ZERO for code in CURRENCIES}
    for expense in record.expenses:
        totals[expense.currency_code] = totals.get(expense.currency_code, ZERO) + expense.amount
    return {k: money(v) for k, v in totals.items()}


def _component_value(record: ShopDailyRecord, key: str, currency: str) -> Decimal:
    suffix = currency.lower()
    if key == "total_transfers":
        return transfer_totals(record)[currency]
    if key == "total_expenses":
        return expense_totals(record)[currency]
    if key == "total_sales":
        return money(getattr(record, f"total_sales_{suffix}"))
    if key == "opening_balance":
        return money(getattr(record, f"opening_balance_{suffix}"))
    return money(getattr(record, f"{key}_{suffix}", ZERO))


def balance_breakdown(
    record: ShopDailyRecord, components: list[dict]
) -> dict[str, dict]:
    """Returns, per currency, the ordered steps and the resulting closing balance."""
    out: dict[str, dict] = {}
    for currency in CURRENCIES:
        steps = []
        running = ZERO
        for component in components:
            if not component.get("enabled") or component.get("sign", 0) == 0:
                continue
            value = _component_value(record, component["key"], currency)
            sign = int(component["sign"])
            running += value * sign
            steps.append(
                {
                    "key": component["key"],
                    "label": component.get("label", component["key"]),
                    "sign": sign,
                    "amount": str(money(value)),
                    "running_total": str(money(running)),
                }
            )
        entered = money(getattr(record, f"closing_balance_{currency.lower()}"))
        computed = money(running)
        out[currency] = {
            "steps": steps,
            "computed": str(computed),
            "entered": str(entered),
            "difference": str(money(entered - computed)),
            "matches": entered == computed,
        }
    return out


def apply_computed_closing(record: ShopDailyRecord, components: list[dict]) -> None:
    """Used when the record is not overriding the figure by hand."""
    if record.closing_balance_source == "MANUAL":
        return
    breakdown = balance_breakdown(record, components)
    record.closing_balance_usd = Decimal(breakdown["USD"]["computed"])
    record.closing_balance_nio = Decimal(breakdown["NIO"]["computed"])
