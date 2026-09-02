"""Everything a statement parser must produce, and nothing about how it gets there.

Each bank formats its PDF differently, so each bank gets its own parser. What
they share is the output: one normalised transaction shape the rest of the
system understands."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from app.parsers.document import PdfDocument


@dataclass(slots=True)
class NormalizedTransaction:
    txn_date: date
    amount: Decimal                 # always positive; direction carries the sign
    direction: str                  # CREDIT | DEBIT
    currency_code: str
    description: str = ""
    reference: str | None = None
    external_id: str | None = None
    value_date: date | None = None
    debit: Decimal = Decimal("0.00")
    credit: Decimal = Decimal("0.00")
    running_balance: Decimal | None = None
    movement_type: str | None = None
    page_number: int | None = None
    row_index: int = 0
    raw_text: str = ""
    # 0-100. Text extraction yields 100; OCR yields what the balance chain and
    # Tesseract's own word confidence justify.
    confidence: int = 100
    #: True once the statement's own running balance has confirmed this row.
    chain_verified: bool = False


@dataclass(slots=True)
class ParseResult:
    transactions: list[NormalizedTransaction] = field(default_factory=list)
    extraction_method: str = "TEXT"
    warnings: list[str] = field(default_factory=list)
    account_number: str | None = None
    statement_currency: str | None = None
    period_start: date | None = None
    period_end: date | None = None
    opening_balance: Decimal | None = None
    closing_balance: Decimal | None = None
    # True when the parser recognised the layout but could not vouch for every
    # row. The statement is then marked PARTIALLY_PROCESSED rather than PROCESSED.
    partial: bool = False


class ParserError(Exception):
    """Raised when a parser recognises it cannot handle the file. The message is
    shown to the admin verbatim, so it must be written for a person."""


class BaseParser(ABC):
    key: str = ""
    display_name: str = ""
    #: Set False for banks whose parser is a placeholder awaiting a real sample.
    implemented: bool = True

    @abstractmethod
    def can_parse(self, doc: PdfDocument) -> bool:
        """Cheap check used for auto-detection when the bank has no parser set."""

    @abstractmethod
    def parse(self, doc: PdfDocument, *, currency_code: str) -> ParseResult:
        """Extract every transaction, or raise ParserError explaining why not."""
