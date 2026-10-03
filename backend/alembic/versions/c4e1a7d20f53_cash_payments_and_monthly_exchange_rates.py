"""cash payments and monthly exchange rates

Revision ID: c4e1a7d20f53
Revises: 9501dbd3d7b1
Create Date: 2026-10-03 00:27:19.741917+00:00

- shop_transfers.payment_method (BANK | CASH); bank_id becomes optional for cash,
  with the database enforcing that a BANK payment still names its bank.
- match_settings.cash_deposit_window_days: how far forward a cash payment looks
  for the deposit that banked it.
- exchange_rates: one C$-per-USD rate per month, for USD presentation only.
- The "Cash received" balance component is added to the existing settings row,
  so cash keeps reducing the closing balance exactly as it did when it had to be
  typed in as a bank transfer.
"""
from __future__ import annotations

import json

from alembic import op
import sqlalchemy as sa


revision = 'c4e1a7d20f53'
down_revision = '9501dbd3d7b1'
branch_labels = None
depends_on = None

CASH_COMPONENT = {"key": "total_cash", "label": "Cash received", "sign": -1, "enabled": True}


def upgrade() -> None:
    op.create_table('exchange_rates',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('month', sa.Date(), nullable=False),
    sa.Column('nio_per_usd', sa.Numeric(precision=12, scale=4), nullable=False),
    sa.Column('set_by_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('EXTRACT(DAY FROM month) = 1', name=op.f('ck_exchange_rates_month_is_first_day')),
    sa.CheckConstraint('nio_per_usd > 0', name=op.f('ck_exchange_rates_rate_positive')),
    sa.ForeignKeyConstraint(['set_by_id'], ['users.id'], name=op.f('fk_exchange_rates_set_by_id_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_exchange_rates')),
    sa.UniqueConstraint('month', name=op.f('uq_exchange_rates_month'))
    )
    op.add_column('match_settings', sa.Column('cash_deposit_window_days', sa.Integer(), server_default='7', nullable=False))

    # Every existing row is a bank payment, so the server default fills them in.
    op.add_column('shop_transfers', sa.Column('payment_method', sa.String(length=8), server_default='BANK', nullable=False))
    op.alter_column('shop_transfers', 'bank_id',
               existing_type=sa.INTEGER(),
               nullable=True)
    op.create_index(op.f('ix_shop_transfers_payment_method'), 'shop_transfers', ['payment_method'], unique=False)
    op.create_check_constraint(
        op.f('ck_shop_transfers_payment_method_valid'), 'shop_transfers',
        "payment_method IN ('BANK','CASH')",
    )
    op.create_check_constraint(
        op.f('ck_shop_transfers_bank_payment_has_bank'), 'shop_transfers',
        "payment_method = 'CASH' OR bank_id IS NOT NULL",
    )

    # Insert "Cash received" straight after "Deposited to banks" wherever an
    # installation has customised its components, rather than resetting them.
    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT id, balance_components FROM system_settings")).fetchall()
    for row_id, components in rows:
        components = list(components or [])
        if any(c.get("key") == "total_cash" for c in components):
            continue
        position = next(
            (i + 1 for i, c in enumerate(components) if c.get("key") == "total_transfers"),
            len(components),
        )
        components.insert(position, dict(CASH_COMPONENT))
        bind.execute(
            sa.text("UPDATE system_settings SET balance_components = CAST(:c AS jsonb) WHERE id = :id"),
            {"c": json.dumps(components), "id": row_id},
        )


def downgrade() -> None:
    bind = op.get_bind()
    cash_rows = bind.execute(
        sa.text("SELECT count(*) FROM shop_transfers WHERE payment_method = 'CASH'")
    ).scalar()
    if cash_rows:
        raise RuntimeError(
            f"{cash_rows} cash payment(s) exist. They have no bank, so bank_id cannot be "
            "made required again without inventing one. Reassign or archive them first."
        )
    rows = bind.execute(sa.text("SELECT id, balance_components FROM system_settings")).fetchall()
    for row_id, components in rows:
        kept = [c for c in (components or []) if c.get("key") != "total_cash"]
        bind.execute(
            sa.text("UPDATE system_settings SET balance_components = CAST(:c AS jsonb) WHERE id = :id"),
            {"c": json.dumps(kept), "id": row_id},
        )
    op.drop_constraint(op.f('ck_shop_transfers_bank_payment_has_bank'), 'shop_transfers', type_='check')
    op.drop_constraint(op.f('ck_shop_transfers_payment_method_valid'), 'shop_transfers', type_='check')
    op.drop_index(op.f('ix_shop_transfers_payment_method'), table_name='shop_transfers')
    op.alter_column('shop_transfers', 'bank_id',
               existing_type=sa.INTEGER(),
               nullable=False)
    op.drop_column('shop_transfers', 'payment_method')
    op.drop_column('match_settings', 'cash_deposit_window_days')
    op.drop_table('exchange_rates')
