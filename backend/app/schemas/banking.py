from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class StatementOut(ORMModel):
    id: int
    bank_account_id: int
    bank_id: int | None = None
    bank_code: str | None = None
    bank_name: str | None = None
    account_label: str | None = None
    currency_code: str | None = None
    period_start: date | None
    period_end: date | None
    original_filename: str
    file_size: int
    page_count: int | None
    status: str
    parser_key: str | None
    extraction_method: str
    error_message: str | None
    warnings: list[str] | None = None
    transaction_count: int
    duplicate_count: int
    statement_closing_balance: Decimal | None
    uploaded_by_id: int | None
    uploaded_by_name: str | None = None
    created_at: datetime
    processed_at: datetime | None
    is_demo: bool


class TransactionOut(ORMModel):
    id: int
    statement_id: int
    bank_account_id: int
    bank_id: int
    bank_code: str | None = None
    account_label: str | None = None
    txn_date: date
    value_date: date | None
    description: str
    reference: str | None
    external_id: str | None
    movement_type: str | None
    debit: Decimal
    credit: Decimal
    amount: Decimal
    direction: str
    currency_code: str
    running_balance: Decimal | None
    extraction_confidence: int | None
    page_number: int | None
    is_ignored: bool
    match_status: str = "UNMATCHED"
    matched_transfer_id: int | None = None
    suggestion_count: int = 0


class IgnoreIn(BaseModel):
    reason: str = Field("", max_length=255)
    undo: bool = False
