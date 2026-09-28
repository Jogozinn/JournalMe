from __future__ import annotations

import base64
import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime, time, timezone
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.config import Settings, get_settings
from app.models import (
    DailyJournal,
    NotificationDelivery,
    PushSubscription,
    Trade,
    TradeJournal,
    TradingAccount,
    User,
    UserPreference,
)
from app.services.intelligence import build_intelligence_overview
from app.services.review import trade_review_statuses

logger = logging.getLogger(__name__)

DEFAULT_PUSH_PREFERENCES: dict[str, Any] = {
    "enabled": True,
    "patterns": True,
    "mindset": True,
    "review_reminders": True,
    "daily_cue": False,
    "daily_cue_time": "08:30",
    "review_reminder_time": "19:00",
    "quiet_hours_enabled": True,
    "quiet_hours_start": "22:00",
    "quiet_hours_end": "07:00",
}

EVIDENCE_LABELS = {
    "early_signal": "Early signal",
    "repeated_pattern": "Repeated pattern",
    "strong_evidence": "Strong evidence",
}


@dataclass(frozen=True)
class PushNotice:
    key: str
    kind: str
    title: str
    body: str
    url: str
    account_id: UUID | None = None


def push_configured(settings: Settings | None = None) -> bool:
    settings = settings or get_settings()
    return bool(
        settings.vapid_public_key
        and (settings.vapid_private_key or settings.vapid_private_key_b64)
        and settings.vapid_subject
    )


def endpoint_hash(endpoint: str) -> str:
    return hashlib.sha256(endpoint.strip().encode("utf-8")).hexdigest()


def merged_push_preferences(item: UserPreference | None) -> dict[str, Any]:
    stored = dict(item.notification_preferences_json or {}) if item else {}
    return {**DEFAULT_PUSH_PREFERENCES, **stored}


def _private_key(settings: Settings) -> str:
    if settings.vapid_private_key:
        return settings.vapid_private_key.replace("\\n", "\n")
    if settings.vapid_private_key_b64:
        return base64.b64decode(settings.vapid_private_key_b64).decode("utf-8")
    raise RuntimeError("VAPID private key is not configured.")


def _send_webpush(subscription: PushSubscription, payload: dict[str, Any], settings: Settings) -> None:
    try:
        from pywebpush import webpush
    except ImportError as exc:  # pragma: no cover - deployment dependency guard
        raise RuntimeError("pywebpush is required for background notifications.") from exc

    webpush(
        subscription_info={
            "endpoint": subscription.endpoint,
            "keys": {"p256dh": subscription.p256dh, "auth": subscription.auth},
        },
        data=json.dumps(payload, separators=(",", ":")),
        vapid_private_key=_private_key(settings),
        vapid_claims={"sub": settings.vapid_subject},
        timeout=10,
    )


def send_push_to_user(
    db: Session,
    user_id: UUID,
    notice: PushNotice,
    *,
    settings: Settings | None = None,
    record_delivery: bool = True,
) -> dict[str, int]:
    settings = settings or get_settings()
    if not push_configured(settings):
        return {"sent": 0, "failed": 0, "disabled": 0}
    delivery: NotificationDelivery | None = None
    if record_delivery:
        existing = db.scalar(
            select(NotificationDelivery).where(
                NotificationDelivery.user_id == user_id,
                NotificationDelivery.notice_key == notice.key,
            )
        )
        if existing is not None:
            return {"sent": 0, "failed": 0, "disabled": 0}
        delivery = NotificationDelivery(
            user_id=user_id,
            account_id=notice.account_id,
            notice_key=notice.key,
            kind=notice.kind,
            title=notice.title,
            body=notice.body,
            target_url=notice.url,
            sent_at=datetime.now(timezone.utc),
            metadata_json={"status": "sending"},
        )
        db.add(delivery)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            return {"sent": 0, "failed": 0, "disabled": 0}

    subscriptions = list(
        db.scalars(
            select(PushSubscription).where(
                PushSubscription.user_id == user_id,
                PushSubscription.enabled.is_(True),
            )
        ).all()
    )
    sent = failed = disabled = 0
    payload = {
        "title": notice.title,
        "body": notice.body,
        "url": notice.url,
        "tag": f"journalme-{notice.kind}",
        "kind": notice.kind,
    }
    for subscription in subscriptions:
        try:
            _send_webpush(subscription, payload, settings)
            subscription.last_seen_at = datetime.now(timezone.utc)
            sent += 1
        except Exception as exc:  # noqa: BLE001 - provider errors vary by implementation
            failed += 1
            response = getattr(exc, "response", None)
            status_code = getattr(response, "status_code", None)
            if status_code in {404, 410}:
                subscription.enabled = False
                disabled += 1

    if delivery is not None:
        if sent:
            delivery.metadata_json = {
                "status": "sent",
                "sent_devices": sent,
                "failed_devices": failed,
            }
        else:
            db.delete(delivery)
    db.commit()
    return {"sent": sent, "failed": failed, "disabled": disabled}


def _parse_clock(value: str, fallback: str) -> time:
    raw = value if isinstance(value, str) else fallback
    try:
        hour, minute = (int(part) for part in raw.split(":", 1))
        return time(hour=hour, minute=minute)
    except (TypeError, ValueError):
        hour, minute = (int(part) for part in fallback.split(":", 1))
        return time(hour=hour, minute=minute)


def _minutes(value: time) -> int:
    return value.hour * 60 + value.minute


def _in_window(now: time, target: time, width_minutes: int = 180) -> bool:
    current = _minutes(now)
    start = _minutes(target)
    return start <= current < min(start + width_minutes, 24 * 60)


def _in_quiet_hours(now: time, prefs: dict[str, Any]) -> bool:
    if not prefs.get("quiet_hours_enabled", True):
        return False
    start = _minutes(_parse_clock(str(prefs.get("quiet_hours_start", "22:00")), "22:00"))
    end = _minutes(_parse_clock(str(prefs.get("quiet_hours_end", "07:00")), "07:00"))
    current = _minutes(now)
    if start == end:
        return False
    if start < end:
        return start <= current < end
    return current >= start or current < end


def _selected_account(db: Session, user_id: UUID, preference: UserPreference | None) -> TradingAccount | None:
    accounts = list(
        db.scalars(
            select(TradingAccount)
            .where(TradingAccount.user_id == user_id, TradingAccount.active.is_(True))
            .order_by(TradingAccount.updated_at.desc())
        ).all()
    )
    if not accounts:
        return None
    if preference and preference.default_account_id:
        default = next((item for item in accounts if item.id == preference.default_account_id), None)
        if default is not None:
            return default
    return accounts[0]


def build_push_notices(
    db: Session,
    user: User,
    *,
    now_utc: datetime | None = None,
) -> list[PushNotice]:
    preference = db.get(UserPreference, user.id)
    prefs = merged_push_preferences(preference)
    if not prefs.get("enabled", True):
        return []

    account = _selected_account(db, user.id, preference)
    timezone_name = preference.timezone if preference else (account.timezone if account else "America/New_York")
    try:
        zone = ZoneInfo(timezone_name)
    except Exception:  # noqa: BLE001 - invalid user timezone falls back safely
        zone = ZoneInfo("America/New_York")
    local_now = (now_utc or datetime.now(timezone.utc)).astimezone(zone)
    if _in_quiet_hours(local_now.time(), prefs):
        return []

    learning_accounts = list(
        db.scalars(
            select(TradingAccount)
            .where(
                TradingAccount.user_id == user.id,
                TradingAccount.include_in_learning.is_(True),
            )
            .order_by(TradingAccount.created_at)
        ).all()
    )
    notices: list[PushNotice] = []
    if learning_accounts and (prefs.get("patterns", True) or prefs.get("mindset", True)):
        account_ids = [item.id for item in learning_accounts]
        trades = list(
            db.scalars(
                select(Trade)
                .where(Trade.account_id.in_(account_ids))
                .order_by(Trade.account_id, Trade.entry_timestamp)
            ).all()
        )
        journals = list(
            db.scalars(
                select(DailyJournal)
                .where(DailyJournal.account_id.in_(account_ids))
                .order_by(DailyJournal.account_id, DailyJournal.trading_date)
            ).all()
        )
        overview = build_intelligence_overview(
            learning_accounts,
            trades,
            journals,
            current_account_id=account.id if account and account.id in account_ids else None,
        )
        if prefs.get("patterns", True):
            for insight in overview.get("insights", [])[:3]:
                evidence = str(insight.get("evidence", ""))
                if evidence not in {"repeated_pattern", "strong_evidence"}:
                    continue
                condition = insight.get("condition", {})
                comparison = insight.get("comparison", {})
                sample = int(condition.get("trades", 0)) + int(comparison.get("trades", 0))
                notices.append(
                    PushNotice(
                        key=f"pattern:{insight.get('key')}:{evidence}",
                        kind="pattern",
                        title=str(insight.get("title") or "JournalMe noticed a trading pattern"),
                        body=f"{EVIDENCE_LABELS.get(evidence, 'Pattern')} · {sample} trades studied. {insight.get('explanation', '')}".strip(),
                        url="/intelligence",
                        account_id=account.id if account else None,
                    )
                )
        if prefs.get("mindset", True):
            for insight in overview.get("mindset_insights", [])[:2]:
                evidence = str(insight.get("evidence", ""))
                if evidence not in {"repeated_pattern", "strong_evidence"}:
                    continue
                tagged = insight.get("tagged", {})
                other = insight.get("other_reviewed_days", {})
                sample = int(tagged.get("days", 0)) + int(other.get("days", 0))
                notices.append(
                    PushNotice(
                        key=f"mindset:{insight.get('key')}:{evidence}",
                        kind="mindset",
                        title=str(insight.get("title") or "JournalMe noticed a mindset pattern"),
                        body=f"{EVIDENCE_LABELS.get(evidence, 'Pattern')} · {sample} reviewed days. {insight.get('explanation', '')}".strip(),
                        url="/intelligence",
                        account_id=account.id if account else None,
                    )
                )

    if account is not None and prefs.get("review_reminders", True):
        reminder_at = _parse_clock(str(prefs.get("review_reminder_time", "19:00")), "19:00")
        if _in_window(local_now.time(), reminder_at, 240):
            account_trades = list(
                db.scalars(
                    select(Trade)
                    .options(selectinload(Trade.tags), selectinload(Trade.journal))
                    .where(Trade.account_id == account.id)
                    .order_by(Trade.entry_timestamp)
                ).all()
            )
            statuses = trade_review_statuses(db, user.id, account_trades)
            awaiting = sum(payload["status"] != "complete" for payload in statuses.values())
            if awaiting:
                notices.append(
                    PushNotice(
                        key=f"review:{account.id}:{local_now.date().isoformat()}",
                        kind="review",
                        title="Your journal has unfinished context",
                        body=f"{awaiting} completed trade{'s are' if awaiting != 1 else ' is'} still waiting for your perspective.",
                        url="/review",
                        account_id=account.id,
                    )
                )

    if account is not None and prefs.get("daily_cue", False):
        cue_at = _parse_clock(str(prefs.get("daily_cue_time", "08:30")), "08:30")
        if _in_window(local_now.time(), cue_at, 180):
            journal = db.scalar(
                select(TradeJournal)
                .join(Trade, TradeJournal.trade_id == Trade.id)
                .join(TradingAccount, Trade.account_id == TradingAccount.id)
                .where(
                    TradingAccount.user_id == user.id,
                    TradeJournal.lesson_learned.is_not(None),
                    TradeJournal.lesson_learned != "",
                )
                .order_by(Trade.entry_timestamp.desc())
                .limit(1)
            )
            if journal and journal.lesson_learned:
                notices.insert(
                    0,
                    PushNotice(
                        key=f"cue:{local_now.date().isoformat()}:{hashlib.sha256(journal.lesson_learned.encode('utf-8')).hexdigest()[:12]}",
                        kind="cue",
                        title="Carry this forward today",
                        body=journal.lesson_learned.strip()[:240],
                        url=f"/trades/{journal.trade_id}",
                        account_id=account.id,
                    ),
                )

    # Avoid a burst of old findings when a device is first subscribed. The scheduler
    # will surface the most relevant notices over subsequent passes.
    return notices[:2]


def run_push_notification_tick(*, settings: Settings | None = None) -> dict[str, int]:
    from app.database import SessionLocal

    settings = settings or get_settings()
    if not push_configured(settings):
        return {"users": 0, "sent": 0}
    users_checked = sent_total = 0
    with SessionLocal() as db:
        user_ids = list(
            db.scalars(
                select(PushSubscription.user_id)
                .where(PushSubscription.enabled.is_(True))
                .distinct()
            ).all()
        )
        for user_id in user_ids:
            user = db.get(User, user_id)
            if user is None:
                continue
            users_checked += 1
            for notice in build_push_notices(db, user):
                result = send_push_to_user(db, user.id, notice, settings=settings)
                sent_total += result["sent"]
    return {"users": users_checked, "sent": sent_total}
