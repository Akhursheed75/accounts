from __future__ import annotations

from decimal import Decimal

from tests.conftest import make_sheet


def test_creating_a_sheet_keeps_currencies_apart(client, admin_headers, world):
    body = make_sheet(
        client, admin_headers,
        shop_id=world["shops"]["SHOP1"], business_date="2026-08-11",
        sales_usd="1310.00", sales_nio="31840.00",
        transfers=[
            {"bank_id": world["banks"]["BAC"], "currency_code": "USD", "amount": "480.00"},
            {"bank_id": world["banks"]["BAC"], "currency_code": "NIO", "amount": "8275.00"},
            {"bank_id": world["banks"]["LAFISE"], "currency_code": "NIO", "amount": "8350.00"},
        ],
    ).json()
    assert body["transfer_totals"]["USD"] == "480.00"
    assert body["transfer_totals"]["NIO"] == "16625.00"
    # There is no combined figure anywhere in the response.
    assert "total" not in body["transfer_totals"]


def test_one_bank_may_receive_several_deposits_in_a_day(client, admin_headers, world):
    body = make_sheet(
        client, admin_headers,
        shop_id=world["shops"]["SHOP1"], business_date="2026-08-12",
        transfers=[
            {"bank_id": world["banks"]["BAC"], "currency_code": "USD", "amount": "100.00"},
            {"bank_id": world["banks"]["BAC"], "currency_code": "USD", "amount": "250.00"},
            {"bank_id": world["banks"]["BAC"], "currency_code": "USD", "amount": "60.00"},
        ],
    ).json()
    assert len(body["transfers"]) == 3
    assert body["transfer_totals"]["USD"] == "410.00"


def test_a_second_sheet_for_the_same_shop_and_day_is_refused(client, admin_headers, world):
    make_sheet(
        client, admin_headers,
        shop_id=world["shops"]["SHOP1"], business_date="2026-08-13", transfers=[],
    )
    response = make_sheet(
        client, admin_headers,
        shop_id=world["shops"]["SHOP1"], business_date="2026-08-13", transfers=[], expect=409,
    )
    assert "already exists" in response.json()["error"]["message"]


def test_closing_balance_is_computed_and_explained(client, admin_headers, world):
    body = make_sheet(
        client, admin_headers,
        shop_id=world["shops"]["SHOP1"], business_date="2026-08-14",
        sales_usd="1000.00", transfers=[
            {"bank_id": world["banks"]["BAC"], "currency_code": "USD", "amount": "400.00"},
        ],
    ).json()
    usd = body["balance"]["USD"]
    assert usd["computed"] == "600.00"          # 0 opening + 1000 sales - 400 banked
    assert usd["matches"] is True
    labels = [step["label"] for step in usd["steps"]]
    assert labels == ["Starting balance", "Total sales", "Total expenses", "Deposited to banks"]
    assert body["closing_balance_usd"] == "600.00"


def test_a_hand_entered_closing_balance_shows_the_difference(client, admin_headers, world):
    payload = {
        "shop_id": world["shops"]["SHOP1"], "business_date": "2026-08-15",
        "total_sales_usd": "1000.00", "transfers": [], "expenses": [], "bale_records": [],
        "closing_balance_source": "MANUAL", "closing_balance_usd": "950.00",
        "status": "DRAFT",
    }
    body = client.post("/api/v1/accounting/daily", json=payload, headers=admin_headers).json()
    usd = body["balance"]["USD"]
    assert usd["entered"] == "950.00"
    assert usd["computed"] == "1000.00"
    assert usd["difference"] == "-50.00"
    assert usd["matches"] is False


def test_negative_and_absurd_amounts_are_rejected(client, admin_headers, world):
    for amount in ["-5.00", "0"]:
        response = client.post(
            "/api/v1/accounting/daily",
            json={
                "shop_id": world["shops"]["SHOP1"], "business_date": "2026-08-16",
                "transfers": [
                    {"bank_id": world["banks"]["BAC"], "currency_code": "USD", "amount": amount}
                ],
                "expenses": [], "bale_records": [],
            },
            headers=admin_headers,
        )
        assert response.status_code == 422


def test_a_future_date_is_rejected(client, admin_headers, world):
    make_sheet(
        client, admin_headers,
        shop_id=world["shops"]["SHOP1"], business_date="2099-01-01",
        transfers=[], expect=422,
    )


def test_a_transfer_currency_must_match_the_chosen_account(client, admin_headers, world):
    response = client.post(
        "/api/v1/accounting/daily",
        json={
            "shop_id": world["shops"]["SHOP1"], "business_date": "2026-08-17",
            "transfers": [
                {
                    "bank_id": world["banks"]["BAC"],
                    "bank_account_id": world["accounts"]["BAC Dollars"],
                    "currency_code": "NIO",
                    "amount": "100.00",
                }
            ],
            "expenses": [], "bale_records": [],
        },
        headers=admin_headers,
    )
    assert response.status_code == 422
    assert "USD" in response.json()["error"]["message"]


def test_editing_a_sheet_is_audited_with_before_and_after(client, admin_headers, world):
    created = make_sheet(
        client, admin_headers,
        shop_id=world["shops"]["SHOP1"], business_date="2026-08-18",
        sales_usd="100.00", transfers=[],
    ).json()
    client.put(
        f"/api/v1/accounting/daily/{created['id']}",
        json={
            "shop_id": world["shops"]["SHOP1"], "business_date": "2026-08-18",
            "total_sales_usd": "175.00", "transfers": [], "expenses": [], "bale_records": [],
        },
        headers=admin_headers,
    )
    logs = client.get(
        "/api/v1/audit-logs",
        params={"action": "EDIT_ACCOUNTING", "record_id": created["id"]},
        headers=admin_headers,
    ).json()["items"]
    assert logs
    entry = logs[0]
    assert entry["old_values"]["total_sales_usd"] == "100.00"
    assert entry["new_values"]["total_sales_usd"] == "175.00"


def test_archiving_keeps_the_record_out_of_lists_but_in_the_database(
    client, admin_headers, world
):
    created = make_sheet(
        client, admin_headers,
        shop_id=world["shops"]["SHOP1"], business_date="2026-08-19", transfers=[],
    ).json()
    assert client.delete(
        f"/api/v1/accounting/daily/{created['id']}", headers=admin_headers
    ).status_code == 200

    listed = client.get("/api/v1/accounting/daily", headers=admin_headers).json()
    assert created["id"] not in [row["id"] for row in listed["items"]]

    logs = client.get(
        "/api/v1/audit-logs",
        params={"action": "DELETE_ACCOUNTING", "record_id": created["id"]},
        headers=admin_headers,
    ).json()["items"]
    assert logs, "archiving must leave an audit trail"

    # The same shop and date can now be used again.
    make_sheet(
        client, admin_headers,
        shop_id=world["shops"]["SHOP1"], business_date="2026-08-19", transfers=[],
    )
