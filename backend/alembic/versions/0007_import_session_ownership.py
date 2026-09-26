"""Add direct ownership to import sessions.

Revision ID: 0007
Revises: 0006
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("import_sessions") as batch:
        batch.add_column(sa.Column("user_id", sa.Uuid(), nullable=True))
        batch.create_foreign_key(
            "fk_import_sessions_user_id_users", "users", ["user_id"], ["id"], ondelete="CASCADE"
        )
        batch.create_index("ix_import_sessions_user_id", ["user_id"])
    op.execute(
        "UPDATE import_sessions SET user_id = ("
        "SELECT user_id FROM trading_accounts "
        "WHERE trading_accounts.id = import_sessions.account_id) "
        "WHERE account_id IS NOT NULL"
    )


def downgrade() -> None:
    with op.batch_alter_table("import_sessions") as batch:
        batch.drop_index("ix_import_sessions_user_id")
        batch.drop_constraint("fk_import_sessions_user_id_users", type_="foreignkey")
        batch.drop_column("user_id")
