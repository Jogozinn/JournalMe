"""Add auditable trade accounting state and versioned balance snapshots.

Revision ID: 0017
Revises: 0016
"""

import sqlalchemy as sa

from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("trades") as batch_op:
        batch_op.add_column(
            sa.Column(
                "accounting_status",
                sa.String(24),
                nullable=False,
                server_default="included",
            )
        )
        batch_op.add_column(
            sa.Column("accounting_exclusion_reason", sa.Text(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("superseded_by_trade_id", sa.Uuid(), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_trades_superseded_by_trade_id",
            "trades",
            ["superseded_by_trade_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index("ix_trades_accounting_status", ["accounting_status"])

    with op.batch_alter_table("daily_balances") as batch_op:
        batch_op.drop_constraint("uq_daily_balance_source", type_="unique")
        batch_op.add_column(
            sa.Column("revision", sa.Integer(), nullable=False, server_default="1")
        )
        batch_op.add_column(sa.Column("supersedes_id", sa.Uuid(), nullable=True))
        batch_op.create_foreign_key(
            "fk_daily_balances_supersedes_id",
            "daily_balances",
            ["supersedes_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_unique_constraint(
            "uq_daily_balance_revision",
            ["account_id", "trade_date", "source_identity", "revision"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    excluded = bind.execute(
        sa.text(
            "SELECT count(*) FROM trades "
            "WHERE accounting_status <> 'included' "
            "OR accounting_exclusion_reason IS NOT NULL "
            "OR superseded_by_trade_id IS NOT NULL"
        )
    ).scalar_one()
    revised = bind.execute(
        sa.text(
            "SELECT count(*) FROM daily_balances "
            "WHERE revision <> 1 OR supersedes_id IS NOT NULL"
        )
    ).scalar_one()
    if excluded or revised:
        raise RuntimeError(
            "Cannot downgrade accounting revision migration while excluded trades "
            "or revised balance snapshots exist; export and explicitly resolve that "
            "history before retrying."
        )

    with op.batch_alter_table("daily_balances") as batch_op:
        batch_op.drop_constraint("uq_daily_balance_revision", type_="unique")
        batch_op.drop_constraint("fk_daily_balances_supersedes_id", type_="foreignkey")
        batch_op.drop_column("supersedes_id")
        batch_op.drop_column("revision")
        batch_op.create_unique_constraint(
            "uq_daily_balance_source",
            ["account_id", "trade_date", "source_identity"],
        )
    with op.batch_alter_table("trades") as batch_op:
        batch_op.drop_index("ix_trades_accounting_status")
        batch_op.drop_constraint("fk_trades_superseded_by_trade_id", type_="foreignkey")
        batch_op.drop_column("superseded_by_trade_id")
        batch_op.drop_column("accounting_exclusion_reason")
        batch_op.drop_column("accounting_status")
