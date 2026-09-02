from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index, Integer,
    Numeric, String, Text, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

MONEY = Numeric(18, 2)


class BankStatement(Base, TimestampMixin):
    __tablename__ = "bank_statements"
    __table_args__ = (
        # The same PDF cannot be uploaded twice for the same account.
        UniqueConstraint("bank_account_id", "file_hash", name="uq_bank_statements_account_file"),
        Index("ix_bank_statements_period", "period_start", "period_end"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    bank_account_id: Mapped[int] = mapped_column(
        ForeignKey("bank_accounts.id"), nullable=False, index=True
    )
    period_start: Mapped[date | None] = mapped_column(Date)
    period_end: Mapped[date | None] = mapped_column(Date)

    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_key: Mapped[str] = mapped_column(String(400), nullable=False)
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    content_type: Mapped[str] = mapped_column(String(120), nullable=False)
    page_count: Mapped[int | None] = mapped_column(Integer)

    status: Mapped[str] = mapped_column(String(24), default="UPLOADED", nullable=False, index=True)
    parser_key: Mapped[str | None] = mapped_column(String(32))
    extraction_method: Mapped[str] = mapped_column(String(16), default="UNKNOWN", nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text)
    warnings: Mapped[list | None] = mapped_column(JSONB)
    transaction_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    duplicate_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    statement_opening_balance: Mapped[Decimal | None] = mapped_column(MONEY)
    statement_closing_balance: Mapped[Decimal | None] = mapped_column(MONEY)

    uploaded_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    account: Mapped["BankAccount"] = relationship(lazy="joined")  # noqa: F821
    transactions: Mapped[list["BankTransaction"]] = relationship(
        back_populates="statement", cascade="all, delete-orphan"
    )


class BankTransaction(Base, TimestampMixin):
    """One extracted line. Immutable once written: corrections create a new
    statement rather than editing history."""

    __tablename__ = "bank_transactions"
    __table_args__ = (
        # Re-uploading an overlapping statement must not double-count a line.
        UniqueConstraint(
            "bank_account_id", "dedupe_hash", name="uq_bank_transactions_account_dedupe"
        ),
        CheckConstraint("debit >= 0 AND credit >= 0", name="amounts_non_negative"),
        CheckConstraint("direction IN ('CREDIT','DEBIT')", name="direction_valid"),
        Index("ix_bank_transactions_match_lookup", "currency_code", "amount", "txn_date"),
        Index("ix_bank_transactions_account_date", "bank_account_id", "txn_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    statement_id: Mapped[int] = mapped_column(
        ForeignKey("bank_statements.id", ondelete="CASCADE"), nullable=False, index=True
    )
    bank_account_id: Mapped[int] = mapped_column(
        ForeignKey("bank_accounts.id"), nullable=False, index=True
    )
    bank_id: Mapped[int] = mapped_column(ForeignKey("banks.id"), nullable=False, index=True)

    txn_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    value_date: Mapped[date | None] = mapped_column(Date)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    reference: Mapped[str | None] = mapped_column(String(120), index=True)
    external_id: Mapped[str | None] = mapped_column(String(120), index=True)
    movement_type: Mapped[str | None] = mapped_column(String(16))

    debit: Mapped[Decimal] = mapped_column(MONEY, default=0, nullable=False)
    credit: Mapped[Decimal] = mapped_column(MONEY, default=0, nullable=False)
    # Absolute value; direction carries the sign. Matching compares absolutes.
    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False, index=True)
    direction: Mapped[str] = mapped_column(String(8), nullable=False, index=True)
    currency_code: Mapped[str] = mapped_column(
        ForeignKey("currencies.code"), nullable=False, index=True
    )
    running_balance: Mapped[Decimal | None] = mapped_column(MONEY)

    row_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    page_number: Mapped[int | None] = mapped_column(Integer)
    raw_text: Mapped[str | None] = mapped_column(Text)
    extraction_confidence: Mapped[int | None] = mapped_column(Integer)
    dedupe_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_ignored: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    ignored_reason: Mapped[str | None] = mapped_column(String(255))

    statement: Mapped[BankStatement] = relationship(back_populates="transactions")
    bank: Mapped["Bank"] = relationship(lazy="joined")  # noqa: F821
