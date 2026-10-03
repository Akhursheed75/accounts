"""Cash payments on the daily sheet.

Cash has no bank when it is taken. It waits as a pending deposit, and is matched
to the bank line where it was eventually banked — any bank, same currency, on or
after the day it was received, and only ever confirmed by a person."""
from __future__ import annotations

from sqlalchemy import text

from app.db.session import engine
from tests.conftest import make_sheet
from tests.test_reconciliation import add_bank_transaction, run_matching, status_of


def cash(amount: str, currency: str = "USD", **extra) -> dict:
    return {"payment_method": "CASH", "currency_code": currency, "amount": amount, **extra}


def bank(world, code: str, amount: str, currency: str = "USD") -> dict:
    return {"bank_id": world["banks"][code], "currency_code": currency, "amount": amount}


def test_cash_is_saved_without_a_bank_and_shown_as_pending_deposit(client, admin_headers, world):
    body = make_sheet(
        client, admin_headers, shop_id=world["shops"]["SHOP1"], business_date="2026-08-10",
        transfers=[cash("150.00")],
    ).json()
    payment = body["transfers"][0]
    assert payment["payment_method"] == "CASH"
    assert payment["bank_id"] is None
    assert payment["match_status"] == "PENDING_DEPOSIT"


def test_a_stale_bank_choice_is_dropped_when_the_row_is_cash(client, admin_headers, world):
    # The form may still hold the last bank in its dropdown; it must not be stored.
    body = make_sheet(
        client, admin_headers, shop_id=world["shops"]["SHOP1"], business_date="2026-08-10",
        transfers=[cash("150.00", bank_id=world["banks"]["BAC"],
                        bank_account_id=world["accounts"]["BAC Dollars"])],
    ).json()
    payment = body["transfers"][0]
    assert payment["bank_id"] is None
    assert payment["bank_account_id"] is None


def test_a_bank_payment_still_needs_a_bank(client, admin_headers, world):
    make_sheet(
        client, admin_headers, shop_id=world["shops"]["SHOP1"], business_date="2026-08-10",
        transfers=[{"currency_code": "USD", "amount": "10.00"}], expect=422,
    )


def test_the_database_refuses_a_bank_payment_without_a_bank(world):
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO shop_daily_records (shop_id, business_date, status, bale_count, "
            "invoice_count, total_sales_usd, total_sales_nio, delivery_usd, delivery_nio, "
            "commercial_invoice_usd, commercial_invoice_nio, credit_usd, credit_nio, "
            "opening_balance_usd, opening_balance_nio, closing_balance_usd, "
            "closing_balance_nio, closing_balance_source, observations, is_demo) "
            "VALUES (:s, '2026-08-01', 'DRAFT', 0,0,0,0,0,0,0,0,0,0,0,0,0,0,'COMPUTED','',false)"
        ), {"s": world["shops"]["SHOP1"]})
    try:
        with engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO shop_transfers (daily_record_id, payment_method, bank_id, "
                "currency_code, amount, note, is_ignored) "
                "SELECT id, 'BANK', NULL, 'USD', 5, '', false FROM shop_daily_records LIMIT 1"
            ))
    except Exception as exc:  # noqa: BLE001
        assert "bank_payment_has_bank" in str(exc)
    else:
        raise AssertionError("a BANK payment with no bank was accepted by the database")


def test_cash_and_bank_are_totalled_separately_and_both_reduce_the_balance(
    client, admin_headers, world
):
    body = make_sheet(
        client, admin_headers, shop_id=world["shops"]["SHOP1"], business_date="2026-08-11",
        sales_usd="1000.00",
        transfers=[bank(world, "BAC", "600.00"), cash("400.00")],
    ).json()
    assert body["transfer_totals"]["USD"] == "600.00"
    assert body["cash_totals"]["USD"] == "400.00"
    usd = body["balance"]["USD"]
    assert usd["computed"] == "0.00"   # 1000 sales − 600 banked − 400 cash
    steps = {s["key"]: s["amount"] for s in usd["steps"]}
    assert steps["total_transfers"] == "600.00"
    assert steps["total_cash"] == "400.00"


def test_cash_is_suggested_against_a_later_deposit_in_any_bank_never_auto_confirmed(
    client, admin_headers, world, db
):
    # The shop took $250 in cash on the 12th and banked it at LAFISE on the 14th.
    add_bank_transaction(
        db, world, account_label="LAFISE Dollars", amount="250.00",
        txn_date="2026-08-14", currency="USD",
    )
    sheet = make_sheet(
        client, admin_headers, shop_id=world["shops"]["SHOP1"], business_date="2026-08-12",
        transfers=[cash("250.00")],
    ).json()
    row = status_of(client, admin_headers, sheet["transfers"][0]["id"])
    assert row["status"] == "POSSIBLE"
    assert row["confirmed"] is None
    assert len(row["suggestions"]) == 1
    signals = {s["signal"] for s in row["suggestions"][0]["score_breakdown"]}
    assert "cash" in signals and "bank" not in signals

    confirmed = client.post(
        "/api/v1/reconciliation/confirm",
        json={"match_id": row["suggestions"][0]["id"]}, headers=admin_headers,
    )
    assert confirmed.status_code == 200, confirmed.text
    assert status_of(client, admin_headers, sheet["transfers"][0]["id"])["status"] == "MATCHED"


def test_cash_cannot_match_a_deposit_made_before_it_was_received(
    client, admin_headers, world, db
):
    add_bank_transaction(
        db, world, account_label="BAC Dollars", amount="90.00",
        txn_date="2026-08-19", currency="USD",
    )
    sheet = make_sheet(
        client, admin_headers, shop_id=world["shops"]["SHOP1"], business_date="2026-08-20",
        transfers=[cash("90.00")],
    ).json()
    row = status_of(client, admin_headers, sheet["transfers"][0]["id"])
    assert row["status"] == "PENDING_DEPOSIT"
    assert row["suggestions"] == []


def test_cash_looks_only_as_far_forward_as_the_deposit_window(
    client, admin_headers, world, db
):
    add_bank_transaction(
        db, world, account_label="BAC Dollars", amount="75.00",
        txn_date="2026-08-29", currency="USD",            # 9 days later; window is 7
    )
    sheet = make_sheet(
        client, admin_headers, shop_id=world["shops"]["SHOP1"], business_date="2026-08-20",
        transfers=[cash("75.00")],
    ).json()
    assert status_of(client, admin_headers, sheet["transfers"][0]["id"])["status"] == (
        "PENDING_DEPOSIT"
    )

    client.put("/api/v1/settings/matching", json={"cash_deposit_window_days": 10},
               headers=admin_headers)
    run_matching(client, admin_headers)
    assert status_of(client, admin_headers, sheet["transfers"][0]["id"])["status"] == "POSSIBLE"


def test_cash_never_matches_the_other_currency(client, admin_headers, world, db):
    add_bank_transaction(
        db, world, account_label="BAC Cordobas", amount="480.00",
        txn_date="2026-08-21", currency="NIO",
    )
    sheet = make_sheet(
        client, admin_headers, shop_id=world["shops"]["SHOP1"], business_date="2026-08-21",
        transfers=[cash("480.00", "USD")],
    ).json()
    assert status_of(client, admin_headers, sheet["transfers"][0]["id"])["status"] == (
        "PENDING_DEPOSIT"
    )


def test_switching_a_matched_bank_payment_to_cash_releases_the_old_match(
    client, admin_headers, world, db
):
    add_bank_transaction(
        db, world, account_label="BAC Dollars", amount="300.00",
        txn_date="2026-08-22", currency="USD", reference="R1",
    )
    sheet = make_sheet(
        client, admin_headers, shop_id=world["shops"]["SHOP1"], business_date="2026-08-22",
        transfers=[bank(world, "BAC", "300.00")],
    ).json()
    transfer = sheet["transfers"][0]
    assert transfer["match_status"] == "MATCHED"

    payload = {
        "transfers": [{"id": transfer["id"], **cash("300.00")}],
        "status": "SUBMITTED",
    }
    updated = client.put(
        f"/api/v1/accounting/daily/{sheet['id']}", json=payload, headers=admin_headers
    ).json()
    row = status_of(client, admin_headers, transfer["id"])
    # The old automatic match proved a BAC deposit; for cash it is only a candidate.
    assert updated["transfers"][0]["payment_method"] == "CASH"
    assert row["status"] == "POSSIBLE"
    assert any(not m["is_active"] for m in row["history"])


def test_daily_list_counts_pending_cash_apart_from_unmatched(client, admin_headers, world):
    make_sheet(
        client, admin_headers, shop_id=world["shops"]["SHOP1"], business_date="2026-08-23",
        transfers=[cash("10.00"), bank(world, "BAC", "11.00")],
    )
    row = client.get("/api/v1/accounting/daily", headers=admin_headers).json()["items"][0]
    assert row["pending_cash_count"] == 1
    assert row["unmatched_count"] == 1
    assert row["cash_total_usd"] == "10.00"
    assert row["transfer_total_usd"] == "11.00"
