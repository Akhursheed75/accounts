from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class Currency(Base):
    """Currencies are rows, not an enum: adding one must not require a migration."""

    __tablename__ = "currencies"

    code: Mapped[str] = mapped_column(String(3), primary_key=True)   # USD, NIO
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    symbol: Mapped[str] = mapped_column(String(8), nullable=False)   # $, C$
    decimals: Mapped[int] = mapped_column(Integer, default=2, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class City(Base, TimestampMixin):
    __tablename__ = "cities"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    country: Mapped[str] = mapped_column(String(80), default="Nicaragua", nullable=False)

    shops: Mapped[list["Shop"]] = relationship(back_populates="city")


class Shop(Base, TimestampMixin):
    __tablename__ = "shops"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    city_id: Mapped[int | None] = mapped_column(ForeignKey("cities.id"), index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    city: Mapped[City | None] = relationship(back_populates="shops", lazy="joined")
    user_links: Mapped[list["UserShop"]] = relationship(  # noqa: F821
        back_populates="shop", cascade="all, delete-orphan"
    )


class Bank(Base, TimestampMixin):
    __tablename__ = "banks"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    # Which parser handles this bank's statements; NULL means "not configured yet".
    parser_key: Mapped[str | None] = mapped_column(String(32))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    accounts: Mapped[list["BankAccount"]] = relationship(
        back_populates="bank", cascade="all, delete-orphan", lazy="selectin"
    )


class BankAccount(Base, TimestampMixin):
    __tablename__ = "bank_accounts"
    __table_args__ = (
        UniqueConstraint("bank_id", "account_number", name="uq_bank_accounts_bank_id_account_number"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    bank_id: Mapped[int] = mapped_column(
        ForeignKey("banks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    account_number: Mapped[str] = mapped_column(String(64), nullable=False)
    currency_code: Mapped[str] = mapped_column(
        ForeignKey("currencies.code"), nullable=False, index=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    bank: Mapped[Bank] = relationship(back_populates="accounts", lazy="joined")
    currency: Mapped[Currency] = relationship(lazy="joined")
