import io
import json
import zipfile
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api import phase2
from app.api import router as api_router
from app.auth import get_current_user
from app.database import Base, get_db
from app.models import AccountType, CaptureEvent, TradingAccount, TradingEpisode, User
from app.storage import LocalFileStorage


def test_waverr_research_pack_preserves_live_timeline_and_screenshot(tmp_path, monkeypatch) -> None:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    storage = LocalFileStorage(tmp_path / "storage")
    now = datetime(2026, 9, 28, 14, 3, tzinfo=timezone.utc)

    with Session(engine) as db:
        user = User(email="research@journalme.local", display_name="Research")
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
        db.flush()
        episode = TradingEpisode(
            user_id=user.id,
            account_id=account.id,
            symbol="MNQ",
            side="long",
            status="active",
            source="journalme_mobile_companion",
            started_at=now,
        )
        db.add(episode)
        db.flush()
        capture = CaptureEvent(
            user_id=user.id,
            account_id=account.id,
            episode_id=episode.id,
            captured_at=now,
            event_type="update",
            phase="pre_entry",
            recorded_live=True,
            symbol="MNQ",
            side="long",
            note="Swept the low; waiting for confirmation.",
            setup_tags_json=["Liquidity Sweep"],
            execution_tags_json=[],
            emotion_tags_json=["Patient"],
            source="journalme_mobile_companion",
            screenshot_original_filename="chart.png",
            screenshot_mime="image/png",
            match_status="unmatched",
        )
        db.add(capture)
        db.flush()
        capture.screenshot_storage_key = storage.put(capture.id, "chart.png", b"chart-bytes")
        db.commit()
        user_id = user.id
        account_id = account.id

    def override_db():
        with Session(engine) as session:
            yield session

    def override_user():
        with Session(engine) as session:
            return session.get(User, user_id)

    monkeypatch.setattr(phase2, "get_storage_provider", lambda _settings: storage)
    app = FastAPI()
    app.include_router(phase2.router, prefix="/api/v1")
    app.include_router(api_router.router, prefix="/api/v1")
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = override_user
    client = TestClient(app)

    response = client.get(f"/api/v1/exports/waverr-research.zip?account_id={account_id}")
    assert response.status_code == 200, response.text
    with zipfile.ZipFile(io.BytesIO(response.content)) as bundle:
        manifest = json.loads(bundle.read("manifest.json"))
        assert manifest["export_type"] == "waverr_research_pack"
        assert manifest["episodes"][0]["moment_count"] == 1
        folder = manifest["episodes"][0]["folder"]
        moment = json.loads(bundle.read(f"{folder}/moments.jsonl").decode().strip())
        assert moment["knowledge_stage"] == "decision_time"
        assert moment["recorded_live"] is True
        assert moment["note"] == "Swept the low; waiting for confirmation."
        assert bundle.read(moment["screenshot_path"]) == b"chart-bytes"


def test_waverr_research_pack_includes_unjournaled_account_trade(tmp_path, monkeypatch) -> None:
    from decimal import Decimal

    from app.domain import TradeSide
    from app.models import Trade

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    storage = LocalFileStorage(tmp_path / "storage")
    entry = datetime(2026, 9, 30, 14, 0, tzinfo=timezone.utc)
    exit_time = datetime(2026, 9, 30, 14, 5, tzinfo=timezone.utc)

    with Session(engine) as db:
        user = User(email="all-trades@journalme.local", display_name="All Trades")
        db.add(user)
        db.flush()
        account = TradingAccount(
            user_id=user.id,
            name="Research Account",
            provider="tradovate",
            account_type=AccountType.EVALUATION,
            timezone="America/New_York",
            currency="USD",
        )
        db.add(account)
        db.flush()
        trade = Trade(
            account_id=account.id,
            duplicate_fingerprint="unlinked-trade-1",
            symbol="MNQZ6",
            root_symbol="MNQ",
            contract_quantity=Decimal("2"),
            side=TradeSide.LONG,
            entry_price=Decimal("30000"),
            exit_price=Decimal("30010"),
            gross_pnl=Decimal("40"),
            fees=Decimal("2"),
            net_pnl=Decimal("38"),
            currency="USD",
            entry_timestamp=entry,
            exit_timestamp=exit_time,
            duration_seconds=300,
            source_quality="ledger_canonical",
            reconciliation_status="reconciled",
        )
        losing_trade = Trade(
            account_id=account.id,
            duplicate_fingerprint="legitimate-losing-trade",
            symbol="MNQZ6",
            root_symbol="MNQ",
            contract_quantity=Decimal("1"),
            side=TradeSide.LONG,
            entry_price=Decimal("30010"),
            exit_price=Decimal("30005"),
            gross_pnl=Decimal("-10"),
            fees=Decimal("2"),
            net_pnl=Decimal("-12"),
            currency="USD",
            entry_timestamp=entry,
            exit_timestamp=exit_time,
            duration_seconds=300,
            source_quality="ledger_canonical",
            reconciliation_status="reconciled",
        )
        superseded_trade = Trade(
            account_id=account.id,
            duplicate_fingerprint="superseded-reconciliation-row",
            symbol="MNQZ6",
            root_symbol="MNQ",
            contract_quantity=Decimal("1"),
            side=TradeSide.LONG,
            entry_price=Decimal("30000"),
            exit_price=Decimal("30010"),
            gross_pnl=Decimal("500"),
            fees=Decimal("2"),
            net_pnl=Decimal("498"),
            currency="USD",
            entry_timestamp=entry,
            exit_timestamp=exit_time,
            duration_seconds=300,
            source_quality="ledger_canonical",
            reconciliation_status="reconciled",
            accounting_status="superseded",
            accounting_exclusion_reason="Duplicate execution allocation",
        )
        quarantined_trade = Trade(
            account_id=account.id,
            duplicate_fingerprint="quarantined-source-mismatch",
            symbol="MNQZ6",
            root_symbol="MNQ",
            contract_quantity=Decimal("1"),
            side=TradeSide.LONG,
            entry_price=Decimal("30000"),
            exit_price=Decimal("30010"),
            gross_pnl=Decimal("100"),
            fees=Decimal("2"),
            net_pnl=Decimal("98"),
            currency="USD",
            entry_timestamp=entry,
            exit_timestamp=exit_time,
            duration_seconds=300,
            source_quality="ledger_canonical",
            reconciliation_status="reconciled",
            accounting_status="quarantined",
            accounting_exclusion_reason="Source account identity mismatch",
        )
        db.add_all([trade, losing_trade, superseded_trade, quarantined_trade])
        db.commit()
        user_id = user.id
        account_id = account.id
        trade_id = trade.id
        losing_trade_id = losing_trade.id

    def override_db():
        with Session(engine) as session:
            yield session

    def override_user():
        with Session(engine) as session:
            return session.get(User, user_id)

    monkeypatch.setattr(phase2, "get_storage_provider", lambda _settings: storage)
    app = FastAPI()
    app.include_router(phase2.router, prefix="/api/v1")
    app.include_router(api_router.router, prefix="/api/v1")
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = override_user
    client = TestClient(app)

    response = client.get(f"/api/v1/exports/waverr-research.zip?account_id={account_id}")
    assert response.status_code == 200, response.text
    with zipfile.ZipFile(io.BytesIO(response.content)) as bundle:
        manifest = json.loads(bundle.read("manifest.json"))
        assert manifest["schema_version"] == 3
        assert manifest["dataset_counts"]["trades"] == 2
        trades = json.loads(bundle.read("dataset/trades.json"))
        by_id = {item["id"]: item for item in trades}
        assert set(by_id) == {str(trade_id), str(losing_trade_id)}
        assert Decimal(by_id[str(trade_id)]["net_pnl"]) == Decimal("38")
        assert Decimal(by_id[str(losing_trade_id)]["net_pnl"]) == Decimal("-12")
        assert by_id[str(trade_id)]["calendar_date"] == "2026-09-30"
        assert by_id[str(trade_id)]["trading_date"] == "2026-09-30"
        assert by_id[str(trade_id)]["trading_date_source"] == "session_rollover_fallback"
        dictionary = bundle.read("dataset/DATA_DICTIONARY.txt").decode()
        assert "including trades with no Companion episode" in manifest["research_contract"]["account_dataset"]
        assert "every current trade" in dictionary

    analytics = client.get(
        "/api/v1/analytics", params={"account_id": str(account_id)}
    )
    assert analytics.status_code == 200, analytics.text
    assert analytics.json()["metrics"]["total_trades"] == 2
    assert Decimal(analytics.json()["metrics"]["net_pnl"]) == Decimal("26")

    trades_csv = client.get(
        "/api/v1/exports/trades.csv", params={"account_id": str(account_id)}
    )
    assert trades_csv.status_code == 200, trades_csv.text
    assert "-12.0000" in trades_csv.text
    assert "498.0000" not in trades_csv.text
    assert "98.0000" not in trades_csv.text
    assert len(trades_csv.text.splitlines()) == 3  # header and two included trades

    archive_response = client.get("/api/v1/exports/archive.zip")
    assert archive_response.status_code == 200, archive_response.text
    with zipfile.ZipFile(io.BytesIO(archive_response.content)) as bundle:
        archive_trades = json.loads(bundle.read("data/trades.json"))
        assert {item["id"] for item in archive_trades} == {
            str(trade_id),
            str(losing_trade_id),
        }
