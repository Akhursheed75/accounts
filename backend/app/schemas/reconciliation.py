from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.schemas.banking import TransactionOut
from app.schemas.common import ORMModel


class ScoreSignal(BaseModel):
    signal: str
    points: int
    detail: str


class MatchOut(ORMModel):
    id: int
    shop_transfer_id: int
    bank_transaction_id: int
    status: str
    match_type: str
    confidence: int
    amount_delta: Decimal
    date_delta_days: int
    score_breakdown: list[ScoreSignal] | None = None
    is_active: bool
    matched_by_name: str | None = None
    matched_at: datetime | None = None
    unmatched_by_name: str | None = None
    unmatched_at: datetime | None = None
    note: str | None = None


class TransferSide(BaseModel):
    id: int
    shop_id: int
    shop_name: str | None
    business_date: date
    payment_method: str = "BANK"
    bank_id: int | None
    bank_code: str | None
    currency_code: str
    amount: Decimal
    reference: str | None
    note: str
    is_ignored: bool


class ReconciliationRow(BaseModel):
    transfer: TransferSide
    status: str                       # MATCHED | POSSIBLE | UNMATCHED | IGNORED
    confirmed: MatchOut | None = None
    confirmed_transaction: TransactionOut | None = None
    suggestions: list[MatchOut] = []
    suggested_transactions: list[TransactionOut] = []
    history: list[MatchOut] = []


class MatchIn(BaseModel):
    shop_transfer_id: int
    bank_transaction_id: int
    note: str | None = Field(None, max_length=1000)


class ConfirmIn(BaseModel):
    match_id: int
    note: str | None = Field(None, max_length=1000)


class UnmatchIn(BaseModel):
    match_id: int
    reason: str | None = Field(None, max_length=1000)


class RunIn(BaseModel):
    shop_id: int | None = None
    bank_id: int | None = None
    date_from: date | None = None
    date_to: date | None = None


class UnmatchedSummary(BaseModel):
    shop_payments: list[TransferSide]
    bank_transactions: list[TransactionOut]
    totals: dict
