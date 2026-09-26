"""Add the Phase 2 professional journal domain.

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

UUID = sa.Uuid()
MONEY = sa.Numeric(18, 4)


def _has_column(table_name: str, column_name: str) -> bool:
    return column_name in {
        item["name"] for item in sa.inspect(op.get_bind()).get_columns(table_name)
    }


def _add_column(table_name: str, column: sa.Column) -> None:
    if not _has_column(table_name, column.name):
        op.add_column(table_name, column)


def _create_table(table_name: str, *columns, **kwargs) -> None:
    if not sa.inspect(op.get_bind()).has_table(table_name):
        op.create_table(table_name, *columns, **kwargs)


def _create_index(index_name: str, table_name: str, columns: list[str]) -> None:
    indexes = {
        item["name"] for item in sa.inspect(op.get_bind()).get_indexes(table_name)
    }
    if index_name not in indexes:
        op.create_index(index_name, table_name, columns)


def upgrade() -> None:
    _add_column("trading_accounts", sa.Column("notes", sa.Text(), nullable=True))
    _add_column(
        "trade_journals",
        sa.Column("market_condition", sa.String(120), nullable=True),
    )
    _add_column(
        "trade_journals",
        sa.Column("session_name", sa.String(80), nullable=True),
    )
    _add_column("trade_journals", sa.Column("custom_notes", sa.Text(), nullable=True))
    _add_column(
        "trade_journals",
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
    )
    _create_index("ix_trade_journals_reviewed_at", "trade_journals", ["reviewed_at"])

    for column in (
        sa.Column("confidence_score", sa.Integer(), nullable=True),
        sa.Column("sleep_quality", sa.Integer(), nullable=True),
        sa.Column("energy_score", sa.Integer(), nullable=True),
        sa.Column("max_trades", sa.Integer(), nullable=True),
        sa.Column(
            "allowed_playbook_ids", sa.JSON(), nullable=False, server_default=sa.text("'[]'")
        ),
        sa.Column(
            "prohibited_behaviors", sa.JSON(), nullable=False, server_default=sa.text("'[]'")
        ),
        sa.Column("checklist_json", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("what_worked", sa.Text(), nullable=True),
        sa.Column("what_did_not_work", sa.Text(), nullable=True),
        sa.Column("lesson_learned", sa.Text(), nullable=True),
        sa.Column("followed_rules", sa.Boolean(), nullable=True),
        sa.Column("tomorrow_note", sa.Text(), nullable=True),
    ):
        _add_column("daily_journals", column)

    _add_column(
        "goals",
        sa.Column(
            "goal_type",
            sa.String(40),
            nullable=False,
            server_default=sa.text("'pnl_target'"),
        ),
    )
    _add_column("goals", sa.Column("target_value", MONEY, nullable=True))
    _add_column(
        "goals",
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
    )

    for column in (
        sa.Column("account_label", sa.String(160), nullable=True),
        sa.Column("profile_account_type", sa.String(80), nullable=True),
        sa.Column("starting_balance", MONEY, nullable=True),
        sa.Column("drawdown_amount", MONEY, nullable=True),
        sa.Column("drawdown_lock_behavior", sa.String(160), nullable=True),
        sa.Column("payout_buffer", MONEY, nullable=True),
        sa.Column("minimum_trading_days", sa.Integer(), nullable=True),
        sa.Column(
            "rules_enabled_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")
        ),
    ):
        _add_column("prop_rule_profiles", column)

    _create_table(
        "playbooks",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("user_id", UUID, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("market_scope", sa.String(255), nullable=True),
        sa.Column("direction_scope", sa.String(40), nullable=True),
        sa.Column("preferred_session", sa.String(80), nullable=True),
        sa.Column("minimum_confluences", sa.Integer(), nullable=True),
        sa.Column("ideal_entry_criteria", sa.Text(), nullable=True),
        sa.Column("confirmation_criteria", sa.Text(), nullable=True),
        sa.Column("invalidation_criteria", sa.Text(), nullable=True),
        sa.Column("stop_logic", sa.Text(), nullable=True),
        sa.Column("target_logic", sa.Text(), nullable=True),
        sa.Column("management_rules", sa.Text(), nullable=True),
        sa.Column("prohibited_conditions", sa.Text(), nullable=True),
        sa.Column("default_grade_expectations", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "name", name="uq_playbook_name"),
    )
    _create_index("ix_playbooks_user_id", "playbooks", ["user_id"])
    _add_column(
        "attachments",
        sa.Column(
            "playbook_id",
            UUID,
            sa.ForeignKey("playbooks.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )

    _create_table(
        "playbook_checklist_items",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "playbook_id",
            UUID,
            sa.ForeignKey("playbooks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("text", sa.String(500), nullable=False),
        sa.Column("category", sa.String(80), nullable=False, server_default="entry"),
        sa.Column("required", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
    )
    _create_index(
        "ix_playbook_checklist_items_playbook_id",
        "playbook_checklist_items",
        ["playbook_id"],
    )
    _create_table(
        "trade_playbooks",
        sa.Column(
            "trade_id", UUID, sa.ForeignKey("trades.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column(
            "playbook_id",
            UUID,
            sa.ForeignKey("playbooks.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=False),
    )
    _create_index("ix_trade_playbook_primary", "trade_playbooks", ["trade_id", "is_primary"])
    _create_index("ix_trade_playbooks_is_primary", "trade_playbooks", ["is_primary"])
    _create_table(
        "trade_checklist_responses",
        sa.Column(
            "trade_id", UUID, sa.ForeignKey("trades.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column(
            "checklist_item_id",
            UUID,
            sa.ForeignKey("playbook_checklist_items.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("passed", sa.Boolean(), nullable=True),
        sa.Column("note", sa.String(500), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    _create_table(
        "rule_violations",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "trade_id", UUID, sa.ForeignKey("trades.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "playbook_id", UUID, sa.ForeignKey("playbooks.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("rule_text", sa.String(500), nullable=False),
        sa.Column("severity", sa.String(30), nullable=False, server_default="medium"),
        sa.Column("estimated_cost", MONEY, nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    _create_index("ix_rule_violations_trade_id", "rule_violations", ["trade_id"])

    period_columns = [
        sa.Column("written_review", sa.Text(), nullable=True),
        sa.Column("what_worked", sa.Text(), nullable=True),
        sa.Column("what_failed", sa.Text(), nullable=True),
        sa.Column("next_period_focus", sa.Text(), nullable=True),
        sa.Column("next_period_goals", sa.Text(), nullable=True),
        sa.Column("grade", sa.String(3), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    ]
    _create_table(
        "weekly_reviews",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "account_id",
            UUID,
            sa.ForeignKey("trading_accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("week_start", sa.Date(), nullable=False),
        *period_columns,
        sa.UniqueConstraint("account_id", "week_start", name="uq_weekly_review_period"),
    )
    _create_index("ix_weekly_reviews_account_id", "weekly_reviews", ["account_id"])
    _create_table(
        "monthly_reviews",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "account_id",
            UUID,
            sa.ForeignKey("trading_accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("month_start", sa.Date(), nullable=False),
        *[
            sa.Column(column.name, column.type, nullable=column.nullable)
            for column in period_columns
        ],
        sa.UniqueConstraint("account_id", "month_start", name="uq_monthly_review_period"),
    )
    _create_index("ix_monthly_reviews_account_id", "monthly_reviews", ["account_id"])

    _create_table(
        "account_groups",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("user_id", UUID, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "name", name="uq_account_group_name"),
    )
    _create_index("ix_account_groups_user_id", "account_groups", ["user_id"])
    _create_table(
        "account_group_members",
        sa.Column(
            "group_id",
            UUID,
            sa.ForeignKey("account_groups.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "account_id",
            UUID,
            sa.ForeignKey("trading_accounts.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )
    _create_table(
        "manual_adjustments",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "account_id",
            UUID,
            sa.ForeignKey("trading_accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("adjustment_type", sa.String(40), nullable=False),
        sa.Column("amount", MONEY, nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("source", sa.String(30), nullable=False, server_default="manual"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    _create_index("ix_manual_adjustments_account_id", "manual_adjustments", ["account_id"])
    _create_index("ix_manual_adjustments_effective_at", "manual_adjustments", ["effective_at"])
    _create_table(
        "user_preferences",
        sa.Column(
            "user_id", UUID, sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column("timezone", sa.String(80), nullable=False, server_default="America/New_York"),
        sa.Column("currency", sa.String(3), nullable=False, server_default="USD"),
        sa.Column("week_start", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "default_account_id",
            UUID,
            sa.ForeignKey("trading_accounts.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("default_date_range", sa.String(40), nullable=False, server_default="this_month"),
        sa.Column("pnl_display", sa.String(20), nullable=False, server_default="net"),
        sa.Column("density", sa.String(20), nullable=False, server_default="comfortable"),
        sa.Column("reduced_motion", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "session_definitions_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")
        ),
        sa.Column(
            "review_rules_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    _create_table(
        "audit_events",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("user_id", UUID, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "account_id",
            UUID,
            sa.ForeignKey("trading_accounts.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("entity_type", sa.String(60), nullable=False),
        sa.Column("entity_id", sa.String(120), nullable=False),
        sa.Column("action", sa.String(30), nullable=False),
        sa.Column("before_json", sa.JSON(), nullable=True),
        sa.Column("after_json", sa.JSON(), nullable=True),
        sa.Column("reason", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    _create_index("ix_audit_events_user_id", "audit_events", ["user_id"])
    _create_index("ix_audit_events_account_id", "audit_events", ["account_id"])


def downgrade() -> None:
    for table in (
        "audit_events",
        "user_preferences",
        "manual_adjustments",
        "account_group_members",
        "account_groups",
        "monthly_reviews",
        "weekly_reviews",
        "rule_violations",
        "trade_checklist_responses",
        "trade_playbooks",
        "playbook_checklist_items",
    ):
        op.drop_table(table)
    op.drop_column("attachments", "playbook_id")
    op.drop_table("playbooks")

    for column in (
        "rules_enabled_json",
        "minimum_trading_days",
        "payout_buffer",
        "drawdown_lock_behavior",
        "drawdown_amount",
        "starting_balance",
        "profile_account_type",
        "account_label",
    ):
        op.drop_column("prop_rule_profiles", column)
    for column in ("archived_at", "target_value", "goal_type"):
        op.drop_column("goals", column)
    for column in (
        "tomorrow_note",
        "followed_rules",
        "lesson_learned",
        "what_did_not_work",
        "what_worked",
        "checklist_json",
        "prohibited_behaviors",
        "allowed_playbook_ids",
        "max_trades",
        "energy_score",
        "sleep_quality",
        "confidence_score",
    ):
        op.drop_column("daily_journals", column)
    op.drop_index("ix_trade_journals_reviewed_at", table_name="trade_journals")
    for column in ("reviewed_at", "custom_notes", "session_name", "market_condition"):
        op.drop_column("trade_journals", column)
    op.drop_column("trading_accounts", "notes")
