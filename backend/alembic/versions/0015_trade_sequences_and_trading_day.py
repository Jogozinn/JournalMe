"""Add trade review sequences.

Revision ID: 0015
Revises: 0014
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())

    if "trade_sequences" not in tables:
        op.create_table(
            "trade_sequences",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("account_id", sa.Uuid(), nullable=False),
            sa.Column("title", sa.String(length=240), nullable=True),
            sa.Column("thesis", sa.Text(), nullable=True),
            sa.Column("shared_context", sa.Text(), nullable=True),
            sa.Column("lesson_learned", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["account_id"], ["trading_accounts.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_trade_sequences_account_id", "trade_sequences", ["account_id"])

    if "trade_sequence_trades" not in tables:
        op.create_table(
            "trade_sequence_trades",
            sa.Column("sequence_id", sa.Uuid(), nullable=False),
            sa.Column("trade_id", sa.Uuid(), nullable=False),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("note", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["sequence_id"], ["trade_sequences.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["trade_id"], ["trades.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("sequence_id", "trade_id"),
            sa.UniqueConstraint("trade_id", name="uq_trade_sequence_trade"),
        )
        op.create_index("ix_trade_sequence_trades_trade_id", "trade_sequence_trades", ["trade_id"])
        op.create_index("ix_trade_sequence_members_order", "trade_sequence_trades", ["sequence_id", "sort_order"])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "trade_sequence_trades" in tables:
        op.drop_table("trade_sequence_trades")
    if "trade_sequences" in tables:
        op.drop_table("trade_sequences")
