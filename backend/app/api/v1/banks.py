from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import require
from app.core.errors import Conflict, NotFound
from app.db.session import get_db
from app.models import Bank, BankAccount, BankTransaction, Currency, User
from app.parsers.registry import parser_keys, has_parser
from app.schemas.common import Message
from app.schemas.org import (
    BankAccountIn, BankAccountOut, BankAccountUpdate, BankIn, BankOut, BankUpdate, CurrencyOut,
)
from app.services import audit

router = APIRouter(tags=["banks"])


def _account_out(acc: BankAccount) -> BankAccountOut:
    return BankAccountOut(
        id=acc.id, bank_id=acc.bank_id,
        bank_code=acc.bank.code if acc.bank else None,
        bank_name=acc.bank.name if acc.bank else None,
        label=acc.label, account_number=acc.account_number,
        currency_code=acc.currency_code, is_active=acc.is_active,
    )


def _bank_out(bank: Bank) -> BankOut:
    return BankOut(
        id=bank.id, code=bank.code, name=bank.name, parser_key=bank.parser_key,
        parser_available=has_parser(bank.parser_key),
        is_active=bank.is_active,
        accounts=[_account_out(a) for a in sorted(bank.accounts, key=lambda a: a.label)],
    )


@router.get("/banks", response_model=list[BankOut])
def list_banks(
    include_inactive: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(require("shop.read")),
) -> list[BankOut]:
    stmt = select(Bank).order_by(Bank.code)
    if not include_inactive:
        stmt = stmt.where(Bank.is_active.is_(True))
    return [_bank_out(b) for b in db.scalars(stmt)]


@router.get("/banks/parsers", response_model=list[str])
def list_parsers(user: User = Depends(require("shop.read"))) -> list[str]:
    """Which statement parsers this build ships with, for the bank form."""
    return parser_keys()


@router.post("/banks", response_model=BankOut, status_code=201)
def create_bank(
    payload: BankIn,
    db: Session = Depends(get_db),
    user: User = Depends(require("bank.manage")),
) -> BankOut:
    if db.scalar(select(Bank).where(Bank.code == payload.code)):
        raise Conflict(f"A bank with the code '{payload.code}' already exists.")
    bank = Bank(**payload.model_dump())
    db.add(bank)
    db.flush()
    audit.record(db, action=audit.Actions.CREATE_BANK, module="banks", user=user,
                 record_type="bank", record_id=bank.id,
                 summary=f"Created bank {bank.code}", new_values=payload.model_dump())
    db.commit()
    db.refresh(bank)
    return _bank_out(bank)


@router.patch("/banks/{bank_id}", response_model=BankOut)
def update_bank(
    bank_id: int,
    payload: BankUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require("bank.manage")),
) -> BankOut:
    bank = db.get(Bank, bank_id)
    if not bank:
        raise NotFound("That bank does not exist.")
    before = {"code": bank.code, "name": bank.name, "parser_key": bank.parser_key,
              "is_active": bank.is_active}
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(bank, key, value)
    after = {"code": bank.code, "name": bank.name, "parser_key": bank.parser_key,
             "is_active": bank.is_active}
    old, new = audit.diff(before, after)
    audit.record(db, action=audit.Actions.EDIT_BANK, module="banks", user=user,
                 record_type="bank", record_id=bank.id,
                 summary=f"Edited bank {bank.code}", old_values=old, new_values=new)
    db.commit()
    db.refresh(bank)
    return _bank_out(bank)


@router.get("/bank-accounts", response_model=list[BankAccountOut])
def list_accounts(
    bank_id: int | None = None,
    currency_code: str | None = None,
    include_inactive: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(require("shop.read")),
) -> list[BankAccountOut]:
    stmt = select(BankAccount).order_by(BankAccount.bank_id, BankAccount.label)
    if bank_id:
        stmt = stmt.where(BankAccount.bank_id == bank_id)
    if currency_code:
        stmt = stmt.where(BankAccount.currency_code == currency_code.upper())
    if not include_inactive:
        stmt = stmt.where(BankAccount.is_active.is_(True))
    return [_account_out(a) for a in db.scalars(stmt)]


@router.post("/bank-accounts", response_model=BankAccountOut, status_code=201)
def create_account(
    payload: BankAccountIn,
    db: Session = Depends(get_db),
    user: User = Depends(require("bank.manage")),
) -> BankAccountOut:
    if not db.get(Bank, payload.bank_id):
        raise NotFound("That bank does not exist.")
    code = payload.currency_code.upper()
    if not db.get(Currency, code):
        raise NotFound(f"Currency '{code}' is not configured.")
    exists = db.scalar(
        select(BankAccount).where(
            BankAccount.bank_id == payload.bank_id,
            BankAccount.account_number == payload.account_number,
        )
    )
    if exists:
        raise Conflict("That account number already exists for this bank.")
    data = payload.model_dump()
    data["currency_code"] = code
    account = BankAccount(**data)
    db.add(account)
    db.flush()
    audit.record(db, action=audit.Actions.CREATE_BANK, module="banks", user=user,
                 record_type="bank_account", record_id=account.id,
                 summary=f"Created account {account.label}", new_values=data)
    db.commit()
    db.refresh(account)
    return _account_out(account)


@router.patch("/bank-accounts/{account_id}", response_model=BankAccountOut)
def update_account(
    account_id: int,
    payload: BankAccountUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require("bank.manage")),
) -> BankAccountOut:
    account = db.get(BankAccount, account_id)
    if not account:
        raise NotFound("That bank account does not exist.")
    changes = payload.model_dump(exclude_unset=True)
    if "currency_code" in changes and changes["currency_code"]:
        changes["currency_code"] = changes["currency_code"].upper()
        if changes["currency_code"] != account.currency_code:
            # Changing currency under transactions already extracted would
            # silently corrupt every total and every match.
            in_use = db.scalar(
                select(BankTransaction.id).where(
                    BankTransaction.bank_account_id == account_id
                ).limit(1)
            )
            if in_use:
                raise Conflict(
                    "This account already has transactions, so its currency cannot be changed. "
                    "Create a new account instead."
                )
    before = {"label": account.label, "account_number": account.account_number,
              "currency_code": account.currency_code, "is_active": account.is_active}
    for key, value in changes.items():
        setattr(account, key, value)
    after = {"label": account.label, "account_number": account.account_number,
             "currency_code": account.currency_code, "is_active": account.is_active}
    old, new = audit.diff(before, after)
    audit.record(db, action=audit.Actions.EDIT_BANK, module="banks", user=user,
                 record_type="bank_account", record_id=account.id,
                 summary=f"Edited account {account.label}", old_values=old, new_values=new)
    db.commit()
    db.refresh(account)
    return _account_out(account)


@router.get("/currencies", response_model=list[CurrencyOut])
def list_currencies(
    db: Session = Depends(get_db), user: User = Depends(require("shop.read"))
) -> list[CurrencyOut]:
    return list(db.scalars(select(Currency).order_by(Currency.code)))
