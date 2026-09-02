from __future__ import annotations

import os
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg://reconcilia:reconcilia@127.0.0.1:5432/reconcilia_test",
)
os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("STORAGE_ROOT", "./storage-test")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.core.security import hash_password  # noqa: E402
from app.db.session import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import (  # noqa: E402
    Bank, BankAccount, Base, City, Currency, Role, Shop, User, UserShop,
)
from app.seed import ensure_reference_data  # noqa: E402

SAMPLES = Path(__file__).resolve().parents[2] / "samples"


@pytest.fixture(scope="session", autouse=True)
def database():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    # The partial unique indexes that guarantee one match per side are declared
    # on the models, so create_all builds them too; assert that they exist,
    # because half of the reconciliation guarantees live in the database.
    with engine.connect() as conn:
        names = {
            row[0]
            for row in conn.execute(
                text("SELECT indexname FROM pg_indexes WHERE tablename = 'reconciliation_matches'")
            )
        }
    assert "uq_recon_active_bank_txn" in names
    assert "uq_recon_active_transfer" in names
    yield
    Base.metadata.drop_all(engine)


@pytest.fixture()
def db(database):
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


def _truncate() -> None:
    with engine.begin() as conn:
        tables = ", ".join(f'"{t}"' for t in Base.metadata.tables)
        conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))


@pytest.fixture()
def world(database):
    """A clean company: reference data, three shops, four banks, three users."""
    _truncate()
    session = SessionLocal()
    ensure_reference_data(session)
    session.commit()

    admin_role = session.query(Role).filter_by(code="ADMIN").one()
    shop_role = session.query(Role).filter_by(code="SHOP_USER").one()

    admin = User(
        email="admin@test.local", full_name="Admin", role_id=admin_role.id,
        password_hash=hash_password("AdminPassword1"),
    )
    session.add(admin)

    shops = session.query(Shop).order_by(Shop.code).all()
    shop_user = User(
        email="shop1@test.local", full_name="Shop 1 user", role_id=shop_role.id,
        password_hash=hash_password("ShopPassword1"),
    )
    session.add(shop_user)
    session.flush()
    session.add(UserShop(user_id=shop_user.id, shop_id=shops[0].id))
    session.commit()

    data = {
        "shops": {s.code: s.id for s in session.query(Shop)},
        "banks": {b.code: b.id for b in session.query(Bank)},
        "accounts": {a.label: a.id for a in session.query(BankAccount)},
    }
    session.close()
    return data


@pytest.fixture()
def client(world):
    with TestClient(app) as test_client:
        yield test_client


def login(client: TestClient, email: str, password: str) -> dict:
    response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return {"authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture()
def admin_headers(client):
    return login(client, "admin@test.local", "AdminPassword1")


@pytest.fixture()
def shop_headers(client):
    return login(client, "shop1@test.local", "ShopPassword1")


def make_sheet(
    client: TestClient,
    headers: dict,
    *,
    shop_id: int,
    business_date: str,
    transfers: list[dict],
    sales_usd: str = "0.00",
    sales_nio: str = "0.00",
    expect: int = 201,
):
    payload = {
        "shop_id": shop_id,
        "business_date": business_date,
        "total_sales_usd": sales_usd,
        "total_sales_nio": sales_nio,
        "transfers": transfers,
        "expenses": [],
        "bale_records": [],
        "status": "SUBMITTED",
    }
    response = client.post("/api/v1/accounting/daily", json=payload, headers=headers)
    assert response.status_code == expect, response.text
    return response
