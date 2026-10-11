"""Each bank account's balance, day by day.

A day's closing balance comes from, in order:

- ENTERED    typed by a person from the bank (BANPRO's export prints no balance);
- STATEMENT  printed on the uploaded statement (BAC and LAFISE print a running
             balance, and the statement's closing balance is kept);
- CALCULATED the previous day's closing plus that day's credits minus its debits.

Where a printed or typed closing exists and the previous day's closing is
known too, the two are compared: a difference means a movement is missing
from what was uploaded (or a balance was typed wrong)."""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import BankAccount, BankBalance, BankStatement, BankTransaction

ZERO = Decimal("0.00")


def _statement_closings(db: Session, account_id: int) -> dict[date, Decimal]:
    """Closing balance printed on a statement, keyed by the statement's last day."""
    last_txn = dict(
        db.execute(
            select(BankTransaction.statement_id, func.max(BankTransaction.txn_date))
            .where(BankTransaction.bank_account_id == account_id)
            .group_by(BankTransaction.statement_id)
        ).all()
    )
    out: dict[date, Decimal] = {}
    for statement in db.scalars(
        select(BankStatement).where(
            BankStatement.bank_account_id == account_id,
            BankStatement.statement_closing_balance.is_not(None),
        ).order_by(BankStatement.id)
    ):
        day = statement.period_end or last_txn.get(statement.id)
        if day:
            out[day] = statement.statement_closing_balance
    return out


def account_days(db: Session, account: BankAccount) -> list[dict]:
    """Every day the account has movements or a known balance, oldest first."""
    moves: dict[date, dict[str, Decimal]] = defaultdict(lambda: {"CREDIT": ZERO, "DEBIT": ZERO})
    counts: dict[date, int] = defaultdict(int)
    for day, direction, total, n in db.execute(
        select(BankTransaction.txn_date, BankTransaction.direction,
               func.sum(BankTransaction.amount), func.count())
        .where(BankTransaction.bank_account_id == account.id,
               BankTransaction.is_ignored.is_(False))
        .group_by(BankTransaction.txn_date, BankTransaction.direction)
    ):
        moves[day][direction] = total or ZERO
        counts[day] += n
    printed = _statement_closings(db, account.id)
    entered = {
        b.balance_date: b for b in db.scalars(
            select(BankBalance).where(BankBalance.bank_account_id == account.id)
        )
    }

    days = sorted(set(moves) | set(printed) | set(entered))
    rows: list[dict] = []
    previous: Decimal | None = None
    for day in days:
        credits = moves[day]["CREDIT"] if day in moves else ZERO
        debits = moves[day]["DEBIT"] if day in moves else ZERO
        calculated = previous + credits - debits if previous is not None else None
        if day in entered:
            closing, source = entered[day].closing_balance, "ENTERED"
        elif day in printed:
            closing, source = printed[day], "STATEMENT"
        else:
            closing, source = calculated, "CALCULATED" if calculated is not None else None
        opening = previous if previous is not None else (
            closing - credits + debits if closing is not None else None
        )
        difference = (
            closing - calculated
            if source in ("ENTERED", "STATEMENT") and calculated is not None and closing != calculated
            else None
        )
        rows.append({
            "date": day.isoformat(),
            "opening": opening,
            "credits": credits,
            "debits": debits,
            "movements": counts.get(day, 0),
            "closing": closing,
            "source": source,
            "statement_closing": printed.get(day),
            "entered_closing": entered[day].closing_balance if day in entered else None,
            "difference": difference,
        })
        if closing is not None:
            previous = closing
    return rows


def overview(db: Session, *, date_from: date | None, date_to: date | None) -> list[dict]:
    out = []
    accounts = db.scalars(
        select(BankAccount).where(BankAccount.is_active.is_(True)).order_by(BankAccount.id)
    )
    for account in accounts:
        rows = account_days(db, account)
        known = [r for r in rows if r["closing"] is not None]
        shown = [
            r for r in rows
            if (not date_from or r["date"] >= date_from.isoformat())
            and (not date_to or r["date"] <= date_to.isoformat())
        ]
        out.append({
            "account_id": account.id,
            "bank_code": account.bank.code if account.bank else None,
            "bank_name": account.bank.name if account.bank else None,
            "label": account.label,
            "currency_code": account.currency_code,
            "latest": known[-1] if known else None,
            "days": list(reversed(shown)),
        })
    return out
