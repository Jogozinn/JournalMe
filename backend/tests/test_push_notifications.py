from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.database import Base
from app.domain import TradeSide
from app.models import (
    NotificationDelivery,
    PushSubscription,
    Trade,
    TradeJournal,
    TradingAccount,
    User,
    UserPreference,
)
from app.services import push_notifications
from app.services.push_notifications import PushNotice, build_push_notices, send_push_to_user


def _db() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_push_delivery_is_deduplicated_per_notice(monkeypatch) -> None:
    with _db() as db:
        user = User(email="push@journalme.local", display_name="Push")
        db.add(user)
        db.flush()
        db.add(
            PushSubscription(
                user_id=user.id,
                subscription_hash="a" * 64,
                endpoint="https://push.example/subscription",
                p256dh="key",
                auth="auth",
                enabled=True,
            )
        )
        db.commit()
        sent: list[str] = []
        monkeypatch.setattr(
            push_notifications,
            "_send_webpush",
            lambda subscription, payload, settings: sent.append(payload["title"]),
        )
        settings = Settings(
            vapid_public_key="public",
            vapid_private_key="private",
            vapid_subject="mailto:test@example.com",
        )
        notice = PushNotice(
            key="pattern:after_loss:repeated_pattern",
            kind="pattern",
            title="JournalMe noticed",
            body="Evidence-backed reminder",
            url="/intelligence",
        )
        first = send_push_to_user(db, user.id, notice, settings=settings)
        second = send_push_to_user(db, user.id, notice, settings=settings)
        assert first["sent"] == 1
        assert second["sent"] == 0
        assert sent == ["JournalMe noticed"]
        assert db.scalar(select(NotificationDelivery)) is not None


def test_daily_cue_uses_the_users_own_saved_lesson() -> None:
    with _db() as db:
        user = User(email="cue@journalme.local", display_name="Cue")
        db.add(user)
        db.flush()
        account = TradingAccount(
            user_id=user.id,
            name="Evaluation",
            timezone="America/New_York",
            include_in_learning=True,
        )
        db.add(account)
        db.flush()
        trade = Trade(
            account_id=account.id,
            duplicate_fingerprint="cue-trade",
            symbol="MNQZ6",
            root_symbol="MNQ",
            contract_quantity=Decimal("1"),
            side=TradeSide.LONG,
            entry_price=Decimal("25000"),
            exit_price=Decimal("25010"),
            gross_pnl=Decimal("20"),
            fees=Decimal("1"),
            net_pnl=Decimal("19"),
            entry_timestamp=datetime(2026, 9, 27, 14, 0, tzinfo=timezone.utc),
            exit_timestamp=datetime(2026, 9, 27, 14, 5, tzinfo=timezone.utc),
            duration_seconds=300,
        )
        db.add(trade)
        db.flush()
        db.add(
            TradeJournal(
                trade_id=trade.id,
                lesson_learned="Wait for confirmation instead of anticipating the reversal.",
            )
        )
        db.add(
            UserPreference(
                user_id=user.id,
                timezone="America/New_York",
                default_account_id=account.id,
                notification_preferences_json={
                    "enabled": True,
                    "patterns": False,
                    "mindset": False,
                    "review_reminders": False,
                    "daily_cue": True,
                    "daily_cue_time": "08:30",
                    "quiet_hours_enabled": False,
                },
            )
        )
        db.commit()
        notices = build_push_notices(
            db,
            user,
            now_utc=datetime(2026, 9, 28, 12, 35, tzinfo=timezone.utc),
        )
        assert notices
        assert notices[0].kind == "cue"
        assert notices[0].body == "Wait for confirmation instead of anticipating the reversal."
        assert notices[0].url == f"/trades/{trade.id}"


def test_base64_pem_vapid_key_is_converted_to_py_vapid_der_string() -> None:
    import base64

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    private_key = ec.generate_private_key(ec.SECP256R1())
    pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    settings = Settings(
        vapid_public_key="public",
        vapid_private_key_b64=base64.b64encode(pem).decode("ascii"),
        vapid_subject="mailto:test@example.com",
    )

    encoded = push_notifications._private_key(settings)
    padding = "=" * ((4 - len(encoded) % 4) % 4)
    der = base64.urlsafe_b64decode(encoded + padding)
    loaded = serialization.load_der_private_key(der, password=None)

    assert loaded.private_numbers().private_value == private_key.private_numbers().private_value
