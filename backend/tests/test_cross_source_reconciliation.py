from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.database import Base
from app.domain import TradeSide
from app.models import (
    AccountType,
    Fill,
    ImportFile,
    ImportSession,
    ImportStatus,
    Trade,
    TradingAccount,
    User,
)
from app.services.import_sessions import build_preview, commit_import
from app.services.importer import exact_duplicate_count, parse_report


class MemoryStorage:
    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}

    def read(self, key: str) -> bytes:
        return self.files[key]


def _source_reports():
    performance = (
        "symbol,_priceFormat,_priceFormatType,_tickSize,buyFillId,sellFillId,qty,"
        "buyPrice,sellPrice,pnl,boughtTimestamp,soldTimestamp,duration\n"
        "MNQZ6,-2,0,0.25,B1,S1,2,30566.25,30567.00,$3.00,"
        "09/28/2026 10:28:51,09/28/2026 10:21:35,7min 16sec\n"
    ).encode()
    fills = (
        "_id,_orderId,_timestamp,_tradeDate,Fill ID,Order ID,Timestamp,Account,B/S,"
        "Quantity,Price,_tickSize,Contract,Product,Product Description,commission\n"
        "S1,OS,2026-09-28 14:21:35.644Z,2026-09-28,S1,OS,09/28/2026 10:21:35,"
        "LFE05085094850003,Sell,2,30567.00,0.25,MNQZ6,MNQ,Micro E-mini NASDAQ-100,1.0\n"
        "B1,OB,2026-09-28 14:28:51.493Z,2026-09-28,B1,OB,09/28/2026 10:28:51,"
        "LFE05085094850003,Buy,2,30566.25,0.25,MNQZ6,MNQ,Micro E-mini NASDAQ-100,1.0\n"
    ).encode()
    return [
        ("Performance.csv", performance, parse_report("Performance.csv", performance)),
        ("Fills.csv", fills, parse_report("Fills.csv", fills)),
    ]


def test_tradovate_import_enriches_live_trade_and_collapses_legacy_pair() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    storage = MemoryStorage()

    with Session(engine) as db:
        user = User(email="reconcile@journalme.local", display_name="Trader")
        db.add(user)
        db.flush()
        account = TradingAccount(
            user_id=user.id,
            name="Lucid Flex 50K",
            external_account_id="LFE05085094850003",
            provider="tradovate",
            account_type=AccountType.EVALUATION,
            starting_balance=Decimal("50000"),
        )
        db.add(account)
        db.flush()

        live_trade = Trade(
            account_id=account.id,
            duplicate_fingerprint="live-execution-fingerprint",
            symbol="MNQ 12-26",
            root_symbol="MNQ",
            contract_quantity=Decimal("2"),
            side=TradeSide.SHORT,
            entry_price=Decimal("30567.00"),
            exit_price=Decimal("30566.25"),
            gross_pnl=Decimal("3.00"),
            fees=None,
            net_pnl=Decimal("3.00"),
            currency="USD",
            entry_timestamp=datetime(2026, 9, 28, 14, 21, 35, 644000, tzinfo=timezone.utc),
            exit_timestamp=datetime(2026, 9, 28, 14, 28, 51, 493000, tzinfo=timezone.utc),
            duration_seconds=435,
            source_quality="broker_live",
            reconciliation_status="live_fees_pending",
            source_payload={"source": "broker_live", "execution_ids": ["NT1", "NT2"]},
        )
        db.add(live_trade)
        db.flush()

        # Represents the old importer behavior: one Tradovate lot-pair row as a
        # second JournalMe trade for the same real position lifecycle.
        legacy_pair = Trade(
            account_id=account.id,
            duplicate_fingerprint="legacy-pair-fingerprint",
            external_buy_fill_id="B1",
            external_sell_fill_id="S1",
            symbol="MNQZ6",
            root_symbol="MNQ",
            contract_quantity=Decimal("2"),
            side=TradeSide.SHORT,
            entry_price=Decimal("30567.00"),
            exit_price=Decimal("30566.25"),
            gross_pnl=Decimal("3.00"),
            fees=Decimal("2.00"),
            net_pnl=Decimal("1.00"),
            currency="USD",
            entry_timestamp=live_trade.entry_timestamp,
            exit_timestamp=live_trade.exit_timestamp,
            duration_seconds=435,
            source_quality="paired_report",
            reconciliation_status="reconciled",
            source_payload={"fill_ids": ["B1", "S1"]},
        )
        db.add(legacy_pair)
        db.flush()

        sources = _source_reports()
        batch = ImportSession(
            user_id=user.id,
            account_id=account.id,
            source_provider="tradovate",
            status=ImportStatus.READY,
            file_count=len(sources),
        )
        db.add(batch)
        db.flush()
        for filename, content, report in sources:
            key = f"{batch.id}/{filename}"
            storage.files[key] = content
            batch.files.append(
                ImportFile(
                    filename=filename,
                    detected_report_type=report.report_type.value,
                    content_hash=report.content_hash,
                    row_count=len(report.rows),
                    valid_count=len(report.normalized_rows),
                    duplicate_count=exact_duplicate_count(report.rows),
                    error_count=len(report.errors),
                    status="ready",
                    stored_path=key,
                    header_signature=report.header_signature,
                )
            )
        db.commit()

        reports = [item[2] for item in sources]
        preview = build_preview(reports, db, account)
        assert preview["canonical_trades"] == 1
        assert preview["new_trades"] == 0
        assert preview["existing_trades"] == 1

        created = commit_import(db, user, batch, storage)
        db.commit()
        assert created["trades"] == 0
        assert batch.summary_json["reconciled_trades"] == 1
        assert batch.summary_json["collapsed_legacy_trades"] == 1

        trades = list(db.scalars(select(Trade).where(Trade.account_id == account.id)).all())
        assert len(trades) == 1
        trade = trades[0]
        assert trade.id == live_trade.id
        assert trade.symbol == "MNQ 12-26"
        assert trade.duplicate_fingerprint == "live-execution-fingerprint"
        assert trade.source_quality == "multi_source_reconciled"
        assert trade.reconciliation_status == "reconciled"
        assert trade.gross_pnl == Decimal("3.0000")
        assert trade.fees == Decimal("2.0000")
        assert trade.net_pnl == Decimal("1.0000")
        assert trade.external_buy_fill_id == "B1"
        assert trade.external_sell_fill_id == "S1"

        stored_fills = list(db.scalars(select(Fill).where(Fill.account_id == account.id)).all())
        assert len(stored_fills) == 2
        assert {fill.trade_id for fill in stored_fills} == {trade.id}
