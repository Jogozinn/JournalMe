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
    BrokerExecutionEvent,
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
    TradingEpisode,
)
from app.services.instrument_identity import canonical_contract_key, root_symbol
from app.services.broker_ingestion import reconstruct_round_trips


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


def _payload_ids(payload: dict[str, Any], keys: tuple[str, ...]) -> set[str]:
    ids: set[str] = set()
    for key in keys:
        values = payload.get(key)
        if isinstance(values, list):
            ids.update(str(value) for value in values if value)
        elif isinstance(values, str) and values.strip():
            ids.update(_split_ids(values))
    return ids


def trade_import_fill_ids(trade: Trade) -> set[str]:
    """Tradovate/import fill identifiers only.

    NinjaTrader execution IDs live in a different namespace and must never be
    compared directly with Tradovate fill IDs.
    """
    ids = _split_ids(trade.external_buy_fill_id) | _split_ids(trade.external_sell_fill_id)
    payload = trade.source_payload or {}
    ids.update(_payload_ids(payload, ("fill_ids", "ledger_fill_ids")))
    tradovate = payload.get("tradovate_reconciliation")
    if isinstance(tradovate, dict):
        ids.update(_payload_ids(tradovate, ("fill_ids", "ledger_fill_ids")))
    # Older payloads can preserve raw performance rows instead of a top-level
    # fill_ids list. Recover those IDs without depending on a historical schema.
    paired_rows = payload.get("paired_rows")
    if isinstance(paired_rows, list):
        for row in paired_rows:
            if not isinstance(row, dict):
                continue
            for key in ("buyFillId", "sellFillId", "Buy Fill ID", "Sell Fill ID", "fillId", "Fill ID"):
                value = row.get(key)
                if value:
                    ids.add(str(value))
    return ids


def trade_execution_ids(trade: Trade) -> set[str]:
    """Live broker execution IDs only."""
    payload = trade.source_payload or {}
    ids = _payload_ids(payload, ("execution_ids", "broker_execution_ids"))
    final_id = payload.get("final_execution_id")
    if final_id:
        ids.add(str(final_id))
    return ids


def trade_fill_ids(trade: Trade) -> set[str]:
    # Backward-compatible union for diagnostics/scoring only. Reconciliation
    # itself uses source-specific ID namespaces.
    return trade_import_fill_ids(trade) | trade_execution_ids(trade)


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


def _live_round_trips(db: Session, account: TradingAccount) -> list[Any]:
    events = list(
        db.scalars(
            select(BrokerExecutionEvent)
            .where(BrokerExecutionEvent.account_id == account.id)
            .order_by(BrokerExecutionEvent.executed_at, BrokerExecutionEvent.created_at)
        ).all()
    )
    grouped: dict[tuple[UUID, str], list[BrokerExecutionEvent]] = defaultdict(list)
    for event in events:
        grouped[(event.connection_id, canonical_contract_key(event.symbol, event.executed_at))].append(event)
    trips: list[Any] = []
    for grouped_events in grouped.values():
        trips.extend(reconstruct_round_trips(grouped_events))
    return sorted(trips, key=lambda item: item.entry_timestamp)


def _trip_execution_ids(trip: Any) -> set[str]:
    return {str(item.event.external_execution_id) for item in trip.slices if item.event.external_execution_id}


def _repair_live_group(
    db: Session, group: list[Trade], trip: Any
) -> tuple[int, dict[str, Any] | None, Trade | None]:
    if not group:
        return 0, None, None
    content_rows = [row for row in group if _has_user_content(db, row.id)]
    if len(content_rows) > 1:
        return 0, {
            "trade_ids": [str(item.id) for item in group],
            "reason": "multiple_live_duplicate_rows_have_user_content",
        }, None
    execution_ids = _trip_execution_ids(trip)
    target = max(
        group,
        key=lambda row: (
            int(row in content_rows) * 1000
            + int(trade_execution_ids(row) == execution_ids) * 500
            + PREFERRED_SOURCE_QUALITY.get(row.source_quality, 0),
            len(trade_execution_ids(row)),
            str(row.id),
        ),
    )
    target.symbol = trip.symbol
    target.root_symbol = root_symbol(trip.symbol)
    target.side = trip.side
    target.contract_quantity = trip.quantity
    target.entry_price = trip.entry_price
    target.exit_price = trip.exit_price
    target.entry_timestamp = trip.entry_timestamp
    target.exit_timestamp = trip.exit_timestamp
    target.duration_seconds = max(0, int((trip.exit_timestamp - trip.entry_timestamp).total_seconds()))
    target.gross_pnl = trip.gross_pnl
    target.fees = trip.fees
    target.net_pnl = trip.net_pnl
    target.currency = trip.currency
    target.source_quality = "broker_live"
    target.reconciliation_status = "reconciled" if trip.fees is not None else "live_fees_pending"
    payload = dict(target.source_payload or {})
    payload.update({
        "source": "broker_live",
        "execution_ids": sorted(execution_ids),
        "ledger_canonical": True,
        "canonical_contract": canonical_contract_key(trip.symbol, trip.entry_timestamp),
        "point_value": str(trip.point_value),
        "ledger_component_trade_ids": [str(row.id) for row in group],
    })
    target.source_payload = payload
    collapsed = 0
    for duplicate in list(group):
        if duplicate.id == target.id:
            continue
        if _has_user_content(db, duplicate.id):
            return collapsed, {
                "trade_ids": [str(item.id) for item in group],
                "reason": "live_duplicate_user_content_race",
            }, target
        _move_safe_relations(db, target, duplicate)
        db.delete(duplicate)
        collapsed += 1
    db.flush()
    return collapsed, None, target


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


def _target_score(
    trade: Trade, union_fill_ids: set[str], has_content: bool, *, import_only: bool = False
) -> tuple[int, int, str]:
    fill_ids = trade_import_fill_ids(trade) if import_only else trade_fill_ids(trade)
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
    for episode in db.scalars(
        select(TradingEpisode).where(TradingEpisode.matched_trade_id == duplicate.id)
    ).all():
        episode.matched_trade_id = target.id


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
) -> tuple[int, dict[str, Any] | None, Trade | None]:
    if not group:
        return 0, None, None
    content_rows = [row for row in group if _has_user_content(db, row.id)]
    if len(content_rows) > 1:
        return 0, {
            "trade_ids": [str(item.id) for item in group],
            "reason": "multiple_duplicate_rows_have_user_content",
        }, None

    union_ids: set[str] = set()
    if lifecycle is not None:
        # This repair pass is anchored to Tradovate/import fills. Keep live
        # execution IDs out of the imported fill namespace.
        for row in group:
            union_ids.update(trade_import_fill_ids(row))
        union_ids.update(lifecycle.fill_ids)
    else:
        for row in group:
            union_ids.update(trade_fill_ids(row))

    target = max(
        group,
        key=lambda row: _target_score(
            row, union_ids, row in content_rows, import_only=lifecycle is not None
        ),
    )
    if lifecycle is not None:
        # Old paired-report rows are lot accounting, not JournalMe trades. The
        # persisted fills provide the authoritative flat-to-flat boundaries.
        # If this row came from the live broker bridge, keep its user-facing
        # contract notation (for example, MNQ 12-26) while using canonical
        # contract identity to reconcile it with an imported symbol like MNQZ6.
        had_live_source = target.source_quality in {"broker_live", "multi_source_reconciled"}
        preserve_live_symbol = had_live_source and bool(target.symbol)
        if not preserve_live_symbol:
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
            if trade_import_fill_ids(row) and trade_import_fill_ids(row).issubset(lifecycle.fill_ids)
            and row.source_quality not in {"broker_live", "multi_source_reconciled", "ledger_reconciled", "fills_lifecycle"}
        ]
        canonical_financial = next(
            (
                row
                for row in group
                if trade_import_fill_ids(row) == lifecycle.fill_ids
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
        target.source_quality = "multi_source_reconciled" if had_live_source else "ledger_reconciled"
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
            }, target
        _move_safe_relations(db, target, duplicate)
        db.delete(duplicate)
        collapsed += 1
    db.flush()
    return collapsed, None, target


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

    # First normalize the live-broker namespace from the raw execution stream.
    # A NinjaTrader execution ID is not a Tradovate fill ID; treating them as the
    # same namespace was the reason old live partial/position rows survived the
    # first repair pass.
    live_trips = _live_round_trips(db, account)
    for trip in live_trips:
        execution_ids = _trip_execution_ids(trip)
        group = [
            trade for trade in active
            if trade.id not in used_trade_ids
            and trade_execution_ids(trade)
            and trade_execution_ids(trade).issubset(execution_ids)
        ]
        if not group:
            group = [
                trade for trade in active
                if trade.id not in used_trade_ids
                and trade.source_quality == "broker_live"
                and _same_lifecycle_values(
                    trade,
                    symbol=trip.symbol,
                    side=trip.side,
                    quantity=trip.quantity,
                    entry_price=trip.entry_price,
                    exit_price=trip.exit_price,
                    entry_timestamp=trip.entry_timestamp,
                    exit_timestamp=trip.exit_timestamp,
                )
            ]
        if not group:
            continue
        used_trade_ids.update(trade.id for trade in group)
        count, conflict, _target = _repair_live_group(db, group, trip)
        collapsed += count
        repaired_groups += int(count > 0 or len(group) == 1)
        if conflict:
            conflicts.append(conflict)

    # Remove deleted ORM objects from the in-memory candidate list before the
    # import-source pass. A live canonical row is allowed to participate again
    # so Tradovate can enrich it with fees.
    active = [row for row in active if db.get(Trade, row.id) is not None]
    used_trade_ids.clear()
    authoritative_import_trade_ids: set[UUID] = set()
    for lifecycle in lifecycles:
        fill_components = [
            trade
            for trade in active
            if trade.id not in used_trade_ids
            and trade_import_fill_ids(trade)
            and trade_import_fill_ids(trade).issubset(lifecycle.fill_ids)
        ]
        linked_trade_ids = {
            item.fill.trade_id for item in lifecycle.slices if item.fill.trade_id is not None
        }
        linked_trades = [
            trade for trade in active
            if trade.id not in used_trade_ids and trade.id in linked_trade_ids
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
        group = list({trade.id: trade for trade in [*linked_trades, *fill_components, *lifecycle_matches]}.values())
        if not group:
            conflicts.append({
                "reason": "authoritative_fill_lifecycle_has_no_trade_row",
                "symbol": lifecycle.symbol,
                "entry_timestamp": lifecycle.entry_timestamp.isoformat(),
                "exit_timestamp": lifecycle.exit_timestamp.isoformat(),
                "fill_ids": sorted(lifecycle.fill_ids),
            })
            continue
        used_trade_ids.update(trade.id for trade in group)
        count, conflict, target = _repair_group(db, group, lifecycle=lifecycle)
        collapsed += count
        repaired_groups += int(target is not None)
        if conflict:
            conflicts.append(conflict)
        if target is not None:
            authoritative_import_trade_ids.add(target.id)
            for item in lifecycle.slices:
                item.fill.trade_id = target.id

    # Tradovate fills are authoritative inside the time span they cover. A
    # partial live stream can otherwise invent "phantom" round trips by
    # interpreting a real exit as a new entry and the next real entry as its
    # exit. Suppress those machine-generated rows whenever complete imported
    # fill evidence covers the same contract/time window.
    coverage_by_contract: dict[str, tuple[datetime, datetime]] = {}
    for fill in fills:
        key = canonical_contract_key(fill.symbol, fill.timestamp)
        current = coverage_by_contract.get(key)
        ts = _as_utc_naive(fill.timestamp)
        if current is None:
            coverage_by_contract[key] = (ts, ts)
        else:
            coverage_by_contract[key] = (min(current[0], ts), max(current[1], ts))

    suppressed_by_authoritative_fills = 0
    current_rows = list(db.scalars(select(Trade).where(Trade.account_id == account.id)).all())
    for row in current_rows:
        if row.source_quality == "manual" or row.id in authoritative_import_trade_ids:
            continue
        key = canonical_contract_key(row.symbol, row.entry_timestamp)
        coverage = coverage_by_contract.get(key)
        if coverage is None:
            continue
        start, end = coverage
        entry = _as_utc_naive(row.entry_timestamp)
        exit_at = _as_utc_naive(row.exit_timestamp)
        tolerance_seconds = 5
        inside_authoritative_window = (
            entry.timestamp() >= start.timestamp() - tolerance_seconds
            and exit_at.timestamp() <= end.timestamp() + tolerance_seconds
        )
        if not inside_authoritative_window:
            continue
        if _has_user_content(db, row.id):
            conflicts.append({
                "trade_ids": [str(row.id)],
                "reason": "noncanonical_trade_has_user_content_in_authoritative_fill_window",
            })
            continue
        # Fill links have already been reassigned to the authoritative lifecycle
        # targets above. Preserve capture matching only when there is a unique
        # nearest canonical trade on the same contract.
        canonical_candidates = [
            candidate
            for candidate in current_rows
            if candidate.id in authoritative_import_trade_ids
            and canonical_contract_key(candidate.symbol, candidate.entry_timestamp) == key
        ]
        if canonical_candidates:
            nearest = min(
                canonical_candidates,
                key=lambda candidate: min(
                    abs((_as_utc_naive(candidate.entry_timestamp) - entry).total_seconds()),
                    abs((_as_utc_naive(candidate.exit_timestamp) - exit_at).total_seconds()),
                ),
            )
            for capture in db.scalars(
                select(CaptureEvent).where(CaptureEvent.matched_trade_id == row.id)
            ).all():
                capture.matched_trade_id = nearest.id
            for episode in db.scalars(
                select(TradingEpisode).where(TradingEpisode.matched_trade_id == row.id)
            ).all():
                episode.matched_trade_id = nearest.id
        db.delete(row)
        collapsed += 1
        suppressed_by_authoritative_fills += 1

    db.flush()

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
            count, conflict, _target = _repair_group(db, group, lifecycle=None)
            collapsed += count
            repaired_groups += int(count > 0)
            if conflict:
                conflicts.append(conflict)

    remaining_rows = list(db.scalars(select(Trade).where(Trade.account_id == account.id)).all())
    unresolved_nonmanual = [
        row for row in remaining_rows
        if row.source_quality != "manual"
        and not (row.source_payload or {}).get("ledger_canonical")
        and row.source_quality not in {"multi_source_reconciled", "ledger_reconciled"}
    ]
    return {
        "account_id": str(account.id),
        "before_trade_rows": before,
        "after_trade_rows": len(remaining_rows),
        "collapsed_trade_rows": collapsed,
        "repaired_groups": repaired_groups,
        "fill_lifecycles": len(lifecycles),
        "live_lifecycles": len(live_trips),
        "suppressed_by_authoritative_fills": suppressed_by_authoritative_fills,
        "unresolved_nonmanual_trade_rows": len(unresolved_nonmanual),
        "conflicts": conflicts,
        "status": "needs_attention" if conflicts or unresolved_nonmanual else "reconciled",
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
