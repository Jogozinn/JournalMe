import json
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api import captures
from app.auth import get_current_user
from app.database import Base, get_db
from app.models import AccountType, TradingAccount, User
from app.storage import LocalFileStorage


def _client(tmp_path, monkeypatch):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = User(email="episodes@journalme.local", display_name="Episodes")
        db.add(user)
        db.flush()
        account = TradingAccount(
            user_id=user.id,
            name="Lucid Flex Evaluation 50K #1",
            provider="tradovate",
            account_type=AccountType.EVALUATION,
            timezone="America/New_York",
            currency="USD",
        )
        db.add(account)
        db.commit()
        db.refresh(user)
        db.refresh(account)
        user_id = user.id
        account_id = account.id

    def override_db():
        with Session(engine) as session:
            yield session

    def override_user():
        with Session(engine) as session:
            return session.get(User, user_id)

    monkeypatch.setattr(captures, "_storage", lambda: LocalFileStorage(tmp_path))
    app = FastAPI()
    app.include_router(captures.router, prefix="/api/v1")
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = override_user
    return TestClient(app), str(account_id)


def test_episode_accepts_optional_timeline_updates(tmp_path, monkeypatch) -> None:
    client, account_id = _client(tmp_path, monkeypatch)
    started = datetime(2026, 9, 28, 14, 3, tzinfo=timezone.utc)

    created = client.post(
        "/api/v1/captures/episodes",
        json={
            "account_id": account_id,
            "symbol": "MNQ",
            "side": "long",
            "started_at": started.isoformat(),
            "source": "journalme_mobile_companion",
        },
    )
    assert created.status_code == 201, created.text
    episode = created.json()
    assert episode["status"] == "active"
    assert episode["moment_count"] == 0

    first = client.post(
        "/api/v1/captures/moments",
        data={
            "metadata": json.dumps(
                {
                    "episode_id": episode["id"],
                    "account_id": account_id,
                    "captured_at": started.isoformat(),
                    "phase": "pre_entry",
                    "symbol": "MNQ",
                    "side": "long",
                    "note": "Swept the low. Waiting for confirmation.",
                    "setup_tags": ["Liquidity Sweep", "4H FVG"],
                    "source": "journalme_mobile_companion",
                }
            )
        },
    )
    assert first.status_code == 201, first.text
    first_payload = first.json()
    assert first_payload["phase"] == "pre_entry"
    assert first_payload["event_type"] == "update"
    assert first_payload["has_screenshot"] is False
    assert first_payload["episode"]["moment_count"] == 1

    png = b"\x89PNG\r\n\x1a\n" + b"episode-screenshot"
    confirmation_time = started + timedelta(minutes=5)
    second = client.post(
        "/api/v1/captures/moments",
        data={
            "metadata": json.dumps(
                {
                    "episode_id": episode["id"],
                    "account_id": account_id,
                    "captured_at": confirmation_time.isoformat(),
                    "phase": "confirmation",
                    "symbol": "MNQ",
                    "side": "long",
                    "note": "Displacement confirmed the reclaim.",
                    "execution_tags": ["Waited for Displacement"],
                    "source": "journalme_mobile_companion",
                }
            )
        },
        files={"screenshot": ("confirmation.png", png, "image/png")},
    )
    assert second.status_code == 201, second.text
    second_payload = second.json()
    assert second_payload["has_screenshot"] is True
    assert second_payload["episode"]["moment_count"] == 2
    image = client.get(second_payload["screenshot_url"])
    assert image.status_code == 200
    assert image.content == png

    active = client.get(f"/api/v1/captures/episodes/active?account_id={account_id}")
    assert active.status_code == 200
    active_payload = active.json()
    assert active_payload["id"] == episode["id"]
    assert [item["phase"] for item in active_payload["moments"]] == ["pre_entry", "confirmation"]

    exit_time = confirmation_time + timedelta(minutes=12)
    closed = client.post(
        "/api/v1/captures/moments",
        data={
            "metadata": json.dumps(
                {
                    "episode_id": episode["id"],
                    "captured_at": exit_time.isoformat(),
                    "phase": "exit",
                    "note": "Closed as momentum stalled.",
                    "source": "journalme_mobile_companion",
                }
            )
        },
    )
    assert closed.status_code == 201, closed.text
    assert closed.json()["episode"]["status"] == "complete"
    assert closed.json()["episode"]["moment_count"] == 3

    no_active = client.get(f"/api/v1/captures/episodes/active?account_id={account_id}")
    assert no_active.status_code == 200
    assert no_active.json() is None

    recent = client.get(f"/api/v1/captures/episodes?account_id={account_id}&limit=5")
    assert recent.status_code == 200
    assert recent.json()[0]["moment_count"] == 3
    assert recent.json()[0]["screenshot_count"] == 1


def test_moment_can_start_episode_automatically(tmp_path, monkeypatch) -> None:
    client, account_id = _client(tmp_path, monkeypatch)
    now = datetime(2026, 9, 28, 15, 0, tzinfo=timezone.utc)
    response = client.post(
        "/api/v1/captures/moments",
        data={
            "metadata": json.dumps(
                {
                    "account_id": account_id,
                    "captured_at": now.isoformat(),
                    "phase": "wait",
                    "symbol": "MNQ",
                    "note": "No clean setup. Stayed out.",
                }
            )
        },
    )
    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["episode_id"]
    assert payload["episode"]["status"] == "wait"
    assert payload["episode"]["moment_count"] == 1
