from __future__ import annotations

from datetime import datetime, timezone
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
from app.models import AccountType, BrokerConnection, Trade, TradingAccount, User


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
        {**base, "external_execution_id": "E1", "external_order_id": "O1", "side": "buy", "quantity": "2", "price": "100", "executed_at": "2026-09-28T12:00:00+00:00"},
        {**base, "external_execution_id": "E2", "external_order_id": "O2", "side": "sell", "quantity": "1", "price": "101", "executed_at": "2026-09-28T12:01:00+00:00"},
        {**base, "external_execution_id": "E3", "external_order_id": "O3", "side": "sell", "quantity": "1", "price": "102", "executed_at": "2026-09-28T12:02:00+00:00"},
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
