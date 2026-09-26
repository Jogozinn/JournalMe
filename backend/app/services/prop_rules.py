from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    DailyBalance,
    ManualAdjustment,
    PropPayoutCycle,
    PropPayoutRecord,
    PropRuleProfile,
    PropRuleProfileVersion,
    PropScalingTier,
    Trade,
    TradingAccount,
)
from app.schemas import PropScalingTierInput
from app.services.balance import BalanceResolution

MONEY = Decimal("0.01")

PROFILE_RULE_FIELDS = (
    "firm_name",
    "account_label",
    "profile_account_type",
    "starting_balance",
    "profit_target",
    "max_loss",
    "daily_loss_limit",
    "consistency_percent",
    "drawdown_type",
    "drawdown_amount",
    "drawdown_lock_behavior",
    "payout_buffer",
    "minimum_trading_days",
    "qualifying_profit_days_required",
    "minimum_profit_per_qualifying_day",
    "payout_cycle_net_profit_required",
    "minimum_payout",
    "payout_profit_percentage",
    "maximum_payout",
    "maximum_payout_count",
    "profit_split_trader_percent",
    "profit_split_firm_percent",
    "no_fixed_payout_window",
    "payout_cycle_start_date",
    "qualifying_days_since_last_payout",
    "payouts_completed",
    "preset_key",
    "effective_date",
    "source_note",
    "preset_version_id",
    "configuration_state",
    "evaluation_drawdown_choice",
    "daily_loss_limit_enabled",
    "daily_loss_limit_amount",
    "initial_trail_balance",
    "locked_mll_balance",
    "payout_buffer_balance_threshold",
    "max_daily_simulated_profit",
    "news_restriction_note",
    "live_transition_note",
    "purchase_configuration_json",
    "rules_enabled_json",
    "enabled",
)


def _money(value: Decimal | None) -> str | None:
    return (
        str(value.quantize(MONEY, rounding=ROUND_HALF_UP))
        if value is not None
        else None
    )


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    return value


def profile_rules_snapshot(profile: PropRuleProfile) -> dict[str, Any]:
    return {
        field: _json_value(getattr(profile, field))
        for field in PROFILE_RULE_FIELDS
    }


def lucidflex_funded_50k_preset(
    cycle_start: date,
) -> tuple[dict[str, Any], list[PropScalingTierInput]]:
    rules = {
        "firm_name": "Lucid Trading",
        "account_label": "Lucid Flex 50K #1",
        "profile_account_type": "LucidFlex Funded",
        "starting_balance": Decimal("50000"),
        "profit_target": None,
        "max_loss": Decimal("2000"),
        "daily_loss_limit": None,
        "consistency_percent": None,
        "drawdown_type": "end_of_day_trailing",
        "drawdown_amount": Decimal("2000"),
        "drawdown_lock_behavior": None,
        "payout_buffer": None,
        "minimum_trading_days": None,
        "qualifying_profit_days_required": 5,
        "minimum_profit_per_qualifying_day": Decimal("150"),
        "payout_cycle_net_profit_required": True,
        "minimum_payout": Decimal("500"),
        "payout_profit_percentage": Decimal("50"),
        "maximum_payout": Decimal("2000"),
        "maximum_payout_count": 5,
        "profit_split_trader_percent": Decimal("90"),
        "profit_split_firm_percent": Decimal("10"),
        "no_fixed_payout_window": True,
        "payout_cycle_start_date": cycle_start,
        "qualifying_days_since_last_payout": 0,
        "payouts_completed": 0,
        "preset_key": "lucidflex-funded-50k",
        "effective_date": cycle_start,
        "source_note": (
            "User-configured LucidFlex Funded 50K preset. Verify against the "
            "current Lucid Trading firm agreement."
        ),
        "configuration_state": "configured",
        "evaluation_drawdown_choice": None,
        "daily_loss_limit_enabled": False,
        "daily_loss_limit_amount": None,
        "initial_trail_balance": Decimal("52100"),
        "locked_mll_balance": Decimal("50100"),
        "payout_buffer_balance_threshold": None,
        "max_daily_simulated_profit": None,
        "news_restriction_note": None,
        "live_transition_note": None,
        "purchase_configuration_json": {},
        "rules_enabled_json": {
            "profit_target": False,
            "max_loss": True,
            "daily_loss_limit": False,
            "consistency": False,
            "minimum_trading_days": False,
            "qualifying_profit_days": True,
            "payout_cycle_net_profit": True,
        },
        "enabled": True,
    }
    tiers = [
        PropScalingTierInput(
            lower_profit_bound=Decimal("0"),
            upper_profit_bound=Decimal("999.99"),
            max_mini_contracts=2,
            max_micro_contracts=20,
        ),
        PropScalingTierInput(
            lower_profit_bound=Decimal("1000"),
            upper_profit_bound=Decimal("1999.99"),
            max_mini_contracts=3,
            max_micro_contracts=30,
        ),
        PropScalingTierInput(
            lower_profit_bound=Decimal("2000"),
            upper_profit_bound=Decimal("2999.99"),
            max_mini_contracts=4,
            max_micro_contracts=40,
        ),
    ]
    return rules, tiers


def create_profile_version(
    db: Session,
    profile: PropRuleProfile,
    tiers: list[PropScalingTierInput],
) -> PropRuleProfileVersion:
    next_number = (
        db.scalar(
            select(func.max(PropRuleProfileVersion.version_number)).where(
                PropRuleProfileVersion.profile_id == profile.id
            )
        )
        or 0
    ) + 1
    version = PropRuleProfileVersion(
        profile_id=profile.id,
        version_number=next_number,
        effective_date=profile.effective_date or date.today(),
        source_note=profile.source_note,
        preset_version_id=profile.preset_version_id,
        purchase_configuration_json=profile.purchase_configuration_json or {},
        rules_json=profile_rules_snapshot(profile),
    )
    db.add(version)
    db.flush()
    version.scaling_tiers = [
        PropScalingTier(
            profile_version_id=version.id,
            lower_profit_bound=item.lower_profit_bound,
            upper_profit_bound=item.upper_profit_bound,
            max_mini_contracts=item.max_mini_contracts,
            max_micro_contracts=item.max_micro_contracts,
        )
        for item in tiers
    ]
    db.flush()
    return version


def latest_profile_version(
    db: Session, profile_id
) -> PropRuleProfileVersion | None:
    return db.scalar(
        select(PropRuleProfileVersion)
        .options(selectinload(PropRuleProfileVersion.scaling_tiers))
        .where(PropRuleProfileVersion.profile_id == profile_id)
        .order_by(PropRuleProfileVersion.version_number.desc())
    )


def ensure_open_cycle(
    db: Session,
    account: TradingAccount,
    profile: PropRuleProfile,
    version: PropRuleProfileVersion,
    fallback_start: date,
) -> PropPayoutCycle:
    cycle = db.scalar(
        select(PropPayoutCycle).where(
            PropPayoutCycle.account_id == account.id,
            PropPayoutCycle.status == "open",
        )
    )
    start = profile.payout_cycle_start_date or fallback_start
    if cycle is None:
        cycle = PropPayoutCycle(
            account_id=account.id,
            profile_version_id=version.id,
            start_date=start,
            status="open",
        )
        db.add(cycle)
        db.flush()
    return cycle


def _in_cycle(
    timestamp: datetime, zone: ZoneInfo, cycle: PropPayoutCycle | None
) -> bool:
    if cycle is None:
        return True
    value = timestamp
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    local_date = value.astimezone(zone).date()
    return local_date >= cycle.start_date and (
        cycle.end_date is None or local_date <= cycle.end_date
    )


def calculate_prop_status(
    account: TradingAccount,
    profile: PropRuleProfile,
    trades: list[Trade],
    balances: list[DailyBalance],
    adjustments: list[ManualAdjustment] | None = None,
    cycle: PropPayoutCycle | None = None,
    version: PropRuleProfileVersion | None = None,
    payouts: list[PropPayoutRecord] | None = None,
    balance_resolution: BalanceResolution | None = None,
    hard_breach: bool = False,
) -> dict[str, Any]:
    adjustments = adjustments or []
    payouts = payouts or []
    zone = ZoneInfo(account.timezone)
    all_by_day: dict[date, Decimal] = defaultdict(lambda: Decimal("0"))
    cycle_by_day: dict[date, Decimal] = defaultdict(lambda: Decimal("0"))
    calculated_profit = Decimal("0")
    cycle_trade_profit = Decimal("0")
    for trade in trades:
        timestamp = trade.entry_timestamp
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        local_date = timestamp.astimezone(zone).date()
        all_by_day[local_date] += trade.net_pnl
        calculated_profit += trade.net_pnl
        if _in_cycle(timestamp, zone, cycle):
            cycle_by_day[local_date] += trade.net_pnl
            cycle_trade_profit += trade.net_pnl

    cycle_adjustments = Decimal("0")
    for item in adjustments:
        if _in_cycle(item.effective_at, zone, cycle):
            cycle_adjustments += item.amount
    cycle_net_profit = cycle_trade_profit + cycle_adjustments

    imported_balance = balances[-1].total_amount if balances else None
    configured_start = (
        profile.starting_balance
        if profile.starting_balance is not None
        else account.starting_balance
    )
    current_balance = (
        balance_resolution.resolved_current_balance
        if balance_resolution is not None
        else imported_balance
        if imported_balance is not None
        else configured_start + calculated_profit
        if configured_start is not None
        else None
    )
    net_profit = (
        current_balance - configured_start
        if current_balance is not None and configured_start is not None
        else calculated_profit
    )
    best_day = max(all_by_day.values(), default=Decimal("0"))
    positive_profit = max(net_profit, Decimal("0"))
    consistency = profile.consistency_percent
    best_day_percent = (
        best_day / positive_profit * 100
        if positive_profit > 0 and best_day > 0
        else None
    )
    additional_for_consistency = None
    if consistency is not None and consistency > 0 and best_day > 0:
        required_profit = best_day / (consistency / 100)
        additional_for_consistency = max(
            required_profit - positive_profit, Decimal("0")
        )

    profit_remaining = (
        max(profile.profit_target - net_profit, Decimal("0"))
        if profile.profit_target is not None
        else None
    )
    drawdown_amount = (
        profile.drawdown_amount
        if profile.drawdown_amount is not None
        else profile.max_loss
    )
    high_water_balance = configured_start
    if profile.drawdown_type == "end_of_day_trailing" and drawdown_amount is not None:
        cumulative = configured_start
        calculated_end_of_day = []
        if cumulative is not None:
            for item_date in sorted(all_by_day):
                cumulative += all_by_day[item_date]
                calculated_end_of_day.append(cumulative)
        candidates = [
            value
            for value in [
                configured_start,
                *(item.total_amount for item in balances),
                *calculated_end_of_day,
            ]
            if value is not None
        ]
        high_water_balance = max(candidates) if candidates else None
        loss_floor = (
            high_water_balance - drawdown_amount
            if high_water_balance is not None
            else None
        )
        if loss_floor is not None and profile.locked_mll_balance is not None:
            loss_floor = min(loss_floor, profile.locked_mll_balance)
    else:
        loss_floor = (
            configured_start - profile.max_loss
            if configured_start is not None
            else None
        )
    maximum_loss_buffer = (
        current_balance - loss_floor
        if current_balance is not None and loss_floor is not None
        else None
    )
    latest_day_pnl = all_by_day[max(all_by_day)] if all_by_day else Decimal("0")
    daily_loss_buffer = (
        profile.daily_loss_limit + latest_day_pnl
        if profile.daily_loss_limit is not None
        else None
    )
    minimum_days_remaining = (
        max(profile.minimum_trading_days - len(all_by_day), 0)
        if profile.minimum_trading_days is not None
        else None
    )

    qualifying_threshold = profile.minimum_profit_per_qualifying_day
    qualifying_dates = sorted(
        item_date
        for item_date, pnl in cycle_by_day.items()
        if qualifying_threshold is not None and pnl >= qualifying_threshold
    )
    qualifying_count = (
        (profile.qualifying_days_since_last_payout or 0)
        + len(set(qualifying_dates))
    )
    qualifying_required = profile.qualifying_profit_days_required
    eligible_by_days = (
        qualifying_count >= qualifying_required
        if qualifying_required is not None
        else True
    )
    eligible_by_profit = (
        cycle_net_profit > 0
        if profile.payout_cycle_net_profit_required is not False
        else True
    )
    rule_breaches: list[str] = []
    if maximum_loss_buffer is not None and maximum_loss_buffer < 0:
        rule_breaches.append("Maximum-loss limit breached.")
    if daily_loss_buffer is not None and daily_loss_buffer < 0:
        rule_breaches.append("Daily-loss limit breached.")
    if hard_breach:
        rule_breaches.append("A recorded hard rule breach blocks payout eligibility.")

    approved_count = sum(item.status == "approved" for item in payouts)
    payouts_completed = max(profile.payouts_completed or 0, approved_count)
    payout_count_available = (
        profile.maximum_payout_count is None
        or payouts_completed < profile.maximum_payout_count
    )
    if not payout_count_available:
        rule_breaches.append("Maximum payout count reached.")
    is_daily_funded = profile.preset_key == "lucid_daily_funded_50k"
    is_evaluation = profile.preset_key == "lucid_daily_eval_50k"
    eligible_for_payout = (
        eligible_by_days
        and eligible_by_profit
        and payout_count_available
        and not rule_breaches
        and not is_evaluation
    )

    gross_available = None
    profit_above_buffer = None
    if is_daily_funded and current_balance is not None:
        threshold = profile.payout_buffer_balance_threshold or Decimal("52100")
        profit_above_buffer = max(current_balance - threshold, Decimal("0"))
        gross_available = profit_above_buffer.quantize(
            MONEY, rounding=ROUND_HALF_UP
        )
    elif profile.payout_profit_percentage is not None:
        gross_available = max(cycle_net_profit, Decimal("0")) * (
            profile.payout_profit_percentage / Decimal("100")
        )
        if profile.maximum_payout is not None:
            gross_available = min(gross_available, profile.maximum_payout)
        gross_available = gross_available.quantize(MONEY, rounding=ROUND_HALF_UP)
    minimum_payout_met = (
        gross_available is not None
        and (
            profile.minimum_payout is None
            or gross_available >= profile.minimum_payout
        )
    )
    if is_daily_funded:
        eligible_for_payout = (
            eligible_for_payout
            and bool(profit_above_buffer and profit_above_buffer > 0)
            and minimum_payout_met
        )
    requestable_payout = (
        gross_available if eligible_for_payout and minimum_payout_met else None
    )
    trader_share = (
        gross_available
        * profile.profit_split_trader_percent
        / Decimal("100")
        if gross_available is not None
        and profile.profit_split_trader_percent is not None
        else None
    )
    if trader_share is not None:
        trader_share = trader_share.quantize(MONEY, rounding=ROUND_HALF_UP)
    firm_share = (
        gross_available - trader_share
        if gross_available is not None and trader_share is not None
        else None
    )

    tiers = list(version.scaling_tiers) if version is not None else []
    tiers.sort(key=lambda item: item.lower_profit_bound)
    current_tier = None
    for item in tiers:
        if net_profit >= item.lower_profit_bound and (
            item.upper_profit_bound is None or net_profit <= item.upper_profit_bound
        ):
            current_tier = item
    current_index = tiers.index(current_tier) if current_tier in tiers else -1
    previous_tier = tiers[current_index - 1] if current_index > 0 else None
    next_tier = (
        tiers[current_index + 1]
        if current_index >= 0 and current_index + 1 < len(tiers)
        else None
    )

    ineligibility_reasons = []
    if not eligible_by_days and qualifying_required is not None:
        ineligibility_reasons.append(
            f"{qualifying_count} of {qualifying_required or 0} qualifying profit days."
        )
    if not eligible_by_profit:
        ineligibility_reasons.append("Payout-cycle net profit is not positive.")
    if is_daily_funded and not profit_above_buffer:
        ineligibility_reasons.append(
            "Resolved balance is not above the $52,100 payout threshold."
        )
    if is_daily_funded and gross_available is not None and not minimum_payout_met:
        ineligibility_reasons.append("Gross requestable payout is below $500.")
    ineligibility_reasons.extend(rule_breaches)

    generic_checks = []
    if profile.profit_target is not None:
        generic_checks.append(net_profit >= profile.profit_target)
    if maximum_loss_buffer is not None:
        generic_checks.append(maximum_loss_buffer >= 0)
    if daily_loss_buffer is not None:
        generic_checks.append(daily_loss_buffer >= 0)
    if consistency is not None and best_day_percent is not None:
        generic_checks.append(best_day_percent <= consistency)
    if minimum_days_remaining is not None:
        generic_checks.append(minimum_days_remaining == 0)

    def tier_payload(item: PropScalingTier | None) -> dict[str, Any] | None:
        if item is None:
            return None
        return {
            "lower_profit_bound": _money(item.lower_profit_bound),
            "upper_profit_bound": _money(item.upper_profit_bound),
            "max_mini_contracts": item.max_mini_contracts,
            "max_micro_contracts": item.max_micro_contracts,
        }

    return {
        "enabled": profile.enabled,
        "profile_version": (
            {
                "id": str(version.id),
                "version_number": version.version_number,
                "effective_date": version.effective_date.isoformat(),
                "source_note": version.source_note,
            }
            if version is not None
            else None
        ),
        "verified": {
            "current_imported_balance": _money(imported_balance),
            "calculated_trade_net_pnl": _money(calculated_profit),
            "trading_days": len(all_by_day),
            "best_day": _money(best_day),
            "latest_day_net_pnl": _money(latest_day_pnl),
        },
        "configured": {
            field: (
                _money(value)
                if isinstance(value := getattr(profile, field), Decimal)
                else value.isoformat()
                if isinstance(value, date)
                else value
            )
            for field in PROFILE_RULE_FIELDS
            if field
            not in {
                "rules_enabled_json",
                "enabled",
                "source_note",
                "effective_date",
                "preset_key",
            }
        },
        "status": {
            "current_balance": _money(current_balance),
            "net_profit": _money(net_profit),
            "profit_remaining": _money(profit_remaining),
            "best_day_percent": _money(best_day_percent),
            "additional_profit_for_consistency": _money(
                additional_for_consistency
            ),
            "maximum_loss_buffer": _money(maximum_loss_buffer),
            "maximum_loss_floor": _money(loss_floor),
            "high_water_balance": _money(high_water_balance),
            "daily_loss_buffer": _money(daily_loss_buffer),
            "minimum_days_remaining": minimum_days_remaining,
            "estimated_pass": bool(generic_checks) and all(generic_checks),
        },
        "payout_cycle": {
            "id": str(cycle.id) if cycle is not None else None,
            "start_date": cycle.start_date.isoformat() if cycle is not None else None,
            "cycle_trade_net_pnl": _money(cycle_trade_profit),
            "approved_manual_adjustments": _money(cycle_adjustments),
            "cycle_net_profit": _money(cycle_net_profit),
            "qualifying_day_dates": [item.isoformat() for item in qualifying_dates],
            "qualifying_day_count": qualifying_count,
            "qualifying_day_required": qualifying_required,
            "eligible_by_days": eligible_by_days,
            "eligible_by_profit": eligible_by_profit,
            "eligible_for_payout": eligible_for_payout,
            "gross_available_payout": _money(gross_available),
            "minimum_payout_met": minimum_payout_met,
            "requestable_payout": _money(requestable_payout),
            "buffer_balance_threshold": _money(
                profile.payout_buffer_balance_threshold
            ),
            "profit_above_buffer": _money(profit_above_buffer),
            "estimated_trader_share": _money(trader_share),
            "estimated_firm_share": _money(firm_share),
            "payouts_completed": payouts_completed,
            "maximum_payout_count": profile.maximum_payout_count,
            "ineligibility_reasons": ineligibility_reasons,
        },
        "scaling": {
            "current": tier_payload(current_tier),
            "previous": tier_payload(previous_tier),
            "next": tier_payload(next_tier),
        },
        "formulas": {
            "net_profit": "current balance - configured starting balance",
            "cycle_net_profit": (
                "cycle trade net P&L after fees + approved manual adjustments"
            ),
            "qualifying_day": (
                "distinct cycle date where daily net P&L ≥ minimum qualifying-day profit"
            ),
            "gross_available_payout": (
                "max(0, resolved current balance - payout buffer balance threshold)"
                if is_daily_funded
                else "min(cycle net profit × payout percentage, maximum payout)"
            ),
            "trader_share": "gross available payout × trader profit split",
            "maximum_loss_buffer": (
                "current balance - (highest imported end-of-day balance - drawdown amount)"
                if profile.drawdown_type == "end_of_day_trailing"
                else "current balance - (starting balance - maximum loss)"
            ),
        },
        "warning": (
            "Informational estimate. Verify every configured rule against the "
            "current firm agreement. End-of-day trailing drawdown uses imported "
            "daily balances and cannot represent missing intraday firm events."
        ),
        "balance_resolution": (
            balance_resolution.as_dict() if balance_resolution is not None else None
        ),
    }
