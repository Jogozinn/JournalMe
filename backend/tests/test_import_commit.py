from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.database import Base
from app.models import (
    CashTransaction,
    DailyBalance,
    Fill,
    ImportFile,
    ImportSession,
    ImportStatus,
    Order,
    Trade,
    TradingAccount,
    User,
)
from app.services.import_sessions import (
    _persist_balances,
    _persist_cash,
    _persist_fills,
    build_preview,
    commit_import,
)
from app.services.importer import (
    NormalizedBalanceRow,
    NormalizedCashRow,
    NormalizedFillRow,
    NormalizedOrderRow,
    ParsedReport,
    ReportType,
    exact_duplicate_count,
    parse_report,
)

SOURCE_FILENAMES = [
    "Performance.csv",
    "Position History.csv",
    "Fills.csv",
    "Orders (1).csv",
    "Cash History.csv",
    "Account Balance History.csv",
    "Order Details.csv",
]


class MemoryStorage:
    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}

    def save(self, session_id, filename: str, content: bytes) -> str:
        key = f"{session_id}/{filename}"
        self.files[key] = content
        return key

    def read(self, storage_key: str) -> bytes:
        return self.files[storage_key]

    def delete(self, storage_key: str) -> None:
        self.files.pop(storage_key, None)


def _reports(root: Path):
    missing = [name for name in SOURCE_FILENAMES if not (root / name).exists()]
    if missing:
        pytest.skip(f"Supplied Tradovate reports are unavailable: {missing}")
    return [
        parse_report(name, (root / name).read_bytes()) for name in SOURCE_FILENAMES
    ]


def _import_session(
    db: Session,
    storage: MemoryStorage,
    account: TradingAccount,
    reports,
) -> ImportSession:
    batch = ImportSession(
        account_id=account.id,
        source_provider="tradovate",
        status=ImportStatus.READY,
        file_count=len(reports),
    )
    db.add(batch)
    db.flush()
    for report in reports:
        content = (Path(__file__).resolve().parents[2] / report.filename).read_bytes()
        batch.files.append(
            ImportFile(
                filename=report.filename,
                detected_report_type=report.report_type.value,
                content_hash=report.content_hash,
                row_count=len(report.rows),
                valid_count=len(report.normalized_rows),
                duplicate_count=exact_duplicate_count(report.rows),
                error_count=len(report.errors),
                status=(
                    "skipped"
                    if report.report_type is ReportType.ORDER_DETAILS_EMPTY
                    else "ready"
                ),
                stored_path=storage.save(batch.id, report.filename, content),
                header_signature=report.header_signature,
            )
        )
    db.flush()
    return batch


def test_real_seven_file_commit_and_reupload_are_atomic_and_idempotent() -> None:
    root = Path(__file__).resolve().parents[2]
    reports = _reports(root)
    assert all(not report.errors for report in reports)

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    storage = MemoryStorage()
    with Session(engine) as db:
        user = User(email="masked@journalme.local", display_name="Trader")
        db.add(user)
        db.flush()
        account = TradingAccount(
            user_id=user.id,
            name="Regression account",
            provider="tradovate",
            starting_balance=50000,
        )
        db.add(account)
        db.flush()

        preview = build_preview(reports, db, account)
        # Fills now define JournalMe trades by flat -> position -> flat lifecycle.
        # This sanitized fixture contains 9 completed position lifecycles, not 12 lot-pair groups.
        assert preview["canonical_trades"] == 9
        assert preview["new_trades"] == 9
        assert preview["duplicate_rows"] == 0
        assert preview["unmatched_fills"] == 0
        assert preview["linked_filled_orders"] == 24
        assert preview["canceled_unfilled_orders"] == 13
        assert preview["unmatched_filled_orders"] == 0

        first_batch = _import_session(db, storage, account, reports)
        db.commit()
        first_counts = commit_import(db, user, first_batch, storage)
        db.commit()
        assert first_counts == {
            "trades": 9,
            "fills": 25,
            "orders": 37,
            "cash_transactions": 39,
            "daily_balances": 4,
        }
        assert db.scalar(select(func.count()).select_from(Trade)) == 9
        assert db.scalar(select(func.count()).select_from(Fill)) == 25
        assert db.scalar(select(func.count()).select_from(Order)) == 37
        assert (
            db.scalar(
                select(func.count())
                .select_from(Order)
                .where(Order.status == "filled")
            )
            == 24
        )
        assert (
            db.scalar(
                select(func.count())
                .select_from(Order)
                .where(Order.status != "filled")
            )
            == 13
        )
        assert (
            db.scalar(
                select(func.count())
                .select_from(Order)
                .where(Order.filled_quantity.is_(None))
            )
            == 13
        )
        assert db.scalar(select(func.count()).select_from(CashTransaction)) == 39
        assert db.scalar(select(func.count()).select_from(DailyBalance)) == 4
        assert db.scalar(select(func.sum(Fill.commission))) == Decimal("28.8000")
        assert (
            db.scalar(
                select(func.count())
                .select_from(Fill)
                .where(Fill.trade_id.is_(None))
            )
            == 0
        )

        order_report = next(
            report for report in reports if report.report_type is ReportType.ORDERS
        )
        normalized_orders = [
            row
            for row in order_report.normalized_rows
            if isinstance(row, NormalizedOrderRow)
        ]
        canceled_ids = {
            row.external_order_id
            for row in normalized_orders
            if row.status != "filled"
        }
        fill_order_ids = set(
            db.scalars(select(Fill.external_order_id)).all()
        )
        assert len(canceled_ids - fill_order_ids) == 13

        second_batch = _import_session(db, storage, account, reports)
        db.commit()
        second_preview = build_preview(reports, db, account)
        assert second_preview["new_trades"] == 0
        assert second_preview["existing_trades"] == 9
        second_counts = commit_import(db, user, second_batch, storage)
        db.commit()
        assert second_counts == {
            "trades": 0,
            "fills": 0,
            "orders": 0,
            "cash_transactions": 0,
            "daily_balances": 0,
        }
        assert db.scalar(select(func.count()).select_from(Trade)) == 9
        assert db.scalar(select(func.count()).select_from(Order)) == 37


def test_same_date_balance_correction_is_versioned_and_exact_reimport_is_idempotent() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = User(email="balance-revision@journalme.local", display_name="Trader")
        db.add(user)
        db.flush()
        account = TradingAccount(
            user_id=user.id,
            name="Synthetic account fixture",
            external_account_id="TEST-TRADOVATE-ACCOUNT",
            provider="tradovate",
            starting_balance=50000,
        )
        db.add(account)
        db.flush()
        batch = ImportSession(user_id=user.id, account_id=account.id, status=ImportStatus.READY)
        db.add(batch)
        db.flush()
        source_file = ImportFile(
            import_session_id=batch.id,
            filename="Account Balance History.csv",
            detected_report_type=ReportType.BALANCE_HISTORY.value,
            content_hash="first",
            stored_path="first.csv",
            header_signature="first",
        )
        corrected_file = ImportFile(
            import_session_id=batch.id,
            filename="Account Balance History.csv",
            detected_report_type=ReportType.BALANCE_HISTORY.value,
            content_hash="corrected",
            stored_path="corrected.csv",
            header_signature="corrected",
        )
        db.add_all([source_file, corrected_file])
        db.flush()

        def report(amount: str, realized: str) -> ParsedReport:
            return ParsedReport(
                filename="Account Balance History.csv",
                report_type=ReportType.BALANCE_HISTORY,
                content_hash=amount,
                headers=[],
                rows=[],
                normalized_rows=[
                    NormalizedBalanceRow(
                        row_number=2,
                        source_payload={
                            "Account Name": "TEST-TRADOVATE-ACCOUNT",
                            "Total Amount": amount,
                        },
                        trade_date=date(2026, 10, 21),
                        total_amount=Decimal(amount),
                        total_realized_pnl=Decimal(realized),
                        source_account_id="TEST-TRADOVATE-ACCOUNT",
                        source_account_name="Synthetic account",
                    )
                ],
            )

        assert _persist_balances(db, account, source_file, report("1000.00", "0.00")) == 1
        db.flush()
        original = db.scalar(select(DailyBalance))
        assert original.revision == 1

        corrected = report("1012.50", "12.50")
        assert _persist_balances(db, account, corrected_file, corrected) == 1
        db.flush()
        latest = db.scalar(
            select(DailyBalance).order_by(DailyBalance.revision.desc())
        )
        assert latest.revision == 2
        assert latest.supersedes_id == original.id
        assert latest.import_file_id == corrected_file.id
        assert original.total_amount == Decimal("1000.00")
        assert original.source_payload == {
            "Account Name": "TEST-TRADOVATE-ACCOUNT",
            "Total Amount": "1000.00",
        }

        assert _persist_balances(db, account, corrected_file, corrected) == 0
        db.flush()
        assert db.scalar(select(func.count()).select_from(DailyBalance)) == 2


def test_fill_and_cash_reimports_require_full_source_identity() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = User(email="source-id@journalme.local", display_name="Trader")
        db.add(user)
        db.flush()
        account = TradingAccount(
            user_id=user.id,
            name="Synthetic account fixture",
            external_account_id="TEST-TRADOVATE-ACCOUNT",
            provider="tradovate",
            starting_balance=50000,
        )
        db.add(account)
        db.flush()
        batch = ImportSession(user_id=user.id, account_id=account.id)
        db.add(batch)
        db.flush()
        source_file = ImportFile(
            import_session_id=batch.id,
            filename="Fills (3).csv",
            detected_report_type=ReportType.FILLS.value,
            content_hash="report-hash",
            stored_path="private/fills.csv",
            header_signature="header-hash",
        )
        cash_file = ImportFile(
            import_session_id=batch.id,
            filename="Cash History (3).csv",
            detected_report_type=ReportType.CASH_HISTORY.value,
            content_hash="cash-hash",
            stored_path="private/cash.csv",
            header_signature="header-hash",
        )
        db.add_all([source_file, cash_file])
        db.flush()
        timestamp = datetime(2026, 10, 22, 14, 30, tzinfo=timezone.utc)
        fill = Fill(
            account_id=account.id,
            import_file_id=source_file.id,
            external_fill_id="test-fill-001",
            external_order_id="order-1",
            symbol="MNQZ6",
            action="buy",
            quantity=Decimal("1"),
            price=Decimal("25000"),
            commission=Decimal("2.50"),
            timestamp=timestamp,
            trade_date=date(2026, 10, 22),
            product="MNQ",
            product_description="Micro E-mini Nasdaq-100",
            source_payload={"Account": "TEST-TRADOVATE-ACCOUNT"},
        )
        cash = CashTransaction(
            account_id=account.id,
            import_file_id=cash_file.id,
            external_transaction_id="cash-1",
            timestamp=timestamp,
            trade_date=date(2026, 10, 22),
            delta=Decimal("-2.50"),
            amount=Decimal("2.50"),
            cash_change_type="Commission",
            currency="USD",
            contract="MNQZ6",
            source_payload={"Account": "TEST-TRADOVATE-ACCOUNT"},
        )
        db.add_all([fill, cash])
        db.flush()

        def fill_report(*, price: str = "25000", commission: str = "2.50"):
            return ParsedReport(
                filename="Fills (3).csv",
                report_type=ReportType.FILLS,
                content_hash="report-hash",
                headers=[],
                rows=[],
                normalized_rows=[
                    NormalizedFillRow(
                        row_number=2,
                        source_payload={"Account": "TEST-TRADOVATE-ACCOUNT"},
                        external_fill_id="test-fill-001",
                        external_order_id="order-1",
                        symbol="MNQZ6",
                        action="buy",
                        quantity=Decimal("1"),
                        price=Decimal(price),
                        commission=Decimal(commission),
                        timestamp=timestamp,
                        trade_date=date(2026, 10, 22),
                        product="MNQ",
                        product_description="Micro E-mini Nasdaq-100",
                    )
                ],
            )

        def cash_report(*, delta: str = "-2.50"):
            return ParsedReport(
                filename="Cash History (3).csv",
                report_type=ReportType.CASH_HISTORY,
                content_hash="cash-hash",
                headers=[],
                rows=[],
                normalized_rows=[
                    NormalizedCashRow(
                        row_number=2,
                        source_payload={"Account": "TEST-TRADOVATE-ACCOUNT"},
                        external_transaction_id="cash-1",
                        timestamp=timestamp,
                        trade_date=date(2026, 10, 22),
                        delta=Decimal(delta),
                        amount=Decimal("2.50"),
                        cash_change_type="Commission",
                        currency="USD",
                        contract="MNQZ6",
                    )
                ],
            )

        assert _persist_fills(db, account, source_file, fill_report(), {}) == 0
        assert _persist_cash(db, account, cash_file, cash_report()) == 0
        with pytest.raises(ValueError, match="Fill test-fill-001.*conflicting source attributes"):
            _persist_fills(db, account, source_file, fill_report(price="25000.25"), {})
        with pytest.raises(
            ValueError, match="Cash transaction cash-1.*conflicting source attributes"
        ):
            _persist_cash(db, account, cash_file, cash_report(delta="-3.50"))
