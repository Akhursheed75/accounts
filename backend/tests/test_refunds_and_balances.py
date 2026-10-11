"""A payment the bank shows on another day, a refund paid back out of the
account, and each account's balance day by day."""
from __future__ import annotations

from decimal import Decimal

from app.models import BankStatement
from tests.test_reconciliation import add_bank_transaction


def bank_row(world, bank, currency, amount, **extra):
    return {"payment_method": "BANK", "bank_id": world["banks"][bank],
            "currency_code": currency, "amount": amount, **extra}


def save(client, headers, world, shop, day, transfers):
    response = client.post("/api/v1/accounting/daily", json={
        "shop_id": world["shops"][shop], "business_date": day, "status": "SUBMITTED",
        "transfers": transfers, "expenses": [], "bale_records": [],
    }, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def statuses(body):
    return [t["match_status"] for t in body["transfers"]]


# ------------------------------------------------- a deposit of an earlier day
def test_a_deposit_dated_on_the_sheet_is_found_on_that_days_statement(
    client, admin_headers, world, db
):
    # The sheet of 1 Oct lists C$3,823 deposited on 30 Sep; the bank has it on 30 Sep,
    # and an identical amount on 3 Oct that belongs to someone else.
    on_30 = add_bank_transaction(db, world, account_label="BAC Cordobas", amount="3823.00",
                                 txn_date="2026-09-30", currency="NIO")
    add_bank_transaction(db, world, account_label="BAC Cordobas", amount="3823.00",
                         txn_date="2026-10-03", currency="NIO", description="other")
    body = save(client, admin_headers, world, "SHOP3", "2026-10-01",
                [bank_row(world, "BAC", "NIO", "3823.00", bank_date="2026-09-30", reference="")])
    transfer = body["transfers"][0]
    assert transfer["bank_date"] == "2026-09-30"
    assert transfer["match_status"] == "MATCHED"
    assert transfer["matched_transaction_id"] == on_30


def test_the_live_check_uses_the_bank_date(client, admin_headers, world, db):
    add_bank_transaction(db, world, account_label="BAC Cordobas", amount="3823.00",
                         txn_date="2026-09-30", currency="NIO")
    body = {"business_date": "2026-10-01", "details": [
        {"bank_id": world["banks"]["BAC"], "currency_code": "NIO", "amount": "3823.00",
         "bank_date": "2026-09-30"},
        {"bank_id": world["banks"]["BAC"], "currency_code": "NIO", "amount": "3823.00"},
    ], "totals": []}
    result = client.post("/api/v1/accounting/daily/preview-match", json=body,
                         headers=admin_headers).json()
    # Without the date it looks on 1 Oct, whose statement has no such line uploaded.
    assert [d["status"] for d in result["details"]] == ["FOUND", "NO_STATEMENT"]


# ------------------------------------------------------------------ refunds
def test_a_refund_matches_the_debit_that_paid_it(client, admin_headers, world, db):
    deposit = add_bank_transaction(db, world, account_label="LAFISE Dollars", amount="300.00",
                                   txn_date="2026-10-01", currency="USD")
    refund = add_bank_transaction(db, world, account_label="LAFISE Dollars", amount="300.00",
                                  txn_date="2026-10-03", currency="USD", direction="DEBIT",
                                  description="Devolucion")
    first = save(client, admin_headers, world, "SHOP1", "2026-10-01",
                 [bank_row(world, "LAFISE", "USD", "300.00")])
    assert first["transfers"][0]["matched_transaction_id"] == deposit
    later = save(client, admin_headers, world, "SHOP1", "2026-10-03",
                 [bank_row(world, "LAFISE", "USD", "300.00", direction="DEBIT")])
    transfer = later["transfers"][0]
    assert transfer["direction"] == "DEBIT"
    assert transfer["matched_transaction_id"] == refund
    # The refund takes money out of what the shop banked that day.
    from app.models import ShopDailyRecord
    from app.services.accounting import transfer_totals
    db.expire_all()
    assert transfer_totals(db.get(ShopDailyRecord, later["id"]))["USD"] == Decimal("-300.00")


def test_a_refund_never_takes_a_deposit_line_or_the_other_way(client, admin_headers, world, db):
    add_bank_transaction(db, world, account_label="LAFISE Dollars", amount="120.00",
                         txn_date="2026-10-01", currency="USD")
    body = save(client, admin_headers, world, "SHOP1", "2026-10-01",
                [bank_row(world, "LAFISE", "USD", "120.00", direction="DEBIT")])
    assert statuses(body) == ["UNMATCHED"]
    live = client.post("/api/v1/accounting/daily/preview-match", json={
        "business_date": "2026-10-01", "details": [
            {"bank_id": world["banks"]["LAFISE"], "currency_code": "USD", "amount": "120.00",
             "direction": "DEBIT"}], "totals": []}, headers=admin_headers).json()
    assert live["details"][0]["status"] in ("NO_STATEMENT", "NOT_FOUND")


def test_cash_cannot_be_a_refund(client, admin_headers, world):
    response = client.post("/api/v1/accounting/daily", json={
        "shop_id": world["shops"]["SHOP1"], "business_date": "2026-10-01",
        "transfers": [{"payment_method": "CASH", "currency_code": "USD", "amount": "5.00",
                       "direction": "DEBIT"}],
        "expenses": [], "bale_records": [],
    }, headers=admin_headers)
    assert response.status_code == 422


# ------------------------------------------------------------- bank balances
def account(body, label):
    return next(a for a in body if a["label"] == label)


def test_balances_from_the_statement_from_a_person_and_calculated(
    client, admin_headers, world, db
):
    # LAFISE prints its balance: the statement's closing balance is kept.
    add_bank_transaction(db, world, account_label="LAFISE Cordobas", amount="1000.00",
                         txn_date="2026-10-01", currency="NIO")
    statement = db.query(BankStatement).filter_by(
        bank_account_id=world["accounts"]["LAFISE Cordobas"]).one()
    statement.statement_closing_balance = Decimal("5000.00")
    db.commit()

    # BANPRO prints none: the person types the closing of 1 Oct; 2 Oct is calculated.
    add_bank_transaction(db, world, account_label="BANPRO Cordobas", amount="3153.00",
                         txn_date="2026-10-01", currency="NIO")
    add_bank_transaction(db, world, account_label="BANPRO Cordobas", amount="500.00",
                         txn_date="2026-10-02", currency="NIO", description="b")
    add_bank_transaction(db, world, account_label="BANPRO Cordobas", amount="200.00",
                         txn_date="2026-10-02", currency="NIO", direction="DEBIT", description="c")
    put = client.put(f"/api/v1/bank-balances/{world['accounts']['BANPRO Cordobas']}/2026-10-01",
                     json={"closing_balance": "10000.00"}, headers=admin_headers)
    assert put.status_code == 200, put.text
    assert put.json()["source"] == "ENTERED"

    body = client.get("/api/v1/bank-balances", headers=admin_headers).json()
    lafise = account(body, "LAFISE Cordobas")
    assert lafise["latest"]["closing"] == "5000.00" and lafise["latest"]["source"] == "STATEMENT"
    assert lafise["latest"]["opening"] == "4000.00"
    banpro = account(body, "BANPRO Cordobas")
    days = {d["date"]: d for d in banpro["days"]}
    assert days["2026-10-01"]["closing"] == "10000.00"
    assert days["2026-10-02"]["opening"] == "10000.00"
    assert days["2026-10-02"]["credits"] == "500.00" and days["2026-10-02"]["debits"] == "200.00"
    assert days["2026-10-02"]["closing"] == "10300.00"
    assert days["2026-10-02"]["source"] == "CALCULATED"

    # Typing the bank's figure for 2 Oct that disagrees shows the difference.
    client.put(f"/api/v1/bank-balances/{world['accounts']['BANPRO Cordobas']}/2026-10-02",
               json={"closing_balance": "10350.00"}, headers=admin_headers)
    body = client.get("/api/v1/bank-balances", headers=admin_headers).json()
    day2 = next(d for d in account(body, "BANPRO Cordobas")["days"] if d["date"] == "2026-10-02")
    assert day2["closing"] == "10350.00" and day2["difference"] == "50.00"

    # Clearing it goes back to the calculation.
    client.put(f"/api/v1/bank-balances/{world['accounts']['BANPRO Cordobas']}/2026-10-02",
               json={"closing_balance": None}, headers=admin_headers)
    body = client.get("/api/v1/bank-balances", headers=admin_headers).json()
    day2 = next(d for d in account(body, "BANPRO Cordobas")["days"] if d["date"] == "2026-10-02")
    assert day2["source"] == "CALCULATED"


def test_a_shop_user_cannot_type_bank_balances(client, shop_headers, world):
    response = client.put(f"/api/v1/bank-balances/{world['accounts']['BANPRO Cordobas']}/2026-10-01",
                          json={"closing_balance": "1.00"}, headers=shop_headers)
    assert response.status_code == 403
