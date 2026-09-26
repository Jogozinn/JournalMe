import csv
import io
from decimal import Decimal

import pytest

from app.services.importer import (
    ImportValidationError,
    NormalizedCashRow,
    NormalizedOrderRow,
    NormalizedPositionRow,
    optional_decimal,
    parse_report,
    required_decimal,
)


def _csv_bytes(headers: list[str], row: dict[str, str]) -> bytes:
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=headers, lineterminator="\n")
    writer.writeheader()
    writer.writerow(row)
    return output.getvalue().encode()


ORDER_HEADERS = [
    "orderId",
    "Account",
    "Order ID",
    "B/S",
    "Contract",
    "Status",
    "Timestamp",
    "Quantity",
    "Text",
    "Type",
    "Limit Price",
    "Stop Price",
    "Filled Qty",
    "Avg Fill Price",
    "Fill Time",
    "Notional Value",
    "Currency",
]


def _order(**overrides: str) -> NormalizedOrderRow:
    row = {
        "orderId": "ORDER-1",
        "Account": "MASKED",
        "Order ID": "ORDER-1",
        "B/S": " Buy ",
        "Contract": "MNQ",
        "Status": " Canceled ",
        "Timestamp": "07/29/2026 10:00:00",
        "Quantity": "1",
        "Text": " Chart ",
        "Type": " Limit ",
        "Limit Price": "100.25",
        "Stop Price": "",
        "Filled Qty": "",
        "Avg Fill Price": "",
        "Fill Time": "",
        "Notional Value": "",
        "Currency": " USD ",
        **overrides,
    }
    report = parse_report("Orders.csv", _csv_bytes(ORDER_HEADERS, row))
    assert report.errors == []
    normalized = report.normalized_rows[0]
    assert isinstance(normalized, NormalizedOrderRow)
    return normalized


def test_optional_decimal_preserves_unavailable_values() -> None:
    assert optional_decimal("") is None
    assert optional_decimal("   ") is None
    assert optional_decimal("NaN") is None
    assert optional_decimal("0") == Decimal("0")


def test_required_decimal_raises_structured_error() -> None:
    with pytest.raises(ImportValidationError) as caught:
        required_decimal(
            "",
            filename="Cash History.csv",
            row_number=2,
            source_column="Amount",
            field_name="amount",
        )
    assert caught.value.as_dict() == {
        "report_type": "unknown",
        "filename": "Cash History.csv",
        "row_number": 2,
        "source_column": "Amount",
        "field_name": "amount",
        "reason": "is required but blank or unavailable.",
    }


def test_canceled_limit_order_keeps_blank_execution_values_null() -> None:
    order = _order()
    assert order.status == "canceled"
    assert order.order_type == "limit"
    assert order.filled_quantity is None
    assert order.average_fill_price is None
    assert order.fill_timestamp is None
    assert order.limit_price == Decimal("100.25")
    assert order.stop_price is None
    assert order.notional_value is None


def test_canceled_stop_order_keeps_blank_execution_values_null() -> None:
    order = _order(
        **{
            "Type": " Stop ",
            "Limit Price": "",
            "Stop Price": "99.75",
        }
    )
    assert order.order_type == "stop"
    assert order.limit_price is None
    assert order.stop_price == Decimal("99.75")
    assert order.filled_quantity is None


def test_filled_market_order_allows_blank_limit_and_stop() -> None:
    order = _order(
        **{
            "Status": " Filled ",
            "Type": " Market ",
            "Limit Price": "",
            "Stop Price": "",
            "Filled Qty": "1",
            "Avg Fill Price": "100.50",
            "Fill Time": "07/29/2026 10:00:01",
            "Notional Value": "20100.00",
        }
    )
    assert order.status == "filled"
    assert order.order_type == "market"
    assert order.limit_price is None
    assert order.stop_price is None
    assert order.filled_quantity == Decimal("1")
    assert order.average_fill_price == Decimal("100.50")


def test_flat_position_allows_blank_net_price() -> None:
    headers = [
        "Position ID",
        "Account",
        "Pair ID",
        "Buy Fill ID",
        "Sell Fill ID",
        "Net Pos",
        "Net Price",
        "Paired Qty",
        "Buy Price",
        "Sell Price",
        "P/L",
        "Bought Timestamp",
        "Sold Timestamp",
    ]
    row = {
        "Position ID": "POSITION-1",
        "Account": "MASKED",
        "Pair ID": "PAIR-1",
        "Buy Fill ID": "BUY-1",
        "Sell Fill ID": "SELL-1",
        "Net Pos": "0",
        "Net Price": "",
        "Paired Qty": "1",
        "Buy Price": "100",
        "Sell Price": "101",
        "P/L": "2.00",
        "Bought Timestamp": "07/29/2026 10:00:00",
        "Sold Timestamp": "07/29/2026 10:01:00",
    }
    report = parse_report("Position History.csv", _csv_bytes(headers, row))
    assert report.errors == []
    normalized = report.normalized_rows[0]
    assert isinstance(normalized, NormalizedPositionRow)
    assert normalized.net_position == 0
    assert normalized.net_price is None
    assert normalized.buy_price == Decimal("100")


def test_fund_transaction_allows_blank_contract() -> None:
    headers = [
        "Account",
        "Transaction ID",
        "Timestamp",
        "Date",
        "Delta",
        "Amount",
        "Cash Change Type",
        "Currency",
        "Contract",
    ]
    row = {
        "Account": "MASKED",
        "Transaction ID": "TX-1",
        "Timestamp": "07/27/2026 16:10:51",
        "Date": "2026-07-27",
        "Delta": "50,000.00",
        "Amount": "50,000.00",
        "Cash Change Type": " Fund Transaction ",
        "Currency": "USD",
        "Contract": "",
    }
    report = parse_report("Cash History.csv", _csv_bytes(headers, row))
    assert report.errors == []
    normalized = report.normalized_rows[0]
    assert isinstance(normalized, NormalizedCashRow)
    assert normalized.contract is None
    assert normalized.amount == Decimal("50000.00")


@pytest.mark.parametrize(
    ("filename", "headers", "row", "column", "field_name"),
    [
        (
            "Position History.csv",
            [
                "Position ID",
                "Account",
                "Pair ID",
                "Buy Fill ID",
                "Sell Fill ID",
                "Net Pos",
                "Net Price",
                "Paired Qty",
                "Buy Price",
                "Sell Price",
                "P/L",
                "Bought Timestamp",
                "Sold Timestamp",
            ],
            {
                "Position ID": "P1",
                "Account": "MASKED",
                "Pair ID": "PAIR1",
                "Buy Fill ID": "B1",
                "Sell Fill ID": "S1",
                "Net Pos": "0",
                "Net Price": "",
                "Paired Qty": "1",
                "Buy Price": "100",
                "Sell Price": "101",
                "P/L": "",
                "Bought Timestamp": "07/29/2026 10:00:00",
                "Sold Timestamp": "07/29/2026 10:01:00",
            },
            "P/L",
            "pnl",
        ),
        (
            "Cash History.csv",
            [
                "Account",
                "Transaction ID",
                "Timestamp",
                "Date",
                "Delta",
                "Amount",
                "Cash Change Type",
            ],
            {
                "Account": "MASKED",
                "Transaction ID": "TX1",
                "Timestamp": "07/29/2026 10:00:00",
                "Date": "2026-07-29",
                "Delta": "10",
                "Amount": "",
                "Cash Change Type": "Adjustment",
            },
            "Amount",
            "amount",
        ),
    ],
)
def test_required_financial_errors_include_source_context(
    filename: str,
    headers: list[str],
    row: dict[str, str],
    column: str,
    field_name: str,
) -> None:
    report = parse_report(filename, _csv_bytes(headers, row))
    assert len(report.errors) == 1
    error = report.errors[0]
    assert error.filename == filename
    assert error.row_number == 2
    assert error.source_column == column
    assert error.field_name == field_name
    assert "required" in error.reason


def test_preview_and_commit_parsing_produce_identical_normalized_models() -> None:
    content = _csv_bytes(
        ORDER_HEADERS,
        {
            "orderId": "ORDER-1",
            "Account": "MASKED",
            "Order ID": "ORDER-1",
            "B/S": " Sell ",
            "Contract": "MNQ",
            "Status": " Canceled ",
            "Quantity": "2",
            "Type": " Stop ",
            "Stop Price": "99.75",
        },
    )
    preview_report = parse_report("Orders (1).csv", content)
    commit_report = parse_report("Orders (1).csv", content)
    assert preview_report.errors == commit_report.errors == []
    assert preview_report.normalized_rows == commit_report.normalized_rows

