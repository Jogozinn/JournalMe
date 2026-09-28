from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Iterable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain import TradeSide
from app.models import BrokerConnection, BrokerExecutionEvent, Trade
from app.services.capture_matching import reconcile_unmatched_captures


@dataclass(frozen=True)
class ExecutionSlice:
    event: BrokerExecutionEvent
    quantity: Decimal
    role: str  # "open" or "close"


@dataclass(frozen=True)
class CompletedRoundTrip:
    slices: tuple[ExecutionSlice, ...]
    symbol: str
    side: TradeSide
    quantity: Decimal
    entry_price: Decimal
    exit_price: Decimal
    gross_pnl: Decimal
    fees: Decimal | None
    net_pnl: Decimal
    entry_timestamp: datetime
    exit_timestamp: datetime
    point_value: Decimal
    currency: str


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _root_symbol(symbol: str) -> str:
    compact = symbol.replace(" ", "").upper()
    # NinjaTrader typically emits symbols like "MNQ 12-26" while imports may use MNQZ26.
    if match := re.match(r"^([A-Z0-9]+?)(?:\d{2}-\d{2})$", compact):
        return match.group(1)
    return re.sub(r"[FGHJKMNQUVXZ]\d{1,2}$", "", compact) or compact


def _side_sign(side: str) -> int:
    normalized = side.lower()
    if normalized in {"buy", "long"}:
        return 1
    if normalized in {"sell", "short"}:
        return -1
    raise ValueError(f"Unsupported execution side: {side}")


def _weighted_price(slices: Iterable[ExecutionSlice], role: str) -> Decimal:
    selected = [item for item in slices if item.role == role]
    quantity = sum((item.quantity for item in selected), Decimal("0"))
    if quantity <= 0:
        return Decimal("0")
    return sum((item.quantity * item.event.price for item in selected), Decimal("0")) / quantity


def _allocated_commission(event: BrokerExecutionEvent, quantity: Decimal) -> Decimal | None:
    if event.commission is None or event.quantity <= 0:
        return None
    return event.commission * quantity / event.quantity


def reconstruct_round_trips(events: list[BrokerExecutionEvent]) -> list[CompletedRoundTrip]:
    """Reconstruct flat-to-flat trades, including partial exits and position reversals."""
    ordered = sorted(events, key=lambda item: (_as_utc(item.executed_at), item.created_at, str(item.id)))
    completed: list[CompletedRoundTrip] = []
    position = Decimal("0")
    active_side = 0
    active_slices: list[ExecutionSlice] = []
    realized = Decimal("0")
    lots: list[list[object]] = []  # [qty, price, event]
    active_point_value: Decimal | None = None
    active_currency = "USD"

    def finalize() -> None:
        nonlocal active_slices, realized, lots, active_side, active_point_value, active_currency
        if not active_slices or active_point_value is None:
            active_slices = []
            realized = Decimal("0")
            lots = []
            active_side = 0
            active_point_value = None
            active_currency = "USD"
            return
        open_slices = [item for item in active_slices if item.role == "open"]
        close_slices = [item for item in active_slices if item.role == "close"]
        opened = sum((item.quantity for item in open_slices), Decimal("0"))
        closed = sum((item.quantity for item in close_slices), Decimal("0"))
        if opened <= 0 or closed <= 0 or opened != closed:
            return
        commissions = [_allocated_commission(item.event, item.quantity) for item in active_slices]
        fees = (
            sum((value or Decimal("0") for value in commissions), Decimal("0"))
            if all(value is not None for value in commissions)
            else None
        )
        entry_ts = min(_as_utc(item.event.executed_at) for item in open_slices)
        exit_ts = max(_as_utc(item.event.executed_at) for item in close_slices)
        trade_side = TradeSide.LONG if _side_sign(open_slices[0].event.side) > 0 else TradeSide.SHORT
        completed.append(
            CompletedRoundTrip(
                slices=tuple(active_slices),
                symbol=open_slices[0].event.symbol,
                side=trade_side,
                quantity=opened,
                entry_price=_weighted_price(active_slices, "open"),
                exit_price=_weighted_price(active_slices, "close"),
                gross_pnl=realized,
                fees=fees,
                net_pnl=realized - fees if fees is not None else realized,
                entry_timestamp=entry_ts,
                exit_timestamp=exit_ts,
                point_value=active_point_value,
                currency=active_currency,
            )
        )
        active_slices = []
        realized = Decimal("0")
        lots = []
        active_side = 0
        active_point_value = None
        active_currency = "USD"

    for event in ordered:
        qty_remaining = Decimal(event.quantity)
        event_side = _side_sign(event.side)
        point_value = Decimal(event.point_value) if event.point_value is not None else None
        while qty_remaining > 0:
            if position == 0:
                active_side = event_side
                active_point_value = point_value
                active_currency = event.currency or "USD"
                lots = [[qty_remaining, Decimal(event.price), event]]
                active_slices.append(ExecutionSlice(event, qty_remaining, "open"))
                position = Decimal(event_side) * qty_remaining
                qty_remaining = Decimal("0")
                continue

            position_side = 1 if position > 0 else -1
            if event_side == position_side:
                if point_value is not None and active_point_value is None:
                    active_point_value = point_value
                lots.append([qty_remaining, Decimal(event.price), event])
                active_slices.append(ExecutionSlice(event, qty_remaining, "open"))
                position += Decimal(event_side) * qty_remaining
                qty_remaining = Decimal("0")
                continue

            close_qty = min(abs(position), qty_remaining)
            active_slices.append(ExecutionSlice(event, close_qty, "close"))
            to_match = close_qty
            while to_match > 0 and lots:
                lot_qty = Decimal(lots[0][0])
                lot_price = Decimal(lots[0][1])
                matched = min(lot_qty, to_match)
                pv = active_point_value or point_value
                if pv is None:
                    return completed
                if position_side > 0:
                    realized += (Decimal(event.price) - lot_price) * matched * pv
                else:
                    realized += (lot_price - Decimal(event.price)) * matched * pv
                lot_qty -= matched
                to_match -= matched
                if lot_qty == 0:
                    lots.pop(0)
                else:
                    lots[0][0] = lot_qty

            position += Decimal(event_side) * close_qty
            qty_remaining -= close_qty
            if position == 0:
                finalize()
                # If the same execution reverses beyond flat, the remaining quantity opens a new trade.
                continue

    return completed


def _fingerprint(connection: BrokerConnection, trip: CompletedRoundTrip) -> str:
    parts = []
    for item in trip.slices:
        parts.append(
            f"{item.event.external_execution_id}:{item.role}:{item.quantity.normalize()}"
        )
    source = f"broker-live|{connection.id}|" + "|".join(parts)
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def materialize_closed_trades(
    db: Session,
    connection: BrokerConnection,
    *,
    symbol: str | None = None,
) -> list[Trade]:
    if connection.account_id is None:
        return []
    statement = select(BrokerExecutionEvent).where(
        BrokerExecutionEvent.connection_id == connection.id,
        BrokerExecutionEvent.account_id == connection.account_id,
    )
    if symbol:
        statement = statement.where(BrokerExecutionEvent.symbol == symbol)
    events = list(db.scalars(statement.order_by(BrokerExecutionEvent.executed_at, BrokerExecutionEvent.created_at)).all())
    if not events:
        return []

    by_symbol: dict[str, list[BrokerExecutionEvent]] = {}
    for event in events:
        by_symbol.setdefault(event.symbol, []).append(event)

    created: list[Trade] = []
    used_event_ids: set[UUID] = set()
    for symbol_events in by_symbol.values():
        for trip in reconstruct_round_trips(symbol_events):
            fingerprint = _fingerprint(connection, trip)
            existing = db.scalar(
                select(Trade).where(
                    Trade.account_id == connection.account_id,
                    Trade.duplicate_fingerprint == fingerprint,
                )
            )
            if existing is not None:
                used_event_ids.update(item.event.id for item in trip.slices)
                continue
            buy_ids = sorted({item.event.external_execution_id for item in trip.slices if _side_sign(item.event.side) > 0})
            sell_ids = sorted({item.event.external_execution_id for item in trip.slices if _side_sign(item.event.side) < 0})
            warnings = [] if trip.fees is not None else ["Commission/fees were unavailable from the live broker event and remain unreconciled."]
            trade = Trade(
                account_id=connection.account_id,
                primary_import_session_id=None,
                external_position_id=None,
                external_pair_id=f"broker:{connection.id}:{fingerprint[:16]}",
                external_buy_fill_id=",".join(buy_ids) or None,
                external_sell_fill_id=",".join(sell_ids) or None,
                duplicate_fingerprint=fingerprint,
                symbol=trip.symbol,
                root_symbol=_root_symbol(trip.symbol),
                product=None,
                product_description=None,
                contract_quantity=trip.quantity,
                side=trip.side,
                entry_price=trip.entry_price,
                exit_price=trip.exit_price,
                gross_pnl=trip.gross_pnl,
                fees=trip.fees,
                net_pnl=trip.net_pnl,
                currency=trip.currency,
                entry_timestamp=trip.entry_timestamp,
                exit_timestamp=trip.exit_timestamp,
                duration_seconds=max(0, int((trip.exit_timestamp - trip.entry_timestamp).total_seconds())),
                tick_size=None,
                source_quality="broker_live",
                reconciliation_status="reconciled" if trip.fees is not None else "live_fees_pending",
                source_payload={
                    "source": "broker_live",
                    "provider": connection.provider,
                    "connection_id": str(connection.id),
                    "execution_ids": sorted({item.event.external_execution_id for item in trip.slices}),
                    "point_value": str(trip.point_value),
                    "warnings": warnings,
                },
            )
            db.add(trade)
            db.flush()
            created.append(trade)
            used_event_ids.update(item.event.id for item in trip.slices)

    if used_event_ids:
        for event in events:
            if event.id in used_event_ids:
                event.ingest_status = "materialized"
    if created:
        reconcile_unmatched_captures(db, connection.user_id, account_id=connection.account_id)
    return created
