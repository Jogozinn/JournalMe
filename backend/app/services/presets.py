from __future__ import annotations

from datetime import date, timezone
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    AccountType,
    PropPreset,
    PropPresetVersion,
    PropRuleProfile,
    PropRuleProfileVersion,
    Trade,
    TradingAccount,
)
from app.schemas import PropPresetApply, PropScalingTierInput
from app.services.prop_rules import (
    create_profile_version,
    ensure_open_cycle,
    latest_profile_version,
    lucidflex_funded_50k_preset,
)


class PresetConfigurationError(ValueError):
    pass


class PresetReplacementRequired(ValueError):
    pass


def _decimal(value: Any) -> Decimal | None:
    return Decimal(str(value)) if value is not None else None


def _latest_catalog_version(
    db: Session, preset_key: str
) -> tuple[PropPreset, PropPresetVersion]:
    preset = db.scalar(
        select(PropPreset)
        .options(
            selectinload(PropPreset.versions).selectinload(
                PropPresetVersion.scaling_tiers
            )
        )
        .where(PropPreset.preset_key == preset_key, PropPreset.active.is_(True))
    )
    if preset is None or not preset.versions:
        raise PresetConfigurationError("Preset is unavailable.")
    return preset, preset.versions[-1]


def list_preset_catalog(db: Session) -> list[dict[str, Any]]:
    presets = list(
        db.scalars(
            select(PropPreset)
            .options(
                selectinload(PropPreset.versions).selectinload(
                    PropPresetVersion.scaling_tiers
                )
            )
            .where(PropPreset.active.is_(True))
            .order_by(PropPreset.display_name)
        ).all()
    )
    result = []
    for preset in presets:
        version = preset.versions[-1]
        result.append(
            {
                "preset_key": preset.preset_key,
                "provider": preset.provider,
                "plan_family": preset.plan_family,
                "account_phase": preset.account_phase,
                "account_size": (
                    str(preset.account_size) if preset.account_size is not None else None
                ),
                "display_name": preset.display_name,
                "version": version.version_number,
                "effective_date": version.effective_date.isoformat(),
                "source_note": version.source_note,
                "required_fields": version.required_fields_json,
                "optional_fields": version.optional_fields_json,
                "rules": version.rules_json,
                "scaling_tiers": [
                    {
                        "lower_profit_bound": str(item.lower_profit_bound),
                        "upper_profit_bound": (
                            str(item.upper_profit_bound)
                            if item.upper_profit_bound is not None
                            else None
                        ),
                        "max_mini_contracts": item.max_mini_contracts,
                        "max_micro_contracts": item.max_micro_contracts,
                    }
                    for item in version.scaling_tiers
                ],
            }
        )
    return result


def _purchase_configuration(
    db: Session,
    preset: PropPreset,
    payload: PropPresetApply,
) -> dict[str, Any]:
    base: dict[str, Any] = {
        "provider": preset.provider,
        "plan_family": preset.plan_family,
        "phase": preset.account_phase,
        "account_size": (
            str(preset.account_size) if preset.account_size is not None else None
        ),
    }
    if payload.preset_key == "lucid_daily_eval_50k":
        if payload.evaluation_drawdown_choice is None:
            raise PresetConfigurationError(
                "Evaluation drawdown choice is required."
            )
        if payload.daily_loss_limit_enabled is None:
            raise PresetConfigurationError(
                "Daily Loss Limit ON or OFF is required."
            )
        base.update(
            {
                "evaluation_drawdown_choice": payload.evaluation_drawdown_choice,
                "daily_loss_limit_enabled": payload.daily_loss_limit_enabled,
                "daily_loss_limit_amount": (
                    "1200" if payload.daily_loss_limit_enabled else None
                ),
            }
        )
    elif payload.preset_key == "lucid_daily_funded_50k":
        inherited = None
        if payload.inherited_profile_version_id is not None:
            inherited = db.get(
                PropRuleProfileVersion, payload.inherited_profile_version_id
            )
            inherited_config = (
                inherited.purchase_configuration_json if inherited else {}
            )
            if (
                inherited is None
                or inherited_config.get("plan_family") != "LucidDaily"
                or inherited_config.get("daily_loss_limit_enabled") is None
            ):
                raise PresetConfigurationError(
                    "The selected evaluation version has no usable LucidDaily DLL choice."
                )
            dll_enabled = bool(
                inherited_config["daily_loss_limit_enabled"]
            )
        else:
            if payload.daily_loss_limit_enabled is None:
                raise PresetConfigurationError(
                    "Daily Loss Limit ON or OFF is required for a standalone funded account."
                )
            dll_enabled = payload.daily_loss_limit_enabled
        base.update(
            {
                "daily_loss_limit_enabled": dll_enabled,
                "daily_loss_limit_amount": "1200" if dll_enabled else None,
                "inherited_profile_version_id": (
                    str(inherited.id) if inherited is not None else None
                ),
                "funded_drawdown_choice": "intraday_trailing",
            }
        )
    return base


def _rules_from_catalog(
    preset: PropPreset,
    version: PropPresetVersion,
    payload: PropPresetApply,
    purchase: dict[str, Any],
    cycle_start: date,
) -> tuple[dict[str, Any], list[PropScalingTierInput]]:
    if payload.preset_key == "lucidflex-funded-50k":
        values, _ = lucidflex_funded_50k_preset(cycle_start)
    else:
        rules = version.rules_json
        is_daily_eval = payload.preset_key == "lucid_daily_eval_50k"
        is_flex_eval = payload.preset_key == "lucidflex-eval-50k"
        is_eval = is_daily_eval or is_flex_eval
        dll_enabled = bool(purchase.get("daily_loss_limit_enabled"))
        if is_flex_eval:
            account_label = "LucidFlex Evaluation 50K"
            profile_account_type = "LucidFlex Evaluation"
        elif is_daily_eval:
            account_label = "LucidDaily Evaluation 50K"
            profile_account_type = "LucidDaily Evaluation"
        else:
            account_label = "LucidDaily Funded 50K"
            profile_account_type = "LucidDaily Funded"
        values = {
            "firm_name": preset.provider,
            "account_label": account_label,
            "profile_account_type": profile_account_type,
            "starting_balance": _decimal(rules.get("starting_balance")),
            "profit_target": _decimal(rules.get("profit_target")),
            "max_loss": _decimal(rules.get("max_loss")),
            "daily_loss_limit": Decimal("1200") if dll_enabled else None,
            "consistency_percent": _decimal(rules.get("consistency_percent")),
            "drawdown_type": (
                payload.evaluation_drawdown_choice
                if is_daily_eval
                else rules.get("drawdown_type") or "intraday_trailing"
            ),
            "drawdown_amount": _decimal(rules.get("drawdown_amount"))
            or Decimal("2000"),
            "drawdown_lock_behavior": (
                "Locks at the configured minimum-loss-limit balance."
            ),
            "payout_buffer": None,
            "minimum_trading_days": None,
            "qualifying_profit_days_required": None,
            "minimum_profit_per_qualifying_day": None,
            "payout_cycle_net_profit_required": not is_eval,
            "minimum_payout": None if is_eval else Decimal("500"),
            "payout_profit_percentage": None,
            "maximum_payout": None,
            "maximum_payout_count": None,
            "profit_split_trader_percent": None if is_eval else Decimal("90"),
            "profit_split_firm_percent": None if is_eval else Decimal("10"),
            "no_fixed_payout_window": not is_eval,
            "payout_cycle_start_date": cycle_start,
            "qualifying_days_since_last_payout": 0,
            "payouts_completed": 0,
            "preset_key": payload.preset_key,
            "effective_date": payload.effective_date,
            "source_note": version.source_note,
            "configuration_state": "configured",
            "evaluation_drawdown_choice": (
                payload.evaluation_drawdown_choice if is_daily_eval else None
            ),
            "daily_loss_limit_enabled": dll_enabled,
            "daily_loss_limit_amount": Decimal("1200") if dll_enabled else None,
            "initial_trail_balance": _decimal(rules.get("initial_trail_balance"))
            or Decimal("52100"),
            "locked_mll_balance": _decimal(rules.get("locked_mll_balance"))
            or Decimal("50100"),
            "payout_buffer_balance_threshold": (
                None if is_eval else Decimal("52100")
            ),
            "max_daily_simulated_profit": (
                None if is_eval else Decimal("8000")
            ),
            "news_restriction_note": (
                None
                if is_eval
                else (
                    "Red-folder news trading is prohibited. Remain flat from "
                    "one minute before through one minute after the event."
                )
            ),
            "live_transition_note": (
                None
                if is_eval
                else (
                    "$8,000 maximum daily simulated-profit threshold is a "
                    "firm live-review condition; JournalMe cannot transition the account."
                )
            ),
            "purchase_configuration_json": purchase,
            "rules_enabled_json": {
                "profit_target": is_eval,
                "max_loss": True,
                "daily_loss_limit": dll_enabled,
                "consistency": is_eval,
                "minimum_trading_days": False,
                "qualifying_profit_days": False,
                "payout_cycle_net_profit": not is_eval,
            },
            "enabled": True,
        }
    values["preset_version_id"] = version.id
    values["purchase_configuration_json"] = purchase
    values["effective_date"] = payload.effective_date
    tiers = [
        PropScalingTierInput(
            lower_profit_bound=item.lower_profit_bound,
            upper_profit_bound=item.upper_profit_bound,
            max_mini_contracts=item.max_mini_contracts,
            max_micro_contracts=item.max_micro_contracts,
        )
        for item in version.scaling_tiers
    ]
    return values, tiers


def apply_preset(
    db: Session,
    account: TradingAccount,
    payload: PropPresetApply,
) -> tuple[PropRuleProfile, PropRuleProfileVersion, bool]:
    if payload.preset_key == "custom":
        raise PresetConfigurationError(
            "Create the account, then use the custom rule editor."
        )
    preset, catalog_version = _latest_catalog_version(db, payload.preset_key)
    profile = db.scalar(
        select(PropRuleProfile).where(PropRuleProfile.account_id == account.id)
    )
    current_version = latest_profile_version(db, profile.id) if profile else None
    if (
        payload.preset_key == "lucid_daily_funded_50k"
        and payload.inherited_profile_version_id is None
        and profile is not None
        and profile.preset_key == "lucid_daily_eval_50k"
        and current_version is not None
    ):
        payload = payload.model_copy(
            update={
                "inherited_profile_version_id": current_version.id,
                "daily_loss_limit_enabled": None,
            }
        )
    purchase = _purchase_configuration(db, preset, payload)
    if (
        profile is not None
        and profile.enabled
        and profile.preset_key != payload.preset_key
        and not payload.confirm_replace
    ):
        raise PresetReplacementRequired(
            "Confirm replacement of the active rule profile."
        )
    latest = current_version
    if (
        profile is not None
        and profile.enabled
        and profile.configuration_state == "configured"
        and profile.preset_key == payload.preset_key
        and profile.preset_version_id == catalog_version.id
        and profile.purchase_configuration_json == purchase
        and latest is not None
        and latest.preset_version_id == catalog_version.id
        and latest.purchase_configuration_json == purchase
    ):
        return profile, latest, False

    earliest = db.scalar(
        select(func.min(Trade.entry_timestamp)).where(
            Trade.account_id == account.id
        )
    )
    if earliest is not None:
        if earliest.tzinfo is None:
            earliest = earliest.replace(tzinfo=timezone.utc)
        cycle_start = earliest.astimezone(ZoneInfo(account.timezone)).date()
    else:
        cycle_start = payload.effective_date
    values, tiers = _rules_from_catalog(
        preset, catalog_version, payload, purchase, cycle_start
    )
    if profile is None:
        profile = PropRuleProfile(account_id=account.id, **values)
        db.add(profile)
    else:
        for key, value in values.items():
            setattr(profile, key, value)
    account.starting_balance = values["starting_balance"]
    account.account_type = (
        AccountType.EVALUATION
        if preset.account_phase.lower() == "evaluation"
        else AccountType.FUNDED
    )
    db.flush()
    created_version = create_profile_version(db, profile, tiers)
    ensure_open_cycle(db, account, profile, created_version, cycle_start)
    return profile, created_version, True
