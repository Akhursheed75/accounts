from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal

from sqlalchemy import (
    Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index, Integer,
    Numeric, String, Text, Time,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

MONEY = Numeric(18, 2)
ZERO = Decimal("0.00")


class BaleType(Base):
    """100 LBS / 25 LBS and anything else the admin adds later."""

    __tablename__ = "bale_types"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    weight_lbs: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class ShopDailyRecord(Base, TimestampMixin):
    """One accounting sheet: one shop, one business day."""

    __tablename__ = "shop_daily_records"
    __table_args__ = (
        Index(
            "uq_shop_daily_records_shop_date_live",
            "shop_id", "business_date",
            unique=True,
            postgresql_where="deleted_at IS NULL",
        ),
        Index("ix_shop_daily_records_business_date", "business_date"),
        CheckConstraint("bale_count >= 0", name="bale_count_non_negative"),
        CheckConstraint("invoice_count >= 0", name="invoice_count_non_negative"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id"), nullable=False, index=True)
    business_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="DRAFT", nullable=False, index=True)

    # --- sales summary --------------------------------------------------
    bale_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    invoice_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_sales_usd: Mapped[Decimal] = mapped_column(MONEY, default=ZERO, nullable=False)
    total_sales_nio: Mapped[Decimal] = mapped_column(MONEY, default=ZERO, nullable=False)

    # --- sheet concepts kept per currency, never mixed ------------------
    delivery_usd: Mapped[Decimal] = mapped_column(MONEY, default=ZERO, nullable=False)
    delivery_nio: Mapped[Decimal] = mapped_column(MONEY, default=ZERO, nullable=False)
    commercial_invoice_usd: Mapped[Decimal] = mapped_column(MONEY, default=ZERO, nullable=False)
    commercial_invoice_nio: Mapped[Decimal] = mapped_column(MONEY, default=ZERO, nullable=False)
    credit_usd: Mapped[Decimal] = mapped_column(MONEY, default=ZERO, nullable=False)
    credit_nio: Mapped[Decimal] = mapped_column(MONEY, default=ZERO, nullable=False)

    opening_balance_usd: Mapped[Decimal] = mapped_column(MONEY, default=ZERO, nullable=False)
    opening_balance_nio: Mapped[Decimal] = mapped_column(MONEY, default=ZERO, nullable=False)
    closing_balance_usd: Mapped[Decimal] = mapped_column(MONEY, default=ZERO, nullable=False)
    closing_balance_nio: Mapped[Decimal] = mapped_column(MONEY, default=ZERO, nullable=False)
    # COMPUTED means the figure came from the formula; MANUAL means an admin
    # overrode it and the difference is shown rather than hidden.
    closing_balance_source: Mapped[str] = mapped_column(
        String(16), default="COMPUTED", nullable=False
    )

    observations: Mapped[str] = mapped_column(Text, default="", nullable=False)

    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    updated_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    shop: Mapped["Shop"] = relationship(lazy="joined")  # noqa: F821
    transfers: Mapped[list["ShopTransfer"]] = relationship(
        back_populates="daily_record", cascade="all, delete-orphan", lazy="selectin"
    )
    expenses: Mapped[list["Expense"]] = relationship(
        back_populates="daily_record", cascade="all, delete-orphan", lazy="selectin"
    )
    bale_records: Mapped[list["BaleRecord"]] = relationship(
        back_populates="daily_record", cascade="all, delete-orphan", lazy="selectin"
    )


class ShopTransfer(Base, TimestampMixin):
    """A payment the shop says it deposited into a bank. The left-hand side of
    reconciliation. Several rows per bank per day are expected, not exceptional."""

    __tablename__ = "shop_transfers"
    __table_args__ = (
        CheckConstraint("amount > 0", name="amount_positive"),
        Index("ix_shop_transfers_lookup", "currency_code", "amount", "bank_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    daily_record_id: Mapped[int] = mapped_column(
        ForeignKey("shop_daily_records.id", ondelete="CASCADE"), nullable=False, index=True
    )
    bank_id: Mapped[int] = mapped_column(ForeignKey("banks.id"), nullable=False, index=True)
    bank_account_id: Mapped[int | None] = mapped_column(ForeignKey("bank_accounts.id"), index=True)
    currency_code: Mapped[str] = mapped_column(
        ForeignKey("currencies.code"), nullable=False, index=True
    )
    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    reference: Mapped[str | None] = mapped_column(String(120), index=True)
    deposit_time: Mapped[time | None] = mapped_column(Time)
    note: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    # Set when a user decides this transfer will never have a bank counterpart.
    is_ignored: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    ignored_reason: Mapped[str | None] = mapped_column(String(255))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)

    daily_record: Mapped[ShopDailyRecord] = relationship(back_populates="transfers")
    bank: Mapped["Bank"] = relationship(lazy="joined")  # noqa: F821


class Expense(Base, TimestampMixin):
    __tablename__ = "expenses"
    __table_args__ = (CheckConstraint("amount >= 0", name="amount_non_negative"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    daily_record_id: Mapped[int] = mapped_column(
        ForeignKey("shop_daily_records.id", ondelete="CASCADE"), nullable=False, index=True
    )
    category: Mapped[str] = mapped_column(String(80), default="GENERAL", nullable=False)
    description: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    currency_code: Mapped[str] = mapped_column(ForeignKey("currencies.code"), nullable=False)
    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)

    daily_record: Mapped[ShopDailyRecord] = relationship(back_populates="expenses")


class BaleRecord(Base, TimestampMixin):
    __tablename__ = "bale_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    daily_record_id: Mapped[int] = mapped_column(
        ForeignKey("shop_daily_records.id", ondelete="CASCADE"), nullable=False, index=True
    )
    bale_type_id: Mapped[int] = mapped_column(ForeignKey("bale_types.id"), nullable=False)
    opening_qty: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    received_qty: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    sold_qty: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    closing_qty: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    daily_record: Mapped[ShopDailyRecord] = relationship(back_populates="bale_records")
    bale_type: Mapped[BaleType] = relationship(lazy="joined")
