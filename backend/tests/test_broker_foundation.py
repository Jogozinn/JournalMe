from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.router import router
from app.auth import get_current_user
from app.database import Base, get_db
from app.models import AccountType, TradingAccount, User


def _client() -> tuple[TestClient, Session, User, TradingAccount]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = Session(engine)
    user = User(email="broker@journalme.local", display_name="Broker")
    db.add(user)
    db.flush()
    account = TradingAccount(
        user_id=user.id,
        name="Lucid fixture",
        provider="lucid",
        account_type=AccountType.EVALUATION,
        starting_balance=Decimal("50000"),
        include_in_learning=True,
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


def test_broker_connection_and_execution_deduplication() -> None:
    client, _, _, account = _client()
    created = client.post(
        "/api/v1/broker-connections",
        json={
            "provider": "ninjatrader",
            "connection_type": "desktop_bridge",
            "display_name": "NinjaTrader Desktop",
            "account_id": str(account.id),
            "external_account_id": "LFE-test",
            "metadata_json": {"mode": "probe", "read_only": True},
        },
    )
    assert created.status_code == 201, created.text
    connection = created.json()
    assert connection["status"] == "disconnected"
    assert connection["account_id"] == str(account.id)

    heartbeat = client.post(f"/api/v1/broker-connections/{connection['id']}/heartbeat")
    assert heartbeat.status_code == 200, heartbeat.text
    assert heartbeat.json()["status"] == "connected"
    assert heartbeat.json()["last_seen_at"] is not None

    payload = {
        "connection_id": connection["id"],
        "external_execution_id": "EXEC-001",
        "external_order_id": "ORDER-001",
        "symbol": "MNQ 12-26",
        "side": "buy",
        "quantity": "2",
        "price": "25000.25",
        "commission": "1.20",
        "executed_at": datetime(2026, 9, 26, 14, 30, tzinfo=timezone.utc).isoformat(),
        "source_payload": {"source": "fixture"},
    }
    first = client.post("/api/v1/broker-executions", json=payload)
    assert first.status_code == 201, first.text
    assert first.json()["duplicate"] is False

    duplicate = client.post("/api/v1/broker-executions", json=payload)
    assert duplicate.status_code == 201, duplicate.text
    assert duplicate.json()["duplicate"] is True

    listed = client.get(f"/api/v1/broker-executions?account_id={account.id}")
    assert listed.status_code == 200, listed.text
    assert len(listed.json()) == 1
    assert listed.json()[0]["external_execution_id"] == "EXEC-001"
    assert listed.json()[0]["quantity"] == "2.000000"


def test_account_learning_toggle_is_returned_and_patchable() -> None:
    client, _, _, account = _client()
    accounts = client.get("/api/v1/accounts?include_archived=true")
    assert accounts.status_code == 200, accounts.text
    assert accounts.json()[0]["include_in_learning"] is True

    updated = client.patch(
        f"/api/v1/accounts/{account.id}",
        json={"include_in_learning": False},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["include_in_learning"] is False
