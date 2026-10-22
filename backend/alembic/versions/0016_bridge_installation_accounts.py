"""Add source-scoped accounts beneath a bridge installation.

Revision ID: 0016
Revises: 0015
"""

import sqlalchemy as sa
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("broker_connections", sa.Column("installation_id", sa.Uuid(), nullable=True))
    op.add_column("broker_connections", sa.Column("source_namespace", sa.String(160), nullable=True))
    op.add_column("broker_connections", sa.Column("source_account_name", sa.String(160), nullable=True))
    op.create_index("ix_broker_connections_installation_id", "broker_connections", ["installation_id"])
    op.create_foreign_key(
        "fk_broker_connections_installation_id", "broker_connections", "broker_connections",
        ["installation_id"], ["id"], ondelete="SET NULL",
    )
    op.create_unique_constraint(
        "uq_bridge_installation_source_account", "broker_connections",
        ["installation_id", "source_namespace", "source_account_name"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_bridge_installation_source_account", "broker_connections", type_="unique")
    op.drop_constraint("fk_broker_connections_installation_id", "broker_connections", type_="foreignkey")
    op.drop_index("ix_broker_connections_installation_id", table_name="broker_connections")
    op.drop_column("broker_connections", "source_account_name")
    op.drop_column("broker_connections", "source_namespace")
    op.drop_column("broker_connections", "installation_id")
