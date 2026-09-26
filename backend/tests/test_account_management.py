from datetime import datetime, timezone
from decimal import Decimal

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.router import router
from app.auth import get_current_user
from app.database import Base, get_db
from app.domain import TradeSide
from app.models import AccountLifecycleStatus, Trade, TradingAccount, User


def _trade(account: TradingAccount) -> Trade:
    entered = datetime(2026, 9, 1, 14, tzinfo=timezone.utc)
    return Trade(
        account_id=account.id,
        duplicate_fingerprint=f"account-management-{account.id}",
        symbol="MNQU6",
        root_symbol="MNQ",
        contract_quantity=Decimal("1"),
        side=TradeSide.LONG,
        entry_price=Decimal("20000"),
        exit_price=Decimal("20010"),
        gross_pnl=Decimal("100"),
        fees=Decimal("2"),
        net_pnl=Decimal("98"),
        entry_timestamp=entered,
        exit_timestamp=entered.replace(minute=5),
        duration_seconds=300,
    )


def test_account_lifecycle_archive_restore_and_authorization() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = Session(engine)
    owner = User(email="owner@journalme.local", display_name="Owner")
    other = User(email="other@journalme.local", display_name="Other")
    db.add_all([owner, other])
    db.flush()
    account = TradingAccount(user_id=owner.id, name="Fixture account")
    db.add(account)
    db.flush()
    db.add(_trade(account))
    db.commit()

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: owner
    client = TestClient(app)

    listed = client.get("/api/v1/accounts")
    assert listed.status_code == 200, listed.text
    assert listed.json()[0]["lifecycle_status"] == "active"

    renamed = client.patch(
        f"/api/v1/accounts/{account.id}",
        json={"name": "Renamed fixture", "lifecycle_status": "blown"},
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["name"] == "Renamed fixture"
    assert renamed.json()["lifecycle_status"] == "blown"

    archived = client.post(f"/api/v1/accounts/{account.id}/archive")
    assert archived.status_code == 200, archived.text
    assert archived.json()["active"] is False
    assert archived.json()["lifecycle_status"] == "blown"

    active_accounts = client.get("/api/v1/accounts")
    assert active_accounts.status_code == 200
    assert active_accounts.json() == []

    archived_accounts = client.get("/api/v1/accounts?include_archived=true")
    assert [item["id"] for item in archived_accounts.json()] == [str(account.id)]
    assert archived_accounts.json()[0]["net_pnl"] == "98.0000"

    historical_trades = client.get(f"/api/v1/trades?account_id={account.id}")
    assert historical_trades.status_code == 200, historical_trades.text
    assert historical_trades.json()["total"] == 1
    assert historical_trades.json()["items"][0]["account_id"] == str(account.id)

    restored = client.post(f"/api/v1/accounts/{account.id}/restore")
    assert restored.status_code == 200, restored.text
    assert restored.json()["active"] is True
    assert restored.json()["lifecycle_status"] == "blown"
    assert [item["id"] for item in client.get("/api/v1/accounts").json()] == [str(account.id)]

    app.dependency_overrides[get_current_user] = lambda: other
    assert client.patch(f"/api/v1/accounts/{account.id}", json={"name": "Nope"}).status_code == 404
    assert client.post(f"/api/v1/accounts/{account.id}/archive").status_code == 404


def test_custom_account_creation_remains_available() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = Session(engine)
    user = User(email="create@journalme.local", display_name="Create")
    db.add(user)
    db.commit()

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: user
    client = TestClient(app)

    created = client.post(
        "/api/v1/accounts/from-preset",
        json={
            "account": {"name": "Custom fixture", "provider": "manual"},
            "preset": {"preset_key": "custom"},
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["name"] == "Custom fixture"
    assert created.json()["lifecycle_status"] == AccountLifecycleStatus.ACTIVE.value


def test_lifecycle_status_uses_lowercase_database_values() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = Session(engine)
    user = User(email="lifecycle@journalme.local", display_name="Lifecycle")
    db.add(user)
    db.flush()
    account = TradingAccount(
        user_id=user.id,
        name="Existing lowercase lifecycle account",
        lifecycle_status=AccountLifecycleStatus.ACTIVE,
    )
    db.add(account)
    db.commit()

    db.execute(
        text("UPDATE trading_accounts SET lifecycle_status = 'active' WHERE id = :account_id"),
        {"account_id": account.id.hex},
    )
    db.commit()
    db.expire_all()

    loaded = db.get(TradingAccount, account.id)
    assert loaded is not None
    assert loaded.lifecycle_status is AccountLifecycleStatus.ACTIVE

    loaded.lifecycle_status = AccountLifecycleStatus.BLOWN
    db.commit()
    assert db.execute(
        text("SELECT lifecycle_status FROM trading_accounts WHERE id = :account_id"),
        {"account_id": account.id.hex},
    ).scalar_one() == "blown"

    lifecycle_type = TradingAccount.__table__.c.lifecycle_status.type
    assert lifecycle_type.native_enum is False
    assert lifecycle_type.enums == [member.value for member in AccountLifecycleStatus]
