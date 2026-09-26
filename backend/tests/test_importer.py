from decimal import Decimal

import pytest

from app.services.importer import (
    ReportType,
    money,
    parse_duration,
    parse_report,
)


@pytest.mark.parametrize(
    ("headers", "expected"),
    [
        (
            "symbol,_priceFormat,_priceFormatType,_tickSize,buyFillId,sellFillId,"
            "qty,buyPrice,sellPrice,pnl,boughtTimestamp,soldTimestamp,duration",
            ReportType.PERFORMANCE,
        ),
        (
            "Position ID,Account,Pair ID,Buy Fill ID,Sell Fill ID,Paired Qty,P/L",
            ReportType.POSITION_HISTORY,
        ),
        (
            "Fill ID,Order ID,Account,B/S,Quantity,Price,commission",
            ReportType.FILLS,
        ),
        (
            "Order ID,Account,B/S,Status,Type,Filled Qty,Quantity",
            ReportType.ORDERS,
        ),
        (
            "Account,Transaction ID,Cash Change Type,Delta,Amount",
            ReportType.CASH_HISTORY,
        ),
        (
            "Account ID,Account Name,Trade Date,Total Amount,Total Realized PNL",
            ReportType.BALANCE_HISTORY,
        ),
    ],
)
def test_detection_uses_headers_not_filename(headers: str, expected: ReportType) -> None:
    report = parse_report("duplicate-name (42).csv", f"{headers}\n".encode())
    assert report.report_type is expected


def test_empty_order_details_is_nonfatal() -> None:
    report = parse_report("anything.csv", b"undefined\n")
    assert report.report_type is ReportType.ORDER_DETAILS_EMPTY
    assert report.rows == []
    assert report.errors == []
    assert report.warnings


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("1min 40sec", 100),
        ("14min 37sec", 877),
        ("1h 17min 16sec", 4636),
    ],
)
def test_duration_parsing(value: str, expected: int) -> None:
    assert parse_duration(value) == expected


def test_financial_parser_uses_decimal_and_parenthetical_negatives() -> None:
    assert money("$1,570.50") == Decimal("1570.50")
    assert money("$(383.00)") == Decimal("-383.00")
    assert money("", required=False) is None

