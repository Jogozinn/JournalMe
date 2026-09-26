"""Add Phase 2.2 prop preset catalog and ledger support.

Revision ID: 0005
Revises: 0004
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from uuid import UUID

import sqlalchemy as sa

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

UUID_TYPE = sa.Uuid()
MONEY = sa.Numeric(18, 4)

FLEX_PRESET_ID = UUID("a97ffcb5-7bf1-43a4-9c9c-8e082f274101")
FLEX_VERSION_ID = UUID("a97ffcb5-7bf1-43a4-9c9c-8e082f274102")
DAILY_EVAL_PRESET_ID = UUID("a97ffcb5-7bf1-43a4-9c9c-8e082f274201")
DAILY_EVAL_VERSION_ID = UUID("a97ffcb5-7bf1-43a4-9c9c-8e082f274202")
DAILY_FUNDED_PRESET_ID = UUID("a97ffcb5-7bf1-43a4-9c9c-8e082f274301")
DAILY_FUNDED_VERSION_ID = UUID("a97ffcb5-7bf1-43a4-9c9c-8e082f274302")
CUSTOM_PRESET_ID = UUID("a97ffcb5-7bf1-43a4-9c9c-8e082f274401")
CUSTOM_VERSION_ID = UUID("a97ffcb5-7bf1-43a4-9c9c-8e082f274402")

LFF_ACCOUNT_ID = UUID("c777b1ea-e964-4860-8df3-68f5da57d534")
LDI_ACCOUNT_ID = UUID("f1f3dd0c-4932-4da1-85a8-889a5e459dec")


def _json(value) -> str:
    return json.dumps(value, separators=(",", ":"))


def _index_names(table_name: str) -> set[str]:
    return {
        item["name"] for item in sa.inspect(op.get_bind()).get_indexes(table_name)
    }


def _create_index(name: str, table: str, columns: list[str]) -> None:
    if name not in _index_names(table):
        op.create_index(name, table, columns)


def _drop_index(name: str, table: str) -> None:
    if name in _index_names(table):
        op.drop_index(name, table_name=table)


def _create_table(name: str, *columns, **kwargs) -> None:
    if not sa.inspect(op.get_bind()).has_table(name):
        op.create_table(name, *columns, **kwargs)


def _insert_missing(table, key: str, rows: list[dict]) -> None:
    connection = op.get_bind()
    existing = set(connection.execute(sa.select(table.c[key])).scalars())
    missing = [row for row in rows if row[key] not in existing]
    if missing:
        op.bulk_insert(table, missing)


def _drop_empty_interrupted_batch_table(name: str) -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(name):
        return
    row_count = op.get_bind().execute(
        sa.text(f'SELECT COUNT(*) FROM "{name}"')
    ).scalar_one()
    if row_count:
        raise RuntimeError(
            f"Interrupted Alembic table {name} contains data; refusing to drop it."
        )
    op.drop_table(name)


def upgrade() -> None:
    for interrupted_table in (
        "_alembic_tmp_prop_rule_profiles",
        "_alembic_tmp_prop_rule_profile_versions",
        "_alembic_tmp_manual_adjustments",
    ):
        _drop_empty_interrupted_batch_table(interrupted_table)

    _create_table(
        "prop_presets",
        sa.Column("id", UUID_TYPE, primary_key=True),
        sa.Column("preset_key", sa.String(80), nullable=False),
        sa.Column("provider", sa.String(80), nullable=False),
        sa.Column("plan_family", sa.String(80), nullable=False),
        sa.Column("account_phase", sa.String(40), nullable=False),
        sa.Column("account_size", MONEY, nullable=True),
        sa.Column("display_name", sa.String(160), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("preset_key", name="uq_prop_preset_key"),
    )
    _create_index("ix_prop_presets_preset_key", "prop_presets", ["preset_key"])
    _create_table(
        "prop_preset_versions",
        sa.Column("id", UUID_TYPE, primary_key=True),
        sa.Column(
            "preset_id",
            UUID_TYPE,
            sa.ForeignKey("prop_presets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("effective_date", sa.Date(), nullable=False),
        sa.Column("source_note", sa.String(1000), nullable=True),
        sa.Column("required_fields_json", sa.JSON(), nullable=False),
        sa.Column("optional_fields_json", sa.JSON(), nullable=False),
        sa.Column("rules_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "preset_id", "version_number", name="uq_prop_preset_version"
        ),
    )
    _create_index(
        "ix_prop_preset_versions_preset_id",
        "prop_preset_versions",
        ["preset_id"],
    )
    _create_table(
        "prop_preset_scaling_tiers",
        sa.Column("id", UUID_TYPE, primary_key=True),
        sa.Column(
            "preset_version_id",
            UUID_TYPE,
            sa.ForeignKey("prop_preset_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("lower_profit_bound", MONEY, nullable=False),
        sa.Column("upper_profit_bound", MONEY, nullable=True),
        sa.Column("max_mini_contracts", sa.Integer(), nullable=False),
        sa.Column("max_micro_contracts", sa.Integer(), nullable=False),
    )
    _create_index(
        "ix_prop_preset_scaling_tiers_preset_version_id",
        "prop_preset_scaling_tiers",
        ["preset_version_id"],
    )

    profile_columns = (
        sa.Column("preset_version_id", UUID_TYPE, nullable=True),
        sa.Column(
            "configuration_state",
            sa.String(30),
            nullable=False,
            server_default="configured",
        ),
        sa.Column("evaluation_drawdown_choice", sa.String(40), nullable=True),
        sa.Column("daily_loss_limit_enabled", sa.Boolean(), nullable=True),
        sa.Column("daily_loss_limit_amount", MONEY, nullable=True),
        sa.Column("initial_trail_balance", MONEY, nullable=True),
        sa.Column("locked_mll_balance", MONEY, nullable=True),
        sa.Column("payout_buffer_balance_threshold", MONEY, nullable=True),
        sa.Column("max_daily_simulated_profit", MONEY, nullable=True),
        sa.Column("news_restriction_note", sa.String(1000), nullable=True),
        sa.Column("live_transition_note", sa.String(1000), nullable=True),
        sa.Column(
            "purchase_configuration_json",
            sa.JSON(),
            nullable=False,
            server_default="{}",
        ),
    )
    with op.batch_alter_table("prop_rule_profiles") as batch:
        for column in profile_columns:
            batch.add_column(column)
        batch.create_foreign_key(
            "fk_prop_profile_preset_version",
            "prop_preset_versions",
            ["preset_version_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_index(
            "ix_prop_rule_profiles_preset_version_id", ["preset_version_id"]
        )

    with op.batch_alter_table("prop_rule_profile_versions") as batch:
        batch.add_column(sa.Column("preset_version_id", UUID_TYPE, nullable=True))
        batch.add_column(
            sa.Column(
                "purchase_configuration_json",
                sa.JSON(),
                nullable=False,
                server_default="{}",
            )
        )
        batch.create_foreign_key(
            "fk_prop_profile_version_preset_version",
            "prop_preset_versions",
            ["preset_version_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_index(
            "ix_prop_rule_profile_versions_preset_version_id",
            ["preset_version_id"],
        )

    with op.batch_alter_table("manual_adjustments") as batch:
        batch.add_column(
            sa.Column(
                "status",
                sa.String(30),
                nullable=False,
                server_default="approved",
            )
        )
        batch.add_column(
            sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch.create_index("ix_manual_adjustments_status", ["status"])

    _create_index(
        "ix_trade_account_exit", "trades", ["account_id", "exit_timestamp"]
    )
    _create_index(
        "ix_fill_account_timestamp", "fills", ["account_id", "timestamp"]
    )
    _create_index(
        "ix_order_account_fill", "orders", ["account_id", "fill_timestamp"]
    )
    _create_index(
        "ix_cash_account_timestamp",
        "cash_transactions",
        ["account_id", "timestamp"],
    )
    _create_index(
        "ix_daily_balance_account_date",
        "daily_balances",
        ["account_id", "trade_date"],
    )
    _create_index(
        "ix_manual_adjustment_account_effective",
        "manual_adjustments",
        ["account_id", "effective_at"],
    )
    _create_index(
        "ix_payout_account_status_date",
        "prop_payout_records",
        ["account_id", "status", "approved_date"],
    )

    presets = sa.table(
        "prop_presets",
        sa.column("id", UUID_TYPE),
        sa.column("preset_key", sa.String),
        sa.column("provider", sa.String),
        sa.column("plan_family", sa.String),
        sa.column("account_phase", sa.String),
        sa.column("account_size", MONEY),
        sa.column("display_name", sa.String),
        sa.column("active", sa.Boolean),
        sa.column("created_at", sa.DateTime),
    )
    versions = sa.table(
        "prop_preset_versions",
        sa.column("id", UUID_TYPE),
        sa.column("preset_id", UUID_TYPE),
        sa.column("version_number", sa.Integer),
        sa.column("effective_date", sa.Date),
        sa.column("source_note", sa.String),
        sa.column("required_fields_json", sa.JSON),
        sa.column("optional_fields_json", sa.JSON),
        sa.column("rules_json", sa.JSON),
        sa.column("created_at", sa.DateTime),
    )
    tiers = sa.table(
        "prop_preset_scaling_tiers",
        sa.column("id", UUID_TYPE),
        sa.column("preset_version_id", UUID_TYPE),
        sa.column("lower_profit_bound", MONEY),
        sa.column("upper_profit_bound", MONEY),
        sa.column("max_mini_contracts", sa.Integer),
        sa.column("max_micro_contracts", sa.Integer),
    )
    now = datetime.now(timezone.utc)
    _insert_missing(
        presets,
        "preset_key",
        [
            {
                "id": FLEX_PRESET_ID,
                "preset_key": "lucidflex-funded-50k",
                "provider": "Lucid Trading",
                "plan_family": "LucidFlex",
                "account_phase": "Funded",
                "account_size": 50000,
                "display_name": "LucidFlex Funded 50K",
                "active": True,
                "created_at": now,
            },
            {
                "id": DAILY_EVAL_PRESET_ID,
                "preset_key": "lucid_daily_eval_50k",
                "provider": "Lucid Trading",
                "plan_family": "LucidDaily",
                "account_phase": "Evaluation",
                "account_size": 50000,
                "display_name": "LucidDaily Evaluation 50K",
                "active": True,
                "created_at": now,
            },
            {
                "id": DAILY_FUNDED_PRESET_ID,
                "preset_key": "lucid_daily_funded_50k",
                "provider": "Lucid Trading",
                "plan_family": "LucidDaily",
                "account_phase": "Funded",
                "account_size": 50000,
                "display_name": "LucidDaily Funded 50K",
                "active": True,
                "created_at": now,
            },
            {
                "id": CUSTOM_PRESET_ID,
                "preset_key": "custom",
                "provider": "Custom",
                "plan_family": "Custom",
                "account_phase": "Custom",
                "account_size": None,
                "display_name": "Custom",
                "active": True,
                "created_at": now,
            },
        ],
    )
    flex_rules = {
        "starting_balance": "50000",
        "profit_target": None,
        "max_loss": "2000",
        "daily_loss_limit": None,
        "consistency_percent": None,
        "drawdown_type": "end_of_day_trailing",
        "drawdown_amount": "2000",
        "initial_trail_balance": "52100",
        "locked_mll_balance": "50100",
        "payout_buffer": None,
        "qualifying_profit_days_required": 5,
        "minimum_profit_per_qualifying_day": "150",
        "payout_cycle_net_profit_required": True,
        "minimum_payout": "500",
        "payout_profit_percentage": "50",
        "maximum_payout": "2000",
        "maximum_payout_count": 5,
        "profit_split_trader_percent": "90",
        "profit_split_firm_percent": "10",
        "no_fixed_payout_window": True,
    }
    eval_rules = {
        "starting_balance": "50000",
        "profit_target": "3000",
        "max_loss": "2000",
        "consistency_percent": "50",
        "maximum_contracts": {"minis": 4, "micros": 40},
        "minimum_trading_days": None,
    }
    funded_rules = {
        "starting_balance": "50000",
        "profit_target": None,
        "max_loss": "2000",
        "consistency_percent": None,
        "drawdown_type": "intraday_trailing",
        "drawdown_amount": "2000",
        "initial_trail_balance": "52100",
        "locked_mll_balance": "50100",
        "payout_buffer_balance_threshold": "52100",
        "minimum_payout": "500",
        "payout_cycle_net_profit_required": True,
        "profit_split_trader_percent": "90",
        "profit_split_firm_percent": "10",
        "max_daily_simulated_profit": "8000",
        "no_fixed_payout_window": True,
    }
    source = (
        "User-configured preset. Verify every value against the current "
        "Lucid Trading firm agreement."
    )
    _insert_missing(
        versions,
        "id",
        [
            {
                "id": FLEX_VERSION_ID,
                "preset_id": FLEX_PRESET_ID,
                "version_number": 1,
                "effective_date": date(2026, 7, 30),
                "source_note": source,
                "required_fields_json": [],
                "optional_fields_json": [],
                "rules_json": flex_rules,
                "created_at": now,
            },
            {
                "id": DAILY_EVAL_VERSION_ID,
                "preset_id": DAILY_EVAL_PRESET_ID,
                "version_number": 1,
                "effective_date": date(2026, 7, 30),
                "source_note": source,
                "required_fields_json": [
                    "evaluation_drawdown_choice",
                    "daily_loss_limit_enabled",
                ],
                "optional_fields_json": [],
                "rules_json": eval_rules,
                "created_at": now,
            },
            {
                "id": DAILY_FUNDED_VERSION_ID,
                "preset_id": DAILY_FUNDED_PRESET_ID,
                "version_number": 1,
                "effective_date": date(2026, 7, 30),
                "source_note": source,
                "required_fields_json": ["daily_loss_limit_enabled"],
                "optional_fields_json": ["inherited_profile_version_id"],
                "rules_json": funded_rules,
                "created_at": now,
            },
            {
                "id": CUSTOM_VERSION_ID,
                "preset_id": CUSTOM_PRESET_ID,
                "version_number": 1,
                "effective_date": date(2026, 7, 30),
                "source_note": "Custom user-authored profile.",
                "required_fields_json": [],
                "optional_fields_json": [],
                "rules_json": {},
                "created_at": now,
            },
        ],
    )
    tier_rows = []
    for index, (lower, upper, minis, micros) in enumerate(
        [(0, 999.99, 2, 20), (1000, 1999.99, 3, 30), (2000, 2999.99, 4, 40)]
    ):
        tier_rows.append(
            {
                "id": UUID(f"a97ffcb5-7bf1-43a4-9c9c-8e082f27411{index}"),
                "preset_version_id": FLEX_VERSION_ID,
                "lower_profit_bound": lower,
                "upper_profit_bound": upper,
                "max_mini_contracts": minis,
                "max_micro_contracts": micros,
            }
        )
    tier_rows.extend(
        [
            {
                "id": UUID("a97ffcb5-7bf1-43a4-9c9c-8e082f274210"),
                "preset_version_id": DAILY_EVAL_VERSION_ID,
                "lower_profit_bound": 0,
                "upper_profit_bound": None,
                "max_mini_contracts": 4,
                "max_micro_contracts": 40,
            },
            {
                "id": UUID("a97ffcb5-7bf1-43a4-9c9c-8e082f274310"),
                "preset_version_id": DAILY_FUNDED_VERSION_ID,
                "lower_profit_bound": 0,
                "upper_profit_bound": None,
                "max_mini_contracts": 4,
                "max_micro_contracts": 40,
            },
        ]
    )
    _insert_missing(tiers, "id", tier_rows)

    connection = op.get_bind()
    connection.execute(
        sa.text(
            """
            UPDATE trading_accounts
            SET name = 'Lucid Flex 50K #1'
            WHERE id = :account_id
              AND external_account_id = 'LFF05085094850001'
            """
        ),
        {"account_id": LFF_ACCOUNT_ID.hex},
    )
    connection.execute(
        sa.text(
            """
            UPDATE prop_rule_profiles
            SET preset_version_id = :preset_version_id,
                configuration_state = 'configured',
                enabled = 1,
                initial_trail_balance = 52100,
                locked_mll_balance = 50100,
                daily_loss_limit_enabled = 0,
                daily_loss_limit_amount = NULL,
                purchase_configuration_json = :configuration
            WHERE account_id = :account_id
            """
        ),
        {
            "preset_version_id": FLEX_VERSION_ID.hex,
            "account_id": LFF_ACCOUNT_ID.hex,
            "configuration": _json(
                {
                    "provider": "Lucid Trading",
                    "plan_family": "LucidFlex",
                    "phase": "Funded",
                    "account_size": "50000",
                }
            ),
        },
    )
    connection.execute(
        sa.text(
            """
            UPDATE prop_rule_profiles
            SET enabled = 0,
                configuration_state = 'required',
                preset_version_id = NULL
            WHERE account_id = :account_id
              AND preset_key = 'lucidflex-funded-50k'
            """
        ),
        {"account_id": LDI_ACCOUNT_ID.hex},
    )


def downgrade() -> None:
    connection = op.get_bind()
    connection.execute(
        sa.text(
            """
            UPDATE trading_accounts
            SET name = 'Fiorst'
            WHERE id = :account_id
              AND external_account_id = 'LFF05085094850001'
              AND name = 'Lucid Flex 50K #1'
            """
        ),
        {"account_id": LFF_ACCOUNT_ID.hex},
    )
    connection.execute(
        sa.text(
            """
            UPDATE prop_rule_profiles
            SET enabled = 1
            WHERE account_id = :account_id
              AND preset_key = 'lucidflex-funded-50k'
            """
        ),
        {"account_id": LDI_ACCOUNT_ID.hex},
    )

    _drop_index(
        "ix_payout_account_status_date",
        "prop_payout_records",
    )
    _drop_index(
        "ix_manual_adjustment_account_effective",
        "manual_adjustments",
    )
    _drop_index(
        "ix_daily_balance_account_date",
        "daily_balances",
    )
    _drop_index("ix_cash_account_timestamp", "cash_transactions")
    _drop_index("ix_order_account_fill", "orders")
    _drop_index("ix_fill_account_timestamp", "fills")
    _drop_index("ix_trade_account_exit", "trades")

    with op.batch_alter_table("manual_adjustments") as batch:
        batch.drop_index("ix_manual_adjustments_status")
        batch.drop_column("approved_at")
        batch.drop_column("status")
    with op.batch_alter_table("prop_rule_profile_versions") as batch:
        batch.drop_index("ix_prop_rule_profile_versions_preset_version_id")
        batch.drop_constraint(
            "fk_prop_profile_version_preset_version", type_="foreignkey"
        )
        batch.drop_column("purchase_configuration_json")
        batch.drop_column("preset_version_id")
    with op.batch_alter_table("prop_rule_profiles") as batch:
        batch.drop_index("ix_prop_rule_profiles_preset_version_id")
        batch.drop_constraint("fk_prop_profile_preset_version", type_="foreignkey")
        for column in (
            "purchase_configuration_json",
            "live_transition_note",
            "news_restriction_note",
            "max_daily_simulated_profit",
            "payout_buffer_balance_threshold",
            "locked_mll_balance",
            "initial_trail_balance",
            "daily_loss_limit_amount",
            "daily_loss_limit_enabled",
            "evaluation_drawdown_choice",
            "configuration_state",
            "preset_version_id",
        ):
            batch.drop_column(column)

    op.drop_index(
        "ix_prop_preset_scaling_tiers_preset_version_id",
        table_name="prop_preset_scaling_tiers",
    )
    op.drop_table("prop_preset_scaling_tiers")
    op.drop_index(
        "ix_prop_preset_versions_preset_id",
        table_name="prop_preset_versions",
    )
    op.drop_table("prop_preset_versions")
    op.drop_index("ix_prop_presets_preset_key", table_name="prop_presets")
    op.drop_table("prop_presets")
