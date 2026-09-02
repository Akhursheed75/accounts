from __future__ import annotations

import re
from typing import Annotated, Generic, TypeVar

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

_EMAIL = re.compile(r"^[^@\s]+@[^@\s.]+(\.[^@\s.]+)+$")


def _valid_email(value: str) -> str:
    """Deliberately looser than RFC-perfect validation.

    Self-hosted businesses use internal domains — company.local, an intranet
    host — and a stricter library rejects them outright. The address only has to
    be a plausible one; whether mail reaches it is not this system's business."""
    cleaned = value.strip().lower()
    if not _EMAIL.match(cleaned) or len(cleaned) > 255:
        raise ValueError("is not a valid email address")
    return cleaned


Email = Annotated[str, AfterValidator(_valid_email)]

T = TypeVar("T")


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int

    @property
    def pages(self) -> int:
        return max(1, -(-self.total // self.page_size))


class PageParams(BaseModel):
    page: int = Field(1, ge=1)
    page_size: int = Field(50, ge=1, le=500)

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


class Message(BaseModel):
    message: str


class MoneyPair(BaseModel):
    """Every total in this system is reported per currency. There is deliberately
    no combined figure: adding USD to cordobas would be a lie."""

    usd: str = "0.00"
    nio: str = "0.00"
