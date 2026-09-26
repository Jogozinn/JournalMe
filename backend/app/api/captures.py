from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.config import get_settings
from app.database import get_db
from app.models import CaptureEvent, Trade, TradingAccount, User, UserPreference
from app.services.capture_matching import (
    clear_capture_match,
    force_match_capture,
    reconcile_capture,
    reconcile_unmatched_captures,
)
from app.storage import StorageProvider, get_storage_provider

router = APIRouter(prefix="/captures", tags=["captures"])
Db = Annotated[Session, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]

_ALLOWED_EVENT_TYPES = {"entry", "exit", "update", "wait"}
_ALLOWED_SIDES = {"long", "short"}
_ALLOWED_IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp"}


def _storage() -> StorageProvider:
    return get_storage_provider(get_settings())


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _timestamp(value: datetime | None) -> str | None:
    return _as_utc(value).isoformat() if value else None


def _clean_tags(value: Any, field: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise HTTPException(status_code=422, detail=f"{field} must be a list.")
    output: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise HTTPException(status_code=422, detail=f"{field} values must be strings.")
        cleaned = item.strip()
        if cleaned and cleaned not in output:
            output.append(cleaned[:80])
    if len(output) > 40:
        raise HTTPException(status_code=422, detail=f"{field} may contain at most 40 values.")
    return output


def _parse_metadata(raw: str) -> dict[str, Any]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail="metadata must be valid JSON.") from exc
    if not isinstance(data, dict):
        raise HTTPException(status_code=422, detail="metadata must be a JSON object.")

    event_type = str(data.get("event_type") or "").strip().lower()
    if event_type not in _ALLOWED_EVENT_TYPES:
        raise HTTPException(
            status_code=422,
            detail="event_type must be entry, exit, update, or wait.",
        )

    side_raw = data.get("side")
    side = str(side_raw).strip().lower() if side_raw else None
    if side is not None and side not in _ALLOWED_SIDES:
        raise HTTPException(status_code=422, detail="side must be long, short, or null.")

    symbol_raw = data.get("symbol")
    symbol = str(symbol_raw).strip().upper()[:80] if symbol_raw else None
    if event_type != "wait" and not symbol:
        raise HTTPException(status_code=422, detail="symbol is required unless event_type is wait.")

    captured_raw = data.get("captured_at")
    if not captured_raw:
        raise HTTPException(status_code=422, detail="captured_at is required.")
    try:
        captured_at = datetime.fromisoformat(str(captured_raw).replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="captured_at must be ISO-8601.") from exc
    if captured_at.tzinfo is None:
        raise HTTPException(status_code=422, detail="captured_at must include a timezone.")

    account_id = None
    if data.get("account_id"):
        try:
            account_id = UUID(str(data["account_id"]))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="account_id must be a UUID.") from exc

    note = str(data.get("note") or "").strip() or None
    if note and len(note) > 1000:
        raise HTTPException(status_code=422, detail="note may contain at most 1000 characters.")

    return {
        "captured_at": captured_at.astimezone(timezone.utc),
        "event_type": event_type,
        "account_id": account_id,
        "symbol": symbol,
        "side": side,
        "note": note,
        "setup_tags_json": _clean_tags(data.get("setup_tags"), "setup_tags"),
        "execution_tags_json": _clean_tags(data.get("execution_tags"), "execution_tags"),
        "emotion_tags_json": _clean_tags(data.get("emotion_tags"), "emotion_tags"),
        "platform": str(data.get("platform") or "").strip()[:80] or None,
        "page_url": str(data.get("page_url") or "").strip()[:2048] or None,
        "page_title": str(data.get("page_title") or "").strip()[:500] or None,
        "source": str(data.get("source") or "journalme_chrome_extension").strip()[:80],
    }


def _resolve_capture_account_id(
    db: Session, user: User, requested_account_id: UUID | None
) -> UUID | None:
    if requested_account_id is not None:
        owned_account = db.scalar(
            select(TradingAccount.id).where(
                TradingAccount.id == requested_account_id,
                TradingAccount.user_id == user.id,
            )
        )
        if owned_account is None:
            raise HTTPException(status_code=404, detail="Trading account not found.")
        return requested_account_id

    preference = db.get(UserPreference, user.id)
    if preference and preference.default_account_id:
        default_account = db.scalar(
            select(TradingAccount.id).where(
                TradingAccount.id == preference.default_account_id,
                TradingAccount.user_id == user.id,
                TradingAccount.active.is_(True),
            )
        )
        if default_account is not None:
            return default_account

    active_accounts = db.scalars(
        select(TradingAccount.id).where(
            TradingAccount.user_id == user.id,
            TradingAccount.active.is_(True),
        )
    ).all()
    if len(active_accounts) == 1:
        return active_accounts[0]
    return None


def _owned_trade_or_404(db: Session, user: User, trade_id: UUID) -> Trade:
    trade = db.scalar(
        select(Trade)
        .join(TradingAccount, TradingAccount.id == Trade.account_id)
        .where(Trade.id == trade_id, TradingAccount.user_id == user.id)
    )
    if trade is None:
        raise HTTPException(status_code=404, detail="Trade not found.")
    return trade


def _owned_capture_or_404(db: Session, user: User, capture_id: UUID) -> CaptureEvent:
    capture = db.scalar(
        select(CaptureEvent).where(
            CaptureEvent.id == capture_id,
            CaptureEvent.user_id == user.id,
        )
    )
    if capture is None:
        raise HTTPException(status_code=404, detail="Capture not found.")
    return capture


def _capture_dict(item: CaptureEvent) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "account_id": str(item.account_id) if item.account_id else None,
        "captured_at": _timestamp(item.captured_at),
        "created_at": _timestamp(item.created_at),
        "event_type": item.event_type,
        "symbol": item.symbol,
        "side": item.side,
        "note": item.note,
        "setup_tags": item.setup_tags_json or [],
        "execution_tags": item.execution_tags_json or [],
        "emotion_tags": item.emotion_tags_json or [],
        "platform": item.platform,
        "page_url": item.page_url,
        "page_title": item.page_title,
        "source": item.source,
        "match_status": item.match_status,
        "matched_trade_id": str(item.matched_trade_id) if item.matched_trade_id else None,
        "match_score": float(item.match_score) if item.match_score is not None else None,
        "matched_at": _timestamp(item.matched_at),
        "match_method": item.match_method,
        "screenshot_url": f"{get_settings().api_prefix}/captures/{item.id}/screenshot",
    }


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_capture(
    db: Db,
    user: CurrentUser,
    metadata: Annotated[str, Form()],
    screenshot: Annotated[UploadFile, File()],
) -> dict[str, Any]:
    data = _parse_metadata(metadata)

    data["account_id"] = _resolve_capture_account_id(db, user, data["account_id"])

    mime_type = (screenshot.content_type or "").lower()
    if mime_type not in _ALLOWED_IMAGE_TYPES:
        raise HTTPException(status_code=415, detail="Screenshot must be PNG, JPEG, or WebP.")

    content = await screenshot.read()
    if not content:
        raise HTTPException(status_code=422, detail="Screenshot is empty.")
    if len(content) > get_settings().max_upload_bytes:
        raise HTTPException(status_code=413, detail="Screenshot exceeds the upload limit.")

    capture_id = uuid4()
    suffix = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}[mime_type]
    original = Path(screenshot.filename or f"capture{suffix}").name
    if Path(original).suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
        original = f"capture{suffix}"
    storage_key = _storage().put(capture_id, original, content)

    capture = CaptureEvent(
        id=capture_id,
        user_id=user.id,
        account_id=data["account_id"],
        captured_at=data["captured_at"],
        event_type=data["event_type"],
        symbol=data["symbol"],
        side=data["side"],
        note=data["note"],
        setup_tags_json=data["setup_tags_json"],
        execution_tags_json=data["execution_tags_json"],
        emotion_tags_json=data["emotion_tags_json"],
        platform=data["platform"],
        page_url=data["page_url"],
        page_title=data["page_title"],
        source=data["source"],
        screenshot_storage_key=storage_key,
        screenshot_original_filename=original,
        screenshot_mime=mime_type,
        match_status="unmatched",
    )
    db.add(capture)
    db.flush()
    reconcile_capture(db, capture, user.id)
    db.commit()
    db.refresh(capture)
    return _capture_dict(capture)


@router.get("")
def list_captures(
    db: Db,
    user: CurrentUser,
    limit: int = Query(default=20, ge=1, le=100),
    match_status: str | None = Query(default=None),
) -> list[dict[str, Any]]:
    query = select(CaptureEvent).where(CaptureEvent.user_id == user.id)
    if match_status:
        query = query.where(CaptureEvent.match_status == match_status)
    rows = db.scalars(
        query.order_by(CaptureEvent.captured_at.desc()).limit(limit)
    ).all()
    return [_capture_dict(item) for item in rows]


@router.post("/reconcile")
def reconcile_captures(
    db: Db,
    user: CurrentUser,
    account_id: UUID | None = Query(default=None),
) -> dict[str, int]:
    if account_id is not None:
        _resolve_capture_account_id(db, user, account_id)
    stats = reconcile_unmatched_captures(db, user.id, account_id=account_id)
    db.commit()
    return stats


@router.post("/{capture_id}/match/{trade_id}")
def match_capture_manually(
    capture_id: UUID, trade_id: UUID, db: Db, user: CurrentUser
) -> dict[str, Any]:
    capture = _owned_capture_or_404(db, user, capture_id)
    trade = _owned_trade_or_404(db, user, trade_id)
    force_match_capture(db, capture, trade, score=1.0, method="manual")
    db.commit()
    db.refresh(capture)
    return _capture_dict(capture)


@router.post("/{capture_id}/unmatch")
def unmatch_capture(
    capture_id: UUID, db: Db, user: CurrentUser
) -> dict[str, Any]:
    capture = _owned_capture_or_404(db, user, capture_id)
    clear_capture_match(db, capture)
    db.commit()
    db.refresh(capture)
    return _capture_dict(capture)


@router.delete("/{capture_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_capture(capture_id: UUID, db: Db, user: CurrentUser) -> Response:
    capture = _owned_capture_or_404(db, user, capture_id)
    _storage().delete(capture.screenshot_storage_key)
    db.delete(capture)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{capture_id}/screenshot")
def capture_screenshot(capture_id: UUID, db: Db, user: CurrentUser) -> Response:
    capture = _owned_capture_or_404(db, user, capture_id)
    content = _storage().get(capture.screenshot_storage_key)
    return Response(
        content=content,
        media_type=capture.screenshot_mime,
        headers={"Cache-Control": "private, max-age=3600"},
    )
