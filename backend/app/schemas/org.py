from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class CurrencyOut(ORMModel):
    code: str
    name: str
    symbol: str
    decimals: int
    is_active: bool


class CityIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    country: str = Field("Nicaragua", max_length=80)


class CityOut(ORMModel):
    id: int
    name: str
    country: str


class ShopIn(BaseModel):
    code: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=120)
    city_id: int | None = None
    is_active: bool = True


class ShopUpdate(BaseModel):
    code: str | None = Field(None, min_length=1, max_length=32)
    name: str | None = Field(None, min_length=1, max_length=120)
    city_id: int | None = None
    is_active: bool | None = None


class ShopOut(ORMModel):
    id: int
    code: str
    name: str
    city_id: int | None
    city_name: str | None = None
    is_active: bool
    is_demo: bool


class BankAccountIn(BaseModel):
    bank_id: int
    label: str = Field(min_length=1, max_length=120)
    account_number: str = Field(min_length=1, max_length=64)
    currency_code: str = Field(min_length=3, max_length=3)
    is_active: bool = True


class BankAccountUpdate(BaseModel):
    label: str | None = Field(None, min_length=1, max_length=120)
    account_number: str | None = Field(None, min_length=1, max_length=64)
    currency_code: str | None = Field(None, min_length=3, max_length=3)
    is_active: bool | None = None


class BankAccountOut(ORMModel):
    id: int
    bank_id: int
    bank_code: str | None = None
    bank_name: str | None = None
    label: str
    account_number: str
    currency_code: str
    is_active: bool


class BankIn(BaseModel):
    code: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=120)
    parser_key: str | None = Field(None, max_length=32)
    is_active: bool = True


class BankUpdate(BaseModel):
    code: str | None = Field(None, min_length=1, max_length=32)
    name: str | None = Field(None, min_length=1, max_length=120)
    parser_key: str | None = Field(None, max_length=32)
    is_active: bool | None = None


class BankOut(ORMModel):
    id: int
    code: str
    name: str
    parser_key: str | None
    parser_available: bool = False
    is_active: bool
    accounts: list[BankAccountOut] = []
