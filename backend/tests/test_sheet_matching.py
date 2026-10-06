"""1 October 2026, replayed: the six statements and the three shops' sheets.

Bank lines are the real ones from that day's statements; the sheets are what
Juigalpa, Jinotega and Managua actually wrote. Juigalpa and Jinotega list each
deposit; Managua writes only a total per bank."""
from __future__ import annotations

from decimal import Decimal

from app.services.sheet_matching import find_combinations
from tests.conftest import make_sheet
from tests.test_reconciliation import add_bank_transaction

DAY = "2026-10-01"

BANK_LINES = {
    "BAC Cordobas": ["18000.00", "19030.00", "130.00", "10000.00", "9921.00", "4823.00", "17822.00"],
    "BAC Dollars": ["10.00", "185.00", "1510.00", "10.00", "15.00"],
    "BANPRO Dollars": ["190.00", "1095.00", "235.00", "280.00"],
    "LAFISE Dollars": ["1395.00", "1046.00", "500.00", "240.00", "200.00", "230.00", "1300.00",
                       "2320.00", "195.00", "30.00", "1020.00", "425.00", "300.00"],
}


def load_statements(db, world):
    for label, amounts in BANK_LINES.items():
        currency = "USD" if label.endswith("Dollars") else "NIO"
        for n, amount in enumerate(amounts):
            add_bank_transaction(
                db, world, account_label=label, amount=amount, txn_date=DAY,
                currency=currency, description=f"{label} line {n}", reference=f"{label[:3]}{n}",
            )


def detail(world, bank, currency, amount):
    return {"bank_id": world["banks"][bank], "currency_code": currency, "amount": amount}


def total(world, bank, currency, amount):
    return {"bank_id": world["banks"][bank], "currency_code": currency, "amount": amount}


def save(client, headers, world, shop, *, transfers=(), totals=(), **extra):
    payload = {
        "shop_id": world["shops"][shop], "business_date": DAY,
        "transfers": list(transfers), "bank_totals": list(totals),
        "expenses": [], "bale_records": [], "status": "SUBMITTED", **extra,
    }
    response = client.post("/api/v1/accounting/daily", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def cell(body, bank_code, currency):
    return next(c for c in body["bank_cells"]
                if c["bank_code"] == bank_code and c["currency_code"] == currency)


def reload(client, headers, sheet):
    return client.get(f"/api/v1/accounting/daily/{sheet['id']}", headers=headers).json()


# ------------------------------------------------------------ the search
def test_combination_search_on_the_real_numbers():
    d = Decimal
    bac = [(1, d("10")), (2, d("185")), (3, d("1510")), (4, d("10")), (5, d("15"))]
    assert find_combinations(bac, d("1695")) == [[3, 2]]
    lafise = [(i, d(a)) for i, a in enumerate(BANK_LINES["LAFISE Dollars"])]
    assert len(find_combinations(lafise, d("7066"))) == 2       # two ways: a person decides
    assert find_combinations([(1, d("10")), (2, d("10"))], d("10")) == [[2], [1]]
    assert find_combinations(bac, d("99999")) == []


# --------------------------------------------------- deposit by deposit
def test_listed_deposits_turn_green(client, admin_headers, world, db):
    load_statements(db, world)
    juigalpa = save(
        client, admin_headers, world, "SHOP1",
        transfers=[detail(world, "BAC", "NIO", "17822.00")],
        totals=[total(world, "BAC", "NIO", "17822.00")],
    )
    jinotega = save(
        client, admin_headers, world, "SHOP2",
        transfers=[detail(world, "BAC", "NIO", "18000.00"), detail(world, "BAC", "NIO", "19030.00")],
        totals=[total(world, "BAC", "NIO", "37030.00")],
    )
    assert cell(juigalpa, "BAC", "NIO")["status"] == "MATCHED"
    assert cell(jinotega, "BAC", "NIO")["status"] == "MATCHED"
    assert cell(jinotega, "BAC", "NIO")["matched_sum"] == "37030.00"


def test_a_deposit_with_two_identical_bank_lines_is_left_for_a_person(
    client, admin_headers, world, db
):
    # Jinotega's $10: BAC shows a $10 RAPIBAC deposit and a $10 "sales 30/09".
    load_statements(db, world)
    jinotega = save(
        client, admin_headers, world, "SHOP2",
        transfers=[detail(world, "BAC", "USD", "10.00")],
        totals=[total(world, "BAC", "USD", "10.00")],
    )
    assert cell(jinotega, "BAC", "USD")["status"] == "POSSIBLE"


# ------------------------------------------------------- totals only
def test_a_bank_total_is_matched_when_only_one_combination_adds_up(
    client, admin_headers, world, db
):
    load_statements(db, world)
    managua = save(
        client, admin_headers, world, "SHOP3",
        totals=[total(world, "BAC", "USD", "1695.00"), total(world, "BANPRO", "USD", "1800.00")],
    )
    bac = cell(managua, "BAC", "USD")
    banpro = cell(managua, "BANPRO", "USD")
    assert bac["status"] == "MATCHED"
    assert sorted(l["amount"] for l in bac["lines"]) == ["1510.00", "185.00"]
    assert {l["source"] for l in bac["lines"]} == {"FOUND"}
    assert banpro["status"] == "MATCHED" and len(banpro["lines"]) == 4


def test_an_ambiguous_total_waits_for_a_person_who_picks_the_lines(
    client, admin_headers, world, db
):
    load_statements(db, world)
    managua = save(client, admin_headers, world, "SHOP3",
                   totals=[total(world, "LAFISE", "USD", "7066.00")])
    lafise = cell(managua, "LAFISE", "USD")
    assert lafise["status"] == "UNMATCHED"
    assert lafise["remaining"] == "7066.00"

    url = f"/api/v1/accounting/daily/{managua['id']}/bank-totals/{lafise['total_id']}"
    lines = client.get(f"{url}/candidates", headers=admin_headers).json()["lines"]
    assert len(lines) == 13
    # A person looks at the slips and ticks one of the combinations.
    combos = find_combinations([(l["id"], Decimal(l["amount"])) for l in lines], Decimal("7066"))
    chosen = combos[0]
    assert sum(Decimal(l["amount"]) for l in lines if l["id"] in chosen) == Decimal("7066")
    picked = client.post(f"{url}/pick", json={"transaction_ids": chosen}, headers=admin_headers)
    assert picked.status_code == 200, picked.text
    lafise = cell(picked.json(), "LAFISE", "USD")
    assert lafise["status"] == "MATCHED"
    assert {l["source"] for l in lafise["lines"]} == {"PICKED"}

    # Picking more than the total is refused.
    too_much = client.post(f"{url}/pick", json={"transaction_ids": [l["id"] for l in lines]},
                           headers=admin_headers)
    assert too_much.status_code == 422


def test_a_total_never_keeps_lines_a_shop_lists_later(client, admin_headers, world, db):
    load_statements(db, world)
    # Managua is entered first and its BAC C$ total happens to equal Jinotega's
    # two deposits: the only combination is 18,000 + 19,030, so it takes them.
    managua = save(client, admin_headers, world, "SHOP3",
                   totals=[total(world, "BAC", "NIO", "37030.00")])
    assert cell(managua, "BAC", "NIO")["status"] == "MATCHED"

    # Jinotega then lists those exact deposits. The day is re-solved: the
    # listed slips win, and Managua's total is open again rather than wrong.
    jinotega = save(
        client, admin_headers, world, "SHOP2",
        transfers=[detail(world, "BAC", "NIO", "18000.00"), detail(world, "BAC", "NIO", "19030.00")],
        totals=[total(world, "BAC", "NIO", "37030.00")],
    )
    assert cell(jinotega, "BAC", "NIO")["status"] == "MATCHED"
    managua = reload(client, admin_headers, managua)
    assert cell(managua, "BAC", "NIO")["status"] == "UNMATCHED"


def test_details_that_disagree_with_the_total_are_flagged(client, admin_headers, world, db):
    load_statements(db, world)
    sheet = save(
        client, admin_headers, world, "SHOP2",
        transfers=[detail(world, "BAC", "NIO", "18000.00"), detail(world, "BAC", "NIO", "19000.00")],
        totals=[total(world, "BAC", "NIO", "37030.00")],
    )
    bac = cell(sheet, "BAC", "NIO")
    assert bac["status"] == "DIFFERENT"
    assert bac["listed_sum"] == "37000.00"


def test_a_bank_with_no_statement_yet_is_waiting(client, admin_headers, world, db):
    load_statements(db, world)
    sheet = save(client, admin_headers, world, "SHOP1",
                 totals=[total(world, "BANPRO", "NIO", "20000.00")])
    assert cell(sheet, "BANPRO", "NIO")["status"] == "WAITING"


def test_editing_the_sheet_keeps_found_lines_out_of_the_form(client, admin_headers, world, db):
    load_statements(db, world)
    managua = save(client, admin_headers, world, "SHOP3",
                   totals=[total(world, "BAC", "USD", "1695.00")])
    # The form sends back only what it shows: no deposits, the same total.
    response = client.put(
        f"/api/v1/accounting/daily/{managua['id']}",
        json={"transfers": [], "bank_totals": [total(world, "BAC", "USD", "1695.00")],
              "status": "SUBMITTED"},
        headers=admin_headers,
    )
    assert response.status_code == 200, response.text
    assert cell(response.json(), "BAC", "USD")["status"] == "MATCHED"


# ------------------------------------------------------- the sheet in dollars
def test_paper_view_totals_in_dollars_and_shows_a_paper_arithmetic_slip(
    client, admin_headers, world, db
):
    client.put("/api/v1/monthly/2026-10/rate", json={"nio_per_usd": "37.1"},
               headers=admin_headers)
    # Juigalpa, as written: sales 1,415, other balances 528, closing written as 256.
    payload = {
        "shop_id": world["shops"]["SHOP1"], "business_date": DAY,
        "total_sales_usd": "1415.00", "opening_balance_usd": "528.00",
        "bank_totals": [total(world, "BAC", "NIO", "17822.00"),
                        total(world, "LAFISE", "NIO", "4860.00"),
                        total(world, "BANPRO", "NIO", "20000.00")],
        "transfers": [],
        "expenses": [
            {"category": "GENERAL", "description": "J David", "currency_code": "USD", "amount": "204.00"},
            {"category": "GENERAL", "description": "Marcol", "currency_code": "USD", "amount": "196.00"},
            {"category": "GENERAL", "description": "Bonos", "currency_code": "NIO", "amount": "5000.00"},
            {"category": "GENERAL", "description": "Bus", "currency_code": "NIO", "amount": "100.00"},
        ],
        "bale_records": [], "status": "SUBMITTED", "declared_closing_usd": "256.00",
    }
    body = client.post("/api/v1/accounting/daily", json=payload, headers=admin_headers).json()
    paper = body["paper"]
    # 1,415 + 528 = 1,943. The paper's TOTAL box says 1,923: an addition slip
    # on the sheet, which the calculated total makes visible.
    assert paper["total_usd"] == "1943.00"
    assert paper["transfers"]["total_usd"] == "1150.46"     # 42,682 ÷ 37.1 (paper: 480+131+539 = 1,150)
    assert paper["expenses"]["total_usd"] == "537.47"       # $400 + C$5,100 ÷ 37.1 (paper: 537)
    assert paper["closing_computed_usd"] == "255.07"        # 1,943 − 1,150.46 − 537.47
    # The sheet's 256 is right; the 0.93 is the paper rounding each bank to whole dollars.
    assert paper["closing_declared_usd"] == "256.00"
    assert paper["closing_difference_usd"] == "0.93"
