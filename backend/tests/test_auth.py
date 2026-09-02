from __future__ import annotations

from tests.conftest import login


def test_login_returns_a_token_and_the_user(client):
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@test.local", "password": "AdminPassword1"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["user"]["email"] == "admin@test.local"
    assert "dashboard.view" in body["user"]["permissions"]
    assert body["user"]["has_global_scope"] is True


def test_wrong_password_is_rejected_without_revealing_the_account(client):
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@test.local", "password": "not the password"},
    )
    assert response.status_code == 401
    message = response.json()["error"]["message"]
    assert message == "Email or password is incorrect."

    unknown = client.post(
        "/api/v1/auth/login",
        json={"email": "nobody@test.local", "password": "whatever12"},
    )
    # Identical wording, so the form cannot be used to enumerate addresses.
    assert unknown.json()["error"]["message"] == message


def test_endpoints_require_a_session(client):
    assert client.get("/api/v1/shops").status_code == 401
    assert client.get("/api/v1/dashboard").status_code == 401


def test_a_tampered_token_is_refused(client):
    headers = login(client, "admin@test.local", "AdminPassword1")
    broken = headers["authorization"][:-3] + "aaa"
    response = client.get("/api/v1/auth/me", headers={"authorization": broken})
    assert response.status_code == 401


def test_changing_the_password_invalidates_existing_tokens(client):
    headers = login(client, "admin@test.local", "AdminPassword1")
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 200

    changed = client.post(
        "/api/v1/auth/change-password",
        json={"current_password": "AdminPassword1", "new_password": "BrandNewPassword1"},
        headers=headers,
    )
    assert changed.status_code == 200
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 401
    login(client, "admin@test.local", "BrandNewPassword1")


def test_login_and_failed_login_are_both_audited(client, admin_headers):
    client.post("/api/v1/auth/login", json={"email": "admin@test.local", "password": "wrong pass"})
    response = client.get("/api/v1/audit-logs", headers=admin_headers, params={"module": "auth"})
    actions = {row["action"] for row in response.json()["items"]}
    assert "LOGIN" in actions
    assert "LOGIN_FAILED" in actions
