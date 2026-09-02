"""Creates the permissions, roles, reference data and an admin account, and can
load a demo month so the system is explorable before any real data exists.

Safe to run more than once: everything is looked up before it is created."""
from __future__ import annotations

import argparse
import logging
import os
import secrets
from datetime import date
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.permissions import PERMISSIONS, ROLE_PRESETS
from app.core.security import hash_password
from app.db.session import SessionLocal
from app.models import (
    BaleType, Bank, BankAccount, City, Currency, Permission, Role, Shop,
    ShopDailyRecord, ShopTransfer, User, UserShop,
)
from app.services.settings_store import match_settings, system_settings

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("seed")

CURRENCIES = [
    ("USD", "US Dollar", "$", 2),
    ("NIO", "Nicaraguan Cordoba", "C$", 2),
]

CITIES = ["Managua", "Leon", "Granada"]

SHOPS = [
    ("SHOP1", "Shop 1", "Managua"),
    ("SHOP2", "Shop 2", "Leon"),
    ("SHOP3", "Shop 3", "Granada"),
]

BANKS = [
    ("BAC", "BAC Credomatic", "BAC"),
    ("LAFISE", "Banco LAFISE Bancentro", "LAFISE"),
    ("BANPRO", "Banco de la Produccion", "BANPRO"),
    # No parser yet: the upload is stored and reported honestly rather than guessed at.
    ("FICHOSA", "FICOHSA", None),
]

ACCOUNTS = [
    ("BAC", "BAC Cordobas", "370555179", "NIO"),
    ("BAC", "BAC Dollars", "370555203", "USD"),
    ("LAFISE", "LAFISE Cordobas", "LAFISE-NIO-01", "NIO"),
    ("LAFISE", "LAFISE Dollars", "LAFISE-USD-01", "USD"),
    ("BANPRO", "BANPRO Cordobas", "BANPRO-NIO-01", "NIO"),
    ("BANPRO", "BANPRO Dollars", "BANPRO-USD-01", "USD"),
    ("FICHOSA", "FICOHSA Cordobas", "FICOHSA-NIO-01", "NIO"),
    ("FICHOSA", "FICOHSA Dollars", "FICOHSA-USD-01", "USD"),
]

BALE_TYPES = [("100LBS", "100 lb bale", Decimal("100"), 1), ("25LBS", "25 lb bale", Decimal("25"), 2)]

SAMPLE_STATEMENTS = [
    ("bac cordoba aug-11.pdf", "BAC Cordobas", date(2026, 8, 11)),
    ("bac dollars Aug-11.pdf", "BAC Dollars", date(2026, 8, 11)),
    ("lafise cordoba Aug-11.pdf", "LAFISE Cordobas", date(2026, 8, 11)),
    ("lafise dollar Aug-11.pdf", "LAFISE Dollars", date(2026, 8, 11)),
    ("lafise cordoba Aug-20.pdf", "LAFISE Cordobas", date(2026, 8, 20)),
    ("lafise dollar Aug-20.pdf", "LAFISE Dollars", date(2026, 8, 20)),
    ("Banpro - Cordoba Aug-20.pdf", "BANPRO Cordobas", date(2026, 8, 20)),
    ("Banpro - USD Aug-20.pdf", "BANPRO Dollars", date(2026, 8, 20)),
]

# Chosen so the demo shows every outcome: clean matches, a payment with no bank
# counterpart, and an amount that appears twice in one day and must NOT be
# auto-matched.
DEMO_SHEETS = [
    {
        "shop": "SHOP1", "date": date(2026, 8, 11),
        "bales": 42, "invoices": 18,
        "sales_usd": "1310.00", "sales_nio": "31840.00",
        "opening_usd": "300.00", "opening_nio": "5000.00",
        "expenses": [("Transport", "USD", "60.00"), ("Wages", "NIO", "1200.00")],
        "transfers": [
            ("BAC", "NIO", "4452.00", "Deposit for bale sales"),
            ("LAFISE", "NIO", "14098.00", "Pago de pacas"),
            ("LAFISE", "USD", "410.00", ""),
            # Two identical 250.00 credits exist on this day at BAC — the engine
            # must offer both rather than pick one.
            ("BAC", "USD", "250.00", ""),
        ],
        "observations": "Demo sheet. Figures illustrate the reconciliation outcomes.",
    },
    {
        "shop": "SHOP2", "date": date(2026, 8, 11),
        "bales": 31, "invoices": 12,
        "sales_usd": "980.00", "sales_nio": "22100.00",
        "opening_usd": "150.00", "opening_nio": "3400.00",
        "expenses": [("Fuel", "USD", "35.00")],
        "transfers": [
            ("BAC", "NIO", "7234.00", ""),
            ("BAC", "USD", "715.00", ""),
            ("LAFISE", "NIO", "11501.00", "Pago de pacas"),
        ],
        "observations": "Demo sheet.",
    },
    {
        "shop": "SHOP3", "date": date(2026, 8, 20),
        "bales": 55, "invoices": 24,
        "sales_usd": "1640.00", "sales_nio": "40200.00",
        "opening_usd": "220.00", "opening_nio": "6100.00",
        "expenses": [("Rent", "NIO", "4000.00")],
        "transfers": [
            ("BANPRO", "NIO", "20000.00", ""),
            ("BANPRO", "USD", "460.00", ""),
            ("LAFISE", "NIO", "6493.00", ""),
            ("LAFISE", "USD", "370.00", ""),
        ],
        "observations": "Demo sheet.",
    },
    {
        "shop": "SHOP1", "date": date(2026, 8, 20),
        "bales": 20, "invoices": 9,
        "sales_usd": "700.00", "sales_nio": "14000.00",
        "opening_usd": "180.00", "opening_nio": "2400.00",
        "expenses": [],
        "transfers": [
            # Deliberately has no counterpart in any statement: this is what an
            # exception looks like.
            ("BAC", "USD", "999.00", "Missing from the bank statement on purpose"),
            ("LAFISE", "NIO", "2000.00", ""),
        ],
        "observations": "Demo sheet with one payment the bank never received.",
    },
]


def ensure_reference_data(db: Session) -> None:
    for code, description in PERMISSIONS.items():
        if not db.scalar(select(Permission).where(Permission.code == code)):
            db.add(Permission(code=code, description=description))
    db.flush()

    all_perms = {p.code: p for p in db.scalars(select(Permission))}
    for code, preset in ROLE_PRESETS.items():
        role = db.scalar(select(Role).where(Role.code == code))
        if role is None:
            role = Role(code=code, name=preset["name"], description=preset["description"],
                        is_system=True)
            db.add(role)
            db.flush()
        role.permissions = [all_perms[c] for c in preset["permissions"] if c in all_perms]
    db.flush()

    for code, name, symbol, decimals in CURRENCIES:
        if not db.get(Currency, code):
            db.add(Currency(code=code, name=name, symbol=symbol, decimals=decimals))
    db.flush()

    for name in CITIES:
        if not db.scalar(select(City).where(City.name == name)):
            db.add(City(name=name))
    db.flush()

    cities = {c.name: c for c in db.scalars(select(City))}
    for code, name, city in SHOPS:
        if not db.scalar(select(Shop).where(Shop.code == code)):
            db.add(Shop(code=code, name=name, city_id=cities[city].id, is_active=True))
    db.flush()

    for code, name, parser in BANKS:
        bank = db.scalar(select(Bank).where(Bank.code == code))
        if bank is None:
            db.add(Bank(code=code, name=name, parser_key=parser, is_active=True))
    db.flush()

    banks = {b.code: b for b in db.scalars(select(Bank))}
    for bank_code, label, number, currency in ACCOUNTS:
        exists = db.scalar(
            select(BankAccount).where(
                BankAccount.bank_id == banks[bank_code].id,
                BankAccount.account_number == number,
            )
        )
        if not exists:
            db.add(
                BankAccount(bank_id=banks[bank_code].id, label=label,
                            account_number=number, currency_code=currency)
            )
    db.flush()

    for code, name, weight, order in BALE_TYPES:
        if not db.scalar(select(BaleType).where(BaleType.code == code)):
            db.add(BaleType(code=code, name=name, weight_lbs=weight, sort_order=order))
    db.flush()

    match_settings(db)
    system_settings(db)
    db.flush()


def ensure_admin(db: Session) -> tuple[str, str | None]:
    email = os.getenv("ADMIN_EMAIL", "admin@reconcilia.local").lower()
    existing = db.scalar(select(User).where(User.email == email))
    if existing:
        return email, None
    password = os.getenv("ADMIN_PASSWORD") or secrets.token_urlsafe(12)
    admin_role = db.scalar(select(Role).where(Role.code == "ADMIN"))
    db.add(
        User(
            email=email,
            full_name=os.getenv("ADMIN_NAME", "System administrator"),
            password_hash=hash_password(password),
            role_id=admin_role.id,
            is_active=True,
        )
    )
    db.flush()
    return email, password


def ensure_demo_users(db: Session) -> list[tuple[str, str]]:
    role = db.scalar(select(Role).where(Role.code == "SHOP_USER"))
    shops = {s.code: s for s in db.scalars(select(Shop))}
    created = []
    for shop_code in ("SHOP1", "SHOP2", "SHOP3"):
        email = f"{shop_code.lower()}@reconcilia.local"
        if db.scalar(select(User).where(User.email == email)):
            continue
        password = os.getenv("DEMO_PASSWORD", "DemoShop!2026")
        user = User(
            email=email, full_name=f"{shops[shop_code].name} user",
            password_hash=hash_password(password), role_id=role.id, is_active=True,
        )
        db.add(user)
        db.flush()
        db.add(UserShop(user_id=user.id, shop_id=shops[shop_code].id))
        created.append((email, password))
    db.flush()
    return created


def ensure_demo_sheets(db: Session) -> int:
    shops = {s.code: s for s in db.scalars(select(Shop))}
    banks = {b.code: b for b in db.scalars(select(Bank))}
    created = 0
    for sheet in DEMO_SHEETS:
        shop = shops[sheet["shop"]]
        exists = db.scalar(
            select(ShopDailyRecord).where(
                ShopDailyRecord.shop_id == shop.id,
                ShopDailyRecord.business_date == sheet["date"],
                ShopDailyRecord.deleted_at.is_(None),
            )
        )
        if exists:
            continue
        record = ShopDailyRecord(
            shop_id=shop.id, business_date=sheet["date"], status="SUBMITTED",
            bale_count=sheet["bales"], invoice_count=sheet["invoices"],
            total_sales_usd=Decimal(sheet["sales_usd"]),
            total_sales_nio=Decimal(sheet["sales_nio"]),
            opening_balance_usd=Decimal(sheet["opening_usd"]),
            opening_balance_nio=Decimal(sheet["opening_nio"]),
            observations=sheet["observations"], is_demo=True,
        )
        for bank_code, currency, amount, note in sheet["transfers"]:
            record.transfers.append(
                ShopTransfer(
                    bank_id=banks[bank_code].id, currency_code=currency,
                    amount=Decimal(amount), note=note,
                )
            )
        from app.models import Expense

        for category, currency, amount in sheet["expenses"]:
            record.expenses.append(
                Expense(category=category, currency_code=currency, amount=Decimal(amount))
            )
        db.add(record)
        created += 1
    db.flush()

    from app.services.accounting import apply_computed_closing

    components = system_settings(db).balance_components
    for record in db.scalars(select(ShopDailyRecord).where(ShopDailyRecord.is_demo.is_(True))):
        apply_computed_closing(record, components)
    db.flush()
    return created


def ingest_sample_statements(db: Session, samples_dir: Path) -> int:
    """Loads the real statement PDFs kept for parser development, so the demo
    reconciles against genuine bank layouts rather than invented ones."""
    from app.core.security import sha256_bytes
    from app.models import BankStatement
    from app.services.statement_processing import process_statement
    from app.services.storage import get_storage, statement_key

    accounts = {a.label: a for a in db.scalars(select(BankAccount))}
    loaded = 0
    for filename, account_label, period in SAMPLE_STATEMENTS:
        path = samples_dir / filename
        if not path.exists():
            log.warning("sample missing, skipping: %s", filename)
            continue
        account = accounts.get(account_label)
        if account is None:
            continue
        data = path.read_bytes()
        digest = sha256_bytes(data)
        if db.scalar(
            select(BankStatement).where(
                BankStatement.bank_account_id == account.id,
                BankStatement.file_hash == digest,
            )
        ):
            continue
        key = statement_key(account.bank.code, period, filename)
        get_storage().save(key, data)
        statement = BankStatement(
            bank_account_id=account.id, period_start=period, period_end=period,
            original_filename=filename, stored_key=key, file_hash=digest,
            file_size=len(data), content_type="application/pdf", status="UPLOADED",
            is_demo=True,
        )
        db.add(statement)
        db.flush()
        db.commit()
        result = process_statement(db, statement.id, auto_match=False)
        log.info("  %s -> %s (%s new)", filename, result.get("status"), result.get("inserted"))
        loaded += 1
    return loaded


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed the database.")
    parser.add_argument("--demo", action="store_true", help="also create demo shops data")
    parser.add_argument(
        "--with-statements", action="store_true",
        help="load the sample bank PDFs from ../samples and process them",
    )
    parser.add_argument("--samples-dir", default="../samples")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        ensure_reference_data(db)
        email, password = ensure_admin(db)
        db.commit()
        log.info("reference data ready")
        if password:
            log.info("ADMIN ACCOUNT  %s", email)
            log.info("ADMIN PASSWORD %s   <- change this after signing in", password)
        else:
            log.info("admin account already exists: %s", email)

        if args.demo:
            users = ensure_demo_users(db)
            sheets = ensure_demo_sheets(db)
            db.commit()
            log.info("demo: %s shop users, %s daily sheets", len(users), sheets)
            for demo_email, demo_password in users:
                log.info("  %s / %s", demo_email, demo_password)

        if args.with_statements:
            count = ingest_sample_statements(db, Path(args.samples_dir))
            db.commit()
            log.info("loaded %s sample statements", count)

        if args.demo:
            from app.services.reconciliation import run_batch

            summary = run_batch(db, match_settings(db))
            db.commit()
            log.info("matching: %s", summary)
    finally:
        db.close()


if __name__ == "__main__":
    main()
