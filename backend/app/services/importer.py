from __future__ import annotations

import csv
import hashlib
import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any
from zoneinfo import ZoneInfo


class ReportType(str, Enum):
    PERFORMANCE = "performance"
    POSITION_HISTORY = "position_history"
    FILLS = "fills"
    ORDERS = "orders"
    CASH_HISTORY = "cash_history"
    BALANCE_HISTORY = "account_balance_history"
    ORDER_DETAILS_EMPTY = "order_details_empty"
    UNKNOWN = "unknown"


class ImportValidationError(ValueError):
    """A source-aware validation error safe to return to the import UI."""

    def __init__(
        self,
        *,
        report_type: ReportType = ReportType.UNKNOWN,
        filename: str = "<unknown>",
        row_number: int = 0,
        source_column: str = "<value>",
        field_name: str = "value",
        reason: str,
    ) -> None:
        self.report_type = report_type
        self.filename = filename
        self.row_number = row_number
        self.source_column = source_column
        self.field_name = field_name
        self.reason = reason
        location = (
            f"{filename}, CSV row {row_number}, column {source_column}"
            if row_number
            else source_column
        )
        super().__init__(f"{location}: {field_name} {reason}")

    def as_dict(self) -> dict[str, str | int]:
        return {
            "report_type": self.report_type.value,
            "filename": self.filename,
            "row_number": self.row_number,
            "source_column": self.source_column,
            "field_name": self.field_name,
            "reason": self.reason,
        }


class ImportReportValidationError(ValueError):
    def __init__(self, errors: list[ImportValidationError]) -> None:
        self.errors = errors
        super().__init__(
            f"{len(errors)} required import value(s) failed validation."
        )

    def as_detail(self) -> dict[str, Any]:
        return {
            "message": str(self),
            "errors": [error.as_dict() for error in self.errors],
        }


@dataclass(frozen=True)
class NormalizedSourceRow:
    row_number: int
    source_payload: dict[str, str]


@dataclass(frozen=True)
class NormalizedPerformanceRow(NormalizedSourceRow):
    quantity: Decimal
    buy_price: Decimal
    sell_price: Decimal
    pnl: Decimal
    bought_timestamp: datetime
    sold_timestamp: datetime


@dataclass(frozen=True)
class NormalizedPositionRow(NormalizedSourceRow):
    net_position: Decimal
    net_price: Decimal | None
    paired_quantity: Decimal
    buy_price: Decimal
    sell_price: Decimal
    pnl: Decimal
    bought_timestamp: datetime
    sold_timestamp: datetime


@dataclass(frozen=True)
class NormalizedFillRow(NormalizedSourceRow):
    external_fill_id: str
    external_order_id: str | None
    symbol: str
    action: str
    quantity: Decimal
    price: Decimal
    commission: Decimal | None
    timestamp: datetime
    trade_date: date
    product: str | None
    product_description: str | None


@dataclass(frozen=True)
class NormalizedOrderRow(NormalizedSourceRow):
    external_order_id: str
    side: str
    symbol: str
    order_type: str | None
    status: str
    text: str | None
    requested_quantity: Decimal
    filled_quantity: Decimal | None
    limit_price: Decimal | None
    stop_price: Decimal | None
    average_fill_price: Decimal | None
    notional_value: Decimal | None
    venue: str | None
    currency: str | None
    submitted_timestamp: datetime | None
    fill_timestamp: datetime | None


@dataclass(frozen=True)
class NormalizedCashRow(NormalizedSourceRow):
    external_transaction_id: str
    timestamp: datetime
    trade_date: date
    delta: Decimal
    amount: Decimal
    cash_change_type: str
    currency: str | None
    contract: str | None


@dataclass(frozen=True)
class NormalizedBalanceRow(NormalizedSourceRow):
    trade_date: date
    total_amount: Decimal
    total_realized_pnl: Decimal
    source_account_id: str | None
    source_account_name: str | None


type NormalizedRow = (
    NormalizedPerformanceRow
    | NormalizedPositionRow
    | NormalizedFillRow
    | NormalizedOrderRow
    | NormalizedCashRow
    | NormalizedBalanceRow
)


REPORT_HEADERS: dict[ReportType, set[str]] = {
    ReportType.PERFORMANCE: {
        "symbol",
        "buyfillid",
        "sellfillid",
        "qty",
        "pnl",
        "boughttimestamp",
        "soldtimestamp",
        "duration",
    },
    ReportType.POSITION_HISTORY: {
        "position id",
        "pair id",
        "buy fill id",
        "sell fill id",
        "paired qty",
        "p/l",
        "account",
    },
    ReportType.FILLS: {
        "fill id",
        "order id",
        "account",
        "b/s",
        "quantity",
        "price",
        "commission",
    },
    ReportType.ORDERS: {
        "order id",
        "account",
        "status",
        "type",
        "filled qty",
        "quantity",
    },
    ReportType.CASH_HISTORY: {
        "transaction id",
        "cash change type",
        "delta",
        "amount",
        "account",
    },
    ReportType.BALANCE_HISTORY: {
        "account id",
        "account name",
        "trade date",
        "total amount",
        "total realized pnl",
    },
}


@dataclass
class ParsedReport:
    filename: str
    report_type: ReportType
    content_hash: str
    headers: list[str]
    rows: list[dict[str, str]]
    normalized_rows: list[NormalizedRow] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[ImportValidationError] = field(default_factory=list)

    @property
    def header_signature(self) -> str:
        normalized = ",".join(sorted(normalize_header(value) for value in self.headers))
        return hashlib.sha256(normalized.encode()).hexdigest()


def normalize_header(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def detect_report_type(headers: list[str], body: str) -> ReportType:
    if body.strip().lower() == "undefined":
        return ReportType.ORDER_DETAILS_EMPTY
    normalized = {normalize_header(value) for value in headers}
    for report_type, required in REPORT_HEADERS.items():
        if required.issubset(normalized):
            return report_type
    return ReportType.UNKNOWN


def parse_report(filename: str, content: bytes) -> ParsedReport:
    content_hash = hashlib.sha256(content).hexdigest()
    try:
        body = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        body = content.decode("cp1252")
    if body.strip().lower() == "undefined":
        return ParsedReport(
            filename=filename,
            report_type=ReportType.ORDER_DETAILS_EMPTY,
            content_hash=content_hash,
            headers=["undefined"],
            rows=[],
            warnings=["Empty Order Details report was skipped."],
        )
    reader = csv.DictReader(io.StringIO(body))
    headers = list(reader.fieldnames or [])
    report_type = detect_report_type(headers, body)
    report = ParsedReport(
        filename=filename,
        report_type=report_type,
        content_hash=content_hash,
        headers=headers,
        rows=[{key: (value or "").strip() for key, value in row.items()} for row in reader],
    )
    if report_type is ReportType.UNKNOWN:
        report.errors.append(
            ImportValidationError(
                report_type=ReportType.UNKNOWN,
                filename=filename,
                row_number=1,
                source_column="<headers>",
                field_name="report_type",
                reason="does not match a supported Tradovate schema.",
            )
        )
    else:
        normalize_report_rows(report)
    return report


def optional_decimal(
    value: str | None,
    *,
    report_type: ReportType = ReportType.UNKNOWN,
    filename: str = "<unknown>",
    row_number: int = 0,
    source_column: str = "<value>",
    field_name: str = "value",
) -> Decimal | None:
    cleaned = (value or "").strip()
    if cleaned.casefold() in {"", "nan", "n/a", "null", "none", "undefined"}:
        return None
    negative = cleaned.startswith("$(") and cleaned.endswith(")")
    cleaned = cleaned.replace("$", "").replace(",", "").replace("(", "").replace(")", "")
    try:
        result = Decimal(cleaned)
    except InvalidOperation as exc:
        raise ImportValidationError(
            report_type=report_type,
            filename=filename,
            row_number=row_number,
            source_column=source_column,
            field_name=field_name,
            reason="must be a valid decimal value.",
        ) from exc
    if not result.is_finite():
        raise ImportValidationError(
            report_type=report_type,
            filename=filename,
            row_number=row_number,
            source_column=source_column,
            field_name=field_name,
            reason="must be a finite decimal value.",
        )
    return -result if negative else result


def required_decimal(
    value: str | None,
    *,
    report_type: ReportType = ReportType.UNKNOWN,
    filename: str = "<unknown>",
    row_number: int = 0,
    source_column: str = "<value>",
    field_name: str = "value",
) -> Decimal:
    result = optional_decimal(
        value,
        report_type=report_type,
        filename=filename,
        row_number=row_number,
        source_column=source_column,
        field_name=field_name,
    )
    if result is None:
        raise ImportValidationError(
            report_type=report_type,
            filename=filename,
            row_number=row_number,
            source_column=source_column,
            field_name=field_name,
            reason="is required but blank or unavailable.",
        )
    return result


def money(value: str | None, *, required: bool = True) -> Decimal | None:
    """Backward-compatible decimal helper for reconciliation code."""
    return required_decimal(value) if required else optional_decimal(value)


def parse_datetime(value: str, timezone_name: str = "America/New_York") -> datetime:
    value = value.strip()
    if value.endswith("Z"):
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    for fmt in ("%m/%d/%Y %H:%M:%S", "%m/%d/%y %H:%M:%S"):
        try:
            local = datetime.strptime(value, fmt).replace(tzinfo=ZoneInfo(timezone_name))
            return local.astimezone(timezone.utc)
        except ValueError:
            continue
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo(timezone_name))
    return parsed.astimezone(timezone.utc)


def parse_date(value: str) -> date:
    value = value.strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Invalid date: {value!r}")


def parse_duration(value: str) -> int | None:
    if not value.strip():
        return None
    matches = dict(
        (unit, int(amount))
        for amount, unit in re.findall(r"(\d+)\s*(h|min|sec)", value.lower())
    )
    if not matches:
        raise ValueError(f"Invalid duration: {value!r}")
    return matches.get("h", 0) * 3600 + matches.get("min", 0) * 60 + matches.get("sec", 0)


def row_get(row: dict[str, str], *names: str) -> str:
    normalized = {normalize_header(key): value for key, value in row.items()}
    for name in names:
        value = normalized.get(normalize_header(name))
        if value is not None:
            return value.strip()
    return ""


class _RowReader:
    def __init__(self, report: ParsedReport, row: dict[str, str], row_number: int) -> None:
        self.report = report
        self.row = row
        self.row_number = row_number

    def source(self, *names: str) -> tuple[str, str]:
        normalized = {
            normalize_header(key): (key, (value or "").strip())
            for key, value in self.row.items()
        }
        first_present: tuple[str, str] | None = None
        for name in names:
            found = normalized.get(normalize_header(name))
            if found is None:
                continue
            if first_present is None:
                first_present = found
            if found[1]:
                return found[1], found[0]
        if first_present:
            return first_present[1], first_present[0]
        return "", names[0]

    def required_text(self, field_name: str, *columns: str) -> str:
        value, source_column = self.source(*columns)
        if not value:
            raise self.error(
                source_column, field_name, "is required but blank or unavailable."
            )
        return value

    def optional_text(self, *columns: str) -> str | None:
        value, _ = self.source(*columns)
        return value or None

    def required_decimal(self, field_name: str, *columns: str) -> Decimal:
        value, source_column = self.source(*columns)
        return required_decimal(
            value,
            report_type=self.report.report_type,
            filename=self.report.filename,
            row_number=self.row_number,
            source_column=source_column,
            field_name=field_name,
        )

    def optional_decimal(self, field_name: str, *columns: str) -> Decimal | None:
        value, source_column = self.source(*columns)
        return optional_decimal(
            value,
            report_type=self.report.report_type,
            filename=self.report.filename,
            row_number=self.row_number,
            source_column=source_column,
            field_name=field_name,
        )

    def required_datetime(
        self, field_name: str, *columns: str, timezone_name: str = "America/New_York"
    ) -> datetime:
        value, source_column = self.source(*columns)
        if not value:
            raise self.error(
                source_column, field_name, "is required but blank or unavailable."
            )
        try:
            return parse_datetime(value, timezone_name)
        except (TypeError, ValueError) as exc:
            raise self.error(
                source_column, field_name, "must be a valid timestamp."
            ) from exc

    def optional_datetime(
        self, field_name: str, *columns: str, timezone_name: str = "America/New_York"
    ) -> datetime | None:
        value, source_column = self.source(*columns)
        if not value:
            return None
        try:
            return parse_datetime(value, timezone_name)
        except (TypeError, ValueError) as exc:
            raise self.error(
                source_column, field_name, "must be a valid timestamp."
            ) from exc

    def required_date(self, field_name: str, *columns: str) -> date:
        value, source_column = self.source(*columns)
        if not value:
            raise self.error(
                source_column, field_name, "is required but blank or unavailable."
            )
        try:
            return parse_date(value)
        except ValueError as exc:
            raise self.error(source_column, field_name, "must be a valid date.") from exc

    def error(
        self, source_column: str, field_name: str, reason: str
    ) -> ImportValidationError:
        return ImportValidationError(
            report_type=self.report.report_type,
            filename=self.report.filename,
            row_number=self.row_number,
            source_column=source_column,
            field_name=field_name,
            reason=reason,
        )


def normalize_report_rows(report: ParsedReport) -> None:
    for row_number, row in enumerate(report.rows, start=2):
        try:
            normalized = _normalize_row(report, row, row_number)
        except ImportValidationError as error:
            report.errors.append(error)
        else:
            if normalized is not None:
                report.normalized_rows.append(normalized)


def _normalize_row(
    report: ParsedReport, row: dict[str, str], row_number: int
) -> NormalizedRow | None:
    reader = _RowReader(report, row, row_number)
    if report.report_type is ReportType.PERFORMANCE:
        return NormalizedPerformanceRow(
            row_number=row_number,
            source_payload=row,
            quantity=reader.required_decimal("quantity", "qty"),
            buy_price=reader.required_decimal("buy_price", "buyPrice"),
            sell_price=reader.required_decimal("sell_price", "sellPrice"),
            pnl=reader.required_decimal("pnl", "pnl"),
            bought_timestamp=reader.required_datetime(
                "bought_timestamp", "boughtTimestamp"
            ),
            sold_timestamp=reader.required_datetime(
                "sold_timestamp", "soldTimestamp"
            ),
        )
    if report.report_type is ReportType.POSITION_HISTORY:
        net_position = reader.required_decimal("net_position", "Net Pos")
        net_price = reader.optional_decimal("net_price", "Net Price")
        if net_position != 0 and net_price is None:
            _, source_column = reader.source("Net Price")
            raise reader.error(
                source_column,
                "net_price",
                "is required for a non-flat position.",
            )
        return NormalizedPositionRow(
            row_number=row_number,
            source_payload=row,
            net_position=net_position,
            net_price=net_price,
            paired_quantity=reader.required_decimal("paired_quantity", "Paired Qty"),
            buy_price=reader.required_decimal("buy_price", "Buy Price"),
            sell_price=reader.required_decimal("sell_price", "Sell Price"),
            pnl=reader.required_decimal("pnl", "P/L"),
            bought_timestamp=reader.required_datetime(
                "bought_timestamp", "Bought Timestamp"
            ),
            sold_timestamp=reader.required_datetime(
                "sold_timestamp", "Sold Timestamp"
            ),
        )
    if report.report_type is ReportType.FILLS:
        action = reader.optional_text("B/S")
        if not action:
            raw_action = reader.required_text("action", "_action")
            action = "buy" if raw_action == "0" else "sell"
        return NormalizedFillRow(
            row_number=row_number,
            source_payload=row,
            external_fill_id=reader.required_text("external_fill_id", "Fill ID", "_id"),
            external_order_id=reader.optional_text("Order ID", "_orderId"),
            symbol=reader.required_text("symbol", "Contract"),
            action=action.casefold(),
            quantity=reader.required_decimal("quantity", "Quantity", "_qty"),
            price=reader.required_decimal("price", "Price", "_price"),
            commission=reader.optional_decimal("commission", "commission"),
            timestamp=reader.required_datetime("timestamp", "_timestamp", "Timestamp"),
            trade_date=reader.required_date("trade_date", "_tradeDate", "Date"),
            product=reader.optional_text("Product"),
            product_description=reader.optional_text("Product Description"),
        )
    if report.report_type is ReportType.ORDERS:
        return NormalizedOrderRow(
            row_number=row_number,
            source_payload=row,
            external_order_id=reader.required_text(
                "external_order_id", "Order ID", "orderId"
            ),
            side=reader.required_text("side", "B/S").casefold(),
            symbol=reader.required_text("symbol", "Contract"),
            order_type=(
                value.casefold() if (value := reader.optional_text("Type")) else None
            ),
            status=reader.required_text("status", "Status").casefold(),
            text=reader.optional_text("Text"),
            requested_quantity=reader.required_decimal(
                "requested_quantity", "Quantity"
            ),
            filled_quantity=reader.optional_decimal(
                "filled_quantity", "Filled Qty", "filledQty"
            ),
            limit_price=reader.optional_decimal(
                "limit_price", "Limit Price", "decimalLimit"
            ),
            stop_price=reader.optional_decimal(
                "stop_price", "Stop Price", "decimalStop"
            ),
            average_fill_price=reader.optional_decimal(
                "average_fill_price",
                "Avg Fill Price",
                "decimalFillAvg",
                "avgPrice",
            ),
            notional_value=reader.optional_decimal(
                "notional_value", "Notional Value"
            ),
            venue=reader.optional_text("Venue"),
            currency=reader.optional_text("Currency"),
            submitted_timestamp=reader.optional_datetime(
                "submitted_timestamp", "Timestamp"
            ),
            fill_timestamp=reader.optional_datetime("fill_timestamp", "Fill Time"),
        )
    if report.report_type is ReportType.CASH_HISTORY:
        return NormalizedCashRow(
            row_number=row_number,
            source_payload=row,
            external_transaction_id=reader.required_text(
                "external_transaction_id", "Transaction ID"
            ),
            timestamp=reader.required_datetime("timestamp", "Timestamp"),
            trade_date=reader.required_date("trade_date", "Date"),
            delta=reader.required_decimal("delta", "Delta"),
            amount=reader.required_decimal("amount", "Amount"),
            cash_change_type=reader.required_text(
                "cash_change_type", "Cash Change Type"
            ),
            currency=reader.optional_text("Currency"),
            contract=reader.optional_text("Contract"),
        )
    if report.report_type is ReportType.BALANCE_HISTORY:
        return NormalizedBalanceRow(
            row_number=row_number,
            source_payload=row,
            trade_date=reader.required_date("trade_date", "Trade Date"),
            total_amount=reader.required_decimal("total_amount", "Total Amount"),
            total_realized_pnl=reader.required_decimal(
                "total_realized_pnl", "Total Realized PNL"
            ),
            source_account_id=reader.optional_text("Account ID"),
            source_account_name=reader.optional_text("Account Name"),
        )
    return None


def exact_duplicate_count(rows: list[dict[str, str]]) -> int:
    seen: set[tuple[tuple[str, str], ...]] = set()
    duplicates = 0
    for row in rows:
        marker = tuple(sorted(row.items()))
        if marker in seen:
            duplicates += 1
        else:
            seen.add(marker)
    return duplicates


def detected_accounts(report: ParsedReport) -> set[str]:
    key = "Account Name" if report.report_type is ReportType.BALANCE_HISTORY else "Account"
    return {row_get(row, key) for row in report.rows if row_get(row, key)}


def report_date_coverage(report: ParsedReport) -> tuple[date | None, date | None]:
    dates: list[date] = []
    for row in report.rows:
        raw = row_get(
            row,
            "Trade Date",
            "_tradeDate",
            "Date",
            "boughtTimestamp",
            "Bought Timestamp",
        )
        if not raw:
            continue
        try:
            dates.append(parse_date(raw.split(" ")[0]))
        except ValueError:
            try:
                dates.append(parse_datetime(raw).date())
            except ValueError:
                continue
    return (min(dates), max(dates)) if dates else (None, None)


def json_safe_row(row: dict[str, Any]) -> dict[str, Any]:
    return {key: str(value) if isinstance(value, Decimal) else value for key, value in row.items()}
