"""Add learning scope, smart review fields, and broker connector foundation.

Revision ID: 0011
Revises: 0010
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None

UUID_TYPE = sa.Uuid()
MONEY = sa.Numeric(18, 4)
PRICE = sa.Numeric(18, 8)


def upgrade() -> None:
    op.add_column(
        "trading_accounts",
        sa.Column("include_in_learning", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column("daily_journals", sa.Column("quick_rating", sa.String(length=20), nullable=True))
    op.add_column(
        "daily_journals",
        sa.Column("quick_focus_tags_json", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
    )
    op.add_column(
        "daily_journals",
        sa.Column("quick_emotion_tags_json", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
    )
    op.add_column(
        "daily_journals",
        sa.Column("quick_behavior_tags_json", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
    )
    op.add_column("daily_journals", sa.Column("quick_note", sa.Text(), nullable=True))
    op.add_column(
        "daily_journals",
        sa.Column("review_depth", sa.String(length=20), nullable=False, server_default="quick"),
    )

    op.create_table(
        "broker_connections",
        sa.Column("id", UUID_TYPE, nullable=False),
        sa.Column("user_id", UUID_TYPE, nullable=False),
        sa.Column("account_id", UUID_TYPE, nullable=True),
        sa.Column("provider", sa.String(length=60), nullable=False),
        sa.Column("connection_type", sa.String(length=40), nullable=False),
        sa.Column("display_name", sa.String(length=160), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("external_account_id", sa.String(length=120), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["trading_accounts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "provider", "connection_type", "external_account_id",
            name="uq_broker_connection_external",
        ),
    )
    op.create_index("ix_broker_connections_user_id", "broker_connections", ["user_id"])
    op.create_index("ix_broker_connections_account_id", "broker_connections", ["account_id"])
    op.create_index("ix_broker_connections_status", "broker_connections", ["status"])

    op.create_table(
        "broker_execution_events",
        sa.Column("id", UUID_TYPE, nullable=False),
        sa.Column("user_id", UUID_TYPE, nullable=False),
        sa.Column("account_id", UUID_TYPE, nullable=True),
        sa.Column("connection_id", UUID_TYPE, nullable=False),
        sa.Column("provider", sa.String(length=60), nullable=False),
        sa.Column("external_execution_id", sa.String(length=160), nullable=False),
        sa.Column("external_order_id", sa.String(length=160), nullable=True),
        sa.Column("symbol", sa.String(length=80), nullable=False),
        sa.Column("side", sa.String(length=10), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 6), nullable=False),
        sa.Column("price", PRICE, nullable=False),
        sa.Column("commission", MONEY, nullable=True),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ingest_status", sa.String(length=30), nullable=False),
        sa.Column("source_payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["trading_accounts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["connection_id"], ["broker_connections.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "connection_id", "external_execution_id", name="uq_broker_execution_external"
        ),
    )
    op.create_index("ix_broker_execution_events_user_id", "broker_execution_events", ["user_id"])
    op.create_index("ix_broker_execution_events_account_id", "broker_execution_events", ["account_id"])
    op.create_index("ix_broker_execution_events_connection_id", "broker_execution_events", ["connection_id"])
    op.create_index("ix_broker_execution_events_provider", "broker_execution_events", ["provider"])
    op.create_index("ix_broker_execution_events_symbol", "broker_execution_events", ["symbol"])
    op.create_index("ix_broker_execution_events_executed_at", "broker_execution_events", ["executed_at"])
    op.create_index("ix_broker_execution_events_ingest_status", "broker_execution_events", ["ingest_status"])
    op.create_index(
        "ix_broker_execution_account_time",
        "broker_execution_events",
        ["account_id", "executed_at"],
    )

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("ALTER TABLE broker_connections ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE broker_execution_events ENABLE ROW LEVEL SECURITY")
        owner_expr = """
            EXISTS (
                SELECT 1 FROM auth_identities ai
                WHERE ai.user_id = {table}.user_id
                  AND ai.provider = 'supabase'
                  AND ai.subject = auth.uid()::text
            )
        """
        for table in ("broker_connections", "broker_execution_events"):
            condition = owner_expr.format(table=table)
            op.execute(
                f"CREATE POLICY {table}_own_rows ON {table} FOR ALL TO authenticated "
                f"USING ({condition}) WITH CHECK ({condition})"
            )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP POLICY IF EXISTS broker_execution_events_own_rows ON broker_execution_events")
        op.execute("DROP POLICY IF EXISTS broker_connections_own_rows ON broker_connections")
    op.drop_index("ix_broker_execution_account_time", table_name="broker_execution_events")
    op.drop_index("ix_broker_execution_events_ingest_status", table_name="broker_execution_events")
    op.drop_index("ix_broker_execution_events_executed_at", table_name="broker_execution_events")
    op.drop_index("ix_broker_execution_events_symbol", table_name="broker_execution_events")
    op.drop_index("ix_broker_execution_events_provider", table_name="broker_execution_events")
    op.drop_index("ix_broker_execution_events_connection_id", table_name="broker_execution_events")
    op.drop_index("ix_broker_execution_events_account_id", table_name="broker_execution_events")
    op.drop_index("ix_broker_execution_events_user_id", table_name="broker_execution_events")
    op.drop_table("broker_execution_events")
    op.drop_index("ix_broker_connections_status", table_name="broker_connections")
    op.drop_index("ix_broker_connections_account_id", table_name="broker_connections")
    op.drop_index("ix_broker_connections_user_id", table_name="broker_connections")
    op.drop_table("broker_connections")
    op.drop_column("daily_journals", "review_depth")
    op.drop_column("daily_journals", "quick_note")
    op.drop_column("daily_journals", "quick_behavior_tags_json")
    op.drop_column("daily_journals", "quick_emotion_tags_json")
    op.drop_column("daily_journals", "quick_focus_tags_json")
    op.drop_column("daily_journals", "quick_rating")
    op.drop_column("trading_accounts", "include_in_learning")
