"""The matching rules, stated as tests.

Each test names the situation it protects against; if one of these ever goes
red, real money is about to be reconciled against the wrong bank line."""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from io import BytesIO

import pytest
from sqlalchemy import select

from app.models import BankAccount, BankStatement, BankTransaction, Shop
from tests.conftest import SAMPLES, make_sheet


def add_bank_transaction(
    db, world, *, account_label: str, amount: str, txn_date: str,
    currency: str, direction: str = "CREDIT", description: str = "Deposit",
    reference: str | None = None,
):
    """Puts one line into the bank side directly, so a test can describe the
    exact situation it is about rather than needing a whole PDF."""
    account = db.get(BankAccount, world["accounts"][account_label])
    statement = db.scalar(
        select(BankStatement).where(BankStatement.bank_account_id == account.id)
    )
    if statement is None:
        statement = BankStatement(
            bank_account_id=account.id, original_filename="fixture.pdf",
            stored_key=f"test/{account.id}.pdf", file_hash=f"hash-{account.id}",
            file_size=1, content_type="application/pdf", status="PROCESSED",
        )
        db.add(statement)
        db.flush()
    value = Decimal(amount)
    txn = BankTransaction(
        statement_id=statement.id, bank_account_id=account.id, bank_id=account.bank_id,
        txn_date=date.fromisoformat(txn_date), description=description,
        reference=reference, external_id=reference,
        debit=value if direction == "DEBIT" else Decimal("0.00"),
        credit=value if direction == "CREDIT" else Decimal("0.00"),
        amount=value, direction=direction, currency_code=currency,
        dedupe_hash=f"{account.id}-{txn_date}-{amount}-{description}-{reference}",
    )
    db.add(txn)
    db.commit()
    return txn.id


def run_matching(client, headers, **body):
    return client.post("/api/v1/reconciliation/run", json=body, headers=headers).json()


def status_of(client, headers, transfer_id: int) -> dict:
    rows = client.get(
        "/api/v1/reconciliation", params={"page_size": 200}, headers=headers
    ).json()["items"]
    return next(row for row in rows if row["transfer"]["id"] == transfer_id)


# ------------------------------------------------------- the happy exact case
def test_same_amount_same_currency_same_date_matches(client, admin_headers, world, db):
    add_bank_transaction(
        db, world, account_label="BAC Dollars", amount="480.00",
        txn_date="2026-08-25", currency="USD", reference="XXX123",
    )
    sheet = make_sheet(
        client, admin_headers, shop_id=world["shops"]["SHOP1"],
        business_date="2026-08-25",
        transfers=[{"bank_id": world["banks"]["BAC"], "currency_code": "USD",
                    "amount": "480.00"}],
    ).json()
    row = status_of(client, admin_headers, sheet["transfers"][0]["id"])
    assert row["status"] == "MATCHED"
    assert row["confirmed"]["match_type"] == "EXACT"
    assert row["confirmed"]["confidence"] >= 95
    signals = {s["signal"] for s in row["confirmed"]["score_breakdown"]}
    assert {"amount", "currency", "bank", "date"} <= signals


# --------------------------------------------------------------- currency
def test_the_same_number_in_another_currency_never_matches(client, admin_headers, world, db):
    add_bank_transaction(
        db, world, account_label="BAC Cordobas", amount="480.00",
        txn_date="2026-08-25", currency="NIO",
    )
    sheet = make_sheet(
        client, admin_headers, shop_id=world["shops"]["SHOP1"],
        business_date="2026-08-25",
        transfers=[{"bank_id": world["banks"]["BAC"], "currency_code": "USD",
                    "amount": "480.00"}],
    ).json()
    row = status_of(client, admin_headers, sheet["transfers"][0]["id"])
    assert row["status"] == "UNMATCHED"
    assert row["suggestions"] == []


def test_a_cross_currency_manual_match_is_refused(client, admin_headers, world, db):
    txn_id = add_bank_transaction(
        db, world, account_label="BAC Cordobas", amount="480.00",
        txn_date="2026-08-25", currency="NIO",
    )
    sheet = make_sheet(
        client, admin_headers, shop_id=world["shops"]["SHOP1"],
        business_date="2026-08-25",
        transfers=[{"bank_id": world["banks"]["BAC"], "currency_code": "USD",
                    "amount": "480.00"}],
    ).json()
    response = client.post(
        "/api/v1/reconciliation/match",
        json={"shop_transfer_id": sheet["transfers"][0]["id"], "bank_transaction_id": txn_id},
        headers=admin_headers,
    )
    assert response.status_code == 422
    assert "Currency mismatch" in response.json()["error"]["message"]


# ----------------------------------------------------------------- amounts
def test_a_thousand_times_the_amount_is_not_a_match(client, admin_headers, world, db):
    # The example from the specification: C$8,350 must never meet C$8,350,000.
    add_bank_transaction(
        db, world, account_label="BAC Cordobas", amount="8350000.00",
        txn_date="2026-08-25", currency="NIO",
    )
    sheet = make_sheet(
        client, admin_headers, shop_id=world["shops"]["SHOP1"],
        business_date="2026-08-25",
        transfers=[{"bank_id": world["banks"]["BAC"], "currency_code": "NIO",
                    "amount": "8350.00"}],
    ).json()
    assert status_of(client, admin_headers, sheet["transfers"][0]["id"])["status"] == "UNMATCHED"


def test_a_nearly_equal_amount_is_not_a_match_by_default(client, admin_headers, world, db):
    add_bank_transaction(
        db, world, account_label="BAC Dollars", amount="480.01",
        txn_date="2026-08-25", currency="USD",
    )
    sheet = make_sheet(
        client, admin_headers, shop_id=world["shops"]["SHOP1"],
        business_date="2026-08-25",
        transfers=[{"bank_id": world["banks"]["BAC"], "currency_code": "USD",
                    "amount": "480.00"}],
    ).json()
    assert status_of(client, admin_headers, sheet["transfers"][0]["id"])["status"] == "UNMATCHED"


# -------------------------------------------------------------------- banks
def test_the_right_amount_at_the_wrong_bank_does_not_match(client, admin_headers, world, db):
    add_bank_transaction(
        db, world, account_label="LAFISE Dollars", amount="480.00",
        txn_date="2026-08-25", currency="USD",
    )
    sheet = make_sheet(
        client, admin_headers, shop_id=world["shops"]["SHOP1"],
        business_date="2026-08-25",
        transfers=[{"bank_id": world["banks"]["BAC"], "currency_code": "USD",
                    "amount": "480.00"}],
    ).json()
    assert status_of(client, admin_headers, sheet["transfers"][0]["id"])["status"] == "UNMATCHED"


# --------------------------------------------------------------------- dates
def test_a_deposit_that_lands_the_next_day_still_matches(client, admin_headers, world, db):
    add_bank_transaction(
        db, world, account_label="BAC Dollars", amount="480.00",
        txn_date="2026-08-26", currency="USD",
    )
    sheet = make_sheet(
        client, admin_headers, shop_id=world["shops"]["SHOP1"],
        business_date="2026-08-25",
        transfers=[{"bank_id": world["banks"]["BAC"], "currency_code": "USD",
                    "amount": "480.00"}],
    ).json()
    row = status_of(client, admin_headers, sheet["transfers"][0]["id"])
    # One day apart scores below the automatic threshold, so a person decides.
    assert row["status"] == "POSSIBLE"
    assert row["suggestions"][0]["date_delta_days"] == 1


def test_a_deposit_far_outside_the_window_is_not_offered(client, admin_headers, world, db):
    add_bank_transaction(
        db, world, account_label="BAC Dollars", amount="480.00",
        txn_date="2026-09-20", currency="USD",
    )
    sheet = make_sheet(
        client, admin_headers, shop_id=world["shops"]["SHOP1"],
        business_date="2026-08-25",
        transfers=[{"bank_id": world["banks"]["BAC"], "currency_code": "USD",
                    "amount": "480.00"}],
    ).json()
    assert status_of(client, admin_headers, sheet["transfers"][0]["id"])["status"] == "UNMATCHED"


# ------------------------------------------------------------------ ambiguity
def test_two_identical_deposits_are_offered_not_guessed(client, admin_headers, world, db):
    for reference in ("REF-A", "REF-B"):
        add_bank_transaction(
            db, world, account_label="BAC Dollars", amount="250.00",
            txn_date="2026-08-25", currency="USD", reference=reference,
            description=f"Deposit {reference}",
        )
    sheet = make_sheet(
        client, admin_headers, shop_id=world["shops"]["SHOP1"],
        business_date="2026-08-25",
        transfers=[{"bank_id": world["banks"]["BAC"], "currency_code": "USD",
                    "amount": "250.00"}],
    ).json()
    row = status_of(client, admin_headers, sheet["transfers"][0]["id"])
    assert row["status"] == "POSSIBLE"
    assert len(row["suggestions"]) == 2
    assert row["confirmed"] is None


def test_a_matching_reference_breaks_the_tie(client, admin_headers, world, db):
    add_bank_transaction(
        db, world, account_label="BAC Dollars", amount="250.00",
        txn_date="2026-08-25", currency="USD", reference="99887766",
    )
    add_bank_transaction(
        db, world, account_label="BAC Dollars", amount="250.00",
        txn_date="2026-08-26", currency="USD", reference="00000000",
    )
    sheet = make_sheet(
        client, admin_headers, shop_id=world["shops"]["SHOP1"],
        business_date="2026-08-25",
        transfers=[{"bank_id": world["banks"]["BAC"], "currency_code": "USD",
                    "amount": "250.00", "reference": "99887766"}],
    ).json()
    row = status_of(client, admin_headers, sheet["transfers"][0]["id"])
    assert row["status"] == "MATCHED"
    details = " ".join(s["detail"] for s in row["confirmed"]["score_breakdown"])
    assert "99887766" in details


# ------------------------------------------------------ one match per side
def test_a_bank_transaction_cannot_be_claimed_twice(client, admin_headers, world, db):
    txn_id = add_bank_transaction(
        db, world, account_label="BAC Dollars", amount="480.00",
        txn_date="2026-08-25", currency="USD",
    )
    first = make_sheet(
        client, admin_headers, shop_id=world["shops"]["SHOP1"],
        business_date="2026-08-25",
        transfers=[{"bank_id": world["banks"]["BAC"], "currency_code": "USD",
                    "amount": "480.00"}],
    ).json()
    assert status_of(client, admin_headers, first["transfers"][0]["id"])["status"] == "MATCHED"

    second = make_sheet(
        client, admin_headers, shop_id=world["shops"]["SHOP2"],
        business_date="2026-08-25",
        transfers=[{"bank_id": world["banks"]["BAC"], "currency_code": "USD",
                    "amount": "480.00"}],
    ).json()
    second_row = status_of(client, admin_headers, second["transfers"][0]["id"])
    assert second_row["status"] == "UNMATCHED"

    response = client.post(
        "/api/v1/reconciliation/match",
        json={"shop_transfer_id": second["transfers"][0]["id"], "bank_transaction_id": txn_id},
        headers=admin_headers,
    )
    assert response.status_code == 409
    assert "already reconciled" in response.json()["error"]["message"]


def test_the_database_refuses_a_second_confirmed_match_even_without_the_api(
    client, admin_headers, world, db
):
    from sqlalchemy.exc import IntegrityError

    from app.models import ReconciliationMatch

    txn_id = add_bank_transaction(
        db, world, account_label="BAC Dollars", amount="480.00",
        txn_date="2026-08-25", currency="USD",
    )
    sheet = make_sheet(
        client, admin_headers, shop_id=world["shops"]["SHOP1"],
        business_date="2026-08-25",
        transfers=[{"bank_id": world["banks"]["BAC"], "currency_code": "USD",
                    "amount": "480.00"}],
    ).json()
    other = make_sheet(
        client, admin_headers, shop_id=world["shops"]["SHOP2"],
        business_date="2026-08-25",
        transfers=[{"bank_id": world["banks"]["BAC"], "currency_code": "USD",
                    "amount": "999.00"}],
    ).json()

    db.add(
        ReconciliationMatch(
            shop_transfer_id=other["transfers"][0]["id"], bank_transaction_id=txn_id,
            status="CONFIRMED", match_type="MANUAL", confidence=100, is_active=True,
        )
    )
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


# --------------------------------------------------------- manual and undo
def test_manual_match_records_who_and_why(client, admin_headers, world, db):
    txn_id = add_bank_transaction(
        db, world, account_label="BAC Dollars", amount="480.00",
        txn_date="2026-08-30", currency="USD",
    )
    sheet = make_sheet(
        client, admin_headers, shop_id=world["shops"]["SHOP1"],
        business_date="2026-08-25",
        transfers=[{"bank_id": world["banks"]["BAC"], "currency_code": "USD",
                    "amount": "480.00"}],
    ).json()
    transfer_id = sheet["transfers"][0]["id"]
    assert status_of(client, admin_headers, transfer_id)["status"] == "UNMATCHED"

    match = client.post(
        "/api/v1/reconciliation/match",
        json={
            "shop_transfer_id": transfer_id,
            "bank_transaction_id": txn_id,
            "note": "Bank statement date was five days later",
        },
        headers=admin_headers,
    ).json()
    assert match["match_type"] == "MANUAL"
    assert match["matched_by_name"] == "Admin"

    logs = client.get(
        "/api/v1/audit-logs", params={"action": "MANUAL_MATCH"}, headers=admin_headers
    ).json()["items"]
    assert logs and "five days later" in logs[0]["summary"]


def test_unmatching_keeps_the_history(client, admin_headers, world, db):
    add_bank_transaction(
        db, world, account_label="BAC Dollars", amount="480.00",
        txn_date="2026-08-25", currency="USD",
    )
    sheet = make_sheet(
        client, admin_headers, shop_id=world["shops"]["SHOP1"],
        business_date="2026-08-25",
        transfers=[{"bank_id": world["banks"]["BAC"], "currency_code": "USD",
                    "amount": "480.00"}],
    ).json()
    transfer_id = sheet["transfers"][0]["id"]
    match_id = status_of(client, admin_headers, transfer_id)["confirmed"]["id"]

    undone = client.post(
        "/api/v1/reconciliation/unmatch",
        json={"match_id": match_id, "reason": "Belongs to Shop 2"},
        headers=admin_headers,
    ).json()
    assert undone["is_active"] is False
    assert undone["unmatched_by_name"] == "Admin"

    row = status_of(client, admin_headers, transfer_id)
    assert row["status"] == "UNMATCHED"
    assert len(row["history"]) == 1
    assert row["history"][0]["note"] == "Belongs to Shop 2"

    # And the transaction is free again.
    again = client.post(
        "/api/v1/reconciliation/match",
        json={
            "shop_transfer_id": transfer_id,
            "bank_transaction_id": undone["bank_transaction_id"],
        },
        headers=admin_headers,
    )
    assert again.status_code == 200


def test_unmatching_twice_is_refused(client, admin_headers, world, db):
    add_bank_transaction(
        db, world, account_label="BAC Dollars", amount="480.00",
        txn_date="2026-08-25", currency="USD",
    )
    sheet = make_sheet(
        client, admin_headers, shop_id=world["shops"]["SHOP1"],
        business_date="2026-08-25",
        transfers=[{"bank_id": world["banks"]["BAC"], "currency_code": "USD",
                    "amount": "480.00"}],
    ).json()
    match_id = status_of(client, admin_headers, sheet["transfers"][0]["id"])["confirmed"]["id"]
    client.post("/api/v1/reconciliation/unmatch", json={"match_id": match_id},
                headers=admin_headers)
    second = client.post("/api/v1/reconciliation/unmatch", json={"match_id": match_id},
                         headers=admin_headers)
    assert second.status_code == 409


def test_confirming_a_suggestion_removes_the_others(client, admin_headers, world, db):
    for reference in ("REF-A", "REF-B"):
        add_bank_transaction(
            db, world, account_label="BAC Dollars", amount="250.00",
            txn_date="2026-08-25", currency="USD", reference=reference,
        )
    sheet = make_sheet(
        client, admin_headers, shop_id=world["shops"]["SHOP1"],
        business_date="2026-08-25",
        transfers=[{"bank_id": world["banks"]["BAC"], "currency_code": "USD",
                    "amount": "250.00"}],
    ).json()
    transfer_id = sheet["transfers"][0]["id"]
    row = status_of(client, admin_headers, transfer_id)
    chosen = row["suggestions"][0]

    client.post("/api/v1/reconciliation/confirm", json={"match_id": chosen["id"]},
                headers=admin_headers)
    after = status_of(client, admin_headers, transfer_id)
    assert after["status"] == "MATCHED"
    assert after["suggestions"] == []

    # The transaction that lost is available for another payment.
    others = client.get(
        "/api/v1/bank-transactions", params={"match_status": "UNMATCHED"},
        headers=admin_headers,
    ).json()
    assert len(others["items"]) == 1


# ------------------------------------------------------------------ outgoing
def test_outgoing_transactions_are_not_matched_by_default(client, admin_headers, world, db):
    add_bank_transaction(
        db, world, account_label="BAC Dollars", amount="480.00",
        txn_date="2026-08-25", currency="USD", direction="DEBIT",
    )
    sheet = make_sheet(
        client, admin_headers, shop_id=world["shops"]["SHOP1"],
        business_date="2026-08-25",
        transfers=[{"bank_id": world["banks"]["BAC"], "currency_code": "USD",
                    "amount": "480.00"}],
    ).json()
    assert status_of(client, admin_headers, sheet["transfers"][0]["id"])["status"] == "UNMATCHED"


# ------------------------------------------------------------------ exceptions
def test_the_unmatched_page_reports_both_sides(client, admin_headers, world, db):
    add_bank_transaction(
        db, world, account_label="BAC Cordobas", amount="8350.00",
        txn_date="2026-08-25", currency="NIO", description="Deposit nobody claimed",
    )
    make_sheet(
        client, admin_headers, shop_id=world["shops"]["SHOP1"],
        business_date="2026-08-25",
        transfers=[{"bank_id": world["banks"]["LAFISE"], "currency_code": "NIO",
                    "amount": "1234.00"}],
    )
    summary = client.get("/api/v1/reconciliation/unmatched", headers=admin_headers).json()
    assert summary["totals"]["shop_payments"]["count"] == 1
    assert summary["totals"]["shop_payments"]["NIO"] == "1234.00"
    assert summary["totals"]["bank_transactions"]["count"] == 1
    assert summary["totals"]["bank_transactions"]["NIO"] == "8350.00"


def test_an_ignored_bank_line_leaves_the_exception_list(client, admin_headers, world, db):
    txn_id = add_bank_transaction(
        db, world, account_label="BAC Cordobas", amount="99.00",
        txn_date="2026-08-25", currency="NIO", description="Bank interest",
    )
    before = client.get("/api/v1/reconciliation/unmatched", headers=admin_headers).json()
    assert before["totals"]["bank_transactions"]["count"] == 1

    client.post(
        f"/api/v1/bank-transactions/{txn_id}/ignore",
        json={"reason": "Bank interest, never a shop deposit"},
        headers=admin_headers,
    )
    after = client.get("/api/v1/reconciliation/unmatched", headers=admin_headers).json()
    assert after["totals"]["bank_transactions"]["count"] == 0
