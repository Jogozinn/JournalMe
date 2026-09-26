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
    assert len(trades) == 12
    assert sum((trade.fees or Decimal("0")) for trade in trades) == Decimal("28.8")
