from __future__ import annotations

from tests.conftest import make_sheet


def test_shop_user_cannot_open_the_company_dashboard(client, shop_headers):
    response = client.get("/api/v1/dashboard", headers=shop_headers)
    assert response.status_code == 403
    assert "does not allow" in response.json()["error"]["message"]


def test_shop_user_only_sees_their_own_shop(client, shop_headers, world):
    shops = client.get("/api/v1/shops", headers=shop_headers).json()
    assert [s["id"] for s in shops] == [world["shops"]["SHOP1"]]


def test_shop_user_cannot_create_a_sheet_for_another_shop(client, shop_headers, world):
    make_sheet(
        client, shop_headers,
        shop_id=world["shops"]["SHOP2"], business_date="2026-08-11",
        transfers=[], expect=403,
    )


def test_shop_user_cannot_read_another_shops_sheet(client, admin_headers, shop_headers, world):
    created = make_sheet(
        client, admin_headers,
        shop_id=world["shops"]["SHOP2"], business_date="2026-08-11", transfers=[],
    ).json()
    response = client.get(f"/api/v1/accounting/daily/{created['id']}", headers=shop_headers)
    assert response.status_code == 403


def test_shop_user_cannot_manage_users_or_settings(client, shop_headers):
    assert client.get("/api/v1/users", headers=shop_headers).status_code == 403
    assert client.put(
        "/api/v1/settings/matching", json={"date_window_days": 9}, headers=shop_headers
    ).status_code == 403


def test_shop_user_cannot_export_reports(client, shop_headers):
    listing = client.get("/api/v1/reports/shop-sales", headers=shop_headers)
    assert listing.status_code == 200          # viewing is allowed
    export = client.get(
        "/api/v1/reports/shop-sales", params={"format": "xlsx"}, headers=shop_headers
    )
    assert export.status_code == 403           # exporting is not


def test_an_admin_cannot_lock_themselves_out_of_user_management(client, admin_headers):
    roles = client.get("/api/v1/roles", headers=admin_headers).json()
    admin_role = next(r for r in roles if r["code"] == "ADMIN")
    response = client.put(
        f"/api/v1/roles/{admin_role['id']}/permissions",
        json={"permissions": ["shop.read"]},
        headers=admin_headers,
    )
    assert response.status_code == 422
    assert "lock yourself out" in response.json()["error"]["message"]
