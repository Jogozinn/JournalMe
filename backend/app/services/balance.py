from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timezone
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    CashTransaction,
    DailyBalance,
    ManualAdjustment,
    PropPayoutRecord,
    Trade,
    TradingAccount,
)

ZERO = Decimal("0")
TRADE_CASH_TYPES = {"commission", "trade paired"}
PAYOUT_CASH_MARKERS = ("payout", "withdraw")


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def _local_date(value: datetime, zone: ZoneInfo) -> date:
    return _utc(value).astimezone(zone).date()


def _date_as_utc(value: date, zone: ZoneInfo) -> datetime:
    return datetime.combine(value, time.max, tzinfo=zone).astimezone(timezone.utc)


def _money(value: Decimal | None) -> str | None:
    return str(value.quantize(Decimal("0.01"))) if value is not None else None


@dataclass(frozen=True)
class BalanceResolution:
    starting_balance: Decimal | None
    imported_balance: Decimal | None
    imported_balance_as_of: date | None
    calculated_balance: Decimal | None
    calculated_balance_as_of: datetime | None
    resolved_current_balance: Decimal | None
    resolution_method: str
    reconciliation_difference: Decimal | None
    stale_snapshot: bool
    canonical_trade_net_pnl: Decimal
    approved_manual_adjustments: Decimal
    external_cash_movements: Decimal
    approved_payout_deductions: Decimal

    def as_dict(self) -> dict[str, Any]:
        values = asdict(self)
        for key, value in list(values.items()):
            if isinstance(value, Decimal):
                values[key] = _money(value)
            elif isinstance(value, (date, datetime)):
                values[key] = value.isoformat()
        return values


def _is_approved_adjustment(item: ManualAdjustment) -> bool:
    return getattr(item, "status", "approved") == "approved"


def _is_opening_funding(
    item: CashTransaction,
    starting_balance: Decimal | None,
    first_trade_at: datetime | None,
) -> bool:
    if item.cash_change_type.strip().lower() != "fund transaction":
        return False
    if starting_balance is None or item.delta != starting_balance:
        return False
    return first_trade_at is None or _utc(item.timestamp) <= _utc(first_trade_at)


def _cash_delta(
    item: CashTransaction,
    *,
    starting_balance: Decimal | None,
    first_trade_at: datetime | None,
    has_approved_payouts: bool,
) -> Decimal:
    cash_type = item.cash_change_type.strip().lower()
    if cash_type in TRADE_CASH_TYPES:
        return ZERO
    if _is_opening_funding(item, starting_balance, first_trade_at):
        return ZERO
    if has_approved_payouts and any(marker in cash_type for marker in PAYOUT_CASH_MARKERS):
        return ZERO
    return item.delta


def _group_by_account(items) -> dict[Any, list[Any]]:
    grouped: dict[Any, list[Any]] = defaultdict(list)
    for item in items:
        grouped[item.account_id].append(item)
    return grouped


def resolve_account_balances(
    db: Session,
    accounts: list[TradingAccount],
) -> dict[Any, BalanceResolution]:
    if not accounts:
        return {}
    account_ids = [item.id for item in accounts]
    trades = _group_by_account(
        db.scalars(
            select(Trade)
            .where(Trade.account_id.in_(account_ids))
            .order_by(Trade.account_id, Trade.exit_timestamp)
        ).all()
    )
    adjustments = _group_by_account(
        item
        for item in db.scalars(
            select(ManualAdjustment)
            .where(
                ManualAdjustment.account_id.in_(account_ids),
                ManualAdjustment.status == "approved",
            )
            .order_by(
                ManualAdjustment.account_id,
                ManualAdjustment.effective_at,
            )
        ).all()
        if _is_approved_adjustment(item)
    )
    cash = _group_by_account(
        db.scalars(
            select(CashTransaction)
            .where(CashTransaction.account_id.in_(account_ids))
            .order_by(CashTransaction.account_id, CashTransaction.timestamp)
        ).all()
    )
    payouts = _group_by_account(
        db.scalars(
            select(PropPayoutRecord)
            .where(
                PropPayoutRecord.account_id.in_(account_ids),
                PropPayoutRecord.status == "approved",
            )
            .order_by(
                PropPayoutRecord.account_id,
                PropPayoutRecord.approved_date,
            )
        ).all()
    )
    snapshots = _group_by_account(
        db.scalars(
            select(DailyBalance)
            .where(DailyBalance.account_id.in_(account_ids))
            .order_by(DailyBalance.account_id, DailyBalance.trade_date)
        ).all()
    )
    return {
        account.id: _calculate_balance(
            account,
            trades.get(account.id, []),
            adjustments.get(account.id, []),
            cash.get(account.id, []),
            payouts.get(account.id, []),
            snapshots.get(account.id, []),
        )
        for account in accounts
    }


def resolve_account_balance(
    db: Session,
    account: TradingAccount,
) -> BalanceResolution:
    return resolve_account_balances(db, [account])[account.id]


def _calculate_balance(
    account: TradingAccount,
    trades: list[Trade],
    adjustments: list[ManualAdjustment],
    cash: list[CashTransaction],
    payouts: list[PropPayoutRecord],
    snapshots: list[DailyBalance],
) -> BalanceResolution:
    zone = ZoneInfo(account.timezone)
    first_trade_at = trades[0].entry_timestamp if trades else None
    trade_net = sum((item.net_pnl for item in trades), ZERO)
    adjustment_net = sum((item.amount for item in adjustments), ZERO)
    cash_net = sum(
        (
            _cash_delta(
                item,
                starting_balance=account.starting_balance,
                first_trade_at=first_trade_at,
                has_approved_payouts=bool(payouts),
            )
            for item in cash
        ),
        ZERO,
    )
    payout_deductions = sum(
        (
            item.approved_gross_amount
            if item.approved_gross_amount is not None
            else item.requested_amount
            for item in payouts
        ),
        ZERO,
    )
    calculated = (
        account.starting_balance
        + trade_net
        + adjustment_net
        + cash_net
        - payout_deductions
        if account.starting_balance is not None
        else None
    )

    activity_points: list[datetime] = [
        *(_utc(item.exit_timestamp) for item in trades),
        *(_utc(item.effective_at) for item in adjustments),
        *(_utc(item.timestamp) for item in cash if _cash_delta(
            item,
            starting_balance=account.starting_balance,
            first_trade_at=first_trade_at,
            has_approved_payouts=bool(payouts),
        ) != ZERO),
        *(_date_as_utc(item.approved_date, zone) for item in payouts if item.approved_date),
    ]
    latest_activity = max(activity_points, default=None)
    latest_activity_date = (
        _local_date(latest_activity, zone) if latest_activity is not None else None
    )
    latest_snapshot = snapshots[-1] if snapshots else None
    imported = latest_snapshot.total_amount if latest_snapshot else None
    imported_as_of = latest_snapshot.trade_date if latest_snapshot else None
    stale = bool(
        imported_as_of
        and latest_activity_date
        and imported_as_of < latest_activity_date
    )

    if latest_snapshot and not stale:
        resolved = imported
        method = "imported_snapshot"
    elif latest_snapshot:
        cutoff = latest_snapshot.trade_date
        later_trades = sum(
            (
                item.net_pnl
                for item in trades
                if _local_date(item.exit_timestamp, zone) > cutoff
            ),
            ZERO,
        )
        later_adjustments = sum(
            (
                item.amount
                for item in adjustments
                if _local_date(item.effective_at, zone) > cutoff
            ),
            ZERO,
        )
        later_cash = sum(
            (
                _cash_delta(
                    item,
                    starting_balance=account.starting_balance,
                    first_trade_at=first_trade_at,
                    has_approved_payouts=bool(payouts),
                )
                for item in cash
                if _local_date(item.timestamp, zone) > cutoff
            ),
            ZERO,
        )
        later_payouts = sum(
            (
                item.approved_gross_amount
                if item.approved_gross_amount is not None
                else item.requested_amount
                for item in payouts
                if item.approved_date and item.approved_date > cutoff
            ),
            ZERO,
        )
        resolved = (
            imported + later_trades + later_adjustments + later_cash - later_payouts
        )
        method = "stale_snapshot_roll_forward"
    elif latest_activity is not None:
        resolved = calculated
        method = "calculated_from_ledger"
    else:
        resolved = account.starting_balance
        method = "starting_balance_no_activity"

    difference = (
        imported - calculated
        if imported is not None and calculated is not None
        else None
    )
    return BalanceResolution(
        starting_balance=account.starting_balance,
        imported_balance=imported,
        imported_balance_as_of=imported_as_of,
        calculated_balance=calculated,
        calculated_balance_as_of=latest_activity,
        resolved_current_balance=resolved,
        resolution_method=method,
        reconciliation_difference=difference,
        stale_snapshot=stale,
        canonical_trade_net_pnl=trade_net,
        approved_manual_adjustments=adjustment_net,
        external_cash_movements=cash_net,
        approved_payout_deductions=payout_deductions,
    )
