from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.router import router
from app.auth import get_current_user
from app.database import Base, get_db
from app.models import (
    AccountType,
    CaptureEvent,
    BrokerConnection,
    BrokerExecutionEvent,
    Trade,
    TradeJournal,
    TradingAccount,
    User,
)
from app.services.broker_ingestion import _fingerprint, _trip_allocation_rows, reconstruct_round_trips
from tools.repair_ninjatrader_replay import _find_plan, _update_target


def _client() -> tuple[TestClient, Session, User, TradingAccount]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = Session(engine)
    user = User(email="bridge@journalme.local", display_name="Bridge")
    db.add(user)
    db.flush()
    account = TradingAccount(
        user_id=user.id,
        name="Lucid Flex 50K",
        external_account_id="LFE05085094850003",
        provider="lucid",
        account_type=AccountType.EVALUATION,
        starting_balance=Decimal("50000"),
    )
    db.add(account)
    db.commit()

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app), db, user, account


def _create_connection_and_token(client: TestClient, account: TradingAccount) -> tuple[dict, str]:
    response = client.post(
        "/api/v1/broker-connections",
        json={
            "provider": "ninjatrader",
            "connection_type": "desktop_bridge",
            "display_name": "NinjaTrader Desktop",
            "account_id": str(account.id),
            "external_account_id": account.external_account_id,
            "metadata_json": {"read_only": True},
        },
    )
    assert response.status_code == 201, response.text
    connection = response.json()
    issued = client.post(f"/api/v1/broker-connections/{connection['id']}/bridge-token")
    assert issued.status_code == 200, issued.text
    return connection, issued.json()["bridge_token"]


def test_bridge_token_auth_heartbeat_and_revocation() -> None:
    client, _, _, account = _client()
    connection, token = _create_connection_and_token(client, account)

    missing = client.post("/api/v1/broker-bridge/heartbeat")
    assert missing.status_code == 401

    wrong = client.post(
        "/api/v1/broker-bridge/heartbeat",
        headers={"Authorization": "Bearer jmbrg.00000000-0000-0000-0000-000000000000.bad"},
    )
    assert wrong.status_code == 401

    heartbeat = client.post(
        "/api/v1/broker-bridge/heartbeat",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert heartbeat.status_code == 200, heartbeat.text
    assert heartbeat.json()["connection_id"] == connection["id"]

    revoked = client.delete(f"/api/v1/broker-connections/{connection['id']}/bridge-token")
    assert revoked.status_code == 204
    after = client.post(
        "/api/v1/broker-bridge/heartbeat",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert after.status_code == 401


def test_live_execution_round_trip_materializes_trade_and_deduplicates() -> None:
    client, db, _, account = _client()
    connection, token = _create_connection_and_token(client, account)
    headers = {"Authorization": f"Bearer {token}"}

    entry = {
        "external_execution_id": "671242171298_1",
        "external_order_id": "671242171298",
        "symbol": "MNQ 12-26",
        "side": "buy",
        "quantity": "3",
        "price": "30677",
        "commission": None,
        "point_value": "2",
        "currency": "USD",
        "executed_at": datetime(2026, 9, 28, 4, 50, 30, tzinfo=timezone.utc).isoformat(),
        "source_payload": {"bridge_version": "0.7.1"},
    }
    first = client.post("/api/v1/broker-bridge/executions", json=entry, headers=headers)
    assert first.status_code == 201, first.text
    assert first.json()["trade_ids"] == []

    exit_payload = {
        **entry,
        "external_execution_id": "671242171301_1",
        "external_order_id": "671242171301",
        "side": "sell",
        "price": "30677.5",
        "executed_at": datetime(2026, 9, 28, 4, 54, 51, tzinfo=timezone.utc).isoformat(),
    }
    second = client.post(
        "/api/v1/broker-bridge/executions", json=exit_payload, headers=headers
    )
    assert second.status_code == 201, second.text
    assert len(second.json()["trade_ids"]) == 1

    trade = db.scalar(select(Trade).where(Trade.account_id == account.id))
    assert trade is not None
    assert trade.symbol == "MNQ 12-26"
    assert trade.root_symbol == "MNQ"
    assert trade.side.value == "long"
    assert trade.contract_quantity == Decimal("3")
    assert trade.entry_price == Decimal("30677")
    assert trade.exit_price == Decimal("30677.5")
    assert trade.gross_pnl == Decimal("3.0000")
    assert trade.fees is None
    assert trade.net_pnl == Decimal("3.0000")
    assert trade.source_quality == "broker_live"
    assert trade.reconciliation_status == "live_fees_pending"

    duplicate = client.post(
        "/api/v1/broker-bridge/executions", json=exit_payload, headers=headers
    )
    assert duplicate.status_code == 201, duplicate.text
    assert duplicate.json()["duplicate"] is True
    assert len(db.scalars(select(Trade).where(Trade.account_id == account.id)).all()) == 1

    stored_connection = db.get(BrokerConnection, UUID(connection["id"]))
    assert stored_connection is not None
    assert stored_connection.last_sync_at is not None

    activity = client.get(f"/api/v1/broker-activity?account_id={account.id}")
    assert activity.status_code == 200, activity.text
    body = activity.json()
    assert len(body["connections"]) == 1
    assert body["events"][0]["external_execution_id"] == "671242171301_1"
    assert body["events"][0]["root_symbol"] == "MNQ"
    assert body["events"][0]["completed_trade"]["id"] == str(trade.id)
    assert body["events"][0]["completed_trade"]["fees"] is None


def test_partial_exit_round_trip_uses_weighted_exit_price() -> None:
    client, db, _, account = _client()
    _, token = _create_connection_and_token(client, account)
    headers = {"Authorization": f"Bearer {token}"}
    base = {
        "symbol": "MNQ 12-26",
        "point_value": "2",
        "currency": "USD",
        "commission": None,
        "source_payload": {},
    }
    events = [
        {
            **base,
            "external_execution_id": "E1",
            "external_order_id": "O1",
            "side": "buy",
            "quantity": "2",
            "price": "100",
            "executed_at": "2026-09-28T12:00:00+00:00",
        },
        {
            **base,
            "external_execution_id": "E2",
            "external_order_id": "O2",
            "side": "sell",
            "quantity": "1",
            "price": "101",
            "executed_at": "2026-09-28T12:01:00+00:00",
        },
        {
            **base,
            "external_execution_id": "E3",
            "external_order_id": "O3",
            "side": "sell",
            "quantity": "1",
            "price": "102",
            "executed_at": "2026-09-28T12:02:00+00:00",
        },
    ]
    for payload in events:
        response = client.post("/api/v1/broker-bridge/executions", json=payload, headers=headers)
        assert response.status_code == 201, response.text

    trade = db.scalar(select(Trade).where(Trade.account_id == account.id))
    assert trade is not None
    assert trade.contract_quantity == Decimal("2")
    assert trade.entry_price == Decimal("100")
    assert trade.exit_price == Decimal("101.5")
    assert trade.gross_pnl == Decimal("6.0000")


def test_eight_verified_mnq_fills_reconstruct_four_trades_and_exact_totals() -> None:
    client, db, _, account = _client()
    _, token = _create_connection_and_token(client, account)
    headers = {"Authorization": f"Bearer {token}"}
    trades = [
        ("29251.50", "29302.50", "2", "2.00", "18:12"),
        ("29190.00", "29170.75", "10", "10.00", "19:23"),
        ("29158.75", "29157.25", "5", "5.00", "19:40"),
        ("29139.75", "29126.00", "1", "1.00", "20:02"),
    ]
    fill_number = 0
    for entry_price, exit_price, quantity, total_fee, clock in trades:
        hour, minute = (int(value) for value in clock.split(":"))
        entry_at = datetime(2026, 10, 25, hour, minute, tzinfo=timezone.utc)
        for side, price, offset in [
            ("sell", entry_price, 0),
            ("buy", exit_price, 1),
        ]:
            fill_number += 1
            response = client.post(
                "/api/v1/broker-bridge/executions",
                headers=headers,
                json={
                    "external_execution_id": f"VERIFIED-{fill_number}",
                    "symbol": "MNQ 12-26",
                    "side": side,
                    "quantity": quantity,
                    "price": price,
                    "commission": str(Decimal(total_fee) / 2),
                    "point_value": "2",
                    "currency": "USD",
                    "executed_at": (entry_at + timedelta(minutes=offset)).isoformat(),
                },
            )
            assert response.status_code == 201, response.text

    completed = list(db.scalars(select(Trade).where(Trade.account_id == account.id)).all())
    assert len(completed) == 4
    assert sum((trade.gross_pnl for trade in completed), Decimal("0")) == Decimal("223.5000")
    assert sum((trade.fees for trade in completed), Decimal("0")) == Decimal("18.0000")
    assert sum((trade.net_pnl for trade in completed), Decimal("0")) == Decimal("205.5000")
    assert account.starting_balance + sum(
        (trade.net_pnl for trade in completed), Decimal("0")
    ) == Decimal("50205.5000")
    assert {trade.reconciliation_status for trade in completed} == {
        "live_stream_unverified"
    }
    assert all(
        "no completeness watermark" in trade.source_payload["warnings"][0]
        for trade in completed
    )
    assert sorted(trade.contract_quantity for trade in completed) == [
        Decimal("1"), Decimal("2"), Decimal("5"), Decimal("10")
    ]


def test_replay_batch_buffers_observed_out_of_order_arrival_until_complete() -> None:
    client, db, _, account = _client()
    _, token = _create_connection_and_token(client, account)
    headers = {"Authorization": f"Bearer {token}"}
    ids = [f"REPLAY-{index}" for index in range(1, 9)]
    batch = {
        "source_namespace": "Lucid connection",
        "source_account_name": account.external_account_id,
        "batch_id": "47355e2e-6651-4e7f-9bda-45879c6bb18f",
        "expected_execution_ids": ids,
    }
    started = client.post(
        "/api/v1/broker-bridge/execution-batches/start", json=batch, headers=headers
    )
    assert started.status_code == 200, started.text

    # This is the production receive order for the first four fills.
    fills = [
        ("buy", "10", "29170.75", "2026-10-25T19:26:57.766-04:00"),
        ("sell", "2", "29251.50", "2026-10-25T18:12:38.351-04:00"),
        ("buy", "2", "29302.50", "2026-10-25T18:31:18.337-04:00"),
        ("sell", "10", "29190.00", "2026-10-25T19:23:36.919-04:00"),
        ("sell", "5", "29158.75", "2026-10-25T19:40:00.000-04:00"),
        ("buy", "5", "29157.25", "2026-10-25T19:41:00.000-04:00"),
        ("sell", "1", "29139.75", "2026-10-25T20:02:00.000-04:00"),
        ("buy", "1", "29126.00", "2026-10-25T20:03:00.000-04:00"),
    ]
    for index, (side, quantity, price, executed_at) in enumerate(fills):
        response = client.post(
            "/api/v1/broker-bridge/executions",
            headers=headers,
            json={
                "source_namespace": batch["source_namespace"],
                "source_account_name": batch["source_account_name"],
                "external_execution_id": ids[index],
                "symbol": "MNQ 12-26",
                "side": side,
                "quantity": quantity,
                "price": price,
                "point_value": "2",
                "executed_at": executed_at,
            },
        )
        assert response.status_code == 201, response.text
        if index == 1:
            assert response.json()["trade_ids"] == []
            assert db.scalars(select(Trade).where(Trade.account_id == account.id)).all() == []
    assert db.scalars(select(Trade).where(Trade.account_id == account.id)).all() == []

    completed = client.post(
        "/api/v1/broker-bridge/execution-batches/complete",
        json=batch,
        headers=headers,
    )
    assert completed.status_code == 200, completed.text
    trades = list(db.scalars(
        select(Trade).where(Trade.account_id == account.id)
        .order_by(Trade.entry_timestamp)
    ).all())
    assert len(trades) == 4
    assert [trade.gross_pnl for trade in trades] == [
        Decimal("-204"), Decimal("385"), Decimal("15"), Decimal("27.5")
    ]
    assert [(trade.entry_price, trade.exit_price) for trade in trades] == [
        (Decimal("29251.50"), Decimal("29302.50")),
        (Decimal("29190.00"), Decimal("29170.75")),
        (Decimal("29158.75"), Decimal("29157.25")),
        (Decimal("29139.75"), Decimal("29126.00")),
    ]

    # Exact batch retries are idempotent and preserve the four materialized rows.
    assert client.post(
        "/api/v1/broker-bridge/execution-batches/start", json=batch, headers=headers
    ).status_code == 200
    retried = client.post(
        "/api/v1/broker-bridge/execution-batches/complete",
        json=batch,
        headers=headers,
    )
    assert retried.status_code == 200, retried.text
    assert db.scalars(select(Trade).where(Trade.account_id == account.id)).all() == trades


def test_unbatched_late_fill_is_quarantined_and_does_not_rewrite_saved_trade() -> None:
    client, db, _, account = _client()
    _, token = _create_connection_and_token(client, account)
    headers = {"Authorization": f"Bearer {token}"}

    def send(execution_id: str, side: str, quantity: str, price: str, at: str):
        return client.post(
            "/api/v1/broker-bridge/executions",
            headers=headers,
            json={
                "external_execution_id": execution_id,
                "symbol": "MNQ 12-26",
                "side": side,
                "quantity": quantity,
                "price": price,
                "point_value": "2",
                "executed_at": at,
            },
        )

    assert send(
        "LATE-ENTRY", "sell", "2", "29251.50", "2026-10-25T22:12:38Z"
    ).status_code == 201
    second = send(
        "LATE-EXIT", "buy", "2", "29170.75", "2026-10-25T23:26:57Z"
    )
    assert second.status_code == 201, second.text
    trade = db.scalar(select(Trade).where(Trade.account_id == account.id))
    assert trade is not None
    original_id = trade.id
    original_pnl = trade.gross_pnl
    assert original_pnl == Decimal("323.0000")

    late = send(
        "LATE-MISSING-CLOSE", "buy", "2", "29302.50", "2026-10-25T22:31:18Z"
    )
    assert late.status_code == 201, late.text
    late_event = db.scalar(
        select(BrokerExecutionEvent).where(
            BrokerExecutionEvent.external_execution_id == "LATE-MISSING-CLOSE"
        )
    )
    assert late_event is not None
    assert late_event.ingest_status == "needs_reconciliation"
    db.refresh(trade)
    assert trade.id == original_id
    assert trade.gross_pnl == original_pnl
    assert trade.reconciliation_status == "needs_reconciliation"


def test_targeted_repair_preserves_trade_id_journal_and_capture() -> None:
    client, db, user, account = _client()
    connection_data, _ = _create_connection_and_token(client, account)
    connection = db.get(BrokerConnection, UUID(connection_data["id"]))
    assert connection is not None
    fills = [
        ("buy", "10", "29170.75", "2026-10-25T19:26:57+00:00"),
        ("sell", "2", "29251.50", "2026-10-25T18:12:38+00:00"),
        ("buy", "2", "29302.50", "2026-10-25T18:31:18+00:00"),
        ("sell", "10", "29190.00", "2026-10-25T19:23:36+00:00"),
        ("sell", "5", "29158.75", "2026-10-25T19:40:00+00:00"),
        ("buy", "5", "29157.25", "2026-10-25T19:41:00+00:00"),
        ("sell", "1", "29139.75", "2026-10-25T20:02:00+00:00"),
        ("buy", "1", "29126.00", "2026-10-25T20:03:00+00:00"),
    ]
    events = [
        BrokerExecutionEvent(
            user_id=user.id,
            account_id=account.id,
            connection_id=connection.id,
            provider="ninjatrader",
            external_execution_id=f"REPAIR-{index}",
            symbol="MNQ 12-26",
            side=side,
            quantity=Decimal(quantity),
            price=Decimal(price),
            commission=None,
            point_value=Decimal("2"),
            currency="USD",
            executed_at=datetime.fromisoformat(timestamp),
            ingest_status="needs_reconciliation",
            source_payload={"ninjatrader_account": account.external_account_id},
        )
        for index, (side, quantity, price, timestamp) in enumerate(fills, start=1)
    ]
    db.add_all(events)
    db.flush()
    ids = {event.external_execution_id for event in events}
    wrong_trip = reconstruct_round_trips(events[:2])[0]

    def saved_trade(trip, *, fingerprint: str | None = None) -> Trade:
        event_ids = sorted({item.event.external_execution_id for item in trip.slices})
        buy_ids = sorted({item.event.external_execution_id for item in trip.slices if item.event.side == "buy"})
        sell_ids = sorted({item.event.external_execution_id for item in trip.slices if item.event.side == "sell"})
        return Trade(
            account_id=account.id,
            duplicate_fingerprint=fingerprint or _fingerprint(connection, trip),
            symbol=trip.symbol,
            root_symbol="MNQ",
            contract_quantity=trip.quantity,
            side=trip.side,
            entry_price=trip.entry_price,
            exit_price=trip.exit_price,
            gross_pnl=trip.gross_pnl,
            fees=None,
            net_pnl=trip.gross_pnl,
            entry_timestamp=trip.entry_timestamp,
            exit_timestamp=trip.exit_timestamp,
            duration_seconds=0,
            source_quality="broker_live",
            reconciliation_status="needs_reconciliation",
            source_payload={
                "connection_id": str(connection.id),
                "execution_ids": event_ids,
                "execution_allocations": _trip_allocation_rows(trip),
            },
            external_buy_fill_id=",".join(buy_ids),
            external_sell_fill_id=",".join(sell_ids),
        )

    target = saved_trade(wrong_trip, fingerprint="bad-fingerprint-target")
    correct_trip3 = reconstruct_round_trips(events[4:6])[0]
    correct_trip4 = reconstruct_round_trips(events[6:8])[0]
    existing3 = saved_trade(correct_trip3)
    existing4 = saved_trade(correct_trip4)
    db.add_all([target, existing3, existing4])
    db.flush()
    db.add(TradeJournal(trade_id=target.id, thesis="Keep this journal content"))
    capture = CaptureEvent(
        user_id=user.id,
        account_id=account.id,
        captured_at=datetime(2026, 10, 25, 18, 15, tzinfo=timezone.utc),
        event_type="note",
        note="Keep this capture",
        match_status="matched",
        matched_trade_id=target.id,
    )
    db.add(capture)
    db.flush()

    plan = _find_plan(
        db,
        account.id,
        ids,
        str(target.id).replace("-", "")[-8:],
        {},
    )
    assert len(plan["after"]) == 4
    assert plan["after"][0]["trade_id"] == str(target.id)
    assert Decimal(plan["after"][0]["gross_pnl"]) == Decimal("-204")
    assert plan["after"][1]["action"] == "create"
    assert "trade_journals" in plan["relationships"]
    assert "capture_events" in plan["relationships"]

    _update_target(db, plan, {}, None)
    repaired = db.get(Trade, target.id)
    assert repaired is not None
    assert repaired.gross_pnl == Decimal("-204.0000")
    assert repaired.duplicate_fingerprint == _fingerprint(connection, reconstruct_round_trips(events)[0])
    assert db.get(TradeJournal, target.id).thesis == "Keep this journal content"
    db.refresh(capture)
    assert capture.matched_trade_id == target.id
    assert len(db.scalars(select(Trade).where(Trade.account_id == account.id)).all()) == 4


def test_read_only_reconciliation_diagnostic_redacts_execution_ids_and_is_account_scoped() -> None:
    client, _, user, account = _client()
    _, token = _create_connection_and_token(client, account)
    response = client.post(
        "/api/v1/broker-bridge/executions",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "external_execution_id": "PRIVATE-EXECUTION-123",
            "symbol": "MNQ 12-26",
            "side": "sell",
            "quantity": "1",
            "price": "100",
            "point_value": "2",
            "executed_at": "2026-10-25T18:12:00+00:00",
        },
    )
    assert response.status_code == 201, response.text

    diagnostic = client.get(
        "/api/v1/broker-reconciliation-diagnostic",
        params={"account_id": str(account.id)},
    )
    assert diagnostic.status_code == 200, diagnostic.text
    body = diagnostic.json()
    assert body["read_only"] is True
    assert body["coverage_assessment"] == "unknown_without_broker_history_replay"
    assert body["execution_count"] == 1
    assert body["executions"][0]["execution_ref"] != "PRIVATE-EXECUTION-123"
    assert "PRIVATE-EXECUTION-123" not in diagnostic.text

    other_user = User(email="diagnostic-other@journalme.local", display_name="Other")
    client.app.dependency_overrides[get_current_user] = lambda: other_user
    forbidden = client.get(
        "/api/v1/broker-reconciliation-diagnostic",
        params={"account_id": str(account.id)},
    )
    assert forbidden.status_code == 404


def test_installation_requires_explicit_mapping_and_scopes_same_execution_ids() -> None:
    client, db, user, first_account = _client()
    second_account = TradingAccount(
        user_id=user.id,
        name="Lucid Flex 50K #2",
        external_account_id="LFE-second",
        provider="lucid",
        account_type=AccountType.EVALUATION,
    )
    db.add(second_account)
    extra_accounts = [
        TradingAccount(
            user_id=user.id,
            name=f"Lucid Flex 50K #{index}",
            external_account_id=f"LFE-{index}",
            provider="lucid",
            account_type=AccountType.EVALUATION,
        )
        for index in range(3, 6)
    ]
    db.add_all(extra_accounts)
    db.commit()
    installation = client.post(
        "/api/v1/broker-connections",
        json={
            "provider": "ninjatrader",
            "connection_type": "bridge_installation",
            "display_name": "NinjaTrader installation",
        },
    )
    assert installation.status_code == 201, installation.text
    installation_id = installation.json()["id"]
    token = client.post(f"/api/v1/broker-connections/{installation_id}/bridge-token").json()[
        "bridge_token"
    ]
    headers = {"Authorization": f"Bearer {token}"}
    destinations = {"LFE-first": first_account, "LFE-second": second_account}
    destinations.update(
        {
            f"LFE-{index}": account
            for index, account in zip(range(3, 6), extra_accounts, strict=True)
        }
    )
    for name in destinations:
        response = client.post(
            "/api/v1/broker-bridge/discovered-accounts",
            json={
                "source_namespace": "Lucid connection",
                "source_account_name": name,
            },
            headers=headers,
        )
        assert response.status_code == 200, response.text
        assert response.json()["approved"] is False
    sources = client.get("/api/v1/broker-connections").json()
    children = {
        item["source_account_name"]: item
        for item in sources
        if item["installation_id"] == installation_id
    }
    assert len(children) == 5
    stranger = User(email="other@journalme.local", display_name="Other")
    db.add(stranger)
    db.flush()
    foreign_account = TradingAccount(
        user_id=stranger.id,
        name="Other account",
        provider="lucid",
        account_type=AccountType.EVALUATION,
    )
    db.add(foreign_account)
    db.commit()
    assert (
        client.post(
            f"/api/v1/broker-connections/{children['LFE-first']['id']}/authorize-source",
            json={"account_id": str(foreign_account.id)},
        ).status_code
        == 404
    )
    entry = {
        "source_namespace": "Lucid connection",
        "source_account_name": "LFE-first",
        "external_execution_id": "same-id",
        "symbol": "MNQ 12-26",
        "side": "buy",
        "quantity": "1",
        "price": "100",
        "point_value": "2",
        "executed_at": "2026-09-28T12:00:00+00:00",
    }
    assert (
        client.post("/api/v1/broker-bridge/executions", json=entry, headers=headers).status_code
        == 409
    )
    for name, destination in destinations.items():
        response = client.post(
            f"/api/v1/broker-connections/{children[name]['id']}/authorize-source",
            json={
                "account_id": str(destination.id),
            },
        )
        assert response.status_code == 200, response.text
    assert client.post(
        f"/api/v1/broker-connections/{children['LFE-first']['id']}/authorize-source",
        json={"account_id": str(destinations["LFE-second"].id)},
    ).status_code == 409
    for name in children:
        payload = {**entry, "source_account_name": name}
        assert (
            client.post(
                "/api/v1/broker-bridge/executions", json=payload, headers=headers
            ).status_code
            == 201
        )
        assert (
            client.post("/api/v1/broker-bridge/executions", json=payload, headers=headers).json()[
                "duplicate"
            ]
            is True
        )
    events = db.scalars(select(BrokerExecutionEvent)).all()
    assert len(events) == 5
    assert {event.account_id for event in events} == {
        account.id for account in destinations.values()
    }
    assert (
        client.post(
            "/api/v1/broker-bridge/executions",
            json={**entry, "source_account_name": "unknown"},
            headers=headers,
        ).status_code
        == 409
    )
    first_source_id = children["LFE-first"]["id"]
    assert (
        client.post(f"/api/v1/broker-connections/{first_source_id}/disconnect").status_code == 200
    )
    assert (
        client.post("/api/v1/broker-bridge/executions", json=entry, headers=headers).status_code
        == 409
    )
    assert (
        client.post(
            f"/api/v1/broker-connections/{first_source_id}/authorize-source",
            json={"account_id": str(first_account.id)},
        ).status_code
        == 200
    )
    assert (
        client.post("/api/v1/broker-bridge/executions", json=entry, headers=headers).json()[
            "duplicate"
        ]
        is True
    )


def test_disconnect_keeps_history_and_revokes_installation_key() -> None:
    client, db, user, account = _client()
    installation = client.post(
        "/api/v1/broker-connections",
        json={
            "provider": "ninjatrader",
            "connection_type": "bridge_installation",
            "display_name": "NT",
        },
    ).json()
    token = client.post(f"/api/v1/broker-connections/{installation['id']}/bridge-token").json()[
        "bridge_token"
    ]
    headers = {"Authorization": f"Bearer {token}"}
    source = {"source_namespace": "Lucid", "source_account_name": "LFE"}
    client.post("/api/v1/broker-bridge/discovered-accounts", json=source, headers=headers)
    child = next(
        item
        for item in client.get("/api/v1/broker-connections").json()
        if item["installation_id"] == installation["id"]
    )
    client.post(
        f"/api/v1/broker-connections/{child['id']}/authorize-source",
        json={"account_id": str(account.id)},
    )
    event = {
        **source,
        "external_execution_id": "E1",
        "symbol": "MNQ 12-26",
        "side": "buy",
        "quantity": "1",
        "price": "100",
        "point_value": "2",
        "executed_at": "2026-09-28T12:00:00+00:00",
    }
    assert (
        client.post("/api/v1/broker-bridge/executions", json=event, headers=headers).status_code
        == 201
    )
    assert (
        client.post(f"/api/v1/broker-connections/{installation['id']}/disconnect").status_code
        == 200
    )
    assert (
        client.post("/api/v1/broker-bridge/executions", json=event, headers=headers).status_code
        == 401
    )
    assert (
        db.scalar(
            select(BrokerExecutionEvent).where(BrokerExecutionEvent.external_execution_id == "E1")
        )
        is not None
    )
    assert db.get(TradingAccount, account.id) is not None
    assert (
        client.post(f"/api/v1/broker-connections/{installation['id']}/bridge-token").status_code
        == 409
    )


def test_installation_key_rotation_invalidates_previous_key() -> None:
    client, _, _, _ = _client()
    installation = client.post(
        "/api/v1/broker-connections",
        json={
            "provider": "ninjatrader",
            "connection_type": "bridge_installation",
            "display_name": "NT",
        },
    ).json()
    path = f"/api/v1/broker-connections/{installation['id']}/bridge-token"
    first = client.post(path).json()["bridge_token"]
    second = client.post(path).json()["bridge_token"]
    assert first != second
    for token, expected in ((first, 401), (second, 200)):
        response = client.post(
            "/api/v1/broker-bridge/heartbeat",
            json={},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == expected


def test_snapshots_stay_with_their_approved_source_account() -> None:
    client, db, user, first_account = _client()
    second_account = TradingAccount(
        user_id=user.id,
        name="Lucid Flex 50K #2",
        provider="lucid",
        account_type=AccountType.EVALUATION,
    )
    db.add(second_account)
    db.commit()
    installation = client.post(
        "/api/v1/broker-connections",
        json={
            "provider": "ninjatrader",
            "connection_type": "bridge_installation",
            "display_name": "NT",
        },
    ).json()
    token = client.post(
        f"/api/v1/broker-connections/{installation['id']}/bridge-token"
    ).json()["bridge_token"]
    headers = {"Authorization": f"Bearer {token}"}
    sources = [
        {"source_namespace": "Lucid", "source_account_name": name}
        for name in ("LFE-A", "LFE-B", "LFE-pending")
    ]
    for source in sources:
        assert client.post(
            "/api/v1/broker-bridge/discovered-accounts", json=source, headers=headers
        ).status_code == 200
    children = {
        item["source_account_name"]: item
        for item in client.get("/api/v1/broker-connections").json()
        if item["installation_id"] == installation["id"]
    }
    for name, account in (("LFE-A", first_account), ("LFE-B", second_account)):
        assert client.post(
            f"/api/v1/broker-connections/{children[name]['id']}/authorize-source",
            json={"account_id": str(account.id)},
        ).status_code == 200
    for source, cash, expected in (
        (sources[0], "50100", 200),
        (sources[1], "48750", 200),
        (sources[2], "99999", 409),
    ):
        assert client.post(
            "/api/v1/broker-bridge/account-snapshot",
            json={**source, "captured_at": "2026-10-21T12:00:00Z", "cash_value": cash},
            headers=headers,
        ).status_code == expected
    db.expire_all()
    first_source = db.get(BrokerConnection, UUID(children["LFE-A"]["id"]))
    second_source = db.get(BrokerConnection, UUID(children["LFE-B"]["id"]))
    pending_source = db.get(BrokerConnection, UUID(children["LFE-pending"]["id"]))
    assert first_source.account_id == first_account.id
    assert second_source.account_id == second_account.id
    assert first_source.metadata_json["account_snapshot"]["cash_value"] == "50100"
    assert second_source.metadata_json["account_snapshot"]["cash_value"] == "48750"
    assert "account_snapshot" not in pending_source.metadata_json


def test_late_backfill_cannot_create_second_profit_trade_reusing_executions() -> None:
    """A changed reconstruction fingerprint must not double-consume live fills."""
    client, db, _, account = _client()
    _, token = _create_connection_and_token(client, account)
    headers = {"Authorization": f"Bearer {token}"}
    def deliver(execution_id: str, side: str, qty: str, price: str, time: str):
        response = client.post("/api/v1/broker-bridge/executions", json={
            "external_execution_id": execution_id,
            "external_order_id": execution_id,
            "symbol": "MNQ 12-26", "side": side, "quantity": qty,
            "price": price, "point_value": "2", "currency": "USD",
            "executed_at": time, "source_payload": {"ninjatrader_account": account.external_account_id},
        }, headers=headers)
        assert response.status_code == 201, response.text
        return response.json()
    deliver("E1", "buy", "1", "100", "2026-10-23T10:00:00Z")
    original = deliver("E2", "sell", "1", "101", "2026-10-23T10:02:00Z")
    assert len(original["trade_ids"]) == 1
    persisted = db.get(Trade, UUID(original["trade_ids"][0]))
    # Contract labels can change during feed corrections. Execution identity is
    # still global to this connection and cannot be consumed a second time.
    persisted.source_payload["canonical_contract"] = "MNQ|unrelated-contract-label"
    db.flush()
    deliver("E0", "buy", "1", "99", "2026-10-23T09:59:00Z")
    later = deliver("E3", "sell", "1", "102", "2026-10-23T10:03:00Z")
    assert later["trade_ids"] == []
    trades = list(db.scalars(select(Trade).where(Trade.account_id == account.id)))
    assert len(trades) == 1
    assert trades[0].gross_pnl == Decimal("2")
    assert db.scalar(select(BrokerExecutionEvent).where(
        BrokerExecutionEvent.external_execution_id == "E3"
    )).ingest_status == "needs_reconciliation"


def test_reversal_split_allows_disjoint_allocations_but_no_double_consumption() -> None:
    client, db, _, account = _client()
    _, token = _create_connection_and_token(client, account)
    headers = {"Authorization": f"Bearer {token}"}
    base = {"symbol": "MNQ 12-26", "point_value": "2", "currency": "USD", "commission": None,
            "source_payload": {"ninjatrader_account": account.external_account_id}}
    for eid, side, qty, price, minute in [
        ("REV-E1", "buy", "1", "100", 0),
        ("REV-E2", "sell", "2", "101", 1),
        ("REV-E3", "buy", "1", "99", 2),
    ]:
        response = client.post("/api/v1/broker-bridge/executions", json={
            **base, "external_execution_id": eid, "external_order_id": eid,
            "side": side, "quantity": qty, "price": price,
            "executed_at": f"2026-10-23T11:{minute:02d}:00Z",
        }, headers=headers)
        assert response.status_code == 201, response.text
    trades = list(db.scalars(select(Trade).where(Trade.account_id == account.id)))
    assert len(trades) == 2
    assert [t.gross_pnl for t in sorted(trades, key=lambda t: t.entry_timestamp)] == [Decimal("2"), Decimal("4")]
    assert all(t.source_payload.get("execution_allocations") for t in trades)


def test_foreign_source_account_blocks_materialization_without_dropping_raw_events() -> None:
    client, db, _, account = _client()
    _, token = _create_connection_and_token(client, account)
    headers = {"Authorization": f"Bearer {token}"}
    for eid, side, minute in [("wrong-1", "buy", 0), ("wrong-2", "sell", 1)]:
        response = client.post("/api/v1/broker-bridge/executions", json={
            "external_execution_id": eid, "external_order_id": eid,
            "symbol": "MNQ 12-26", "side": side, "quantity": "1",
            "price": "100", "point_value": "2", "currency": "USD",
            "executed_at": f"2026-10-23T12:{minute:02d}:00Z",
            "source_payload": {"ninjatrader_account": "OTHER-ACCOUNT"},
        }, headers=headers)
        assert response.status_code == 201, response.text
    assert not list(db.scalars(select(Trade).where(Trade.account_id == account.id)))
    events = list(db.scalars(select(BrokerExecutionEvent)))
    assert len(events) == 2
    assert all(event.ingest_status == "needs_reconciliation" for event in events)
