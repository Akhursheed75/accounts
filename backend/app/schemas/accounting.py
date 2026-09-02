from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

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
    bank_id: int
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


class TransferOut(ORMModel):
    id: int
    bank_id: int
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
    transfers: list[TransferIn] = []
    expenses: list[ExpenseIn] = []
    bale_records: list[BaleIn] = []

    @field_validator(
        "total_sales_usd", "total_sales_nio", "delivery_usd", "delivery_nio",
        "commercial_invoice_usd", "commercial_invoice_nio", "credit_usd", "credit_nio",
        "opening_balance_usd", "opening_balance_nio",
        "closing_balance_usd", "closing_balance_nio",
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
    expense_totals: dict[str, Decimal] = {}
    balance: dict[str, BalanceSide] = {}


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
    matched_count: int = 0
    possible_count: int = 0
    unmatched_count: int = 0
