from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import app.api.router as router_module
from app.api.router import router
from app.auth import get_current_user
from app.config import Settings
from app.database import Base, get_db
from app.models import User


def _client(monkeypatch) -> tuple[TestClient, Session, User]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = Session(engine)
    user = User(email="push-api@journalme.local", display_name="Push API")
    db.add(user)
    db.commit()

    settings = Settings(
        vapid_public_key="public-key",
        vapid_private_key="private-key",
        vapid_subject="mailto:test@example.com",
    )
    monkeypatch.setattr(router_module, "get_settings", lambda: settings)

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app), db, user


def test_push_subscription_and_preferences_round_trip(monkeypatch) -> None:
    client, db, _ = _client(monkeypatch)
    try:
        config = client.get("/api/v1/push/config")
        assert config.status_code == 200
        assert config.json() == {"enabled": True, "vapid_public_key": "public-key"}

        created = client.post(
            "/api/v1/push/subscriptions",
            json={
                "endpoint": "https://push.example/device-1",
                "keys": {"p256dh": "p256dh", "auth": "auth"},
                "device_label": "iPhone Home Screen",
                "user_agent": "Safari fixture",
            },
        )
        assert created.status_code == 201, created.text
        assert created.json()["enabled"] is True

        preferences = client.get("/api/v1/push/preferences")
        assert preferences.status_code == 200
        assert preferences.json()["active_subscriptions"] == 1
        assert preferences.json()["patterns"] is True

        updated = client.put(
            "/api/v1/push/preferences",
            json={"daily_cue": True, "daily_cue_time": "08:15", "quiet_hours_enabled": False},
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["daily_cue"] is True
        assert updated.json()["daily_cue_time"] == "08:15"
        assert updated.json()["active_subscriptions"] == 1

        removed = client.request(
            "DELETE",
            "/api/v1/push/subscriptions",
            json={"endpoint": "https://push.example/device-1"},
        )
        assert removed.status_code == 204, removed.text
        after = client.get("/api/v1/push/preferences")
        assert after.json()["active_subscriptions"] == 0
    finally:
        db.close()
