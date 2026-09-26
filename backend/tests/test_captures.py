import json
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api import captures
from app.auth import get_current_user
from app.database import Base, get_db
from app.models import User
from app.storage import LocalFileStorage


def test_create_list_and_read_capture(tmp_path, monkeypatch) -> None:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = User(email="capture@journalme.local", display_name="Capture")
        db.add(user)
        db.commit()
        db.refresh(user)
        user_id = user.id

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
    client = TestClient(app)

    metadata = {
        "captured_at": datetime(2026, 9, 23, 19, 30, tzinfo=timezone.utc).isoformat(),
        "event_type": "entry",
        "symbol": "MNQ",
        "side": "short",
        "note": "Sweep into FVG",
        "setup_tags": ["Liquidity Sweep", "FVG"],
        "execution_tags": ["Good"],
        "emotion_tags": ["Calm"],
        "platform": "TradingView",
        "source": "journalme_chrome_extension",
    }
    png = b"\x89PNG\r\n\x1a\n" + b"journalme-test"
    created = client.post(
        "/api/v1/captures",
        data={"metadata": json.dumps(metadata)},
        files={"screenshot": ("chart.png", png, "image/png")},
    )
    assert created.status_code == 201, created.text
    payload = created.json()
    assert payload["symbol"] == "MNQ"
    assert payload["event_type"] == "entry"
    assert payload["match_status"] == "unmatched"
    assert payload["setup_tags"] == ["Liquidity Sweep", "FVG"]

    listed = client.get("/api/v1/captures?limit=8")
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [payload["id"]]

    image = client.get(payload["screenshot_url"])
    assert image.status_code == 200
    assert image.content == png
    assert image.headers["content-type"].startswith("image/png")

    deleted = client.delete(f"/api/v1/captures/{payload['id']}")
    assert deleted.status_code == 204

    listed_after_delete = client.get("/api/v1/captures?limit=8")
    assert listed_after_delete.status_code == 200
    assert listed_after_delete.json() == []

    missing_image = client.get(payload["screenshot_url"])
    assert missing_image.status_code == 404
