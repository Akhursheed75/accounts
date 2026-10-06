from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.common import ORMModel

MONEY_MAX = Decimal("999999999999.99")


def _check_money(value: Decimal | None) -> Decimal:
    if value is None:
        return Decimal("0.00")
    if value.is_nan() or value.is_infinite():
        raise ValueError("must be a number")
    if abs(value) > MONEY_MAX:
        raise ValueError("is larger than this system supports")
    return value.quantize(Decimal("0.01"))


class TransferIn(BaseModel):
    id: int | None = None
    payment_method: Literal["BANK", "CASH"] = "BANK"
    bank_id: int | None = None
    bank_account_id: int | None = None
    currency_code: str = Field(min_length=3, max_length=3)
    amount: Decimal = Field(gt=0)
    reference: str | None = Field(None, max_length=120)
    deposit_time: time | None = None
    note: str = Field("", max_length=255)

    @field_validator("amount")
    @classmethod
    def _amount(cls, v: Decimal) -> Decimal:
        return _check_money(v)

    @field_validator("currency_code")
    @classmethod
    def _currency(cls, v: str) -> str:
        return v.upper()

    @model_validator(mode="after")
    def _bank_matches_method(self) -> "TransferIn":
        if self.payment_method == "CASH":
            # Cash has no bank yet. Whatever the form sent is discarded rather
            # than stored, so a stale dropdown value can never mislead matching.
            self.bank_id = None
            self.bank_account_id = None
        elif self.bank_id is None:
            raise ValueError("a bank payment needs a bank")
        return self


class TransferOut(ORMModel):
    id: int
    payment_method: str = "BANK"
    source: str = "SHEET"
    bank_id: int | None
    bank_code: str | None = None
    bank_name: str | None = None
    bank_account_id: int | None
    currency_code: str
    amount: Decimal
    reference: str | None
    deposit_time: time | None
    note: str
    is_ignored: bool
    ignored_reason: str | None = None
    match_status: str = "UNMATCHED"
    matched_transaction_id: int | None = None
    suggestion_count: int = 0


class ExpenseIn(BaseModel):
    id: int | None = None
    category: str = Field("GENERAL", max_length=80)
    description: str = Field("", max_length=255)
    currency_code: str = Field(min_length=3, max_length=3)
    amount: Decimal = Field(ge=0)

    @field_validator("amount")
    @classmethod
    def _amount(cls, v: Decimal) -> Decimal:
        return _check_money(v)

    @field_validator("currency_code")
    @classmethod
    def _currency(cls, v: str) -> str:
        return v.upper()


class ExpenseOut(ORMModel):
    id: int
    category: str
    description: str
    currency_code: str
    amount: Decimal


class BaleIn(BaseModel):
    id: int | None = None
    bale_type_id: int
    opening_qty: int = Field(0, ge=0)
    received_qty: int = Field(0, ge=0)
    sold_qty: int = Field(0, ge=0)
    closing_qty: int = Field(0, ge=0)


class BaleOut(ORMModel):
    id: int
    bale_type_id: int
    bale_type_code: str | None = None
    bale_type_name: str | None = None
    opening_qty: int
    received_qty: int
    sold_qty: int
    closing_qty: int


class BaleTypeOut(ORMModel):
    id: int
    code: str
    name: str
    weight_lbs: Decimal | None
    sort_order: int
    is_active: bool


class BankTotalIn(BaseModel):
    """One cell of the sheet's TRANSFERS table."""
    bank_id: int
    currency_code: str = Field(min_length=3, max_length=3)
    amount: Decimal = Field(gt=0)

    @field_validator("amount")
    @classmethod
    def _amount(cls, v: Decimal) -> Decimal:
        return _check_money(v)

    @field_validator("currency_code")
    @classmethod
    def _currency(cls, v: str) -> str:
        return v.upper()


class DailyRecordIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    shop_id: int
    business_date: date
    bale_count: int = Field(0, ge=0)
    invoice_count: int = Field(0, ge=0)
    total_sales_usd: Decimal = Field(Decimal("0.00"), ge=0)
    total_sales_nio: Decimal = Field(Decimal("0.00"), ge=0)
    delivery_usd: Decimal = Field(Decimal("0.00"), ge=0)
    delivery_nio: Decimal = Field(Decimal("0.00"), ge=0)
    commercial_invoice_usd: Decimal = Field(Decimal("0.00"), ge=0)
    commercial_invoice_nio: Decimal = Field(Decimal("0.00"), ge=0)
    credit_usd: Decimal = Field(Decimal("0.00"), ge=0)
    credit_nio: Decimal = Field(Decimal("0.00"), ge=0)
    opening_balance_usd: Decimal = Decimal("0.00")
    opening_balance_nio: Decimal = Decimal("0.00")
    closing_balance_usd: Decimal | None = None
    closing_balance_nio: Decimal | None = None
    closing_balance_source: str = "COMPUTED"
    observations: str = Field("", max_length=4000)
    status: str = "DRAFT"
    # The paper sheet's dollar-only lines.
    commercial_invoice_cash_usd: Decimal = Field(Decimal("0.00"), ge=0)
    commercial_invoice_deposit_usd: Decimal = Field(Decimal("0.00"), ge=0)
    delivery_cash_usd: Decimal = Field(Decimal("0.00"), ge=0)
    delivery_transfer_usd: Decimal = Field(Decimal("0.00"), ge=0)
    declared_closing_usd: Decimal | None = None
    transfers: list[TransferIn] = []
    bank_totals: list[BankTotalIn] = []
    expenses: list[ExpenseIn] = []
    bale_records: list[BaleIn] = []
    # Photos uploaded before saving, to attach to this sheet.
    photo_ids: list[int] = []

    @field_validator(
        "total_sales_usd", "total_sales_nio", "delivery_usd", "delivery_nio",
        "commercial_invoice_usd", "commercial_invoice_nio", "credit_usd", "credit_nio",
        "opening_balance_usd", "opening_balance_nio",
        "closing_balance_usd", "closing_balance_nio",
        "commercial_invoice_cash_usd", "commercial_invoice_deposit_usd",
        "delivery_cash_usd", "delivery_transfer_usd", "declared_closing_usd",
    )
    @classmethod
    def _money(cls, v):
        return _check_money(v) if v is not None else None

    @field_validator("business_date")
    @classmethod
    def _not_future(cls, v: date) -> date:
        # Typing 2062 instead of 2026 should not silently create a record that
        # then never appears in any report.
        from datetime import date as _d, timedelta
        if v > _d.today() + timedelta(days=1):
            raise ValueError("cannot be in the future")
        return v

    @field_validator("status")
    @classmethod
    def _status(cls, v: str) -> str:
        if v not in {"DRAFT", "SUBMITTED"}:
            raise ValueError("must be DRAFT or SUBMITTED")
        return v


class DailyRecordUpdate(DailyRecordIn):
    shop_id: int | None = None
    business_date: date | None = None


class BalanceStep(BaseModel):
    key: str
    label: str
    sign: int
    amount: str
    running_total: str


class BalanceSide(BaseModel):
    steps: list[BalanceStep]
    computed: str
    entered: str
    difference: str
    matches: bool


class DailyRecordOut(ORMModel):
    id: int
    shop_id: int
    shop_name: str | None = None
    shop_code: str | None = None
    business_date: date
    status: str
    bale_count: int
    invoice_count: int
    total_sales_usd: Decimal
    total_sales_nio: Decimal
    delivery_usd: Decimal
    delivery_nio: Decimal
    commercial_invoice_usd: Decimal
    commercial_invoice_nio: Decimal
    credit_usd: Decimal
    credit_nio: Decimal
    opening_balance_usd: Decimal
    opening_balance_nio: Decimal
    closing_balance_usd: Decimal
    closing_balance_nio: Decimal
    closing_balance_source: str
    observations: str
    created_at: datetime
    updated_at: datetime
    submitted_at: datetime | None
    locked_at: datetime | None
    is_demo: bool
    transfers: list[TransferOut] = []
    expenses: list[ExpenseOut] = []
    bale_records: list[BaleOut] = []
    transfer_totals: dict[str, Decimal] = {}
    cash_totals: dict[str, Decimal] = {}
    expense_totals: dict[str, Decimal] = {}
    balance: dict[str, BalanceSide] = {}
    commercial_invoice_cash_usd: Decimal = Decimal("0.00")
    commercial_invoice_deposit_usd: Decimal = Decimal("0.00")
    delivery_cash_usd: Decimal = Decimal("0.00")
    delivery_transfer_usd: Decimal = Decimal("0.00")
    declared_closing_usd: Decimal | None = None
    bank_totals: list[dict] = []
    # The TRANSFERS table with a status per cell, and the sheet in dollars.
    bank_cells: list[dict] = []
    paper: dict = {}
    photos: list["PhotoOut"] = []


class PhotoOut(ORMModel):
    id: int
    original_filename: str
    content_type: str
    file_size: int
    created_at: datetime
    extraction: dict | None = None
    extraction_model: str | None = None
    extraction_error: str | None = None


class DailyRecordRow(ORMModel):
    id: int
    shop_id: int
    shop_name: str | None = None
    business_date: date
    status: str
    bale_count: int
    invoice_count: int
    total_sales_usd: Decimal
    total_sales_nio: Decimal
    transfer_total_usd: Decimal = Decimal("0.00")
    transfer_total_nio: Decimal = Decimal("0.00")
    cash_total_usd: Decimal = Decimal("0.00")
    cash_total_nio: Decimal = Decimal("0.00")
    matched_count: int = 0
    possible_count: int = 0
    unmatched_count: int = 0
    pending_cash_count: int = 0


DailyRecordOut.model_rebuild()
