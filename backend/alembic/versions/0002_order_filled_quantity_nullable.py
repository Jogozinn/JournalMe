"""Allow canceled orders to retain unavailable filled quantity.

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("orders") as batch_op:
        batch_op.alter_column(
            "filled_quantity",
            existing_type=sa.Numeric(18, 6),
            nullable=True,
        )


def downgrade() -> None:
    with op.batch_alter_table("orders") as batch_op:
        batch_op.alter_column(
            "filled_quantity",
            existing_type=sa.Numeric(18, 6),
            nullable=False,
        )
