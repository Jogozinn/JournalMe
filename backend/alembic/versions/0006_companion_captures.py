"""Add JournalMe Companion capture events.

Revision ID: 0006
Revises: 0005
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "capture_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("event_type", sa.String(20), nullable=False),
        sa.Column("symbol", sa.String(80), nullable=True),
        sa.Column("side", sa.String(10), nullable=True),
        sa.Column("note", sa.String(1000), nullable=True),
        sa.Column("setup_tags_json", sa.JSON(), nullable=False),
        sa.Column("execution_tags_json", sa.JSON(), nullable=False),
        sa.Column("emotion_tags_json", sa.JSON(), nullable=False),
        sa.Column("platform", sa.String(80), nullable=True),
        sa.Column("page_url", sa.String(2048), nullable=True),
        sa.Column("page_title", sa.String(500), nullable=True),
        sa.Column("source", sa.String(80), nullable=False),
        sa.Column("screenshot_storage_key", sa.String(512), nullable=False),
        sa.Column("screenshot_original_filename", sa.String(255), nullable=False),
        sa.Column("screenshot_mime", sa.String(120), nullable=False),
        sa.Column("match_status", sa.String(30), nullable=False),
        sa.Column("matched_trade_id", sa.Uuid(), nullable=True),
        sa.Column("match_score", sa.Numeric(8, 6), nullable=True),
        sa.Column("matched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("match_method", sa.String(80), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["account_id"], ["trading_accounts.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["matched_trade_id"], ["trades.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_capture_events_user_id", "capture_events", ["user_id"])
    op.create_index("ix_capture_events_account_id", "capture_events", ["account_id"])
    op.create_index("ix_capture_events_captured_at", "capture_events", ["captured_at"])
    op.create_index("ix_capture_events_event_type", "capture_events", ["event_type"])
    op.create_index("ix_capture_events_symbol", "capture_events", ["symbol"])
    op.create_index("ix_capture_events_match_status", "capture_events", ["match_status"])
    op.create_index("ix_capture_events_matched_trade_id", "capture_events", ["matched_trade_id"])
    op.create_index(
        "ix_capture_events_user_captured", "capture_events", ["user_id", "captured_at"]
    )
    op.create_index(
        "ix_capture_events_user_match", "capture_events", ["user_id", "match_status"]
    )


def downgrade() -> None:
    op.drop_index("ix_capture_events_user_match", table_name="capture_events")
    op.drop_index("ix_capture_events_user_captured", table_name="capture_events")
    op.drop_index("ix_capture_events_matched_trade_id", table_name="capture_events")
    op.drop_index("ix_capture_events_match_status", table_name="capture_events")
    op.drop_index("ix_capture_events_symbol", table_name="capture_events")
    op.drop_index("ix_capture_events_event_type", table_name="capture_events")
    op.drop_index("ix_capture_events_captured_at", table_name="capture_events")
    op.drop_index("ix_capture_events_account_id", table_name="capture_events")
    op.drop_index("ix_capture_events_user_id", table_name="capture_events")
    op.drop_table("capture_events")
