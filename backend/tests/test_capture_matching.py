from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.database import Base
from app.domain import TradeSide
from app.models import Attachment, CaptureEvent, Trade, TradingAccount, User
from app.services import capture_matching
from app.storage import LocalFileStorage


def _trade(account: TradingAccount, at: datetime, *, seconds: int = 120) -> Trade:
    return Trade(
        account_id=account.id,
        duplicate_fingerprint=str(uuid4()),
        symbol="MNQU6",
        root_symbol="MNQ",
        contract_quantity=Decimal("1"),
        side=TradeSide.LONG,
        entry_price=Decimal("25000"),
        exit_price=Decimal("25010"),
        gross_pnl=Decimal("20"),
        fees=Decimal("2"),
        net_pnl=Decimal("18"),
        entry_timestamp=at,
        exit_timestamp=at + timedelta(seconds=seconds),
        duration_seconds=seconds,
    )


def _capture(storage: LocalFileStorage, user: User, account: TradingAccount | None, at: datetime, *, event_type: str = "entry") -> CaptureEvent:
    capture_id = uuid4()
    key = storage.save(capture_id, "chart.png", b"fake-png-data")
    return CaptureEvent(
        id=capture_id,
        user_id=user.id,
        account_id=account.id if account else None,
        captured_at=at,
        event_type=event_type,
        symbol="CME_MINI:MNQ1!",
        side="long",
        note="Liquidity sweep into FVG",
        setup_tags_json=["Liquidity Sweep", "FVG"],
        execution_tags_json=["Good"],
        emotion_tags_json=["Calm"],
        platform="TradingView",
        source="journalme_chrome_extension",
        screenshot_storage_key=key,
        screenshot_original_filename="chart.png",
        screenshot_mime="image/png",
        match_status="unmatched",
    )


def test_normalize_symbol_handles_chart_and_broker_futures() -> None:
    assert capture_matching.normalize_symbol("CME_MINI:MNQ1!") == "MNQ"
    assert capture_matching.normalize_symbol("MNQU6") == "MNQ"
    assert capture_matching.normalize_symbol("NQ1!") == "NQ"
    assert capture_matching.normalize_symbol("XAUUSD") == "XAUUSD"


def test_entry_capture_auto_matches_without_duplicate_trade_attachment(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(capture_matching, "get_settings", lambda: SimpleNamespace(storage_path=tmp_path))
    storage = LocalFileStorage(tmp_path)
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        user = User(email="capture@journalme.local", display_name="Capture")
        db.add(user)
        db.flush()
        account = TradingAccount(user_id=user.id, name="One account")
        db.add(account)
        db.flush()
        at = datetime(2026, 9, 23, 18, 0, tzinfo=timezone.utc)
        trade = _trade(account, at)
        capture = _capture(storage, user, account, at + timedelta(seconds=8))
        db.add_all([trade, capture])
        db.flush()

        result = capture_matching.reconcile_capture(db, capture, user.id)
        db.commit()

        assert result.status == "matched"
        assert capture.match_status == "matched"
        assert capture.matched_trade_id == trade.id
        assert float(capture.match_score) >= 0.82
        assert db.scalar(select(func.count()).select_from(Attachment)) == 0
        assert storage.read(capture.screenshot_storage_key) == b"fake-png-data"

        capture_matching.clear_capture_match(db, capture)
        db.commit()
        assert capture.match_status == "unmatched"
        assert capture.matched_trade_id is None
        assert db.scalar(select(func.count()).select_from(Attachment)) == 0
        # The original Companion capture remains intact when a match is cleared.
        assert storage.read(capture.screenshot_storage_key) == b"fake-png-data"


def test_ambiguous_nearby_trades_are_suggested_not_auto_matched(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(capture_matching, "get_settings", lambda: SimpleNamespace(storage_path=tmp_path))
    storage = LocalFileStorage(tmp_path)
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        user = User(email="ambiguous@journalme.local", display_name="Ambiguous")
        db.add(user)
        db.flush()
        account = TradingAccount(user_id=user.id, name="Scalping")
        db.add(account)
        db.flush()
        at = datetime(2026, 9, 23, 18, 0, tzinfo=timezone.utc)
        first = _trade(account, at - timedelta(seconds=10))
        second = _trade(account, at + timedelta(seconds=10))
        capture = _capture(storage, user, account, at)
        db.add_all([first, second, capture])
        db.flush()

        result = capture_matching.reconcile_capture(db, capture, user.id)
        db.commit()

        assert result.status == "suggested"
        assert capture.match_status == "suggested"
        assert capture.matched_trade_id in {first.id, second.id}
        assert capture.matched_at is None
        assert db.scalar(select(func.count()).select_from(Attachment)) == 0


def test_wait_capture_is_never_attached_to_an_executed_trade(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(capture_matching, "get_settings", lambda: SimpleNamespace(storage_path=tmp_path))
    storage = LocalFileStorage(tmp_path)
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        user = User(email="wait@journalme.local", display_name="Wait")
        db.add(user)
        db.flush()
        account = TradingAccount(user_id=user.id, name="One account")
        db.add(account)
        db.flush()
        at = datetime(2026, 9, 23, 18, 0, tzinfo=timezone.utc)
        trade = _trade(account, at)
        capture = _capture(storage, user, account, at, event_type="wait")
        db.add_all([trade, capture])
        db.flush()

        result = capture_matching.reconcile_capture(db, capture, user.id)
        db.commit()

        assert result.status == "unmatched"
        assert capture.matched_trade_id is None
        assert db.scalar(select(func.count()).select_from(Attachment)) == 0


def test_capture_api_uses_single_active_account_and_auto_matches(tmp_path, monkeypatch) -> None:
    import asyncio
    import json

    import httpx
    from fastapi import FastAPI
    from sqlalchemy.pool import StaticPool

    from app.api import captures as captures_api
    from app.auth import get_current_user
    from app.database import get_db

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = User(email="api-capture@journalme.local", display_name="API Capture")
        db.add(user)
        db.flush()
        account = TradingAccount(user_id=user.id, name="Only active account")
        db.add(account)
        db.flush()
        at = datetime(2026, 9, 23, 18, 0, tzinfo=timezone.utc)
        trade = _trade(account, at)
        db.add(trade)
        db.commit()
        user_id = user.id
        account_id = account.id
        trade_id = trade.id

    settings = SimpleNamespace(
        storage_path=tmp_path,
        max_upload_bytes=10 * 1024 * 1024,
        api_prefix="/api/v1",
    )
    monkeypatch.setattr(captures_api, "get_settings", lambda: settings)
    monkeypatch.setattr(capture_matching, "get_settings", lambda: settings)

    app = FastAPI()
    app.include_router(captures_api.router, prefix="/api/v1")

    def override_db():
        with Session(engine) as db:
            yield db

    def override_user():
        with Session(engine) as db:
            return db.get(User, user_id)

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = override_user

    async def scenario() -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            response = await client.post(
                "/api/v1/captures",
                data={
                    "metadata": json.dumps(
                        {
                            "captured_at": (at + timedelta(seconds=5)).isoformat(),
                            "event_type": "entry",
                            "symbol": "MNQ1!",
                            "side": "long",
                            "note": "API auto match",
                            "setup_tags": ["FVG"],
                        }
                    )
                },
                files={"screenshot": ("chart.png", b"png-bytes", "image/png")},
            )
            assert response.status_code == 201, response.text
            payload = response.json()
            assert payload["account_id"] == str(account_id)
            assert payload["match_status"] == "matched"
            assert payload["matched_trade_id"] == str(trade_id)

            recent = await client.get("/api/v1/captures?limit=8")
            assert recent.status_code == 200
            assert recent.json()[0]["match_status"] == "matched"

            reconcile = await client.post("/api/v1/captures/reconcile")
            assert reconcile.status_code == 200
            assert reconcile.json()["checked"] == 0

    asyncio.run(scenario())

