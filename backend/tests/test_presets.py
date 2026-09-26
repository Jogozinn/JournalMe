from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.database import Base
from app.domain import TradeSide
from app.models import (
    PropPayoutCycle,
    PropPreset,
    PropPresetScalingTier,
    PropPresetVersion,
    PropRuleProfile,
    PropRuleProfileVersion,
    Trade,
    TradingAccount,
    User,
)
from app.schemas import PropPresetApply
from app.services.balance import resolve_account_balance
from app.services.presets import PresetConfigurationError, apply_preset
from app.services.prop_rules import calculate_prop_status


def _catalog(
    db: Session,
    key: str,
    family: str,
    phase: str,
    rules: dict,
    required: list[str],
) -> None:
    preset = PropPreset(
        preset_key=key,
        provider="Lucid Trading",
        plan_family=family,
        account_phase=phase,
        account_size=Decimal("50000"),
        display_name=f"{family} {phase} 50K",
    )
    version = PropPresetVersion(
        version_number=1,
        effective_date=date(2026, 7, 30),
        source_note="Verify against the agreement.",
        required_fields_json=required,
        optional_fields_json=[],
        rules_json=rules,
    )
    version.scaling_tiers = [
        PropPresetScalingTier(
            lower_profit_bound=Decimal("0"),
            upper_profit_bound=None,
            max_mini_contracts=4,
            max_micro_contracts=40,
        )
    ]
    preset.versions = [version]
    db.add(preset)


def _session() -> tuple[Session, TradingAccount]:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    user = User(email=f"{uuid4()}@journalme.local", display_name="Preset")
    db.add(user)
    db.flush()
    account = TradingAccount(
        user_id=user.id,
        name="Lucid",
        starting_balance=Decimal("50000"),
    )
    db.add(account)
    _catalog(
        db,
        "lucid_daily_eval_50k",
        "LucidDaily",
        "Evaluation",
        {
            "starting_balance": "50000",
            "profit_target": "3000",
            "max_loss": "2000",
            "consistency_percent": "50",
        },
        ["evaluation_drawdown_choice", "daily_loss_limit_enabled"],
    )
    _catalog(
        db,
        "lucid_daily_funded_50k",
        "LucidDaily",
        "Funded",
        {
            "starting_balance": "50000",
            "max_loss": "2000",
            "consistency_percent": None,
        },
        ["daily_loss_limit_enabled"],
    )
    _catalog(
        db,
        "lucidflex-eval-50k",
        "LucidFlex",
        "Evaluation",
        {
            "starting_balance": "50000",
            "profit_target": "3000",
            "max_loss": "2000",
            "consistency_percent": "50",
            "drawdown_type": "end_of_day_trailing",
            "drawdown_amount": "2000",
            "initial_trail_balance": "52100",
            "locked_mll_balance": "50100",
        },
        [],
    )
    _catalog(
        db,
        "lucidflex-funded-50k",
        "LucidFlex",
        "Funded",
        {"starting_balance": "50000", "max_loss": "2000"},
        [],
    )
    db.flush()
    return db, account


def test_lucidflex_evaluation_copies_evaluation_rules() -> None:
    db, account = _session()
    profile, version, created = apply_preset(
        db, account, PropPresetApply(preset_key="lucidflex-eval-50k")
    )

    assert created is True
    assert profile.profile_account_type == "LucidFlex Evaluation"
    assert profile.starting_balance == Decimal("50000")
    assert profile.profit_target == Decimal("3000")
    assert profile.max_loss == Decimal("2000")
    assert profile.consistency_percent == Decimal("50")
    assert profile.drawdown_type == "end_of_day_trailing"
    assert profile.drawdown_amount == Decimal("2000")
    assert profile.daily_loss_limit is None
    assert profile.initial_trail_balance == Decimal("52100")
    assert profile.locked_mll_balance == Decimal("50100")
    assert profile.minimum_payout is None
    assert version.scaling_tiers[0].max_mini_contracts == 4
    assert version.scaling_tiers[0].max_micro_contracts == 40
    db.close()


def test_lucid_daily_evaluation_requires_both_purchase_choices() -> None:
    db, account = _session()
    with pytest.raises(
        PresetConfigurationError, match="Evaluation drawdown choice"
    ):
        apply_preset(
            db,
            account,
            PropPresetApply(preset_key="lucid_daily_eval_50k"),
        )
    with pytest.raises(PresetConfigurationError, match="Daily Loss Limit"):
        apply_preset(
            db,
            account,
            PropPresetApply(
                preset_key="lucid_daily_eval_50k",
                evaluation_drawdown_choice="end_of_day_trailing",
            ),
        )
    db.close()


@pytest.mark.parametrize(
    ("enabled", "expected_limit"), [(True, Decimal("1200")), (False, None)]
)
def test_lucid_daily_evaluation_copies_exact_rules(
    enabled: bool, expected_limit: Decimal | None
) -> None:
    db, account = _session()
    profile, version, created = apply_preset(
        db,
        account,
        PropPresetApply(
            preset_key="lucid_daily_eval_50k",
            evaluation_drawdown_choice="intraday_trailing",
            daily_loss_limit_enabled=enabled,
        ),
    )

    assert created is True
    assert profile.profit_target == Decimal("3000")
    assert profile.max_loss == Decimal("2000")
    assert profile.consistency_percent == Decimal("50")
    assert profile.daily_loss_limit == expected_limit
    assert profile.evaluation_drawdown_choice == "intraday_trailing"
    assert version.scaling_tiers[0].max_mini_contracts == 4
    assert version.scaling_tiers[0].max_micro_contracts == 40
    db.close()


def test_funded_conversion_inherits_dll_and_preserves_evaluation_version() -> None:
    db, account = _session()
    profile, evaluation_version, _ = apply_preset(
        db,
        account,
        PropPresetApply(
            preset_key="lucid_daily_eval_50k",
            evaluation_drawdown_choice="end_of_day_trailing",
            daily_loss_limit_enabled=False,
        ),
    )
    funded_profile, funded_version, _ = apply_preset(
        db,
        account,
        PropPresetApply(
            preset_key="lucid_daily_funded_50k",
            confirm_replace=True,
        ),
    )

    assert funded_profile.id == profile.id
    assert funded_profile.drawdown_type == "intraday_trailing"
    assert funded_profile.consistency_percent is None
    assert funded_profile.daily_loss_limit_enabled is False
    assert funded_profile.payout_buffer_balance_threshold == Decimal("52100")
    assert funded_profile.minimum_payout == Decimal("500")
    assert funded_profile.max_daily_simulated_profit == Decimal("8000")
    assert funded_version.purchase_configuration_json[
        "inherited_profile_version_id"
    ] == str(evaluation_version.id)
    assert db.get(PropRuleProfileVersion, evaluation_version.id) is not None
    db.close()


def test_mistaken_historical_profile_is_preserved_when_configured() -> None:
    db, account = _session()
    profile = PropRuleProfile(
        account_id=account.id,
        firm_name="Lucid Trading",
        max_loss=Decimal("2000"),
        preset_key="lucidflex-funded-50k",
        configuration_state="required",
        enabled=False,
    )
    db.add(profile)
    db.flush()
    historical = PropRuleProfileVersion(
        profile_id=profile.id,
        version_number=1,
        effective_date=date(2026, 7, 29),
        rules_json={"preset_key": "lucidflex-funded-50k"},
        purchase_configuration_json={},
    )
    db.add(historical)
    db.flush()

    configured, version, _ = apply_preset(
        db,
        account,
        PropPresetApply(
            preset_key="lucid_daily_eval_50k",
            evaluation_drawdown_choice="end_of_day_trailing",
            daily_loss_limit_enabled=True,
        ),
    )

    assert configured.id == profile.id
    assert configured.preset_key == "lucid_daily_eval_50k"
    assert configured.enabled is True
    assert version.version_number == 2
    assert db.get(PropRuleProfileVersion, historical.id).rules_json[
        "preset_key"
    ] == "lucidflex-funded-50k"
    db.close()


def test_lucid_daily_funded_payout_is_profit_above_balance_threshold() -> None:
    db, account = _session()
    profile, version, _ = apply_preset(
        db,
        account,
        PropPresetApply(
            preset_key="lucid_daily_funded_50k",
            daily_loss_limit_enabled=False,
            effective_date=date(2026, 7, 30),
        ),
    )
    trade = Trade(
        account_id=account.id,
        duplicate_fingerprint=str(uuid4()),
        symbol="MESU6",
        contract_quantity=Decimal("1"),
        side=TradeSide.LONG,
        entry_price=Decimal("5000"),
        exit_price=Decimal("5001"),
        gross_pnl=Decimal("3000"),
        fees=Decimal("0"),
        net_pnl=Decimal("3000"),
        entry_timestamp=datetime(2026, 7, 30, 14, tzinfo=timezone.utc),
        exit_timestamp=datetime(2026, 7, 30, 15, tzinfo=timezone.utc),
    )
    db.add(trade)
    db.flush()
    cycle = db.scalar(
        select(PropPayoutCycle).where(PropPayoutCycle.account_id == account.id)
    )
    result = calculate_prop_status(
        account,
        profile,
        [trade],
        [],
        cycle=cycle,
        version=version,
        balance_resolution=resolve_account_balance(db, account),
    )

    assert result["status"]["current_balance"] == "53000.00"
    assert result["payout_cycle"]["profit_above_buffer"] == "900.00"
    assert result["payout_cycle"]["gross_available_payout"] == "900.00"
    assert result["payout_cycle"]["estimated_trader_share"] == "810.00"
    assert result["payout_cycle"]["estimated_firm_share"] == "90.00"
    assert result["payout_cycle"]["eligible_for_payout"] is True
    db.close()
