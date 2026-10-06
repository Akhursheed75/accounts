"""Photos of the paper sheet: kept with the sheet, and read into a draft.

The reading service is replaced by a fake that answers with what Jinotega's
real sheet of 1 Oct 2026 says, so these tests check our side — the request we
send, and how the answer becomes the form — without a network or a key."""
from __future__ import annotations

import io

import httpx
import pytest
from PIL import Image
from sqlalchemy import update

from app.core.config import settings
from app.db.session import SessionLocal
from app.models import Shop
from app.services import sheet_reader

JINOTEGA = {
    "date": "2026-10-01", "shop": "Jinotega", "bales_sold": 7, "total_sales_usd": 980,
    "other_balances_usd": 529, "total_usd": 1509, "invoices": 5,
    "cash_received": {"nio": None, "usd": None, "total_usd": None},
    "commercial_invoice": {"cash": None, "deposit": None, "total_usd": None},
    "transfers": [
        {"bank": "BAC", "usd": 10, "nio": 37030, "total_usd": 1008},
        {"bank": "LAFISE", "usd": None, "nio": 7000, "total_usd": 189},
    ],
    "deposit_details": [
        {"bank": "BAC", "currency": "USD", "amounts": [10]},
        {"bank": "BAC", "currency": "NIO", "amounts": [18000, 19030]},
        {"bank": "LAFISE", "currency": "NIO", "amounts": [7000]},
    ],
    "expenses": [
        {"description": "Kike comis", "currency": "NIO", "amount": 10388},
        {"description": "Lenin comis", "currency": "NIO", "amount": 1113},
        {"description": "Offload", "currency": "NIO", "amount": 100},
    ],
    "expenses_total_usd": 313,
    "delivery": {"cash": None, "transfers": None},
    "credit_usd": None, "observations": None,
    "bales": [
        {"type": "100LBS", "quantity": 45, "received": None, "after_closing": 38},
        {"type": "25LBS", "quantity": 4, "received": None, "after_closing": 4},
    ],
    "starting_balance_usd": 529, "closing_balance_usd": 0, "unclear": [],
}


def jpeg(width=1200, height=1600, exif_rotate=False) -> bytes:
    image = Image.new("RGB", (width, height), "white")
    out = io.BytesIO()
    if exif_rotate:
        exif = Image.Exif()
        exif[0x0112] = 6            # "rotate 90° clockwise to view"
        image.save(out, format="JPEG", exif=exif)
    else:
        image.save(out, format="JPEG")
    return out.getvalue()


@pytest.fixture()
def reader(monkeypatch):
    """A fake reading service that records what it was sent."""
    sent: dict = {}

    def fake_post(url, json, headers, timeout):
        sent.update(url=url, body=json, headers=headers)
        return httpx.Response(200, json={"content": [
            {"type": "tool_use", "name": "record_sheet", "input": JINOTEGA},
        ]})

    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    monkeypatch.setattr(sheet_reader.httpx, "post", fake_post)
    return sent


def rename(code: str, name: str) -> None:
    with SessionLocal() as db:
        db.execute(update(Shop).where(Shop.code == code).values(name=name))
        db.commit()


def upload(client, headers, data=None, name="sheet.jpg"):
    return client.post(
        "/api/v1/accounting/photos", headers=headers,
        files={"file": (name, data if data is not None else jpeg(), "image/jpeg")},
    )


def test_without_a_key_the_photo_is_kept_and_nothing_is_guessed(
    client, admin_headers, monkeypatch
):
    monkeypatch.setattr(settings, "anthropic_api_key", None)
    response = upload(client, admin_headers)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["reader_available"] is False
    assert body["draft"] is None
    photo_id = body["photo"]["id"]
    served = client.get(f"/api/v1/accounting/photos/{photo_id}/file", headers=admin_headers)
    assert served.status_code == 200
    assert served.headers["content-type"] == "image/jpeg"


def test_the_request_sends_an_upright_downscaled_image_and_forces_the_structure(
    client, admin_headers, reader
):
    assert upload(client, admin_headers, jpeg(3000, 4000, exif_rotate=True)).status_code == 201
    body = reader["body"]
    assert reader["headers"]["x-api-key"] == "test-key"
    assert body["model"] == settings.sheet_reader_model
    assert body["tool_choice"] == {"type": "tool", "name": "record_sheet"}
    image_block = body["messages"][0]["content"][0]
    assert image_block["type"] == "image" and image_block["source"]["media_type"] == "image/jpeg"
    import base64
    sent = Image.open(io.BytesIO(base64.b64decode(image_block["source"]["data"])))
    # A 3000x4000 photo tagged "rotate 90°" arrives upright (landscape) and ≤ 1568 px.
    assert max(sent.size) <= sheet_reader.MAX_EDGE
    assert sent.size[0] > sent.size[1]


def test_jinotegas_sheet_becomes_a_draft_that_agrees_with_itself(
    client, admin_headers, reader, world
):
    rename("SHOP2", "Jinotega")
    client.put("/api/v1/monthly/2026-10/rate", json={"nio_per_usd": "37.1"},
               headers=admin_headers)
    body = upload(client, admin_headers).json()
    draft = body["draft"]
    assert body["checks"] == []        # TOTAL$, expenses and bales all add up at 37.1
    assert draft["shop_id"] == world["shops"]["SHOP2"]
    assert draft["business_date"] == "2026-10-01"
    assert draft["total_sales_usd"] == "980.00" and draft["opening_balance_usd"] == "529.00"
    totals = {(t["bank_id"], t["currency_code"]): t["amount"] for t in draft["bank_totals"]}
    assert totals == {
        (world["banks"]["BAC"], "USD"): "10.00",
        (world["banks"]["BAC"], "NIO"): "37030.00",
        (world["banks"]["LAFISE"], "NIO"): "7000.00",
    }
    deposits = sorted(t["amount"] for t in draft["transfers"])
    assert deposits == ["10.00", "18000.00", "19030.00", "7000.00"]
    assert [e["currency_code"] for e in draft["expenses"]] == ["NIO", "NIO", "NIO"]
    sold = {b["opening_qty"]: b["sold_qty"] for b in draft["bale_records"]}
    assert sold == {45: 7, 4: 0}
    assert draft["declared_closing_usd"] == "0.00"

    # The person checks it and saves: the photo stays with the sheet.
    payload = {**{k: v for k, v in draft.items() if k != "shop_name_read"},
               "status": "SUBMITTED", "photo_ids": [body["photo"]["id"]]}
    saved = client.post("/api/v1/accounting/daily", json=payload, headers=admin_headers)
    assert saved.status_code == 201, saved.text
    record = saved.json()
    assert [p["id"] for p in record["photos"]] == [body["photo"]["id"]]
    assert record["photos"][0]["extraction"]["shop"] == "Jinotega"
    assert record["paper"]["total_usd"] == "1509.00"


def test_sheet_disagreements_are_reported_for_a_second_look(client, admin_headers, monkeypatch):
    wrong = {**JINOTEGA, "total_usd": 1500,
             "deposit_details": [{"bank": "BAC", "currency": "NIO", "amounts": [18000, 19000]}]}

    def fake_post(url, json, headers, timeout):
        return httpx.Response(200, json={"content": [
            {"type": "tool_use", "name": "record_sheet", "input": wrong}]})

    monkeypatch.setattr(settings, "anthropic_api_key", "k")
    monkeypatch.setattr(sheet_reader.httpx, "post", fake_post)
    checks = upload(client, admin_headers).json()["checks"]
    assert any("TOTAL says 1500" in c for c in checks)
    assert any("detail lines add up to 37000" in c for c in checks)
    assert any("No shop called 'Jinotega'" in c for c in checks)


def test_a_failing_reading_service_does_not_lose_the_photo(client, admin_headers, monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "k")
    monkeypatch.setattr(sheet_reader.httpx, "post",
                        lambda *a, **k: httpx.Response(529, json={"error": {"message": "overloaded"}}))
    body = upload(client, admin_headers).json()
    assert body["draft"] is None
    assert "529" in body["photo"]["extraction_error"]


def test_only_real_photos_are_accepted(client, admin_headers):
    assert upload(client, admin_headers, b"%PDF-1.7 not a photo").status_code == 415
    heic = b"\x00\x00\x00\x18ftypheic" + b"\x00" * 40
    response = upload(client, admin_headers, heic, "IMG_0001.HEIC")
    assert response.status_code == 415
    assert "JPG" in response.json()["error"]["message"]


def test_a_shop_user_cannot_see_another_users_unattached_photo(
    client, admin_headers, shop_headers, monkeypatch
):
    monkeypatch.setattr(settings, "anthropic_api_key", None)
    photo_id = upload(client, admin_headers).json()["photo"]["id"]
    assert client.get(f"/api/v1/accounting/photos/{photo_id}/file",
                      headers=shop_headers).status_code == 403
