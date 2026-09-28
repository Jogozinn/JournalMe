from decimal import Decimal
from pathlib import Path

import pytest

from app.domain import TradeSide
from app.services.importer import parse_report
from app.services.reconciliation import (
    completed_trade_count,
    reconcile_completed_trades,
)

PERFORMANCE_HEADER = (
    "symbol,_priceFormat,_priceFormatType,_tickSize,buyFillId,sellFillId,qty,"
    "buyPrice,sellPrice,pnl,boughtTimestamp,soldTimestamp,duration"
)


def _performance_report() -> bytes:
    rows = []
    for index in range(11):
        minute = index + 1
        rows.append(
            f"MNQ,-2,0,0.25,B{index},S{index},1,100,101,$2.00,"
            f"07/29/2026 10:{minute:02d}:00,07/29/2026 10:{minute:02d}:30,30sec"
        )
    rows.extend(
        [
            "MCL,-2,0,0.01,BX,SX1,2,83.43,83.30,$(26.00),"
            "07/29/2026 22:58:43,07/29/2026 22:55:49,2min 53sec",
            "MCL,-2,0,0.01,BX,SX2,2,83.43,83.30,$(26.00),"
            "07/29/2026 22:58:43,07/29/2026 22:55:49,2min 53sec",
        ]
    )
    return (PERFORMANCE_HEADER + "\n" + "\n".join(rows)).encode()


def _fills_report() -> bytes:
    return (
        b"Fill ID,Order ID,Account,B/S,Quantity,Price,commission,Timestamp,"
        b"_tradeDate,Contract,Product,Product Description\n"
        b"BX,OB,MASKED,Buy,4,83.43,2.00,07/29/2026 22:58:43,2026-07-29,MCL,MCL,Crude\n"
        b"SX1,OS1,MASKED,Sell,2,83.30,1.00,07/29/2026 22:55:49,2026-07-29,MCL,MCL,Crude\n"
        b"SX2,OS2,MASKED,Sell,2,83.30,1.00,07/29/2026 22:55:49,2026-07-29,MCL,MCL,Crude\n"
    )


def test_shared_fill_graph_reconciles_13_rows_to_12_trades() -> None:
    reports = [parse_report("Performance.csv", _performance_report())]
    assert len(reports[0].rows) == 13
    assert completed_trade_count(reports) == 12


def test_direction_uses_timestamps_and_scaled_fills_aggregate() -> None:
    reports = [
        parse_report("Performance.csv", _performance_report()),
        parse_report("Fills.csv", _fills_report()),
    ]
    trades = reconcile_completed_trades(reports, "MASKED")
    scaled = next(trade for trade in trades if trade.symbol == "MCL")
    assert scaled.side is TradeSide.SHORT
    assert scaled.quantity == Decimal("4")
    assert scaled.gross_pnl == Decimal("-52.00")
    assert scaled.fees == Decimal("4.00")
    assert scaled.net_pnl == Decimal("-56.00")
    assert scaled.entry_price == Decimal("83.30")
    assert scaled.exit_price == Decimal("83.43")


def test_fingerprints_are_stable_for_reuploads() -> None:
    reports = [
        parse_report("first-name.csv", _performance_report()),
        parse_report("fills (1).csv", _fills_report()),
    ]
    first = reconcile_completed_trades(reports, "MASKED")
    second = reconcile_completed_trades(reports, "MASKED")
    assert [trade.fingerprint for trade in first] == [
        trade.fingerprint for trade in second
    ]


def test_exact_duplicate_source_rows_do_not_double_count() -> None:
    one = (
        PERFORMANCE_HEADER
        + "\nMNQ,-2,0,0.25,B1,S1,1,100,101,$2.00,"
        "07/29/2026 10:00:00,07/29/2026 10:01:00,1min"
    )
    report = parse_report("performance.csv", f"{one}\n{one.splitlines()[1]}\n".encode())
    trades = reconcile_completed_trades([report], "MASKED")
    assert len(trades) == 1
    assert trades[0].gross_pnl == Decimal("2.00")


def test_supplied_sanitization_source_reconciles_to_expected_totals() -> None:
    root = Path(__file__).resolve().parents[2]
    paths = list(root.glob("*.csv"))
    if not paths:
        pytest.skip("Local broker exports are intentionally not committed.")
    reports = [parse_report(path.name, path.read_bytes()) for path in paths]
    performance = next(
        report for report in reports if report.report_type.value == "performance"
    )
    empty = next(
        report
        for report in reports
        if report.report_type.value == "order_details_empty"
    )
    trades = reconcile_completed_trades(reports, "MASKED")
    assert len(performance.rows) == 13
    assert empty.warnings
    # With a Fills report present, canonical JournalMe trades are position lifecycles
    # (flat -> position -> flat), not Tradovate lot-pair groups.
    assert len(trades) == 9
    assert sum((trade.fees or Decimal("0")) for trade in trades) == Decimal("28.8")


def test_fills_define_flat_to_flat_trade_boundary_with_partial_exit() -> None:
    fills = (
        b"Fill ID,Order ID,Account,B/S,Quantity,Price,commission,Timestamp,"
        b"_tradeDate,Contract,Product,Product Description\n"
        b"F1,O1,MASKED,Buy,2,100,1.00,09/28/2026 10:00:00,2026-09-28,MNQZ6,MNQ,Nasdaq\n"
        b"F2,O2,MASKED,Buy,1,101,0.50,09/28/2026 10:01:00,2026-09-28,MNQZ6,MNQ,Nasdaq\n"
        b"F3,O3,MASKED,Sell,1,102,0.50,09/28/2026 10:02:00,2026-09-28,MNQZ6,MNQ,Nasdaq\n"
        b"F4,O4,MASKED,Sell,2,103,1.00,09/28/2026 10:03:00,2026-09-28,MNQZ6,MNQ,Nasdaq\n"
        # New position is only partially closed, so it must not be materialized.
        b"F5,O5,MASKED,Buy,2,104,1.00,09/28/2026 10:04:00,2026-09-28,MNQZ6,MNQ,Nasdaq\n"
        b"F6,O6,MASKED,Sell,1,105,0.50,09/28/2026 10:05:00,2026-09-28,MNQZ6,MNQ,Nasdaq\n"
    )
    report = parse_report("Fills.csv", fills)
    trades = reconcile_completed_trades([report], "MASKED")
    assert len(trades) == 1
    trade = trades[0]
    assert trade.side is TradeSide.LONG
    assert trade.quantity == Decimal("3")
    assert trade.fill_ids == {"F1", "F2", "F3", "F4"}
    assert trade.entry_timestamp.minute == 0
    assert trade.exit_timestamp.minute == 3
    assert trade.duration_seconds == 180
    assert trade.fees == Decimal("3.00")


def test_contract_identity_reconciles_ninjatrader_and_tradovate_symbols() -> None:
    from datetime import datetime, timezone

    from app.services.instrument_identity import canonical_contract_key, root_symbol

    reference = datetime(2026, 9, 28, tzinfo=timezone.utc)
    assert canonical_contract_key("MNQ 12-26", reference) == "MNQ:2026-12"
    assert canonical_contract_key("MNQZ6", reference) == "MNQ:2026-12"
    assert root_symbol("MNQ 12-26") == "MNQ"
    assert root_symbol("MNQZ6") == "MNQ"
