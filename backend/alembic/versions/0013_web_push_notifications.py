"""Add background Web Push subscriptions and delivery state.

Revision ID: 0013
Revises: 0012
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "push_subscriptions" not in tables:
        op.create_table(
            "push_subscriptions",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("user_id", sa.Uuid(), nullable=False),
            sa.Column("subscription_hash", sa.String(length=64), nullable=False),
            sa.Column("endpoint", sa.Text(), nullable=False),
            sa.Column("p256dh", sa.Text(), nullable=False),
            sa.Column("auth", sa.Text(), nullable=False),
            sa.Column("user_agent", sa.String(length=500), nullable=True),
            sa.Column("device_label", sa.String(length=120), nullable=True),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("user_id", "subscription_hash", name="uq_push_subscription_user_endpoint"),
        )
        op.create_index("ix_push_subscriptions_user_id", "push_subscriptions", ["user_id"])
        op.create_index("ix_push_subscriptions_enabled", "push_subscriptions", ["enabled"])

    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "notification_deliveries" not in tables:
        op.create_table(
            "notification_deliveries",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("user_id", sa.Uuid(), nullable=False),
            sa.Column("account_id", sa.Uuid(), nullable=True),
            sa.Column("notice_key", sa.String(length=220), nullable=False),
            sa.Column("kind", sa.String(length=40), nullable=False),
            sa.Column("title", sa.String(length=240), nullable=False),
            sa.Column("body", sa.Text(), nullable=False),
            sa.Column("target_url", sa.String(length=500), nullable=False),
            sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("metadata_json", sa.JSON(), nullable=False, server_default="{}"),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["account_id"], ["trading_accounts.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("user_id", "notice_key", name="uq_notification_delivery_notice"),
        )
        op.create_index("ix_notification_deliveries_user_id", "notification_deliveries", ["user_id"])
        op.create_index("ix_notification_deliveries_sent_at", "notification_deliveries", ["sent_at"])

    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("user_preferences")}
    if "notification_preferences_json" not in columns:
        op.add_column(
            "user_preferences",
            sa.Column("notification_preferences_json", sa.JSON(), nullable=False, server_default="{}"),
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("user_preferences")}
    if "notification_preferences_json" in columns:
        with op.batch_alter_table("user_preferences") as batch_op:
            batch_op.drop_column("notification_preferences_json")
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "notification_deliveries" in tables:
        op.drop_index("ix_notification_deliveries_sent_at", table_name="notification_deliveries")
        op.drop_index("ix_notification_deliveries_user_id", table_name="notification_deliveries")
        op.drop_table("notification_deliveries")
    if "push_subscriptions" in tables:
        op.drop_index("ix_push_subscriptions_enabled", table_name="push_subscriptions")
        op.drop_index("ix_push_subscriptions_user_id", table_name="push_subscriptions")
        op.drop_table("push_subscriptions")
