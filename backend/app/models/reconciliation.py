from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, Numeric, String, Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class ReconciliationMatch(Base, TimestampMixin):
    """A link between one shop transfer and one bank transaction.

    Rows are never deleted. Unmatching sets is_active false and records who and
    why, so the history of a reconciliation is always reconstructable."""

    __tablename__ = "reconciliation_matches"
    __table_args__ = (
        # The database, not the application, is what guarantees a bank
        # transaction is confirmed against at most one shop transfer.
        Index(
            "uq_recon_active_bank_txn",
            "bank_transaction_id",
            unique=True,
            postgresql_where="is_active AND status = 'CONFIRMED'",
        ),
        Index(
            "uq_recon_active_transfer",
            "shop_transfer_id",
            unique=True,
            postgresql_where="is_active AND status = 'CONFIRMED'",
        ),
        Index("ix_recon_status", "status", "is_active"),
        CheckConstraint("confidence BETWEEN 0 AND 100", name="confidence_range"),
        CheckConstraint(
            "status IN ('CONFIRMED','SUGGESTED','REJECTED')", name="status_valid"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    shop_transfer_id: Mapped[int] = mapped_column(
        ForeignKey("shop_transfers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    bank_transaction_id: Mapped[int] = mapped_column(
        ForeignKey("bank_transactions.id", ondelete="CASCADE"), nullable=False, index=True
    )

    status: Mapped[str] = mapped_column(String(16), nullable=False, default="SUGGESTED")
    match_type: Mapped[str] = mapped_column(String(16), nullable=False, default="POSSIBLE")
    confidence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    amount_delta: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    date_delta_days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # Human-readable list of the signals that produced the score.
    score_breakdown: Mapped[list | None] = mapped_column(JSONB)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    matched_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    matched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    unmatched_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    unmatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    note: Mapped[str | None] = mapped_column(Text)

    transfer: Mapped["ShopTransfer"] = relationship(lazy="joined")        # noqa: F821
    transaction: Mapped["BankTransaction"] = relationship(lazy="joined")  # noqa: F821


class MatchSetting(Base, TimestampMixin):
    """Single-row table holding the tunable reconciliation rules."""

    __tablename__ = "match_settings"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    date_window_days: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    amount_tolerance: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), default=Decimal("0.00"), nullable=False
    )
    auto_confirm_score: Mapped[int] = mapped_column(Integer, default=95, nullable=False)
    suggest_score: Mapped[int] = mapped_column(Integer, default=60, nullable=False)
    # When several candidates tie at or above auto_confirm_score, never guess.
    auto_confirm_requires_unique: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )
    match_debit_transactions: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
