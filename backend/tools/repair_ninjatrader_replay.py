from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import Base, SessionLocal
from app.domain import TradeSide
from app.models import BrokerConnection, BrokerExecutionEvent, Trade, TradingAccount
from app.services.broker_ingestion import (
    CompletedRoundTrip,
    _fingerprint,
    _side_sign,
    _trip_allocation_rows,
    materialize_closed_trades,
    reconstruct_round_trips,
)
from app.services.instrument_identity import canonical_contract_key, root_symbol


def _json_value(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, bytes):
        return {"byte_length": len(value)}
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def _trade_summary(trade: Trade) -> dict[str, Any]:
    return {
        "trade_id": str(trade.id),
        "account_id": str(trade.account_id),
        "symbol": trade.symbol,
        "side": trade.side.value if isinstance(trade.side, TradeSide) else str(trade.side),
        "quantity": str(trade.contract_quantity),
        "entry_price": str(trade.entry_price),
        "exit_price": str(trade.exit_price),
        "entry_timestamp": trade.entry_timestamp.isoformat(),
        "exit_timestamp": trade.exit_timestamp.isoformat(),
        "gross_pnl": str(trade.gross_pnl),
        "fees": str(trade.fees) if trade.fees is not None else None,
        "net_pnl": str(trade.net_pnl),
        "fingerprint": trade.duplicate_fingerprint,
        "reconciliation_status": trade.reconciliation_status,
        "accounting_status": trade.accounting_status,
        "source_payload": _json_value(trade.source_payload or {}),
    }


def _allocations(trip: CompletedRoundTrip) -> set[tuple[str, str, Decimal]]:
    return {
        (row["execution_id"], row["role"], Decimal(row["quantity"]))
        for row in _trip_allocation_rows(trip)
    }


def _linked_rows(db: Session, trade_ids: set[UUID]) -> dict[str, list[dict[str, Any]]]:
    """Inventory every FK relationship to a trade, including links added later."""
    linked: dict[str, list[dict[str, Any]]] = {}
    for table in Base.metadata.sorted_tables:
        columns = [
            column
            for column in table.columns
            if any(
                foreign_key.target_fullname == "trades.id" for foreign_key in column.foreign_keys
            )
        ]
        for column in columns:
            rows = db.execute(select(table).where(column.in_(trade_ids))).mappings().all()
            if rows:
                linked.setdefault(table.name, []).extend(_json_value(dict(row)) for row in rows)
    return linked


def _find_plan(
    db: Session,
    account_id: UUID,
    execution_ids: set[str],
    preserve_trade_suffix: str,
    fees_by_execution: dict[str, Decimal],
) -> dict[str, Any]:
    account = db.get(TradingAccount, account_id)
    if account is None:
        raise ValueError("The authorized JournalMe account was not found.")
    events = list(
        db.scalars(
            select(BrokerExecutionEvent)
            .where(
                BrokerExecutionEvent.account_id == account.id,
                BrokerExecutionEvent.user_id == account.user_id,
                BrokerExecutionEvent.external_execution_id.in_(execution_ids),
            )
            .order_by(BrokerExecutionEvent.executed_at, BrokerExecutionEvent.created_at)
            .with_for_update()
        ).all()
    )
    found = {event.external_execution_id for event in events}
    if found != execution_ids:
        raise ValueError(
            f"Execution set mismatch: requested {len(execution_ids)}, found {len(found)}."
        )
    connections = {
        connection.id: connection
        for connection in db.scalars(
            select(BrokerConnection)
            .where(
                BrokerConnection.user_id == account.user_id,
                BrokerConnection.account_id == account.id,
                BrokerConnection.provider == "ninjatrader",
            )
            .with_for_update()
        ).all()
    }
    if any(event.connection_id not in connections for event in events):
        raise ValueError(
            "Every requested execution must belong to this account's authorized NinjaTrader source."
        )
    if len({event.connection_id for event in events}) != 1:
        raise ValueError("The targeted execution set spans multiple source connections.")
    connection = connections[events[0].connection_id]
    if any(
        (event.source_payload or {}).get("ninjatrader_account")
        and str((event.source_payload or {}).get("ninjatrader_account")).casefold()
        != str(connection.source_account_name or connection.external_account_id or "").casefold()
        for event in events
    ):
        raise ValueError(
            "An execution's source account identity does not match its authorized mapping."
        )
    for execution_id in fees_by_execution:
        if execution_id not in execution_ids:
            raise ValueError(
                f"Fee map contains an execution outside the selected set: {execution_id}"
            )

    trips = reconstruct_round_trips(events)
    if not trips:
        raise ValueError("The selected executions do not reconstruct any complete round trips.")
    used_ids = {item.event.external_execution_id for trip in trips for item in trip.slices}
    if used_ids != execution_ids:
        raise ValueError(
            "Selected executions include open, unused, or otherwise unreconstructed fills."
        )

    target_suffix = preserve_trade_suffix.casefold()
    matches = list(
        db.scalars(
            select(Trade)
            .where(
                Trade.account_id == account.id,
                Trade.source_quality == "broker_live",
            )
            .execution_options(include_excluded_accounting=True)
            .with_for_update()
        ).all()
    )
    targets = [
        trade
        for trade in matches
        if str(trade.id).replace("-", "").casefold().endswith(target_suffix)
    ]
    if len(targets) != 1:
        raise ValueError(
            "Preserved trade suffix must identify exactly one broker-live trade in this account."
        )
    target = targets[0]
    target_payload = target.source_payload or {}
    target_allocations = target_payload.get("execution_allocations")
    if not isinstance(target_allocations, list):
        raise ValueError(
            "Target trade has no auditable execution allocations; manual review is required."
        )
    target_open_ids = {
        str(row.get("execution_id"))
        for row in target_allocations
        if isinstance(row, dict) and row.get("role") == "open"
    }
    if not target_open_ids:
        raise ValueError("Target trade does not have a provable opening execution allocation.")
    target_candidates = [
        trip
        for trip in trips
        if trip.side == target.side
        and _as_utc(trip.entry_timestamp) == _as_utc(target.entry_timestamp)
        and target_open_ids.issubset(
            {item.event.external_execution_id for item in trip.slices if item.role == "open"}
        )
    ]
    if len(target_candidates) != 1:
        raise ValueError(
            "Target trade identity does not map unambiguously to one reconstructed trip."
        )
    target_trip = target_candidates[0]

    affected_trades = []
    for trade in matches:
        payload = trade.source_payload or {}
        if payload.get("connection_id") != str(connection.id):
            continue
        linked_ids = set(payload.get("execution_ids") or [])
        if not linked_ids.intersection(execution_ids):
            continue
        if trade.id == target.id:
            affected_trades.append(trade)
            continue
        allocation_rows = payload.get("execution_allocations")
        if not isinstance(allocation_rows, list):
            raise ValueError(f"Overlapping trade {trade.id} has unauditable allocations.")
        normalized = set()
        try:
            normalized = {
                (
                    str(row["execution_id"]),
                    str(row["role"]),
                    Decimal(str(row["quantity"])),
                )
                for row in allocation_rows
            }
        except (KeyError, TypeError, ValueError):
            raise ValueError(
                f"Overlapping trade {trade.id} has invalid allocations."
            ) from None
        if not any(normalized == _allocations(trip) for trip in trips):
            raise ValueError(f"Overlapping trade {trade.id} conflicts with the verified replay.")
        affected_trades.append(trade)

    already_correct = {
        trade.duplicate_fingerprint: trade
        for trade in matches
        if trade.id != target.id and trade.source_payload.get("connection_id") == str(connection.id)
    }
    trip_plan = []
    for trip in trips:
        fingerprint = _fingerprint(connection, trip)
        fee_total = sum(
            (
                fees_by_execution.get(
                    item.event.external_execution_id,
                    item.event.commission or Decimal("0"),
                )
                * item.quantity
                / Decimal(item.event.quantity)
                for item in trip.slices
            ),
            Decimal("0"),
        )
        all_fees_known = all(
            item.event.external_execution_id in fees_by_execution
            or item.event.commission is not None
            for item in trip.slices
        )
        existing = target if trip is target_trip else already_correct.get(fingerprint)
        trip_plan.append(
            {
                "trade_id": str(existing.id) if existing else None,
                "preserves_original_id": bool(existing and existing.id == target.id),
                "action": "correct"
                if existing and existing.id == target.id
                else "preserve"
                if existing
                else "create",
                "fingerprint": fingerprint,
                "symbol": trip.symbol,
                "side": trip.side.value,
                "quantity": str(trip.quantity),
                "entry_price": str(trip.entry_price),
                "exit_price": str(trip.exit_price),
                "entry_timestamp": trip.entry_timestamp.isoformat(),
                "exit_timestamp": trip.exit_timestamp.isoformat(),
                "gross_pnl": str(trip.gross_pnl),
                "fees": str(fee_total) if all_fees_known else None,
                "net_pnl": str(trip.gross_pnl - fee_total) if all_fees_known else None,
                "execution_allocations": _trip_allocation_rows(trip),
                "execution_ids": sorted({item.event.external_execution_id for item in trip.slices}),
            }
        )
    return {
        "account": {
            "account_id": str(account.id),
            "name": account.name,
            "external_account_id": account.external_account_id,
            "account_type": account.account_type.value,
        },
        "connection_id": str(connection.id),
        "execution_count": len(events),
        "execution_ids": sorted(execution_ids),
        "before": [_trade_summary(trade) for trade in affected_trades],
        "relationships": _linked_rows(db, {trade.id for trade in affected_trades}),
        "after": trip_plan,
        "totals": {
            "gross_pnl": str(sum((trip.gross_pnl for trip in trips), Decimal("0"))),
            "fees": (
                str(sum((Decimal(item["fees"]) for item in trip_plan), Decimal("0")))
                if all(item["fees"] is not None for item in trip_plan)
                else None
            ),
            "net_pnl": (
                str(sum((Decimal(item["net_pnl"]) for item in trip_plan), Decimal("0")))
                if all(item["net_pnl"] is not None for item in trip_plan)
                else None
            ),
        },
        "_target": target,
        "_target_trip": target_trip,
        "_connection": connection,
        "_trips": trips,
        "_events": events,
    }


def _as_utc(value: datetime) -> datetime:
    return (
        value.replace(tzinfo=timezone.utc)
        if value.tzinfo is None
        else value.astimezone(timezone.utc)
    )


def _update_target(
    db: Session,
    plan: dict[str, Any],
    fees_by_execution: dict[str, Decimal],
    fee_source: str | None,
) -> list[Trade]:
    target: Trade = plan["_target"]
    trip: CompletedRoundTrip = plan["_target_trip"]
    connection: BrokerConnection = plan["_connection"]
    old_values = _trade_summary(target)
    fingerprint = _fingerprint(connection, trip)
    buy_ids = sorted(
        {
            item.event.external_execution_id
            for item in trip.slices
            if _side_sign(item.event.side) > 0
        }
    )
    sell_ids = sorted(
        {
            item.event.external_execution_id
            for item in trip.slices
            if _side_sign(item.event.side) < 0
        }
    )
    fees_known = all(
        item.event.external_execution_id in fees_by_execution or item.event.commission is not None
        for item in trip.slices
    )
    fee_total = sum(
        (
            fees_by_execution.get(
                item.event.external_execution_id, item.event.commission or Decimal("0")
            )
            * item.quantity
            / Decimal(item.event.quantity)
            for item in trip.slices
        ),
        Decimal("0"),
    )
    payload = {
        **(target.source_payload or {}),
        "source": "broker_live",
        "provider": connection.provider,
        "connection_id": str(connection.id),
        "source_namespace": connection.source_namespace,
        "source_account_name": connection.source_account_name,
        "execution_ids": sorted({item.event.external_execution_id for item in trip.slices}),
        "execution_allocations": _trip_allocation_rows(trip),
        "final_execution_id": max(
            trip.slices,
            key=lambda item: (
                _as_utc(item.event.executed_at),
                item.event.created_at,
                str(item.event.id),
            ),
        ).event.external_execution_id,
        "canonical_contract": canonical_contract_key(trip.symbol, trip.entry_timestamp),
        "point_value": str(trip.point_value),
        "warnings": [] if fees_known else ["Broker commissions remain unreconciled."],
        "repair_history": [
            *(target.source_payload or {}).get("repair_history", []),
            {
                "repaired_at": datetime.now(timezone.utc).isoformat(),
                "method": "verified_execution_replay",
                "execution_ids": sorted({item.event.external_execution_id for item in trip.slices}),
                "before": old_values,
                "fee_source": fee_source if fees_by_execution else None,
            },
        ],
    }
    target.duplicate_fingerprint = fingerprint
    target.symbol = trip.symbol
    target.root_symbol = root_symbol(trip.symbol)
    target.contract_quantity = trip.quantity
    target.side = trip.side
    target.entry_price = trip.entry_price
    target.exit_price = trip.exit_price
    target.gross_pnl = trip.gross_pnl
    target.fees = fee_total if fees_known else None
    target.net_pnl = trip.gross_pnl - fee_total if fees_known else trip.gross_pnl
    target.currency = trip.currency
    target.entry_timestamp = trip.entry_timestamp
    target.exit_timestamp = trip.exit_timestamp
    target.duration_seconds = max(
        0, int((trip.exit_timestamp - trip.entry_timestamp).total_seconds())
    )
    target.reconciliation_status = "reconciled" if fees_known else "live_fees_pending"
    target.source_payload = payload
    target.external_buy_fill_id = ",".join(buy_ids) or None
    target.external_sell_fill_id = ",".join(sell_ids) or None
    db.flush()
    created = materialize_closed_trades(
        db,
        connection,
        symbol=trip.symbol,
        execution_ids=set(plan["execution_ids"]),
    )
    expected_fingerprints = {_fingerprint(connection, item) for item in plan["_trips"]}
    canonical_trades = list(
        db.scalars(
            select(Trade)
            .where(
                Trade.account_id == target.account_id,
                Trade.duplicate_fingerprint.in_(expected_fingerprints),
            )
            .execution_options(include_excluded_accounting=True)
        ).all()
    )
    events_by_id = {event.external_execution_id: event for event in plan["_events"]}
    for trade in canonical_trades:
        trade.source_payload = {
            **trade.source_payload,
            "verified_replay_repair": {
                "repaired_at": datetime.now(timezone.utc).isoformat(),
                "execution_ids": sorted(plan["execution_ids"]),
                "preserved_trade_id": str(target.id),
            },
        }
        allocations = trade.source_payload.get("execution_allocations") or []
        fee_values = []
        fee_ids = set()
        fees_complete = True
        for row in allocations:
            execution_id = row["execution_id"]
            event = events_by_id[execution_id]
            commission = fees_by_execution.get(execution_id, event.commission)
            if commission is None:
                fees_complete = False
                break
            fee_values.append(
                Decimal(str(commission)) * Decimal(str(row["quantity"])) / Decimal(event.quantity)
            )
            if execution_id in fees_by_execution:
                fee_ids.add(execution_id)
        if fees_complete:
            trade.fees = sum(fee_values, Decimal("0"))
            trade.net_pnl = trade.gross_pnl - trade.fees
            trade.reconciliation_status = "reconciled"
            if fee_ids:
                trade.source_payload = {
                    **trade.source_payload,
                    "fee_reconciliation": {
                        "source": fee_source,
                        "execution_ids": sorted(fee_ids),
                    },
                }
    db.flush()
    return [target, *created]


def _parse_fee_map(path: Path | None) -> tuple[dict[str, Decimal], str | None]:
    if path is None:
        return {}, None
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not isinstance(raw.get("fees_by_execution"), dict):
        raise ValueError("Fee map JSON must contain a fees_by_execution object.")
    return {str(key): Decimal(str(value)) for key, value in raw["fees_by_execution"].items()}, str(
        raw.get("source") or path.name
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Preview or transactionally repair one NinjaTrader replay."
    )
    parser.add_argument("--account-id", required=True, type=UUID)
    parser.add_argument("--execution-id", required=True, action="append")
    parser.add_argument("--preserve-trade-suffix", required=True)
    parser.add_argument("--fees-json", type=Path)
    parser.add_argument(
        "--apply", action="store_true", help="Apply after a second transactional validation."
    )
    parser.add_argument(
        "--confirm-account-id", help="Must exactly match --account-id with --apply."
    )
    args = parser.parse_args()
    ids = set(args.execution_id)
    if len(ids) != len(args.execution_id):
        parser.error("Execution IDs must be unique.")
    fee_map, fee_source = _parse_fee_map(args.fees_json)
    if args.apply and args.confirm_account_id != str(args.account_id):
        parser.error("--apply requires --confirm-account-id equal to the full account UUID.")

    db: Session = SessionLocal()
    try:
        plan = _find_plan(db, args.account_id, ids, args.preserve_trade_suffix, fee_map)
        output = {key: value for key, value in plan.items() if not key.startswith("_")}
        output["mode"] = "apply" if args.apply else "dry_run"
        print(json.dumps(output, indent=2, default=_json_value))
        if not args.apply:
            db.rollback()
            return 0

        db.rollback()
        with db.begin():
            # Lock the account row so two repairs cannot race on the same ledger.
            db.scalar(
                select(TradingAccount).where(TradingAccount.id == args.account_id).with_for_update()
            )
            plan = _find_plan(db, args.account_id, ids, args.preserve_trade_suffix, fee_map)
            changed = _update_target(db, plan, fee_map, fee_source)
            expected_fingerprints = {
                _fingerprint(plan["_connection"], trip) for trip in plan["_trips"]
            }
            materialized = list(
                db.scalars(
                    select(Trade)
                    .where(
                        Trade.account_id == args.account_id,
                        Trade.duplicate_fingerprint.in_(expected_fingerprints),
                    )
                    .execution_options(include_excluded_accounting=True)
                ).all()
            )
            if {trade.duplicate_fingerprint for trade in materialized} != expected_fingerprints:
                raise RuntimeError(
                    "Post-repair validation did not find every expected canonical trade."
                )
            if len(materialized) != len(plan["_trips"]):
                raise RuntimeError("Post-repair validation found an unexpected trade count.")
            for trade in materialized:
                if trade.account_id != args.account_id:
                    raise RuntimeError("Account isolation validation failed.")
        print(
            json.dumps(
                {
                    "status": "applied",
                    "account_id": str(args.account_id),
                    "trade_ids": [str(item.id) for item in changed],
                },
                indent=2,
            )
        )
        return 0
    except Exception as exc:
        db.rollback()
        print(
            json.dumps(
                {"status": "rolled_back" if args.apply else "blocked", "error": str(exc)}, indent=2
            )
        )
        return 2
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
