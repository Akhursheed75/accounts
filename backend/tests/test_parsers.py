"""Parsers are checked against the real statement PDFs, not invented fixtures.

If a bank changes its layout, these are the tests that will say so."""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.parsers.bac import BacParser
from app.parsers.banpro import BanproParser
from app.parsers.base import ParserError
from app.parsers.document import PdfDocument
from app.parsers.fichosa import FichosaParser
from app.parsers.lafise import LafiseParser
from app.parsers.layout import parse_date, parse_money
from app.parsers.registry import detect_parser, has_parser
from tests.conftest import SAMPLES


def load(name: str) -> PdfDocument:
    path = SAMPLES / name
    if not path.exists():
        pytest.skip(f"sample {name} is not present")
    return PdfDocument(path.read_bytes(), name)


# ------------------------------------------------------------------ helpers
def test_money_parsing_handles_both_conventions():
    assert parse_money("14,098.00") == Decimal("14098.00")
    assert parse_money("C$20,000.00") == Decimal("20000.00")
    assert parse_money("$460.00") == Decimal("460.00")
    assert parse_money("1.234,56") == Decimal("1234.56")
    assert parse_money("(1,234.00)") == Decimal("-1234.00")
    assert parse_money("not a number") is None


def test_dates_are_read_day_first():
    assert parse_date("11/AUG/2026").isoformat() == "2026-08-11"
    assert parse_date("20/08/2026").isoformat() == "2026-08-20"
    # 20 can only be a day, whatever order the file uses.
    assert parse_date("8/20/26").isoformat() == "2026-08-20"


# -------------------------------------------------------------------- LAFISE
def test_lafise_statement_is_read_completely():
    with load("lafise cordoba Aug-11.pdf") as doc:
        result = LafiseParser().parse(doc, currency_code="NIO")
    assert len(result.transactions) == 6
    assert result.extraction_method == "TEXT"
    amounts = [t.amount for t in result.transactions]
    assert Decimal("14098.00") in amounts
    assert Decimal("24655.54") in amounts
    assert all(t.direction == "CREDIT" for t in result.transactions)
    # Every row agreed with the running balance, so no warnings were raised.
    assert result.warnings == []


def test_lafise_reads_the_confirmation_number_as_the_reference():
    with load("lafise cordoba Aug-11.pdf") as doc:
        result = LafiseParser().parse(doc, currency_code="NIO")
    first = result.transactions[0]
    assert first.external_id == "144018417"
    assert first.description == "Pago de pacas"
    assert first.running_balance == Decimal("259522.14")


def test_lafise_dollar_statement():
    with load("lafise dollar Aug-20.pdf") as doc:
        result = LafiseParser().parse(doc, currency_code="USD")
    assert [t.amount for t in result.transactions] == [
        Decimal("10.00"), Decimal("370.00"), Decimal("15.00")
    ]


# -------------------------------------------------------------------- BANPRO
def test_banpro_statement_is_read_completely():
    with load("Banpro - USD Aug-20.pdf") as doc:
        result = BanproParser().parse(doc, currency_code="USD")
    assert len(result.transactions) == 3
    assert [t.amount for t in result.transactions] == [
        Decimal("460.00"), Decimal("245.00"), Decimal("200.00")
    ]
    # BANPRO gives no balance column, so the parser says so instead of pretending.
    assert any("no debit/credit column" in w for w in result.warnings)


def test_banpro_wrapped_descriptions_stay_in_their_own_row():
    with load("Banpro - Cordoba Aug-20.pdf") as doc:
        result = BanproParser().parse(doc, currency_code="NIO")
    assert len(result.transactions) == 2
    assert result.transactions[0].amount == Decimal("20000.00")
    assert result.transactions[0].reference == "48366907"
    assert result.transactions[1].amount == Decimal("4267.00")
    assert "Katia Rivera" in result.transactions[1].description


def test_banpro_refuses_a_statement_in_the_wrong_currency():
    with load("Banpro - USD Aug-20.pdf") as doc:
        with pytest.raises(ParserError) as excinfo:
            BanproParser().parse(doc, currency_code="NIO")
    assert "USD" in str(excinfo.value) and "NIO" in str(excinfo.value)


# ----------------------------------------------------------------------- BAC
def test_bac_statements_have_no_text_layer_and_go_through_ocr():
    with load("bac cordoba aug-11.pdf") as doc:
        assert doc.has_text_layer is False
        if not doc.ocr_available():
            pytest.skip("tesseract is not installed")
        result = BacParser().parse(doc, currency_code="NIO")
    assert result.extraction_method == "OCR"
    assert len(result.transactions) == 7
    assert result.account_number == "NI61BAMC00000000000370555179"
    amounts = [t.amount for t in result.transactions]
    assert amounts == [
        Decimal("4452.00"), Decimal("186.00"), Decimal("7234.00"), Decimal("63.00"),
        Decimal("15585.00"), Decimal("37139.00"), Decimal("12620.00"),
    ]


def test_ocr_rows_are_confirmed_against_the_running_balance():
    with load("bac dollars Aug-11.pdf") as doc:
        if not doc.ocr_available():
            pytest.skip("tesseract is not installed")
        result = BacParser().parse(doc, currency_code="USD")
    checked = [t for t in result.transactions if t.chain_verified]
    # Every row but the first has a predecessor to be checked against.
    assert len(checked) == len(result.transactions) - 1
    assert all(t.confidence >= 97 for t in checked)
    assert result.transactions[0].confidence < 97
    assert result.closing_balance == Decimal("18743.49")


def test_bac_refuses_a_statement_for_the_other_currency():
    with load("bac dollars Aug-11.pdf") as doc:
        if not doc.ocr_available():
            pytest.skip("tesseract is not installed")
        with pytest.raises(ParserError) as excinfo:
            BacParser().parse(doc, currency_code="NIO")
    assert "USD" in str(excinfo.value)


# ------------------------------------------------------------------- FICHOSA
def test_fichosa_declines_clearly_instead_of_guessing():
    assert has_parser("FICHOSA") is False
    with load("lafise cordoba Aug-11.pdf") as doc:
        with pytest.raises(ParserError) as excinfo:
            FichosaParser().parse(doc, currency_code="NIO")
    message = str(excinfo.value)
    assert "No parser has been built for FICHOSA" in message
    assert "nothing is lost" in message


# ------------------------------------------------------------------ registry
@pytest.mark.parametrize(
    "filename,expected",
    [
        ("lafise cordoba Aug-11.pdf", "LAFISE"),
        ("Banpro - USD Aug-20.pdf", "BANPRO"),
        ("bac cordoba aug-11.pdf", "BAC"),
    ],
)
def test_each_bank_layout_is_recognised(filename, expected):
    with load(filename) as doc:
        parser = detect_parser(doc)
    assert parser is not None and parser.key == expected


# ------------------------------------------- the daily set of 1 October 2026
# Six statements as they now arrive each morning. Three are "Microsoft: Print To
# PDF" with no text layer (both BAC and BANPRO dollars) and go through OCR.
def _parse(name: str, parser, currency: str):
    with load(name) as doc:
        return parser.parse(doc, currency_code=currency)


def test_oct01_bac_dollars_reads_every_row_including_the_3v_code():
    result = _parse("2026-10-01-bac_usd.pdf", BacParser(), "USD")
    assert result.extraction_method == "OCR"
    assert len(result.transactions) == 8
    assert result.warnings == []            # the running balance confirms every row
    fee = [t for t in result.transactions if t.amount == Decimal("125.00")]
    assert fee and fee[0].direction == "DEBIT"
    credits = sorted(t.amount for t in result.transactions if t.direction == "CREDIT")
    assert credits == [Decimal(x) for x in ("10.00", "10.00", "15.00", "185.00", "1510.00")]


def test_oct01_bac_cordobas_holds_the_shops_deposits():
    result = _parse("2026-10-01-bac_nio.pdf", BacParser(), "NIO")
    amounts = {t.amount for t in result.transactions if t.direction == "CREDIT"}
    # Jinotega's two deposits and Juigalpa's one, as written on their sheets.
    assert {Decimal("18000.00"), Decimal("19030.00"), Decimal("17822.00")} <= amounts
    assert result.warnings == []


def test_oct01_banpro_dollars_is_a_scan_and_is_read_by_ocr():
    with load("2026-10-01-banpro_usd.pdf") as doc:
        assert not doc.has_text_layer
        assert detect_parser(doc).key == "BANPRO"
        result = BanproParser().parse(doc, currency_code="USD")
    assert result.extraction_method == "OCR"
    assert [t.amount for t in result.transactions] == [
        Decimal("190.00"), Decimal("1095.00"), Decimal("235.00"), Decimal("280.00"),
    ]
    assert {t.reference for t in result.transactions} >= {"56780413", "56719022", "56715547"}


def test_oct01_text_statements():
    lafise_usd = _parse("2026-10-01-lafise_usd.pdf", LafiseParser(), "USD")
    lafise_nio = _parse("2026-10-01-lafise_nio.pdf", LafiseParser(), "NIO")
    banpro_nio = _parse("2026-10-01-banpro_nio.pdf", BanproParser(), "NIO")
    assert len(lafise_usd.transactions) == 15
    assert len(lafise_nio.transactions) == 12
    assert len(banpro_nio.transactions) == 7
    assert Decimal("4860.00") in {t.amount for t in lafise_nio.transactions}
    assert Decimal("20000.00") in {t.amount for t in banpro_nio.transactions}
