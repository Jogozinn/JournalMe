"""Add LucidFlex Evaluation 50K to the preset catalog.

Revision ID: 0010
Revises: 0009
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import UUID

import sqlalchemy as sa

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

UUID_TYPE = sa.Uuid()
MONEY = sa.Numeric(18, 4)

PRESET_ID = UUID("a97ffcb5-7bf1-43a4-9c9c-8e082f274501")
VERSION_ID = UUID("a97ffcb5-7bf1-43a4-9c9c-8e082f274502")
TIER_ID = UUID("a97ffcb5-7bf1-43a4-9c9c-8e082f274510")
PRESET_KEY = "lucidflex-eval-50k"


def upgrade() -> None:
    bind = op.get_bind()
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
        sa.column("created_at", sa.DateTime(timezone=True)),
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
        sa.column("created_at", sa.DateTime(timezone=True)),
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

    preset_id = bind.execute(
        sa.select(presets.c.id).where(presets.c.preset_key == PRESET_KEY)
    ).scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if preset_id is None:
        op.bulk_insert(
            presets,
            [
                {
                    "id": PRESET_ID,
                    "preset_key": PRESET_KEY,
                    "provider": "Lucid Trading",
                    "plan_family": "LucidFlex",
                    "account_phase": "Evaluation",
                    "account_size": 50000,
                    "display_name": "LucidFlex Evaluation 50K",
                    "active": True,
                    "created_at": now,
                }
            ],
        )
        preset_id = PRESET_ID

    version_id = bind.execute(
        sa.select(versions.c.id).where(
            versions.c.preset_id == preset_id,
            versions.c.version_number == 1,
        )
    ).scalar_one_or_none()
    if version_id is None:
        op.bulk_insert(
            versions,
            [
                {
                    "id": VERSION_ID,
                    "preset_id": preset_id,
                    "version_number": 1,
                    "effective_date": date(2026, 9, 25),
                    "source_note": (
                        "User-configured LucidFlex Evaluation 50K preset. "
                        "Verify every value against the current Lucid Trading agreement."
                    ),
                    "required_fields_json": [],
                    "optional_fields_json": [],
                    "rules_json": {
                        "starting_balance": "50000",
                        "profit_target": "3000",
                        "max_loss": "2000",
                        "daily_loss_limit": None,
                        "consistency_percent": "50",
                        "drawdown_type": "end_of_day_trailing",
                        "drawdown_amount": "2000",
                        "initial_trail_balance": "52100",
                        "locked_mll_balance": "50100",
                        "maximum_contracts": {"minis": 4, "micros": 40},
                        "minimum_trading_days": None,
                    },
                    "created_at": now,
                }
            ],
        )
        version_id = VERSION_ID

    existing_tier = bind.execute(
        sa.select(tiers.c.id).where(tiers.c.preset_version_id == version_id)
    ).scalar_one_or_none()
    if existing_tier is None:
        op.bulk_insert(
            tiers,
            [
                {
                    "id": TIER_ID,
                    "preset_version_id": version_id,
                    "lower_profit_bound": 0,
                    "upper_profit_bound": None,
                    "max_mini_contracts": 4,
                    "max_micro_contracts": 40,
                }
            ],
        )


def downgrade() -> None:
    bind = op.get_bind()
    preset_id = bind.execute(
        sa.text("SELECT id FROM prop_presets WHERE preset_key = :preset_key"),
        {"preset_key": PRESET_KEY},
    ).scalar_one_or_none()
    if preset_id is None:
        return
    version_ids = list(
        bind.execute(
            sa.text("SELECT id FROM prop_preset_versions WHERE preset_id = :preset_id"),
            {"preset_id": preset_id},
        ).scalars()
    )
    for version_id in version_ids:
        bind.execute(
            sa.text(
                "DELETE FROM prop_preset_scaling_tiers "
                "WHERE preset_version_id = :version_id"
            ),
            {"version_id": version_id},
        )
    bind.execute(
        sa.text("DELETE FROM prop_preset_versions WHERE preset_id = :preset_id"),
        {"preset_id": preset_id},
    )
    bind.execute(
        sa.text("DELETE FROM prop_presets WHERE id = :preset_id"),
        {"preset_id": preset_id},
    )
