from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import require
from app.core.errors import NotFound
from app.db.session import get_db
from app.models import BankAccount, BankBalance, User
from app.services import audit, bank_balances

router = APIRouter(tags=["banking"])


@router.get("/bank-balances")
def list_balances(
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(require("statement.read")),
) -> list[dict]:
    """Each account's balance day by day: opening, credits, debits, closing."""
    return bank_balances.overview(db, date_from=date_from, date_to=date_to)


class BalanceIn(BaseModel):
    # None removes a typed balance, so the day falls back to the statement or the calculation.
    closing_balance: Decimal | None = Field(None, max_digits=18, decimal_places=2)


@router.put("/bank-balances/{account_id}/{day}")
def set_balance(
    account_id: int,
    day: date,
    payload: BalanceIn,
    db: Session = Depends(get_db),
    user: User = Depends(require("statement.upload")),
) -> dict:
    """Type the closing balance the bank shows for a day (BANPRO prints none)."""
    account = db.get(BankAccount, account_id)
    if account is None:
        raise NotFound("That bank account does not exist.")
    row = db.scalar(select(BankBalance).where(
        BankBalance.bank_account_id == account_id, BankBalance.balance_date == day,
    ))
    old = row.closing_balance if row else None
    if payload.closing_balance is None:
        if row:
            db.delete(row)
    elif row:
        row.closing_balance = payload.closing_balance
        row.entered_by_id = user.id
    else:
        db.add(BankBalance(bank_account_id=account_id, balance_date=day,
                           closing_balance=payload.closing_balance, entered_by_id=user.id))
    audit.record(
        db, action=audit.Actions.SET_BANK_BALANCE, module="banking", user=user, record_type="bank_balance",
        record_id=f"{account_id}:{day}",
        summary=f"Closing balance of {account.label} on {day}: {old} -> {payload.closing_balance}",
        old_values={"closing_balance": old}, new_values={"closing_balance": payload.closing_balance},
    )
    db.commit()
    rows = bank_balances.account_days(db, account)
    return next((r for r in rows if r["date"] == day.isoformat()), {"date": day.isoformat()})
