"""Add a non-destructive lifecycle status for trading accounts.

Revision ID: 0009
Revises: 0008
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def _lifecycle_status_exists() -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(
        column["name"] == "lifecycle_status"
        for column in inspector.get_columns("trading_accounts")
    )


def upgrade() -> None:
    if not _lifecycle_status_exists():
        op.add_column(
            "trading_accounts",
            sa.Column(
                "lifecycle_status",
                sa.String(length=20),
                nullable=False,
                server_default="active",
            ),
        )


def downgrade() -> None:
    if _lifecycle_status_exists():
        with op.batch_alter_table("trading_accounts") as batch_op:
            batch_op.drop_column("lifecycle_status")
