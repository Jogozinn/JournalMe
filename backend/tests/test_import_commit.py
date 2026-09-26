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
from app.services.import_sessions import build_preview, commit_import
from app.services.importer import (
    NormalizedOrderRow,
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
        assert preview["canonical_trades"] == 12
        assert preview["new_trades"] == 12
        assert preview["duplicate_rows"] == 1
        assert preview["unmatched_fills"] == 0
        assert preview["linked_filled_orders"] == 24
        assert preview["canceled_unfilled_orders"] == 13
        assert preview["unmatched_filled_orders"] == 0

        first_batch = _import_session(db, storage, account, reports)
        db.commit()
        first_counts = commit_import(db, user, first_batch, storage)
        db.commit()
        assert first_counts == {
            "trades": 12,
            "fills": 25,
            "orders": 37,
            "cash_transactions": 39,
            "daily_balances": 4,
        }
        assert db.scalar(select(func.count()).select_from(Trade)) == 12
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
        assert second_preview["existing_trades"] == 12
        second_counts = commit_import(db, user, second_batch, storage)
        db.commit()
        assert second_counts == {
            "trades": 0,
            "fills": 0,
            "orders": 0,
            "cash_transactions": 0,
            "daily_balances": 0,
        }
        assert db.scalar(select(func.count()).select_from(Trade)) == 12
        assert db.scalar(select(func.count()).select_from(Order)) == 37
