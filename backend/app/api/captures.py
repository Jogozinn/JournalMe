from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Query, Response, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.config import get_settings
from app.database import get_db
from app.models import CaptureEvent, Trade, TradingAccount, TradingEpisode, User, UserPreference, utcnow
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
_ALLOWED_PHASES = {
    "pre_entry",
    "confirmation",
    "entry",
    "management",
    "exit",
    "wait",
    "post_trade",
    "general",
}
_ALLOWED_EPISODE_STATUSES = {"active", "complete", "wait", "archived"}


def _storage() -> StorageProvider:
    return get_storage_provider(get_settings())


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _timestamp(value: datetime | None) -> str | None:
    return _as_utc(value).isoformat() if value else None


def _parse_timestamp(value: Any, field: str, *, default: datetime | None = None) -> datetime:
    if value in (None, ""):
        if default is not None:
            return _as_utc(default)
        raise HTTPException(status_code=422, detail=f"{field} is required.")
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"{field} must be ISO-8601.") from exc
    if parsed.tzinfo is None:
        raise HTTPException(status_code=422, detail=f"{field} must include a timezone.")
    return parsed.astimezone(timezone.utc)


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


def _parse_side(value: Any) -> str | None:
    side = str(value).strip().lower() if value else None
    if side is not None and side not in _ALLOWED_SIDES:
        raise HTTPException(status_code=422, detail="side must be long, short, or null.")
    return side


def _parse_metadata(raw: str) -> dict[str, Any]:
    """Parse the original screenshot-first Companion payload."""
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

    side = _parse_side(data.get("side"))
    symbol_raw = data.get("symbol")
    symbol = str(symbol_raw).strip().upper()[:80] if symbol_raw else None
    if event_type != "wait" and not symbol:
        raise HTTPException(status_code=422, detail="symbol is required unless event_type is wait.")

    captured_at = _parse_timestamp(data.get("captured_at"), "captured_at")

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
        "captured_at": captured_at,
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


def _parse_moment_metadata(raw: str) -> dict[str, Any]:
    """Parse timeline-first capture data. Everything except timestamp is optional."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail="metadata must be valid JSON.") from exc
    if not isinstance(data, dict):
        raise HTTPException(status_code=422, detail="metadata must be a JSON object.")

    phase_raw = str(data.get("phase") or "").strip().lower().replace("-", "_")
    phase = phase_raw or None
    if phase is not None and phase not in _ALLOWED_PHASES:
        raise HTTPException(
            status_code=422,
            detail="phase must be pre_entry, confirmation, entry, management, exit, wait, post_trade, general, or null.",
        )

    event_type = str(data.get("event_type") or "").strip().lower()
    if not event_type:
        event_type = {
            "entry": "entry",
            "exit": "exit",
            "wait": "wait",
        }.get(phase, "update")
    if event_type not in _ALLOWED_EVENT_TYPES:
        raise HTTPException(status_code=422, detail="event_type must be entry, exit, update, or wait.")

    account_id = None
    if data.get("account_id"):
        try:
            account_id = UUID(str(data["account_id"]))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="account_id must be a UUID.") from exc

    episode_id = None
    if data.get("episode_id"):
        try:
            episode_id = UUID(str(data["episode_id"]))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="episode_id must be a UUID.") from exc

    note = str(data.get("note") or "").strip() or None
    if note and len(note) > 1000:
        raise HTTPException(status_code=422, detail="note may contain at most 1000 characters.")

    symbol_raw = data.get("symbol")
    symbol = str(symbol_raw).strip().upper()[:80] if symbol_raw else None

    return {
        "episode_id": episode_id,
        "captured_at": _parse_timestamp(data.get("captured_at"), "captured_at", default=utcnow()),
        "event_type": event_type,
        "phase": phase,
        "recorded_live": bool(data.get("recorded_live", True)),
        "account_id": account_id,
        "symbol": symbol,
        "side": _parse_side(data.get("side")),
        "note": note,
        "setup_tags_json": _clean_tags(data.get("setup_tags"), "setup_tags"),
        "execution_tags_json": _clean_tags(data.get("execution_tags"), "execution_tags"),
        "emotion_tags_json": _clean_tags(data.get("emotion_tags"), "emotion_tags"),
        "platform": str(data.get("platform") or "").strip()[:80] or None,
        "page_url": str(data.get("page_url") or "").strip()[:2048] or None,
        "page_title": str(data.get("page_title") or "").strip()[:500] or None,
        "source": str(data.get("source") or "journalme_companion").strip()[:80],
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


def _owned_episode_or_404(db: Session, user: User, episode_id: UUID) -> TradingEpisode:
    episode = db.scalar(
        select(TradingEpisode).where(
            TradingEpisode.id == episode_id,
            TradingEpisode.user_id == user.id,
        )
    )
    if episode is None:
        raise HTTPException(status_code=404, detail="Trading episode not found.")
    return episode


def _capture_dict(item: CaptureEvent) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "episode_id": str(item.episode_id) if item.episode_id else None,
        "account_id": str(item.account_id) if item.account_id else None,
        "captured_at": _timestamp(item.captured_at),
        "created_at": _timestamp(item.created_at),
        "event_type": item.event_type,
        "phase": item.phase,
        "recorded_live": bool(item.recorded_live),
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
        "has_screenshot": bool(item.screenshot_storage_key),
        "screenshot_url": (
            f"{get_settings().api_prefix}/captures/{item.id}/screenshot"
            if item.screenshot_storage_key
            else None
        ),
    }


def _episode_dict(db: Session, item: TradingEpisode, *, include_moments: bool = False) -> dict[str, Any]:
    moment_query = (
        select(CaptureEvent)
        .where(CaptureEvent.episode_id == item.id)
        .order_by(CaptureEvent.captured_at.asc(), CaptureEvent.created_at.asc())
    )
    moments = list(db.scalars(moment_query).all())
    last = moments[-1] if moments else None
    matched_trade = db.get(Trade, item.matched_trade_id) if item.matched_trade_id else None
    payload: dict[str, Any] = {
        "id": str(item.id),
        "account_id": str(item.account_id) if item.account_id else None,
        "symbol": item.symbol,
        "side": item.side,
        "title": item.title,
        "status": item.status,
        "source": item.source,
        "started_at": _timestamp(item.started_at),
        "ended_at": _timestamp(item.ended_at),
        "created_at": _timestamp(item.created_at),
        "updated_at": _timestamp(item.updated_at),
        "matched_trade_id": str(item.matched_trade_id) if item.matched_trade_id else None,
        "moment_count": len(moments),
        "screenshot_count": sum(1 for moment in moments if moment.screenshot_storage_key),
        "last_moment_at": _timestamp(last.captured_at) if last else None,
        "last_note": last.note if last else None,
        "matched_trade": (
            {
                "id": str(matched_trade.id),
                "symbol": matched_trade.symbol,
                "side": matched_trade.side.value if hasattr(matched_trade.side, "value") else str(matched_trade.side),
                "net_pnl": str(matched_trade.net_pnl),
                "entry_timestamp": _timestamp(matched_trade.entry_timestamp),
                "exit_timestamp": _timestamp(matched_trade.exit_timestamp),
            }
            if matched_trade
            else None
        ),
    }
    if include_moments:
        payload["moments"] = [_capture_dict(moment) for moment in moments]
    return payload


async def _store_screenshot(
    screenshot: UploadFile | None,
    capture_id: UUID,
) -> tuple[str | None, str | None, str | None]:
    if screenshot is None:
        return None, None, None
    mime_type = (screenshot.content_type or "").lower()
    if mime_type not in _ALLOWED_IMAGE_TYPES:
        raise HTTPException(status_code=415, detail="Screenshot must be PNG, JPEG, or WebP.")
    content = await screenshot.read()
    if not content:
        raise HTTPException(status_code=422, detail="Screenshot is empty.")
    if len(content) > get_settings().max_upload_bytes:
        raise HTTPException(status_code=413, detail="Screenshot exceeds the upload limit.")
    suffix = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}[mime_type]
    original = Path(screenshot.filename or f"capture{suffix}").name
    if Path(original).suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
        original = f"capture{suffix}"
    storage_key = _storage().put(capture_id, original, content)
    return storage_key, original, mime_type


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_capture(
    db: Db,
    user: CurrentUser,
    metadata: Annotated[str, Form()],
    screenshot: Annotated[UploadFile, File()],
) -> dict[str, Any]:
    """Backward-compatible screenshot-first capture endpoint."""
    data = _parse_metadata(metadata)
    data["account_id"] = _resolve_capture_account_id(db, user, data["account_id"])

    capture_id = uuid4()
    storage_key, original, mime_type = await _store_screenshot(screenshot, capture_id)
    capture = CaptureEvent(
        id=capture_id,
        user_id=user.id,
        account_id=data["account_id"],
        captured_at=data["captured_at"],
        event_type=data["event_type"],
        phase=None,
        recorded_live=True,
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


@router.post("/episodes", status_code=status.HTTP_201_CREATED)
def create_episode(
    db: Db,
    user: CurrentUser,
    payload: Annotated[dict[str, Any], Body(default_factory=dict)],
) -> dict[str, Any]:
    account_id_raw = payload.get("account_id")
    account_id: UUID | None = None
    if account_id_raw:
        try:
            account_id = UUID(str(account_id_raw))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="account_id must be a UUID.") from exc
    account_id = _resolve_capture_account_id(db, user, account_id)

    symbol = str(payload.get("symbol") or "").strip().upper()[:80] or None
    side = _parse_side(payload.get("side"))
    title = str(payload.get("title") or "").strip()[:240] or None
    source = str(payload.get("source") or "journalme_companion").strip()[:80]
    started_at = _parse_timestamp(payload.get("started_at"), "started_at", default=utcnow())

    episode = TradingEpisode(
        user_id=user.id,
        account_id=account_id,
        symbol=symbol,
        side=side,
        title=title,
        status="active",
        source=source,
        started_at=started_at,
    )
    db.add(episode)
    db.commit()
    db.refresh(episode)
    return _episode_dict(db, episode, include_moments=True)


@router.get("/episodes")
def list_episodes(
    db: Db,
    user: CurrentUser,
    limit: int = Query(default=12, ge=1, le=100),
    account_id: UUID | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
) -> list[dict[str, Any]]:
    query = select(TradingEpisode).where(TradingEpisode.user_id == user.id)
    if account_id is not None:
        _resolve_capture_account_id(db, user, account_id)
        query = query.where(TradingEpisode.account_id == account_id)
    if status_filter:
        if status_filter not in _ALLOWED_EPISODE_STATUSES:
            raise HTTPException(status_code=422, detail="Unknown episode status.")
        query = query.where(TradingEpisode.status == status_filter)
    rows = db.scalars(query.order_by(TradingEpisode.updated_at.desc()).limit(limit)).all()
    return [_episode_dict(db, item) for item in rows]


@router.get("/episodes/active")
def active_episode(
    db: Db,
    user: CurrentUser,
    account_id: UUID | None = Query(default=None),
) -> dict[str, Any] | None:
    query = select(TradingEpisode).where(
        TradingEpisode.user_id == user.id,
        TradingEpisode.status == "active",
    )
    if account_id is not None:
        _resolve_capture_account_id(db, user, account_id)
        query = query.where(TradingEpisode.account_id == account_id)
    item = db.scalar(query.order_by(TradingEpisode.updated_at.desc()).limit(1))
    return _episode_dict(db, item, include_moments=True) if item else None


@router.get("/episodes/{episode_id}")
def episode_detail(episode_id: UUID, db: Db, user: CurrentUser) -> dict[str, Any]:
    return _episode_dict(db, _owned_episode_or_404(db, user, episode_id), include_moments=True)


@router.patch("/episodes/{episode_id}")
def update_episode(
    episode_id: UUID,
    db: Db,
    user: CurrentUser,
    payload: Annotated[dict[str, Any], Body(default_factory=dict)],
) -> dict[str, Any]:
    episode = _owned_episode_or_404(db, user, episode_id)
    if "account_id" in payload:
        raw = payload.get("account_id")
        parsed = UUID(str(raw)) if raw else None
        episode.account_id = _resolve_capture_account_id(db, user, parsed)
    if "symbol" in payload:
        episode.symbol = str(payload.get("symbol") or "").strip().upper()[:80] or None
    if "side" in payload:
        episode.side = _parse_side(payload.get("side"))
    if "title" in payload:
        episode.title = str(payload.get("title") or "").strip()[:240] or None
    if "status" in payload:
        next_status = str(payload.get("status") or "").strip().lower()
        if next_status not in _ALLOWED_EPISODE_STATUSES:
            raise HTTPException(status_code=422, detail="Unknown episode status.")
        episode.status = next_status
        if next_status != "active" and episode.ended_at is None:
            episode.ended_at = utcnow()
        elif next_status == "active":
            episode.ended_at = None
    episode.updated_at = utcnow()
    db.commit()
    db.refresh(episode)
    return _episode_dict(db, episode, include_moments=True)


@router.post("/episodes/{episode_id}/complete")
def complete_episode(episode_id: UUID, db: Db, user: CurrentUser) -> dict[str, Any]:
    episode = _owned_episode_or_404(db, user, episode_id)
    episode.status = "complete"
    episode.ended_at = episode.ended_at or utcnow()
    episode.updated_at = utcnow()
    db.commit()
    db.refresh(episode)
    return _episode_dict(db, episode, include_moments=True)


@router.post("/moments", status_code=status.HTTP_201_CREATED)
async def create_moment(
    db: Db,
    user: CurrentUser,
    metadata: Annotated[str, Form()],
    screenshot: Annotated[UploadFile | None, File()] = None,
) -> dict[str, Any]:
    """Create one optional-screenshot timeline update, automatically starting an episode when needed."""
    data = _parse_moment_metadata(metadata)

    episode: TradingEpisode | None = None
    if data["episode_id"] is not None:
        episode = _owned_episode_or_404(db, user, data["episode_id"])

    requested_account_id = data["account_id"] or (episode.account_id if episode else None)
    account_id = _resolve_capture_account_id(db, user, requested_account_id)
    symbol = data["symbol"] or (episode.symbol if episode else None)
    side = data["side"] or (episode.side if episode else None)

    has_content = bool(
        screenshot
        or data["note"]
        or data["setup_tags_json"]
        or data["execution_tags_json"]
        or data["emotion_tags_json"]
    )
    if not has_content:
        raise HTTPException(status_code=422, detail="Add a thought, tag, or screenshot before saving the moment.")

    if episode is None:
        episode = TradingEpisode(
            user_id=user.id,
            account_id=account_id,
            symbol=symbol,
            side=side,
            status="active",
            source=data["source"],
            started_at=data["captured_at"],
        )
        db.add(episode)
        db.flush()
    else:
        if episode.status != "active":
            raise HTTPException(status_code=409, detail="This episode is already complete. Start a new episode for another idea.")
        if episode.account_id is None and account_id is not None:
            episode.account_id = account_id
        if not episode.symbol and symbol:
            episode.symbol = symbol
        if not episode.side and side:
            episode.side = side
        if data["captured_at"] < _as_utc(episode.started_at):
            episode.started_at = data["captured_at"]

    capture_id = uuid4()
    storage_key, original, mime_type = await _store_screenshot(screenshot, capture_id)
    capture = CaptureEvent(
        id=capture_id,
        user_id=user.id,
        account_id=account_id,
        episode_id=episode.id,
        captured_at=data["captured_at"],
        event_type=data["event_type"],
        phase=data["phase"],
        recorded_live=data["recorded_live"],
        symbol=symbol,
        side=side,
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

    if capture.matched_trade_id and episode.matched_trade_id is None:
        episode.matched_trade_id = capture.matched_trade_id
    episode.updated_at = utcnow()
    if data["phase"] == "exit":
        episode.status = "complete"
        episode.ended_at = data["captured_at"]
    elif data["phase"] == "wait":
        episode.status = "wait"
        episode.ended_at = data["captured_at"]

    db.commit()
    db.refresh(capture)
    db.refresh(episode)
    return {
        **_capture_dict(capture),
        "episode": _episode_dict(db, episode, include_moments=True),
    }


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
    rows = db.scalars(query.order_by(CaptureEvent.captured_at.desc()).limit(limit)).all()
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

    # If a moment matched after a later broker sync/import, carry that match to its episode.
    matched_rows = db.execute(
        select(CaptureEvent.episode_id, CaptureEvent.matched_trade_id)
        .where(
            CaptureEvent.user_id == user.id,
            CaptureEvent.episode_id.is_not(None),
            CaptureEvent.matched_trade_id.is_not(None),
        )
        .order_by(CaptureEvent.captured_at.asc())
    ).all()
    for episode_id, trade_id in matched_rows:
        episode = db.get(TradingEpisode, episode_id)
        if episode is not None and episode.user_id == user.id and episode.matched_trade_id is None:
            episode.matched_trade_id = trade_id
            episode.updated_at = utcnow()
    db.commit()
    return stats


@router.post("/{capture_id}/match/{trade_id}")
def match_capture_manually(
    capture_id: UUID, trade_id: UUID, db: Db, user: CurrentUser
) -> dict[str, Any]:
    capture = _owned_capture_or_404(db, user, capture_id)
    trade = _owned_trade_or_404(db, user, trade_id)
    force_match_capture(db, capture, trade, score=1.0, method="manual")
    if capture.episode_id:
        episode = db.get(TradingEpisode, capture.episode_id)
        if episode and episode.user_id == user.id and episode.matched_trade_id is None:
            episode.matched_trade_id = trade.id
            episode.updated_at = utcnow()
    db.commit()
    db.refresh(capture)
    return _capture_dict(capture)


@router.post("/{capture_id}/unmatch")
def unmatch_capture(capture_id: UUID, db: Db, user: CurrentUser) -> dict[str, Any]:
    capture = _owned_capture_or_404(db, user, capture_id)
    clear_capture_match(db, capture)
    db.commit()
    db.refresh(capture)
    return _capture_dict(capture)


@router.delete("/{capture_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_capture(capture_id: UUID, db: Db, user: CurrentUser) -> Response:
    capture = _owned_capture_or_404(db, user, capture_id)
    if capture.screenshot_storage_key:
        _storage().delete(capture.screenshot_storage_key)
    episode_id = capture.episode_id
    db.delete(capture)
    db.flush()
    if episode_id is not None:
        remaining = db.scalar(
            select(func.count()).select_from(CaptureEvent).where(CaptureEvent.episode_id == episode_id)
        ) or 0
        if remaining == 0:
            episode = db.get(TradingEpisode, episode_id)
            if episode is not None and episode.user_id == user.id:
                db.delete(episode)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{capture_id}/screenshot")
def capture_screenshot(capture_id: UUID, db: Db, user: CurrentUser) -> Response:
    capture = _owned_capture_or_404(db, user, capture_id)
    if not capture.screenshot_storage_key or not capture.screenshot_mime:
        raise HTTPException(status_code=404, detail="This moment has no screenshot.")
    try:
        content = _storage().get(capture.screenshot_storage_key)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Screenshot not found.") from exc
    return Response(
        content=content,
        media_type=capture.screenshot_mime,
        headers={"Cache-Control": "private, max-age=3600"},
    )
