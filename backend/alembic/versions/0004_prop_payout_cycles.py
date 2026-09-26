"""Add nullable, versioned prop rules and payout cycles.

Revision ID: 0004
Revises: 0003
"""

import sqlalchemy as sa

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

UUID = sa.Uuid()
MONEY = sa.Numeric(18, 4)
PERCENT = sa.Numeric(7, 4)


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
    profit_target = next(
        item
        for item in sa.inspect(op.get_bind()).get_columns("prop_rule_profiles")
        if item["name"] == "profit_target"
    )
    if not profit_target["nullable"]:
        with op.batch_alter_table("prop_rule_profiles") as batch:
            batch.alter_column(
                "profit_target",
                existing_type=MONEY,
                nullable=True,
            )

    for column in (
        sa.Column("qualifying_profit_days_required", sa.Integer(), nullable=True),
        sa.Column("minimum_profit_per_qualifying_day", MONEY, nullable=True),
        sa.Column(
            "payout_cycle_net_profit_required",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column("minimum_payout", MONEY, nullable=True),
        sa.Column("payout_profit_percentage", PERCENT, nullable=True),
        sa.Column("maximum_payout", MONEY, nullable=True),
        sa.Column("maximum_payout_count", sa.Integer(), nullable=True),
        sa.Column("profit_split_trader_percent", PERCENT, nullable=True),
        sa.Column("profit_split_firm_percent", PERCENT, nullable=True),
        sa.Column(
            "no_fixed_payout_window",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("payout_cycle_start_date", sa.Date(), nullable=True),
        sa.Column(
            "qualifying_days_since_last_payout",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "payouts_completed",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("preset_key", sa.String(80), nullable=True),
        sa.Column("effective_date", sa.Date(), nullable=True),
        sa.Column("source_note", sa.String(1000), nullable=True),
    ):
        _add_column("prop_rule_profiles", column)

    _create_table(
        "prop_rule_profile_versions",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "profile_id",
            UUID,
            sa.ForeignKey("prop_rule_profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("effective_date", sa.Date(), nullable=False),
        sa.Column("source_note", sa.String(1000), nullable=True),
        sa.Column("rules_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "profile_id",
            "version_number",
            name="uq_prop_rule_profile_version",
        ),
    )
    _create_index(
        "ix_prop_rule_profile_versions_profile_id",
        "prop_rule_profile_versions",
        ["profile_id"],
    )

    _create_table(
        "prop_scaling_tiers",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "profile_version_id",
            UUID,
            sa.ForeignKey("prop_rule_profile_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("lower_profit_bound", MONEY, nullable=False),
        sa.Column("upper_profit_bound", MONEY, nullable=True),
        sa.Column("max_mini_contracts", sa.Integer(), nullable=False),
        sa.Column("max_micro_contracts", sa.Integer(), nullable=False),
    )
    _create_index(
        "ix_prop_scaling_tiers_profile_version_id",
        "prop_scaling_tiers",
        ["profile_version_id"],
    )

    _create_table(
        "prop_payout_cycles",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "account_id",
            UUID,
            sa.ForeignKey("trading_accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "profile_version_id",
            UUID,
            sa.ForeignKey("prop_rule_profile_versions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="open"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
    )
    _create_index(
        "ix_prop_payout_cycles_account_id",
        "prop_payout_cycles",
        ["account_id"],
    )
    _create_index(
        "ix_prop_payout_cycles_profile_version_id",
        "prop_payout_cycles",
        ["profile_version_id"],
    )
    _create_index(
        "ix_prop_payout_cycles_start_date",
        "prop_payout_cycles",
        ["start_date"],
    )
    _create_index(
        "ix_prop_payout_cycles_account_status",
        "prop_payout_cycles",
        ["account_id", "status"],
    )

    _create_table(
        "prop_payout_records",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "cycle_id",
            UUID,
            sa.ForeignKey("prop_payout_cycles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "account_id",
            UUID,
            sa.ForeignKey("trading_accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("request_date", sa.Date(), nullable=False),
        sa.Column("approved_date", sa.Date(), nullable=True),
        sa.Column("requested_amount", MONEY, nullable=False),
        sa.Column("approved_gross_amount", MONEY, nullable=True),
        sa.Column("trader_amount", MONEY, nullable=True),
        sa.Column("firm_amount", MONEY, nullable=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="pending"),
        sa.Column("notes", sa.String(2000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    _create_index(
        "ix_prop_payout_records_cycle_id",
        "prop_payout_records",
        ["cycle_id"],
    )
    _create_index(
        "ix_prop_payout_records_account_id",
        "prop_payout_records",
        ["account_id"],
    )


def downgrade() -> None:
    for table in (
        "prop_payout_records",
        "prop_payout_cycles",
        "prop_scaling_tiers",
        "prop_rule_profile_versions",
    ):
        if sa.inspect(op.get_bind()).has_table(table):
            op.drop_table(table)

    for column in (
        "source_note",
        "effective_date",
        "preset_key",
        "payouts_completed",
        "qualifying_days_since_last_payout",
        "payout_cycle_start_date",
        "no_fixed_payout_window",
        "profit_split_firm_percent",
        "profit_split_trader_percent",
        "maximum_payout_count",
        "maximum_payout",
        "payout_profit_percentage",
        "minimum_payout",
        "payout_cycle_net_profit_required",
        "minimum_profit_per_qualifying_day",
        "qualifying_profit_days_required",
    ):
        if _has_column("prop_rule_profiles", column):
            op.drop_column("prop_rule_profiles", column)

    op.execute(
        sa.text(
            "UPDATE prop_rule_profiles SET profit_target = 0 "
            "WHERE profit_target IS NULL"
        )
    )
    with op.batch_alter_table("prop_rule_profiles") as batch:
        batch.alter_column(
            "profit_target",
            existing_type=MONEY,
            nullable=False,
        )
