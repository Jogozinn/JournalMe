from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain import TradeSide
from app.models import (
    Attachment,
    CaptureEvent,
    Fill,
    Order,
    RuleViolation,
    Trade,
    TradeChecklistResponse,
    TradeJournal,
    TradePlaybook,
    TradeTag,
    TradingAccount,
)
from app.services.instrument_identity import canonical_contract_key, root_symbol


PREFERRED_SOURCE_QUALITY = {
    "multi_source_reconciled": 50,
    "ledger_reconciled": 45,
    "fills_lifecycle": 40,
    "broker_live": 30,
    "paired_report": 20,
    "manual": 100,
}


@dataclass(frozen=True)
class PersistedFillSlice:
    fill: Fill
    quantity: Decimal
    role: str


@dataclass(frozen=True)
class PersistedLifecycle:
    slices: tuple[PersistedFillSlice, ...]
    symbol: str
    side: TradeSide
    quantity: Decimal
    entry_price: Decimal
    exit_price: Decimal
    entry_timestamp: datetime
    exit_timestamp: datetime

    @property
    def fill_ids(self) -> set[str]:
        return {
            item.fill.external_fill_id
            for item in self.slices
            if item.fill.external_fill_id
        }


def _split_ids(value: str | None) -> set[str]:
    return {item.strip() for item in (value or "").split(",") if item.strip()}


def trade_fill_ids(trade: Trade) -> set[str]:
    ids = _split_ids(trade.external_buy_fill_id) | _split_ids(trade.external_sell_fill_id)
    payload = trade.source_payload or {}
    for key in ("fill_ids", "ledger_fill_ids", "execution_ids"):
        values = payload.get(key)
        if isinstance(values, list):
            ids.update(str(value) for value in values if value)
    tradovate = payload.get("tradovate_reconciliation")
    if isinstance(tradovate, dict):
        values = tradovate.get("fill_ids")
        if isinstance(values, list):
            ids.update(str(value) for value in values if value)
    return ids


def _as_utc_naive(value: datetime) -> datetime:
    return value.replace(tzinfo=None) if value.tzinfo is not None else value


def _side_sign(action: str) -> int:
    value = action.strip().casefold()
    if value in {"buy", "long"}:
        return 1
    if value in {"sell", "short"}:
        return -1
    raise ValueError(f"Unsupported fill action: {action}")


def _weighted_fill_price(slices: list[PersistedFillSlice], role: str) -> Decimal:
    selected = [item for item in slices if item.role == role]
    quantity = sum((item.quantity for item in selected), Decimal("0"))
    if quantity <= 0:
        return Decimal("0")
    return sum((item.quantity * Decimal(item.fill.price) for item in selected), Decimal("0")) / quantity


def _reconstruct_fill_lifecycles(fills: list[Fill]) -> list[PersistedLifecycle]:
    by_contract: dict[str, list[Fill]] = defaultdict(list)
    for fill in fills:
        by_contract[canonical_contract_key(fill.symbol, fill.timestamp)].append(fill)

    completed: list[PersistedLifecycle] = []
    for contract_fills in by_contract.values():
        ordered = sorted(
            contract_fills,
            key=lambda item: (_as_utc_naive(item.timestamp), str(item.external_fill_id or ""), str(item.id)),
        )
        position = Decimal("0")
        active: list[PersistedFillSlice] = []

        def finalize() -> None:
            nonlocal active
            opens = [item for item in active if item.role == "open"]
            closes = [item for item in active if item.role == "close"]
            opened = sum((item.quantity for item in opens), Decimal("0"))
            closed = sum((item.quantity for item in closes), Decimal("0"))
            if not opens or opened <= 0 or opened != closed:
                return
            completed.append(
                PersistedLifecycle(
                    slices=tuple(active),
                    symbol=opens[0].fill.symbol,
                    side=TradeSide.LONG if _side_sign(opens[0].fill.action) > 0 else TradeSide.SHORT,
                    quantity=opened,
                    entry_price=_weighted_fill_price(active, "open"),
                    exit_price=_weighted_fill_price(active, "close"),
                    entry_timestamp=min(item.fill.timestamp for item in opens),
                    exit_timestamp=max(item.fill.timestamp for item in closes),
                )
            )
            active = []

        for fill in ordered:
            remaining = Decimal(fill.quantity)
            event_side = _side_sign(fill.action)
            while remaining > 0:
                if position == 0:
                    active.append(PersistedFillSlice(fill, remaining, "open"))
                    position = Decimal(event_side) * remaining
                    remaining = Decimal("0")
                    continue
                position_side = 1 if position > 0 else -1
                if event_side == position_side:
                    active.append(PersistedFillSlice(fill, remaining, "open"))
                    position += Decimal(event_side) * remaining
                    remaining = Decimal("0")
                    continue
                close_qty = min(abs(position), remaining)
                active.append(PersistedFillSlice(fill, close_qty, "close"))
                position += Decimal(event_side) * close_qty
                remaining -= close_qty
                if position == 0:
                    finalize()
                    # A reversal execution may have quantity remaining; that
                    # remainder becomes the opening slice of the next lifecycle.
                    continue
    return sorted(completed, key=lambda item: item.entry_timestamp)


def _same_lifecycle_trade(left: Trade, right: Trade) -> bool:
    return _same_lifecycle_values(
        left,
        symbol=right.symbol,
        side=right.side,
        quantity=Decimal(right.contract_quantity),
        entry_price=Decimal(right.entry_price),
        exit_price=Decimal(right.exit_price),
        entry_timestamp=right.entry_timestamp,
        exit_timestamp=right.exit_timestamp,
    )


def _same_lifecycle_values(
    trade: Trade,
    *,
    symbol: str,
    side: TradeSide,
    quantity: Decimal,
    entry_price: Decimal,
    exit_price: Decimal,
    entry_timestamp: datetime,
    exit_timestamp: datetime,
) -> bool:
    if trade.source_quality == "manual" or trade.side != side:
        return False
    if Decimal(trade.contract_quantity) != quantity:
        return False
    if canonical_contract_key(trade.symbol, trade.entry_timestamp) != canonical_contract_key(symbol, entry_timestamp):
        return False
    tolerance = max(Decimal(trade.tick_size or 0), Decimal("0.00000001")) / Decimal("2")
    if abs(Decimal(trade.entry_price) - entry_price) > tolerance:
        return False
    if abs(Decimal(trade.exit_price) - exit_price) > tolerance:
        return False
    if abs((_as_utc_naive(trade.entry_timestamp) - _as_utc_naive(entry_timestamp)).total_seconds()) > 3:
        return False
    if abs((_as_utc_naive(trade.exit_timestamp) - _as_utc_naive(exit_timestamp)).total_seconds()) > 3:
        return False
    return True


def _has_user_content(db: Session, trade_id: UUID) -> bool:
    checks = (TradeJournal, TradeTag, TradePlaybook, TradeChecklistResponse, Attachment, RuleViolation)
    return any(
        db.scalar(select(model).where(model.trade_id == trade_id).limit(1)) is not None
        for model in checks
    )


def _target_score(trade: Trade, union_fill_ids: set[str], has_content: bool) -> tuple[int, int, str]:
    fill_ids = trade_fill_ids(trade)
    exact = int(bool(union_fill_ids) and fill_ids == union_fill_ids)
    return (
        int(has_content) * 1000 + exact * 500 + PREFERRED_SOURCE_QUALITY.get(trade.source_quality, 0),
        len(fill_ids),
        str(trade.id),
    )


def _move_safe_relations(db: Session, target: Trade, duplicate: Trade) -> None:
    for fill in db.scalars(select(Fill).where(Fill.trade_id == duplicate.id)).all():
        fill.trade_id = target.id
    for capture in db.scalars(
        select(CaptureEvent).where(CaptureEvent.matched_trade_id == duplicate.id)
    ).all():
        capture.matched_trade_id = target.id


def _fees_for_lifecycle(lifecycle: PersistedLifecycle) -> Decimal | None:
    allocated: list[Decimal | None] = []
    for item in lifecycle.slices:
        if item.fill.commission is None or Decimal(item.fill.quantity) <= 0:
            allocated.append(None)
        else:
            allocated.append(
                Decimal(item.fill.commission) * item.quantity / Decimal(item.fill.quantity)
            )
    if not allocated or any(value is None for value in allocated):
        return None
    return sum((value or Decimal("0") for value in allocated), Decimal("0"))


def _repair_group(
    db: Session,
    group: list[Trade],
    *,
    lifecycle: PersistedLifecycle | None,
) -> tuple[int, dict[str, Any] | None]:
    if len(group) <= 1:
        return 0, None
    content_rows = [row for row in group if _has_user_content(db, row.id)]
    if len(content_rows) > 1:
        return 0, {
            "trade_ids": [str(item.id) for item in group],
            "reason": "multiple_duplicate_rows_have_user_content",
        }

    union_ids: set[str] = set()
    for row in group:
        union_ids.update(trade_fill_ids(row))
    if lifecycle is not None:
        union_ids.update(lifecycle.fill_ids)

    target = max(group, key=lambda row: _target_score(row, union_ids, row in content_rows))
    exact_canonical = bool(union_ids) and trade_fill_ids(target) == union_ids

    if lifecycle is not None and not exact_canonical:
        # Old paired-report rows are lot accounting, not JournalMe trades. The
        # persisted fills provide the authoritative flat-to-flat boundaries.
        target.symbol = lifecycle.symbol
        target.root_symbol = root_symbol(lifecycle.symbol)
        target.side = lifecycle.side
        target.contract_quantity = lifecycle.quantity
        target.entry_price = lifecycle.entry_price
        target.exit_price = lifecycle.exit_price
        target.entry_timestamp = lifecycle.entry_timestamp
        target.exit_timestamp = lifecycle.exit_timestamp
        target.duration_seconds = max(
            0,
            int((_as_utc_naive(lifecycle.exit_timestamp) - _as_utc_naive(lifecycle.entry_timestamp)).total_seconds()),
        )
        component_rows = [
            row
            for row in group
            if trade_fill_ids(row) and trade_fill_ids(row).issubset(lifecycle.fill_ids)
            and row.source_quality not in {"broker_live", "multi_source_reconciled", "ledger_reconciled", "fills_lifecycle"}
        ]
        canonical_financial = next(
            (
                row
                for row in group
                if trade_fill_ids(row) == lifecycle.fill_ids
                or row.source_quality in {"multi_source_reconciled", "ledger_reconciled", "fills_lifecycle"}
            ),
            None,
        )
        target.gross_pnl = (
            Decimal(canonical_financial.gross_pnl)
            if canonical_financial is not None
            else sum((Decimal(row.gross_pnl) for row in component_rows), Decimal("0"))
        )
        target.fees = _fees_for_lifecycle(lifecycle)
        target.net_pnl = target.gross_pnl - target.fees if target.fees is not None else target.gross_pnl
        target.source_quality = "ledger_reconciled"
        target.reconciliation_status = "reconciled" if target.fees is not None else "warning"

    payload = dict(target.source_payload or {})
    payload.update(
        {
            "ledger_canonical": True,
            "ledger_fill_ids": sorted(union_ids),
            "ledger_component_trade_ids": [str(row.id) for row in group],
            "canonical_contract": canonical_contract_key(target.symbol, target.entry_timestamp),
        }
    )
    target.source_payload = payload

    collapsed = 0
    for duplicate in list(group):
        if duplicate.id == target.id:
            continue
        if _has_user_content(db, duplicate.id):
            return collapsed, {
                "trade_ids": [str(item.id) for item in group],
                "reason": "duplicate_user_content_race",
            }
        _move_safe_relations(db, target, duplicate)
        db.delete(duplicate)
        collapsed += 1
    db.flush()
    return collapsed, None


def reconcile_trade_ledger(db: Session, account: TradingAccount) -> dict[str, Any]:
    """Normalize persisted history to one row per flat -> position -> flat lifecycle.

    Orders remain orders; fills remain fills; partial exits remain inside the same
    trade. Existing user-authored review data is never silently merged when more
    than one duplicate row has review content.
    """
    trades = list(
        db.scalars(
            select(Trade).where(Trade.account_id == account.id).order_by(Trade.entry_timestamp)
        ).all()
    )
    before = len(trades)
    active = [row for row in trades if row.source_quality != "manual"]
    fills = list(
        db.scalars(
            select(Fill).where(Fill.account_id == account.id).order_by(Fill.timestamp)
        ).all()
    )
    lifecycles = _reconstruct_fill_lifecycles(fills)
    used_trade_ids: set[UUID] = set()
    collapsed = 0
    repaired_groups = 0
    conflicts: list[dict[str, Any]] = []

    for lifecycle in lifecycles:
        fill_components = [
            trade
            for trade in active
            if trade.id not in used_trade_ids
            and trade_fill_ids(trade)
            and trade_fill_ids(trade).issubset(lifecycle.fill_ids)
        ]
        lifecycle_matches = [
            trade
            for trade in active
            if trade.id not in used_trade_ids
            and _same_lifecycle_values(
                trade,
                symbol=lifecycle.symbol,
                side=lifecycle.side,
                quantity=lifecycle.quantity,
                entry_price=lifecycle.entry_price,
                exit_price=lifecycle.exit_price,
                entry_timestamp=lifecycle.entry_timestamp,
                exit_timestamp=lifecycle.exit_timestamp,
            )
        ]
        group = list({trade.id: trade for trade in [*fill_components, *lifecycle_matches]}.values())
        if not group:
            continue
        used_trade_ids.update(trade.id for trade in group)
        if len(group) > 1 or not any(trade_fill_ids(row) == lifecycle.fill_ids for row in group):
            count, conflict = _repair_group(db, group, lifecycle=lifecycle)
            collapsed += count
            repaired_groups += int(count > 0)
            if conflict:
                conflicts.append(conflict)

    # Catch duplicate live/import rows that are identical but have different
    # source execution IDs and no imported fill evidence yet.
    remaining = [
        trade
        for trade in active
        if trade.id not in used_trade_ids and db.get(Trade, trade.id) is not None
    ]
    seen: set[UUID] = set()
    for trade in remaining:
        if trade.id in seen:
            continue
        group = [trade]
        for other in remaining:
            if other.id == trade.id or other.id in seen:
                continue
            if _same_lifecycle_trade(trade, other):
                group.append(other)
        seen.update(item.id for item in group)
        if len(group) > 1:
            count, conflict = _repair_group(db, group, lifecycle=None)
            collapsed += count
            repaired_groups += int(count > 0)
            if conflict:
                conflicts.append(conflict)

    remaining_ids = list(db.scalars(select(Trade.id).where(Trade.account_id == account.id)).all())
    return {
        "account_id": str(account.id),
        "before_trade_rows": before,
        "after_trade_rows": len(remaining_ids),
        "collapsed_trade_rows": collapsed,
        "repaired_groups": repaired_groups,
        "fill_lifecycles": len(lifecycles),
        "conflicts": conflicts,
        "status": "needs_attention" if conflicts else "reconciled",
    }


def trading_activity_summary(
    db: Session,
    account: TradingAccount,
    *,
    start_at: datetime,
    end_at: datetime,
    trades: list[Trade],
) -> dict[str, Any]:
    orders = list(
        db.scalars(
            select(Order).where(
                Order.account_id == account.id,
                Order.submitted_timestamp.is_not(None),
                Order.submitted_timestamp >= start_at,
                Order.submitted_timestamp <= end_at,
            )
        ).all()
    )
    fills = list(
        db.scalars(
            select(Fill).where(
                Fill.account_id == account.id,
                Fill.timestamp >= start_at,
                Fill.timestamp <= end_at,
            )
        ).all()
    )
    statuses: dict[str, int] = defaultdict(int)
    for order in orders:
        statuses[(order.status or "unknown").strip().casefold()] += 1
    fees_known = bool(fills) and all(fill.commission is not None for fill in fills)
    fees = (
        sum((Decimal(fill.commission or 0) for fill in fills), Decimal("0"))
        if fees_known
        else None
    )
    gross = sum((Decimal(trade.gross_pnl) for trade in trades), Decimal("0"))
    net = sum((Decimal(trade.net_pnl) for trade in trades), Decimal("0"))
    return {
        "completed_trades": len(trades),
        "orders_submitted": len(orders),
        "orders_filled": statuses.get("filled", 0),
        "orders_canceled": statuses.get("canceled", 0) + statuses.get("cancelled", 0),
        "orders_rejected": statuses.get("rejected", 0),
        "orders_other": sum(
            count
            for status, count in statuses.items()
            if status not in {"filled", "canceled", "cancelled", "rejected"}
        ),
        "fill_count": len(fills),
        "contracts_executed": str(sum((Decimal(fill.quantity) for fill in fills), Decimal("0"))),
        "fees_paid": str(fees) if fees is not None else None,
        "gross_pnl": str(gross),
        "net_pnl": str(net),
        "fees_complete": fees_known,
    }
