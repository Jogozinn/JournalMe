"""Add companion trading episodes and timeline moments.

Revision ID: 0014
Revises: 0013
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def _index_names(table: str) -> set[str]:
    return {item["name"] for item in sa.inspect(op.get_bind()).get_indexes(table)}


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())

    if "trading_episodes" not in tables:
        op.create_table(
            "trading_episodes",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("user_id", sa.Uuid(), nullable=False),
            sa.Column("account_id", sa.Uuid(), nullable=True),
            sa.Column("matched_trade_id", sa.Uuid(), nullable=True),
            sa.Column("symbol", sa.String(length=80), nullable=True),
            sa.Column("side", sa.String(length=10), nullable=True),
            sa.Column("title", sa.String(length=240), nullable=True),
            sa.Column("status", sa.String(length=30), nullable=False, server_default="active"),
            sa.Column("source", sa.String(length=80), nullable=False, server_default="journalme_companion"),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["account_id"], ["trading_accounts.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["matched_trade_id"], ["trades.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_trading_episodes_user_id", "trading_episodes", ["user_id"])
        op.create_index("ix_trading_episodes_account_id", "trading_episodes", ["account_id"])
        op.create_index("ix_trading_episodes_matched_trade_id", "trading_episodes", ["matched_trade_id"])
        op.create_index("ix_trading_episodes_symbol", "trading_episodes", ["symbol"])
        op.create_index("ix_trading_episodes_status", "trading_episodes", ["status"])
        op.create_index("ix_trading_episodes_started_at", "trading_episodes", ["started_at"])
        op.create_index("ix_trading_episodes_user_started", "trading_episodes", ["user_id", "started_at"])
        op.create_index("ix_trading_episodes_user_status", "trading_episodes", ["user_id", "status"])

    columns = {column["name"]: column for column in sa.inspect(op.get_bind()).get_columns("capture_events")}
    with op.batch_alter_table("capture_events") as batch_op:
        if "episode_id" not in columns:
            batch_op.add_column(sa.Column("episode_id", sa.Uuid(), nullable=True))
            batch_op.create_foreign_key(
                "fk_capture_events_episode_id_trading_episodes",
                "trading_episodes",
                ["episode_id"],
                ["id"],
                ondelete="CASCADE",
            )
        if "phase" not in columns:
            batch_op.add_column(sa.Column("phase", sa.String(length=30), nullable=True))
        if "recorded_live" not in columns:
            batch_op.add_column(sa.Column("recorded_live", sa.Boolean(), nullable=False, server_default=sa.true()))
        # A timeline moment may be text-only, so screenshot metadata is optional now.
        if "screenshot_storage_key" in columns and not columns["screenshot_storage_key"].get("nullable", True):
            batch_op.alter_column("screenshot_storage_key", existing_type=sa.String(length=512), nullable=True)
        if "screenshot_original_filename" in columns and not columns["screenshot_original_filename"].get("nullable", True):
            batch_op.alter_column("screenshot_original_filename", existing_type=sa.String(length=255), nullable=True)
        if "screenshot_mime" in columns and not columns["screenshot_mime"].get("nullable", True):
            batch_op.alter_column("screenshot_mime", existing_type=sa.String(length=120), nullable=True)

    indexes = _index_names("capture_events")
    if "ix_capture_events_episode_id" not in indexes:
        op.create_index("ix_capture_events_episode_id", "capture_events", ["episode_id"])
    if "ix_capture_events_phase" not in indexes:
        op.create_index("ix_capture_events_phase", "capture_events", ["phase"])


def downgrade() -> None:
    columns = {column["name"]: column for column in sa.inspect(op.get_bind()).get_columns("capture_events")}
    indexes = _index_names("capture_events")
    if "ix_capture_events_phase" in indexes:
        op.drop_index("ix_capture_events_phase", table_name="capture_events")
    if "ix_capture_events_episode_id" in indexes:
        op.drop_index("ix_capture_events_episode_id", table_name="capture_events")

    with op.batch_alter_table("capture_events") as batch_op:
        # Text-only moments cannot survive the old non-null screenshot schema. Downgrade is intentionally strict.
        if "screenshot_storage_key" in columns:
            batch_op.alter_column("screenshot_storage_key", existing_type=sa.String(length=512), nullable=False)
        if "screenshot_original_filename" in columns:
            batch_op.alter_column("screenshot_original_filename", existing_type=sa.String(length=255), nullable=False)
        if "screenshot_mime" in columns:
            batch_op.alter_column("screenshot_mime", existing_type=sa.String(length=120), nullable=False)
        if "recorded_live" in columns:
            batch_op.drop_column("recorded_live")
        if "phase" in columns:
            batch_op.drop_column("phase")
        if "episode_id" in columns:
            batch_op.drop_constraint("fk_capture_events_episode_id_trading_episodes", type_="foreignkey")
            batch_op.drop_column("episode_id")

    if "trading_episodes" in set(sa.inspect(op.get_bind()).get_table_names()):
        op.drop_table("trading_episodes")
