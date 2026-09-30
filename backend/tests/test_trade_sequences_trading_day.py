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
from app.domain import TradeSide
from app.models import Trade, TradingAccount, User
from app.services.review import trade_review_statuses
from app.services.trading_calendar import fallback_trading_date_for_timestamp


def _trade(account: TradingAccount, *, at: datetime, pnl: str, symbol: str = "MNQZ6") -> Trade:
    return Trade(
        account_id=account.id,
        duplicate_fingerprint=f"{symbol}-{at.isoformat()}-{pnl}",
        symbol=symbol,
        root_symbol="MNQ",
        contract_quantity=Decimal("1"),
        side=TradeSide.SHORT,
        entry_price=Decimal("30000"),
        exit_price=Decimal("29999"),
        gross_pnl=Decimal(pnl),
        fees=Decimal("0"),
        net_pnl=Decimal(pnl),
        entry_timestamp=at,
        exit_timestamp=at.replace(minute=(at.minute + 1) % 60),
        duration_seconds=60,
    )


def _client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = Session(engine, expire_on_commit=False)
    user = User(email="sequence@journalme.local", display_name="Sequence")
    db.add(user)
    db.flush()
    account = TradingAccount(
        user_id=user.id,
        name="Review account",
        timezone="America/New_York",
    )
    db.add(account)
    db.flush()
    trades = [
        _trade(
            account,
            at=datetime(2026, 9, 29, 1, 0, tzinfo=timezone.utc),  # Sep 28 9 PM ET -> Sep 29 trading day
            pnl="-25",
        ),
        _trade(
            account,
            at=datetime(2026, 9, 29, 14, 0, tzinfo=timezone.utc),  # Sep 29 10 AM ET
            pnl="75",
        ),
        _trade(
            account,
            at=datetime(2026, 9, 29, 22, 30, tzinfo=timezone.utc),  # Sep 29 6:30 PM ET -> Sep 30 trading day
            pnl="20",
        ),
    ]
    db.add_all(trades)
    db.commit()

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app), db, account, trades


def test_trading_day_rollover_groups_evening_with_next_regular_session() -> None:
    assert fallback_trading_date_for_timestamp(
        datetime(2026, 9, 29, 1, 0, tzinfo=timezone.utc), "America/New_York"
    ).isoformat() == "2026-09-29"
    assert fallback_trading_date_for_timestamp(
        datetime(2026, 9, 29, 14, 0, tzinfo=timezone.utc), "America/New_York"
    ).isoformat() == "2026-09-29"
    assert fallback_trading_date_for_timestamp(
        datetime(2026, 9, 29, 22, 30, tzinfo=timezone.utc), "America/New_York"
    ).isoformat() == "2026-09-30"


def test_trade_review_navigation_persists_after_save_and_is_trading_day_scoped() -> None:
    client, db, _account, trades = _client()
    first, second, third = trades

    detail = client.get(f"/api/v1/trades/{first.id}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["review_position"] == {
        "index": 1,
        "count": 2,
        "date": "2026-09-29",
        "date_mode": "trading",
    }
    assert detail.json()["next_trade_id"] == str(second.id)

    saved = client.put(
        f"/api/v1/trades/{first.id}/journal",
        json={"thesis": "Same bearish idea", "mark_reviewed": True},
    )
    assert saved.status_code == 200, saved.text
    # Regression: saving used to replace the detail payload with a version that
    # did not contain next/previous navigation.
    assert saved.json()["next_trade_id"] == str(second.id)
    assert saved.json()["review_position"]["count"] == 2
    assert saved.json()["next_trade_id"] != str(third.id)
    db.close()


def test_trade_sequence_keeps_canonical_trades_separate_with_shared_and_per_trade_notes() -> None:
    client, db, account, trades = _client()
    first, second, _third = trades

    created = client.post(
        "/api/v1/trade-sequences",
        json={
            "account_id": str(account.id),
            "title": "NY bearish continuation",
            "thesis": "Same directional idea across re-entries.",
            "shared_context": "Targeting lower liquidity; took profit and re-entered.",
            "lesson_learned": "Keep the idea separate from each execution decision.",
            "members": [
                {"trade_id": str(first.id), "note": "Initial entry."},
                {"trade_id": str(second.id), "note": "Cleaner re-entry."},
            ],
        },
    )
    assert created.status_code == 201, created.text
    payload = created.json()
    assert payload["summary"]["trade_count"] == 2
    assert Decimal(payload["summary"]["net_pnl"]) == Decimal("50")
    assert [item["trade"]["id"] for item in payload["members"]] == [
        str(first.id),
        str(second.id),
    ]
    assert payload["members"][1]["note"] == "Cleaner re-entry."

    first_lookup = client.get(f"/api/v1/trades/{first.id}/sequence")
    assert first_lookup.status_code == 200
    assert first_lookup.json()["id"] == payload["id"]

    # The two broker trades remain two canonical trade rows.
    listed = client.get(f"/api/v1/trades?account_id={account.id}&page_size=50")
    assert listed.status_code == 200
    assert listed.json()["total"] == 3
    db.close()


def test_calendar_defaults_to_trading_day_but_can_toggle_calendar_day() -> None:
    client, db, account, _trades = _client()

    trading = client.get(
        f"/api/v1/calendar?account_id={account.id}&year=2026&month=9"
    )
    assert trading.status_code == 200, trading.text
    trading_days = {row["date"]: row for row in trading.json()["days"]}
    assert trading.json()["date_mode"] == "trading"
    assert trading_days["2026-09-29"]["trade_count"] == 2
    assert trading_days["2026-09-30"]["trade_count"] == 1

    calendar = client.get(
        f"/api/v1/calendar?account_id={account.id}&year=2026&month=9&date_mode=calendar"
    )
    assert calendar.status_code == 200, calendar.text
    calendar_days = {row["date"]: row for row in calendar.json()["days"]}
    assert calendar.json()["date_mode"] == "calendar"
    assert calendar_days["2026-09-28"]["trade_count"] == 1
    assert calendar_days["2026-09-29"]["trade_count"] == 2
    db.close()


def test_sequence_shared_context_reduces_repeated_review_fields() -> None:
    client, db, account, trades = _client()
    first, second, _third = trades
    created = client.post(
        "/api/v1/trade-sequences",
        json={
            "account_id": str(account.id),
            "thesis": "Shared bearish thesis.",
            "shared_context": "Same session objective.",
            "lesson_learned": "Wait for cleaner confirmation.",
            "members": [
                {"trade_id": str(first.id), "note": "Initial entry after rejection."},
                {"trade_id": str(second.id), "note": "Re-entered after confirmation."},
            ],
        },
    )
    assert created.status_code == 201, created.text

    statuses = trade_review_statuses(db, account.user_id, [first, second])
    # Shared sequence context means the trader does not have to repeat the same
    # thesis/entry idea/lesson on every canonical trade. Other required fields
    # remain trade-specific and therefore still appear as missing.
    for trade in (first, second):
        assert "thesis" not in statuses[trade.id]["missing"]
        assert "entry reason" not in statuses[trade.id]["missing"]
        assert "lesson learned" not in statuses[trade.id]["missing"]
    db.close()
