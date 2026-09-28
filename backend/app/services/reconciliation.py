from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from app.domain import TradeSide
from app.services.importer import (
    NormalizedFillRow,
    ParsedReport,
    ReportType,
    money,
    parse_datetime,
    parse_duration,
    row_get,
)
from app.services.instrument_identity import canonical_contract_key


@dataclass
class CanonicalTrade:
    fingerprint: str
    fill_ids: set[str]
    buy_fill_ids: set[str]
    sell_fill_ids: set[str]
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
    duration_seconds: int
    tick_size: Decimal | None
    currency: str
    product: str | None = None
    product_description: str | None = None
    external_position_id: str | None = None
    external_pair_id: str | None = None
    source_quality: str = "paired_report"
    reconciliation_status: str = "reconciled"
    warnings: list[str] = field(default_factory=list)
    source_payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FillSlice:
    fill: NormalizedFillRow
    quantity: Decimal
    role: str  # "open" or "close"


@dataclass(frozen=True)
class FillLifecycle:
    slices: tuple[FillSlice, ...]
    symbol: str
    side: TradeSide
    quantity: Decimal
    entry_price: Decimal
    exit_price: Decimal
    entry_timestamp: datetime
    exit_timestamp: datetime

    @property
    def fill_ids(self) -> set[str]:
        return {item.fill.external_fill_id for item in self.slices}


class DisjointSet:
    """Fallback identity graph used for legacy imports that do not include Fills."""

    def __init__(self) -> None:
        self.parent: dict[str, str] = {}

    def find(self, value: str) -> str:
        self.parent.setdefault(value, value)
        if self.parent[value] != value:
            self.parent[value] = self.find(self.parent[value])
        return self.parent[value]

    def union(self, left: str, right: str) -> None:
        left_root, right_root = self.find(left), self.find(right)
        if left_root != right_root:
            self.parent[right_root] = left_root


def _unique_rows(rows: Iterable[dict[str, str]]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in rows:
        marker = json.dumps(row, sort_keys=True, separators=(",", ":"))
        if marker not in seen:
            result.append(row)
            seen.add(marker)
    return result


def _paired_rows(reports: list[ParsedReport]) -> list[tuple[ReportType, dict[str, str]]]:
    rows: list[tuple[ReportType, dict[str, str]]] = []
    for report in reports:
        if report.report_type in {ReportType.PERFORMANCE, ReportType.POSITION_HISTORY}:
            rows.extend((report.report_type, row) for row in _unique_rows(report.rows))
    return rows


def _preferred_paired_rows(reports: list[ParsedReport]) -> list[dict[str, str]]:
    position_rows = [
        row
        for report in reports
        if report.report_type is ReportType.POSITION_HISTORY
        for row in report.rows
    ]
    if position_rows:
        return _unique_rows(position_rows)
    performance_rows = [
        row
        for report in reports
        if report.report_type is ReportType.PERFORMANCE
        for row in report.rows
    ]
    return _unique_rows(performance_rows)


def _fill_pair(row: dict[str, str]) -> tuple[str, str]:
    return row_get(row, "buyFillId", "Buy Fill ID"), row_get(
        row, "sellFillId", "Sell Fill ID"
    )


def _normalized_fills(reports: list[ParsedReport]) -> list[NormalizedFillRow]:
    seen: set[str] = set()
    fills: list[NormalizedFillRow] = []
    for report in reports:
        if report.report_type is not ReportType.FILLS:
            continue
        for row in report.normalized_rows:
            if not isinstance(row, NormalizedFillRow):
                continue
            if row.external_fill_id in seen:
                continue
            seen.add(row.external_fill_id)
            fills.append(row)
    return fills


def _side_sign(action: str) -> int:
    normalized = action.casefold()
    if normalized in {"buy", "long"}:
        return 1
    if normalized in {"sell", "short"}:
        return -1
    raise ValueError(f"Unsupported fill action: {action}")


def _weighted_fill_price(slices: Iterable[FillSlice], role: str) -> Decimal:
    selected = [item for item in slices if item.role == role]
    quantity = sum((item.quantity for item in selected), Decimal("0"))
    if quantity <= 0:
        return Decimal("0")
    return sum(
        (item.quantity * item.fill.price for item in selected), Decimal("0")
    ) / quantity


def _allocated_commission(item: FillSlice) -> Decimal | None:
    if item.fill.commission is None or item.fill.quantity <= 0:
        return None
    return item.fill.commission * item.quantity / item.fill.quantity


def _reconstruct_fill_lifecycles(fills: list[NormalizedFillRow]) -> list[FillLifecycle]:
    """Reconstruct the trader-visible flat -> position -> flat lifecycle from fills.

    Tradovate Performance/Position History rows are lot pairings. They are useful
    enrichment evidence, but they are not the JournalMe trade boundary. Fills are
    therefore grouped by canonical futures contract and position state first.
    """
    by_contract: dict[str, list[NormalizedFillRow]] = defaultdict(list)
    for fill in fills:
        by_contract[canonical_contract_key(fill.symbol, fill.timestamp)].append(fill)

    completed: list[FillLifecycle] = []
    for contract_fills in by_contract.values():
        ordered = sorted(
            contract_fills,
            key=lambda item: (item.timestamp, item.row_number, item.external_fill_id),
        )
        position = Decimal("0")
        active_slices: list[FillSlice] = []

        def finalize() -> None:
            nonlocal active_slices
            open_slices = [item for item in active_slices if item.role == "open"]
            close_slices = [item for item in active_slices if item.role == "close"]
            opened = sum((item.quantity for item in open_slices), Decimal("0"))
            closed = sum((item.quantity for item in close_slices), Decimal("0"))
            if not open_slices or opened <= 0 or opened != closed:
                return
            entry_timestamp = min(item.fill.timestamp for item in open_slices)
            exit_timestamp = max(item.fill.timestamp for item in close_slices)
            completed.append(
                FillLifecycle(
                    slices=tuple(active_slices),
                    symbol=open_slices[0].fill.symbol,
                    side=(
                        TradeSide.LONG
                        if _side_sign(open_slices[0].fill.action) > 0
                        else TradeSide.SHORT
                    ),
                    quantity=opened,
                    entry_price=_weighted_fill_price(active_slices, "open"),
                    exit_price=_weighted_fill_price(active_slices, "close"),
                    entry_timestamp=entry_timestamp,
                    exit_timestamp=exit_timestamp,
                )
            )
            active_slices = []

        for fill in ordered:
            remaining = Decimal(fill.quantity)
            event_side = _side_sign(fill.action)
            while remaining > 0:
                if position == 0:
                    active_slices.append(FillSlice(fill, remaining, "open"))
                    position = Decimal(event_side) * remaining
                    remaining = Decimal("0")
                    continue

                position_side = 1 if position > 0 else -1
                if event_side == position_side:
                    active_slices.append(FillSlice(fill, remaining, "open"))
                    position += Decimal(event_side) * remaining
                    remaining = Decimal("0")
                    continue

                close_quantity = min(abs(position), remaining)
                active_slices.append(FillSlice(fill, close_quantity, "close"))
                position += Decimal(event_side) * close_quantity
                remaining -= close_quantity
                if position == 0:
                    finalize()
                    # A single reversal fill can close one lifecycle and open the next.
                    continue

    return sorted(completed, key=lambda item: item.entry_timestamp)


def completed_trade_count(reports: list[ParsedReport]) -> int:
    fills = _normalized_fills(reports)
    if fills:
        return len(_reconstruct_fill_lifecycles(fills))

    paired = _paired_rows(reports)
    dsu = DisjointSet()
    for _, row in paired:
        buy_id, sell_id = _fill_pair(row)
        if buy_id and sell_id:
            dsu.union(f"f:{buy_id}", f"f:{sell_id}")
        else:
            fallback = row_get(row, "Pair ID", "Position ID") or hashlib.sha256(
                json.dumps(row, sort_keys=True).encode()
            ).hexdigest()
            dsu.find(f"p:{fallback}")
    return len({dsu.find(value) for value in dsu.parent})


def reconcile_completed_trades(
    reports: list[ParsedReport],
    account_identity: str,
    timezone_name: str = "America/New_York",
) -> list[CanonicalTrade]:
    fills = _normalized_fills(reports)
    if fills:
        return _reconcile_fill_lifecycles(reports, fills, account_identity)
    return _reconcile_paired_rows(reports, account_identity, timezone_name)


def _reconcile_fill_lifecycles(
    reports: list[ParsedReport],
    fills: list[NormalizedFillRow],
    account_identity: str,
) -> list[CanonicalTrade]:
    paired_rows = _preferred_paired_rows(reports)
    lifecycles = _reconstruct_fill_lifecycles(fills)
    result: list[CanonicalTrade] = []

    for lifecycle in lifecycles:
        fill_ids = lifecycle.fill_ids
        matched_rows = []
        for row in paired_rows:
            buy_id, sell_id = _fill_pair(row)
            if buy_id and sell_id and buy_id in fill_ids and sell_id in fill_ids:
                matched_rows.append(row)

        gross_pnl = sum(
            (
                money(row_get(row, "P/L", "pnl"), required=False)
                or Decimal("0")
            )
            for row in matched_rows
        )
        commissions = [_allocated_commission(item) for item in lifecycle.slices]
        fees = (
            sum((value or Decimal("0") for value in commissions), Decimal("0"))
            if commissions and all(value is not None for value in commissions)
            else None
        )
        warnings: list[str] = []
        if not matched_rows:
            warnings.append(
                "No paired P&L rows matched this flat-to-flat fill lifecycle; gross P&L could not be enriched."
            )
        if fees is None:
            warnings.append("One or more fill commissions were unavailable.")

        buy_ids = {
            item.fill.external_fill_id
            for item in lifecycle.slices
            if _side_sign(item.fill.action) > 0
        }
        sell_ids = {
            item.fill.external_fill_id
            for item in lifecycle.slices
            if _side_sign(item.fill.action) < 0
        }
        all_ids = buy_ids | sell_ids
        first_open = next(item.fill for item in lifecycle.slices if item.role == "open")
        pair_ids = {row_get(row, "Pair ID") for row in matched_rows if row_get(row, "Pair ID")}
        position_ids = {
            row_get(row, "Position ID")
            for row in matched_rows
            if row_get(row, "Position ID")
        }
        currencies = [row_get(row, "Currency") for row in matched_rows if row_get(row, "Currency")]
        tick_size = money(row_get(first_open.source_payload, "_tickSize"), required=False)
        fill_identity = ",".join(sorted(all_ids))
        fingerprint_source = f"{account_identity}|fills|{fill_identity}"
        fingerprint = hashlib.sha256(fingerprint_source.encode()).hexdigest()
        net_pnl = gross_pnl - fees if fees is not None else gross_pnl
        status = "reconciled" if matched_rows and not warnings else "warning"

        result.append(
            CanonicalTrade(
                fingerprint=fingerprint,
                fill_ids=all_ids,
                buy_fill_ids=buy_ids,
                sell_fill_ids=sell_ids,
                symbol=lifecycle.symbol,
                side=lifecycle.side,
                quantity=lifecycle.quantity,
                entry_price=lifecycle.entry_price,
                exit_price=lifecycle.exit_price,
                gross_pnl=gross_pnl,
                fees=fees,
                net_pnl=net_pnl,
                entry_timestamp=lifecycle.entry_timestamp,
                exit_timestamp=lifecycle.exit_timestamp,
                duration_seconds=max(
                    0,
                    int((lifecycle.exit_timestamp - lifecycle.entry_timestamp).total_seconds()),
                ),
                tick_size=tick_size,
                currency=currencies[0] if currencies else "USD",
                product=first_open.product,
                product_description=first_open.product_description,
                external_position_id=(next(iter(position_ids)) if len(position_ids) == 1 else None),
                external_pair_id=(next(iter(pair_ids)) if len(pair_ids) == 1 else None),
                source_quality="fills_lifecycle",
                reconciliation_status=status,
                warnings=warnings,
                source_payload={
                    "source": "tradovate_fill_lifecycle",
                    "fill_ids": sorted(all_ids),
                    "paired_rows": matched_rows,
                    "canonical_contract": canonical_contract_key(
                        lifecycle.symbol, lifecycle.entry_timestamp
                    ),
                    "warnings": warnings,
                },
            )
        )
    return result


def _reconcile_paired_rows(
    reports: list[ParsedReport],
    account_identity: str,
    timezone_name: str,
) -> list[CanonicalTrade]:
    """Legacy fallback when a historical import does not contain a Fills report."""
    paired = _paired_rows(reports)
    dsu = DisjointSet()
    keyed_rows: list[tuple[str, ReportType, dict[str, str]]] = []
    for index, (report_type, row) in enumerate(paired):
        buy_id, sell_id = _fill_pair(row)
        if buy_id and sell_id:
            dsu.union(f"f:{buy_id}", f"f:{sell_id}")
            key = dsu.find(f"f:{buy_id}")
        else:
            fallback = row_get(row, "Pair ID", "Position ID") or str(index)
            key = f"p:{fallback}"
            dsu.find(key)
        keyed_rows.append((key, report_type, row))

    groups: dict[str, list[tuple[ReportType, dict[str, str]]]] = defaultdict(list)
    for key, report_type, row in keyed_rows:
        groups[dsu.find(key)].append((report_type, row))

    result = [
        _canonicalize_legacy_group(rows, account_identity, timezone_name)
        for rows in groups.values()
    ]
    return sorted(result, key=lambda item: item.entry_timestamp)


def _canonicalize_legacy_group(
    typed_rows: list[tuple[ReportType, dict[str, str]]],
    account_identity: str,
    timezone_name: str,
) -> CanonicalTrade:
    position_rows = [row for kind, row in typed_rows if kind is ReportType.POSITION_HISTORY]
    performance_rows = [row for kind, row in typed_rows if kind is ReportType.PERFORMANCE]
    preferred = position_rows or performance_rows
    if not preferred:
        raise ValueError("A completed trade requires a paired source row.")

    buy_ids = {buy for row in preferred if (buy := _fill_pair(row)[0])}
    sell_ids = {sell for row in preferred if (sell := _fill_pair(row)[1])}
    all_ids = buy_ids | sell_ids
    bought_times = [
        parse_datetime(row_get(row, "Bought Timestamp", "boughtTimestamp"), timezone_name)
        for row in preferred
    ]
    sold_times = [
        parse_datetime(row_get(row, "Sold Timestamp", "soldTimestamp"), timezone_name)
        for row in preferred
    ]
    earliest_buy, earliest_sell = min(bought_times), min(sold_times)
    side = TradeSide.LONG if earliest_buy < earliest_sell else TradeSide.SHORT
    entry_timestamp = min(bought_times + sold_times)
    exit_timestamp = max(bought_times + sold_times)
    gross_rows = position_rows or performance_rows
    gross_pnl = sum(
        (money(row_get(row, "P/L", "pnl")) or Decimal("0")) for row in gross_rows
    )
    quantity = sum(
        (money(row_get(row, "Paired Qty", "qty")) or Decimal("0")) for row in gross_rows
    )

    def weighted_price(fallback_name: str) -> Decimal:
        values = [
            (
                money(row_get(row, "Paired Qty", "qty")) or Decimal("0"),
                money(row_get(row, fallback_name)),
            )
            for row in gross_rows
        ]
        total = sum(qty for qty, _ in values)
        return sum(qty * (price or Decimal("0")) for qty, price in values) / total

    buy_price = weighted_price("Buy Price" if position_rows else "buyPrice")
    sell_price = weighted_price("Sell Price" if position_rows else "sellPrice")
    entry_price, exit_price = (
        (buy_price, sell_price) if side is TradeSide.LONG else (sell_price, buy_price)
    )
    fill_identity = ",".join(sorted(all_ids))
    fingerprint_source = (
        f"{account_identity}|fills|{fill_identity}"
        if fill_identity
        else "|".join(
            [
                account_identity,
                row_get(preferred[0], "symbol", "Contract"),
                entry_timestamp.isoformat(),
                exit_timestamp.isoformat(),
                str(quantity),
                str(entry_price),
                str(exit_price),
            ]
        )
    )
    durations = [
        parse_duration(row_get(row, "duration"))
        for row in performance_rows
        if row_get(row, "duration")
    ]
    first = preferred[0]
    return CanonicalTrade(
        fingerprint=hashlib.sha256(fingerprint_source.encode()).hexdigest(),
        fill_ids=all_ids,
        buy_fill_ids=buy_ids,
        sell_fill_ids=sell_ids,
        symbol=row_get(first, "symbol", "Contract"),
        side=side,
        quantity=quantity,
        entry_price=entry_price,
        exit_price=exit_price,
        gross_pnl=gross_pnl,
        fees=None,
        net_pnl=gross_pnl,
        entry_timestamp=entry_timestamp,
        exit_timestamp=exit_timestamp,
        duration_seconds=(
            max(value for value in durations if value is not None)
            if any(value is not None for value in durations)
            else int((exit_timestamp - entry_timestamp).total_seconds())
        ),
        tick_size=money(row_get(first, "_tickSize"), required=False),
        currency=row_get(first, "Currency") or "USD",
        product=row_get(first, "Product") or None,
        product_description=row_get(first, "Product Description") or None,
        external_position_id=row_get(first, "Position ID") or None,
        external_pair_id=row_get(first, "Pair ID") or None,
        source_quality="paired_report",
        reconciliation_status="warning",
        warnings=["Fills report was unavailable; trade boundaries use legacy paired-report reconciliation."],
        source_payload={
            "paired_rows": [row for _, row in typed_rows],
            "fill_ids": sorted(all_ids),
            "warnings": ["Fills report was unavailable; trade boundaries use legacy paired-report reconciliation."],
        },
    )
