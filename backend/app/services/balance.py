from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    BrokerConnection,
    CashTransaction,
    DailyBalance,
    ManualAdjustment,
    PropPayoutRecord,
    Trade,
    TradingAccount,
)
from app.services.trading_calendar import (
    fallback_trading_date_for_timestamp,
    fill_trade_date_map,
)

ZERO = Decimal("0")
TRADE_CASH_TYPES = {"commission", "trade paired"}
PAYOUT_CASH_MARKERS = ("payout", "withdraw")


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def _date_as_utc(value: date, zone: ZoneInfo) -> datetime:
    return datetime.combine(value, time.max, tzinfo=zone).astimezone(timezone.utc)


def latest_balance_revisions(snapshots: list[DailyBalance]) -> list[DailyBalance]:
    """Return one latest immutable source revision per date and source."""
    latest: dict[tuple[date, str], DailyBalance] = {}
    for item in snapshots:
        key = (item.trade_date, item.source_identity)
        current = latest.get(key)
        if current is None or (item.revision, str(item.id)) > (
            current.revision,
            str(current.id),
        ):
            latest[key] = item
    return sorted(
        latest.values(),
        key=lambda item: (item.trade_date, item.source_identity, item.revision, str(item.id)),
    )


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
    broker_reported_cash_value: Decimal | None
    broker_reported_net_liquidation: Decimal | None
    broker_snapshot_as_of: datetime | None
    broker_snapshot_source_account: str | None
    broker_snapshot_fresh: bool

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


def _opening_funding_id(
    account: TradingAccount,
    cash: list[CashTransaction],
) -> UUID | None:
    """Identify an opening deposit from source cash chronology, not trade chronology.

    Imported broker executions may predate the actual account's funding after an
    erroneous mapping. Counting opening funding on top of ``starting_balance``
    would then inflate the ledger by the entire original account allocation.

    The first non-trade external cash movement must be an exact starting-balance
    funding entry and, if source identity is present, must belong to this
    account. Later matching deposits are real movements and are not suppressed.
    """
    if account.starting_balance is None:
        return None
    for item in sorted(cash, key=lambda value: (_utc(value.timestamp), str(value.id))):
        kind = item.cash_change_type.strip().lower()
        if kind in TRADE_CASH_TYPES:
            continue
        if kind != "fund transaction" or item.delta != account.starting_balance:
            return None
        source = item.source_payload or {}
        broker_account = source.get("Account") or source.get("account")
        if broker_account and account.external_account_id and (
            str(broker_account).strip().casefold()
            != account.external_account_id.strip().casefold()
        ):
            return None
        return item.id
    return None


def _cash_delta(
    item: CashTransaction,
    *,
    opening_funding_id: UUID | None,
    has_approved_payouts: bool,
) -> Decimal:
    cash_type = item.cash_change_type.strip().lower()
    if cash_type in TRADE_CASH_TYPES:
        return ZERO
    if item.id == opening_funding_id:
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
            .where(
                Trade.account_id.in_(account_ids),
                Trade.accounting_status == "included",
            )
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
    broker_snapshots = _latest_broker_snapshots(db, account_ids)
    trade_dates = fill_trade_date_map(
        db, [item.id for values in trades.values() for item in values]
    )
    return {
        account.id: _calculate_balance(
            account,
            trades.get(account.id, []),
            adjustments.get(account.id, []),
            cash.get(account.id, []),
            payouts.get(account.id, []),
            snapshots.get(account.id, []),
            trade_dates,
            broker_snapshots.get(account.id),
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
    trade_dates: dict[UUID, date],
    broker_snapshot: dict[str, Any] | None,
) -> BalanceResolution:
    zone = ZoneInfo(account.timezone)
    snapshots = latest_balance_revisions(snapshots)
    def trading_date(value: datetime) -> date:
        return fallback_trading_date_for_timestamp(value, account.timezone)

    def trade_date(item: Trade) -> date:
        return trade_dates.get(item.id) or trading_date(item.entry_timestamp)
    opening_funding_id = _opening_funding_id(account, cash)
    trade_net = sum((item.net_pnl for item in trades), ZERO)
    adjustment_net = sum((item.amount for item in adjustments), ZERO)
    cash_net = sum(
        (
            _cash_delta(
                item,
                opening_funding_id=opening_funding_id,
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
            opening_funding_id=opening_funding_id,
            has_approved_payouts=bool(payouts),
        ) != ZERO),
        *(_date_as_utc(item.approved_date, zone) for item in payouts if item.approved_date),
    ]
    latest_activity = max(activity_points, default=None)
    activity_dates = [trade_date(item) for item in trades]
    activity_dates.extend(
        item.trade_date
        for item in cash
        if _cash_delta(
            item,
            opening_funding_id=opening_funding_id,
            has_approved_payouts=bool(payouts),
        ) != ZERO
    )
    activity_dates.extend(trading_date(item.effective_at) for item in adjustments)
    activity_dates.extend(item.approved_date for item in payouts if item.approved_date)
    latest_activity_date = max(activity_dates, default=None)
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
                if trade_date(item) > cutoff
            ),
            ZERO,
        )
        later_adjustments = sum(
            (
                item.amount
                for item in adjustments
                if trading_date(item.effective_at) > cutoff
            ),
            ZERO,
        )
        later_cash = sum(
            (
                _cash_delta(
                    item,
                    opening_funding_id=opening_funding_id,
                    has_approved_payouts=bool(payouts),
                )
                for item in cash
                if item.trade_date > cutoff
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
    broker_fresh = bool(broker_snapshot and broker_snapshot["fresh"])
    broker_value = None
    if broker_fresh:
        broker_value = (
            broker_snapshot["cash_value"]
            if broker_snapshot["cash_value"] is not None
            else broker_snapshot["net_liquidation"]
        )
        if broker_value is not None:
            resolved = broker_value
            method = "broker_reported_snapshot"
            difference = broker_value - calculated if calculated is not None else None
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
        broker_reported_cash_value=(
            broker_snapshot["cash_value"] if broker_snapshot else None
        ),
        broker_reported_net_liquidation=(
            broker_snapshot["net_liquidation"] if broker_snapshot else None
        ),
        broker_snapshot_as_of=broker_snapshot["captured_at"] if broker_snapshot else None,
        broker_snapshot_source_account=(
            broker_snapshot["source_account_name"] if broker_snapshot else None
        ),
        broker_snapshot_fresh=broker_fresh,
    )


def _latest_broker_snapshots(
    db: Session,
    account_ids: list[UUID],
) -> dict[UUID, dict[str, Any]]:
    if not account_ids:
        return {}
    connections = db.scalars(
        select(BrokerConnection).where(
            BrokerConnection.account_id.in_(account_ids),
            BrokerConnection.provider == "ninjatrader",
            BrokerConnection.connection_type == "desktop_bridge",
            BrokerConnection.status != "removed",
        )
    ).all()
    latest: dict[UUID, dict[str, Any]] = {}
    now = datetime.now(timezone.utc)
    for connection in connections:
        account_id = connection.account_id
        snapshot = (connection.metadata_json or {}).get("account_snapshot") or {}
        captured_text = snapshot.get("captured_at")
        if not account_id or not captured_text:
            continue
        try:
            captured_at = datetime.fromisoformat(str(captured_text).replace("Z", "+00:00"))
            captured_at = _utc(captured_at)
        except (TypeError, ValueError):
            continue
        age = now - captured_at
        fresh = timedelta(0) <= age <= timedelta(minutes=5)
        candidate = {
            "captured_at": captured_at,
            "cash_value": (
                Decimal(str(snapshot["cash_value"]))
                if snapshot.get("cash_value") is not None
                else None
            ),
            "net_liquidation": (
                Decimal(str(snapshot["net_liquidation"]))
                if snapshot.get("net_liquidation") is not None
                else None
            ),
            "source_account_name": connection.source_account_name,
            "fresh": fresh,
        }
        previous = latest.get(account_id)
        if previous is None or candidate["captured_at"] > previous["captured_at"]:
            latest[account_id] = candidate
    return latest
