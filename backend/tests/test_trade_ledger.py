from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.database import Base
from app.domain import TradeSide
from app.models import Fill, ImportFile, ImportSession, Trade, TradingAccount, User
from app.services.trade_ledger import reconcile_trade_ledger


def _trade(account_id, *, buy: str, sell: str, qty: str, pnl: str, entry: str, exit: str) -> Trade:
    return Trade(
        account_id=account_id,
        duplicate_fingerprint=f"fp-{buy}-{sell}",
        external_buy_fill_id=buy,
        external_sell_fill_id=sell,
        symbol="MNQZ6",
        root_symbol="MNQ",
        contract_quantity=Decimal(qty),
        side=TradeSide.SHORT,
        entry_price=Decimal("30723.25"),
        exit_price=Decimal("30722.50"),
        gross_pnl=Decimal(pnl),
        fees=None,
        net_pnl=Decimal(pnl),
        entry_timestamp=datetime.fromisoformat(entry).replace(tzinfo=timezone.utc),
        exit_timestamp=datetime.fromisoformat(exit).replace(tzinfo=timezone.utc),
        duration_seconds=25,
        source_quality="paired_report",
        reconciliation_status="reconciled",
        source_payload={"fill_ids": [buy, sell]},
    )


def test_ledger_uses_fills_to_collapse_lot_pairs_into_one_position_lifecycle() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = User(email="ledger@example.com", display_name="Ledger")
        db.add(user); db.flush()
        account = TradingAccount(user_id=user.id, name="Evaluation", provider="tradovate")
        db.add(account); db.flush()
        session = ImportSession(user_id=user.id, account_id=account.id)
        db.add(session); db.flush()
        source = ImportFile(import_session_id=session.id, filename="Fills.csv", detected_report_type="fills", content_hash="hash", stored_path="x", header_signature="x")
        db.add(source); db.flush()

        # One 20-contract short position, represented in Performance as two lot
        # pair rows (1 + 19). The fill stream proves it was one lifecycle.
        db.add_all([
            Fill(account_id=account.id, import_file_id=source.id, external_fill_id="s1", external_order_id="os", symbol="MNQZ6", action="Sell", quantity=Decimal("1"), price=Decimal("30723.50"), commission=Decimal("0.5"), timestamp=datetime(2026,9,28,2,18,43,tzinfo=timezone.utc), trade_date=date(2026,9,28), source_payload={}),
            Fill(account_id=account.id, import_file_id=source.id, external_fill_id="s2", external_order_id="os", symbol="MNQZ6", action="Sell", quantity=Decimal("19"), price=Decimal("30723.25"), commission=Decimal("9.5"), timestamp=datetime(2026,9,28,2,18,43,tzinfo=timezone.utc), trade_date=date(2026,9,28), source_payload={}),
            Fill(account_id=account.id, import_file_id=source.id, external_fill_id="b1", external_order_id="ob", symbol="MNQZ6", action="Buy", quantity=Decimal("1"), price=Decimal("30722.50"), commission=Decimal("0.5"), timestamp=datetime(2026,9,28,2,19,7,tzinfo=timezone.utc), trade_date=date(2026,9,28), source_payload={}),
            Fill(account_id=account.id, import_file_id=source.id, external_fill_id="b2", external_order_id="ob", symbol="MNQZ6", action="Buy", quantity=Decimal("19"), price=Decimal("30723.50"), commission=Decimal("9.5"), timestamp=datetime(2026,9,28,2,19,8,tzinfo=timezone.utc), trade_date=date(2026,9,28), source_payload={}),
        ])
        db.add_all([
            _trade(account.id, buy="b1", sell="s1", qty="1", pnl="2", entry="2026-09-28T02:18:43", exit="2026-09-28T02:19:07"),
            _trade(account.id, buy="b2", sell="s2", qty="19", pnl="-9.5", entry="2026-09-28T02:18:43", exit="2026-09-28T02:19:08"),
        ])
        db.flush()

        report = reconcile_trade_ledger(db, account)
        rows = list(db.scalars(select(Trade).where(Trade.account_id == account.id)).all())
        assert report["collapsed_trade_rows"] == 1
        assert report["fill_lifecycles"] == 1
        assert len(rows) == 1
        assert rows[0].source_quality == "ledger_reconciled"
        assert rows[0].contract_quantity == Decimal("20")
        assert rows[0].gross_pnl == Decimal("-7.5")
        assert rows[0].fees == Decimal("20.0")
        assert rows[0].net_pnl == Decimal("-27.5")
        assert rows[0].reconciliation_status == "reconciled"
