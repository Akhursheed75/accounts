"""Daily-sheet arithmetic.

Two rules run through all of it: USD and cordobas are never added together, and
the closing balance is always returned with the steps that produced it, so the
figure on screen can be checked against the paper sheet line by line.

The paper sheet itself works in dollars: every C$ amount is converted and the
TOTAL$ column, the expenses and the balances are all dollar figures. That view
is `paper_view` — the per-currency figures stay the record of truth, and the
dollar view is computed from them at the month's rate, never stored."""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from app.models import ShopDailyRecord

ZERO = Decimal("0.00")
CENT = Decimal("0.01")
CURRENCIES = ("USD", "NIO")


def money(value: Decimal | None) -> Decimal:
    return Decimal(value if value is not None else 0).quantize(CENT, rounding=ROUND_HALF_UP)


def _live(record: ShopDailyRecord):
    return [t for t in record.transfers if t.deleted_at is None]


def _payment_totals(record: ShopDailyRecord, *, cash: bool) -> dict[str, Decimal]:
    totals = {code: ZERO for code in CURRENCIES}
    for transfer in _live(record):
        if transfer.is_cash != cash:
            continue
        totals[transfer.currency_code] = totals.get(transfer.currency_code, ZERO) + transfer.amount
    return {k: money(v) for k, v in totals.items()}


def details_by_cell(record: ShopDailyRecord) -> dict[tuple[int, str], Decimal]:
    """Sum of the bank deposits per (bank, currency)."""
    out: dict[tuple[int, str], Decimal] = {}
    for transfer in _live(record):
        if transfer.is_cash:
            continue
        key = (transfer.bank_id, transfer.currency_code)
        out[key] = out.get(key, ZERO) + transfer.amount
    return out


def declared_by_cell(record: ShopDailyRecord) -> dict[tuple[int, str], Decimal]:
    return {(t.bank_id, t.currency_code): t.amount for t in record.bank_totals}


def transfer_totals(record: ShopDailyRecord) -> dict[str, Decimal]:
    """Bank payments only; cash is its own line on the sheet.

    Where the sheet gives a bank total, that total is what was banked — it is
    the figure the shop signed off on. Where it gives only deposits, their sum
    is. A difference between the two is reported, never silently resolved."""
    declared = declared_by_cell(record)
    details = details_by_cell(record)
    totals = {code: ZERO for code in CURRENCIES}
    for key in set(declared) | set(details):
        amount = declared.get(key, details.get(key, ZERO))
        totals[key[1]] = totals.get(key[1], ZERO) + amount
    return {k: money(v) for k, v in totals.items()}


def cash_totals(record: ShopDailyRecord) -> dict[str, Decimal]:
    return _payment_totals(record, cash=True)


def transfer_totals_by_bank(record: ShopDailyRecord) -> dict[int, dict[str, Decimal]]:
    out: dict[int, dict[str, Decimal]] = {}
    declared = declared_by_cell(record)
    details = details_by_cell(record)
    for (bank_id, currency) in set(declared) | set(details):
        bucket = out.setdefault(bank_id, {c: ZERO for c in CURRENCIES})
        bucket[currency] = declared.get((bank_id, currency), details.get((bank_id, currency), ZERO))
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
    if key == "total_cash":
        return cash_totals(record)[currency]
    if key == "total_expenses":
        return expense_totals(record)[currency]
    if key == "total_sales":
        return money(getattr(record, f"total_sales_{suffix}"))
    if key == "opening_balance":
        return money(getattr(record, f"opening_balance_{suffix}"))
    # The paper's dollar-only lines add to the older per-currency fields.
    if key == "delivery" and currency == "USD":
        return money(record.delivery_usd + record.delivery_cash_usd + record.delivery_transfer_usd)
    if key == "commercial_invoice" and currency == "USD":
        return money(
            record.commercial_invoice_usd + record.commercial_invoice_cash_usd
            + record.commercial_invoice_deposit_usd
        )
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


# --------------------------------------------------------------- dollar view
def in_usd(usd: Decimal, nio: Decimal, rate: Decimal | None) -> Decimal | None:
    if not rate:
        return None if nio else money(usd)
    return money(Decimal(usd) + Decimal(nio) / rate)


def paper_view(
    record: ShopDailyRecord, components: list[dict], rate: Decimal | None
) -> dict:
    """The sheet as the shop writes it: everything in dollars.

    The closing balance follows the same configurable components as the
    per-currency breakdown, each converted at the month's rate. With no rate,
    anything that involves cordobas is None rather than a guess."""
    def pair(usd: Decimal, nio: Decimal) -> dict:
        return {"usd": str(money(usd)), "nio": str(money(nio)), "total_usd": _s(in_usd(usd, nio, rate))}

    total = in_usd(
        record.total_sales_usd + record.opening_balance_usd,
        record.total_sales_nio + record.opening_balance_nio, rate,
    )
    cash = cash_totals(record)
    expenses = expense_totals(record)
    transfers = transfer_totals(record)

    steps = []
    running: Decimal | None = ZERO
    for component in components:
        if not component.get("enabled") or component.get("sign", 0) == 0:
            continue
        value = in_usd(
            _component_value(record, component["key"], "USD"),
            _component_value(record, component["key"], "NIO"), rate,
        )
        sign = int(component["sign"])
        if value is None or running is None:
            running = None
        else:
            running += value * sign
        steps.append(
            {"key": component["key"], "label": component.get("label", component["key"]),
             "sign": sign, "amount_usd": _s(value)}
        )
    computed = money(running) if running is not None else None
    declared = record.declared_closing_usd
    return {
        "rate": str(rate) if rate else None,
        "total_usd": _s(total),
        "cash_received": pair(cash["USD"], cash["NIO"]),
        "transfers": pair(transfers["USD"], transfers["NIO"]),
        "expenses": pair(expenses["USD"], expenses["NIO"]),
        "steps": steps,
        "closing_computed_usd": _s(computed),
        "closing_declared_usd": _s(money(declared)) if declared is not None else None,
        "closing_difference_usd": (
            _s(money(declared - computed))
            if declared is not None and computed is not None else None
        ),
    }


def _s(value: Decimal | None) -> str | None:
    return None if value is None else str(value)
