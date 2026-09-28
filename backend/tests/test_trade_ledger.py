from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.database import Base
from app.domain import TradeSide
from app.models import BrokerConnection, BrokerExecutionEvent, Fill, ImportFile, ImportSession, Trade, TradingAccount, User
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



def _broker_trade(account_id, *, execution_ids: list[str], qty: str, entry: str, exit: str, pnl: str) -> Trade:
    return Trade(
        account_id=account_id,
        duplicate_fingerprint=f"live-{'-'.join(execution_ids)}-{qty}",
        symbol="MNQ 12-26",
        root_symbol="MNQ",
        contract_quantity=Decimal(qty),
        side=TradeSide.SHORT,
        entry_price=Decimal("30723.25"),
        exit_price=Decimal("30723.50"),
        gross_pnl=Decimal(pnl),
        fees=None,
        net_pnl=Decimal(pnl),
        entry_timestamp=datetime.fromisoformat(entry).replace(tzinfo=timezone.utc),
        exit_timestamp=datetime.fromisoformat(exit).replace(tzinfo=timezone.utc),
        duration_seconds=25,
        source_quality="broker_live",
        reconciliation_status="live_fees_pending",
        source_payload={"source": "broker_live", "execution_ids": execution_ids},
    )


def test_ledger_reconstructs_live_execution_namespace_and_collapses_partial_rows() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = User(email="live-ledger@example.com", display_name="Live Ledger")
        db.add(user); db.flush()
        account = TradingAccount(user_id=user.id, name="Evaluation", provider="tradovate")
        db.add(account); db.flush()
        connection = BrokerConnection(
            user_id=user.id,
            account_id=account.id,
            provider="ninjatrader",
            connection_type="desktop_bridge",
            display_name="NT",
            status="connected",
        )
        db.add(connection); db.flush()

        # One real short lifecycle. NinjaTrader may split the broker executions
        # differently from Tradovate, so these IDs must be reconciled in their
        # own namespace rather than compared with Tradovate fill IDs.
        events = [
            BrokerExecutionEvent(user_id=user.id, account_id=account.id, connection_id=connection.id, provider="ninjatrader", external_execution_id="nt-s1", symbol="MNQ 12-26", side="Sell", quantity=Decimal("1"), price=Decimal("30723.50"), commission=None, point_value=Decimal("2"), currency="USD", executed_at=datetime(2026,9,28,2,18,43,tzinfo=timezone.utc), source_payload={}),
            BrokerExecutionEvent(user_id=user.id, account_id=account.id, connection_id=connection.id, provider="ninjatrader", external_execution_id="nt-s19", symbol="MNQ 12-26", side="Sell", quantity=Decimal("19"), price=Decimal("30723.25"), commission=None, point_value=Decimal("2"), currency="USD", executed_at=datetime(2026,9,28,2,18,43,tzinfo=timezone.utc), source_payload={}),
            BrokerExecutionEvent(user_id=user.id, account_id=account.id, connection_id=connection.id, provider="ninjatrader", external_execution_id="nt-b1", symbol="MNQ 12-26", side="Buy", quantity=Decimal("1"), price=Decimal("30722.50"), commission=None, point_value=Decimal("2"), currency="USD", executed_at=datetime(2026,9,28,2,19,7,tzinfo=timezone.utc), source_payload={}),
            BrokerExecutionEvent(user_id=user.id, account_id=account.id, connection_id=connection.id, provider="ninjatrader", external_execution_id="nt-b19", symbol="MNQ 12-26", side="Buy", quantity=Decimal("19"), price=Decimal("30723.50"), commission=None, point_value=Decimal("2"), currency="USD", executed_at=datetime(2026,9,28,2,19,8,tzinfo=timezone.utc), source_payload={}),
        ]
        db.add_all(events)
        db.flush()

        # Simulate the legacy bad materialization: four rows describing pieces of
        # the same position. Their execution IDs are subsets of one round trip.
        db.add_all([
            _broker_trade(account.id, execution_ids=["nt-s1", "nt-b1"], qty="1", entry="2026-09-28T02:18:43", exit="2026-09-28T02:19:07", pnl="2"),
            _broker_trade(account.id, execution_ids=["nt-s19", "nt-b19"], qty="19", entry="2026-09-28T02:18:43", exit="2026-09-28T02:19:08", pnl="-9.5"),
            _broker_trade(account.id, execution_ids=["nt-s1", "nt-s19", "nt-b1"], qty="20", entry="2026-09-28T02:18:43", exit="2026-09-28T02:19:07", pnl="-6"),
            _broker_trade(account.id, execution_ids=["nt-s1", "nt-s19", "nt-b1", "nt-b19"], qty="20", entry="2026-09-28T02:18:43", exit="2026-09-28T02:19:08", pnl="-7.5"),
        ])
        db.flush()

        report = reconcile_trade_ledger(db, account)
        rows = list(db.scalars(select(Trade).where(Trade.account_id == account.id)).all())
        assert report["live_lifecycles"] == 1
        assert report["collapsed_trade_rows"] == 3
        assert len(rows) == 1
        assert rows[0].contract_quantity == Decimal("20")
        assert rows[0].gross_pnl == Decimal("-7.5")
        assert rows[0].fees is None
        assert rows[0].net_pnl == Decimal("-7.5")
        assert rows[0].source_payload["execution_ids"] == ["nt-b1", "nt-b19", "nt-s1", "nt-s19"]


def test_ledger_merges_live_execution_lifecycle_with_import_fill_lifecycle() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = User(email="cross-ledger@example.com", display_name="Cross Ledger")
        db.add(user); db.flush()
        account = TradingAccount(user_id=user.id, name="Evaluation", provider="tradovate")
        db.add(account); db.flush()
        connection = BrokerConnection(
            user_id=user.id,
            account_id=account.id,
            provider="ninjatrader",
            connection_type="desktop_bridge",
            display_name="NT",
            status="connected",
        )
        db.add(connection); db.flush()
        session = ImportSession(user_id=user.id, account_id=account.id)
        db.add(session); db.flush()
        source = ImportFile(import_session_id=session.id, filename="Fills.csv", detected_report_type="fills", content_hash="hash-cross", stored_path="x", header_signature="x")
        db.add(source); db.flush()

        db.add_all([
            BrokerExecutionEvent(user_id=user.id, account_id=account.id, connection_id=connection.id, provider="ninjatrader", external_execution_id="nt-s2", symbol="MNQ 12-26", side="Sell", quantity=Decimal("2"), price=Decimal("30785.125"), commission=None, point_value=Decimal("2"), currency="USD", executed_at=datetime(2026,9,28,1,25,2,tzinfo=timezone.utc), source_payload={}),
            BrokerExecutionEvent(user_id=user.id, account_id=account.id, connection_id=connection.id, provider="ninjatrader", external_execution_id="nt-b2", symbol="MNQ 12-26", side="Buy", quantity=Decimal("2"), price=Decimal("30813.25"), commission=None, point_value=Decimal("2"), currency="USD", executed_at=datetime(2026,9,28,1,30,12,tzinfo=timezone.utc), source_payload={}),
        ])
        live = _broker_trade(account.id, execution_ids=["nt-s2", "nt-b2"], qty="2", entry="2026-09-28T01:25:02", exit="2026-09-28T01:30:12", pnl="-112.5")
        live.entry_price = Decimal("30785.125")
        live.exit_price = Decimal("30813.25")
        db.add(live); db.flush()

        imported = _trade(account.id, buy="tv-b2", sell="tv-s2", qty="2", pnl="-112.5", entry="2026-09-28T01:25:02", exit="2026-09-28T01:30:12")
        imported.entry_price = Decimal("30785.125")
        imported.exit_price = Decimal("30813.25")
        imported.primary_import_session_id = session.id
        imported.source_payload = {"fill_ids": ["tv-s2", "tv-b2"]}
        db.add(imported); db.flush()

        sell_fill = Fill(account_id=account.id, import_file_id=source.id, external_fill_id="tv-s2", external_order_id="tv-os", trade_id=imported.id, symbol="MNQZ6", action="Sell", quantity=Decimal("2"), price=Decimal("30785.125"), commission=Decimal("1"), timestamp=datetime(2026,9,28,1,25,2,tzinfo=timezone.utc), trade_date=date(2026,9,28), source_payload={})
        buy_fill = Fill(account_id=account.id, import_file_id=source.id, external_fill_id="tv-b2", external_order_id="tv-ob", trade_id=imported.id, symbol="MNQZ6", action="Buy", quantity=Decimal("2"), price=Decimal("30813.25"), commission=Decimal("1"), timestamp=datetime(2026,9,28,1,30,12,tzinfo=timezone.utc), trade_date=date(2026,9,28), source_payload={})
        db.add_all([sell_fill, buy_fill]); db.flush()

        report = reconcile_trade_ledger(db, account)
        rows = list(db.scalars(select(Trade).where(Trade.account_id == account.id)).all())
        assert len(rows) == 1
        assert report["collapsed_trade_rows"] == 1
        assert rows[0].fees == Decimal("2")
        assert rows[0].net_pnl == Decimal("-114.5")
        assert set(rows[0].source_payload["ledger_fill_ids"]) == {"tv-b2", "tv-s2"}
        assert "nt-s2" not in rows[0].source_payload["ledger_fill_ids"]


def test_authoritative_import_fills_remove_phantom_live_bridge_lifecycle() -> None:
    """An incomplete live stream must not invent a trade between real broker trades.

    If the bridge starts after a real short trade is already open, the first live
    event may be that trade's BUY-to-flat. A naive flat-state reconstruction can
    mistake that exit for a new long entry and pair it with the next SELL entry.
    Complete Tradovate fill history is authoritative for that covered interval.
    """
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = User(email="phantom@example.com", display_name="Phantom")
        db.add(user); db.flush()
        account = TradingAccount(user_id=user.id, name="Evaluation", provider="tradovate")
        db.add(account); db.flush()
        connection = BrokerConnection(
            user_id=user.id,
            account_id=account.id,
            provider="ninjatrader",
            connection_type="desktop_bridge",
            display_name="NT",
            status="connected",
        )
        db.add(connection); db.flush()
        session = ImportSession(user_id=user.id, account_id=account.id)
        db.add(session); db.flush()
        source = ImportFile(
            import_session_id=session.id,
            filename="Fills.csv",
            detected_report_type="fills",
            content_hash="phantom-hash",
            stored_path="x",
            header_signature="x",
        )
        db.add(source); db.flush()

        # Two real broker trades from the authoritative fill stream.
        real_rows = [
            Fill(account_id=account.id, import_file_id=source.id, external_fill_id="t1-s1", external_order_id="o1", symbol="MNQZ6", action="Sell", quantity=Decimal("1"), price=Decimal("30785.25"), commission=Decimal("0.5"), timestamp=datetime(2026,9,28,1,25,2,tzinfo=timezone.utc), trade_date=date(2026,9,28), source_payload={}),
            Fill(account_id=account.id, import_file_id=source.id, external_fill_id="t1-s2", external_order_id="o1", symbol="MNQZ6", action="Sell", quantity=Decimal("1"), price=Decimal("30785.00"), commission=Decimal("0.5"), timestamp=datetime(2026,9,28,1,25,2,tzinfo=timezone.utc), trade_date=date(2026,9,28), source_payload={}),
            Fill(account_id=account.id, import_file_id=source.id, external_fill_id="t1-b", external_order_id="o2", symbol="MNQZ6", action="Buy", quantity=Decimal("2"), price=Decimal("30813.25"), commission=Decimal("1"), timestamp=datetime(2026,9,28,1,30,12,tzinfo=timezone.utc), trade_date=date(2026,9,28), source_payload={}),
            Fill(account_id=account.id, import_file_id=source.id, external_fill_id="t2-s", external_order_id="o3", symbol="MNQZ6", action="Sell", quantity=Decimal("20"), price=Decimal("30723.25"), commission=Decimal("10"), timestamp=datetime(2026,9,28,2,18,43,tzinfo=timezone.utc), trade_date=date(2026,9,28), source_payload={}),
            Fill(account_id=account.id, import_file_id=source.id, external_fill_id="t2-b", external_order_id="o4", symbol="MNQZ6", action="Buy", quantity=Decimal("20"), price=Decimal("30723.50"), commission=Decimal("10"), timestamp=datetime(2026,9,28,2,19,8,tzinfo=timezone.utc), trade_date=date(2026,9,28), source_payload={}),
        ]
        db.add_all(real_rows); db.flush()

        # Performance rows for the two real trades.
        t1a = _trade(account.id, buy="t1-b", sell="t1-s1", qty="1", pnl="-56", entry="2026-09-28T01:25:02", exit="2026-09-28T01:30:12")
        t1a.entry_price = Decimal("30785.25"); t1a.exit_price = Decimal("30813.25")
        t1b = _trade(account.id, buy="t1-b", sell="t1-s2", qty="1", pnl="-56.5", entry="2026-09-28T01:25:02", exit="2026-09-28T01:30:12")
        t1b.entry_price = Decimal("30785.00"); t1b.exit_price = Decimal("30813.25")
        t2 = _trade(account.id, buy="t2-b", sell="t2-s", qty="20", pnl="-10", entry="2026-09-28T02:18:43", exit="2026-09-28T02:19:08")
        t2.entry_price = Decimal("30723.25"); t2.exit_price = Decimal("30723.50")
        db.add_all([t1a, t1b, t2]); db.flush()

        # Incomplete live stream begins with the first trade's EXIT and then sees
        # the next trade's ENTRY. The naive live-only state machine produces a
        # false LONG lifecycle from 1:30 -> 2:18.
        db.add_all([
            BrokerExecutionEvent(user_id=user.id, account_id=account.id, connection_id=connection.id, provider="ninjatrader", external_execution_id="nt-exit-old", symbol="MNQ 12-26", side="Buy", quantity=Decimal("2"), price=Decimal("30813.25"), commission=None, point_value=Decimal("2"), currency="USD", executed_at=datetime(2026,9,28,1,30,12,tzinfo=timezone.utc), source_payload={}),
            BrokerExecutionEvent(user_id=user.id, account_id=account.id, connection_id=connection.id, provider="ninjatrader", external_execution_id="nt-entry-next", symbol="MNQ 12-26", side="Sell", quantity=Decimal("20"), price=Decimal("30723.25"), commission=None, point_value=Decimal("2"), currency="USD", executed_at=datetime(2026,9,28,2,18,43,tzinfo=timezone.utc), source_payload={}),
        ])
        phantom = Trade(
            account_id=account.id,
            duplicate_fingerprint="phantom-live",
            symbol="MNQ 12-26",
            root_symbol="MNQ",
            contract_quantity=Decimal("2"),
            side=TradeSide.LONG,
            entry_price=Decimal("30813.25"),
            exit_price=Decimal("30723.25"),
            gross_pnl=Decimal("-360"),
            fees=None,
            net_pnl=Decimal("-360"),
            entry_timestamp=datetime(2026,9,28,1,30,12,tzinfo=timezone.utc),
            exit_timestamp=datetime(2026,9,28,2,18,43,tzinfo=timezone.utc),
            duration_seconds=2911,
            source_quality="broker_live",
            reconciliation_status="live_fees_pending",
            source_payload={"source":"broker_live", "execution_ids":["nt-exit-old", "nt-entry-next"]},
        )
        db.add(phantom); db.flush()

        report = reconcile_trade_ledger(db, account)
        rows = list(db.scalars(select(Trade).where(Trade.account_id == account.id).order_by(Trade.entry_timestamp)).all())

        assert report["suppressed_by_authoritative_fills"] >= 1
        assert report["unresolved_nonmanual_trade_rows"] == 0
        assert len(rows) == 2
        assert all(row.source_quality == "ledger_reconciled" for row in rows)
        assert rows[0].contract_quantity == Decimal("2")
        assert rows[0].fees == Decimal("2")
        assert rows[0].net_pnl == Decimal("-114.5")
        assert rows[1].contract_quantity == Decimal("20")
        assert rows[1].fees == Decimal("20")
