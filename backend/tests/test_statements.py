from __future__ import annotations

from decimal import Decimal
from io import BytesIO

import pytest

from tests.conftest import SAMPLES


def upload(client, headers, filename: str, account_label: str, world, **extra):
    path = SAMPLES / filename
    if not path.exists():
        pytest.skip(f"sample {filename} is not present")
    files = {"file": (filename, BytesIO(path.read_bytes()), "application/pdf")}
    data = {
        "bank_account_id": str(world["accounts"][account_label]),
        "process_now": "false",
        **{k: str(v) for k, v in extra.items()},
    }
    return client.post("/api/v1/statements/upload", data=data, files=files, headers=headers)


def process(client, headers, statement_id: int):
    return client.post(
        f"/api/v1/statements/{statement_id}/process",
        params={"background": "false"},
        headers=headers,
    )


def test_only_pdfs_are_accepted(client, admin_headers, world):
    files = {"file": ("payload.pdf", BytesIO(b"MZ this is an executable"), "application/pdf")}
    response = client.post(
        "/api/v1/statements/upload",
        data={"bank_account_id": str(world["accounts"]["BAC Dollars"])},
        files=files, headers=admin_headers,
    )
    assert response.status_code == 415
    assert "not a PDF" in response.json()["error"]["message"]


def test_an_empty_file_is_rejected(client, admin_headers, world):
    files = {"file": ("empty.pdf", BytesIO(b""), "application/pdf")}
    response = client.post(
        "/api/v1/statements/upload",
        data={"bank_account_id": str(world["accounts"]["BAC Dollars"])},
        files=files, headers=admin_headers,
    )
    assert response.status_code == 422


def test_the_same_file_cannot_be_uploaded_twice_for_one_account(client, admin_headers, world):
    first = upload(client, admin_headers, "lafise dollar Aug-11.pdf", "LAFISE Dollars", world)
    assert first.status_code == 201
    again = upload(client, admin_headers, "lafise dollar Aug-11.pdf", "LAFISE Dollars", world)
    assert again.status_code == 409
    assert "already uploaded" in again.json()["error"]["message"]


def test_processing_extracts_the_transactions(client, admin_headers, world):
    created = upload(
        client, admin_headers, "lafise cordoba Aug-11.pdf", "LAFISE Cordobas", world
    ).json()
    result = process(client, admin_headers, created["id"]).json()
    assert result["status"] == "PROCESSED"
    assert result["parser"] == "LAFISE"
    assert result["inserted"] == 6

    rows = client.get(
        "/api/v1/bank-transactions",
        params={"statement_id": created["id"], "page_size": 100},
        headers=admin_headers,
    ).json()
    assert rows["total"] == 6
    assert all(row["currency_code"] == "NIO" for row in rows["items"])
    assert all(row["match_status"] == "UNMATCHED" for row in rows["items"])


def test_re_uploading_an_overlapping_period_does_not_duplicate_lines(
    client, admin_headers, world
):
    first = upload(
        client, admin_headers, "lafise cordoba Aug-11.pdf", "LAFISE Cordobas", world
    ).json()
    process(client, admin_headers, first["id"])

    # Same content under a different filename: a different file, the same money.
    path = SAMPLES / "lafise cordoba Aug-11.pdf"
    files = {"file": ("resent-by-the-bank.pdf", BytesIO(path.read_bytes() + b"\n% resent"),
                      "application/pdf")}
    second = client.post(
        "/api/v1/statements/upload",
        data={"bank_account_id": str(world["accounts"]["LAFISE Cordobas"]), "process_now": "false"},
        files=files, headers=admin_headers,
    ).json()
    result = process(client, admin_headers, second["id"]).json()
    assert result["inserted"] == 0
    assert result["duplicates"] == 6

    total = client.get(
        "/api/v1/bank-transactions", params={"page_size": 200}, headers=admin_headers
    ).json()["total"]
    assert total == 6


def test_a_statement_for_the_wrong_currency_account_fails_clearly(client, admin_headers, world):
    created = upload(
        client, admin_headers, "Banpro - USD Aug-20.pdf", "BANPRO Cordobas", world
    ).json()
    result = process(client, admin_headers, created["id"]).json()
    assert result["status"] == "FAILED"
    assert "USD" in result["error"] and "NIO" in result["error"]


def test_a_bank_with_no_parser_reports_it_instead_of_inventing_data(
    client, admin_headers, world
):
    created = upload(
        client, admin_headers, "lafise cordoba Aug-11.pdf", "FICOHSA Cordobas", world
    ).json()
    result = process(client, admin_headers, created["id"]).json()
    assert result["status"] == "FAILED"
    # It recognised the layout, saw it belongs to another bank, and refused
    # rather than filing LAFISE money under a FICOHSA account.
    assert "LAFISE" in result["error"] and "FICOHSA" in result["error"]
    # The file itself is kept, so it can be processed once a parser exists.
    assert client.get(
        f"/api/v1/statements/{created['id']}/file", headers=admin_headers
    ).status_code == 200


def test_bac_statement_goes_through_ocr_end_to_end(client, admin_headers, world):
    from app.parsers.document import PdfDocument

    if not PdfDocument.ocr_available():
        pytest.skip("tesseract is not installed")
    created = upload(
        client, admin_headers, "bac cordoba aug-11.pdf", "BAC Cordobas", world
    ).json()
    result = process(client, admin_headers, created["id"]).json()
    assert result["status"] == "PROCESSED"
    assert result["extraction_method"] == "OCR"
    assert result["inserted"] == 7


def test_uploads_and_processing_are_audited(client, admin_headers, world):
    created = upload(
        client, admin_headers, "lafise dollar Aug-11.pdf", "LAFISE Dollars", world
    ).json()
    process(client, admin_headers, created["id"])
    actions = {
        row["action"]
        for row in client.get(
            "/api/v1/audit-logs", params={"module": "statements"}, headers=admin_headers
        ).json()["items"]
    }
    assert {"UPLOAD_STATEMENT", "PROCESS_STATEMENT"} <= actions


def test_a_bank_with_no_parser_and_an_unknown_layout_says_so(client, admin_headers, world):
    from io import BytesIO

    minimal_pdf = (
        b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\n"
        b"trailer<</Root 1 0 R>>\n%%EOF\n"
    )
    files = {"file": ("mystery.pdf", BytesIO(minimal_pdf), "application/pdf")}
    created = client.post(
        "/api/v1/statements/upload",
        data={
            "bank_account_id": str(world["accounts"]["FICOHSA Dollars"]),
            "process_now": "false",
        },
        files=files, headers=admin_headers,
    ).json()
    result = process(client, admin_headers, created["id"]).json()
    assert result["status"] == "FAILED"
    assert "no statement parser configured" in result["error"]
