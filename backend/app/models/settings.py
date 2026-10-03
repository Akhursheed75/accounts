from __future__ import annotations

from sqlalchemy import Boolean, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin

# How the closing balance is worked out. Each component names a field on the
# daily record (or a computed total) and whether it adds or subtracts. It lives
# in the database because the paper sheet's arithmetic is the business's rule,
# not ours to hard-code.
DEFAULT_BALANCE_COMPONENTS = [
    {"key": "opening_balance", "label": "Starting balance", "sign": 1, "enabled": True},
    {"key": "total_sales", "label": "Total sales", "sign": 1, "enabled": True},
    {"key": "total_expenses", "label": "Total expenses", "sign": -1, "enabled": True},
    {"key": "total_transfers", "label": "Deposited to banks", "sign": -1, "enabled": True},
    {"key": "total_cash", "label": "Cash received", "sign": -1, "enabled": True},
    {"key": "delivery", "label": "Delivery", "sign": -1, "enabled": False},
    {"key": "credit", "label": "Credit given", "sign": -1, "enabled": False},
    {"key": "commercial_invoice", "label": "Commercial invoice", "sign": 0, "enabled": False},
]


class SystemSetting(Base, TimestampMixin):
    __tablename__ = "system_settings"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    company_name: Mapped[str] = mapped_column(String(160), default="", nullable=False)
    base_currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)
    balance_components: Mapped[list] = mapped_column(
        JSONB, default=DEFAULT_BALANCE_COMPONENTS, nullable=False
    )
    # Whether a shop user may edit a record after submitting it.
    allow_shop_edit_after_submit: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )
    lock_records_after_days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
