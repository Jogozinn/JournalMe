"""Add secure desktop bridge credentials and execution contract metadata.

Revision ID: 0012
Revises: 0011
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("broker_connections", sa.Column("bridge_token_hash", sa.String(length=64), nullable=True))
    op.add_column("broker_connections", sa.Column("bridge_token_prefix", sa.String(length=24), nullable=True))
    op.add_column("broker_connections", sa.Column("bridge_token_created_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("broker_execution_events", sa.Column("point_value", sa.Numeric(18, 6), nullable=True))
    op.add_column("broker_execution_events", sa.Column("currency", sa.String(length=3), nullable=False, server_default="USD"))


def downgrade() -> None:
    op.drop_column("broker_execution_events", "currency")
    op.drop_column("broker_execution_events", "point_value")
    op.drop_column("broker_connections", "bridge_token_created_at")
    op.drop_column("broker_connections", "bridge_token_prefix")
    op.drop_column("broker_connections", "bridge_token_hash")
