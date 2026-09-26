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
    ParsedReport,
    ReportType,
    money,
    parse_datetime,
    parse_duration,
    row_get,
)


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


class DisjointSet:
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


def _fill_pair(row: dict[str, str]) -> tuple[str, str]:
    return row_get(row, "buyFillId", "Buy Fill ID"), row_get(
        row, "sellFillId", "Sell Fill ID"
    )


def completed_trade_count(reports: list[ParsedReport]) -> int:
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

    fill_rows: dict[str, dict[str, str]] = {}
    for report in reports:
        if report.report_type is ReportType.FILLS:
            for row in report.rows:
                fill_id = row_get(row, "Fill ID", "_id")
                if fill_id:
                    fill_rows[fill_id] = row

    result: list[CanonicalTrade] = []
    for rows in groups.values():
        result.append(
            _canonicalize_group(rows, fill_rows, account_identity, timezone_name)
        )
    return sorted(result, key=lambda item: item.entry_timestamp)


def _canonicalize_group(
    typed_rows: list[tuple[ReportType, dict[str, str]]],
    fill_rows: dict[str, dict[str, str]],
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
    linked_fills = [fill_rows[fill_id] for fill_id in all_ids if fill_id in fill_rows]

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

    def weighted_price(action: str, fallback_name: str) -> Decimal:
        candidates = [
            (money(row_get(row, "Quantity")) or Decimal("0"), money(row_get(row, "Price")))
            for row in linked_fills
            if row_get(row, "B/S", "_action").lower() == action
        ]
        if candidates and sum(qty for qty, _ in candidates) > 0:
            return sum(qty * (price or Decimal("0")) for qty, price in candidates) / sum(
                qty for qty, _ in candidates
            )
        values = [
            (
                money(row_get(row, "Paired Qty", "qty")) or Decimal("0"),
                money(row_get(row, fallback_name)),
            )
            for row in gross_rows
        ]
        return sum(qty * (price or Decimal("0")) for qty, price in values) / sum(
            qty for qty, _ in values
        )

    buy_price = weighted_price("buy", "Buy Price" if position_rows else "buyPrice")
    sell_price = weighted_price("sell", "Sell Price" if position_rows else "sellPrice")
    entry_price, exit_price = (
        (buy_price, sell_price) if side is TradeSide.LONG else (sell_price, buy_price)
    )
    commissions = [
        money(row_get(row, "commission"), required=False) for row in linked_fills
    ]
    fees = (
        sum((value or Decimal("0")) for value in commissions)
        if linked_fills and any(value is not None for value in commissions)
        else None
    )
    net_pnl = gross_pnl - fees if fees is not None else gross_pnl

    warnings: list[str] = []
    if len(linked_fills) != len(all_ids):
        warnings.append(f"{len(all_ids) - len(linked_fills)} referenced fill(s) were not found.")
    if position_rows and performance_rows:
        performance_gross = sum(
            (money(row_get(row, "pnl")) or Decimal("0")) for row in performance_rows
        )
        if performance_gross != gross_pnl:
            warnings.append(
                f"Position gross P&L {gross_pnl} differs from Performance {performance_gross}."
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
    fingerprint = hashlib.sha256(fingerprint_source.encode()).hexdigest()
    durations = [
        parse_duration(row_get(row, "duration"))
        for row in performance_rows
        if row_get(row, "duration")
    ]
    duration_seconds = (
        max(durations)
        if durations
        else int((exit_timestamp - entry_timestamp).total_seconds())
    )
    first = preferred[0]
    symbol = row_get(first, "symbol", "Contract")
    return CanonicalTrade(
        fingerprint=fingerprint,
        fill_ids=all_ids,
        buy_fill_ids=buy_ids,
        sell_fill_ids=sell_ids,
        symbol=symbol,
        side=side,
        quantity=quantity,
        entry_price=entry_price,
        exit_price=exit_price,
        gross_pnl=gross_pnl,
        fees=fees,
        net_pnl=net_pnl,
        entry_timestamp=entry_timestamp,
        exit_timestamp=exit_timestamp,
        duration_seconds=duration_seconds,
        tick_size=money(row_get(first, "_tickSize"), required=False),
        currency=row_get(first, "Currency") or "USD",
        product=row_get(first, "Product") or None,
        product_description=row_get(first, "Product Description") or None,
        external_position_id=row_get(first, "Position ID") or None,
        external_pair_id=row_get(first, "Pair ID") or None,
        source_quality="fills_enriched" if linked_fills else "paired_report",
        reconciliation_status="warning" if warnings else "reconciled",
        warnings=warnings,
        source_payload={
            "paired_rows": [row for _, row in typed_rows],
            "fill_ids": sorted(all_ids),
            "warnings": warnings,
        },
    )
